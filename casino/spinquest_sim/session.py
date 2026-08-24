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
  no float ever touches the ledger.  Negative zero is normalized away, and
  magnitudes too large to quantize raise :class:`MoneyError` (never a raw
  ``decimal.InvalidOperation``).
- **Drawdown is measured on the gambling equity curve.**  Drawdown statistics
  are computed on the *equity* curve — the bankroll with deposits and
  withdrawals backed out (``starting_bankroll + cumulative bet net``) — so a
  deposit can neither erase nor shrink a drawdown, a withdrawal can neither
  fabricate nor inflate one (in dollars *and* in percent), and
  :attr:`Session.peak_bankroll` (the equity peak) is always positive.  For a
  session with no cash flows the equity curve *is* the bankroll curve.
  :attr:`Session.max_drawdown` is the largest peak-to-trough *dollar*
  drawdown; :attr:`Session.max_drawdown_pct` is an independent running
  maximum of ``drawdown / peak`` evaluated after *every* bet, kept as an
  exact :class:`fractions.Fraction` so it can equal e.g. exactly 1/3.  The
  two maxima may come from different drawdown episodes and both are monotone
  non-decreasing.
- **Drawdown episodes close at the last observation.**  The session tracks
  drawdown *episodes* (peak / trough / recovery, with sequence numbers, bet
  counts and the caller-supplied timestamps).  Following the reference
  tear-sheet convention, an episode that is still open when statistics are
  read is *closed at the last recorded bet*: its span (``bets`` / ``days``)
  runs peak → last observation, it is folded into
  :attr:`Session.longest_drawdown_bets` / ``longest_drawdown_days``, and its
  reported ``recovered_at`` / ``recovered_seq`` carry the last observation
  (with ``recovered: false`` marking it as unrecovered).  An episode rooted
  at the session-start peak dates from ``started_at`` when the constructor
  was given one, else from the first bet's timestamp.  Episode *counts* and
  running sums are kept for **all** episodes, so ``summary()`` can report
  average drawdown depth and duration even though the retained worst-episode
  table is bounded.
