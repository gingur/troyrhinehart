#!/usr/bin/env python3
"""Validate spinquest_sim.games.video_poker against the captured references.

1. [table]    Payout-for-payout comparison of the engine paytable against BOTH
              published copies in references/stake/video_poker.md §6 (the
              description table and the in-game ladder).
2. [exact]    Full-cycle exact optimal-play analysis (all C(52,5) deals x all
              32 holds, integer/rational math) — ONE shared pass over all 9
              paytables (8 WoO variants + Stake's own):
                - Wizard-of-Odds 9/6 Jacks-or-Better benchmark
                  (references/woo/video_poker.md): return 99.5439%, SD 4.417542;
                - Stake's 800/60/22/9/6/4/3/2/1 table: the exact optimal-play
                  ceiling is 98.9445% (edge 1.0555%), so the published
                  "Edge: 1.00%" is NOT attainable under any strategy; only the
                  integer-rounded page title "99% RTP" is consistent with it.
                  This stage asserts the ceiling exactly and documents the
                  discrepancy rather than rubber-stamping the published edge.
3. [variants] All 8 WoO Jacks-or-Better pay-table variants (9/6, 9/5, 8/6,
              8/5, 7/5, 6/5, NetEnt 40-20-9-6-5, Gtech 20/7/5) reproduce the
              published optimal-strategy returns at the reference's displayed
              precision (2 decimals).
4. [multihand] WoO Appendix-3 multihand SDs: the solver's per-deal optimal-EV
              second moment gives the shared-deal covariance c exactly, and
              sqrt(v + (n-1)c) reproduces the published per-hand SD for
              n = 1/3/5/10/50/100 at 2 decimals.
5. [combos]   The 9/6 return table (pays | combinations | probability |
              return): the exact Combinations column on the common
              denominator 19,933,230,517,200 = lcm{C(47,d)} * C(52,5), which
              must match the Wizard's published Combinations integers
              (independently re-derived and cross-verified) and sum to the
              exact RTP.
6. [strat]    Independent strategy spot-checks: for seeded random deals, the
              precomputed optimal-hold table is re-derived by BRUTE FORCE
              (explicitly enumerating every replacement draw of all 32 holds,
              no shared code with the solver's U tables) and must agree.
7. [xcheck]   Scalar/vectorized equivalence: simulated rounds are replayed
              nonce-by-nonce through the scalar provably-fair path and must
              match payout-for-payout (this also proves the simulator's
              2-digest fast path equals the documented 7-digest full deck).
8. [sim]      10M+ provably-fair rounds per paytable on the verified BulkRng
              stream, optimal play from the precomputed hold table.  PASS
              requires: empirical RTP within 3 SE of exact, EVERY per-category
              count within 4 SE of its exact probability (|z| > 3 flagged),
              and the empirical second moment (equivalently SD) within 4 SE
              of exact using the exact 4th-moment standard error.

ALWAYS prints a machine-readable summary line VIDEO_POKER_VALIDATION_JSON:
{...} followed by OVERALL: PASS|FAIL — even if a stage crashes (the JSON then
carries "error" and overall_pass=false) — and exits 0 on PASS / 1 on FAIL.

Usage: python scripts/validate_video_poker.py [--rounds N] [--skip-sim]
       [--cache-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import traceback
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import random  # noqa: E402

import numpy as np  # noqa: E402

from spinquest_sim import rng as sq_rng  # noqa: E402
from spinquest_sim.rng import BulkRng  # noqa: E402
from spinquest_sim.games import video_poker as vp  # noqa: E402

# --------------------------------------------------------------------------
# References (verbatim values from the captured .md files)
# --------------------------------------------------------------------------

# references/stake/video_poker.md §6 — description-section table.
STAKE_DESCRIPTION_TABLE = {
    "Pair of Jacks or better": 1,
    "2 Pair": 2,
    "3 of a Kind": 3,
    "Straight": 4,
    "Flush": 6,
    "Full House": 9,
    "4 of a Kind": 22,
    "Straight Flush": 60,
    "Royal Flush": 800,
}
# references/stake/video_poker.md §6 — in-game paytable ladder (same page).
STAKE_INGAME_LADDER = {
    "Royal Flush": 800,
    "Straight Flush": 60,
    "4 of a Kind": 22,
    "Full House": 9.00,
    "Flush": 6.00,
    "Straight": 4.00,
    "3 of a Kind": 3.00,
    "2 Pair": 2.00,
    "Pair of Jacks or better": 1.00,
}
STAKE_PUBLISHED_RTP = 0.99      # §7: "Edge: 1.00%", "99% RTP"
STAKE_MAX_WIN = 800.0           # §6: header max win 800.00x

# Exact optimal-play ceiling on Stake's table — pinned as a reduced fraction
# (independently re-derived and cross-verified during the gauntlet).
STAKE_OPTIMAL_CEILING = Fraction(410892309848, 415275635775)  # 98.9445%

# references/woo/video_poker.md — full-pay 9/6 JoB, optimal strategy.
WOO_RTP_9_6 = 0.995439          # "more precisely 99.5439%"
WOO_SD_9_6 = 4.417542           # "standard deviation 4.42 ... 4.417542"

# references/woo/video_poker.md — Appendix-3 multihand SD per hand, JoB 9/6.
WOO_NPLAY_SD_9_6 = {1: 4.42, 3: 4.84, 5: 5.23, 10: 6.10, 50: 10.76, 100: 14.64}

# Wizard of Odds 9/6 Jacks-or-Better return-table Combinations column
# (denominator 19,933,230,517,200), royal flush down to nothing.  These
# integers are not in the captured .md (which publishes the derived return /
# SD figures); they were independently re-derived and digit-for-digit
# cross-verified against the Wizard's published table during the gauntlet,
# and are pinned here as the exact regression target for the solver's
# category sums.
WOO_COMBINATIONS_9_6 = {
    "royal_flush": 493_512_264,
    "straight_flush": 2_178_883_296,
    "four_of_a_kind": 47_093_167_764,
    "full_house": 229_475_482_596,
    "flush": 219_554_786_160,
    "straight": 223_837_565_784,
    "three_of_a_kind": 1_484_003_070_324,
    "two_pair": 2_576_946_164_148,
    "jacks_or_better": 4_277_372_890_968,
    "nothing": 10_872_274_993_896,
}
WOO_COMBINATIONS_TOTAL = 19_933_230_517_200

SIM_SERVER_SEED = "c0ffee" * 10 + "abcd"   # 64 hex chars, fixed for repro
SIM_CLIENT_SEED = "spinquest-video-poker-validation"

# Simulation acceptance thresholds.
Z_RTP_MAX = 3.0        # the build requirement: RTP within 3 SE
Z_CAT_MAX = 4.0        # hard bound per category (20 category tests total)
Z_CAT_WARN = 3.0       # flagged (printed, recorded) but not fatal
Z_M2_MAX = 4.0         # empirical second moment vs exact, exact-m4 SE


def check_paytable() -> dict:
    print("[table] engine paytable vs references/stake/video_poker.md §6")
    engine = {
        vp.CATEGORY_LABELS[name]: pays for name, pays in vp.STAKE_PAYTABLE.items()
    }
    mismatches = []
    for ref_name, ref_table in (
        ("description_table", STAKE_DESCRIPTION_TABLE),
        ("ingame_ladder", STAKE_INGAME_LADDER),
    ):
        for label, ref_pay in ref_table.items():
            got = engine.get(label)
            ok = got is not None and float(got) == float(ref_pay)
            if not ok:
                mismatches.append(
                    {"source": ref_name, "hand": label, "ref": ref_pay, "engine": got}
                )
        extra = set(engine) - set(ref_table)
        if extra:
            mismatches.append({"source": ref_name, "extra_engine_hands": sorted(extra)})
    for label, pay in sorted(engine.items(), key=lambda kv: kv[1]):
        ref = STAKE_DESCRIPTION_TABLE[label]
        print(f"[table]   {label:<26} engine {pay:>4}x  ref {ref:>4}x  "
              f"{'OK' if pay == ref else 'MISMATCH'}")
    max_win_ok = max(engine.values()) == STAKE_MAX_WIN
    print(f"[table]   max win {max(engine.values())}x vs published "
          f"{STAKE_MAX_WIN}x {'OK' if max_win_ok else 'MISMATCH'}")
    ok = not mismatches and max_win_ok
    print(f"[table] {'PASS' if ok else 'FAIL'} "
          f"({len(STAKE_DESCRIPTION_TABLE)} hands x 2 published copies)")
    return {
        "pass": ok,
        "n_hands": len(STAKE_DESCRIPTION_TABLE),
        "n_mismatches": len(mismatches),
        "mismatches": mismatches,
        "max_win_ok": max_win_ok,
    }


def solve_all(cache_dir: str | None) -> tuple[dict, dict, float]:
    """One shared full-cycle pass over the 8 WoO variants + Stake's table."""
    names = list(vp.WOO_VARIANT_PAYTABLES)
    tables = [vp.WOO_VARIANT_PAYTABLES[n] for n in names] + [vp.STAKE_PAYTABLE]
    print(f"[exact] full-cycle enumeration: 2,598,960 deals x 32 holds, exact "
          f"integer math, {len(tables)} paytables in ONE shared pass ...")
    t0 = time.perf_counter()
    sols = vp.solve_paytables(tables, cache_dir=cache_dir)
    dt = time.perf_counter() - t0
    print(f"[exact] solved in {dt:.1f}s")
    variants = dict(zip(names, sols[:-1]))
    return variants, {"stake": sols[-1]}, dt


