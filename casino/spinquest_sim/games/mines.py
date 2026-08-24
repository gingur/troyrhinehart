"""Stake-style Mines (5x5 grid, 1-24 mines, cash out after k safe picks).

Math (references/stake/mines.md — Stake's published client code, verbatim):

    multiplier(m, k) = 0.99 * prod_{i=0}^{k-1} (25 - i) / (25 - m - i)
                     = 0.99 * C(25, k) / C(25 - m, k)
                     = 0.99 / P(survive k picks)

so the game returns exactly 99% RTP (1% house edge) at *every* cash-out
point, for every mines count.  The in-game display rounds the multiplier to
2 decimals.  Crucially, Stake's client computes the multiplier as a
left-to-right float64 reduce over the product above (JS numbers), NOT from
the exact rational — 7 of the 300 published cells land on the other side of
a half-cent boundary because of that float accumulation (e.g. the table
shows 1.37x at 1 mine / 7 gems but 1.38x at the mathematically symmetric
7 mines / 1 gem, even though both cells are exactly 11/8 = 1.375: the
float64 reduce gives 1.3749999999999996 in one pick order and exactly
1.375 in the other).
:func:`multiplier_display_float` replays that exact float64 reduce and
:func:`display_multiplier` rounds it, reproducing all 300 published cells
digit-for-digit; payout/RTP math stays on the exact rational
(:func:`multiplier_exact`), whose float image differs from the display
reduce by < 1e-15 relative.

Provably-fair mechanics (same reference): 24 mine-location events are drawn
from the 25 tiles by partial Fisher-Yates over the HMAC-SHA256 float stream;
the first ``minesCount`` drawn positions are the round's mines.  Both the
scalar path (:func:`spinquest_sim.rng.mines_positions`) and the vectorized
path (:meth:`spinquest_sim.rng.BulkRng.mines_positions`) are the
critic-verified RNG core — this module adds no randomness of its own.

Note: references/woo/mines.md analyzes a DIFFERENT, ~95%-RTP (BetFury)
paytable.  Its *methodology* (return = pays x P(win), hypergeometric
survival probability) is identical and is applied to Stake's table in
``scripts/validate_mines.py``; its *numbers* intentionally do not match.
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
    "GRID_TILES",
    "MIN_MINES",
    "MAX_MINES",
    "RTP_FACTOR",
    "win_probability_exact",
    "win_probability",
    "multiplier",
    "multiplier_display_float",
    "display_multiplier",
    "full_payout_table",
    "Mines",
]

GRID_TILES = 25          # 5x5 board
MIN_MINES = 1
MAX_MINES = 24
RTP_FACTOR = Fraction(99, 100)   # 0.99 — Stake's published 1% house edge

# Chunk size for simulate(), sized against the project's 500 MB chunking
# budget measured the honest way: peak PSS summed over the WHOLE process
# tree (BulkRng fans digest work out to forked workers, and parent-only
# tracemalloc is structurally blind to worker allocations and undercounts
# the frombuffer/view/astype chain — it reported ~416 MB for a 1M-round
# chunk whose true tree peak was ~600 MB PSS / ~2.4 GB RSS, which busted
# the budget).  At 200k rounds the 24-mine worst-case chunk is a
# 200_000 x 24 int64 matrix = 38 MB, and the measured whole-tree peak for
# Mines(24, 1).simulate(2_000_000) at this default is ~215 MB PSS
# (~525 MB tree RSS, inflated by fork copy-on-write double-counting that
# PSS charges only once) — ~3.5x smaller than the old 1M default with NO
# throughput loss (~140k rounds/s at either size; smaller chunks drop off
# the parallel digest path and get ~30% slower).  scripts/validate_mines.py
# re-measures this as a gate (peak tree PSS < 500 MB) on every run.
_SIM_CHUNK_ROUNDS = 200_000


def _validate(mines: int, picks: int) -> None:
    if not isinstance(mines, (int, np.integer)) or isinstance(mines, bool):
        raise TypeError("mines must be an int")
    if not isinstance(picks, (int, np.integer)) or isinstance(picks, bool):
        raise TypeError("picks must be an int")
    if not MIN_MINES <= mines <= MAX_MINES:
        raise ValueError(f"mines must be in {MIN_MINES}..{MAX_MINES}, got {mines}")
    max_picks = GRID_TILES - mines
    if not 1 <= picks <= max_picks:
        raise ValueError(
            f"picks must be in 1..{max_picks} for {mines} mines, got {picks}"
        )


def win_probability_exact(mines: int, picks: int) -> Fraction:
    """Exact P(k safe picks with m mines) = C(25-m, k) / C(25, k).

    Equal to the hypergeometric product prod_{i<k} (25-m-i)/(25-i) — the
    same survival probability the Wizard of Odds tabulates ("Prob. win").
    """
    _validate(mines, picks)
    return Fraction(
        math.comb(GRID_TILES - mines, picks), math.comb(GRID_TILES, picks)
    )


def win_probability(mines: int, picks: int) -> float:
    return float(win_probability_exact(mines, picks))


def multiplier_exact(mines: int, picks: int) -> Fraction:
    """Exact cash-out multiplier 0.99 * C(25,k) / C(25-m,k) (for-one)."""
    return RTP_FACTOR / win_probability_exact(mines, picks)


def multiplier(mines: int, picks: int) -> float:
    """Stake's published multiplier, full float precision."""
    return float(multiplier_exact(mines, picks))


