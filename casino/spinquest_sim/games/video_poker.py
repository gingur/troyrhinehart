"""Stake-style Video Poker (single 52-card deck, 5-card draw, Jacks-or-Better).

Rules and provably-fair mechanics (references/stake/video_poker.md — Stake's
published pages, verbatim):

* One bet = 52 game events: the HMAC-SHA256 float stream is mapped through a
  partial Fisher-Yates shuffle (floats x 52, x 51, ...) into a full
  no-duplicate deck permutation over the published CARDS index
  (0..51 = ♦2..♣A; rank-major, suit order ♦♥♠♣ — so ``rank = i >> 2``,
  ``suit = i & 3``).
* The first 5 deck cards are the deal; each discarded card is replaced by the
  next unseen card of the same pre-committed permutation.
* Paytable (total-return multipliers, Stake's published table): Royal Flush
  800x, Straight Flush 60x, 4 of a Kind 22x, Full House 9x, Flush 6x,
  Straight 4x, 3 of a Kind 3x, 2 Pair 2x, Pair of Jacks or better 1x.
  Published house edge: "Edge: 1.00%" / "99% RTP".  Stake does NOT publish
  the strategy assumption behind that figure.

Analysis method (references/woo/video_poker.md — Wizard of Odds methodology):

* Exhaustive combinatorial analysis: all C(52,5) = 2,598,960 deals x all 32
  hold subsets, exact EV per hold, max-EV hold per deal.  No simulation.
* This module implements it exactly, fully vectorized in numpy:

  1. "Superset-sum" tables U_k: for every k-card subset s of the deck
     (k = 0..4, colex-indexed) and every final-hand category c,
     ``U_k[s, c] = #{5-card hands h : h ⊇ s, category(h) = c}``.
     Built bottom-up from the 2,598,960 scored hands via the identity
     ``sum_{x not in s} U_{k+1}[s ∪ {x}] = (5-k) * U_k[s]``.
  2. For a deal D and a held subset s ⊆ D, completions must avoid ALL of D,
     not just s; inclusion-exclusion over the discards gives
     ``N[s, c] = sum_{t ⊆ D\\s} (-1)^{|t|} U[s ∪ t, c]``
     — for all 32 holds of a deal at once this is a signed superset-sum
     (Moebius) transform over the 5-bit hold-mask lattice (80 adds/deal).
  3. ``EV(hold) = (N[s, :] @ pays) / C(47, 5-|s|)``.  All arithmetic is
     int64 on a common denominator ``L = lcm{C(47,d)}``, so hold selection
     and the aggregate return are EXACT integer/rational math (ties broken
     by lowest hold-mask; final results returned as ``fractions.Fraction``).

  Because U_k depends only on hand *categories* (not pays), one pass solves
  any number of paytables simultaneously.  This is the same reduction that
  makes the Wizard's suit-equivalence approach fast — here the caching is
  the shared subset->category tables instead of 134,459 hand classes, and
  the whole cycle runs in ~1-2 minutes of numpy.

Benchmarks (references/woo/video_poker.md): full-pay 9/6 Jacks or Better
(800/50/25/9/6/4/3/2/1) returns 99.54% (more precisely 99.5439%) with
optimal strategy, standard deviation 4.42 (more precisely 4.417542) per
hand.  ``BENCHMARK_9_6_PAYTABLE`` reproduces those numbers exactly;
``STAKE_PAYTABLE`` (800/60/22/...) is the game's own table (exact
optimal-play ceiling 98.9445% — the published "Edge: 1.00%" is not
attainable).  ``WOO_VARIANT_PAYTABLES`` carries all 8 published WoO
Jacks-or-Better variants (9/6, 9/5, 8/6, 8/5, 7/5, 6/5, NetEnt
40-20-9-6-5, Gtech 20/7/5), all solved in the same shared pass and
reproducing the published returns.  The solver also accumulates the
per-deal optimal-EV first/second moments, so ``Solution.hold_ev_variance``
is the exact shared-deal covariance c of WoO Appendix 3 and
``Solution.n_play_std`` reproduces the published multihand SD table
(4.42 / 4.84 / 5.23 / 6.10 / 10.76 / 14.64 for 1/3/5/10/50/100 plays);
``VideoPoker.return_table`` renders the Wizard's
pays | combinations | probability | return table with the exact
Combinations column on the denominator L * C(52,5) = 19,933,230,517,200.

Randomness: the scalar path (:func:`spinquest_sim.rng.video_poker_deck`) and
the vectorized path (:meth:`spinquest_sim.rng.BulkRng.video_poker_decks`) are
the critic-verified RNG core — this module adds no randomness of its own.
"""

from __future__ import annotations

import itertools
import math
import os
import time
from fractions import Fraction
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from spinquest_sim import rng as sq_rng
from spinquest_sim.rng import BulkRng

__all__ = [
    "CATEGORIES",
    "CATEGORY_LABELS",
    "STAKE_PAYTABLE",
    "BENCHMARK_9_6_PAYTABLE",
    "WOO_VARIANT_PAYTABLES",
    "WOO_VARIANT_RETURNS_PCT",
    "COMBINATIONS_DENOMINATOR",
    "DECK_SIZE",
    "HAND_SIZE",
    "N_HANDS",
    "evaluate_hands",
    "evaluate_hand",
    "hand_colex_rank",
    "solve_paytables",
    "hold_ev_exact",
    "hold_ev_bruteforce",
    "VideoPoker",
]

# --------------------------------------------------------------------------
# Cards & categories
# --------------------------------------------------------------------------