def check_exact(variants: dict, stake_sol, solve_seconds: float) -> dict:
    bench = variants["9/6"]
    stake = stake_sol

    b_rtp, b_sd = float(bench.ev), bench.std
    s_rtp, s_sd = float(stake.ev), stake.std
    bench_rtp_ok = abs(b_rtp - WOO_RTP_9_6) < 1e-6
    bench_sd_ok = abs(b_sd - WOO_SD_9_6) < 1e-5

    # Stake's published "Edge: 1.00% / 99% RTP" vs the exact optimal ceiling.
    # 98.9445% is the CEILING (computer-perfect play); a 99% return is
    # therefore unattainable on this paytable under any strategy.  The page
    # title's integer-rounded "99% RTP" is consistent with the ceiling
    # (round(98.9445) == 99), but "Edge: 1.00%" overstates the best case by
    # 0.0555 percentage points.  PASS = our exact ceiling equals the pinned
    # cross-verified fraction AND sits strictly below the published figure.
    ceiling_ok = stake.ev == STAKE_OPTIMAL_CEILING
    below_published = s_rtp < STAKE_PUBLISHED_RTP
    rounding_ok = round(s_rtp * 100) == 99  # integer-precision title claim
    stake_ok = ceiling_ok and below_published and rounding_ok

    print(f"[exact] 9/6 benchmark: RTP {b_rtp:.7f} ({bench.ev}) vs WoO "
          f"{WOO_RTP_9_6} -> {'OK' if bench_rtp_ok else 'FAIL'}")
    print(f"[exact] 9/6 benchmark: SD  {b_sd:.6f} vs WoO {WOO_SD_9_6} "
          f"-> {'OK' if bench_sd_ok else 'FAIL'}")
    print(f"[exact] stake table:   optimal-play CEILING {s_rtp:.7%} "
          f"({stake.ev}), edge {1 - s_rtp:.4%}, SD {s_sd:.6f}")
    print(f"[exact]   pinned exact ceiling match: "
          f"{'OK' if ceiling_ok else 'FAIL'}")
    print(f"[exact]   published 'Edge: 1.00% / 99% RTP' is UNATTAINABLE: "
          f"best-case edge is {1 - s_rtp:.4%} "
          f"(+{(STAKE_PUBLISHED_RTP - s_rtp) * 100:.4f}pp above published); "
          f"only the integer-rounded '99% RTP' title is consistent "
          f"({'OK' if rounding_ok and below_published else 'FAIL'})")
    print("[exact] per-category exact probabilities (optimal play):")
    print(f"[exact]   {'hand':<26} {'pays 9/6':>8} {'P 9/6':>12} "
          f"{'pays stake':>10} {'P stake':>12}")
    for c in reversed(range(vp.N_CAT)):
        name = vp.CATEGORIES[c]
        print(f"[exact]   {vp.CATEGORY_LABELS[name]:<26} "
              f"{vp.BENCHMARK_9_6_PAYTABLE.get(name, 0):>8} "
              f"{float(bench.category_probs[c]):>12.8f} "
              f"{vp.STAKE_PAYTABLE.get(name, 0):>10} "
              f"{float(stake.category_probs[c]):>12.8f}")
    ok = bench_rtp_ok and bench_sd_ok and stake_ok
    print(f"[exact] {'PASS' if ok else 'FAIL'}")
    return {
        "pass": ok,
        "solve_seconds": solve_seconds,
        "benchmark_9_6": {
            "rtp": b_rtp,
            "rtp_exact": str(bench.ev),
            "sd": b_sd,
            "woo_rtp": WOO_RTP_9_6,
            "woo_sd": WOO_SD_9_6,
            "rtp_ok": bench_rtp_ok,
            "sd_ok": bench_sd_ok,
        },
        "stake": {
            "optimal_ceiling_rtp": s_rtp,
            "optimal_ceiling_exact": str(stake.ev),
            "optimal_ceiling_edge": 1 - s_rtp,
            "sd": s_sd,
            "published_rtp": STAKE_PUBLISHED_RTP,
            "published_edge_unattainable": below_published,
            "published_overstates_by_pp": (STAKE_PUBLISHED_RTP - s_rtp) * 100,
            "integer_rounding_consistent": rounding_ok,
            "pinned_ceiling_match": ceiling_ok,
        },
    }


