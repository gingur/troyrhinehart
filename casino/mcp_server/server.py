"""SpinQuest MCP server: the spinquest_sim stack over the Model Context Protocol.

An MCP server (stdio transport, official python SDK ``FastMCP``) exposing the
critic-verified engines in :mod:`spinquest_sim` as tools:

- ``list_games``          — every playable configuration, RTP-ranked via
                            :mod:`spinquest_sim.selector` (engines are the
                            single source of truth; first call builds the
                            analytic table, ~30-40 s, then cached).
- ``game_odds``           — exact analytic RTP / house edge / SD for one
                            (game, config).
- ``simulate``            — vectorized provably-fair simulation (<= 10M
                            rounds, optional deterministic seed); every row
                            is verifiable against the scalar RNG path.
- ``optimal_sizing``      — goal-directed bet sizing from
                            :mod:`spinquest_sim.sizing` (bold/timid regimes,
                            honest negative-EV accounting).
- ``session_start`` / ``session_record_bet`` / ``session_status`` /
  ``session_end``         — the exact-Decimal bankroll ledger of
                            :mod:`spinquest_sim.session`, persisted as JSONL
                            under ``~/.spinquest_sim/sessions/`` (override
                            the root with ``$SPINQUEST_HOME``).
- ``strategy_report``     — the self-contained HTML tear sheet of
                            :mod:`spinquest_sim.report` for a session,
                            written under ``~/.spinquest_sim/reports/``.
- ``verify_bet``          — replay one bet through the provably-fair scalar
                            RNG (HMAC-SHA256 port of Stake's published
                            verifier) and return the fully-derived outcome.

Design rules
------------
* Engines are consumed through their public APIs only; nothing analytic is
  recomputed or hardcoded here.
* Every tool returns JSON-serializable data (numpy / Fraction / Decimal /
  tuple values are sanitized at the edge).
* Tool failures surface as MCP tool errors (the SDK converts raised
  exceptions), never as server crashes.
* stdout belongs to the MCP protocol: every engine call that might print
  (progress meters) runs with stdout redirected to stderr, and simulators
  are invoked with ``progress=False``.

Run:  ``python -m mcp_server.server``  (from the repository root).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import re
import sys
import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import numpy as np

# Make the repository importable no matter how the server is launched
# (``python mcp_server/server.py``, ``python -m mcp_server.server`` from
# anywhere, or an MCP client config with a plain command + cwd).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from spinquest_sim import report as report_mod  # noqa: E402
from spinquest_sim import selector, sizing  # noqa: E402
from spinquest_sim.rng import BulkRng, hash_server_seed  # noqa: E402
from spinquest_sim.session import Session  # noqa: E402
from spinquest_sim.games import baccarat as _baccarat  # noqa: E402
from spinquest_sim.games import blackjack as _blackjack  # noqa: E402
from spinquest_sim.games import crash as _crash  # noqa: E402
from spinquest_sim.games import keno as _keno  # noqa: E402
from spinquest_sim.games import mines as _mines  # noqa: E402
from spinquest_sim.games import plinko as _plinko  # noqa: E402
from spinquest_sim.games import roulette as _roulette  # noqa: E402
from spinquest_sim.games import slots as _slots  # noqa: E402
from spinquest_sim.games import video_poker as _video_poker  # noqa: E402
from spinquest_sim.games import wheel as _wheel  # noqa: E402

MAX_SIM_ROUNDS = 10_000_000
CLIENT_SEED = "spinquest"

GAMES = (
    "baccarat", "blackjack", "crash", "keno", "mines",
    "plinko", "roulette", "slots", "video_poker", "wheel",
)

mcp = FastMCP(
    "spinquest",
    instructions=(
        "Offline casino math tools: exact odds, provably-fair simulation, "
        "bankroll session tracking and honest (negative-EV) bet sizing for "
        "the ten spinquest_sim game engines."
    ),
)


# ---------------------------------------------------------------------------
# plumbing
# ---------------------------------------------------------------------------

def _quiet() -> contextlib.AbstractContextManager:
    """Redirect stdout to stderr: stdout is the MCP protocol channel, and
    some engine paths print progress meters."""
    return contextlib.redirect_stdout(sys.stderr)


def _home() -> Path:
    return Path(os.environ.get("SPINQUEST_HOME", "~/.spinquest_sim")).expanduser()


def _sessions_dir() -> Path:
    d = _home() / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _reports_dir() -> Path:
    d = _home() / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _jsonify(obj: Any) -> Any:
    """Recursively convert engine output to JSON-serializable data.

    numpy scalars/arrays -> python; tuples/sets -> lists; Fraction -> float;
    Decimal -> canonical string (money); non-finite floats -> None (strict
    JSON has no NaN/Infinity).
    """
    if obj is None or isinstance(obj, (bool, str, int)):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, Fraction):
        return float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        f = float(obj)
        return f if math.isfinite(f) else None
    if isinstance(obj, np.ndarray):
        return [_jsonify(v) for v in obj.tolist()]
    if isinstance(obj, dict):
        return {str(k): _jsonify(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonify(v) for v in obj]
    if isinstance(obj, (set, frozenset)):
        return sorted(_jsonify(v) for v in obj)
    return str(obj)


def _require(config: Dict[str, Any], key: str, game: str) -> Any:
    if key not in config:
        raise ValueError(f"{game} config requires {key!r} (got keys {sorted(config)})")
    return config[key]


def _check_game_key(game: str, config: Dict[str, Any]) -> None:
    """A ``game`` key inside the config (e.g. a round-tripped engine
    ``config()`` dict) must agree with the requested game."""
    cfg_game = config.get("game")
    if cfg_game is not None and cfg_game != game:
        raise ValueError(
            f"config['game'] is {cfg_game!r} but the requested game is {game!r}"
        )


# ---------------------------------------------------------------------------
# engine construction (config dict -> engine), cached
# ---------------------------------------------------------------------------

_ENGINE_CACHE: Dict[str, Any] = {}
_ENGINE_LOCK = threading.Lock()


def _engine_params(game: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Extract and validate the constructor parameters for ``game`` from a
    config dict.  Extra descriptive keys (e.g. from a round-tripped engine
    ``config()``) are ignored; missing required keys raise ValueError."""
    _check_game_key(game, config)
    if game == "keno":
        return {
            "picks": _require(config, "picks", game),
            "risk": config.get("risk", "classic"),
        }
    if game == "plinko":
        return {
            "rows": _require(config, "rows", game),
            "risk": _require(config, "risk", game),
        }
    if game == "mines":
        return {
            "mines": _require(config, "mines", game),
            "picks": _require(config, "picks", game),
        }
    if game == "wheel":
        return {
            "segments": _require(config, "segments", game),
            "risk": _require(config, "risk", game),
        }
    if game == "roulette":
        sel = config.get("selection")
        if isinstance(sel, list):
            sel = tuple(sel)
        return {"bet_type": _require(config, "bet_type", game), "selection": sel}
    if game == "baccarat":
        params: Dict[str, Any] = {"bet_type": _require(config, "bet_type", game)}
        if "decks" in config:
            params["decks"] = config["decks"]
        if "tie_odds" in config:
            params["tie_odds"] = config["tie_odds"]
        return params
    if game == "crash":
        return {"target": _require(config, "target", game)}
    if game == "blackjack":
        params = {}
        for key in ("dealer_hits_soft_17", "das", "max_hands", "bj_payout"):
            if key in config:
                params[key] = config[key]
        return params
    if game == "video_poker":
        name = str(config.get("paytable", "stake")).lower()
        if name in ("stake", "stake_paytable"):
            return {"paytable": "stake"}
        if name in ("9/6", "9_6", "benchmark", "benchmark_9_6", "full_pay"):
            return {"paytable": "benchmark_9_6"}
        raise ValueError(
            f"video_poker paytable must be 'stake' or '9/6', got {config.get('paytable')!r}"
        )
    if game == "slots":
        machine = str(config.get("machine", "atkins")).lower()
        if machine != "atkins":
            raise ValueError(
                "slots supports only the validated 'atkins' machine "
                "(Scarab Spin's bonus chain is under-determined by the "
                "published data — see the selector docstring)"
            )
        return {"machine": "atkins"}
    raise ValueError(f"unknown game {game!r}; must be one of {GAMES}")


