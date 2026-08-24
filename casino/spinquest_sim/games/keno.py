"""Stake-style Keno (40-square board, pick 1-10, 10 drawn, 4 risk modes).

Math (references/stake/keno.md — Stake's published material + its own
paytable API, payout-for-payout):

    P(k hits | n selected) = C(n, k) * C(40 - n, 10 - k) / C(40, 10)

(hypergeometric — the same enumeration the Wizard of Odds uses for his
40-ball keno analysis, references/woo/keno.md).  The payout multiplier is a
pure table lookup on (risk, numbers selected, hits); the four risk tables
below are transcribed cell-for-cell from Stake's ``KenoPayouts`` API
response quoted in the reference.  Every one of the 40 (picks, risk)
configurations returns ~99% RTP, matching Stake's published "99% return to
player / 1% house edge".

Provably-fair mechanics (same reference): one round consumes 10 floats
(2 HMAC-SHA256 digests, cursor rounds 0-1); each float is mapped through a
partial Fisher-Yates over the 40 squares, so the 10 drawn numbers never
repeat.  Both the scalar path (:func:`spinquest_sim.rng.keno_hits`) and the
vectorized path (:meth:`spinquest_sim.rng.BulkRng.keno_hits`) are the
critic-verified RNG core — this module adds no randomness of its own.

Note: references/woo/keno.md has NO Stake-specific analysis; its closest
match is the Gamesys 40-ball game (same 40/10 draw structure, different
paytable, 95.66%-97.90% RTP).  ``scripts/validate_keno.py`` applies our
hypergeometric machinery to WoO's published 40-ball paytable and reproduces
his RTP column — methodology cross-check, not a paytable match.
"""

from __future__ import annotations

import math
import time
from fractions import Fraction
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from spinquest_sim import rng as sq_rng
from spinquest_sim.rng import BulkRng

__all__ = [
    "POOL_SIZE",
    "DRAW_COUNT",
    "MIN_PICKS",
    "MAX_PICKS",
    "RISKS",
    "PAYTABLES",
    "hit_probability_exact",
    "hit_probability",
    "paytable_exact",
    "paytable",
    "rtp",
    "house_edge",
    "std_per_unit",
    "full_rtp_table",
    "Keno",
]

POOL_SIZE = 40       # numbered squares 1..40
DRAW_COUNT = 10      # numbers drawn per round, without replacement
MIN_PICKS = 1
MAX_PICKS = 10
RISKS: Tuple[str, ...] = ("classic", "low", "medium", "high")

# Keep per-chunk arrays small: BulkRng.keno_hits(1M) peaks at ~378 MB
# (measured via tracemalloc, documented in spinquest_sim/rng.py), inside
# the 500 MB budget; the (1M, 10) int64 hits matrix itself is 80 MB.
_SIM_CHUNK_ROUNDS = 1_000_000

# ---------------------------------------------------------------------------
# Paytables — references/stake/keno.md §6, Stake's own KenoPayouts API,
# transcribed payout-for-payout.  Key: risk -> picks -> tuple indexed by
# hit count (length picks+1).  Values kept as strings so Fraction() stores
# them exactly (0.47 etc. are not exact binary floats).
# ---------------------------------------------------------------------------