def check_variants(variants: dict) -> dict:
    print("[variants] 8 WoO Jacks-or-Better pay-table variants, optimal-play "
          "return vs published (2dp):")
    rows = []
    failures = 0
    for name, sol in variants.items():
        pct = float(sol.ev) * 100
        published = vp.WOO_VARIANT_RETURNS_PCT[name]
        ok = round(pct, 2) == published
        failures += 0 if ok else 1
        rows.append({
            "variant": name,
            "rtp_pct": pct,
            "rtp_exact": str(sol.ev),
            "published_pct": published,
            "sd": sol.std,
            "pass": ok,
        })
        print(f"[variants]   {name:<20} return {pct:9.4f}%  published "
              f"{published:6.2f}%  SD {sol.std:.6f}  "
              f"{'OK' if ok else 'FAIL'}")
    ok = failures == 0
    print(f"[variants] {'PASS' if ok else 'FAIL'} "
          f"({len(rows) - failures}/{len(rows)} published returns reproduced)")
    return {"pass": ok, "n_variants": len(rows), "rows": rows}


def check_multihand(variants: dict) -> dict:
    """WoO Appendix 3: per-hand n-play SD = sqrt(v + (n-1)c) with c the exact
    shared-deal covariance from the solver's per-deal optimal-EV moments."""
    bench = variants["9/6"]
    v = float(bench.variance)
    c = float(bench.hold_ev_variance)
    print(f"[multihand] JoB 9/6: variance v = {v:.6f}, shared-deal "
          f"covariance c = Var(E[X|deal]) = {c:.6f} (exact "
          f"{bench.hold_ev_variance})")
    # Internal identity: mean of per-deal optimal EVs == aggregate return
    # (already asserted inside Solution; re-checked here explicitly).
    mean_identity = (
        Fraction(bench.hold_ev_sum_scaled, vp.COMBINATIONS_DENOMINATOR)
        == bench.ev
    )
    rows = []
    failures = 0
    for n, published in WOO_NPLAY_SD_9_6.items():
        sd = bench.n_play_std(n)
        ok = round(sd, 2) == published
        failures += 0 if ok else 1
        rows.append({"plays": n, "sd_per_hand": sd, "published": published,
                     "pass": ok})
        print(f"[multihand]   {n:>3} plays: SD/hand {sd:8.4f} vs Appendix-3 "
              f"{published:5.2f}  {'OK' if ok else 'FAIL'}")
    ok = failures == 0 and mean_identity and 0 < c < v
    print(f"[multihand]   per-deal EV mean == aggregate return (exact): "
          f"{'OK' if mean_identity else 'FAIL'}; 0 < c < v: "
          f"{'OK' if 0 < c < v else 'FAIL'}")
    print(f"[multihand] {'PASS' if ok else 'FAIL'} "
          f"({len(rows) - failures}/{len(rows)} Appendix-3 SDs reproduced)")
    return {"pass": ok, "covariance": c, "variance": v,
            "mean_identity_ok": mean_identity, "rows": rows}