DECK_SIZE = 52
HAND_SIZE = 5
N_HANDS = math.comb(DECK_SIZE, HAND_SIZE)  # 2,598,960

# Final-hand categories, low to high.  Codes are the index in this tuple.
CATEGORIES: Tuple[str, ...] = (
    "nothing",
    "jacks_or_better",
    "two_pair",
    "three_of_a_kind",
    "straight",
    "flush",
    "full_house",
    "four_of_a_kind",
    "straight_flush",
    "royal_flush",
)
N_CAT = len(CATEGORIES)

# Display names as printed in the Stake reference paytable.
CATEGORY_LABELS: Dict[str, str] = {
    "royal_flush": "Royal Flush",
    "straight_flush": "Straight Flush",
    "four_of_a_kind": "4 of a Kind",
    "full_house": "Full House",
    "flush": "Flush",
    "straight": "Straight",
    "three_of_a_kind": "3 of a Kind",
    "two_pair": "2 Pair",
    "jacks_or_better": "Pair of Jacks or better",
    "nothing": "Nothing",
}

# Stake's published paytable (references/stake/video_poker.md §6), both the
# description table and the in-game ladder (identical values).
STAKE_PAYTABLE: Dict[str, int] = {
    "royal_flush": 800,
    "straight_flush": 60,
    "four_of_a_kind": 22,
    "full_house": 9,
    "flush": 6,
    "straight": 4,
    "three_of_a_kind": 3,
    "two_pair": 2,
    "jacks_or_better": 1,
}

# Wizard of Odds full-pay 9/6 Jacks or Better benchmark
# (references/woo/video_poker.md: 99.54% return, SD 4.42, royal pays 800).
BENCHMARK_9_6_PAYTABLE: Dict[str, int] = {
    "royal_flush": 800,
    "straight_flush": 50,
    "four_of_a_kind": 25,
    "full_house": 9,
    "flush": 6,
    "straight": 4,
    "three_of_a_kind": 3,
    "two_pair": 2,
    "jacks_or_better": 1,
}

def _job_paytable(sf: int = 50, quads: int = 25, fh: int = 9, fl: int = 6,
                  st: int = 4, royal: int = 800) -> Dict[str, int]:
    """Jacks-or-Better paytable with the usual fixed tail (3K 3 / 2P 2 / JB 1)."""
    return {
        "royal_flush": royal,
        "straight_flush": sf,
        "four_of_a_kind": quads,
        "full_house": fh,
        "flush": fl,
        "straight": st,
        "three_of_a_kind": 3,
        "two_pair": 2,
        "jacks_or_better": 1,
    }


# references/woo/video_poker.md — "Jacks or Better pay-table variants (return
# with optimal strategy)".  Labels are the Wizard's FH/Flush shorthand; the
# NetEnt row is SF/4K/FH/Flush/Straight = 40-20-9-6-5, the Gtech row is
# 4K/FH/Flush = 20/7/5 (royal 800 and the 3/2/1 tail unchanged).
WOO_VARIANT_PAYTABLES: Dict[str, Dict[str, int]] = {
    "9/6": _job_paytable(fh=9, fl=6),
    "9/5": _job_paytable(fh=9, fl=5),
    "8/6": _job_paytable(fh=8, fl=6),
    "8/5": _job_paytable(fh=8, fl=5),
    "7/5": _job_paytable(fh=7, fl=5),
    "6/5": _job_paytable(fh=6, fl=5),
    "netent_40_20_9_6_5": _job_paytable(sf=40, quads=20, fh=9, fl=6, st=5),
    "gtech_20_7_5": _job_paytable(quads=20, fh=7, fl=5),
}

# Published optimal-strategy returns for those variants, in percent, at the
# reference's displayed precision (2 decimals).
WOO_VARIANT_RETURNS_PCT: Dict[str, float] = {
    "9/6": 99.54,
    "9/5": 98.45,
    "8/6": 98.39,
    "8/5": 97.30,
    "7/5": 96.15,
    "6/5": 95.00,
    "netent_40_20_9_6_5": 99.56,
    "gtech_20_7_5": 94.97,
}

# Known 5-card category counts out of C(52,5) = 2,598,960 (standard poker
# combinatorics; "nothing" = high card 1,302,540 + low pairs 760,320).
_KNOWN_CATEGORY_COUNTS = np.array(
    [2_062_860, 337_920, 123_552, 54_912, 10_200, 5_108, 3_744, 624, 36, 4],
    dtype=np.int64,
)

_JACK_RANK = 9  # rank code of J (0 = deuce ... 12 = ace)


def _paytable_key(paytable: Mapping[str, int]) -> Tuple[int, ...]:
    """Canonical hashable form: pays per category code (0 for missing)."""
    unknown = set(paytable) - set(CATEGORIES)
    if unknown:
        raise ValueError(f"unknown paytable categories: {sorted(unknown)}")
    if paytable.get("nothing", 0) != 0:
        raise ValueError("'nothing' must pay 0")
    vec = []
    for name in CATEGORIES:
        pay = paytable.get(name, 0)
        if int(pay) != pay or pay < 0:
            raise ValueError(f"paytable pays must be non-negative integers, got {name}={pay!r}")
        vec.append(int(pay))
    return tuple(vec)


# --------------------------------------------------------------------------
# Vectorized 5-card evaluator
# --------------------------------------------------------------------------