_PAYTABLE_STRINGS: Dict[str, Dict[int, Tuple[str, ...]]] = {
    "classic": {
        1: ("0", "3.96"),
        2: ("0", "1.9", "4.5"),
        3: ("0", "1", "3.1", "10.4"),
        4: ("0", "0.8", "1.8", "5", "22.5"),
        5: ("0", "0.25", "1.4", "4.1", "16.5", "36"),
        6: ("0", "0", "1", "3.68", "7", "16.5", "40"),
        7: ("0", "0", "0.47", "3", "4.5", "14", "31", "60"),
        8: ("0", "0", "0", "2.2", "4", "13", "22", "55", "70"),
        9: ("0", "0", "0", "1.55", "3", "8", "15", "44", "60", "85"),
        10: ("0", "0", "0", "1.4", "2.25", "4.5", "8", "17", "50", "80", "100"),
    },
    "low": {
        1: ("0.7", "1.85"),
        2: ("0", "2", "3.8"),
        3: ("0", "1.1", "1.38", "26"),
        4: ("0", "0", "2.2", "7.9", "90"),
        5: ("0", "0", "1.5", "4.2", "13", "300"),
        6: ("0", "0", "1.1", "2", "6.2", "100", "700"),
        7: ("0", "0", "1.1", "1.6", "3.5", "15", "225", "700"),
        8: ("0", "0", "1.1", "1.5", "2", "5.5", "39", "100", "800"),
        9: ("0", "0", "1.1", "1.3", "1.7", "2.5", "7.5", "50", "250", "1000"),
        10: ("0", "0", "1.1", "1.2", "1.3", "1.8", "3.5", "13", "50", "250", "1000"),
    },
    "medium": {
        1: ("0.4", "2.75"),
        2: ("0", "1.8", "5.1"),
        3: ("0", "0", "2.8", "50"),
        4: ("0", "0", "1.7", "10", "100"),
        5: ("0", "0", "1.4", "4", "14", "390"),
        6: ("0", "0", "0", "3", "9", "180", "710"),
        7: ("0", "0", "0", "2", "7", "30", "400", "800"),
        8: ("0", "0", "0", "2", "4", "11", "67", "400", "900"),
        9: ("0", "0", "0", "2", "2.5", "5", "15", "100", "500", "1000"),
        10: ("0", "0", "0", "1.6", "2", "4", "7", "26", "100", "500", "1000"),
    },
    "high": {
        1: ("0", "3.96"),
        2: ("0", "0", "17.1"),
        3: ("0", "0", "0", "81.5"),
        4: ("0", "0", "0", "10", "259"),
        5: ("0", "0", "0", "4.5", "48", "450"),
        6: ("0", "0", "0", "0", "11", "350", "710"),
        7: ("0", "0", "0", "0", "7", "90", "400", "800"),
        8: ("0", "0", "0", "0", "5", "20", "270", "600", "900"),
        9: ("0", "0", "0", "0", "4", "11", "56", "500", "800", "1000"),
        10: ("0", "0", "0", "0", "3.5", "8", "13", "63", "500", "800", "1000"),
    },
}

PAYTABLES: Dict[str, Dict[int, Tuple[Fraction, ...]]] = {
    risk: {
        picks: tuple(Fraction(v) for v in row)
        for picks, row in tables.items()
    }
    for risk, tables in _PAYTABLE_STRINGS.items()
}


def _validate(picks: int, risk: str) -> str:
    if not isinstance(picks, (int, np.integer)) or isinstance(picks, bool):
        raise TypeError("picks must be an int")
    if not MIN_PICKS <= picks <= MAX_PICKS:
        raise ValueError(f"picks must be in {MIN_PICKS}..{MAX_PICKS}, got {picks}")
    if not isinstance(risk, str):
        raise TypeError("risk must be a str")
    risk_lc = risk.lower()
    if risk_lc not in RISKS:
        raise ValueError(f"risk must be one of {RISKS}, got {risk!r}")
    return risk_lc


# ---------------------------------------------------------------------------
# Analytics (module-level, exact rational arithmetic)
# ---------------------------------------------------------------------------

def hit_probability_exact(picks: int, hits: int) -> Fraction:
    """Exact P(hits | picks) = C(n,k) C(40-n,10-k) / C(40,10)."""
    _validate(picks, "classic")
    if not 0 <= hits <= picks:
        raise ValueError(f"hits must be in 0..{picks}, got {hits}")
    if DRAW_COUNT - hits > POOL_SIZE - picks:
        return Fraction(0)
    return Fraction(
        math.comb(picks, hits) * math.comb(POOL_SIZE - picks, DRAW_COUNT - hits),
        math.comb(POOL_SIZE, DRAW_COUNT),
    )


def hit_probability(picks: int, hits: int) -> float:
    return float(hit_probability_exact(picks, hits))


def paytable_exact(risk: str, picks: int) -> Tuple[Fraction, ...]:
    """Exact payout multipliers indexed by hit count (length picks+1)."""
    risk = _validate(picks, risk)
    return PAYTABLES[risk][picks]


def paytable(risk: str, picks: int) -> List[float]:
    return [float(v) for v in paytable_exact(risk, picks)]


