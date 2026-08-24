#!/usr/bin/env python3
"""Deterministic calibration that produced (and reproduces) the shipped
Atkins / Scarab reel strips in ``spinquest_sim/games/slots.py``.

No randomness anywhere: exact integer / Fraction arithmetic, fixed
iteration orders, fixed tie-breaks.  Re-running this script re-derives
``ATKINS_STRIPS`` and ``SCARAB_STRIPS`` byte-for-byte and exits 0 only if
they match the shipped constants AND full engine enumeration of the result
prints every published figure exactly (see WOO_ATKINS_PRINTED /
STAKE_SCARAB_PRINTED).

How the Atkins calibration works
--------------------------------
The Wizard publishes eight aggregates (references/woo/slots.md).  Three
structural facts make them solvable exactly:

1. The per-line expected pay depends only on per-reel symbol COUNTS (each
   stop is uniform on a cyclic strip), so line return = M / 32^5 where
   M = sum over all symbol 5-tuples of pay(tuple) * prod_i counts_i(s_i),
   an integer when pays are integers.
2. The scatter figures depend only on scatters-per-reel: with counts
   (1,1,1,2,1) spaced >= 3 apart, P(3+ scatters) = 93825/2^23 (prints
   0.011185 and makes E[spins/bonus] print 11.259335) and the scatter
   return is 1170315/2^24 (prints 6.976%) — both independent of position.
3. The remaining published figures (line 63.460%, bonus 26.610%, total
   97.046%, E[bonus win] 23.791632) then pin line return to an interval
   narrower than 1/32^5 — and since every pay is a whole number of
   line-bet units, M is an integer, leaving exactly ONE attainable
   target: M* = 21,293,527, i.e. line return = 21293527/32^5.

Stage 1 derives that window with exact Fractions and asserts M* is its
unique integer.  Stage 2 hits M* exactly: starting from the
documented draft par sheet counts (which print line/scatter/hit/p right
but miss the bonus chain by +8 ppm), it scans, in a fixed order, every
perturbation of one donor reel within an L1<=4 box and solves reel 2's
full count vector exactly by meet-in-the-middle (symbols 0-4 vs 5-9,
counts 1..12, wild capped at 3), keeping the hit frequency inside its
printed window; the winner is the solution minimising total L1 distance.
Stage 3 arranges counts into strips with a fixed greedy interleave
(largest-remaining-count first, +-1-neighbour avoidance, quadratic
tie-break key) that never touches any published figure — strip ORDER only
affects variance.  Stage 4 verifies everything through the engine's own
``enumerate_exact`` and gates on the printed strings.

How the Scarab calibration works
--------------------------------
Stake publishes the complete Scarab Spin paytable, the 30/30/30/30/41
geometry, RTP 97.84%, 15 free spins on 3 scatters, a 10,000x max win and
the wild mechanic ("random wilds in the base game") — but neither the reel
strips nor the wild frequencies (reference Sect. 7).  The reconstruction
is DERIVED, not asserted, in three Scarab stages:

Stage S1 (par-sheet shape): per-reel symbol counts for the 11 line symbols
are the ranked nearest integer ladders to the classic inverse-square-root
-of-pay profile c*(s) ∝ pay5(s)^(-1/2): enumerate EVERY monotone
non-increasing (in 5-of-a-kind pay) count vector with min 1 per symbol,
sum = reel length - scatters, and 13-entry cv >= 0.4, sort by (squared L2
distance to c*, lexicographic); reels 1-4 take ranks 1-4 of the 29-stop
enumeration (so no two reels share a vector), reel 5 takes rank 1 of the
40-stop enumeration.  The wild takes NO strip stops (it is the published
random overlay); each reel carries one scatter at position (4+7i) mod L.
The result must pass every gate in ``SCARAB_SHAPE_GATES`` (Spearman(pay,
count) <= -0.9, distinct reels, cv, monotone ladder).

Stage S2 (exact wild-drop solve): the published random wilds are the
overlay feature (float 5 arms the drop, floats 6-20 cover the 15 tiles).
The tile threshold is selected by a fixed scan of the dyadic grid j/16,
j = 1..15: for each j the fire threshold K_j is the unique 32-bit integer
minimising the exact rational distance |RTP - 97.84%| (RTP = (E0 +
pi*(E1-E0) + sc)/(1 - 15p), every term an exact Fraction via big-integer
contraction of the paytable LUT), and the engine's factorized second
moments give the full-round SD; the winner is the j whose SD lands inside
the published slot-SD band 5.18-13.45 (WoO Cleopatra by lines) closest to
WoO's published typical slot SD 8.74 — j = 8 (tile probability exactly
1/2), K = 203404370, SD 8.5921, RTP = 0.9784000009194... which prints
"97.84"/"2.16" with 9.2e-10 to spare against the half-ULP window 5e-5.

Stage S3 reuses the deterministic strip arrangement (order never touches
any published figure), and Stage S4 verifies everything through the
engine's own analytics and gates on the printed strings, the shape gates
and byte-identity with the shipped constants.

Usage:  python scripts/calibrate_slots.py
"""