def _construct(game: str, params: Dict[str, Any]) -> Any:
    if game == "keno":
        return _keno.Keno(params["picks"], params["risk"])
    if game == "plinko":
        return _plinko.Plinko(params["rows"], params["risk"])
    if game == "mines":
        return _mines.Mines(params["mines"], params["picks"])
    if game == "wheel":
        return _wheel.Wheel(params["segments"], params["risk"])
    if game == "roulette":
        return _roulette.Roulette(params["bet_type"], params["selection"])
    if game == "baccarat":
        return _baccarat.Baccarat(
            params["bet_type"],
            **{k: params[k] for k in ("decks", "tie_odds") if k in params},
        )
    if game == "crash":
        return _crash.Crash(params["target"])
    if game == "blackjack":
        return _blackjack.Blackjack(**params)
    if game == "video_poker":
        table = (
            _video_poker.STAKE_PAYTABLE
            if params["paytable"] == "stake"
            else _video_poker.BENCHMARK_9_6_PAYTABLE
        )
        return _video_poker.VideoPoker(table)
    if game == "slots":
        return _slots.atkins_machine()
    raise ValueError(f"unknown game {game!r}")  # unreachable; _engine_params guards


def _build_engine(game: str, config: Optional[Dict[str, Any]]) -> Any:
    """Build (or fetch from cache) the engine for one (game, config)."""
    if not isinstance(game, str):
        raise ValueError(f"game must be a string, got {type(game).__name__}")
    game = game.lower()
    if game not in GAMES:
        raise ValueError(f"unknown game {game!r}; must be one of {GAMES}")
    cfg = dict(config or {})
    params = _engine_params(game, cfg)
    key = f"{game}:{json.dumps(_jsonify(params), sort_keys=True)}"
    with _ENGINE_LOCK:
        engine = _ENGINE_CACHE.get(key)
    if engine is None:
        with _quiet():
            engine = _construct(game, params)
        with _ENGINE_LOCK:
            _ENGINE_CACHE.setdefault(key, engine)
    return engine


