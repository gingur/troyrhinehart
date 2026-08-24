"""Stake-style Plinko: 8-16 rows x low/medium/high risk.

Ground truth (references/stake/plinko.md, references/woo/plinko.md):

* Path mechanics — one 4-byte float per pin row; ``direction = floor(float * 2)``
  (0 = left, 1 = right).  A board with ``rows`` rows has ``rows + 1`` pockets,
  indexed 0..rows left to right; the landing pocket index equals the count of
  "right" events.  ``P(pocket k) = C(rows, k) / 2**rows`` (pure binomial —
  the Wizard of Odds methodology and Stake's own client-side helper).
* A drop consumes ``rows`` floats from cursor 0 of the bet's byte stream
  (2 HMAC increments cover the possible 16 decisions).
* Pocket multipliers are keyed by (risk, rows).  Stake serves the grid at
  runtime via the ``PlinkoPayouts`` GraphQL query and statically publishes,
  per config, the pocket count and min/max multiplier; the Wizard of Odds
  BGAMING analysis is configuration-identical (its published example tables —
  8/low and 16/medium — and its per-config RTP grid pin the same tables).
  ``PAYTABLES`` below is the standard Stake/BGAMING grid; every row is
  checked against everything the references publish by
  ``scripts/validate_plinko.py`` and ``tests/test_plinko.py``.

Provably-fair mechanics: both the scalar path
(:func:`spinquest_sim.rng.plinko_directions` over
:func:`spinquest_sim.rng.generate_floats`) and the vectorized path
(:meth:`spinquest_sim.rng.BulkRng.plinko_directions`) are the critic-verified
RNG core — this module adds no randomness of its own.
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
    "RISKS",
    "MIN_ROWS",
    "MAX_ROWS",
    "PAYTABLES",
    "pascal_probabilities",
    "Plinko",
]

RISKS: Tuple[str, ...] = ("low", "medium", "high")
MIN_ROWS = 8
MAX_ROWS = 16  # == sq_rng.EVENT_COUNTS["plinko"]

# 1M drops x up-to-16 float64 columns keeps per-chunk arrays ~128 MB
# (well under the project's 500 MB budget even with the floor/int64
# temporaries alive at the same time).
_SIM_CHUNK_ROUNDS = 1_000_000

# ---------------------------------------------------------------------------
# The 27-config multiplier grid (Stake Originals / BGAMING, x bet).
#
# Stored as the symmetric half from the EDGE pocket to the CENTER; the full
# pocket array (length rows + 1) is the half mirrored around the center
# (odd pocket counts share the single center value, even pocket counts repeat
# the innermost half value twice).  Half length = rows // 2 + 1.
#
# Reference anchors, all asserted by tests + validate_plinko.py:
#   - per-config pocket count / min / max: the three verbatim Stake tables
#     ("Playing Sizes") in references/stake/plinko.md section 4;
#   - full-table anchors: WoO 8/low  (5.6, 2.1, 1.1, 1, 0.5, 1, 1.1, 2.1, 5.6)
#     and 16/medium (110, 41, 10, 5, 3, 1.5, 1, 0.5, 0.3, mirrored);
#     16/high == the 1000x table WoO prints as BetFury "Red";
#   - Stake blog facts: 16/high max 1000x, second-to-last pocket 130x;
#   - analytic RTP == WoO's BGAMING RTP grid (medium & high columns exact to
#     the printed 2 decimals; see validate_plinko.py for the low column note).
# ---------------------------------------------------------------------------
PAYTABLES: Dict[Tuple[str, int], Tuple[float, ...]] = {
    # --- low risk ---
    ("low", 8): (5.6, 2.1, 1.1, 1, 0.5),
    ("low", 9): (5.6, 2, 1.6, 1, 0.7),
    ("low", 10): (8.9, 3, 1.4, 1.1, 1, 0.5),
    ("low", 11): (8.4, 3, 1.9, 1.3, 1, 0.7),
    ("low", 12): (10, 3, 1.6, 1.4, 1.1, 1, 0.5),
    ("low", 13): (8.1, 4, 3, 1.9, 1.2, 0.9, 0.7),
    ("low", 14): (7.1, 4, 1.9, 1.4, 1.3, 1.1, 1, 0.5),
    ("low", 15): (15, 8, 3, 2, 1.5, 1.1, 1, 0.7),
    ("low", 16): (16, 9, 2, 1.4, 1.4, 1.2, 1.1, 1, 0.5),
    # --- medium risk ---
    ("medium", 8): (13, 3, 1.3, 0.7, 0.4),
    ("medium", 9): (18, 4, 1.7, 0.9, 0.5),
    ("medium", 10): (22, 5, 2, 1.4, 0.6, 0.4),
    ("medium", 11): (24, 6, 3, 1.8, 0.7, 0.5),
    ("medium", 12): (33, 11, 4, 2, 1.1, 0.6, 0.3),
    ("medium", 13): (43, 13, 6, 3, 1.3, 0.7, 0.4),
    ("medium", 14): (58, 15, 7, 4, 1.9, 1, 0.5, 0.2),
    ("medium", 15): (88, 18, 11, 5, 3, 1.3, 0.5, 0.3),
    ("medium", 16): (110, 41, 10, 5, 3, 1.5, 1, 0.5, 0.3),
    # --- high risk ---
    ("high", 8): (29, 4, 1.5, 0.3, 0.2),
    ("high", 9): (43, 7, 2, 0.6, 0.2),
    ("high", 10): (76, 10, 3, 0.9, 0.3, 0.2),
    ("high", 11): (120, 14, 5.2, 1.4, 0.4, 0.2),
    ("high", 12): (170, 24, 8.1, 2, 0.7, 0.2, 0.2),
    ("high", 13): (260, 37, 11, 4, 1, 0.2, 0.2),
    ("high", 14): (420, 56, 18, 5, 1.9, 0.3, 0.2, 0.2),
    ("high", 15): (620, 83, 27, 8, 3, 0.5, 0.2, 0.2),
    ("high", 16): (1000, 130, 26, 9, 4, 2, 0.2, 0.2, 0.2),
}


def _full_table(half: Tuple[float, ...], rows: int) -> np.ndarray:
    """Mirror an edge-to-center half into the full (rows + 1)-pocket array."""
    if len(half) != rows // 2 + 1:
        raise ValueError(
            f"half table for {rows} rows must have {rows // 2 + 1} entries, "
            f"got {len(half)}"
        )
    if rows % 2 == 0:
        # odd pocket count: single shared center value
        mirrored = tuple(reversed(half[:-1]))
    else:
        # even pocket count: innermost value appears twice
        mirrored = tuple(reversed(half))
    return np.asarray(half + mirrored, dtype=np.float64)


def pascal_probabilities(rows: int) -> np.ndarray:
    """Pocket probabilities via Stake's own client helper (Pascal's triangle
    of 50/50 splits) — exactly ``C(rows, k) / 2**rows``.

    Direct port of the published JS ``probabilities(e)`` from the archived
    Stake Plinko chunk (references/stake/plinko.md section 3).
    """
    t = [1.0]
    for _ in range(rows):
        t = [0.5 * ((t[a - 1] if a > 0 else 0.0) + (t[a] if a < len(t) else 0.0))
             for a in range(len(t) + 1)]
    return np.asarray(t, dtype=np.float64)


class Plinko:
    """Plinko engine for ONE configuration (risk, rows), one unit staked.

    Provides the standard engine contract:

    (a) analytic paytable / probability / RTP / variance,
    (b) provably-fair single-round play on the scalar RNG path,
    (c) a vectorized :class:`BulkRng` simulator for 10M+ rounds,
    (d) the standard result dict {rtp, house_edge, std_per_unit, config}.

    >>> Plinko(rows=16, risk="medium").rtp     # doctest: +ELLIPSIS
    0.9898...

    Besides the 27-config Stake/BGAMING grid, :meth:`from_table` builds an
    engine from any explicit pocket multiplier array — the WoO page's
    CryptoGames and BetFury tables, for instance — so its published RTP/SD
    figures are directly checkable through the identical analytic formulas.
    """

    def __init__(self, rows: int, risk: str) -> None:
        risk = str(risk).lower()
        if risk not in RISKS:
            raise ValueError(f"risk must be one of {RISKS}, got {risk!r}")
        if not (isinstance(rows, (int, np.integer)) and not isinstance(rows, bool)):
            raise TypeError(f"rows must be an int, got {type(rows).__name__}")
        rows = int(rows)
        if not MIN_ROWS <= rows <= MAX_ROWS:
            raise ValueError(f"rows must be in {MIN_ROWS}..{MAX_ROWS}, got {rows}")
        self._init_common(rows, risk, _full_table(PAYTABLES[(risk, rows)], rows))

    @classmethod
    def from_table(cls, payouts, label: str = "custom") -> "Plinko":
        """Engine from an explicit full pocket multiplier array.

        ``payouts`` is the length-(rows + 1) pocket array, edge to edge;
        ``rows`` is inferred as ``len(payouts) - 1``.  Same binomial pocket
        model and analytic surface as the grid configs (used to check the
        WoO CryptoGames / BetFury published RTP + SD figures).  The
        vectorized provably-fair simulator still requires 8..16 rows (the
        verified rng contract); analytic math works for any rows >= 1.
        """
        arr = np.asarray(payouts, dtype=np.float64)
        if arr.ndim != 1 or arr.size < 2:
            raise ValueError(
                f"payouts must be a 1-D array of >= 2 pocket multipliers, "
                f"got shape {arr.shape}"
            )
        if not np.all(np.isfinite(arr)) or np.any(arr < 0):
            raise ValueError("payouts must all be finite and >= 0")
        self = object.__new__(cls)
        self._init_common(int(arr.size - 1), str(label), arr.copy())
        return self

    def _init_common(self, rows: int, risk: str, payouts: np.ndarray) -> None:
        self.rows = rows
        self.risk = risk
        self.payouts: np.ndarray = payouts
        self.payouts.setflags(write=False)
        # Exact rational copies (Fraction over the shortest decimal repr, which
        # round-trips every published table entry) so every analytic quantity
        # below is exact; floats only at the API edge.
        self._mult_exact: Tuple[Fraction, ...] = tuple(
            Fraction(str(float(m))) for m in payouts
        )
        # exact binomial pocket probabilities: C(rows, k) / 2**rows
        self._prob_exact: Tuple[Fraction, ...] = tuple(
            Fraction(math.comb(rows, k), 2 ** rows) for k in range(rows + 1)
        )
        self._combinations = np.asarray(
            [math.comb(rows, k) for k in range(rows + 1)], dtype=np.float64
        )
        self.probabilities: np.ndarray = self._combinations / float(2 ** rows)
        self.probabilities.setflags(write=False)

    # ------------------------------------------------------------------
    # (a) analytics — exact rational arithmetic, converted at the edge
    # ------------------------------------------------------------------

    @property
    def pockets(self) -> int:
        return self.rows + 1

    def paytable(self) -> List[Dict[str, float]]:
        """Per-pocket analytic table, WoO-style: combinations, probability,
        multiplier, and return contribution."""
        return [
            {
                "pocket": k,
                "combinations": int(self._combinations[k]),
                "probability": float(self.probabilities[k]),
                "multiplier": float(self.payouts[k]),
                "return": float(self._prob_exact[k] * self._mult_exact[k]),
            }
            for k in range(self.pockets)
        ]

    @property
    def rtp_exact(self) -> Fraction:
        """Exact analytic RTP: sum_k C(rows,k)/2^rows * multiplier_k."""
        return sum(
            (p * m for p, m in zip(self._prob_exact, self._mult_exact)),
            Fraction(0),
        )

    @property
    def rtp(self) -> float:
        return float(self.rtp_exact)

    @property
    def house_edge(self) -> float:
        return float(1 - self.rtp_exact)

    @property
    def variance_exact(self) -> Fraction:
        """Exact Var of the for-one payout X per unit staked: E[X^2] - EV^2
        (identical to the variance of the NET result X - 1, matching the WoO
        per-unit SD convention)."""
        ex2 = sum(
            (p * m * m for p, m in zip(self._prob_exact, self._mult_exact)),
            Fraction(0),
        )
        return ex2 - self.rtp_exact * self.rtp_exact

    @property
    def variance_per_unit(self) -> float:
        return float(self.variance_exact)

    @property
    def std_per_unit(self) -> float:
        """Per-drop standard deviation of the multiplier, per unit bet
        (the WoO 'standard deviation' convention)."""
        return math.sqrt(self.variance_per_unit)

    @property
    def max_multiplier(self) -> float:
        return float(max(self._mult_exact))

    def config(self) -> Dict[str, object]:
        return {
            "game": "plinko",
            "risk": self.risk,
            "rows": self.rows,
            "pockets": self.pockets,
            # render exactly like the published tables: 110 not 110.0
            "payouts": [int(x) if float(x).is_integer() else float(x)
                        for x in self.payouts],
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
        self,
        server_seed: str,
        client_seed: str,
        nonce: int,
        bet: float = 1.0,
    ) -> Dict[str, object]:
        """Play one verifiable drop: ``rows`` floats from cursor 0 of the
        bet's HMAC-SHA256 stream; ``direction = floor(float * 2)``; the
        landing pocket is the count of rights.  The directions come from the
        critic-verified scalar RNG port of Stake's published verifier; the
        returned dict carries everything needed to re-verify the round
        externally."""
        if not isinstance(server_seed, str) or not server_seed:
            raise ValueError(
                "server_seed must be a non-empty string (Stake publishes a "
                "64-character hex seed; an empty seed is not a reachable state)"
            )
        nonce = sq_rng._check_nonce(nonce)
        if nonce < 0:
            raise ValueError(
                f"nonce must be >= 0 (it counts bets made), got {nonce}"
            )
        bet = float(bet)
        if not math.isfinite(bet) or bet < 0:
            raise ValueError(f"bet must be a finite value >= 0, got {bet!r}")
        floats = sq_rng.generate_floats(
            server_seed, client_seed, nonce, cursor=0, count=self.rows
        )
        directions = sq_rng.plinko_directions(floats)
        pocket = sum(directions)
        multiplier = float(self.payouts[pocket])
        return {
            "game": "plinko",
            "risk": self.risk,
            "rows": self.rows,
            "server_seed": server_seed,
            "server_seed_hash": sq_rng.hash_server_seed(server_seed),
            "client_seed": client_seed,
            "nonce": int(nonce),
            "floats": floats,
            "directions": directions,
            "path": "".join("R" if d else "L" for d in directions),
            "pocket": pocket,
            "multiplier": multiplier,
            "bet": float(bet),
            "payout": float(bet) * multiplier,
        }

    # ------------------------------------------------------------------
    # (c) vectorized simulator
    # ------------------------------------------------------------------

    def simulate(
        self,
        n_rounds: int,
        bulk: Optional[BulkRng] = None,
        chunk_rounds: int = _SIM_CHUNK_ROUNDS,
        progress: bool = True,
    ) -> Dict[str, object]:
        """Simulate ``n_rounds`` provably-fair drops (one nonce per drop) on
        the vectorized :class:`BulkRng` stream and return the standard result
        dict.

        Chunked so per-chunk arrays stay well under 500 MB (the campaign is
        accumulated as a per-pocket ``np.bincount`` histogram); prints
        progress for long campaigns.  Row i of the campaign is bit-for-bit
        verifiable against the scalar path at nonce ``nonce_start + i``.
        Empirical RTP and SD are computed from the histogram in exact
        arithmetic.
        """
        if n_rounds <= 0:
            raise ValueError("n_rounds must be positive")
        if chunk_rounds < 1:
            raise ValueError(f"chunk_rounds must be >= 1, got {chunk_rounds}")
        if not MIN_ROWS <= self.rows <= MAX_ROWS:
            raise ValueError(
                f"the provably-fair stream covers {MIN_ROWS}..{MAX_ROWS} "
                f"rows, got {self.rows}"
            )
        rng = bulk if bulk is not None else BulkRng()
        nonce_first = rng.nonce_next
        counts = np.zeros(self.pockets, dtype=np.int64)
        done = 0
        t0 = time.perf_counter()
        while done < n_rounds:
            step = min(chunk_rounds, n_rounds - done)
            pockets = rng.plinko_directions(self.rows, step).sum(axis=1)
            counts += np.bincount(pockets, minlength=self.pockets)
            done += step
            if progress and n_rounds > chunk_rounds:
                rate = done / (time.perf_counter() - t0)
                print(
                    f"  plinko {self.risk}/{self.rows}: "
                    f"{done:,}/{n_rounds:,} drops ({rate:,.0f}/s)",
                    flush=True,
                )
        elapsed = time.perf_counter() - t0
        return self.summarize_counts(
            counts,
            elapsed_s=elapsed,
            verification={
                "server_seed_hash": rng.server_seed_hash,
                "client_seed": rng.client_seed,
                "nonce_range": (nonce_first, rng.nonce_next),
            },
        )

    def summarize_counts(
        self,
        pocket_counts: np.ndarray,
        elapsed_s: Optional[float] = None,
        verification: Optional[Dict[str, object]] = None,
    ) -> Dict[str, object]:
        """Standard result dict from per-pocket landing counts (also used by
        the validation script, which settles all three risk settings against
        one shared direction stream per row count).

        Aggregation is exact: the total payout and its square are summed as
        rationals over the histogram, so empirical RTP/SD carry no float
        accumulation error.
        """
        pocket_counts = np.asarray(pocket_counts, dtype=np.int64)
        if pocket_counts.shape != (self.pockets,):
            raise ValueError(
                f"expected {self.pockets} pocket counts, got {pocket_counts.shape}"
            )
        n = int(pocket_counts.sum())
        if n <= 0:
            raise ValueError("no rounds in pocket_counts")
        counts = [int(c) for c in pocket_counts]
        total = sum(m * c for m, c in zip(self._mult_exact, counts))
        total_sq = sum(m * m * c for m, c in zip(self._mult_exact, counts))
        rtp_emp = float(Fraction(total) / n)
        var_emp = float(Fraction(total_sq) / n) - rtp_emp ** 2
        std_emp = math.sqrt(max(var_emp, 0.0))
        se_analytic = self.std_per_unit / math.sqrt(n)
        z = (rtp_emp - self.rtp) / se_analytic if se_analytic > 0 else 0.0
        out: Dict[str, object] = {
            "rtp": rtp_emp,
            "house_edge": 1.0 - rtp_emp,
            "std_per_unit": std_emp,
            "config": self.config(),
            "n_rounds": n,
            "pocket_counts": counts,
            "total_payout": float(total),
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