from __future__ import annotations

import itertools
import math
import sys
from fractions import Fraction
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from spinquest_sim.games import slots as S  # noqa: E402

DENOM = 32 ** 5

# The draft Atkins par sheet this calibration started from: symbol counts
# per reel (10 non-scatter symbols, wild first) + scatters (1,1,1,2,1).
# It already printed line 63.460 / scatter 6.976 / hit 5.45 / p 0.011185
# but its M = 21,293,718 sat +191 above the attainable target, leaving the
# bonus chain +8 ppm high (prints 26.611 / 97.047 / 23.791825).
ATKINS_SEED_COUNTS: Tuple[Tuple[int, ...], ...] = (
    (3, 2, 5, 1, 1, 2, 1, 2, 9, 5),
    (2, 1, 2, 1, 1, 1, 4, 3, 9, 7),
    (1, 2, 4, 1, 3, 3, 4, 5, 3, 5),
    (2, 3, 3, 3, 4, 3, 3, 4, 2, 3),
    (3, 2, 3, 4, 4, 2, 2, 3, 4, 4),
)
ATKINS_SCATTERS_PER_REEL = (1, 1, 1, 2, 1)
ATKINS_SCATTER_POS = ((4,), (9,), (14,), (4, 20), (24,))
SOLVE_REEL = 1          # the reel whose counts are re-solved exactly
DONOR_REELS = (0, 2, 3, 4)
BOX_LO, BOX_HI = 1, 12  # count bounds for the solved reel
WILD_HI = 3             # wild count cap everywhere

# Scarab derivation parameters (stages S1/S2; nothing below asserts the
# resulting count matrix or thresholds — they are re-derived every run and
# compared to the shipped constants at the end).
SCARAB_LENS = (30, 30, 30, 30, 41)
SCARAB_SCATTERS_PER_REEL = (1, 1, 1, 1, 1)
SCARAB_TILE_GRID_DEN = 16          # tile-probability scan grid j/16
_TWO32 = 1 << 32


# ---------------------------------------------------------------------------
# Stage 1: derive the unique attainable target M*
# ---------------------------------------------------------------------------

def derive_target() -> Tuple[int, Tuple[float, float]]:
    p = Fraction(93825, 2 ** 23)               # P(3+ scatters), Stage-0 fact
    sc = Fraction(1170315, 2 ** 24)            # scatter return
    e_spins = Fraction(10) / (1 - 10 * p)
    assert f"{float(p):.6f}" == "0.011185"
    assert f"{float(e_spins):.6f}" == "11.259335"
    # printed-string windows (round-half-up closed/open intervals)
    windows = []
    # E[bonus win] = 3*(L+sc)*e_spins prints 23.791632
    windows.append(((Fraction("23.7916315") / (3 * e_spins)) - sc,
                    (Fraction("23.7916325") / (3 * e_spins)) - sc))
    # line prints 63.460
    windows.append((Fraction("0.6345950"), Fraction("0.6346050")))
    # bonus = p*E[T] prints 26.610
    windows.append(((Fraction("0.2660950") / (3 * e_spins * p)) - sc,
                    (Fraction("0.2661050") / (3 * e_spins * p)) - sc))
    # total = (L+sc)*(1 + 3*p*e_spins) prints 97.046
    fac = 1 + 3 * p * e_spins
    windows.append((Fraction("0.9704550") / fac - sc,
                    Fraction("0.9704650") / fac - sc))
    lo = max(w[0] for w in windows) * DENOM
    hi = min(w[1] for w in windows) * DENOM
    ints = [x for x in range(math.floor(lo) + 1, math.ceil(hi))
            if lo < x < hi]
    assert len(ints) == 1, (float(lo), float(hi), ints)
    m_star = ints[0]
    h_win = (0.05445 * DENOM, 0.05455 * DENOM)   # hit freq prints 5.45
    print(f"[stage1] M window ({float(lo):.4f}, {float(hi):.4f}) -> unique "
          f"integer M* = {m_star} (line return = {m_star/DENOM:.10f})")
    return m_star, h_win