def rtp_exact(risk: str, picks: int) -> Fraction:
    """Exact analytic RTP: sum_k pay[k] * P(k hits)."""
    pays = paytable_exact(risk, picks)
    return sum(
        (pays[k] * hit_probability_exact(picks, k) for k in range(picks + 1)),
        Fraction(0),
    )


def rtp(risk: str, picks: int) -> float:
    return float(rtp_exact(risk, picks))


def house_edge(risk: str, picks: int) -> float:
    return float(1 - rtp_exact(risk, picks))


def variance_exact(risk: str, picks: int) -> Fraction:
    """Exact Var(X) of the for-one payout: E[X^2] - E[X]^2."""
    pays = paytable_exact(risk, picks)
    ex = rtp_exact(risk, picks)
    ex2 = sum(
        (pays[k] ** 2 * hit_probability_exact(picks, k) for k in range(picks + 1)),
        Fraction(0),
    )
    return ex2 - ex * ex


def std_per_unit(risk: str, picks: int) -> float:
    return math.sqrt(float(variance_exact(risk, picks)))


def full_rtp_table() -> Dict[str, Dict[int, float]]:
    """{risk: {picks: analytic RTP}} for all 40 configurations."""
    return {
        r: {n: rtp(r, n) for n in range(MIN_PICKS, MAX_PICKS + 1)} for r in RISKS
    }


