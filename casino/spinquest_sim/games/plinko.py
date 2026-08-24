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
  validated payout-for-payout against everything the references publish by
  ``scripts/validate_plinko.py`` and ``tests/test_plinko.py``.

Engine surfaces:

* analytic pocket probabilities / RTP / variance (exact, Fraction-free float64)
* provably-fair single-round :meth:`PlinkoEngine.play` on ``spinquest_sim.rng``
* vectorized simulators: :meth:`simulate` (fast numpy PCG64 binomial path,
  10M+ rounds in seconds) and :meth:`simulate_provably_fair` (the real
  HMAC-SHA256 stream via :class:`spinquest_sim.rng.BulkRng`, row-verifiable)
* a standard result dict ``{rtp, house_edge, std_per_unit, config}``.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import numpy as np

from spinquest_sim import rng as sq_rng

__all__ = [
    "RISKS",
    "MIN_ROWS",
    "MAX_ROWS",
    "PAYTABLES",
    "pascal_probabilities",
    "PlinkoEngine",
]

RISKS: Tuple[str, ...] = ("low", "medium", "high")
MIN_ROWS = 8
MAX_ROWS = 16  # == sq_rng.EVENT_COUNTS["plinko"]

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


class PlinkoEngine:
    """One (risk, rows) Plinko configuration.

    >>> eng = PlinkoEngine(rows=16, risk="medium")
    >>> eng.result()["rtp"]            # doctest: +ELLIPSIS
    0.9898...
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
        self.rows = rows
        self.risk = risk
        self.payouts: np.ndarray = _full_table(PAYTABLES[(risk, rows)], rows)
        self.payouts.setflags(write=False)
        # exact binomial pocket probabilities: C(rows, k) / 2**rows
        self._combinations = np.asarray(
            [math.comb(rows, k) for k in range(rows + 1)], dtype=np.float64
        )
        self.probabilities: np.ndarray = self._combinations / float(2 ** rows)
        self.probabilities.setflags(write=False)

    # ------------------------------------------------------------------ #
    # (a) analytic paytable / probability / RTP / variance
    # ------------------------------------------------------------------ #

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
                "return": float(self.probabilities[k] * self.payouts[k]),
            }
            for k in range(self.pockets)
        ]

    def rtp(self) -> float:
        """Expected multiplier per unit bet: sum p_k * m_k (exact float64 dot
        of exact binomial probabilities against the published table)."""
        return float(self.probabilities @ self.payouts)

    def house_edge(self) -> float:
        return 1.0 - self.rtp()

    def variance(self) -> float:
        """Per-drop variance of the multiplier, per unit bet."""
        mean = self.rtp()
        second = float(self.probabilities @ (self.payouts ** 2))
        return second - mean * mean

    def std_per_unit(self) -> float:
        """Per-drop standard deviation of the multiplier, per unit bet
        (the WoO 'standard deviation' convention)."""
        return math.sqrt(self.variance())

    def config(self) -> Dict[str, object]:
        return {
            "game": "plinko",
            "risk": self.risk,
            "rows": self.rows,
            "pockets": self.pockets,
            "payouts": [float(x) for x in self.payouts],
        }

    def result(self) -> Dict[str, object]:
        """Standard analytic result dict."""
        return {
            "rtp": self.rtp(),
            "house_edge": self.house_edge(),
            "std_per_unit": self.std_per_unit(),
            "config": self.config(),
        }

    # ------------------------------------------------------------------ #
    # (b) provably-fair single round (spinquest_sim.rng scalar path)
    # ------------------------------------------------------------------ #

    def play(
        self,
        server_seed: str,
        client_seed: str,
        nonce: int,
        bet: float = 1.0,
    ) -> Dict[str, object]:
        """One verifiable drop: ``rows`` floats from cursor 0 of the bet's
        HMAC-SHA256 stream; ``direction = floor(float * 2)``; the landing
        pocket is the count of rights."""
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

    # ------------------------------------------------------------------ #
    # (c) vectorized simulators
    # ------------------------------------------------------------------ #

    def _summarize(self, counts: np.ndarray, n: int) -> Dict[str, object]:
        """Empirical result dict from per-pocket landing counts."""
        counts = np.asarray(counts, dtype=np.int64)
        total_payout = float(counts @ self.payouts)
        emp_rtp = total_payout / n
        emp_second = float(counts @ (self.payouts ** 2)) / n
        emp_var = max(emp_second - emp_rtp * emp_rtp, 0.0)
        analytic = self.result()
        se = self.std_per_unit() / math.sqrt(n)
        return {
            "rtp": emp_rtp,
            "house_edge": 1.0 - emp_rtp,
            "std_per_unit": math.sqrt(emp_var),
            "config": self.config(),
            "rounds": int(n),
            "pocket_counts": counts.tolist(),
            "analytic_rtp": analytic["rtp"],
            "rtp_standard_error": se,
            "rtp_z": (emp_rtp - analytic["rtp"]) / se if se > 0 else 0.0,
        }

    def simulate(
        self,
        n_rounds: int,
        seed: Optional[int] = None,
        chunk: int = 20_000_000,
    ) -> Dict[str, object]:
        """Fast Monte-Carlo of ``n_rounds`` drops using numpy PCG64.

        Model-identical to the provably-fair path: the pocket is a
        Binomial(rows, 0.5) draw (the per-row 50/50 directions summed).
        Memory-bounded: works in chunks of ``chunk`` int8 draws (<500 MB).
        """
        if n_rounds < 1:
            raise ValueError("n_rounds must be >= 1")
        gen = np.random.default_rng(seed)
        counts = np.zeros(self.pockets, dtype=np.int64)
        done = 0
        while done < n_rounds:
            step = min(chunk, n_rounds - done)
            pockets = gen.binomial(self.rows, 0.5, size=step)
            counts += np.bincount(pockets, minlength=self.pockets)
            done += step
            if n_rounds > chunk:
                print(f"plinko simulate[{self.risk}/{self.rows}]: "
                      f"{done:,}/{n_rounds:,}", flush=True)
        out = self._summarize(counts, n_rounds)
        out["simulator"] = "numpy-pcg64-binomial"
        return out

    def simulate_provably_fair(
        self,
        n_rounds: int,
        bulk: Optional[sq_rng.BulkRng] = None,
        server_seed: Optional[str] = None,
        client_seed: str = "spinquest",
        nonce_start: int = 0,
    ) -> Dict[str, object]:
        """Monte-Carlo on the REAL provably-fair HMAC-SHA256 stream
        (:class:`spinquest_sim.rng.BulkRng`): one bet per nonce, ``rows``
        floats per bet, every row bit-reproducible by :meth:`play` at its
        nonce.  ~1M+ digests/s; internally chunked by BulkRng."""
        if n_rounds < 1:
            raise ValueError("n_rounds must be >= 1")
        if bulk is None:
            bulk = sq_rng.BulkRng(
                server_seed=server_seed,
                client_seed=client_seed,
                nonce_start=nonce_start,
            )
        directions = bulk.plinko_directions(self.rows, n_rounds)
        pockets = directions.sum(axis=1)
        counts = np.bincount(pockets, minlength=self.pockets)
        out = self._summarize(counts, n_rounds)
        out["simulator"] = "provably-fair-hmac-sha256"
        out["verification"] = bulk.verification_params()
        return out