def check_combinations(variants: dict) -> dict:
    """9/6 return table: pays | combinations | probability | return, with the
    exact Combinations column vs the Wizard's published integers."""
    game = vp.VideoPoker(vp.BENCHMARK_9_6_PAYTABLE)
    rows = game.return_table()
    print("[combos] 9/6 return table (denominator "
          f"{vp.COMBINATIONS_DENOMINATOR:,}):")
    print(f"[combos]   {'hand':<26} {'pays':>5} {'combinations':>18} "
          f"{'probability':>12} {'return':>10}")
    failures = []
    total_combos = 0
    total_return = Fraction(0)
    total_prob = Fraction(0)
    for row in rows:
        expected = WOO_COMBINATIONS_9_6[row["category"]]
        ok = row["combinations"] == expected
        if not ok:
            failures.append({"category": row["category"],
                             "engine": row["combinations"], "expected": expected})
        total_combos += row["combinations"]
        total_return += row["return_exact"]
        total_prob += row["probability_exact"]
        print(f"[combos]   {row['label']:<26} {row['pays']:>5} "
              f"{row['combinations']:>18,} {row['probability']:>12.8f} "
              f"{row['return']:>10.6f}  {'OK' if ok else 'FAIL'}")
    total_ok = total_combos == WOO_COMBINATIONS_TOTAL
    prob_ok = total_prob == 1
    return_ok = total_return == variants["9/6"].ev
    print(f"[combos]   total combinations {total_combos:,} vs "
          f"{WOO_COMBINATIONS_TOTAL:,} {'OK' if total_ok else 'FAIL'}; "
          f"probabilities sum to 1 {'OK' if prob_ok else 'FAIL'}; "
          f"return column sums to exact RTP {float(total_return):.7f} "
          f"{'OK' if return_ok else 'FAIL'}")
    ok = not failures and total_ok and prob_ok and return_ok
    print(f"[combos] {'PASS' if ok else 'FAIL'} "
          f"(10/10 Combinations integers digit-for-digit)" if ok else
          f"[combos] FAIL ({len(failures)} mismatches)")
    return {"pass": ok, "n_mismatches": len(failures), "mismatches": failures,
            "total_ok": total_ok, "prob_sum_ok": prob_ok,
            "return_sum_ok": return_ok}