class Keno:
    """Keno engine for one (picks, risk) configuration.

    The player selects ``picks`` distinct numbers from 1..40 (default the
    first ``picks`` numbers — the draw is uniform without replacement, so
    which squares are selected is statistically irrelevant); the game draws
    10; the payout is the paytable entry for the hit count.  Provides

    (a) analytic paytable / probabilities / RTP / variance,
    (b) provably-fair single-round play on the scalar RNG path,
    (c) a vectorized :class:`BulkRng` simulator for 10M+ rounds,
    (d) the standard result dict {rtp, house_edge, std_per_unit, config}.
    """

    def __init__(self, picks: int, risk: str = "classic") -> None:
        self.risk = _validate(picks, risk)
        self.picks = int(picks)

    # ------------------------------------------------------------------
    # (a) analytics
    # ------------------------------------------------------------------

    @property
    def paytable_exact(self) -> Tuple[Fraction, ...]:
        return paytable_exact(self.risk, self.picks)

    @property
    def paytable(self) -> List[float]:
        return paytable(self.risk, self.picks)

    def hit_probabilities_exact(self) -> List[Fraction]:
        return [
            hit_probability_exact(self.picks, k) for k in range(self.picks + 1)
        ]

    def hit_probabilities(self) -> List[float]:
        return [float(p) for p in self.hit_probabilities_exact()]

    @property
    def rtp_exact(self) -> Fraction:
        return rtp_exact(self.risk, self.picks)

    @property
    def rtp(self) -> float:
        return float(self.rtp_exact)

    @property
    def house_edge(self) -> float:
        return float(1 - self.rtp_exact)

    @property
    def variance_per_unit(self) -> float:
        return float(variance_exact(self.risk, self.picks))

    @property
    def std_per_unit(self) -> float:
        return math.sqrt(self.variance_per_unit)

    @property
    def max_win(self) -> float:
        return float(max(self.paytable_exact))

    def config(self) -> Dict[str, object]:
        return {
            "game": "keno",
            "pool_size": POOL_SIZE,
            "draw_count": DRAW_COUNT,
            "picks": self.picks,
            "risk": self.risk,
            "paytable": self.paytable,
            "max_win": self.max_win,
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

    def _selection(self, selection: Optional[Sequence[int]]) -> List[int]:
        sel = (
            list(range(1, self.picks + 1))
            if selection is None
            else [int(n) for n in selection]
        )
        if len(sel) != self.picks:
            raise ValueError(f"need exactly {self.picks} numbers, got {len(sel)}")
        if len(set(sel)) != len(sel):
            raise ValueError("selected numbers must be distinct")
        if any(not 1 <= n <= POOL_SIZE for n in sel):
            raise ValueError(f"numbers must be in 1..{POOL_SIZE}")
        return sel

    def play_round(
        self,
        server_seed: str,
        client_seed: str,
        nonce: int,
        selection: Optional[Sequence[int]] = None,
    ) -> Dict[str, object]:
        """Play one verifiable round: draw 10 numbers, pay by hit count.

        The draw comes from the critic-verified scalar RNG port of Stake's
        published verifier (10 Fisher-Yates events over the 40 squares, 2
        HMAC digests / cursor rounds); the returned dict carries everything
        needed to re-verify.
        """
        sel = self._selection(selection)
        drawn = sq_rng.keno_hits(server_seed, client_seed, nonce)
        hits = sorted(set(sel) & set(drawn))
        n_hits = len(hits)
        payout = float(self.paytable_exact[n_hits])
        # Bet-record semantics: the stake is 1 unit, so profit is payout - 1
        # and a round only counts as a *win* when the payout exceeds the
        # stake.  Paytable cells in (0, 1] (e.g. Classic picks 3-7 partials,
        # Low/Medium pick-1 consolation) return money but are net losses or
        # pushes, never wins.
        profit = payout - 1.0
        return {
            "drawn": drawn,             # draw order, as generated
            "selection": sel,
            "hits": hits,
            "n_hits": n_hits,
            "payout": payout,
            "multiplier": payout,
            "profit": profit,
            "win": payout > 1.0,
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

    def simulate(
        self,
        n_rounds: int,
        bulk: Optional[BulkRng] = None,
        selection: Optional[Sequence[int]] = None,
        chunk_rounds: int = _SIM_CHUNK_ROUNDS,
        progress: bool = True,
    ) -> Dict[str, object]:
        """Simulate ``n_rounds`` provably-fair rounds (one nonce per round)
        on the vectorized :class:`BulkRng` stream and return the standard
        result dict.

        Chunked so per-chunk arrays stay well under 500 MB; prints progress
        for long campaigns.  Row i of the campaign is bit-for-bit verifiable
        against the scalar path at nonce ``nonce_start + i``.  Because the
        payout is a pure function of the hit count, the campaign is
        aggregated as an exact hit-count histogram — empirical RTP and SD
        are then computed from the histogram in exact arithmetic.
        """
        if n_rounds <= 0:
            raise ValueError("n_rounds must be positive")
        if chunk_rounds < 1:
            raise ValueError(
                f"chunk_rounds must be >= 1, got {chunk_rounds}"
            )
        rng = bulk if bulk is not None else BulkRng()
        sel = self._selection(selection)
        # Fast path: default prefix selection {1..picks} -> "drawn <= picks".
        prefix = sel == list(range(1, self.picks + 1))
        sel_arr = np.asarray(sel, dtype=np.int64)

        nonce_first = rng.nonce_next
        hist = np.zeros(self.picks + 1, dtype=np.int64)
        done = 0
        t0 = time.perf_counter()
        while done < n_rounds:
            step = min(chunk_rounds, n_rounds - done)
            drawn = rng.keno_hits(step)          # (step, 10), values 1..40
            if prefix:
                n_hits = np.count_nonzero(drawn <= self.picks, axis=1)
            else:
                n_hits = np.isin(drawn, sel_arr).sum(axis=1)
            hist += np.bincount(n_hits, minlength=self.picks + 1)
            done += step
            if progress and n_rounds > chunk_rounds:
                rate = done / (time.perf_counter() - t0)
                print(
                    f"  keno {self.risk} picks={self.picks}: "
                    f"{done:,}/{n_rounds:,} rounds ({rate:,.0f}/s)",
                    flush=True,
                )
        elapsed = time.perf_counter() - t0

        # Exact aggregation from the histogram (no float accumulation error).
        pays = self.paytable_exact
        counts = [int(c) for c in hist]
        total = sum(pays[k] * counts[k] for k in range(self.picks + 1))
        total_sq = sum(pays[k] ** 2 * counts[k] for k in range(self.picks + 1))
        rtp_emp = float(Fraction(total, n_rounds))
        var_emp = float(Fraction(total_sq, n_rounds)) - rtp_emp**2
        std_emp = math.sqrt(max(var_emp, 0.0))
        se_analytic = self.std_per_unit / math.sqrt(n_rounds)
        z = (rtp_emp - self.rtp) / se_analytic if se_analytic > 0 else 0.0
        return {
            "rtp": rtp_emp,
            "house_edge": 1.0 - rtp_emp,
            "std_per_unit": std_emp,
            "config": self.config(),
            "n_rounds": n_rounds,
            "hit_histogram": counts,
            "total_payout": float(total),
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
