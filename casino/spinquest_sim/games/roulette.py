"""Stake-style Roulette (European single-zero wheel, 37 pockets 0-36).

Math (references/stake/roulette.md — Stake's published pages, verbatim):

    pocket = Math.floor(float * 37)          # uniform, 1/37 each
    every standard bet pays (36 / coverage)x total return, so

    RTP = coverage/37 * 36/coverage = 36/37 = 97.2973%  (house edge 1/37)

identically for EVERY bet type — bet choice changes only volatility
(references/woo/roulette.md: "bet choice changes only volatility, not
expected return").  Published odds (winnings : stake):

    straight 35:1, split 17:1, street 11:1, corner 8:1, line 5:1,
    dozen 2:1, column 2:1, red/black 1:1, odd/even 1:1, high/low 1:1.

The five-number bet (6:1) exists only on double-zero American wheels and is
deliberately NOT implemented (the Stake reference: "it does not apply to the
Stake Original, which is single-zero").  A pocket of 0 loses every bet that
does not cover 0 — 0 is neither red/black, odd/even, nor high/low.

Provably-fair mechanics: one spin consumes one float (cursor 0, first 4
bytes of the first HMAC-SHA256 digest).  Both the scalar path
(:func:`spinquest_sim.rng.roulette_pocket` over
:func:`spinquest_sim.rng.generate_floats`) and the vectorized path
(:meth:`spinquest_sim.rng.BulkRng.roulette_pockets`) are the critic-verified
RNG core — this module adds no randomness of its own.

Lattice note: Stake's published float has exact granularity 1/2**32, and
2**32 mod 37 == 7, so 7 of the 37 pockets carry one extra lattice point.
The implemented wheel is therefore faithful to Stake's algorithm but not
mathematically perfectly uniform: per-pocket probability is
floor-or-ceil(2**32 / 37) / 2**32, a maximum relative deviation of
37/2**32 ≈ 8.6e-9 from 1/37 (undetectable even at 10M spins — |ΔRTP| <
1e-8).  The ``*_exact`` analytics in this module (``rtp_exact == 36/37``
etc.) describe the IDEAL 37-pocket wheel, which is the published model;
the lattice deviation is documented here rather than modeled.
"""

from __future__ import annotations

import math
import time
from fractions import Fraction
from typing import Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from spinquest_sim import rng as sq_rng
from spinquest_sim.rng import BulkRng

__all__ = [
    "POCKETS",
    "RED_NUMBERS",
    "BLACK_NUMBERS",
    "PAYOUT_ODDS",
    "BET_TYPES",
    "pocket_color",
    "all_splits",
    "all_streets",
    "zero_trios",
    "all_corners",
    "first_four",
    "all_lines",
    "dozen_pockets",
    "column_pockets",
    "all_bets",
    "full_payout_table",
    "settle_bets",
    "Roulette",
]

POCKETS = 37                      # 0..36, single zero
_GRID_ROWS = 12                   # 3-column x 12-row betting mat for 1..36