# ---------------------------------------------------------------------------
# Stage 2: hit M* exactly
# ---------------------------------------------------------------------------

def _lut_tables() -> Tuple[np.ndarray, np.ndarray]:
    """Single-line pay LUT (line-bet units) + hit indicator, 11^5 tensors.
    Depends only on the paytable — built through the engine's own LUT."""
    seed_strips = [arrange(r, 32, ATKINS_SEED_COUNTS[r], 10,
                           ATKINS_SCATTER_POS[r]) for r in range(5)]
    m = S.SlotMachine(
        name="seed", symbols=S.ATKINS_SYMBOLS, strips=seed_strips,
        line_pays=S.ATKINS_LINE_PAYS, wild=S.ATKINS_WILD,
        scatter=S.ATKINS_SCATTER, scatter_pays=S.ATKINS_SCATTER_PAYS,
        scatter_pay_basis="total", free_spins=10, free_spin_multiplier=3)
    n = m.n_symbols
    lut = (m._lut_cents // 100).reshape((n,) * 5).astype(np.float64)
    hit = (m._lut_cents > 0).reshape((n,) * 5).astype(np.float64)
    return lut, hit


def solve_counts(m_star: int, h_win: Tuple[float, float]
                 ) -> List[List[int]]:
    lut, hitl = _lut_tables()
    scat = S.ATKINS_SCATTER
    counts0 = np.zeros((5, 11), dtype=np.float64)
    for r in range(5):
        counts0[r, :10] = ATKINS_SEED_COUNTS[r]
        counts0[r, scat] = ATKINS_SCATTERS_PER_REEL[r]
    cur1 = counts0[SOLVE_REEL, :10].astype(int)

    letters = "abcde"

    def pair(tensor: np.ndarray, donor: int) -> np.ndarray:
        ops, subs = [tensor], ["abcde"]
        for r in range(5):
            if r in (donor, SOLVE_REEL):
                continue
            ops.append(counts0[r])
            subs.append(letters[r])
        sub = ",".join(subs) + "->" + letters[donor] + letters[SOLVE_REEL]
        return np.round(np.einsum(sub, *ops)).astype(np.int64)

    # enumeration tables for the solved reel (built once)
    def sym_range(s: int) -> np.ndarray:
        return np.arange(BOX_LO, (WILD_HI if s == 0 else BOX_HI) + 1)

    meshL = np.meshgrid(*[sym_range(s) for s in range(5)], indexing="ij")
    L_counts = np.stack([g.reshape(-1) for g in meshL], axis=1)
    L_ssum = L_counts.sum(axis=1)
    L_l1 = np.abs(L_counts - cur1[0:5]).sum(axis=1)
    meshR = np.meshgrid(*[sym_range(s + 5) for s in range(5)], indexing="ij")
    R_counts = np.stack([g.reshape(-1) for g in meshR], axis=1)
    R_ssum = R_counts.sum(axis=1)
    R_l1 = np.abs(R_counts - cur1[5:10]).sum(axis=1)
    KEY = 1 << 44
    slots_total = int(cur1.sum())

    def solve_reel(g1: np.ndarray, h1: np.ndarray
                   ) -> List[Tuple[int, Tuple[int, ...], int]]:
        target = m_star - int(g1[scat]) * int(counts0[SOLVE_REEL, scat])
        gg, base = 0, int(g1[9])
        for s in range(10):
            gg = math.gcd(gg, abs(int(g1[s]) - base))
        if gg and (target - slots_total * base) % gg:
            return []
        Lkey = L_ssum * KEY + (L_counts @ g1[0:5])
        Rkey = (slots_total - R_ssum) * KEY + (target - R_counts @ g1[5:10])
        order = np.argsort(Lkey, kind="stable")
        Lk = Lkey[order]
        pos = np.searchsorted(Lk, Rkey)
        ok = pos < Lk.size
        match = np.zeros(Rkey.size, dtype=bool)
        match[ok] = Lk[pos[ok]] == Rkey[ok]
        out = []
        for ri in np.nonzero(match)[0]:
            p = pos[ri]
            while p < Lk.size and Lk[p] == Rkey[ri]:
                li = order[p]
                full = np.concatenate([L_counts[li], R_counts[ri]])
                hv = int(full @ h1[:10]) + int(h1[scat]) * \
                    int(counts0[SOLVE_REEL, scat])
                if h_win[0] <= hv < h_win[1]:
                    out.append((int(L_l1[li] + R_l1[ri]),
                                tuple(int(x) for x in full), hv))
                p += 1
        return out

    def donor_vectors(donor: int):
        curA = counts0[donor, :10].astype(int)
        tot = int(curA.sum())
        rngs = []
        for s in range(10):
            lo = max(1, curA[s] - 2)
            hi = min(curA[s] + 2, WILD_HI) if s == 0 else curA[s] + 2
            rngs.append(range(lo, hi + 1))
        out = []
        for combo in itertools.product(*rngs):
            if sum(combo) != tot:
                continue
            l1 = sum(abs(c - int(curA[s])) for s, c in enumerate(combo))
            if l1 <= 4:
                out.append((l1, combo))
        out.sort()
        return out

    best: Optional[Tuple] = None
    for donor in DONOR_REELS:
        G = pair(lut, donor)
        Hp = pair(hitl, donor)
        cands = donor_vectors(donor)
        print(f"[stage2] donor reel {donor}: {len(cands)} candidate vectors",
              flush=True)
        for l1A, cA in cands:
            cvec = np.array(list(cA) + [int(counts0[donor, scat])],
                            dtype=np.int64)
            for (l1B, c1, hv) in solve_reel(cvec @ G, cvec @ Hp):
                cand = (l1A + l1B, donor, cA, c1, hv)
                print(f"[stage2]   exact solution: donor {donor} -> {cA}, "
                      f"reel {SOLVE_REEL} -> {c1} (L1 {cand[0]})", flush=True)
                if best is None or cand < best:
                    best = cand
    assert best is not None, "no exact solution found"
    _, donor, cA, c1, _ = best
    counts = [list(ATKINS_SEED_COUNTS[r]) for r in range(5)]
    counts[donor] = list(cA)
    counts[SOLVE_REEL] = list(c1)
    print(f"[stage2] winner (min L1={best[0]}): donor reel {donor} -> {cA}, "
          f"reel {SOLVE_REEL} -> {c1}")
    return counts


# ---------------------------------------------------------------------------
# Stage 3: deterministic strip arrangement (order never touches returns)
# ---------------------------------------------------------------------------

def arrange(reel_idx: int, length: int, counts_nonscatter: Sequence[int],
            scatter_sym: int, scatter_positions: Sequence[int]) -> List[int]:
    """Greedy interleave: largest remaining count first, skipping symbols
    within +-1 of the previous placement when an alternative exists;
    fixed quadratic tie-break key so equal-count reels still differ."""
    remaining = {s: c for s, c in enumerate(counts_nonscatter) if c > 0}
    strip: List[Optional[int]] = [None] * length
    for p in scatter_positions:
        strip[p] = scatter_sym
    prev: Optional[int] = None
    slot_no = 0
    for pos in range(length):
        if strip[pos] is not None:
            prev = strip[pos]
            continue
        cands = sorted(
            remaining,
            key=lambda s: (-remaining[s],
                           (7 * s + 5 * slot_no + 3 * slot_no * slot_no
                            + 3 * reel_idx) % 11, s))
        pick = next((s for s in cands if prev is None or abs(s - prev) > 1),
                    cands[0])
        strip[pos] = pick
        remaining[pick] -= 1
        if remaining[pick] == 0:
            del remaining[pick]
        prev = pick
        slot_no += 1
    assert not remaining
    return [int(x) for x in strip]


# ---------------------------------------------------------------------------
# Stage 4: full-engine verification + comparison with shipped constants
# ---------------------------------------------------------------------------

def verify_atkins(strips: List[List[int]]) -> bool:
    m = S.SlotMachine(
        name="atkins", symbols=S.ATKINS_SYMBOLS, strips=strips,
        line_pays=S.ATKINS_LINE_PAYS, wild=S.ATKINS_WILD,
        scatter=S.ATKINS_SCATTER, scatter_pays=S.ATKINS_SCATTER_PAYS,
        scatter_pay_basis="total", free_spins=10, free_spin_multiplier=3)
    ex = m.enumerate_exact()
    ok = True
    for fig, (key, scale, spec, want) in S.WOO_ATKINS_PRINTED.items():
        got = format(scale * float(ex[key]), spec)
        good = got == want
        ok = ok and good
        print(f"[stage4] atkins {fig:22s} prints {got!r} want {want!r} "
              f"{'ok' if good else 'FAIL'}")
    return ok


# ---------------------------------------------------------------------------
# Scarab stage S1: shape-constrained ladder count derivation
# ---------------------------------------------------------------------------

def _scarab_pays5() -> List[float]:
    """5-of-a-kind pays of the 11 line symbols, ascending (published table
    order — SCARAB_SYMBOLS[0..10])."""
    return [S.SCARAB_LINE_PAYS[s][5] for s in range(11)]


def _cv13(vec11: Sequence[int], n_scat: int) -> float:
    """Coefficient of variation of a reel's full 13-entry count vector
    (11 line symbols + wild 0 + scatter)."""
    v = np.array(list(vec11) + [0, n_scat], dtype=np.float64)
    return float(v.std() / v.mean())


def _spearman(x: Sequence[float], y: Sequence[float]) -> float:
    """Spearman rank correlation (average ranks for ties; no scipy)."""
    def ranks(a):
        order = np.argsort(a, kind="stable")
        r = np.empty(len(a))
        av = np.asarray(a, dtype=np.float64)
        i = 0
        srt = av[order]
        while i < len(a):
            j = i
            while j + 1 < len(a) and srt[j + 1] == srt[i]:
                j += 1
            r[order[i:j + 1]] = (i + j) / 2.0 + 1.0
            i = j + 1
        return r
    rx, ry = ranks(list(x)), ranks(list(y))
    rx -= rx.mean()
    ry -= ry.mean()
    return float((rx * ry).sum() / math.sqrt((rx ** 2).sum() * (ry ** 2).sum()))


def scarab_stage1_counts() -> List[List[int]]:
    """Derive the 5 per-reel count vectors: ranked nearest integer ladders
    to the pay^(-1/2) profile (see module docstring)."""
    pays = _scarab_pays5()
    weights = np.array([p ** -0.5 for p in pays])

    def ranked(budget: int, n_scat: int) -> List[Tuple[float, Tuple[int, ...]]]:
        target = budget * weights / weights.sum()
        out: List[Tuple[float, Tuple[int, ...]]] = []

        def rec(i: int, prev: int, left: int, acc: List[int]) -> None:
            if i == 10:
                if 1 <= left <= prev:
                    out.append((0.0, tuple(acc + [left])))
                return
            for c in range(min(prev, left - (10 - i)), 0, -1):
                rec(i + 1, c, left - c, acc + [c])

        rec(0, budget, budget, [])
        scored = []
        for _, v in out:
            if _cv13(v, n_scat) < S.SCARAB_SHAPE_GATES["per_reel_cv_min"]:
                continue
            d = float(((np.array(v) - target) ** 2).sum())
            scored.append((d, v))
        scored.sort()
        return scored

    counts: List[List[int]] = []
    r29 = ranked(SCARAB_LENS[0] - SCARAB_SCATTERS_PER_REEL[0], 1)
    for r in range(4):
        counts.append(list(r29[r][1]))
    r40 = ranked(SCARAB_LENS[4] - SCARAB_SCATTERS_PER_REEL[4], 1)
    counts.append(list(r40[0][1]))
    for r in range(5):
        print(f"[scarabS1] reel {r + 1} counts {tuple(counts[r])} "
              f"(cv {_cv13(counts[r], 1):.3f})")

    # hard shape gates (SCARAB_SHAPE_GATES)
    for r in range(5):
        assert all(counts[r][i] >= counts[r][i + 1] for i in range(10)), \
            "ladder not monotone in pay"
        assert _cv13(counts[r], 1) >= S.SCARAB_SHAPE_GATES["per_reel_cv_min"]
    assert len({tuple(c) for c in counts}) == 5, "duplicate reel count vector"
    totals = [sum(counts[r][s] for r in range(5)) for s in range(11)] + [0]
    rho = _spearman(pays + [S.SCARAB_LINE_PAYS[S.SCARAB_WILD][5]], totals)
    print(f"[scarabS1] Spearman(5oak pay, total count) = {rho:+.4f} "
          f"(need <= -{S.SCARAB_SHAPE_GATES['spearman_abs_min']})")
    assert rho <= -S.SCARAB_SHAPE_GATES["spearman_abs_min"]
    return counts


# ---------------------------------------------------------------------------
# Scarab stage S2: exact wild-drop solve (tile grid scan + exact fire K)
# ---------------------------------------------------------------------------

def scarab_stage2_wild_drop(strips: List[List[int]]
                            ) -> Tuple[int, int, float]:
    """Scan tile probabilities j/16; for each, solve the exact fire
    threshold K minimising |RTP - 97.84%| (Fractions throughout) and
    compute the full-round SD via the engine's factorized analytics; pick
    the in-band SD closest to WoO's published typical slot SD 8.74."""
    lo_sd, hi_sd = S.WOO_SLOT_SD_BAND
    target_rtp = Fraction(9784, 10000)
    F = 15

    def machine(fire_k: int, tile_k: int) -> S.SlotMachine:
        return S.SlotMachine(
            name="scarab_spin", symbols=S.SCARAB_SYMBOLS, strips=strips,
            line_pays=S.SCARAB_LINE_PAYS, wild=S.SCARAB_WILD,
            scatter=S.SCARAB_SCATTER, scatter_pays=S.SCARAB_SCATTER_PAYS,
            scatter_pay_basis="line", free_spins=F, free_spin_multiplier=1,
            wild_drop_fire_k=fire_k, wild_drop_tile_k=tile_k,
            max_win=S.SCARAB_MAX_WIN)

    probe = machine(1, 1)   # structure only; used for the exact components
    e0, _ = probe._exact_line_component(0)
    sc_ret, p, _ = probe._scatter_return_exact()
    need = target_rtp * (1 - F * p) - sc_ret - e0
    print(f"[scarabS2] exact E0 = {e0} = {float(e0):.10f}; "
          f"p = {p} = {float(p):.10f}; sc = {float(sc_ret):.10f}")

    best: Optional[Tuple[float, int, int, int, Fraction]] = None
    for j in range(1, SCARAB_TILE_GRID_DEN):
        tile_k = j * (_TWO32 // SCARAB_TILE_GRID_DEN)
        e1, _ = probe._exact_line_component(tile_k)
        if e1 <= e0:
            continue
        pi = need / (e1 - e0)
        if not (0 < pi < 1):
            print(f"[scarabS2] tile {j}/16: infeasible (pi = {float(pi):.4f})")
            continue
        fire_k = round(pi * _TWO32)
        # exact RTP at the integer threshold (round() minimises the exact
        # distance because RTP is linear in the threshold)
        rtp = (e0 + Fraction(fire_k, _TWO32) * (e1 - e0) + sc_ret) / (1 - F * p)
        sd = float(machine(fire_k, tile_k).enumerate_exact()["std_per_unit"])
        inband = lo_sd <= sd <= hi_sd
        print(f"[scarabS2] tile {j}/16: K = {fire_k}, "
              f"RTP = {float(rtp):.10f} (prints {100 * float(rtp):.2f}), "
              f"SD = {sd:.4f} {'in band' if inband else 'OUT OF BAND'} "
              f"|SD-{S.WOO_TYPICAL_SLOT_SD}| = {abs(sd - S.WOO_TYPICAL_SLOT_SD):.3f}")
        if inband:
            cand = (abs(sd - S.WOO_TYPICAL_SLOT_SD), j, tile_k, fire_k, rtp)
            if best is None or cand < best:
                best = cand
    assert best is not None, "no tile probability lands in the SD band"
    _, j, tile_k, fire_k, rtp = best
    sd = float(machine(fire_k, tile_k).enumerate_exact()["std_per_unit"])
    print(f"[scarabS2] winner: tile {j}/16 (K_tile = {tile_k}), "
          f"K_fire = {fire_k}, exact RTP = {rtp} = {float(rtp):.12f}, "
          f"SD = {sd:.4f}")
    return fire_k, tile_k, sd


def verify_scarab(strips: List[List[int]], fire_k: int, tile_k: int) -> bool:
    m = S.SlotMachine(
        name="scarab_spin", symbols=S.SCARAB_SYMBOLS, strips=strips,
        line_pays=S.SCARAB_LINE_PAYS, wild=S.SCARAB_WILD,
        scatter=S.SCARAB_SCATTER, scatter_pays=S.SCARAB_SCATTER_PAYS,
        scatter_pay_basis="line", free_spins=15, free_spin_multiplier=1,
        wild_drop_fire_k=fire_k, wild_drop_tile_k=tile_k,
        max_win=S.SCARAB_MAX_WIN)
    ex = m.enumerate_exact()
    ok = True
    for fig, (key, scale, spec, want) in S.STAKE_SCARAB_PRINTED.items():
        got = format(scale * float(ex[key]), spec)
        good = got == want
        ok = ok and good
        print(f"[stage4] scarab {fig:22s} prints {got!r} want {want!r} "
              f"{'ok' if good else 'FAIL'}")
    lo_sd, hi_sd = S.WOO_SLOT_SD_BAND
    sd = float(ex["std_per_unit"])
    sd_ok = lo_sd <= sd <= hi_sd
    ok = ok and sd_ok
    print(f"[stage4] scarab std_per_unit {sd:.4f} in published band "
          f"[{lo_sd}, {hi_sd}]: {'ok' if sd_ok else 'FAIL'}")
    return ok


def main() -> int:
    m_star, h_win = derive_target()
    counts = solve_counts(m_star, h_win)
    atkins = [arrange(r, 32, counts[r], S.ATKINS_SCATTER,
                      ATKINS_SCATTER_POS[r]) for r in range(5)]
    print("[stage3] ATKINS_STRIPS = (")
    for s in atkins:
        print("    (" + ", ".join(map(str, s)) + "),")
    print(")")

    scarab_counts = scarab_stage1_counts()
    scarab_pos = [((4 + 7 * i) % SCARAB_LENS[i],) for i in range(5)]
    scarab = [arrange(r, SCARAB_LENS[r], scarab_counts[r],
                      S.SCARAB_SCATTER, scarab_pos[r]) for r in range(5)]
    print("[scarabS3] SCARAB_STRIPS = (")
    for s in scarab:
        print("    (" + ", ".join(map(str, s)) + "),")
    print(")")
    fire_k, tile_k, sd = scarab_stage2_wild_drop(scarab)

    ok = verify_atkins(atkins) and verify_scarab(scarab, fire_k, tile_k)
    match_a = tuple(tuple(s) for s in atkins) == S.ATKINS_STRIPS
    match_s = tuple(tuple(s) for s in scarab) == S.SCARAB_STRIPS
    match_c = tuple(tuple(c) for c in scarab_counts) == S.SCARAB_COUNTS
    match_p = tuple(tuple(p) for p in scarab_pos) == S.SCARAB_SCATTER_POS
    match_k = (fire_k == S.SCARAB_WILD_FIRE_K
               and tile_k == S.SCARAB_WILD_TILE_K)
    print(f"[stage4] reproduces shipped ATKINS_STRIPS: {match_a}")
    print(f"[stage4] reproduces shipped SCARAB_COUNTS: {match_c}")
    print(f"[stage4] reproduces shipped SCARAB_SCATTER_POS: {match_p}")
    print(f"[stage4] reproduces shipped SCARAB_STRIPS: {match_s}")
    print(f"[stage4] reproduces shipped SCARAB_WILD_FIRE_K/TILE_K: {match_k}")
    ok = ok and match_a and match_s and match_c and match_p and match_k
    print(f"CALIBRATION: {'REPRODUCED' if ok else 'MISMATCH'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