def check_strategy(bench: "vp.Solution", stake: "vp.Solution",
                   n_deals: int = 8) -> dict:
    """Re-derive the optimal hold for seeded random deals by BRUTE FORCE
    (explicit enumeration of every replacement draw for all 32 holds via
    ``hold_ev_bruteforce`` — independent of the solver's U tables / Moebius
    transform) and require exact agreement with the precomputed table,
    including the tie-break to the lowest hold mask."""
    print(f"[strat] brute-force re-derivation of the optimal hold for "
          f"{n_deals} seeded random deals x 2 paytables (all 32 holds, "
          f"every replacement draw enumerated) ...")
    rnd = random.Random(20260824)
    failures = []
    n_checked = 0
    for sol, pt, name in (
        (bench, vp.BENCHMARK_9_6_PAYTABLE, "benchmark_9_6"),
        (stake, vp.STAKE_PAYTABLE, "stake"),
    ):
        for _ in range(n_deals):
            dealt = sorted(rnd.sample(range(52), 5))
            evs = [vp.hold_ev_bruteforce(dealt, m, pt) for m in range(32)]
            best_ev = max(evs)
            best_mask = min(m for m in range(32) if evs[m] == best_ev)
            rank = int(vp.hand_colex_rank(np.array(dealt))[0])
            table_mask = int(sol.pattern_table[rank])
            n_checked += 1
            deal_ok = table_mask == best_mask and evs[table_mask] == best_ev
            if not deal_ok:
                failures.append({
                    "paytable": name, "dealt": dealt,
                    "table_mask": table_mask, "bruteforce_mask": best_mask,
                    "table_ev": str(evs[table_mask]),
                    "bruteforce_ev": str(best_ev),
                })
            print(f"[strat]   {name:<14} deal "
                  f"{[sq_rng.card_name(c) for c in dealt]} -> hold mask "
                  f"{table_mask:05b} EV {float(evs[table_mask]):.6f} "
                  f"{'OK' if deal_ok else 'FAIL'}")
    ok = not failures
    print(f"[strat] {'PASS' if ok else 'FAIL'} "
          f"({n_checked} deals, table == independent brute force)")
    return {"pass": ok, "n_checked": n_checked, "failures": failures}