def multiplier_display_float(mines: int, picks: int) -> float:
    """Stake's client-side multiplier: left-to-right float64 reduce.

    Replays the published JS accumulation ``0.99 * prod (25-i)/(25-m-i)``
    term by term in IEEE-754 double precision — the number the client
    actually rounds for display.  Differs from ``multiplier()`` (the float
    image of the exact rational) by < 1e-15 relative, but 7 of the 300
    published cells sit on a half-cent boundary where that difference flips
    the displayed cent.  Display/table comparison ONLY — payout and RTP
    math stay on :func:`multiplier_exact`.
    """
    _validate(mines, picks)
    a = 0.99
    for i in range(picks):
        a = a * (GRID_TILES - i) / (GRID_TILES - mines - i)
    return a


def display_multiplier(mines: int, picks: int) -> float:
    """Multiplier rounded to 2 decimals as shown in-game.

    Rounds :func:`multiplier_display_float` (the client's float64 reduce),
    NOT the exact rational — this reproduces every one of Stake's 300
    published table cells digit-for-digit, including the 7 cells whose
    displayed cent disagrees with round-half-even of the exact value.

    Rounding MODE is a deliberate choice, not an accident: the reference's
    §6 prose says the client displays ``multiplier.toFixed(2)``, but JS
    ``toFixed`` breaks ties AWAY FROM ZERO while Python ``round`` breaks
    them TO EVEN, and the two disagree on exactly 3 cells whose float64
    reduce lands exactly on a half-cent — (3,1) and (19,1) (both reduce to
    an exact ``x.125``) and (17,7) (exactly ``59486.625``).  The published
    §7 table prints the half-even cent in all 3 (1.12x, 4.12x, 59,486.62x),
    so the reference is internally inconsistent and we side with the table
    (300 data points) over the prose (one parenthetical): a "more faithful"
    switch to toFixed semantics would break those 3 cells.  Pinned by
    ``tests/test_mines.py::TestStakeTable::test_tofixed_ties_away_would_break_three_cells``.
    """
    return round(multiplier_display_float(mines, picks), 2)


def full_payout_table() -> Dict[int, Dict[int, float]]:
    """{mines: {picks: exact multiplier}} for all 300 valid combinations."""
    return {
        m: {k: multiplier(m, k) for k in range(1, GRID_TILES - m + 1)}
        for m in range(MIN_MINES, MAX_MINES + 1)
    }