def evaluate_hands(cards: np.ndarray) -> np.ndarray:
    """Category codes (0..9) for an (N, 5) array of card indices 0..51.

    Order-agnostic; single-deck hands assumed (no duplicate cards).
    """
    cards = np.asarray(cards)
    if cards.ndim != 2 or cards.shape[1] != HAND_SIZE:
        raise ValueError("cards must be an (N, 5) array")
    n = cards.shape[0]
    ranks = (cards >> 2).astype(np.int64)
    suits = cards & 3

    flat = ranks + (np.arange(n, dtype=np.int64) * 13)[:, None]
    cnt = np.bincount(flat.ravel(), minlength=n * 13).reshape(n, 13).astype(np.uint8)

    maxc = cnt.max(axis=1)
    npair = (cnt == 2).sum(axis=1, dtype=np.uint8)
    flush = (suits == suits[:, :1]).all(axis=1)
    distinct5 = maxc == 1
    rmin = ranks.min(axis=1)
    rmax = ranks.max(axis=1)
    # A-2-3-4-5 wheel: ranks {12, 0, 1, 2, 3}
    wheel = (
        distinct5
        & (cnt[:, 12] > 0) & (cnt[:, 0] > 0) & (cnt[:, 1] > 0)
        & (cnt[:, 2] > 0) & (cnt[:, 3] > 0)
    )
    straight = distinct5 & (((rmax - rmin) == 4) | wheel)
    royal = straight & flush & (rmin == 8)  # T J Q K A
    high_pair = (maxc == 2) & (npair == 1) & (cnt[:, _JACK_RANK:] == 2).any(axis=1)

    out = np.select(
        [
            royal,
            straight & flush,
            maxc == 4,
            (maxc == 3) & (npair == 1),
            flush,
            straight,
            maxc == 3,
            npair == 2,
            high_pair,
        ],
        [9, 8, 7, 6, 5, 4, 3, 2, 1],
        default=0,
    )
    return out.astype(np.uint8)


def evaluate_hand(cards: Sequence[int]) -> str:
    """Category name of a single 5-card hand."""
    return CATEGORIES[int(evaluate_hands(np.asarray(cards)[None, :])[0])]


# --------------------------------------------------------------------------
# Colex (combinadic) subset ranking
# --------------------------------------------------------------------------

# _CK[k][c] = C(c, k) for c in 0..51, k = 1..5.
_CK = [None] + [
    np.array([math.comb(c, k) for c in range(DECK_SIZE)], dtype=np.int64)
    for k in range(1, HAND_SIZE + 1)
]


def _colex(cols: np.ndarray) -> np.ndarray:
    """Colex rank of each row of an (N, k) array of ASCENDING card indices."""
    k = cols.shape[1]
    idx = _CK[1][cols[:, 0]].copy()
    for j in range(1, k):
        idx += _CK[j + 1][cols[:, j]]
    return idx


def hand_colex_rank(sorted_cards: np.ndarray) -> np.ndarray:
    """Colex rank (0..2,598,959) of (N, 5) ascending-sorted hands."""
    sorted_cards = np.asarray(sorted_cards, dtype=np.int64)
    if sorted_cards.ndim == 1:
        sorted_cards = sorted_cards[None, :]
    if sorted_cards.ndim != 2 or sorted_cards.shape[1] != HAND_SIZE:
        raise ValueError("hands must have exactly 5 cards per row")
    if sorted_cards.size and (
        sorted_cards.min() < 0 or sorted_cards.max() >= DECK_SIZE
    ):
        raise ValueError("card indices must be in 0..51")
    if not (np.diff(sorted_cards, axis=1) > 0).all():
        raise ValueError("cards must be strictly ascending per row")
    return _colex(sorted_cards)


# --------------------------------------------------------------------------
# Hold-mask lattice constants
# --------------------------------------------------------------------------