def check_cross_verification(n_rounds: int = 64) -> dict:
    """Replay a block of vectorized simulator rounds nonce-by-nonce through
    the scalar provably-fair path: each row must produce the same deck, the
    same held-card set, the same final-hand category and the same payout.
    The scalar path generates the full 52-card deck (7 digests) exactly as
    documented; the vectorized path generates only the 10 floats that can
    influence a payout (2 digests) — equality here proves the trimmed
    stream is bit-identical where it matters."""
    print(f"[xcheck] scalar (52-float deck) vs vectorized (10-float fast "
          f"path): {n_rounds} rounds replayed nonce-by-nonce ...")
    game = vp.VideoPoker()
    nonce_start = 5_000
    bulk = BulkRng(server_seed=SIM_SERVER_SEED, client_seed=SIM_CLIENT_SEED,
                   nonce_start=nonce_start)
    sim = game.simulate(n_rounds, bulk=bulk, progress=False)
    scalar_pay = 0.0
    scalar_cats = {name: 0 for name in vp.CATEGORIES}
    for nonce in range(nonce_start, nonce_start + n_rounds):
        r = game.play_round(SIM_SERVER_SEED, SIM_CLIENT_SEED, nonce)
        scalar_pay += r["payout"]
        scalar_cats[r["category"]] += 1
        # deck integrity: dealt = first 5 events of the committed permutation
        deck = sq_rng.video_poker_deck(SIM_SERVER_SEED, SIM_CLIENT_SEED, nonce)
        assert r["dealt"] == deck[:5]
    pay_ok = abs(sim["rtp"] * n_rounds - scalar_pay) < 1e-9
    cats_ok = sim["category_counts"] == scalar_cats
    range_ok = tuple(sim["verification"]["nonce_range"]) == (
        nonce_start, nonce_start + n_rounds)
    ok = pay_ok and cats_ok and range_ok
    print(f"[xcheck]  total payout vectorized {sim['rtp'] * n_rounds:.6f} vs "
          f"scalar {scalar_pay:.6f} {'OK' if pay_ok else 'FAIL'}")
    print(f"[xcheck]  category counts identical: "
          f"{'OK' if cats_ok else 'FAIL'}; nonce range "
          f"{'OK' if range_ok else 'FAIL'}")
    print(f"[xcheck] {'PASS' if ok else 'FAIL'}")
    return {"pass": ok, "n_rounds": n_rounds, "payout_match": pay_ok,
            "category_counts_match": cats_ok, "nonce_range_ok": range_ok}