- **Stop triggers are advisory.**  Stop-loss / stop-win (absolute and
  percent-of-starting-bankroll) are evaluated after *every* recorded bet.
  The first trigger latches (:attr:`Session.stop_reason`,
  :attr:`Session.stopped`, the triggering bet's sequence number) but
  recording is not blocked: a human who keeps playing past their own stop
  still deserves an accurate ledger.  A latched stop is *journalled* to the
  JSONL file as its own ``stop`` record (in the same durable write as the
  triggering bet), so the latch survives reload even if the header's stop
  parameters are later edited — a mismatch between the journalled latch and
  the replayed latch raises on load.
- **JSONL persistence, append-safe and reload-safe.**  When constructed with
  ``jsonl_path``, the session writes one ``session_start`` header line and
  then appends one line per event (``bet`` / ``stop`` / ``cash``), fsyncing
  after each append.  ``Session.load`` replays the file back into an
  identical live session (which keeps appending to the same file).  A torn
  final line (crash mid-append) is *truncated away* before appending resumes,
  so a resume can never glue a new record onto torn garbage or silently lose
  a later bet; corruption anywhere else raises.  Replay re-derives every bet
  from its recorded inputs and verifies the persisted ``seq``, ``payout``,
  ``net`` and ``bankroll_after`` against the recomputation — tampering with
  any of them raises ``ValueError``.  A file may contain several
  ``session_start`` headers (a fresh session pointed at an old file); load
  replays the last one, skipping records that carry a different
  ``session_id`` (so two interleaved sessions do not brick the file).
- **Resume-safe concurrency (last resumer wins).**  Every writing session
  has a private *writer id*; ``Session.load`` gives the resumed session a
  fresh one and journals a ``resume`` record (immediately before its first
  append, so a bare ``load()`` leaves the file byte-identical).  On replay,
  records written by a *superseded* writer after a resume — e.g. a stale
  handle that kept appending after its file was resumed elsewhere — are
  skipped deterministically instead of bricking the file; the count is
  exposed as ``stale_records_skipped``.  Two *diverged* resumed writers
  (both resumed from the same point, both wrote) are detected and rejected
  with a clear error rather than silently merged.
- **Cash movements.**  ``deposit()`` / ``withdraw()`` record a top-up or
  cash-out as a ``cash`` ledger record on the same sequence counter as bets
  (:attr:`CashRecord.seq`), so the full chronological journal is
  reconstructable in memory (:attr:`Session.events`) and in the DataFrame
  export, where the ``bankroll_after`` chain foots across cash flows.  Cash
  moves the bankroll but is excluded from :attr:`Session.pnl` (and therefore
  from stop triggers) and from the equity curve that drawdown is measured on.
- **Timestamps are caller-supplied and stored verbatim.**  Any non-empty
  string (or datetime/date, stored as ISO) is accepted; the session
  additionally *parses* ISO timestamps when possible to derive drawdown
  durations, and counts unparseable or backwards-in-time timestamps in
  :attr:`Session.timestamp_anomalies` (advisory, never blocking).
- **No UI.**  ``summary()`` returns a JSON-serializable dict and
  ``to_dataframe()`` hands the event history to the report layer.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from fractions import Fraction
from typing import Any, Dict, List, Mapping, Optional, Union

import pandas as pd

__all__ = [
    "CENT",
    "MoneyError",
    "BetRecord",
    "CashRecord",
    "Session",
]

CENT = Decimal("0.01")
_ZERO = Decimal("0.00")
_EMPTY_CONFIG_JSON = "{}"
_WORST_EPISODES_KEPT = 32   # bound on retained drawdown episodes (worst by %)

MoneyLike = Union[Decimal, int, str, float]


class MoneyError(ValueError):
    """Raised for invalid money inputs (sub-cent stakes, negatives, floats
    that do not represent exact values, magnitudes too large to quantize,
    etc.)."""


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
    try:
        quantized = dec.quantize(CENT)
    except InvalidOperation as exc:
        raise MoneyError(f"{name} is too large to represent in exact cents: {dec}") from exc
    if quantized != dec:
        raise MoneyError(f"{name} must be an exact cent amount, got {dec}")
    if not quantized:
        quantized = _ZERO  # normalize -0.00 -> 0.00
    return quantized


def _money_str(value: Decimal) -> str:
    """Canonical two-decimal string for a cent amount ('12.30', '-0.50').

    Negative zero is normalized to '0.00'.
    """
    q = value.quantize(CENT)
    if not q:
        return "0.00"
    return str(q)


def _pct_str(frac: Fraction) -> str:
    """Exact ROUND_HALF_UP rendering of a fraction as a percent ('46.67%')."""
    scaled = frac * 10000  # hundredths of a percent
    if scaled >= 0:
        n = (2 * scaled.numerator + scaled.denominator) // (2 * scaled.denominator)
        sign = ""
    else:
        n = (-2 * scaled.numerator + scaled.denominator) // (2 * scaled.denominator)
        sign = "-"
    return f"{sign}{n // 100}.{n % 100:02d}%"


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


def _parse_dt(ts: str) -> Optional[datetime]:
    """Best-effort ISO parse of a stored timestamp string (None if not ISO)."""
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def _pct_decimal(frac: Fraction) -> Decimal:
    """A drawdown fraction as a Decimal at context precision (28 significant
    digits) — constant-cost to accumulate, exact far beyond display needs."""
    return Decimal(frac.numerator) / Decimal(frac.denominator)


def _days_between(a: Optional[datetime], b: Optional[datetime]) -> Optional[float]:
    """Fractional days from ``a`` to ``b`` (None when either is unknown or
    the pair cannot be compared, e.g. naive vs aware)."""
    if a is None or b is None:
        return None
    try:
        return (b - a).total_seconds() / 86400.0
    except TypeError:
        return None


def _canonical_config_json(config: Optional[Mapping[str, Any]]) -> str:
    """Canonical JSON for a bet config, using the *exact* serializer options
    the persistence layer uses (sort_keys + compact separators + strict RFC
    8259 numbers), so anything that passes validation is guaranteed to
    persist byte-identically, and anything that cannot persist fails here —
    before any state is mutated."""
    if not config:
        return _EMPTY_CONFIG_JSON
    try:
        return json.dumps(dict(config), sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
    except ValueError as exc:      # NaN / inf: not representable in JSON
        raise ValueError(f"config must be JSON-serializable: {exc}") from exc
    except TypeError:
        # Mixed-type keys only sort after JSON stringifies them; normalize
        # through a non-sorting dump, then canonicalize.  Anything still
        # unserializable fails here — before any state is mutated.
        try:
            normalized = json.loads(json.dumps(dict(config), allow_nan=False))
            return json.dumps(normalized, sort_keys=True,
                              separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"config must be JSON-serializable: {exc}") from exc


@dataclass(frozen=True, slots=True)
class BetRecord:
    """One resolved bet, as recorded.  All money fields are exact cents.

    ``seq`` is the record's 1-based position in the session's *event
    journal*, shared with cash movements, so bets and cash flows interleave
    unambiguously even when timestamps repeat.

    The game configuration is stored as its canonical JSON string
    (:attr:`config_json`), which makes the record *deeply* immutable — the
    caller's dict is snapshotted at record time and no later mutation of it
    (or of anything returned by :attr:`config`) can alter the ledger row.
    """

    seq: int                      # 1-based position in the event journal
    timestamp: str                # caller-supplied, normalized to str
    game: str
    config_json: str              # canonical JSON of the game configuration
    stake: Decimal                # amount wagered (> 0, exact cents)
    multiplier: Decimal           # total-return multiple, >= 0 ("for one")
    payout: Decimal               # stake * multiplier, quantized to cents
    net: Decimal                  # payout - stake
    bankroll_after: Decimal       # ledger balance after this bet settled

    @property
    def config(self) -> Dict[str, Any]:
        """The game configuration as a fresh dict (mutating it is harmless)."""
        return json.loads(self.config_json)

    def to_json_dict(self) -> Dict[str, Any]:
        """JSON-serializable form (money as canonical strings)."""
        return {
            "type": "bet",
            "seq": self.seq,
            "timestamp": self.timestamp,
            "game": self.game,
            "config": json.loads(self.config_json),
            "stake": _money_str(self.stake),
            "multiplier": str(self.multiplier),
            "payout": _money_str(self.payout),
            "net": _money_str(self.net),
            "bankroll_after": _money_str(self.bankroll_after),
        }


@dataclass(frozen=True, slots=True)
class CashRecord:
    """One cash movement (deposit or withdrawal).  Excluded from P&L.

    ``seq`` sits on the same event-journal counter as :attr:`BetRecord.seq`,
    so the chronological order of bets and cash flows is recoverable from
    the in-memory objects (see :attr:`Session.events`), not just the file.
    """

    kind: str                     # "deposit" | "withdrawal"
    seq: int                      # 1-based position in the event journal
    timestamp: str
    amount: Decimal               # positive exact cents
    bankroll_after: Decimal

    def to_json_dict(self) -> Dict[str, Any]:
        return {
            "type": "cash",
            "kind": self.kind,
            "seq": self.seq,
            "timestamp": self.timestamp,
            "amount": _money_str(self.amount),
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


@dataclass(frozen=True)
class _Episode:
    """One peak-to-trough drawdown episode, closed either by recovery or —
    for the episode still open when statistics are read — at the last
    recorded bet (the reference tear-sheet convention)."""

    from_peak: Decimal            # equity peak the episode fell from
    trough: Decimal               # deepest equity reached
    start_seq: int                # journal seq of the peak bet (0 = session start)
    start_at: Optional[str]
    trough_seq: int
    trough_at: Optional[str]
    end_seq: int                  # recovery bet, or last observed bet if open
    end_at: Optional[str]
    recovered: bool               # False = still underwater at the last bet
    bets: int                     # bets from peak to end
    days: Optional[float]         # peak -> end, when the timestamps parse

    @property
    def drawdown(self) -> Decimal:
        return self.from_peak - self.trough

    @property
    def drawdown_pct(self) -> Fraction:
        if self.from_peak > 0:
            return Fraction(self.drawdown) / Fraction(self.from_peak)
        return Fraction(0)

    def to_json_dict(self) -> Dict[str, Any]:
        pct = self.drawdown_pct
        return {
            "from_peak": _money_str(self.from_peak),
            "trough": _money_str(self.trough),
            "drawdown": _money_str(self.drawdown),
            "drawdown_pct": _pct_str(pct),
            "drawdown_pct_value": float(pct),
            "start_seq": self.start_seq,
            "start_at": self.start_at,
            "trough_seq": self.trough_seq,
            "trough_at": self.trough_at,
            # Tear-sheet convention: an unrecovered episode is closed at the
            # last observation, so recovered_seq/recovered_at always carry the
            # episode's end; the boolean says whether that end was a recovery.
            "recovered": self.recovered,
            "recovered_seq": self.end_seq,
            "recovered_at": self.end_at,
            "end_seq": self.end_seq,
            "end_at": self.end_at,
            "bets": self.bets,
            "days": self.days,
        }


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
    started_at:
        Optional caller-supplied timestamp for the session opening.  Used to
        date a drawdown episode rooted at the session-start peak (when not
        given, such an episode dates from the first bet's timestamp).
    jsonl_path:
        Optional path for append-only JSONL persistence.  The header line is
        written immediately (parent directory must exist).  The append handle
        is held open for the life of the session (each append is still
        flushed and fsynced); call :meth:`close` (or use the session as a
        context manager) to release it early.
    allow_negative_bankroll:
        By default a stake (or withdrawal) larger than the current bankroll
        is rejected (MoneyError) — the ledger cannot cover it.  Set True to
        permit (e.g. tracking a bankroll the human is willing to reload;
        see :meth:`deposit` / :meth:`withdraw` for recording the reloads
        themselves).
    """

    def __init__(
        self,
        starting_bankroll: MoneyLike,
        *,
        stop_loss: Optional[MoneyLike] = None,
        stop_win: Optional[MoneyLike] = None,
        stop_loss_pct: Optional[MoneyLike] = None,
        stop_win_pct: Optional[MoneyLike] = None,
        started_at: Optional[Union[str, datetime, date]] = None,
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

        self.started_at = _timestamp_str(started_at) if started_at is not None else None
        self.session_id = session_id or uuid.uuid4().hex
        self.allow_negative_bankroll = bool(allow_negative_bankroll)

        self.bankroll = self.starting_bankroll
        self.max_drawdown = _ZERO                    # peak-to-trough dollars, >= 0
        self.max_drawdown_pct = Fraction(0)          # running max of dd/peak (exact)
        self.bets: List[BetRecord] = []
        self.cash_flows: List[CashRecord] = []
        self.events: List[Union[BetRecord, CashRecord]] = []   # journal order
        self.total_deposited = _ZERO
        self.total_withdrawn = _ZERO
        self.per_game: Dict[str, _GameStats] = {}
        self._total_staked = _ZERO
        self._total_returned = _ZERO
        self._seq = 0                                # event-journal counter

        self.stopped = False
        self.stop_reason: Optional[str] = None       # e.g. "stop_loss", "stop_win_pct"
        self.stop_seq: Optional[int] = None          # seq of the latching bet
        self._stop_ts: Optional[str] = None          # timestamp of the latching bet
        self._stop_pnl: Optional[Decimal] = None
        self._stop_bankroll: Optional[Decimal] = None

        # -- drawdown tracking on the gambling equity curve -----------------
        # equity = starting_bankroll + cumulative bet net (cash excluded), so
        # the equity peak starts positive and never decreases: percent
        # drawdowns always have a positive, cash-flow-independent baseline.
        self._equity = self.starting_bankroll
        self._eq_peak = self.starting_bankroll
        self._peak_seq = 0                           # 0 == session start
        self._peak_bets = 0                          # bet count when peak was set
        self._peak_ts: Optional[str] = self.started_at
        self._peak_dt: Optional[datetime] = (
            _parse_dt(self.started_at) if self.started_at is not None else None
        )
        self._trough = self._equity
        self._trough_seq = 0
        self._trough_ts: Optional[str] = None
        self._trough_dt: Optional[datetime] = None
        self._in_dd = False
        self._episodes: List[_Episode] = []          # worst by %, bounded
        # aggregates over ALL closed episodes (the open one is folded in at
        # reporting time), so averages survive the bounded episode table.
        # The percent sum is accumulated as a 28-significant-digit Decimal:
        # an exact-Fraction running sum would grow its denominator with every
        # episode (an lcm over ~10^5 unrelated peaks) and turn each addition
        # quadratic; 28 digits is beyond any displayable precision.
        self._ep_count = 0
        self._ep_pct_sum = Decimal(0)
        self._ep_days_sum = 0.0
        self._ep_days_n = 0
        self._closed_longest_bets = 0
        self._closed_longest_days: Optional[float] = None
        self._max_dd_info: Optional[Dict[str, Any]] = None       # where the $ max happened
        self._max_dd_pct_info: Optional[Dict[str, Any]] = None   # where the % max happened

        # first/last observed bet (drawdown durations close here)
        self._first_bet_ts: Optional[str] = None
        self._first_bet_dt: Optional[datetime] = None
        self._last_bet_seq = 0
        self._last_bet_ts: Optional[str] = None
        self._last_bet_dt: Optional[datetime] = None
        self._last_parsed_bet_dt: Optional[datetime] = None  # duration fallback

        # -- timestamp sanity (advisory) ------------------------------------
        self.timestamp_anomalies = 0                 # unparseable or backwards timestamps
        self._last_dt: Optional[datetime] = None

        # -- persistence ----------------------------------------------------
        # Each writing handle has a private writer id.  A resumed session
        # (Session.load) journals a `resume` record immediately before its
        # first append; on replay, post-resume records from superseded
        # writers are skipped (see stale_records_skipped).
        self._writer = uuid.uuid4().hex[:12]
        self._pending_resume: Optional[Dict[str, Any]] = None
        self.stale_records_skipped = 0
        self._jsonl_path = os.fspath(jsonl_path) if jsonl_path is not None else None
        self._fh = None
        if self._jsonl_path is not None and not _defer_header:
            self._append_objs([self._header_dict()])

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
        """Cumulative gambling profit/loss (exact cents).

        Deposits and withdrawals are excluded: pnl reflects only bet
        outcomes, so stop triggers cannot be reset by topping up.
        """
        return (self.bankroll - self.starting_bankroll
                - self.total_deposited + self.total_withdrawn)

    @property
    def total_staked(self) -> Decimal:
        return self._total_staked

    @property
    def total_returned(self) -> Decimal:
        return self._total_returned

    @property
    def jsonl_path(self) -> Optional[str]:
        return self._jsonl_path

    @property
    def peak_bankroll(self) -> Decimal:
        """Highest *gambling* bankroll reached: the running peak of the
        equity curve (bankroll with cash flows backed out).  Equal to the
        plain bankroll peak when there are no cash flows, and always > 0."""
        return self._eq_peak

    @property
    def max_drawdown_peak(self) -> Optional[Decimal]:
        """Equity peak from which the max *dollar* drawdown was measured."""
        return self._max_dd_info["from_peak"] if self._max_dd_info else None

    @property
    def max_drawdown_pct_peak(self) -> Optional[Decimal]:
        """Equity peak from which the max *percent* drawdown was measured."""
        return self._max_dd_pct_info["from_peak"] if self._max_dd_pct_info else None

    @property
    def longest_drawdown_bets(self) -> int:
        """Longest underwater run in bets, the still-open episode included
        (measured peak -> last observed bet)."""
        longest = self._closed_longest_bets
        open_ep = self._open_episode()
        if open_ep is not None and open_ep.bets > longest:
            longest = open_ep.bets
        return longest

    @property
    def longest_drawdown_days(self) -> Optional[float]:
        """Longest underwater run in days (when timestamps parse), the
        still-open episode included (measured peak -> last observed bet)."""
        longest = self._closed_longest_days
        open_ep = self._open_episode()
        if open_ep is not None and open_ep.days is not None:
            longest = open_ep.days if longest is None else max(longest, open_ep.days)
        return longest

    @property
    def drawdown_episode_count(self) -> int:
        """Total number of drawdown episodes (the open one included) — not
        capped, unlike the retained worst-episodes table."""
        return self._ep_count + (1 if self._in_dd else 0)

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

        All validation and serialization happens *before* any state is
        mutated or persisted; if persistence is enabled, the ledger line
        (and, when a stop latches on this bet, its ``stop`` journal line)
        is durably written before the in-memory state is updated.
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
        # Canonical representation (value-preserving): "-0.00"/"2.0000" -> "0"/"2",
        # and no positive exponent ("1E+2" -> "100"), so the ledger renders one
        # spelling per value and a reload of an equal value rewrites identically.
        if not mult_d:
            mult_d = Decimal("0")
        else:
            mult_d = mult_d.normalize()
            if mult_d.as_tuple().exponent > 0:
                try:
                    mult_d = mult_d.quantize(Decimal(1))
                except InvalidOperation:
                    pass  # astronomically large; the payout check below rejects it

        # Snapshot the config as canonical JSON with the exact serializer the
        # persistence layer uses — anything that passes here persists.
        config_json = _canonical_config_json(config)

        try:
            payout = (stake_d * mult_d).quantize(CENT, rounding=ROUND_HALF_UP)
        except InvalidOperation as exc:
            raise MoneyError(
                f"payout {stake_d} * {mult_d} is too large to represent in exact cents"
            ) from exc
        if not payout:
            payout = _ZERO  # normalize -0.00 (e.g. multiplier "-0.00")
        net = payout - stake_d
        if not net:
            net = _ZERO

        new_bankroll = self.bankroll + net
        record = BetRecord(
            seq=self._seq + 1,
            timestamp=ts,
            game=game,
            config_json=config_json,
            stake=stake_d,
            multiplier=mult_d,
            payout=payout,
            net=net,
            bankroll_after=new_bankroll,
        )

        # Decide the stop latch *functionally* so the journal line can be
        # persisted in the same durable write as the bet line.
        new_stop = None
        if not self.stopped:
            new_pnl = new_bankroll - self.starting_bankroll \
                - self.total_deposited + self.total_withdrawn
            reason = self._stop_decision(new_pnl)
            if reason is not None:
                new_stop = (reason, record.seq, ts, new_pnl, new_bankroll)

        # Persist first (serialization errors cannot leave memory/disk split).
        if self._jsonl_path is not None:
            objs = [dict(record.to_json_dict(),
                         session_id=self.session_id, writer=self._writer)]
            if new_stop is not None:
                objs.append(self._stop_journal_dict(*new_stop))
            self._append_objs(objs)

        # Mutate in-memory state.
        self._seq = record.seq
        self.bankroll = new_bankroll
        self._equity += net
        self.bets.append(record)
        self.events.append(record)
        dt = _parse_dt(ts)
        self._note_timestamp(dt)
        if self._first_bet_ts is None:
            self._first_bet_ts, self._first_bet_dt = ts, dt
        self._last_bet_seq, self._last_bet_ts, self._last_bet_dt = record.seq, ts, dt
        if dt is not None:
            self._last_parsed_bet_dt = dt
        self._update_aggregates(record, dt)
        if new_stop is not None:
            (self.stop_reason, self.stop_seq, self._stop_ts,
             self._stop_pnl, self._stop_bankroll) = new_stop
            self.stopped = True
        return record

    def deposit(self, amount: MoneyLike, timestamp: Union[str, datetime, date]) -> CashRecord:
        """Record a bankroll top-up.  Excluded from P&L and stop triggers."""
        return self._record_cash("deposit", amount, timestamp)

    def withdraw(self, amount: MoneyLike, timestamp: Union[str, datetime, date]) -> CashRecord:
        """Record a cash-out.  Excluded from P&L and stop triggers."""
        return self._record_cash("withdrawal", amount, timestamp)

    def _record_cash(
        self,
        kind: str,
        amount: MoneyLike,
        timestamp: Union[str, datetime, date],
    ) -> CashRecord:
        if kind not in ("deposit", "withdrawal"):
            raise ValueError(f"unknown cash kind {kind!r}")
        ts = _timestamp_str(timestamp)
        amt = _to_money(amount, name="amount")
        if amt <= 0:
            raise MoneyError("amount must be > 0")
        signed = amt if kind == "deposit" else -amt
        if kind == "withdrawal" and not self.allow_negative_bankroll and amt > self.bankroll:
            raise MoneyError(
                f"withdrawal {_money_str(amt)} exceeds bankroll {_money_str(self.bankroll)}"
            )
        new_bankroll = self.bankroll + signed
        record = CashRecord(kind=kind, seq=self._seq + 1, timestamp=ts,
                            amount=amt, bankroll_after=new_bankroll)
        if self._jsonl_path is not None:
            self._append_objs([dict(record.to_json_dict(),
                                    session_id=self.session_id,
                                    writer=self._writer)])
        # Cash moves the bankroll but not the equity curve, so drawdown
        # statistics (dollar and percent) are untouched by the transfer.
        self._seq = record.seq
        self.bankroll = new_bankroll
        self.cash_flows.append(record)
        self.events.append(record)
        self._note_timestamp(_parse_dt(ts))
        if kind == "deposit":
            self.total_deposited += amt
        else:
            self.total_withdrawn += amt
        return record

    # ------------------------------------------------------------------ aggregates

    def _note_timestamp(self, dt: Optional[datetime]) -> None:
        if dt is None:
            self.timestamp_anomalies += 1
            return
        if self._last_dt is not None:
            try:
                if dt < self._last_dt:
                    self.timestamp_anomalies += 1
            except TypeError:   # naive vs aware mix
                self.timestamp_anomalies += 1
        self._last_dt = dt

    def _update_aggregates(self, record: BetRecord, dt: Optional[datetime]) -> None:
        seq, ts = record.seq, record.timestamp
        nbets = len(self.bets)
        eq = self._equity
        if eq >= self._eq_peak:
            # Recovery (and possibly a new peak).
            if self._in_dd:
                self._finalize_episode(seq, nbets, ts, dt)
            self._in_dd = False
            if eq > self._eq_peak:
                self._eq_peak = eq
            # The drawdown clock starts at the *last* touch of the peak.
            self._peak_seq, self._peak_bets = seq, nbets
            self._peak_ts, self._peak_dt = ts, dt
            self._trough = eq
            self._trough_seq, self._trough_ts = seq, ts
            self._trough_dt = dt
        else:
            drawdown = self._eq_peak - eq
            self._in_dd = True
            if eq < self._trough:
                self._trough = eq
                self._trough_seq, self._trough_ts = seq, ts
                self._trough_dt = dt
            if drawdown > self.max_drawdown:
                self.max_drawdown = drawdown
                self._max_dd_info = self._dd_snapshot(seq, ts)
            # Independent running max of the *percentage* drawdown, evaluated
            # on every bet (decoupled from the dollar max — see module docs).
            # The equity peak starts positive and never decreases, so the
            # denominator is always > 0 regardless of cash flows.
            pct = Fraction(drawdown) / Fraction(self._eq_peak)
            if pct > self.max_drawdown_pct:
                self.max_drawdown_pct = pct
                self._max_dd_pct_info = self._dd_snapshot(seq, ts)
        stats = self.per_game.setdefault(record.game, _GameStats())
        stats.bets += 1
        stats.total_staked += record.stake
        stats.total_returned += record.payout
        self._total_staked += record.stake
        self._total_returned += record.payout
        if record.payout > record.stake:
            stats.wins += 1
        elif record.payout == record.stake:
            stats.pushes += 1
        else:
            stats.losses += 1

    def _dd_snapshot(self, trough_seq: int, trough_ts: str) -> Dict[str, Any]:
        start_ts, _start_dt = self._episode_start()
        return {
            "from_peak": self._eq_peak,
            "start_seq": self._peak_seq, "start_at": start_ts,
            "trough_seq": trough_seq, "trough_at": trough_ts,
        }

    def _episode_start(self) -> tuple:
        """(timestamp, datetime) the current drawdown episode dates from.

        An episode rooted at the session-start peak dates from ``started_at``
        when the constructor was given one, else from the first bet."""
        if self._peak_ts is not None:
            return self._peak_ts, self._peak_dt
        return self._first_bet_ts, self._first_bet_dt

    def _build_episode(self, end_seq: int, end_bets: int, end_ts: Optional[str],
                       end_dt: Optional[datetime], recovered: bool) -> _Episode:
        start_ts, start_dt = self._episode_start()
        if end_dt is None:
            # Best-effort duration: when the closing bet's timestamp does not
            # parse, the latest parseable bet timestamp stands in for the end.
            end_dt = self._last_parsed_bet_dt
        return _Episode(
            from_peak=self._eq_peak,
            trough=self._trough,
            start_seq=self._peak_seq, start_at=start_ts,
            trough_seq=self._trough_seq, trough_at=self._trough_ts,
            end_seq=end_seq, end_at=end_ts,
            recovered=recovered,
            bets=end_bets - self._peak_bets,
            days=_days_between(start_dt, end_dt),
        )

    def _finalize_episode(self, recovered_seq: int, recovered_bets: int,
                          recovered_ts: str,
                          recovered_dt: Optional[datetime]) -> None:
        ep = self._build_episode(recovered_seq, recovered_bets,
                                 recovered_ts, recovered_dt, recovered=True)
        if ep.bets > self._closed_longest_bets:
            self._closed_longest_bets = ep.bets
        if ep.days is not None and (self._closed_longest_days is None
                                    or ep.days > self._closed_longest_days):
            self._closed_longest_days = ep.days
        self._ep_count += 1
        self._ep_pct_sum += _pct_decimal(ep.drawdown_pct)
        if ep.days is not None:
            self._ep_days_sum += ep.days
            self._ep_days_n += 1
        self._episodes.append(ep)
        self._episodes.sort(key=lambda e: (-e.drawdown_pct, e.start_seq))
        if len(self._episodes) > _WORST_EPISODES_KEPT:
            kept = self._episodes[:_WORST_EPISODES_KEPT]
            # never evict the max-dollar episode: the summary headline must
            # stay reconcilable with the episode table
            if self._max_dd_info is not None:
                tgt = self._max_dd_info["start_seq"]
                if all(e.start_seq != tgt for e in kept):
                    extra = next((e for e in self._episodes[_WORST_EPISODES_KEPT:]
                                  if e.start_seq == tgt), None)
                    if extra is not None:
                        kept.append(extra)
            self._episodes = kept

    def _open_episode(self) -> Optional[_Episode]:
        """The still-open drawdown episode, closed at the last recorded bet
        (None when the session is at its equity peak)."""
        if not self._in_dd:
            return None
        return self._build_episode(self._last_bet_seq, len(self.bets),
                                   self._last_bet_ts, self._last_bet_dt,
                                   recovered=False)

    def drawdown_episodes(self) -> List[Dict[str, Any]]:
        """Worst drawdown episodes (by percent depth), JSON-safe.

        Bounded to the worst ``_WORST_EPISODES_KEPT`` (32) closed episodes
        (plus the max-dollar episode, always retained, and the currently
        open one, closed at the last recorded bet); each entry carries
        peak / trough / end values, sequence numbers, bet counts, the
        caller-supplied timestamps, a ``recovered`` flag, and the duration
        in days when the timestamps parse as ISO.  The *total* episode
        count (uncapped) is :attr:`drawdown_episode_count`, and
        ``summary()['drawdown']`` carries running averages over all
        episodes.
        """
        eps = list(self._episodes)
        open_ep = self._open_episode()
        if open_ep is not None:
            eps.append(open_ep)
        eps.sort(key=lambda e: (-e.drawdown_pct, e.start_seq))
        return [e.to_json_dict() for e in eps]

    def worst_drawdowns(self, n: int = 10) -> List[Dict[str, Any]]:
        """The ``n`` worst drawdown episodes by percent depth (JSON-safe)."""
        return self.drawdown_episodes()[:n]

    # ------------------------------------------------------------------ stops

    def _stop_decision(self, pnl: Decimal) -> Optional[str]:
        """Which stop (if any) a P&L of ``pnl`` crosses.  Loss before win."""
        if self.stop_loss is not None and pnl <= -self.stop_loss:
            return "stop_loss"
        if self.stop_loss_pct is not None and pnl <= -(self.starting_bankroll * self.stop_loss_pct):
            return "stop_loss_pct"
        if self.stop_win is not None and pnl >= self.stop_win:
            return "stop_win"
        if self.stop_win_pct is not None and pnl >= self.starting_bankroll * self.stop_win_pct:
            return "stop_win_pct"
        return None

    def _stop_journal_dict(self, reason: str, seq: int, ts: str,
                           pnl: Decimal, bankroll: Decimal) -> Dict[str, Any]:
        return {
            "type": "stop",
            "session_id": self.session_id,
            "writer": self._writer,
            "reason": reason,
            "seq": seq,
            "timestamp": ts,
            "pnl": _money_str(pnl),
            "bankroll": _money_str(bankroll),
        }

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

    def _dd_headline(self, info: Optional[Dict[str, Any]],
                     open_ep: Optional[_Episode]) -> Optional[Dict[str, Any]]:
        """Summary block for a running-max drawdown snapshot, completed with
        its episode's end (recovery, or last observed bet when still open)."""
        if not info:
            return None
        ep: Optional[_Episode] = None
        if open_ep is not None and open_ep.start_seq == info["start_seq"]:
            ep = open_ep
        else:
            for e in self._episodes:
                if e.start_seq == info["start_seq"]:
                    ep = e
                    break
        out: Dict[str, Any] = {
            "from_peak": _money_str(info["from_peak"]),
            "start_seq": info["start_seq"],
            "start_at": info["start_at"],
        }
        if ep is not None:
            out.update({
                "trough_seq": ep.trough_seq, "trough_at": ep.trough_at,
                "recovered": ep.recovered,
                "recovered_seq": ep.end_seq, "recovered_at": ep.end_at,
                "bets": ep.bets, "days": ep.days,
            })
        else:  # not expected (the episode is always retained); degrade gracefully
            out.update({
                "trough_seq": info["trough_seq"], "trough_at": info["trough_at"],
                "recovered": None, "recovered_seq": None, "recovered_at": None,
                "bets": None, "days": None,
            })
        return out

    def summary(self) -> Dict[str, Any]:
        """Full session summary as a JSON-serializable dict.

        ``max_drawdown_pct`` is rendered like the reference tear sheet
        ("46.67%", ROUND_HALF_UP to two decimals); the exact value is also
        provided as a float in ``max_drawdown_pct_value`` and remains
        available in full precision on :attr:`max_drawdown_pct`.

        The ``drawdown`` block closes the still-open episode at the last
        recorded bet (tear-sheet convention): ``longest_bets`` /
        ``longest_days`` include it, the ``max`` / ``max_pct`` headlines
        carry its period start *and* end (``recovered_at``; ``recovered``
        is false when the end is merely the last observation), ``count`` /
        ``avg_pct`` / ``avg_days`` average over *all* episodes (not just
        the retained worst table), and every ``worst`` row reconciles with
        the headlines.
        """
        first_ts = self.bets[0].timestamp if self.bets else None
        last_ts = self.bets[-1].timestamp if self.bets else None
        open_ep = self._open_episode()

        dd_max = self._dd_headline(self._max_dd_info, open_ep)
        if dd_max:
            dd_max["amount"] = _money_str(self.max_drawdown)
        dd_pct = self._dd_headline(self._max_dd_pct_info, open_ep)
        if dd_pct:
            dd_pct["pct"] = _pct_str(self.max_drawdown_pct)
            dd_pct["pct_value"] = float(self.max_drawdown_pct)

        ep_count = self._ep_count + (1 if open_ep is not None else 0)
        pct_sum = self._ep_pct_sum
        if open_ep is not None:
            pct_sum += _pct_decimal(open_ep.drawdown_pct)
        days_sum, days_n = self._ep_days_sum, self._ep_days_n
        if open_ep is not None and open_ep.days is not None:
            days_sum += open_ep.days
            days_n += 1
        avg_pct = Fraction(pct_sum / ep_count) if ep_count else None
        avg_days = days_sum / days_n if days_n else None

        return {
            "session_id": self.session_id,
            "starting_bankroll": _money_str(self.starting_bankroll),
            "started_at": self.started_at,
            "bankroll": _money_str(self.bankroll),
            "pnl": _money_str(self.pnl),
            "peak_bankroll": _money_str(self.peak_bankroll),
            "max_drawdown": _money_str(self.max_drawdown),
            "max_drawdown_pct": _pct_str(self.max_drawdown_pct),
            "max_drawdown_pct_value": float(self.max_drawdown_pct),
            "drawdown": {
                "max": dd_max,
                "max_pct": dd_pct,
                "longest_bets": self.longest_drawdown_bets,
                "longest_days": self.longest_drawdown_days,
                "count": ep_count,
                "avg_pct": _pct_str(avg_pct) if avg_pct is not None else None,
                "avg_pct_value": float(avg_pct) if avg_pct is not None else None,
                "avg_days": avg_days,
                "worst": self.worst_drawdowns(10),
            },
            "total_bets": len(self.bets),
            "total_staked": _money_str(self.total_staked),
            "total_returned": _money_str(self.total_returned),
            "total_deposited": _money_str(self.total_deposited),
            "total_withdrawn": _money_str(self.total_withdrawn),
            "first_bet_at": first_ts,
            "last_bet_at": last_ts,
            "timestamp_anomalies": self.timestamp_anomalies,
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

    def to_dataframe(self, include_cash: bool = True) -> pd.DataFrame:
        """Event history as a pandas DataFrame for the report layer.

        With ``include_cash=True`` (the default) the frame is the *full
        journal* in event order — bets and cash movements — so the ledger
        foots row by row: ``bankroll_after[i] == bankroll_after[i-1] +
        net[i]`` (with ``bankroll_after[-1]`` the starting bankroll).  Cash
        rows have ``type == "cash"``, ``kind`` set, ``net`` equal to the
        signed transfer amount, and NaN stake/multiplier/payout.  Pass
        ``include_cash=False`` for the bet rows alone.

        Money columns come out as ``float`` (converted from the exact
        Decimal values, so each is within one float ulp of the true cents);
        the Decimal ledger in :attr:`events` / :attr:`bets` remains the
        source of truth.  ``config`` is carried as its canonical JSON string
        in ``config_json``.
        """
        columns = [
            "seq", "type", "timestamp", "game", "kind", "config_json",
            "stake", "multiplier", "payout", "net", "bankroll_after",
        ]
        nan = float("nan")
        rows = []
        for ev in self.events:
            if isinstance(ev, BetRecord):
                rows.append({
                    "seq": ev.seq,
                    "type": "bet",
                    "timestamp": ev.timestamp,
                    "game": ev.game,
                    "kind": None,
                    "config_json": ev.config_json,
                    "stake": float(ev.stake),
                    "multiplier": float(ev.multiplier),
                    "payout": float(ev.payout),
                    "net": float(ev.net),
                    "bankroll_after": float(ev.bankroll_after),
                })
            elif include_cash:
                signed = ev.amount if ev.kind == "deposit" else -ev.amount
                rows.append({
                    "seq": ev.seq,
                    "type": "cash",
                    "timestamp": ev.timestamp,
                    "game": None,
                    "kind": ev.kind,
                    "config_json": None,
                    "stake": nan,
                    "multiplier": nan,
                    "payout": nan,
                    "net": float(signed),
                    "bankroll_after": float(ev.bankroll_after),
                })
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
            "writer": self._writer,
            "starting_bankroll": _money_str(self.starting_bankroll),
            "started_at": self.started_at,
            "stop_loss": _money_str(self.stop_loss) if self.stop_loss is not None else None,
            "stop_win": _money_str(self.stop_win) if self.stop_win is not None else None,
            "stop_loss_pct": str(self.stop_loss_pct) if self.stop_loss_pct is not None else None,
            "stop_win_pct": str(self.stop_win_pct) if self.stop_win_pct is not None else None,
            "allow_negative_bankroll": self.allow_negative_bankroll,
        }

    def _append_objs(self, objs: List[Dict[str, Any]]) -> None:
        """Serialize, then durably append one or more records as one write.

        Serialization happens for *all* records before any byte is written,
        so a serialization failure can never split memory from disk; a bet
        line and its stop journal line land in a single write + fsync.  A
        resumed session's pending ``resume`` record is prepended to its
        first append (so a bare load never mutates the file).
        """
        if self._pending_resume is not None:
            objs = [self._pending_resume] + list(objs)
        data = b"".join(
            json.dumps(obj, sort_keys=True, separators=(",", ":"),
                       allow_nan=False).encode("utf-8") + b"\n"
            for obj in objs
        )
        fh = self._fh
        if fh is None or fh.closed:
            self._repair_tail(self._jsonl_path)
            fh = self._fh = open(self._jsonl_path, "ab")
        try:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        except OSError:
            # Drop the handle so the next append re-runs tail repair and
            # cannot glue onto a partially written line.
            self.close()
            raise
        self._pending_resume = None

    def close(self) -> None:
        """Release the held append handle (appends reopen it on demand)."""
        fh, self._fh = self._fh, None
        if fh is not None:
            try:
                fh.close()
            except OSError:
                pass

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    @staticmethod
    def _repair_tail(path: str) -> None:
        """Truncate a torn final line so appends/loads never glue onto it.

        A JSONL ledger line is only committed once its trailing newline is
        on disk, so a final *non-blank* segment that does not parse as JSON
        (torn mid-append, possibly followed by stray newlines) is garbage by
        contract and is truncated away — before it can swallow the next
        append.  A parseable final line that merely lacks its newline gets
        the newline added.  Best-effort: unwritable files are left alone
        (the tolerant parser in :meth:`load` still skips a torn tail).
        """
        try:
            fh = open(path, "r+b")
        except (FileNotFoundError, OSError):
            return
        with fh:
            raw = fh.read()
            if not raw:
                return
            segments = raw.split(b"\n")
            last_idx = None
            for i in range(len(segments) - 1, -1, -1):
                if segments[i].strip():
                    last_idx = i
                    break
            if last_idx is None:
                return
            seg = segments[last_idx]
            try:
                json.loads(seg.decode("utf-8"))
                parseable = True
            except (UnicodeDecodeError, ValueError):
                parseable = False
            if parseable:
                if last_idx == len(segments) - 1:  # good line, missing newline
                    fh.seek(0, os.SEEK_END)
                    fh.write(b"\n")
                    fh.flush()
                    os.fsync(fh.fileno())
                return
            # Torn tail: truncate to the end of the last good line.
            offset = sum(len(s) + 1 for s in segments[:last_idx])
            fh.truncate(offset)
            fh.flush()
            os.fsync(fh.fileno())

    @classmethod
    def load(cls, jsonl_path: Union[str, os.PathLike]) -> "Session":
        """Reload a session from its JSONL file and keep appending to it.

        Replays the *last* ``session_start`` header and every record after
        it that belongs to that session (records carrying a different
        ``session_id`` — another session interleaved on the same file — are
        skipped).  A torn (unparseable or truncated) final line is truncated
        away before replay so resuming can never corrupt the file or lose a
        later bet; corruption anywhere else raises ``ValueError``.

        Replay re-derives each bet from its recorded inputs and verifies the
        persisted ``seq``, ``payout``, ``net`` and ``bankroll_after``
        against the recomputation; ``cash`` records are verified via
        ``seq`` and ``bankroll_after``, and ``stop`` journal records must
        match the replayed latch exactly (so editing the header's stop
        parameters after the fact is detected instead of silently rewriting
        history).  If a crash lost the stop journal line for a latch the
        replay re-derives, the line is re-appended.

        The loaded session keeps the same ``session_id`` but gets a fresh
        *writer id*; a ``resume`` record announcing it is journalled
        immediately before the loaded session's first append (a bare load
        leaves the file byte-identical).  On replay, records a superseded
        writer appended after such a resume — a stale handle that kept
        playing after its file was resumed elsewhere — are skipped
        deterministically (counted in ``stale_records_skipped``) instead of
        bricking the file; two *diverged* resumed writers are detected and
        rejected.
        """
        path = os.fspath(jsonl_path)
        cls._repair_tail(path)  # best-effort; read-only files parsed tolerantly
        with open(path, "rb") as fh:
            raw = fh.read()
        segments = raw.split(b"\n")
        last_idx = None
        for i in range(len(segments) - 1, -1, -1):
            if segments[i].strip():
                last_idx = i
                break
        parsed: List[Dict[str, Any]] = []
        for i, seg in enumerate(segments):
            if not seg.strip():
                continue
            try:
                obj = json.loads(seg.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                if i == last_idx:
                    break  # torn tail on an unwritable file; skip it
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
            started_at=header.get("started_at"),
            jsonl_path=path,
            allow_negative_bankroll=header.get("allow_negative_bankroll", False),
            session_id=header.get("session_id"),
            _defer_header=True,  # header already on disk; do not duplicate
        )
        # Replay without re-appending.
        session._jsonl_path = None
        header_writer = header.get("writer")
        current_writer = header_writer
        known_writers = {header_writer}
        stale_skipped = 0
        stop_seen = False        # any stop record for this session (even stale)
        stop_journalled = False  # a verified stop record on the live chain
        try:
            for obj in parsed[start_idx + 1:]:
                sid = obj.get("session_id")
                if sid is not None and sid != session.session_id:
                    continue  # another session interleaved on this file
                rtype = obj["type"]
                if rtype == "resume":
                    new_writer = obj.get("writer")
                    if not new_writer:
                        raise ValueError(f"{path}: resume record has no writer id")
                    if obj.get("base_seq") != session._seq:
                        raise ValueError(
                            f"{path}: resume record expects {obj.get('base_seq')} "
                            f"prior records but replay has {session._seq} — "
                            f"concurrent resumed writers diverged"
                        )
                    known_writers.add(new_writer)
                    current_writer = new_writer
                    continue
                writer = obj.get("writer", header_writer)
                if writer != current_writer:
                    if writer in known_writers:
                        # A superseded handle kept appending after a resume:
                        # skip its records deterministically (last resumer
                        # wins) instead of bricking the file.
                        stale_skipped += 1
                        if rtype == "stop":
                            stop_seen = True
                        continue
                    raise ValueError(
                        f"{path}: record from unknown writer {writer!r}"
                    )
                try:
                    if rtype == "bet":
                        record = session.record_bet(
                            obj["game"],
                            obj.get("config") or {},
                            obj["stake"],
                            obj["multiplier"],
                            obj["timestamp"],
                        )
                        cls._verify_replayed_bet(path, obj, record)
                    elif rtype == "cash":
                        cash = session._record_cash(
                            obj["kind"], obj["amount"], obj["timestamp"],
                        )
                        if "seq" in obj and obj["seq"] != cash.seq:
                            raise ValueError(
                                f"{path}: replay mismatch on cash record: replayed "
                                f"seq {cash.seq} != persisted {obj['seq']!r}"
                            )
                        persisted_after = _to_money(obj["bankroll_after"],
                                                    name="bankroll_after")
                        if cash.bankroll_after != persisted_after:
                            raise ValueError(
                                f"{path}: replay mismatch on cash record: replayed "
                                f"bankroll {_money_str(cash.bankroll_after)} "
                                f"!= persisted {obj['bankroll_after']}"
                            )
                    elif rtype == "stop":
                        stop_seen = True
                        if stop_journalled:
                            raise ValueError(f"{path}: duplicate stop record")
                        if (not session.stopped
                                or obj.get("reason") != session.stop_reason
                                or obj.get("seq") != session.stop_seq):
                            raise ValueError(
                                f"{path}: stop record "
                                f"({obj.get('reason')!r} at seq {obj.get('seq')}) does not "
                                f"match the replayed latch "
                                f"({session.stop_reason!r} at seq {session.stop_seq}, "
                                f"stopped={session.stopped}) — header stop parameters "
                                f"may have been altered"
                            )
                        for key, expected in (("pnl", session._stop_pnl),
                                              ("bankroll", session._stop_bankroll)):
                            if key in obj and _to_money(obj[key], name=key) != expected:
                                raise ValueError(
                                    f"{path}: stop record {key} {obj[key]} != replayed "
                                    f"{_money_str(expected)}"
                                )
                        stop_journalled = True
                    else:
                        raise ValueError(f"{path}: unknown record type {rtype!r}")
                except KeyError as exc:
                    raise ValueError(
                        f"{path}: {rtype} record is missing field {exc}"
                    ) from exc
        finally:
            session._jsonl_path = path
        session.stale_records_skipped = stale_skipped
        # Announce this loaded handle as the file's new writer — journalled
        # lazily, immediately before its first append.
        session._pending_resume = {
            "type": "resume",
            "session_id": session.session_id,
            "writer": session._writer,
            "prev_writer": current_writer,
            "base_seq": session._seq,
        }
        if session.stopped and not stop_seen:
            # The stop line was lost (e.g. crash between the bet write and the
            # journal write of an older-format file); re-journal it.
            session._append_objs([
                session._stop_journal_dict(
                    session.stop_reason, session.stop_seq, session._stop_ts,
                    session._stop_pnl, session._stop_bankroll,
                )
            ])
        return session

    @staticmethod
    def _verify_replayed_bet(path: str, obj: Dict[str, Any], record: BetRecord) -> None:
        """Verify the persisted derived fields against the replayed record."""
        if obj["seq"] != record.seq:
            raise ValueError(
                f"{path}: replay mismatch: persisted seq {obj['seq']!r} != "
                f"replayed seq {record.seq}"
            )
        for name, replayed in (("payout", record.payout),
                               ("net", record.net),
                               ("bankroll_after", record.bankroll_after)):
            persisted = _to_money(obj[name], name=name)
            if persisted != replayed:
                raise ValueError(
                    f"{path}: replay mismatch at seq {record.seq}: "
                    f"replayed {name} {_money_str(replayed)} "
                    f"!= persisted {obj[name]}"
                )