_N_MASKS = 32
_MASK_POSITIONS = [
    tuple(i for i in range(HAND_SIZE) if (m >> i) & 1) for m in range(_N_MASKS)
]
_MASK_K = np.array([len(p) for p in _MASK_POSITIONS], dtype=np.int64)
_MASK_DRAWS = HAND_SIZE - _MASK_K
_C47 = np.array([math.comb(47, d) for d in range(HAND_SIZE + 1)], dtype=np.int64)
# Common denominator for exact integer EV comparison across hold sizes.
_L = math.lcm(*(int(x) for x in _C47))  # 7,669,695
_MASK_MULT = np.array([_L // int(_C47[d]) for d in _MASK_DRAWS], dtype=np.int64)
# Exact-probability denominator for aggregate results.  This is also the
# denominator of the Wizard of Odds "Combinations" column for 5-card-draw
# games: every deal is weighted by L so all hold sizes share one denominator
# (L * C(52,5) = 19,933,230,517,200).
_PROB_DEN = _L * N_HANDS
COMBINATIONS_DENOMINATOR = _PROB_DEN


def _exact_sq_sum(v: np.ndarray) -> int:
    """Exact sum of squares of a non-negative int64 array.

    Values < 2**33 (every scaled hold EV: <= 800 * L = 6,135,756,000) are
    split 16/17 bits so each partial sum stays inside int64; larger values
    (a paytable with a >1119x top pay) fall back to exact Python ints.
    """
    if v.size == 0:
        return 0
    if int(v.max()) >= (1 << 33):
        return sum(int(x) * int(x) for x in v.tolist())
    hi = v >> 16          # < 2**17
    lo = v & 0xFFFF       # < 2**16
    # v^2 = hi^2 * 2^32 + (hi*lo) * 2^17 + lo^2, each term summed in int64.
    return (
        (int((hi * hi).sum()) << 32)
        + (int((hi * lo).sum()) << 17)
        + int((lo * lo).sum())
    )


# --------------------------------------------------------------------------
# Superset-sum tables U_k (paytable-independent; built once per process)
# --------------------------------------------------------------------------

_TABLES: Optional[Dict[str, object]] = None


def _build_tables() -> Dict[str, object]:
    """All 2,598,960 hands + their categories + U_0..U_4 subset tables."""
    hands = np.array(
        list(itertools.combinations(range(DECK_SIZE), HAND_SIZE)), dtype=np.uint8
    )
    cat = evaluate_hands(hands)
    counts = np.bincount(cat, minlength=N_CAT).astype(np.int64)
    if not np.array_equal(counts, _KNOWN_CATEGORY_COUNTS):
        raise AssertionError(
            f"5-card category counts {counts.tolist()} != known "
            f"{_KNOWN_CATEGORY_COUNTS.tolist()}"
        )

    cat_rows = [np.nonzero(cat == c)[0] for c in range(N_CAT)]
    h64 = hands.astype(np.int64)

    # U4 from the scored hands directly (divisor 5-4 = 1).
    n4 = math.comb(DECK_SIZE, 4)
    u4 = np.zeros((n4, N_CAT), dtype=np.int64)
    for drop in range(HAND_SIZE):
        cols = [j for j in range(HAND_SIZE) if j != drop]
        idx = _colex(h64[:, cols])
        for c in range(N_CAT):
            u4[:, c] += np.bincount(idx[cat_rows[c]], minlength=n4)

    def shrink(subsets: np.ndarray, vals: np.ndarray, k: int) -> np.ndarray:
        """U_k from U_{k+1}: scatter drop-one subsets, divide by (5-k)."""
        nk = math.comb(DECK_SIZE, k)
        out = np.zeros((nk, N_CAT), dtype=np.float64)
        for drop in range(k + 1):
            cols = [j for j in range(k + 1) if j != drop]
            idx = _colex(subsets[:, cols])
            for c in range(N_CAT):
                out[:, c] += np.bincount(
                    idx, weights=vals[:, c].astype(np.float64), minlength=nk
                )
        out_i = np.rint(out).astype(np.int64)
        if (out_i % (HAND_SIZE - k)).any():
            raise AssertionError(f"U_{k} scatter not divisible by {HAND_SIZE - k}")
        return out_i // (HAND_SIZE - k)

    u = {4: u4}
    for k in (3, 2, 1):
        subsets = np.array(
            list(itertools.combinations(range(DECK_SIZE), k + 1)), dtype=np.int64
        )
        vals = u[k + 1][_colex(subsets)]  # U_{k+1} rows in enumeration order
        u[k] = shrink(subsets, vals, k)

    u0 = u[1].sum(axis=0)
    if (u0 % HAND_SIZE).any():
        raise AssertionError("U_0 not divisible by 5")
    u0 = u0 // HAND_SIZE
    if not np.array_equal(u0, _KNOWN_CATEGORY_COUNTS):
        raise AssertionError("U_0 recurrence does not reproduce category counts")

    return {"hands": hands, "cat": cat, "U": u, "U0": u0}


def _get_tables() -> Dict[str, object]:
    global _TABLES
    if _TABLES is None:
        _TABLES = _build_tables()
    return _TABLES


# --------------------------------------------------------------------------
# Exact full-cycle solver (all deals x all 32 holds, exact integer math)
# --------------------------------------------------------------------------

class Solution:
    """Exact optimal-play solution for one paytable.

    Attributes
    ----------
    pattern_table : (2,598,960,) uint8 — optimal hold mask per deal, indexed
        by the colex rank of the ASCENDING-sorted 5 dealt cards; bit i of the
        mask = hold sorted position i.  EV ties break to the lowest mask.
    category_probs : exact ``Fraction`` probability of each final-hand
        category under optimal play (length 10, sums to 1).
    ev : exact optimal-play return (RTP) as a ``Fraction``.
    hold_ev_variance : exact ``Fraction`` variance ACROSS DEALS of the
        per-deal optimal-hold conditional EV.  For n-play video poker (n
        hands drawn independently from the same dealt 5 cards with the same
        hold) this is exactly the covariance c between any two hands, so the
        Wizard's Appendix-3 formula gives per-hand n-play variance
        v + (n-1)*c — see :meth:`n_play_variance` / :meth:`n_play_std`.
    """

    def __init__(self, paytable_key: Tuple[int, ...], pattern_table: np.ndarray,
                 cat_scaled_sums: np.ndarray, hold_ev_sum_scaled: int,
                 hold_ev_sq_sum_scaled: int) -> None:
        self.paytable_key = paytable_key
        self.pattern_table = pattern_table
        self.cat_scaled_sums = cat_scaled_sums.astype(object)
        self.category_probs: List[Fraction] = [
            Fraction(int(s), _PROB_DEN) for s in cat_scaled_sums
        ]
        assert sum(self.category_probs) == 1
        self.ev: Fraction = sum(
            p * pay for p, pay in zip(self.category_probs, paytable_key)
        )
        self.ev2: Fraction = sum(
            p * pay * pay for p, pay in zip(self.category_probs, paytable_key)
        )
        self.variance: Fraction = self.ev2 - self.ev * self.ev

        # Per-deal optimal-hold EV moments (numerators on denominators L and
        # L^2 per deal).  The first moment MUST reproduce the aggregate
        # return — a strong internal identity linking the two accumulations.
        self.hold_ev_sum_scaled = int(hold_ev_sum_scaled)
        self.hold_ev_sq_sum_scaled = int(hold_ev_sq_sum_scaled)
        mean = Fraction(self.hold_ev_sum_scaled, _PROB_DEN)
        if mean != self.ev:
            raise AssertionError(
                f"sum of per-deal optimal EVs {mean} != aggregate return {self.ev}"
            )
        self.hold_ev_second_moment: Fraction = Fraction(
            self.hold_ev_sq_sum_scaled, _L * _L * N_HANDS
        )
        self.hold_ev_variance: Fraction = (
            self.hold_ev_second_moment - self.ev * self.ev
        )
        # Law of total variance: Var(E[X|deal]) in [0, Var(X)].
        if not 0 <= self.hold_ev_variance <= self.variance:
            raise AssertionError("hold-EV variance outside [0, total variance]")

    @property
    def std(self) -> float:
        return math.sqrt(float(self.variance))

    def n_play_variance(self, n_plays: int) -> Fraction:
        """Exact per-hand variance for n-play (Appendix 3): v + (n-1)*c,
        where c = Var of the per-deal conditional EV (shared-deal
        covariance).  Total n-play variance is n*v + n*(n-1)*c."""
        if n_plays < 1:
            raise ValueError("n_plays must be >= 1")
        return self.variance + (n_plays - 1) * self.hold_ev_variance

    def n_play_std(self, n_plays: int) -> float:
        """Per-hand standard deviation for n-play video poker."""
        return math.sqrt(float(self.n_play_variance(n_plays)))


_SOLUTIONS: Dict[Tuple[int, ...], Solution] = {}

_SOLVE_CHUNK = 65_536  # (32, chunk, 10) int64 core array ~168 MB


def solve_paytables(
    paytables: Sequence[Mapping[str, int]],
    progress: bool = False,
    cache_dir: Optional[str] = None,
) -> List[Solution]:
    """Exact optimal-play solutions for one or more paytables in ONE pass.

    Full-cycle enumeration: every C(52,5) deal, every 32 holds, exact
    integer EV; category tables are shared across paytables so extra
    paytables are nearly free.  Optionally caches per-paytable results
    (pattern table + exact category sums) as .npz in ``cache_dir``.
    """
    keys = [_paytable_key(pt) for pt in paytables]
    todo = []
    for key in keys:
        if key in _SOLUTIONS:
            continue
        if cache_dir:
            sol = _load_cached(cache_dir, key)
            if sol is not None:
                _SOLUTIONS[key] = sol
                continue
        if key not in todo:
            todo.append(key)

    if todo:
        t0 = time.perf_counter()
        tables = _get_tables()
        hands = tables["hands"]
        cat = tables["cat"]
        u = tables["U"]
        u0 = tables["U0"]
        pay_vecs = [np.array(key, dtype=np.int64) for key in todo]
        pattern_tables = [np.zeros(N_HANDS, dtype=np.uint8) for _ in todo]
        cat_sums = [np.zeros(N_CAT, dtype=np.int64) for _ in todo]
        ev_sums = [0 for _ in todo]      # sum of best scaled EV (den L/deal)
        ev_sq_sums = [0 for _ in todo]   # sum of its squares (den L^2/deal)

        for a in range(0, N_HANDS, _SOLVE_CHUNK):
            b = min(a + _SOLVE_CHUNK, N_HANDS)
            h = hands[a:b].astype(np.int64)
            n = b - a
            catnum = np.empty((_N_MASKS, n, N_CAT), dtype=np.int64)
            catnum[0] = u0  # broadcast: completions of the empty hold
            for m in range(1, _N_MASKS - 1):
                pos = _MASK_POSITIONS[m]
                k = len(pos)
                catnum[m] = u[k][_colex(h[:, list(pos)])]
            onehot = np.zeros((n, N_CAT), dtype=np.int64)
            onehot[np.arange(n), cat[a:b].astype(np.int64)] = 1
            catnum[_N_MASKS - 1] = onehot  # hold all 5: the deal itself

            # Signed superset-sum (Moebius) transform over the mask lattice:
            # catnum[m] <- sum_{s >= m} (-1)^{|s|-|m|} catnum[s]
            #            = exact category counts of the C(47, 5-|m|)
            #              completions that avoid every dealt card.
            for bit in range(HAND_SIZE):
                step = 1 << bit
                for m in range(_N_MASKS):
                    if not m & step:
                        catnum[m] -= catnum[m | step]

            ranks5 = _colex(h)
            for i, pv in enumerate(pay_vecs):
                num_pay = np.einsum("mnc,c->mn", catnum, pv)     # int64 exact
                scaled = num_pay * _MASK_MULT[:, None]           # common denom L
                best = scaled.argmax(axis=0)                     # ties -> lowest mask
                pattern_tables[i][ranks5] = best.astype(np.uint8)
                chosen = np.take_along_axis(catnum, best[None, :, None], axis=0)[0]
                cat_sums[i] += (chosen * _MASK_MULT[best][:, None]).sum(axis=0)
                # Per-deal optimal EV moments (for the aggregate-return
                # identity and the n-play shared-deal covariance).
                scaled_best = scaled.max(axis=0)                 # == scaled[best]
                ev_sums[i] += int(scaled_best.sum())
                ev_sq_sums[i] += _exact_sq_sum(scaled_best)
            if progress:
                el = time.perf_counter() - t0
                print(
                    f"  video_poker solve: {b:,}/{N_HANDS:,} deals ({b / el:,.0f}/s)",
                    flush=True,
                )

        for key, pat, cs, es, esq in zip(
            todo, pattern_tables, cat_sums, ev_sums, ev_sq_sums
        ):
            sol = Solution(key, pat, cs, es, esq)
            _SOLUTIONS[key] = sol
            if cache_dir:
                _store_cached(cache_dir, key, sol)

    return [_SOLUTIONS[key] for key in keys]


_CACHE_VERSION = 2  # v2: adds the per-deal optimal-EV moment sums


def _cache_path(cache_dir: str, key: Tuple[int, ...]) -> str:
    tag = "-".join(str(x) for x in key)
    return os.path.join(cache_dir, f"vp_solution_v{_CACHE_VERSION}_{tag}.npz")


def _load_cached(cache_dir: str, key: Tuple[int, ...]) -> Optional[Solution]:
    path = _cache_path(cache_dir, key)
    if not os.path.exists(path):
        return None
    try:
        data = np.load(path)
        pat = data["pattern_table"]
        cs = data["cat_scaled_sums"]
        if pat.shape != (N_HANDS,) or cs.shape != (N_CAT,):
            return None
        ev_sum = int(str(data["hold_ev_sum_scaled"]))
        ev_sq_sum = int(str(data["hold_ev_sq_sum_scaled"]))
        return Solution(key, pat.astype(np.uint8), cs.astype(np.int64),
                        ev_sum, ev_sq_sum)
    except Exception:
        return None


def _store_cached(cache_dir: str, key: Tuple[int, ...], sol: Solution) -> None:
    os.makedirs(cache_dir, exist_ok=True)
    np.savez_compressed(
        _cache_path(cache_dir, key),
        pattern_table=sol.pattern_table,
        cat_scaled_sums=np.array([int(x) for x in sol.cat_scaled_sums], dtype=np.int64),
        # exact python ints (the square sum exceeds int64) stored as strings
        hold_ev_sum_scaled=np.array(str(sol.hold_ev_sum_scaled)),
        hold_ev_sq_sum_scaled=np.array(str(sol.hold_ev_sq_sum_scaled)),
    )


# --------------------------------------------------------------------------
# Per-hold exact EV + independent brute force (test/debug surface)
# --------------------------------------------------------------------------

def hold_ev_exact(dealt: Sequence[int], hold_mask: int,
                  paytable: Mapping[str, int]) -> Fraction:
    """Exact EV of holding ``hold_mask`` (bits over the ASCENDING-sorted
    deal) via the U tables + inclusion-exclusion.  Scalar reference path."""
    pays = _paytable_key(paytable)
    dealt_sorted = sorted(int(c) for c in dealt)
    if len(dealt_sorted) != HAND_SIZE or len(set(dealt_sorted)) != HAND_SIZE:
        raise ValueError("dealt must be 5 distinct cards")
    if not 0 <= hold_mask < _N_MASKS:
        raise ValueError("hold_mask must be in 0..31")
    tables = _get_tables()
    u = tables["U"]
    u0 = tables["U0"]
    held = [dealt_sorted[i] for i in _MASK_POSITIONS[hold_mask]]
    discards = [c for c in dealt_sorted if c not in held]
    num = np.zeros(N_CAT, dtype=np.int64)
    for r in range(len(discards) + 1):
        sign = 1 if r % 2 == 0 else -1
        for t in itertools.combinations(discards, r):
            s = sorted(held + list(t))
            m = len(s)
            if m == 0:
                num += sign * u0
            elif m == HAND_SIZE:
                row = np.zeros(N_CAT, dtype=np.int64)
                row[int(evaluate_hands(np.array(s)[None, :])[0])] = 1
                num += sign * row
            else:
                num += sign * u[m][int(_colex(np.array(s, dtype=np.int64)[None, :])[0])]
    total = sum(int(n) * p for n, p in zip(num, pays))
    return Fraction(total, int(_C47[HAND_SIZE - len(held)]))


def hold_ev_bruteforce(dealt: Sequence[int], hold_mask: int,
                       paytable: Mapping[str, int]) -> Fraction:
    """Independent check: enumerate every replacement draw explicitly."""
    pays = _paytable_key(paytable)
    dealt_sorted = sorted(int(c) for c in dealt)
    held = [dealt_sorted[i] for i in _MASK_POSITIONS[hold_mask]]
    d = HAND_SIZE - len(held)
    remaining = [c for c in range(DECK_SIZE) if c not in dealt_sorted]
    if d == 0:
        combos = np.empty((1, 0), dtype=np.int64)
    else:
        combos = np.array(list(itertools.combinations(remaining, d)), dtype=np.int64)
    full = np.hstack(
        [np.tile(np.array(held, dtype=np.int64), (combos.shape[0], 1)), combos]
    )
    cats = evaluate_hands(full)
    pays_arr = np.array(pays, dtype=np.int64)
    total = int(pays_arr[cats].sum())
    count = combos.shape[0]
    assert count == int(_C47[d])
    return Fraction(total, count)


# --------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------

_SIM_CHUNK_ROUNDS = 500_000  # 500k x 52-float FY decks: pool matrix ~ chunked in rng


class VideoPoker:
    """Video Poker engine (Stake paytable by default).

    (a) exact analytic paytable/probability/RTP/variance (full-cycle
        enumeration, optimal play), (b) provably-fair single-round play on
        the verified rng core, (c) vectorized 10M+-round simulator using the
        precomputed optimal-hold table, (d) the standard result dict
        {rtp, house_edge, std_per_unit, config}.
    """

    def __init__(self, paytable: Optional[Mapping[str, int]] = None,
                 cache_dir: Optional[str] = None) -> None:
        self.paytable: Dict[str, int] = dict(
            STAKE_PAYTABLE if paytable is None else paytable
        )
        self._key = _paytable_key(self.paytable)
        self._pays = np.array(self._key, dtype=np.int64)
        self.cache_dir = cache_dir
        self._solution: Optional[Solution] = None

    # -- analytic ----------------------------------------------------------

    @property
    def solution(self) -> Solution:
        if self._solution is None:
            self._solution = solve_paytables(
                [self.paytable], cache_dir=self.cache_dir
            )[0]
        return self._solution

    @property
    def rtp_exact(self) -> Fraction:
        return self.solution.ev

    @property
    def rtp(self) -> float:
        return float(self.solution.ev)

    @property
    def house_edge(self) -> float:
        return 1.0 - self.rtp

    @property
    def variance_per_unit(self) -> float:
        """Variance of net result per 1 unit bet (= variance of the payout
        multiplier; the -1 shift cancels)."""
        return float(self.solution.variance)

    @property
    def std_per_unit(self) -> float:
        return self.solution.std

    @property
    def hold_ev_covariance(self) -> Fraction:
        """Exact shared-deal covariance c = Var(E[payout | deal]) — the
        covariance between any two hands of an n-play game (same dealt 5
        cards and hold, independent draws)."""
        return self.solution.hold_ev_variance

    def n_play_variance(self, n_plays: int) -> Fraction:
        """Exact per-hand n-play variance v + (n-1)*c (WoO Appendix 3)."""
        return self.solution.n_play_variance(n_plays)

    def n_play_std(self, n_plays: int) -> float:
        """Per-hand n-play standard deviation (WoO Appendix 3)."""
        return self.solution.n_play_std(n_plays)

    def category_probabilities(self) -> Dict[str, Fraction]:
        """Exact final-hand probabilities under optimal play."""
        return dict(zip(CATEGORIES, self.solution.category_probs))

    def return_table(self) -> List[Dict[str, object]]:
        """Wizard-of-Odds-style return table, highest hand first:
        ``pays`` | ``combinations`` | ``probability`` | ``return`` per
        category.  ``combinations`` are exact integers on the common
        denominator ``COMBINATIONS_DENOMINATOR`` = L * C(52,5) =
        19,933,230,517,200 (each deal weighted by L = lcm{C(47,d)} so all
        hold sizes share one denominator — the WoO Combinations column);
        the return column sums to the exact optimal-play RTP."""
        sol = self.solution
        rows: List[Dict[str, object]] = []
        for c in reversed(range(N_CAT)):
            name = CATEGORIES[c]
            prob = sol.category_probs[c]
            pay = self.paytable.get(name, 0)
            rows.append(
                {
                    "category": name,
                    "label": CATEGORY_LABELS[name],
                    "pays": pay,
                    "combinations": int(sol.cat_scaled_sums[c]),
                    "probability": float(prob),
                    "probability_exact": prob,
                    "return": float(prob * pay),
                    "return_exact": prob * pay,
                }
            )
        return rows

    def category_table(self) -> List[Dict[str, object]]:
        """Per-category paytable line: pays, exact probability, contribution."""
        rows = []
        for name, prob in zip(CATEGORIES, self.solution.category_probs):
            pay = self.paytable.get(name, 0)
            rows.append(
                {
                    "category": name,
                    "label": CATEGORY_LABELS[name],
                    "pays": pay,
                    "probability": float(prob),
                    "probability_exact": prob,
                    "contribution": float(prob * pay),
                }
            )
        return rows

    def config(self) -> Dict[str, object]:
        return {
            "game": "video_poker",
            "variant": "jacks_or_better",
            "deck": DECK_SIZE,
            "hand": HAND_SIZE,
            "paytable": dict(self.paytable),
            "strategy": "exact_optimal_full_cycle",
        }

    def analytic_summary(self) -> Dict[str, object]:
        """Standard result dict, analytic (no simulation)."""
        return {
            "rtp": self.rtp,
            "house_edge": self.house_edge,
            "std_per_unit": self.std_per_unit,
            "config": self.config(),
            "rtp_exact": str(self.rtp_exact),
            "variance_per_unit": self.variance_per_unit,
            "category_probabilities": {
                name: float(p) for name, p in self.category_probabilities().items()
            },
        }

    # -- strategy lookups --------------------------------------------------

    @staticmethod
    def _validated_deal(dealt: Sequence[int]) -> List[int]:
        cards = [int(c) for c in dealt]
        if len(cards) != HAND_SIZE or len(set(cards)) != HAND_SIZE or not all(
            0 <= c < DECK_SIZE for c in cards
        ):
            raise ValueError(
                f"dealt must be {HAND_SIZE} distinct cards in 0..{DECK_SIZE - 1}, "
                f"got {dealt!r}"
            )
        return cards

    def optimal_hold_mask_sorted(self, dealt: Sequence[int]) -> int:
        """Optimal hold mask, bit i = hold i-th card of the SORTED deal.
        ``dealt`` must be exactly 5 distinct cards in 0..51."""
        arr = np.sort(np.asarray(self._validated_deal(dealt), dtype=np.int64))
        return int(self.solution.pattern_table[int(hand_colex_rank(arr)[0])])

    def optimal_holds(self, dealt: Sequence[int]) -> List[bool]:
        """Hold flags in the ORIGINAL deal order."""
        dealt = self._validated_deal(dealt)
        order = np.argsort(np.asarray(dealt, dtype=np.int64), kind="stable")
        mask = self.optimal_hold_mask_sorted(dealt)
        holds = [False] * HAND_SIZE
        for sorted_pos in range(HAND_SIZE):
            if (mask >> sorted_pos) & 1:
                holds[int(order[sorted_pos])] = True
        return holds

    # -- provably-fair single round ---------------------------------------

    def play_round(
        self,
        server_seed: str,
        client_seed: str,
        nonce: int,
        bet: float = 1.0,
        holds: Optional[Sequence[bool]] = None,
        cursor: int = 0,
    ) -> Dict[str, object]:
        """One verifiable round on the scalar rng path.

        The 52 game events (full Fisher-Yates deck) come from
        :func:`spinquest_sim.rng.video_poker_deck`; the first 5 cards are the
        deal, discards are replaced left-to-right by the next deck cards.
        ``holds`` is 5 booleans in deal order; None = optimal play.
        """
        if bet <= 0:
            raise ValueError("bet must be positive")
        deck = sq_rng.video_poker_deck(server_seed, client_seed, nonce, cursor)
        dealt = deck[:HAND_SIZE]
        if holds is None:
            hold_flags = self.optimal_holds(dealt)
        else:
            hold_flags = [bool(h) for h in holds]
            if len(hold_flags) != HAND_SIZE:
                raise ValueError("holds must have exactly 5 entries")
        final = list(dealt)
        draw_ptr = HAND_SIZE
        for i in range(HAND_SIZE):
            if not hold_flags[i]:
                final[i] = deck[draw_ptr]
                draw_ptr += 1
        category = evaluate_hand(final)
        mult = self.paytable.get(category, 0)
        return {
            "dealt": list(dealt),
            "dealt_names": [sq_rng.card_name(c) for c in dealt],
            "holds": hold_flags,
            "final": final,
            "final_names": [sq_rng.card_name(c) for c in final],
            "category": category,
            "payout_multiplier": float(mult),
            "bet": bet,
            "payout": bet * mult,
            "config": self.config(),
            "verification": {
                "server_seed_hash": sq_rng.hash_server_seed(server_seed),
                "client_seed": client_seed,
                "nonce": nonce,
                "cursor": cursor,
            },
        }

    # -- vectorized simulator ---------------------------------------------

    def simulate(
        self,
        n_rounds: int,
        bulk: Optional[BulkRng] = None,
        chunk_rounds: int = _SIM_CHUNK_ROUNDS,
        progress: bool = True,
    ) -> Dict[str, object]:
        """Simulate ``n_rounds`` provably-fair rounds (one nonce per round)
        with optimal play from the precomputed hold table; returns the
        standard result dict.

        Row i is bit-for-bit verifiable against the scalar path at nonce
        ``nonce_start + i`` (same committed deck permutation, same hold
        decision, same payout).  Only the first 10 floats of the round are
        generated — a payout can never depend on more (see the chunk-loop
        comment); the scalar :meth:`play_round` still generates the full
        52-card deck exactly as documented.
        """
        if n_rounds <= 0:
            raise ValueError("n_rounds must be positive")
        pattern_table = self.solution.pattern_table  # triggers solve if needed
        held_lut = np.zeros((_N_MASKS, HAND_SIZE), dtype=bool)
        for m, pos in enumerate(_MASK_POSITIONS):
            held_lut[m, list(pos)] = True

        rng = bulk if bulk is not None else BulkRng()
        nonce_first = rng.nonce_next
        pay_sum = 0
        pay_sq_sum = 0
        cat_counts = np.zeros(N_CAT, dtype=np.int64)
        done = 0
        t0 = time.perf_counter()
        while done < n_rounds:
            step = min(chunk_rounds, n_rounds - done)
            # A round can consume at most 10 deck cards (5 dealt + up to 5
            # replacements), and Fisher-Yates draw j depends only on floats
            # 0..j — so the first 10 cards of the committed 52-card
            # permutation need only the first 10 floats (2 HMAC digests, not
            # 7; the other 5 digests never influence a payout).
            # draws_without_replacement(52, 10, .) is bit-identical to
            # video_poker_decks(., cards_needed=10) and to the scalar
            # video_poker_deck()[:10] at the same nonce (asserted by the
            # tests and the validator's nonce-by-nonce replay); nonce
            # accounting is unchanged (one nonce per bet, cursor 0).
            deck10 = rng.draws_without_replacement(DECK_SIZE, 2 * HAND_SIZE, step)
            dealt = deck10[:, :HAND_SIZE]
            sorted_dealt = np.sort(dealt, axis=1)
            masks = pattern_table[_colex(sorted_dealt)].astype(np.int64)
            held = held_lut[masks]  # (step, 5) over sorted positions
            # j-th discarded slot (left-to-right in sorted order) takes
            # replacement card deck10[:, 5 + j].
            repl_slot = np.cumsum(~held, axis=1) - 1  # -1 on leading held slots
            repl = np.take_along_axis(deck10, HAND_SIZE + repl_slot, axis=1)
            final = np.where(held, sorted_dealt, repl)
            cats = evaluate_hands(final)
            pays = self._pays[cats]
            pay_sum += int(pays.sum())
            pay_sq_sum += int((pays * pays).sum())
            cat_counts += np.bincount(cats, minlength=N_CAT)
            done += step
            if progress and n_rounds > chunk_rounds:
                rate = done / (time.perf_counter() - t0)
                print(
                    f"  video_poker: {done:,}/{n_rounds:,} rounds ({rate:,.0f}/s)",
                    flush=True,
                )
        elapsed = time.perf_counter() - t0

        rtp_emp = pay_sum / n_rounds
        var_emp = pay_sq_sum / n_rounds - rtp_emp * rtp_emp
        std_emp = math.sqrt(max(var_emp, 0.0))
        se_analytic = self.std_per_unit / math.sqrt(n_rounds)
        z = (rtp_emp - self.rtp) / se_analytic if se_analytic > 0 else 0.0
        return {
            "rtp": rtp_emp,
            "house_edge": 1.0 - rtp_emp,
            "std_per_unit": std_emp,
            "config": self.config(),
            "n_rounds": n_rounds,
            "category_counts": {
                name: int(c) for name, c in zip(CATEGORIES, cat_counts)
            },
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