def run_sim(name: str, paytable: dict, rounds: int, nonce_start: int) -> dict:
    game = vp.VideoPoker(paytable)
    bulk = BulkRng(
        server_seed=SIM_SERVER_SEED,
        client_seed=SIM_CLIENT_SEED,
        nonce_start=nonce_start,
    )
    print(f"[sim]   {name}: {rounds:,} provably-fair rounds "
          f"(optimal-hold table, nonce_start={nonce_start}) ...")
    res = game.simulate(rounds, bulk=bulk, progress=True)
    sol = game.solution

    rtp_ok = abs(res["z_score"]) <= Z_RTP_MAX
    print(f"[sim]   {name}: empirical RTP {res['rtp']:.6f} vs exact "
          f"{res['analytic_rtp']:.6f}  (z = {res['z_score']:+.3f}, "
          f"3 SE band +-{3 * res['se_rtp']:.6f}) "
          f"{'OK' if rtp_ok else 'FAIL'}")

    # Empirical second moment vs exact, with the EXACT standard error
    # SE = sqrt((m4 - m2^2)/n) from the analytic 4th moment — this is the
    # proper acceptance test for the empirical SD (royal-flush noise
    # dominates m4, so a naive SD band would be meaningless).
    m2_exact = float(sol.ev2)
    m4_exact = float(sum(
        p * pay ** 4 for p, pay in zip(sol.category_probs, sol.paytable_key)
    ))
    m2_emp = res["std_per_unit"] ** 2 + res["rtp"] ** 2  # == pay_sq_sum / n
    se_m2 = math.sqrt((m4_exact - m2_exact ** 2) / rounds)
    z_m2 = (m2_emp - m2_exact) / se_m2
    m2_ok = abs(z_m2) <= Z_M2_MAX
    print(f"[sim]   {name}: empirical SD {res['std_per_unit']:.4f} vs exact "
          f"{res['analytic_std_per_unit']:.4f} — second-moment z = "
          f"{z_m2:+.3f} (exact-m4 SE {se_m2:.4f}) "
          f"{'OK' if m2_ok else 'FAIL'}; "
          f"{res['rounds_per_sec']:,.0f} rounds/s, {res['elapsed_s']:.1f}s")

    cat_z = {}
    cat_flagged = []
    cat_worst = 0.0
    for c, cname in enumerate(vp.CATEGORIES):
        p = float(sol.category_probs[c])
        obs = res["category_counts"][cname]
        se = math.sqrt(p * (1 - p) * rounds)
        z = (obs - p * rounds) / se if se > 0 else 0.0
        cat_z[cname] = z
        cat_worst = max(cat_worst, abs(z))
        flag = ""
        if abs(z) > Z_CAT_MAX:
            flag = "  FAIL(|z|>4)"
        elif abs(z) > Z_CAT_WARN:
            flag = "  FLAGGED(|z|>3)"
            cat_flagged.append(cname)
        print(f"[sim]     {vp.CATEGORY_LABELS[cname]:<26} obs {obs:>9,} "
              f"exp {p * rounds:>12,.1f}  z {z:+.2f}{flag}")
    cat_ok = cat_worst <= Z_CAT_MAX
    run_pass = rtp_ok and m2_ok and cat_ok
    print(f"[sim]   {name}: {'PASS' if run_pass else 'FAIL'} "
          f"(RTP z {'OK' if rtp_ok else 'FAIL'}, second-moment z "
          f"{'OK' if m2_ok else 'FAIL'}, worst category |z| = {cat_worst:.2f} "
          f"{'OK' if cat_ok else 'FAIL'}"
          f"{', flagged: ' + ','.join(cat_flagged) if cat_flagged else ''})")
    return {
        "name": name,
        "n_rounds": rounds,
        "rtp": res["rtp"],
        "analytic_rtp": res["analytic_rtp"],
        "z_score": res["z_score"],
        "se_rtp": res["se_rtp"],
        "within_3se": rtp_ok,
        "std_per_unit": res["std_per_unit"],
        "analytic_std_per_unit": res["analytic_std_per_unit"],
        "second_moment_z": z_m2,
        "second_moment_ok": m2_ok,
        "rounds_per_sec": res["rounds_per_sec"],
        "elapsed_s": res["elapsed_s"],
        "category_counts": res["category_counts"],
        "category_z": cat_z,
        "category_worst_abs_z": cat_worst,
        "category_flagged_over_3": cat_flagged,
        "category_ok": cat_ok,
        "pass": run_pass,
        "verification": res["verification"],
    }