# ---------------------------------------------------------------------------
# sizing distributions (exact, from the engines' public analytics)
# ---------------------------------------------------------------------------

def _sizing_game_config(game: str, engine: Any) -> Any:
    """The exact outcome distribution ``sizing.normalize_game_config``
    accepts, per game.  Multipliers are total-return ('for one')."""
    if game in ("roulette", "mines"):
        # exact two-point engines (win multiplier m w.p. p, else 0)
        return engine
    if game == "baccarat":
        p_win = engine.win_probability_exact
        p_push = engine.push_probability_exact
        return {"distribution": [
            (engine.multiplier_exact, p_win),
            (Fraction(1), p_push),
            (Fraction(0), 1 - p_win - p_push),
        ]}
    if game == "crash":
        p = Fraction(engine.win_count_exact, 2 ** 32)
        m = Fraction(str(float(engine.target)))
        return {"distribution": [(m, p), (Fraction(0), 1 - p)]}
    if game == "wheel":
        return {"distribution": list(engine.paytable_exact().items())}
    if game == "keno":
        pays = engine.paytable_exact
        probs = engine.hit_probabilities_exact()
        return {"distribution": list(zip(pays, probs))}
    if game == "plinko":
        dist = [
            (Fraction(str(row["multiplier"])),
             Fraction(row["combinations"], 2 ** engine.rows))
            for row in engine.paytable()
        ]
        return {"distribution": dist}
    if game == "video_poker":
        pays = engine.paytable
        probs = engine.category_probabilities()
        return {"distribution": [
            (Fraction(pays.get(name, 0)), p) for name, p in probs.items()
        ]}
    if game == "blackjack":
        raise ValueError(
            "optimal_sizing does not support blackjack: doubles and splits "
            "put extra money in play, so a flat-stake total-return outcome "
            "distribution (multiplier >= 0 per unit staked) does not exist "
            "for it.  Use game_odds/simulate for blackjack analytics."
        )
    if game == "slots":
        raise ValueError(
            "optimal_sizing does not support slots: the free-spin chain has "
            "no closed-form finite outcome distribution exposed by the "
            "engine.  Use game_odds (exact RTP/SD) or simulate instead."
        )
    raise ValueError(f"unknown game {game!r}")  # unreachable


# ---------------------------------------------------------------------------
# session registry
# ---------------------------------------------------------------------------

_SESSIONS: Dict[str, Session] = {}
_SESS_LOCK = threading.Lock()      # registry membership
_LEDGER_LOCK = threading.Lock()    # serialize ledger mutations (Session is
                                   # not thread-safe; tools may run on
                                   # concurrent worker threads)
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _check_session_id(session_id: str) -> str:
    if not isinstance(session_id, str) or not _SESSION_ID_RE.match(session_id):
        raise ValueError(f"invalid session_id {session_id!r}")
    return session_id


def _session_path(session_id: str) -> Path:
    return _sessions_dir() / f"{session_id}.jsonl"


