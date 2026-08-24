"""Session state and bankroll tracking for a human playing by hand.

This module is deliberately free of any game logic or RNG: the human plays on
whatever surface they like, and reports each resolved bet here as

    ``(game, config, stake, outcome multiplier, timestamp)``

where the multiplier is the *total return* multiple ("for one"): a lost bet is
``0``, an even-money win is ``2``, a blackjack push is ``1``, a 3:2 blackjack
win is ``2.5``, etc.  The session keeps the authoritative bankroll ledger.

Design points
-------------

- **Decimal-safe money.**  All money amounts (stakes, payouts, bankroll,
  P&L, drawdown) are :class:`decimal.Decimal` quantized to whole cents.
  ``float`` inputs are accepted for convenience but are converted through
  ``str`` so ``0.1`` means ``Decimal("0.1")``, never
  ``0.1000000000000000055511151231257827``.  Stakes must be exact cent
  amounts; payouts are quantized to the cent with ROUND_HALF_UP at the moment
  they are credited, and every subsequent aggregate is a sum of exact cents —
  no float ever touches the ledger.
- **Stop triggers are advisory.**  Stop-loss / stop-win (absolute and
  percent-of-starting-bankroll) are evaluated after *every* recorded bet.
  The first trigger latches (:attr:`Session.stop_reason`,
  :attr:`Session.stopped`, the triggering bet's sequence number) but
  recording is not blocked: a human who keeps playing past their own stop
  still deserves an accurate ledger.  ``record_bet`` returns the record and
  the session exposes :attr:`Session.stopped` so a UI/report layer can nag.
- **JSONL persistence, append-safe and reload-safe.**  When constructed with
  ``jsonl_path``, the session writes one ``session_start`` header line and
  then appends one line per bet, flushing after each append.  ``Session.load``
  replays the file back into an identical live session (which keeps appending
  to the same file).  A torn final line (crash mid-append) is ignored on
  load; corruption anywhere else raises.  A file may contain several
  ``session_start`` headers (a fresh session pointed at an old file); load
  replays the last one.
- **No UI.**  ``summary()`` returns a JSON-serializable dict and
  ``to_dataframe()`` hands the bet history to the report layer.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, IO, List, Mapping, Optional, Union

import pandas as pd

__all__ = [
    "CENT",
    "MoneyError",
    "BetRecord",
    "Session",
]

CENT = Decimal("0.01")

MoneyLike = Union[Decimal, int, str, float]


class MoneyError(ValueError):
    """Raised for invalid money inputs (sub-cent stakes, negatives, floats
    that do not represent exact values, etc.)."""


def _to_decimal(value: MoneyLike, *, name: str) -> Decimal:
    """Convert a user-supplied number to Decimal without float drift.

    Floats go through ``str`` so the *printed* value is honored (``0.1`` ->
    ``Decimal("0.1")``).  NaN/inf are rejected.
    """
    if isinstance(value, bool):
        raise MoneyError(f"{name} must be a number, got bool")
    if isinstance(value, Decimal):
        dec = value
    elif isinstance(value, int):
        dec = Decimal(value)
    elif isinstance(value, float):
        dec = Decimal(str(value))
    elif isinstance(value, str):
        try:
            dec = Decimal(value)
        except InvalidOperation as exc:
            raise MoneyError(f"{name} is not a valid number: {value!r}") from exc
    else:
        raise MoneyError(f"{name} must be Decimal/int/str/float, got {type(value).__name__}")
    if not dec.is_finite():
        raise MoneyError(f"{name} must be finite, got {dec}")
    return dec


def _to_money(value: MoneyLike, *, name: str) -> Decimal:
    """Convert to an exact cent amount; sub-cent precision is an error."""
    dec = _to_decimal(value, name=name)
    quantized = dec.quantize(CENT)
    if quantized != dec:
        raise MoneyError(f"{name} must be an exact cent amount, got {dec}")
    return quantized


def _money_str(value: Decimal) -> str:
    """Canonical two-decimal string for a cent amount ('12.30', '-0.50')."""
    return str(value.quantize(CENT))


def _timestamp_str(timestamp: Union[str, datetime, date]) -> str:
    """Normalize a caller-supplied timestamp to a string (ISO for datetimes)."""
    if isinstance(timestamp, str):
        if not timestamp:
            raise ValueError("timestamp must be non-empty")
        return timestamp
    if isinstance(timestamp, (datetime, date)):
        return timestamp.isoformat()
    raise TypeError(
        f"timestamp must be str/datetime/date supplied by the caller, "
        f"got {type(timestamp).__name__}"
    )


@dataclass(frozen=True)
class BetRecord:
    """One resolved bet, as recorded.  All money fields are exact cents."""

    seq: int                      # 1-based sequence number within the session
    timestamp: str                # caller-supplied, normalized to str
    game: str
    config: Dict[str, Any]        # game configuration (JSON-serializable)
    stake: Decimal                # amount wagered (> 0, exact cents)
    multiplier: Decimal           # total-return multiple, >= 0 ("for one")
    payout: Decimal               # stake * multiplier, quantized to cents
    net: Decimal                  # payout - stake
    bankroll_after: Decimal       # ledger balance after this bet settled

    def to_json_dict(self) -> Dict[str, Any]:
        """JSON-serializable form (money as canonical strings)."""
        return {
            "type": "bet",
            "seq": self.seq,
            "timestamp": self.timestamp,
            "game": self.game,
            "config": self.config,
            "stake": _money_str(self.stake),
            "multiplier": str(self.multiplier),
            "payout": _money_str(self.payout),
            "net": _money_str(self.net),
            "bankroll_after": _money_str(self.bankroll_after),
        }


@dataclass
class _GameStats:
    bets: int = 0
    total_staked: Decimal = field(default_factory=lambda: Decimal("0.00"))
    total_returned: Decimal = field(default_factory=lambda: Decimal("0.00"))
    wins: int = 0     # payout > stake
    pushes: int = 0   # payout == stake
    losses: int = 0   # payout < stake

    @property
    def net(self) -> Decimal:
        return self.total_returned - self.total_staked


class Session:
    """Bankroll ledger for one human play session.

    Parameters
    ----------
    starting_bankroll:
        Exact cent amount, > 0.
    stop_loss:
        Absolute stop-loss: latch a stop once cumulative P&L <= -stop_loss.
        Positive cent amount.
    stop_win:
        Absolute stop-win: latch once P&L >= stop_win.  Positive cent amount.
    stop_loss_pct / stop_win_pct:
        Percent-of-starting-bankroll variants, given as fractions in (0, 1]
        for loss and (0, inf) for win (0.25 == 25%).  Both an absolute and a
        percent trigger may be armed; whichever threshold is crossed first
        latches (evaluated after every bet, loss checked before win).
    jsonl_path:
        Optional path for append-only JSONL persistence.  The header line is
        written immediately (parent directory must exist).
    allow_negative_bankroll:
        By default a stake larger than the current bankroll is rejected
        (MoneyError) — the ledger cannot cover it.  Set True to permit
        (e.g. tracking a bankroll the human is willing to reload).
    """

    def __init__(
        self,
        starting_bankroll: MoneyLike,
        *,
        stop_loss: Optional[MoneyLike] = None,
        stop_win: Optional[MoneyLike] = None,
        stop_loss_pct: Optional[MoneyLike] = None,
        stop_win_pct: Optional[MoneyLike] = None,
        jsonl_path: Optional[Union[str, os.PathLike]] = None,
        allow_negative_bankroll: bool = False,
        session_id: Optional[str] = None,
        _defer_header: bool = False,
    ) -> None:
        self.starting_bankroll = _to_money(starting_bankroll, name="starting_bankroll")
        if self.starting_bankroll <= 0:
            raise MoneyError("starting_bankroll must be > 0")

        self.stop_loss = self._check_stop(stop_loss, "stop_loss")
        self.stop_win = self._check_stop(stop_win, "stop_win")
        self.stop_loss_pct = self._check_pct(stop_loss_pct, "stop_loss_pct", cap_at_one=True)
        self.stop_win_pct = self._check_pct(stop_win_pct, "stop_win_pct", cap_at_one=False)

        self.session_id = session_id or uuid.uuid4().hex
        self.allow_negative_bankroll = bool(allow_negative_bankroll)

        self.bankroll = self.starting_bankroll
        self.peak_bankroll = self.starting_bankroll
        self.max_drawdown = Decimal("0.00")          # peak-to-trough, >= 0
        self.max_drawdown_pct = Decimal("0")         # fraction of peak at the time
        self.bets: List[BetRecord] = []
        self.per_game: Dict[str, _GameStats] = {}

        self.stopped = False
        self.stop_reason: Optional[str] = None       # e.g. "stop_loss", "stop_win_pct"
        self.stop_seq: Optional[int] = None          # seq of the latching bet

        self._jsonl_path = os.fspath(jsonl_path) if jsonl_path is not None else None
        if self._jsonl_path is not None and not _defer_header:
            self._append_line(self._header_dict())

    # ------------------------------------------------------------------ init helpers

    @staticmethod
    def _check_stop(value: Optional[MoneyLike], name: str) -> Optional[Decimal]:
        if value is None:
            return None
        dec = _to_money(value, name=name)
        if dec <= 0:
            raise MoneyError(f"{name} must be > 0")
        return dec

    @staticmethod
    def _check_pct(value: Optional[MoneyLike], name: str, *, cap_at_one: bool) -> Optional[Decimal]:
        if value is None:
            return None
        dec = _to_decimal(value, name=name)
        if dec <= 0:
            raise MoneyError(f"{name} must be > 0 (a fraction, e.g. 0.25 for 25%)")
        if cap_at_one and dec > 1:
            raise MoneyError(f"{name} cannot exceed 1 (you cannot lose more than 100%)")
        return dec

    # ------------------------------------------------------------------ properties

    @property
    def pnl(self) -> Decimal:
        """Cumulative profit/loss vs the starting bankroll (exact cents)."""
        return self.bankroll - self.starting_bankroll

    @property
    def total_staked(self) -> Decimal:
        return sum((g.total_staked for g in self.per_game.values()), Decimal("0.00"))

    @property
    def total_returned(self) -> Decimal:
        return sum((g.total_returned for g in self.per_game.values()), Decimal("0.00"))

    @property
    def jsonl_path(self) -> Optional[str]:
        return self._jsonl_path

    # ------------------------------------------------------------------ recording

    def record_bet(
        self,
        game: str,
        config: Optional[Mapping[str, Any]],
        stake: MoneyLike,
        multiplier: MoneyLike,
        timestamp: Union[str, datetime, date],
    ) -> BetRecord:
        """Record one resolved bet; returns the immutable :class:`BetRecord`.

        ``multiplier`` is the total-return multiple (0 = lost, 1 = push,
        2 = even-money win, ...).  The payout is ``stake * multiplier``
        quantized to the cent (ROUND_HALF_UP).  Stop triggers are evaluated
        after the bet settles; a latched stop does not block recording.
        """
        if not isinstance(game, str) or not game:
            raise ValueError("game must be a non-empty string")
        ts = _timestamp_str(timestamp)

        stake_d = _to_money(stake, name="stake")
        if stake_d <= 0:
            raise MoneyError("stake must be > 0")
        if not self.allow_negative_bankroll and stake_d > self.bankroll:
            raise MoneyError(
                f"stake {_money_str(stake_d)} exceeds bankroll {_money_str(self.bankroll)}"
            )

        mult_d = _to_decimal(multiplier, name="multiplier")
        if mult_d < 0:
            raise MoneyError("multiplier must be >= 0 (it is a total-return multiple)")

        cfg: Dict[str, Any] = dict(config) if config else {}
        # Fail fast (before mutating state) if the config can't be persisted.
        try:
            json.dumps(cfg)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"config must be JSON-serializable: {exc}") from exc

        payout = (stake_d * mult_d).quantize(CENT, rounding=ROUND_HALF_UP)
        net = payout - stake_d

        self.bankroll += net
        record = BetRecord(
            seq=len(self.bets) + 1,
            timestamp=ts,
            game=game,
            config=cfg,
            stake=stake_d,
            multiplier=mult_d,
            payout=payout,
            net=net,
            bankroll_after=self.bankroll,
        )
        self.bets.append(record)
        self._update_aggregates(record)
        self._evaluate_stops(record)
        if self._jsonl_path is not None:
            self._append_line(record.to_json_dict())
        return record

    def _update_aggregates(self, record: BetRecord) -> None:
        if self.bankroll > self.peak_bankroll:
            self.peak_bankroll = self.bankroll
        drawdown = self.peak_bankroll - self.bankroll
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown
            self.max_drawdown_pct = (
                drawdown / self.peak_bankroll if self.peak_bankroll > 0 else Decimal("0")
            )
        stats = self.per_game.setdefault(record.game, _GameStats())
        stats.bets += 1
        stats.total_staked += record.stake
        stats.total_returned += record.payout
        if record.payout > record.stake:
            stats.wins += 1
        elif record.payout == record.stake:
            stats.pushes += 1
        else:
            stats.losses += 1

    def _evaluate_stops(self, record: BetRecord) -> None:
        if self.stopped:
            return
        pnl = self.pnl
        loss_thresholds: List[tuple] = []
        if self.stop_loss is not None:
            loss_thresholds.append(("stop_loss", -self.stop_loss))
        if self.stop_loss_pct is not None:
            loss_thresholds.append(("stop_loss_pct", -(self.starting_bankroll * self.stop_loss_pct)))
        for reason, threshold in loss_thresholds:
            if pnl <= threshold:
                self.stopped, self.stop_reason, self.stop_seq = True, reason, record.seq
                return
        win_thresholds: List[tuple] = []
        if self.stop_win is not None:
            win_thresholds.append(("stop_win", self.stop_win))
        if self.stop_win_pct is not None:
            win_thresholds.append(("stop_win_pct", self.starting_bankroll * self.stop_win_pct))
        for reason, threshold in win_thresholds:
            if pnl >= threshold:
                self.stopped, self.stop_reason, self.stop_seq = True, reason, record.seq
                return

    # ------------------------------------------------------------------ summary / export

    def per_game_breakdown(self) -> Dict[str, Dict[str, Any]]:
        """Per-game stats with money as canonical strings (JSON-safe)."""
        out: Dict[str, Dict[str, Any]] = {}
        for game in sorted(self.per_game):
            g = self.per_game[game]
            out[game] = {
                "bets": g.bets,
                "wins": g.wins,
                "pushes": g.pushes,
                "losses": g.losses,
                "total_staked": _money_str(g.total_staked),
                "total_returned": _money_str(g.total_returned),
                "net": _money_str(g.net),
            }
        return out

    def summary(self) -> Dict[str, Any]:
        """Full session summary as a JSON-serializable dict."""
        first_ts = self.bets[0].timestamp if self.bets else None
        last_ts = self.bets[-1].timestamp if self.bets else None
        return {
            "session_id": self.session_id,
            "starting_bankroll": _money_str(self.starting_bankroll),
            "bankroll": _money_str(self.bankroll),
            "pnl": _money_str(self.pnl),
            "peak_bankroll": _money_str(self.peak_bankroll),
            "max_drawdown": _money_str(self.max_drawdown),
            "max_drawdown_pct": str(self.max_drawdown_pct),
            "total_bets": len(self.bets),
            "total_staked": _money_str(self.total_staked),
            "total_returned": _money_str(self.total_returned),
            "first_bet_at": first_ts,
            "last_bet_at": last_ts,
            "stopped": self.stopped,
            "stop_reason": self.stop_reason,
            "stop_seq": self.stop_seq,
            "stops": {
                "stop_loss": _money_str(self.stop_loss) if self.stop_loss is not None else None,
                "stop_win": _money_str(self.stop_win) if self.stop_win is not None else None,
                "stop_loss_pct": str(self.stop_loss_pct) if self.stop_loss_pct is not None else None,
                "stop_win_pct": str(self.stop_win_pct) if self.stop_win_pct is not None else None,
            },
            "per_game": self.per_game_breakdown(),
        }

    def to_dataframe(self) -> pd.DataFrame:
        """Bet history as a pandas DataFrame for the report layer.

        Money columns come out as ``float`` (converted from the exact Decimal
        values, so each is within one float ulp of the true cents); the
        Decimal ledger in :attr:`bets` remains the source of truth.  ``config``
        is carried as its canonical JSON string in ``config_json``.
        """
        columns = [
            "seq", "timestamp", "game", "config_json",
            "stake", "multiplier", "payout", "net", "bankroll_after",
        ]
        rows = [
            {
                "seq": b.seq,
                "timestamp": b.timestamp,
                "game": b.game,
                "config_json": json.dumps(b.config, sort_keys=True),
                "stake": float(b.stake),
                "multiplier": float(b.multiplier),
                "payout": float(b.payout),
                "net": float(b.net),
                "bankroll_after": float(b.bankroll_after),
            }
            for b in self.bets
        ]
        df = pd.DataFrame(rows, columns=columns)
        if not rows:  # keep dtypes sane for the empty frame
            df = df.astype(
                {
                    "seq": "int64", "stake": "float64", "multiplier": "float64",
                    "payout": "float64", "net": "float64", "bankroll_after": "float64",
                }
            )
        return df

    # ------------------------------------------------------------------ persistence

    def _header_dict(self) -> Dict[str, Any]:
        return {
            "type": "session_start",
            "session_id": self.session_id,
            "starting_bankroll": _money_str(self.starting_bankroll),
            "stop_loss": _money_str(self.stop_loss) if self.stop_loss is not None else None,
            "stop_win": _money_str(self.stop_win) if self.stop_win is not None else None,
            "stop_loss_pct": str(self.stop_loss_pct) if self.stop_loss_pct is not None else None,
            "stop_win_pct": str(self.stop_win_pct) if self.stop_win_pct is not None else None,
            "allow_negative_bankroll": self.allow_negative_bankroll,
        }

    def _append_line(self, obj: Dict[str, Any]) -> None:
        line = json.dumps(obj, sort_keys=True, separators=(",", ":"))
        with open(self._jsonl_path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    @classmethod
    def load(cls, jsonl_path: Union[str, os.PathLike]) -> "Session":
        """Reload a session from its JSONL file and keep appending to it.

        Replays the *last* ``session_start`` header and every bet after it.
        A torn (unparseable or truncated) final line is ignored — the append
        may have been interrupted; corruption anywhere else raises
        ``ValueError``.  The replayed state (bankroll, P&L, peak, drawdown,
        stops, per-game stats) is verified against the persisted
        ``bankroll_after`` of each bet.
        """
        path = os.fspath(jsonl_path)
        with open(path, "r", encoding="utf-8") as fh:
            raw_lines = fh.read().split("\n")
        # A well-formed file ends with "\n" -> last split element is "".
        if raw_lines and raw_lines[-1] == "":
            raw_lines.pop()
        parsed: List[Dict[str, Any]] = []
        for i, line in enumerate(raw_lines):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                if i == len(raw_lines) - 1:
                    break  # torn final append; ignore
                raise ValueError(f"{path}: corrupt JSONL at line {i + 1}")
            if not isinstance(obj, dict) or "type" not in obj:
                raise ValueError(f"{path}: line {i + 1} is not a session record")
            parsed.append(obj)

        start_idx = max(
            (i for i, obj in enumerate(parsed) if obj["type"] == "session_start"),
            default=None,
        )
        if start_idx is None:
            raise ValueError(f"{path}: no session_start header found")
        header = parsed[start_idx]

        session = cls(
            header["starting_bankroll"],
            stop_loss=header.get("stop_loss"),
            stop_win=header.get("stop_win"),
            stop_loss_pct=header.get("stop_loss_pct"),
            stop_win_pct=header.get("stop_win_pct"),
            jsonl_path=path,
            allow_negative_bankroll=header.get("allow_negative_bankroll", False),
            session_id=header.get("session_id"),
            _defer_header=True,  # header already on disk; do not duplicate
        )
        # Replay without re-appending.
        session._jsonl_path = None
        try:
            for obj in parsed[start_idx + 1:]:
                if obj["type"] != "bet":
                    raise ValueError(f"{path}: unknown record type {obj['type']!r}")
                record = session.record_bet(
                    obj["game"],
                    obj.get("config") or {},
                    obj["stake"],
                    obj["multiplier"],
                    obj["timestamp"],
                )
                persisted_after = _to_money(obj["bankroll_after"], name="bankroll_after")
                if record.bankroll_after != persisted_after:
                    raise ValueError(
                        f"{path}: replay mismatch at seq {record.seq}: "
                        f"replayed bankroll {_money_str(record.bankroll_after)} "
                        f"!= persisted {obj['bankroll_after']}"
                    )
        finally:
            session._jsonl_path = path
        return session