def _emit(summary: dict) -> int:
    """The one exit path: machine-readable JSON + OVERALL line, exit code."""
    overall = bool(summary.get("overall_pass", False))
    print("VIDEO_POKER_VALIDATION_JSON: " + json.dumps(summary, default=float))
    print(f"OVERALL: {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 1


def main() -> int:
    try:
        sys.stdout.reconfigure(line_buffering=True)  # progress visible if piped
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rounds", type=int, default=10_000_000,
                    help="simulated rounds per paytable (default 10M)")
    ap.add_argument("--skip-sim", action="store_true")
    ap.add_argument("--cache-dir", default=None,
                    help="optional dir for cached exact solutions (.npz)")
    args = ap.parse_args()

    summary: dict = {"game": "video_poker", "overall_pass": False}
    try:
        table = check_paytable()
        variants, stake_d, solve_dt = solve_all(args.cache_dir)
        stake_sol = stake_d["stake"]
        exact = check_exact(variants, stake_sol, solve_dt)
        var_stage = check_variants(variants)
        multihand = check_multihand(variants)
        combos = check_combinations(variants)
        strat = check_strategy(variants["9/6"], stake_sol)
        xcheck = check_cross_verification()

        if args.skip_sim:
            sim = {"runs": [], "pass": True, "skipped": True,
                   "rounds_requirement_met": False}
            print("[sim]   skipped (--skip-sim) — NOT a full validation run")
        else:
            runs = [
                run_sim("stake_800_60_22", vp.STAKE_PAYTABLE, args.rounds, 0),
                run_sim("benchmark_9_6", vp.BENCHMARK_9_6_PAYTABLE,
                        args.rounds, args.rounds),
            ]
            counts_ok = all(
                sum(r["category_counts"].values()) == r["n_rounds"]
                for r in runs
            )
            rounds_met = args.rounds >= 10_000_000
            if not rounds_met:
                print(f"[sim]   WARNING: --rounds {args.rounds:,} is below "
                      f"the 10M requirement for a full validation run")
            sim = {
                "runs": runs,
                "pass": all(r["pass"] for r in runs) and counts_ok,
                "category_counts_sum_ok": counts_ok,
                "rounds_requirement_met": rounds_met,
            }
            print(f"[sim]   {'PASS' if sim['pass'] else 'FAIL'} "
                  f"(both campaigns: RTP within 3 SE, all categories within "
                  f"4 SE, second moment within 4 SE)")

        overall = bool(
            table["pass"] and exact["pass"] and var_stage["pass"]
            and multihand["pass"] and combos["pass"] and strat["pass"]
            and xcheck["pass"] and sim["pass"]
        )
        summary = {
            "game": "video_poker",
            "overall_pass": overall,
            "stake_table": {k: v for k, v in table.items() if k != "mismatches"},
            "exact_analysis": exact,
            "woo_variants": var_stage,
            "multihand_appendix3": multihand,
            "combinations_column": combos,
            "strategy_spotchecks": strat,
            "scalar_vector_crosscheck": xcheck,
            "empirical": sim,
            "sim_seeds": {
                "server_seed": SIM_SERVER_SEED,
                "client_seed": SIM_CLIENT_SEED,
            },
        }
    except BaseException as exc:  # verdict must ALWAYS be emitted
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            summary["error"] = f"interrupted: {exc!r}"
        else:
            summary["error"] = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
        summary["overall_pass"] = False
        return _emit(summary)
    return _emit(summary)


if __name__ == "__main__":
    raise SystemExit(main())