class Mines:
    """Mines engine for one (mines, picks) configuration.

    Strategy modelled: pick ``picks`` tiles (default the first ``picks``
    tiles in reading order — mine placement is uniform, so tile choice is
    statistically irrelevant), cash out if all are safe.  Provides

    (a) analytic paytable / probability / RTP / variance,
    (b) provably-fair single-round play on the scalar RNG path,
    (c) a vectorized :class:`BulkRng` simulator for 10M+ rounds,
    (d) the standard result dict {rtp, house_edge, std_per_unit, config}.
    """

    def __init__(self, mines: int, picks: int) -> None:
        _validate(mines, picks)
        self.mines = int(mines)
        self.picks = int(picks)

    # ------------------------------------------------------------------
    # (a) analytics
    # ------------------------------------------------------------------

    @property
    def win_probability_exact(self) -> Fraction:
        return win_probability_exact(self.mines, self.picks)

    @property
    def win_probability(self) -> float:
        return float(self.win_probability_exact)

    @property
    def multiplier_exact(self) -> Fraction:
        return multiplier_exact(self.mines, self.picks)

    @property
    def multiplier(self) -> float:
        return float(self.multiplier_exact)

    @property
    def display_mult(self) -> float:
        return display_multiplier(self.mines, self.picks)

    @property
    def rtp(self) -> float:
        """Exact analytic RTP: multiplier * P(win) = 0.99 identically."""
        return float(self.multiplier_exact * self.win_probability_exact)

    @property
    def house_edge(self) -> float:
        return float(1 - self.multiplier_exact * self.win_probability_exact)

    @property
    def variance_per_unit(self) -> float:
        """Var of the for-one payout X per unit staked.

        X = M with prob p, 0 otherwise:  Var = M^2 p - (M p)^2.
        Computed in exact rational arithmetic before conversion.
        """
        m, p = self.multiplier_exact, self.win_probability_exact
        return float(m * m * p - (m * p) ** 2)

    @property
    def std_per_unit(self) -> float:
        return math.sqrt(self.variance_per_unit)

    def config(self) -> Dict[str, object]:
        return {
            "game": "mines",
            "grid_tiles": GRID_TILES,
            "mines": self.mines,
            "picks": self.picks,
            "multiplier": self.multiplier,
            "display_multiplier": self.display_mult,
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

    def _pick_order(self, picks: Optional[Sequence[int]]) -> List[int]:
        order = list(range(self.picks)) if picks is None else [int(t) for t in picks]
        if len(order) != self.picks:
            raise ValueError(f"need exactly {self.picks} tiles, got {len(order)}")
        if len(set(order)) != len(order):
            raise ValueError("picked tiles must be distinct")
        if any(not 0 <= t < GRID_TILES for t in order):
            raise ValueError("tiles must be in 0..24")
        return order

    def play_round(
        self,
        server_seed: str,
        client_seed: str,
        nonce: int,
        picks: Optional[Sequence[int]] = None,
    ) -> Dict[str, object]:
        """Play one verifiable round: reveal ``picks`` tiles in order, cash
        out at the configured multiplier if none is a mine.

        Mine locations come from the critic-verified scalar RNG port of
        Stake's published verifier (24 Fisher-Yates events, first ``mines``
        used); the returned dict carries everything needed to re-verify.
        """
        order = self._pick_order(picks)
        mine_list = sq_rng.mines_positions(
            server_seed, client_seed, nonce, self.mines
        )
        mine_set = set(mine_list)
        revealed: List[int] = []
        hit: Optional[int] = None
        mult_path: List[float] = []
        for tile in order:
            if tile in mine_set:
                hit = tile
                break
            revealed.append(tile)
            mult_path.append(multiplier(self.mines, len(revealed)))
        win = hit is None
        return {
            "win": win,
            "payout": self.multiplier if win else 0.0,
            "multiplier": self.multiplier if win else 0.0,
            "multiplier_path": mult_path,
            "revealed": revealed,
            "hit_mine": hit,
            "mine_positions": mine_list,   # draw order, as generated
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
        picks: Optional[Sequence[int]] = None,
        chunk_rounds: int = _SIM_CHUNK_ROUNDS,
        progress: bool = True,
    ) -> Dict[str, object]:
        """Simulate ``n_rounds`` provably-fair rounds (one nonce per round)
        on the vectorized :class:`BulkRng` stream and return the standard
        result dict.

        Chunked so the whole-process-tree peak (chunk output matrix +
        BulkRng worker fan-out + np.any/np.isin temporaries) stays inside
        the 500 MB budget: at the default ``chunk_rounds`` the measured
        peak is ~215 MB PSS over the tree at the 24-mine worst case
        (see the note at ``_SIM_CHUNK_ROUNDS``; the validator re-measures
        this as a gate).  Prints progress for long campaigns.  Row i of
        the campaign is bit-for-bit verifiable against the scalar path at
        nonce ``nonce_start + i``.
        """
        if n_rounds <= 0:
            raise ValueError("n_rounds must be positive")
        if chunk_rounds < 1:
            # chunk_rounds=0 would make step = min(0, remaining) = 0 and
            # loop forever with no error and no output; negative values
            # would only fail incidentally deeper in the RNG.  Same guard
            # as roulette/plinko/keno.
            raise ValueError(f"chunk_rounds must be >= 1, got {chunk_rounds}")
        rng = bulk if bulk is not None else BulkRng()
        order = self._pick_order(picks)
        pick_arr = np.asarray(order, dtype=np.int64)
        # Fast path: default prefix picks {0..k-1} -> "any mine < k".
        prefix = order == list(range(self.picks))

        nonce_first = rng.nonce_next
        wins = 0
        done = 0
        t0 = time.perf_counter()
        while done < n_rounds:
            step = min(chunk_rounds, n_rounds - done)
            pos = rng.mines_positions(self.mines, step)  # (step, mines)
            if prefix:
                lost = np.any(pos < self.picks, axis=1)
            else:
                lost = np.isin(pos, pick_arr).any(axis=1)
            wins += int(step - np.count_nonzero(lost))
            done += step
            if progress and n_rounds > chunk_rounds:
                rate = done / (time.perf_counter() - t0)
                print(
                    f"  mines={self.mines} picks={self.picks}: "
                    f"{done:,}/{n_rounds:,} rounds ({rate:,.0f}/s)",
                    flush=True,
                )
        elapsed = time.perf_counter() - t0

        mult = self.multiplier
        p_hat = wins / n_rounds
        rtp_emp = p_hat * mult
        # SE of the empirical RTP under the analytic (null) distribution.
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
