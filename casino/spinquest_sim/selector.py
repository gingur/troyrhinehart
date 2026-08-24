"""Odds-ranked game selector.

Enumerates every playable configuration across the ten finished game
engines, pulls the analytic figures (RTP, house edge, per-unit standard
deviation) LIVE from the engine classes — the engines are the single
source of truth, nothing is hardcoded here — and ranks them by RTP with
variance and a bankroll-survival metric as secondary columns.

Public API
----------
enumerate_configs()  -> list[GameConfig]      the playable configuration grid
survival_probability(...) -> float            analytic ruin/survival approx
ranking(...)         -> pandas.DataFrame      RTP-ranked table
to_markdown(...)     -> str                   markdown rendering of ranking()

Configuration grid
------------------
* plinko        : rows 8..16 x risk {low, medium, high}          (27)
* mines         : every (mines m, picks k), 1<=m<=24, 1<=k<=25-m (300)
* keno          : picks 1..10 x risk {classic, low, medium, high} (40)
* wheel         : segments {10,20,30,40,50} x risk {low,medium,high} (15)
* blackjack     : basic strategy, default rules (S17, DAS, resplit
                  to 4, blackjack pays 3:2)                       (1)
* baccarat      : banker / player / tie                           (3)
* roulette      : all 13 European bet types (canonical selections
                  — every selection of a type has identical odds) (13)
* video poker   : full-pay 9/6 Jacks or Better + Stake's paytable (2)
* crash         : a ladder of cashout targets (CRASH_TARGETS)     (10)
* slots         : Atkins Diet (exact WoO par-sheet enumeration)   (1)

Scarab Spin slots is deliberately EXCLUDED: its bonus-chain
reconstruction is documented as under-determined by Stake's published
data (see the strict=False xfails in tests/test_slots.py and
gauntlet/slots/) and its current enumeration returns RTP > 1, which
would falsely top the ranking.  The validated slots model is Atkins.

Survival metric
---------------
``survival_probability`` is the probability of NOT going bankrupt
within ``rounds`` flat bets of size ``bet`` starting from bankroll
``bankroll``.  It is an ANALYTIC NORMAL (diffusion) APPROXIMATION: the
bankroll path is approximated by a Brownian motion with per-round drift
mu = (rtp - 1) * bet and per-round std sigma = std_per_unit * bet, and
the first-passage probability to the ruin barrier is

    P(ruin <= N) = Phi((-B - mu N) / (sigma sqrt(N)))
                 + exp(-2 mu B / sigma^2) * Phi((-B + mu N) / (sigma sqrt(N)))

(the classic reflection formula for drifted Brownian motion).  It is
labeled as such in the DataFrame (``df.attrs["survival_metric"]``).
The approximation is coarse for heavy-tailed games (keno high, plinko
high, slots) whose payout distributions are far from normal, and for
blackjack it treats the INITIAL bet as flat (doubles/splits put extra
money in play).  It is a comparison column, not a guarantee.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd
from scipy.stats import norm

from .games import baccarat as _baccarat
from .games import blackjack as _blackjack
from .games import crash as _crash
from .games import keno as _keno
from .games import mines as _mines
from .games import plinko as _plinko
from .games import roulette as _roulette
from .games import slots as _slots
from .games import video_poker as _video_poker
from .games import wheel as _wheel

__all__ = [
    "GameConfig",
    "CRASH_TARGETS",
    "enumerate_configs",
    "survival_probability",
    "ranking",
    "to_markdown",
]

# Representative ladder of crash cashout targets (the target space is
# continuous; RTP is ~0.99 everywhere modulo the 2^-32 quantization the
# engine computes exactly, so a ladder spans the variance axis).
CRASH_TARGETS: Tuple[float, ...] = (
    1.01, 1.1, 1.2, 1.5, 2.0, 3.0, 5.0, 10.0, 100.0, 1000.0
)

# Canonical roulette selections — every selection of a given bet type
# has identical analytic odds on the European mat, so one canonical
# representative per type covers the full odds space.
_ROULETTE_SELECTIONS: Dict[str, object] = {
    "straight": 17,
    "split": (17, 20),
    "street": (16, 17, 18),
    "corner": (16, 17, 19, 20),
    "line": (16, 17, 18, 19, 20, 21),
    "dozen": 1,
    "column": 1,
    "red": None,
    "black": None,
    "odd": None,
    "even": None,
    "low": None,
    "high": None,
}


@dataclass(frozen=True)
class GameConfig:
    """One playable configuration: a game, a human label, and a factory
    that builds the (critic-verified) engine instance for it."""

    game: str
    label: str
    build: Callable[[], object] = field(compare=False, repr=False)


def _selection_label(bet_type: str, selection: object) -> str:
    if selection is None:
        return bet_type
    if isinstance(selection, tuple):
        return f"{bet_type} {'-'.join(str(p) for p in selection)}"
    return f"{bet_type} {selection}"


def enumerate_configs() -> List[GameConfig]:
    """The full playable configuration grid, in a fixed deterministic
    order.  Factories are lazy — nothing expensive runs here."""
    configs: List[GameConfig] = []

    # video poker -----------------------------------------------------
    configs.append(GameConfig(
        "video_poker", "9/6 Jacks or Better",
        lambda: _video_poker.VideoPoker(_video_poker.BENCHMARK_9_6_PAYTABLE),
    ))
    configs.append(GameConfig(
        "video_poker", "Stake Jacks or Better",
        lambda: _video_poker.VideoPoker(_video_poker.STAKE_PAYTABLE),
    ))

    # blackjack -------------------------------------------------------
    configs.append(GameConfig(
        "blackjack", "basic strategy (S17, DAS, resplit to 4, 3:2)",
        lambda: _blackjack.Blackjack(),
    ))

    # baccarat --------------------------------------------------------
    for bet in _baccarat.BET_TYPES:
        configs.append(GameConfig(
            "baccarat", bet,
            lambda b=bet: _baccarat.Baccarat(b),
        ))

    # roulette --------------------------------------------------------
    for bet in _roulette.BET_TYPES:
        sel = _ROULETTE_SELECTIONS[bet]
        configs.append(GameConfig(
            "roulette", _selection_label(bet, sel),
            lambda b=bet, s=sel: _roulette.Roulette(b, s),
        ))

    # keno ------------------------------------------------------------
    for risk in _keno.RISKS:
        for picks in range(_keno.MIN_PICKS, _keno.MAX_PICKS + 1):
            configs.append(GameConfig(
                "keno", f"{risk}, {picks} picks",
                lambda p=picks, r=risk: _keno.Keno(p, r),
            ))

    # plinko ----------------------------------------------------------
    for risk in _plinko.RISKS:
        for rows in range(_plinko.MIN_ROWS, _plinko.MAX_ROWS + 1):
            configs.append(GameConfig(
                "plinko", f"{risk}, {rows} rows",
                lambda ro=rows, r=risk: _plinko.Plinko(ro, r),
            ))

    # mines -----------------------------------------------------------
    for m in range(_mines.MIN_MINES, _mines.MAX_MINES + 1):
        for k in range(1, _mines.GRID_TILES - m + 1):
            configs.append(GameConfig(
                "mines", f"{m} mines, {k} picks",
                lambda mm=m, kk=k: _mines.Mines(mm, kk),
            ))

    # wheel -----------------------------------------------------------
    for segments in _wheel.SEGMENT_COUNTS:
        for risk in _wheel.RISKS:
            configs.append(GameConfig(
                "wheel", f"{segments} segments, {risk}",
                lambda s=segments, r=risk: _wheel.Wheel(s, r),
            ))

    # crash -----------------------------------------------------------
    for target in CRASH_TARGETS:
        configs.append(GameConfig(
            "crash", f"cashout {target:g}x",
            lambda t=target: _crash.Crash(t),
        ))

    # slots (validated model only — see module docstring) -------------
    configs.append(GameConfig(
        "slots", "Atkins Diet (WoO par sheet)",
        lambda: _slots.atkins_machine(),
    ))

    return configs


@lru_cache(maxsize=1)
def _analytic_rows() -> Tuple[Tuple[str, str, float, float, float], ...]:
    """(game, label, rtp, house_edge, std_per_unit) for every config,
    pulled live from the engines.  Cached: building this once costs
    ~30-40 s (the two video-poker paytable solves and the exact Atkins
    enumeration dominate); every later call is free."""
    rows = []
    for cfg in enumerate_configs():
        engine = cfg.build()
        rtp = float(engine.rtp)
        house_edge = float(engine.house_edge)
        std = float(engine.std_per_unit)
        rows.append((cfg.game, cfg.label, rtp, house_edge, std))
    return tuple(rows)


def survival_probability(
    rtp: float,
    std_per_unit: float,
    bankroll: float,
    bet: float,
    rounds: int,
) -> float:
    """P(bankroll stays above 0 for ``rounds`` flat bets of ``bet``
    starting from ``bankroll``), by the drifted-Brownian-motion
    first-passage (normal/diffusion) approximation — see the module
    docstring for the formula and its limits.  Returns a float in
    [0, 1]."""
    if bankroll <= 0:
        return 0.0
    if bet <= 0:
        raise ValueError(f"bet must be positive, got {bet}")
    if rounds <= 0:
        raise ValueError(f"rounds must be positive, got {rounds}")
    mu = (rtp - 1.0) * bet          # net drift per round
    sigma = std_per_unit * bet      # net std per round
    if sigma == 0.0:
        # Deterministic path: ruin iff cumulative drift reaches -bankroll.
        return 0.0 if mu < 0 and rounds * (-mu) >= bankroll else 1.0
    sqrt_n = math.sqrt(rounds)
    b = float(bankroll)
    term1 = norm.cdf((-b - mu * rounds) / (sigma * sqrt_n))
    # exp(-2 mu B / sigma^2) can overflow for strongly negative drift;
    # its companion cdf is then vanishingly small, so combine in log
    # space: exp(a) * Phi(x) = exp(a + logPhi(x)).
    a = -2.0 * mu * b / (sigma * sigma)
    log_phi = norm.logcdf((-b + mu * rounds) / (sigma * sqrt_n))
    term2 = math.exp(min(a + log_phi, 0.0))
    p_ruin = term1 + term2
    return max(0.0, min(1.0, 1.0 - p_ruin))


def ranking(
    bankroll: float = 100.0,
    bet: float = 1.0,
    rounds: int = 200,
) -> pd.DataFrame:
    """Full RTP-ranked table of every playable configuration.

    Columns: ``rank``, ``game``, ``config``, ``rtp``, ``house_edge``,
    ``std_per_unit``, ``variance_per_unit``, ``survival_prob`` — the
    last being P(surviving ``rounds`` flat bets of ``bet`` from
    ``bankroll``) under the labeled normal approximation.  Sorted by
    RTP descending; ties broken by lower std, then game/config name
    (deterministic).  Analytic figures come live from the engines and
    are cached process-wide; only the survival column depends on the
    parameters."""
    df = pd.DataFrame(
        list(_analytic_rows()),
        columns=["game", "config", "rtp", "house_edge", "std_per_unit"],
    )
    df["variance_per_unit"] = df["std_per_unit"] ** 2
    df["survival_prob"] = [
        survival_probability(r, s, bankroll, bet, rounds)
        for r, s in zip(df["rtp"], df["std_per_unit"])
    ]
    df = df.sort_values(
        by=["rtp", "std_per_unit", "game", "config"],
        ascending=[False, True, True, True],
        kind="mergesort",
    ).reset_index(drop=True)
    df.insert(0, "rank", range(1, len(df) + 1))
    df.attrs["survival_metric"] = (
        "analytic normal (drifted-Brownian first-passage) approximation: "
        f"P(surviving {rounds} flat bets of {bet:g} from bankroll "
        f"{bankroll:g})"
    )
    df.attrs["survival_params"] = {
        "bankroll": float(bankroll), "bet": float(bet), "rounds": int(rounds),
    }
    return df


def to_markdown(
    df: Optional[pd.DataFrame] = None,
    top: Optional[int] = None,
    **ranking_kwargs: object,
) -> str:
    """Markdown rendering of a ranking table.

    ``df`` defaults to ``ranking(**ranking_kwargs)``; ``top`` truncates
    to the first N rows.  Percent columns are formatted to 4 significant
    decimals; the survival column's definition is appended as a
    footnote."""
    if df is None:
        df = ranking(**ranking_kwargs)  # type: ignore[arg-type]
    out = df.head(top) if top is not None else df
    shown = pd.DataFrame({
        "rank": out["rank"],
        "game": out["game"],
        "config": out["config"],
        "RTP": [f"{v * 100:.4f}%" for v in out["rtp"]],
        "house edge": [f"{v * 100:.4f}%" for v in out["house_edge"]],
        "std/unit": [f"{v:.4f}" for v in out["std_per_unit"]],
        "P(survive)": [f"{v:.4f}" for v in out["survival_prob"]],
    })
    body = shown.to_markdown(index=False)
    note = df.attrs.get(
        "survival_metric",
        "analytic normal approximation",
    )
    return f"{body}\n\nP(survive): {note}.\n"
