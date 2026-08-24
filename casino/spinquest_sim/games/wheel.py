"""Stake-style Wheel (Stake Originals multiplier wheel).

Math (references/stake/wheel.md — Stake's published pages, verbatim):

    float   = generateFloats({serverSeed, clientSeed, nonce, cursor: 0})[0]
    segment = Math.floor(float * segments)     # uniform, 1/segments each
    payout  = bet * PAYOUTS[segments][risk][segment]

with ``segments in {10, 20, 30, 40, 50}`` and ``risk in {low, medium, high}``.
The 15 ``PAYOUTS`` arrays below are reproduced verbatim from Stake's published
provably-fair game-events page (references/stake/wheel.md section 3; the
per-segment tables in section 4 are the same arrays rendered row-by-row).

Published invariants (all verified exactly in this module and its tests):

- every configuration returns EV = (sum of multipliers) / segments = 0.99
  exactly -> 99% RTP / 1% house edge at every setting (section 6);
- low risk is the same repeating 10-segment block
  ``[1.5, 1.2, 1.2, 1.2, 0, 1.2, 1.2, 1.2, 1.2, 0]`` at every size;
- high risk pays a single segment (the last index) worth ``segments * 0.99``:
  9.90x / 19.80x / 29.70x / 39.60x / 49.50x, hit probability 1/segments;
- max wins match Stake's published summary table (section 5): low 1.50x,
  medium 3.00x (10-20 seg) / 4.00x (30) / 3.00x (40) / 5.00x (50).

references/woo/wheel.md documents that the Wizard of Odds has NO page for this
game, so the analytic target is Stake's own published table evaluated with the
WoO probability-times-pay methodology (return = sum p_i * pay_i "for one",
SD from sqrt(E[X^2] - EV^2)); per-configuration SD is computed here from the
pay tables directly, exactly as that reference prescribes.

Provably-fair mechanics: one spin consumes ONE float (cursor 0, first 4 bytes
of the first HMAC-SHA256 digest — Wheel is not in Stake's list of games with
more than one incremental number).  Both the scalar path
(:func:`spinquest_sim.rng.wheel_index` over
:func:`spinquest_sim.rng.generate_floats`) and the vectorized path
(:meth:`spinquest_sim.rng.BulkRng.wheel_indices`) are the critic-verified RNG
core — this module adds no randomness of its own.
"""

from __future__ import annotations

import math
import time
from fractions import Fraction
from typing import Dict, List, Optional, Tuple

import numpy as np

from spinquest_sim import rng as sq_rng
from spinquest_sim.rng import BulkRng

__all__ = [
    "SEGMENT_COUNTS",
    "RISKS",
    "PAYOUTS",
    "all_configs",
    "full_analytic_table",
    "Wheel",
]

SEGMENT_COUNTS: Tuple[int, ...] = (10, 20, 30, 40, 50)
RISKS: Tuple[str, ...] = ("low", "medium", "high")

# Low risk: identical repeating 10-segment block at every segments setting
# (references/stake/wheel.md sections 3-4; the reference's structural note
# calls this out explicitly).
_LOW_BLOCK: Tuple[float, ...] = (1.5, 1.2, 1.2, 1.2, 0, 1.2, 1.2, 1.2, 1.2, 0)

# High risk: one paying segment (the LAST index) worth segments * 0.99;
# every other segment pays 0 (verbatim arrays: 9.9 / 19.8 / 29.7 / 39.6 / 49.5).
_HIGH_TOP: Dict[int, float] = {10: 9.9, 20: 19.8, 30: 29.7, 40: 39.6, 50: 49.5}

# Full PAYOUTS config, verbatim from Stake's published game-events page
# (references/stake/wheel.md section 3).  Medium arrays are written out in
# full; low/high use the exact published block structure (the validation
# script re-parses the reference tables and compares every one of the 150
# segment multipliers element-for-element, so this construction cannot drift).
PAYOUTS: Dict[int, Dict[str, Tuple[float, ...]]] = {
    10: {
        "low": _LOW_BLOCK,
        "medium": (0, 1.9, 0, 1.5, 0, 2, 0, 1.5, 0, 3),
        "high": (0,) * 9 + (_HIGH_TOP[10],),
    },
    20: {
        "low": _LOW_BLOCK * 2,
        "medium": (
            1.5, 0, 2, 0, 2, 0, 2, 0, 1.5, 0,
            3, 0, 1.8, 0, 2, 0, 2, 0, 2, 0,
        ),
        "high": (0,) * 19 + (_HIGH_TOP[20],),
    },
    30: {
        "low": _LOW_BLOCK * 3,
        "medium": (
            1.5, 0, 1.5, 0, 2, 0, 1.5, 0, 2, 0,
            2, 0, 1.5, 0, 3, 0, 1.5, 0, 2, 0,
            2, 0, 1.7, 0, 4, 0, 1.5, 0, 2, 0,
        ),
        "high": (0,) * 29 + (_HIGH_TOP[30],),
    },
    40: {
        "low": _LOW_BLOCK * 4,
        "medium": (
            2, 0, 3, 0, 2, 0, 1.5, 0, 3, 0,
            1.5, 0, 1.5, 0, 2, 0, 1.5, 0, 3, 0,
            1.5, 0, 2, 0, 2, 0, 1.6, 0, 2, 0,
            1.5, 0, 3, 0, 1.5, 0, 2, 0, 1.5, 0,
        ),
        "high": (0,) * 39 + (_HIGH_TOP[40],),
    },
    50: {
        "low": _LOW_BLOCK * 5,
        "medium": (
            2, 0, 1.5, 0, 2, 0, 1.5, 0, 3, 0,
            1.5, 0, 1.5, 0, 2, 0, 1.5, 0, 3, 0,
            1.5, 0, 2, 0, 1.5, 0, 2, 0, 2, 0,
            1.5, 0, 3, 0, 1.5, 0, 2, 0, 1.5, 0,
            1.5, 0, 5, 0, 1.5, 0, 2, 0, 1.5, 0,
        ),
        "high": (0,) * 49 + (_HIGH_TOP[50],),
    },
}