# Standard European wheel colors, verbatim from references/stake/roulette.md
# ("there is only one green number"; green = 0).
RED_NUMBERS = frozenset(
    {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
)
BLACK_NUMBERS = frozenset(range(1, POCKETS)) - RED_NUMBERS

# Published winnings-odds (n : 1) per bet type — references/stake/roulette.md
# section 5.  Total-return multiplier is odds + 1 == 36 / coverage for every
# type (asserted below).
PAYOUT_ODDS: Dict[str, int] = {
    "straight": 35,
    "split": 17,
    "street": 11,
    "corner": 8,
    "line": 5,
    "dozen": 2,
    "column": 2,
    "red": 1,
    "black": 1,
    "odd": 1,
    "even": 1,
    "low": 1,
    "high": 1,
}
BET_TYPES: Tuple[str, ...] = tuple(PAYOUT_ODDS)


def pocket_color(pocket: int) -> str:
    """'green' (0), 'red' or 'black' per the standard European wheel."""
    if not 0 <= pocket < POCKETS:
        raise ValueError(f"pocket must be in 0..36, got {pocket}")
    if pocket == 0:
        return "green"
    return "red" if pocket in RED_NUMBERS else "black"


# ---------------------------------------------------------------------------
# Bet enumeration (standard European betting mat: 0 on top, 1..36 in a
# 3-column x 12-row grid, row r = {3r+1, 3r+2, 3r+3})
# ---------------------------------------------------------------------------

def all_splits() -> List[Tuple[int, int]]:
    """All 60 legal splits: 24 horizontal (n, n+1 within a row), 33 vertical
    (n, n+3), and the 3 zero splits (0-1, 0-2, 0-3 — 0 borders the whole
    first row on the European mat)."""
    splits: List[Tuple[int, int]] = [(0, 1), (0, 2), (0, 3)]
    for n in range(1, POCKETS):
        if n % 3 != 0 and n + 1 <= 36:          # horizontal neighbour
            splits.append((n, n + 1))
        if n + 3 <= 36:                          # vertical neighbour
            splits.append((n, n + 3))
    return splits


def all_streets() -> List[Tuple[int, int, int]]:
    """All 12 streets (rows of three): (3r+1, 3r+2, 3r+3), r = 0..11."""
    return [(3 * r + 1, 3 * r + 2, 3 * r + 3) for r in range(_GRID_ROWS)]


def zero_trios() -> List[Tuple[int, int, int]]:
    """The 2 zero trios on the single-zero mat: 0-1-2 and 0-2-3.

    They follow from the SAME zero/first-row adjacency that legalizes the
    zero splits (0-1, 0-2, 0-3): the chip sits on the corner shared by 0 and
    two first-row numbers.  A trio covers 3 pockets and settles as a street
    (11:1); the exact 36/coverage identity holds, so RTP is 36/37 like every
    other bet."""
    return [(0, 1, 2), (0, 2, 3)]


def all_corners() -> List[Tuple[int, int, int, int]]:
    """All 22 corners: (n, n+1, n+3, n+4) for n in columns 1-2 of rows 1-11."""
    return [
        (n, n + 1, n + 3, n + 4)
        for r in range(_GRID_ROWS - 1)
        for n in (3 * r + 1, 3 * r + 2)
    ]


def first_four() -> Tuple[int, int, int, int]:
    """The first-four / basket bet, unique to single-zero mats: 0-1-2-3
    (0 plus the whole first row).  Covers 4 pockets and settles as a corner
    (8:1) — again exactly 36/coverage, RTP 36/37.  (Distinct from the
    American five-number bet 0-00-1-2-3, which needs a double zero and is
    deliberately not implemented.)"""
    return (0, 1, 2, 3)


def all_lines() -> List[Tuple[int, ...]]:
    """All 11 six-lines (two adjacent rows): (n, ..., n+5), n = 1, 4, ..., 31."""
    return [tuple(range(3 * r + 1, 3 * r + 7)) for r in range(_GRID_ROWS - 1)]


def dozen_pockets(index: int) -> Tuple[int, ...]:
    """Dozen 1/2/3 -> pockets 1-12 / 13-24 / 25-36."""
    if index not in (1, 2, 3):
        raise ValueError(f"dozen index must be 1, 2 or 3, got {index}")
    return tuple(range(12 * index - 11, 12 * index + 1))


def column_pockets(index: int) -> Tuple[int, ...]:
    """Column 1/2/3 -> pockets {c, c+3, ..., c+33} (bottom/middle/top row of
    the mat: column 1 = 1,4,...,34)."""
    if index not in (1, 2, 3):
        raise ValueError(f"column index must be 1, 2 or 3, got {index}")
    return tuple(range(index, 37, 3))


_EVEN_MONEY_POCKETS: Dict[str, Tuple[int, ...]] = {
    "red": tuple(sorted(RED_NUMBERS)),
    "black": tuple(sorted(BLACK_NUMBERS)),
    "odd": tuple(range(1, 37, 2)),
    "even": tuple(range(2, 37, 2)),       # 0 is NOT even for betting purposes
    "low": tuple(range(1, 19)),           # 1-18
    "high": tuple(range(19, 37)),         # 19-36
}

# Legal-selection lookup per multi-pocket inside bet type.  The zero trios
# settle as streets and the first four as a corner (coverage-matched odds:
# 11:1 on 3 pockets, 8:1 on 4 pockets), completing the standard 157-bet
# European catalogue.
_LEGAL_SETS: Dict[str, Dict[frozenset, Tuple[int, ...]]] = {
    "split": {frozenset(s): s for s in all_splits()},
    "street": {frozenset(s): s for s in all_streets() + zero_trios()},
    "corner": {frozenset(s): s for s in all_corners() + [first_four()]},
    "line": {frozenset(s): s for s in all_lines()},
}


def all_bets() -> List[Tuple[str, object]]:
    """Every legal (bet_type, selection) — the standard 157-bet European
    catalogue: 37 straight + 60 split + (12 street + 2 zero trios)
    + (22 corner + 1 first-four) + 11 line + 3 dozen + 3 column
    + 6 even-money."""
    bets: List[Tuple[str, object]] = [("straight", n) for n in range(POCKETS)]
    bets += [("split", s) for s in all_splits()]
    bets += [("street", s) for s in all_streets() + zero_trios()]
    bets += [("corner", s) for s in all_corners() + [first_four()]]
    bets += [("line", s) for s in all_lines()]
    bets += [("dozen", i) for i in (1, 2, 3)]
    bets += [("column", i) for i in (1, 2, 3)]
    bets += [(t, None) for t in _EVEN_MONEY_POCKETS]
    return bets


def full_payout_table() -> Dict[str, Dict[str, object]]:
    """Per bet type: published odds, total-return multiplier, coverage, win
    probability, RTP, house edge, per-unit SD — all analytic."""
    table: Dict[str, Dict[str, object]] = {}
    for bet_type in BET_TYPES:
        eng = Roulette(*_CANONICAL[bet_type])
        table[bet_type] = {
            "payout_odds": f"{eng.payout_odds}:1",
            "multiplier": eng.multiplier,
            "coverage": eng.coverage,
            "win_probability": eng.win_probability,
            "rtp": eng.rtp,
            "house_edge": eng.house_edge,
            "std_per_unit": eng.std_per_unit,
        }
    return table


# One canonical bet per type (used by full_payout_table; coverage/odds — and
# therefore all analytics — are identical across selections of a type).
_CANONICAL: Dict[str, Tuple[str, object]] = {
    "straight": ("straight", 17),
    "split": ("split", (17, 20)),
    "street": ("street", (1, 2, 3)),
    "corner": ("corner", (1, 2, 4, 5)),
    "line": ("line", (1, 2, 3, 4, 5, 6)),
    "dozen": ("dozen", 1),
    "column": ("column", 1),
    "red": ("red", None),
    "black": ("black", None),
    "odd": ("odd", None),
    "even": ("even", None),
    "low": ("low", None),
    "high": ("high", None),
}


def _validate_pockets(pockets: np.ndarray) -> np.ndarray:
    """Range/dtype-check an array of spin results before settlement.

    Rejects non-integer dtypes and any value outside 0..36.  Without the low
    check, numpy fancy indexing would silently wrap negatives (-1 -> pocket
    36) and settlement would fabricate wins for impossible outcomes."""
    pockets = np.asarray(pockets)
    if pockets.size == 0:
        return pockets.astype(np.int64)
    if not np.issubdtype(pockets.dtype, np.integer):
        raise TypeError(
            f"pockets must be an integer array, got dtype {pockets.dtype}"
        )
    lo, hi = int(pockets.min()), int(pockets.max())
    if lo < 0 or hi >= POCKETS:
        raise ValueError(
            f"pockets must be in 0..36, got values in [{lo}, {hi}]"
        )
    return pockets


def settle_bets(
    pockets: np.ndarray, bets: Sequence["Roulette"]
) -> np.ndarray:
    """Settle a basket of simultaneous one-unit bets on shared spins.

    This is how roulette is actually played: several chips on one spin.
    Returns the TOTAL for-one payout per spin (total stake = ``len(bets)``
    units per spin); mean(result) / len(bets) estimates the basket's RTP,
    which is 36/37 regardless of composition (every component bet has
    identical EV — bet choice moves only variance/covariance)."""
    if not bets:
        raise ValueError("bets must be a non-empty sequence of Roulette bets")
    pockets = _validate_pockets(pockets)
    total = np.zeros(pockets.shape, dtype=np.float64)
    for bet in bets:
        total += np.where(bet._mask[pockets], bet.multiplier, 0.0)
    return total


class Roulette:
    """Roulette engine for ONE bet of one unit on the single-zero wheel.

    Provides the standard engine contract:

    (a) analytic paytable / probability / RTP / variance,
    (b) provably-fair single-round play on the scalar RNG path,
    (c) a vectorized :class:`BulkRng` simulator for 10M+ rounds,
    (d) the standard result dict {rtp, house_edge, std_per_unit, config}.
    """

    def __init__(self, bet_type: str, selection: object = None) -> None:
        if bet_type not in PAYOUT_ODDS:
            raise ValueError(
                f"unknown bet type {bet_type!r}; must be one of {BET_TYPES} "
                "(the five-number bet exists only on double-zero wheels)"
            )
        self.bet_type = bet_type
        self.selection, pockets = self._resolve(bet_type, selection)
        self.covered = frozenset(pockets)
        self.coverage = len(self.covered)
        self.payout_odds = PAYOUT_ODDS[bet_type]
        self._mult_exact = Fraction(self.payout_odds + 1)
        # Structural identity behind the uniform house edge: for every
        # standard bet, total return odds+1 == 36/coverage exactly.
        assert self._mult_exact == Fraction(36, self.coverage)
        self._mask = np.zeros(POCKETS, dtype=bool)
        self._mask[sorted(self.covered)] = True

    @staticmethod
    def _resolve(bet_type: str, selection: object) -> Tuple[object, Sequence[int]]:
        if bet_type == "straight":
            if not isinstance(selection, (int, np.integer)) or isinstance(
                selection, bool
            ):
                raise TypeError("straight bet needs an int pocket 0..36")
            n = int(selection)
            if not 0 <= n < POCKETS:
                raise ValueError(f"straight pocket must be in 0..36, got {n}")
            return n, (n,)
        if bet_type in _LEGAL_SETS:
            legal = _LEGAL_SETS[bet_type]
            if selection is None or isinstance(selection, (int, np.integer)):
                raise TypeError(
                    f"{bet_type} bet needs a tuple of pockets, e.g. "
                    f"{next(iter(legal.values()))}"
                )
            key = frozenset(int(p) for p in selection)
            if key not in legal:
                raise ValueError(
                    f"{tuple(sorted(key))} is not a legal {bet_type} on the "
                    "European betting mat"
                )
            canonical = legal[key]
            return canonical, canonical
        if bet_type in ("dozen", "column"):
            if not isinstance(selection, (int, np.integer)) or isinstance(
                selection, bool
            ):
                raise TypeError(f"{bet_type} bet needs an index 1, 2 or 3")
            idx = int(selection)
            pockets = (
                dozen_pockets(idx) if bet_type == "dozen" else column_pockets(idx)
            )
            return idx, pockets
        # even-money bets take no selection
        if selection is not None:
            raise TypeError(f"{bet_type} bet takes no selection")
        return None, _EVEN_MONEY_POCKETS[bet_type]

    # ------------------------------------------------------------------
    # (a) analytics — exact rational arithmetic, converted at the edge
    # ------------------------------------------------------------------

    @property
    def multiplier_exact(self) -> Fraction:
        """Total-return multiplier (for-one), exact: odds + 1 = 36/coverage."""
        return self._mult_exact

    @property
    def multiplier(self) -> float:
        return float(self._mult_exact)

    @property
    def win_probability_exact(self) -> Fraction:
        return Fraction(self.coverage, POCKETS)

    @property
    def win_probability(self) -> float:
        return float(self.win_probability_exact)

    @property
    def rtp_exact(self) -> Fraction:
        """Exact analytic RTP: multiplier * P(win) = 36/37 for every bet.

        This is the ideal 37-pocket wheel; the implemented 2**32-lattice
        float deviates by at most ~8.6e-9 relative (see module docstring)."""
        return self._mult_exact * self.win_probability_exact

    @property
    def rtp(self) -> float:
        return float(self.rtp_exact)

    @property
    def house_edge(self) -> float:
        return float(1 - self.rtp_exact)

    @property
    def variance_per_unit(self) -> float:
        """Var of the for-one payout X per unit staked.

        X = M with prob p, 0 otherwise: Var = M^2 p - (M p)^2 — identical to
        the variance of the NET result X - 1, so it matches the Wizard of
        Odds per-unit SD convention (references/woo/roulette.md).
        """
        m, p = self._mult_exact, self.win_probability_exact
        return float(m * m * p - (m * p) ** 2)

    @property
    def std_per_unit(self) -> float:
        return math.sqrt(self.variance_per_unit)

    def config(self) -> Dict[str, object]:
        return {
            "game": "roulette",
            "wheel": "european_single_zero",
            "pockets": POCKETS,
            "bet_type": self.bet_type,
            "selection": self.selection,
            "covered": sorted(self.covered),
            "coverage": self.coverage,
            "payout_odds": f"{self.payout_odds}:1",
            "multiplier": self.multiplier,
            "win_probability": self.win_probability,
        }

    def analytic_summary(self) -> Dict[str, object]:
        """Standard result dict, analytic (no simulation)."""
        return {
            "rtp": self.rtp,
            "house_edge": self.house_edge,
            "std_per_unit": self.std_per_unit,
            "config": self.config(),
        }

    # ------------------------------------------------------------------
    # (b) provably-fair single round (scalar verification path)
    # ------------------------------------------------------------------

    def play_round(
        self, server_seed: str, client_seed: str, nonce: int
    ) -> Dict[str, object]:
        """Play one verifiable spin: one float (cursor 0), pocket =
        floor(float * 37), settle this bet.  The pocket comes from the
        critic-verified scalar RNG port of Stake's published verifier; the
        returned dict carries everything needed to re-verify."""
        value = sq_rng.generate_floats(server_seed, client_seed, nonce, 0, 1)[0]
        pocket = sq_rng.roulette_pocket(value)
        win = pocket in self.covered
        return {
            "pocket": pocket,
            "color": pocket_color(pocket),
            "win": win,
            "payout": self.multiplier if win else 0.0,
            "multiplier": self.multiplier if win else 0.0,
            "float": value,
            "config": self.config(),
            "verification": {
                "server_seed": server_seed,
                "client_seed": client_seed,
                "nonce": nonce,
            },
        }

    # ------------------------------------------------------------------
    # (c) vectorized simulator
    # ------------------------------------------------------------------

    def payouts_for_pockets(self, pockets: np.ndarray) -> np.ndarray:
        """Settle this bet against an array of spin results (for-one payout
        per unit staked) — pure lookup, shared-spin evaluation across bets.

        Pockets are range-checked BOTH ways: values >= 37 would raise via
        numpy anyway, but negative values would silently wrap (numpy fancy
        indexing treats -1 as pocket 36) and pay out for an impossible
        outcome, so they are rejected explicitly."""
        return np.where(
            self._mask[_validate_pockets(pockets)], self.multiplier, 0.0
        )

    def simulate(
        self,
        n_rounds: int,
        bulk: Optional[BulkRng] = None,
        chunk_rounds: int = 2_000_000,
        progress: bool = True,
    ) -> Dict[str, object]:
        """Simulate ``n_rounds`` provably-fair spins (one nonce per spin) on
        the vectorized :class:`BulkRng` stream and return the standard result
        dict.  Chunked so per-chunk arrays stay small (2M spins -> ~32 MB);
        row i of the campaign is bit-for-bit verifiable against the scalar
        path at nonce ``nonce_start + i``."""
        if n_rounds <= 0:
            raise ValueError("n_rounds must be positive")
        rng = bulk if bulk is not None else BulkRng()
        nonce_first = rng.nonce_next
        wins = 0
        pocket_counts = np.zeros(POCKETS, dtype=np.int64)
        done = 0
        t0 = time.perf_counter()
        while done < n_rounds:
            step = min(chunk_rounds, n_rounds - done)
            pockets = rng.roulette_pockets(step)
            pocket_counts += np.bincount(pockets, minlength=POCKETS)
            wins += int(np.count_nonzero(self._mask[pockets]))
            done += step
            if progress and n_rounds > chunk_rounds:
                rate = done / (time.perf_counter() - t0)
                print(
                    f"  roulette {self.bet_type}: {done:,}/{n_rounds:,} spins "
                    f"({rate:,.0f}/s)",
                    flush=True,
                )
        elapsed = time.perf_counter() - t0

        mult = self.multiplier
        p_hat = wins / n_rounds
        rtp_emp = p_hat * mult
        se_analytic = self.std_per_unit / math.sqrt(n_rounds)
        std_emp = mult * math.sqrt(max(p_hat * (1.0 - p_hat), 0.0))
        z = (rtp_emp - self.rtp) / se_analytic if se_analytic > 0 else 0.0
        return {
            "rtp": rtp_emp,
            "house_edge": 1.0 - rtp_emp,
            "std_per_unit": std_emp,
            "config": self.config(),
            "n_rounds": n_rounds,
            "wins": wins,
            "win_rate": p_hat,
            "pocket_counts": pocket_counts,
            "analytic_rtp": self.rtp,
            "analytic_std_per_unit": self.std_per_unit,
            "se_rtp": se_analytic,
            "z_score": z,
            "within_3se": abs(z) <= 3.0,
            "elapsed_s": elapsed,
            "rounds_per_sec": n_rounds / elapsed if elapsed > 0 else float("inf"),
            "verification": {
                "server_seed_hash": rng.server_seed_hash,
                "client_seed": rng.client_seed,
                "nonce_range": (nonce_first, rng.nonce_next),
            },
        }