def _get_session(session_id: str) -> Session:
    sid = _check_session_id(session_id)
    with _SESS_LOCK:
        sess = _SESSIONS.get(sid)
        if sess is not None:
            return sess
        path = _session_path(sid)
        if not path.exists():
            raise ValueError(
                f"unknown session_id {sid!r} (no ledger at {path})"
            )
        sess = Session.load(path)
        _SESSIONS[sid] = sess
        return sess


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _session_payload(sess: Session) -> Dict[str, Any]:
    out = _jsonify(sess.summary())
    out["jsonl_path"] = sess.jsonl_path
    return out


def _session_analytics(sess: Session) -> Dict[str, Any]:
    """Engine analytics for the report: one engine per recorded game name,
    but only when that name was recorded with a single distinct config that
    an engine can be built from.  Anything else is skipped — the report
    handles missing analytics honestly (realized-only, coverage disclosed)."""
    analytics: Dict[str, Any] = {}
    for name in sess.per_game:
        config_jsons = {b.config_json for b in sess.bets if b.game == name}
        if len(config_jsons) != 1:
            continue
        cfg = json.loads(next(iter(config_jsons)))
        base = cfg.get("game", name)
        base = base.lower() if isinstance(base, str) else base
        if base not in GAMES:
            continue
        try:
            analytics[name] = _build_engine(base, cfg)
        except (ValueError, TypeError, KeyError):
            continue
    return analytics