# Structural sanity, checked at import time: array lengths and the published
# 99% RTP identity EV = (sum of multipliers) / segments = 99/100 EXACTLY for
# all 15 configurations (Fraction over the decimal strings, no fp round-off).
for _n in SEGMENT_COUNTS:
    for _r in RISKS:
        _arr = PAYOUTS[_n][_r]
        assert len(_arr) == _n, f"{_n}/{_r}: {len(_arr)} entries"
        _ev = sum(Fraction(str(_m)) for _m in _arr) / _n
        assert _ev == Fraction(99, 100), f"{_n}/{_r}: EV {_ev} != 99/100"
del _n, _r, _arr, _ev


def all_configs() -> List[Tuple[int, str]]:
    """All 15 (segments, risk) configurations."""
    return [(n, r) for n in SEGMENT_COUNTS for r in RISKS]


def full_analytic_table() -> Dict[str, Dict[str, object]]:
    """Analytic summary for every configuration, keyed '<segments>/<risk>'."""
    return {
        f"{n}/{r}": Wheel(n, r).analytic_summary() for n, r in all_configs()
    }


class Wheel:
    """Wheel engine for ONE configuration (segments, risk), one unit staked.

    Provides the standard engine contract:

    (a) analytic paytable / probability / RTP / variance,
    (b) provably-fair single-round play on the scalar RNG path,
    (c) a vectorized :class:`BulkRng` simulator for 10M+ rounds,
    (d) the standard result dict {rtp, house_edge, std_per_unit, config}.
    """

    def __init__(self, segments: int, risk: str) -> None:
        if segments not in SEGMENT_COUNTS:
            raise ValueError(
                f"segments must be one of {SEGMENT_COUNTS}, got {segments!r}"
            )
        if risk not in RISKS:
            raise ValueError(f"risk must be one of {RISKS}, got {risk!r}")
        self.segments = segments
        self.risk = risk
        self.multipliers: Tuple[float, ...] = PAYOUTS[segments][risk]
        # Exact rational copies (Fraction over the decimal strings) so every
        # analytic quantity below is exact; floats only at the API edge.
        self._mult_exact: Tuple[Fraction, ...] = tuple(
            Fraction(str(m)) for m in self.multipliers
        )
        self._pay_arr = np.asarray(self.multipliers, dtype=np.float64)

    # ------------------------------------------------------------------
    # (a) analytics — exact rational arithmetic, converted at the edge
    # ------------------------------------------------------------------

    @property
    def segment_probability_exact(self) -> Fraction:
        """P(any given segment) — uniform: 1/segments."""
        return Fraction(1, self.segments)

    @property
    def segment_probability(self) -> float:
        return float(self.segment_probability_exact)

    def paytable(self) -> Dict[float, float]:
        """Distinct multiplier -> probability (WoO prob-x-pay layout),
        descending by multiplier.  Probabilities sum to 1."""
        counts: Dict[float, int] = {}
        for m in self.multipliers:
            counts[float(m)] = counts.get(float(m), 0) + 1
        return {
            m: c / self.segments
            for m, c in sorted(counts.items(), reverse=True)
        }

    def paytable_exact(self) -> Dict[Fraction, Fraction]:
        """Exact form of :meth:`paytable` (Fraction multiplier -> Fraction p)."""
        counts: Dict[Fraction, int] = {}
        for m in self._mult_exact:
            counts[m] = counts.get(m, 0) + 1
        return {
            m: Fraction(c, self.segments)
            for m, c in sorted(counts.items(), reverse=True)
        }

    @property
    def max_multiplier(self) -> float:
        return float(max(self._mult_exact))

    @property
    def win_probability_exact(self) -> Fraction:
        """P(multiplier > 0)."""
        paying = sum(1 for m in self._mult_exact if m > 0)
        return Fraction(paying, self.segments)

    @property
    def win_probability(self) -> float:
        return float(self.win_probability_exact)

    @property
    def rtp_exact(self) -> Fraction:
        """Exact analytic RTP: sum(p_i * pay_i) = (sum multipliers)/segments —
        equals 99/100 for every configuration (asserted at import)."""
        return sum(self._mult_exact, Fraction(0)) / self.segments

    @property
    def rtp(self) -> float:
        return float(self.rtp_exact)

    @property
    def house_edge(self) -> float:
        return float(1 - self.rtp_exact)

    @property
    def variance_exact(self) -> Fraction:
        """Exact Var of the for-one payout X per unit staked:
        E[X^2] - EV^2 (identical to the variance of the NET result X - 1,
        matching the WoO per-unit SD convention)."""
        ex2 = sum((m * m for m in self._mult_exact), Fraction(0)) / self.segments
        return ex2 - self.rtp_exact * self.rtp_exact

    @property
    def variance_per_unit(self) -> float:
        return float(self.variance_exact)

    @property
    def std_per_unit(self) -> float:
        return math.sqrt(self.variance_per_unit)

    def config(self) -> Dict[str, object]:
        return {
            "game": "wheel",
            "segments": self.segments,
            "risk": self.risk,
            "multipliers": list(self.multipliers),
            "paytable": self.paytable(),
            "max_multiplier": self.max_multiplier,
            "segment_probability": self.segment_probability,
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
        """Play one verifiable spin: one float (cursor 0), segment =
        floor(float * segments), multiplier = PAYOUTS[segments][risk][segment].
        The segment comes from the critic-verified scalar RNG port of Stake's
        published verifier; the returned dict carries everything needed to
        re-verify the round externally."""
        value = sq_rng.generate_floats(server_seed, client_seed, nonce, 0, 1)[0]
        segment = sq_rng.wheel_index(value, self.segments)
        mult = float(self.multipliers[segment])
        return {
            "segment": segment,
            "multiplier": mult,
            "payout": mult,
            "win": mult > 0,
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

    def payouts_for_segments(self, segments: np.ndarray) -> np.ndarray:
        """Settle this configuration against an array of spin results
        (for-one payout per unit staked) — pure lookup, so several risk
        settings can share one spin sequence."""
        return self._pay_arr[segments]

    def payouts_for_floats(self, floats: np.ndarray) -> np.ndarray:
        """Settle directly from raw floats: floor(float * segments) then
        lookup — lets ALL 15 configurations share one float stream."""
        idx = np.floor(floats * self.segments).astype(np.int64)
        return self._pay_arr[idx]

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
        seg_counts = np.zeros(self.segments, dtype=np.int64)
        done = 0
        t0 = time.perf_counter()
        while done < n_rounds:
            step = min(chunk_rounds, n_rounds - done)
            idx = rng.wheel_indices(self.segments, step)
            seg_counts += np.bincount(idx, minlength=self.segments)
            done += step
            if progress and n_rounds > chunk_rounds:
                rate = done / (time.perf_counter() - t0)
                print(
                    f"  wheel {self.segments}/{self.risk}: "
                    f"{done:,}/{n_rounds:,} spins ({rate:,.0f}/s)",
                    flush=True,
                )
        elapsed = time.perf_counter() - t0
        return self.summarize_counts(
            seg_counts,
            elapsed_s=elapsed,
            verification={
                "server_seed_hash": rng.server_seed_hash,
                "client_seed": rng.client_seed,
                "nonce_range": (nonce_first, rng.nonce_next),
            },
        )

    def summarize_counts(
        self,
        seg_counts: np.ndarray,
        elapsed_s: Optional[float] = None,
        verification: Optional[Dict[str, object]] = None,
    ) -> Dict[str, object]:
        """Standard result dict from per-segment hit counts (also used by the
        validation script, which settles all 15 configurations against shared
        spin streams)."""
        seg_counts = np.asarray(seg_counts, dtype=np.int64)
        if seg_counts.shape != (self.segments,):
            raise ValueError(
                f"expected {self.segments} segment counts, got {seg_counts.shape}"
            )
        n = int(seg_counts.sum())
        if n <= 0:
            raise ValueError("no rounds in seg_counts")
        rtp_emp = float(seg_counts @ self._pay_arr) / n
        ex2_emp = float(seg_counts @ (self._pay_arr**2)) / n
        std_emp = math.sqrt(max(ex2_emp - rtp_emp**2, 0.0))
        se_analytic = self.std_per_unit / math.sqrt(n)
        z = (rtp_emp - self.rtp) / se_analytic if se_analytic > 0 else 0.0
        wins = int(seg_counts[self._pay_arr > 0].sum())
        out: Dict[str, object] = {
            "rtp": rtp_emp,
            "house_edge": 1.0 - rtp_emp,
            "std_per_unit": std_emp,
            "config": self.config(),
            "n_rounds": n,
            "wins": wins,
            "win_rate": wins / n,
            "segment_counts": seg_counts,
            "analytic_rtp": self.rtp,
            "analytic_std_per_unit": self.std_per_unit,
            "se_rtp": se_analytic,
            "z_score": z,
            "within_3se": abs(z) <= 3.0,
        }
        if elapsed_s is not None:
            out["elapsed_s"] = elapsed_s
            out["rounds_per_sec"] = (
                n / elapsed_s if elapsed_s > 0 else float("inf")
            )
        if verification is not None:
            out["verification"] = verification
        return out