def _seed_server_seed(seed: Union[int, str]) -> str:
    """Deterministic 64-char-hex server seed (the same form Stake generates)
    from a user seed, so seeded simulations are reproducible AND every row
    stays verifiable through verify-style scalar replay."""
    return hashlib.sha256(f"spinquest-mcp:{seed}".encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# tools
# ---------------------------------------------------------------------------

@mcp.tool()
def list_games(
    bankroll: float = 100.0,
    bet: float = 1.0,
    rounds: int = 200,
    top: Optional[int] = None,
) -> Dict[str, Any]:
    """Every playable configuration across the ten engines, ranked by RTP
    (house edge and per-unit SD as secondary columns), pulled live from the
    engines via the selector.  ``survival_prob`` is the labeled analytic
    normal approximation of surviving ``rounds`` flat bets of ``bet`` from
    ``bankroll``.  ``top`` truncates to the first N rows.  The first call
    builds the analytic table (~30-40 s); later calls are cached.
    """
    if top is not None and top < 1:
        raise ValueError(f"top must be >= 1, got {top}")
    with _quiet():
        df = selector.ranking(bankroll=bankroll, bet=bet, rounds=rounds)
    shown = df.head(top) if top is not None else df
    return {
        "count": int(len(df)),
        "shown": int(len(shown)),
        "survival_metric": df.attrs.get("survival_metric"),
        "games": _jsonify(shown.to_dict(orient="records")),
    }


@mcp.tool()
def game_odds(game: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Exact analytic odds for one (game, config): RTP, house edge, per-unit
    standard deviation, and the engine's own canonical config.

    Config keys per game: keno {picks, risk}; plinko {rows, risk}; mines
    {mines, picks}; wheel {segments, risk}; roulette {bet_type, selection};
    baccarat {bet_type[, decks, tie_odds]}; crash {target}; blackjack
    {[dealer_hits_soft_17, das, max_hands, bj_payout]}; video_poker
    {paytable: 'stake'|'9/6'}; slots {} (validated Atkins model).
    """
    engine = _build_engine(game, config)
    with _quiet():
        summary = _jsonify(engine.analytic_summary())
    out: Dict[str, Any] = {"game": game.lower()}
    out.update(summary)
    if hasattr(engine, "variance_per_unit"):
        out.setdefault("variance_per_unit", _jsonify(engine.variance_per_unit))
    return out


@mcp.tool()
def simulate(
    game: str,
    n_rounds: int,
    config: Optional[Dict[str, Any]] = None,
    seed: Optional[Union[int, str]] = None,
) -> Dict[str, Any]:
    """Simulate up to 10,000,000 provably-fair rounds (one nonce per round)
    on the vectorized engine simulator and return the standard result dict
    (empirical RTP/SD vs analytic, z-score, verification block).

    ``seed`` makes the campaign deterministic: the server seed is derived as
    sha256('spinquest-mcp:<seed>') and disclosed in the result, so any row
    can be re-verified with verify_bet at its nonce.  Without a seed a
    fresh random server seed is drawn (its hash commitment is returned).
    """
    if not isinstance(n_rounds, int) or isinstance(n_rounds, bool):
        raise ValueError(f"n_rounds must be an integer, got {n_rounds!r}")
    if not 1 <= n_rounds <= MAX_SIM_ROUNDS:
        raise ValueError(
            f"n_rounds must be in 1..{MAX_SIM_ROUNDS:,}, got {n_rounds:,}"
        )
    engine = _build_engine(game, config)
    # workers=1: BulkRng's process fan-out forks the interpreter, which is
    # deadlock-prone from inside an async stdio server (fork from a worker
    # thread while the event loop holds locks).  The serial stream is
    # byte-identical by construction — only throughput differs.
    if seed is not None:
        rng = BulkRng(server_seed=_seed_server_seed(seed),
                      client_seed=CLIENT_SEED, workers=1)
    else:
        rng = BulkRng(client_seed=CLIENT_SEED, workers=1)
    with _quiet():
        result = engine.simulate(n_rounds, bulk=rng, progress=False)
    out = _jsonify(result)
    out["game"] = game.lower()
    out["rng"] = {
        "seed": seed,
        "server_seed": rng.server_seed,
        "server_seed_hash": rng.server_seed_hash,
        "client_seed": rng.client_seed,
        "nonce_start": rng.nonce_start,
        "nonce_next": rng.nonce_next,
    }
    return out


@mcp.tool()
def optimal_sizing(
    bankroll: float,
    game: str,
    goal: str,
    config: Optional[Dict[str, Any]] = None,
    target: Optional[float] = None,
    n_rounds: Optional[int] = None,
    min_bet: Optional[float] = None,
    max_bet: Optional[float] = None,
    bet_grid: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """Goal-directed bet sizing for a negative-EV game, with honest
    accounting (no bet size changes the sign of the EV).

    ``goal='reach_target'`` (requires ``target`` > bankroll): bold play —
    stake enough to reach the target in one win — with an exact flat-bet
    evidence table.  ``goal='survive_rounds'`` (requires ``n_rounds``):
    timid play — the smallest allowed bet — with the survival curve per
    candidate size.  The outcome distribution is taken exactly from the
    engine's public analytics.  Blackjack and slots are not supported
    (doubles/splits break the flat-stake model; slots exposes no
    closed-form outcome distribution) and return a clear error.
    """
    engine = _build_engine(game, config)
    game_cfg = _sizing_game_config(game.lower(), engine)
    with _quiet():
        result = sizing.survival_optimal_bet(
            bankroll,
            game_cfg,
            goal,
            target=target,
            n_rounds=n_rounds,
            min_bet=min_bet,
            max_bet=max_bet,
            bet_grid=bet_grid,
        )
    out = _jsonify(result)
    out["game"] = game.lower()
    out["config"] = _jsonify(engine.config())
    return out


@mcp.tool()
def session_start(
    starting_bankroll: float,
    stop_loss: Optional[float] = None,
    stop_win: Optional[float] = None,
    stop_loss_pct: Optional[float] = None,
    stop_win_pct: Optional[float] = None,
    allow_negative_bankroll: bool = False,
    started_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Open a bankroll session (exact-cent Decimal ledger) persisted as
    append-only JSONL under ``$SPINQUEST_HOME`` (default ``~/.spinquest_sim``).
    Money amounts must be exact cents; percent stops are fractions (0.25 =
    25%).  Stops are advisory: the first threshold crossed latches but never
    blocks recording.  Returns the session_id used by the other session tools.
    """
    sid = uuid.uuid4().hex
    sess = Session(
        starting_bankroll,
        stop_loss=stop_loss,
        stop_win=stop_win,
        stop_loss_pct=stop_loss_pct,
        stop_win_pct=stop_win_pct,
        started_at=started_at or _now_iso(),
        jsonl_path=_session_path(sid),
        allow_negative_bankroll=allow_negative_bankroll,
        session_id=sid,
    )
    with _SESS_LOCK:
        _SESSIONS[sid] = sess
    return _session_payload(sess)


@mcp.tool()
def session_record_bet(
    session_id: str,
    game: str,
    stake: float,
    multiplier: float,
    config: Optional[Dict[str, Any]] = None,
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    """Record one resolved bet on a session.  ``multiplier`` is the
    total-return multiple ('for one'): 0 = lost, 1 = push, 2 = even-money
    win, 2.5 = 3:2 blackjack win.  ``stake`` must be an exact cent amount.
    Pass the game's config dict (as used by game_odds) so strategy_report
    can attach exact analytics to this game.  Timestamp defaults to now
    (UTC).  Returns the immutable ledger record plus the running bankroll,
    P&L and advisory stop state.
    """
    sess = _get_session(session_id)
    # Session objects are not thread-safe and FastMCP may run sync tools on
    # concurrent worker threads: serialize ledger mutations.
    with _LEDGER_LOCK:
        record = sess.record_bet(
            game, config, stake, multiplier, timestamp or _now_iso()
        )
        return {
            "bet": _jsonify(record.to_json_dict()),
            "bankroll": str(sess.bankroll),
            "pnl": str(sess.pnl),
            "total_bets": len(sess.bets),
            "stopped": sess.stopped,
            "stop_reason": sess.stop_reason,
            "stop_seq": sess.stop_seq,
        }


@mcp.tool()
def session_status(session_id: str) -> Dict[str, Any]:
    """Full JSON summary of a session: bankroll, P&L, drawdown statistics
    (dollar and percent, worst episodes), per-game breakdown, stop state.
    Works for live sessions and for sessions reloaded from their JSONL
    ledger after a server restart.
    """
    return _session_payload(_get_session(session_id))


@mcp.tool()
def session_end(session_id: str) -> Dict[str, Any]:
    """Close a session: final summary, release the ledger file handle and
    drop the in-memory registration.  The JSONL ledger stays on disk, so
    session_status / strategy_report keep working afterwards (the ledger is
    reloaded on demand).
    """
    sess = _get_session(session_id)
    payload = _session_payload(sess)
    payload["ended"] = True
    sess.close()
    with _SESS_LOCK:
        _SESSIONS.pop(sess.session_id, None)
    return payload


@mcp.tool()
def strategy_report(session_id: str, title: Optional[str] = None) -> Dict[str, Any]:
    """Generate the self-contained HTML strategy tear sheet for a session
    (bankroll/underwater curves, realized-vs-expected edge with SE bands,
    z-score luck decomposition, drawdown episodes, stop-loss audit) and
    return the file path.  Exact engine analytics are attached for every
    game recorded under a single config that an engine can be built from;
    other games are reported on the realized side only.  Requires at least
    one recorded bet.
    """
    sess = _get_session(session_id)
    analytics = _session_analytics(sess)
    out_path = _reports_dir() / f"{sess.session_id}.html"
    with _quiet():
        report_mod.generate_report(
            sess,
            analytics=analytics or None,
            title=title or f"SpinQuest Strategy Report — {sess.session_id[:8]}",
            output_path=str(out_path),
        )
    return {
        "report_path": str(out_path),
        "session_id": sess.session_id,
        "total_bets": len(sess.bets),
        "analytics_games": sorted(analytics),
    }


@mcp.tool()
def verify_bet(
    game: str,
    server_seed: str,
    client_seed: str,
    nonce: int,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Replay one bet through the provably-fair scalar RNG (byte-exact
    HMAC-SHA256 port of Stake's published verifier) and return the fully
    derived outcome plus the seed-hash commitment.

    ``config`` selects the game configuration (same keys as game_odds) and
    may carry per-bet extras: keno ``selection`` (list of squares), mines
    ``reveal`` (tile order to reveal), video_poker ``holds`` (5 booleans;
    omitted = optimal play).  Crash verifies via the seed-pair mechanism
    (crash {target} config).
    """
    if not isinstance(nonce, int) or isinstance(nonce, bool):
        raise ValueError(f"nonce must be an integer, got {nonce!r}")
    if nonce < 0:
        raise ValueError(f"nonce must be >= 0, got {nonce}")
    cfg = dict(config or {})
    engine = _build_engine(game, cfg)
    game = game.lower()
    with _quiet():
        if game == "crash":
            result = engine.play_round_seedpair(server_seed, client_seed, nonce)
        elif game == "keno":
            sel = cfg.get("selection")
            result = engine.play_round(server_seed, client_seed, nonce, selection=sel)
        elif game == "mines":
            reveal = cfg.get("reveal")
            result = engine.play_round(server_seed, client_seed, nonce, picks=reveal)
        elif game == "video_poker":
            holds = cfg.get("holds")
            result = engine.play_round(server_seed, client_seed, nonce, holds=holds)
        else:
            result = engine.play_round(server_seed, client_seed, nonce)
    out = _jsonify(result)
    out["game"] = game
    out["server_seed_hash"] = hash_server_seed(server_seed)
    return out


if __name__ == "__main__":
    mcp.run()  # stdio transport
