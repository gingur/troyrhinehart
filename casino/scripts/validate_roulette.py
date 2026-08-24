#!/usr/bin/env python3
"""Validate the Roulette engine against the published references.

1. Payout-for-payout comparison against Stake's published table
   (references/stake/roulette.md, section 5): the reference markdown table is
   PARSED and every row's odds, total-return multiplier, coverage and win
   probability are compared against the engine.  The red/black color lists
   are parsed and compared verbatim, and the pocket mapping
   floor(float * 37) is spot-verified scalar-vs-bulk.

2. Wizard-of-Odds SD cross-check (references/woo/roulette.md): the derived
   single-zero per-unit SD table is parsed and compared to the engine's
   analytic SDs.  WoO's stated formula sqrt(E[X^2] - EV^2) is recomputed
   exactly (even money sqrt(1 - (1/37)^2) = 0.9996347, single number
   sqrt((35^2+36)/37 - (1/37)^2) = 5.8378379).  The reference file prints
   the latter as "5.837800" (5.8378 zero-padded), so printed figures are
   compared to 4 decimals and the formula to 1e-12.

3. Analytic gate: every one of the 154 legal bets has exact RTP 36/37
   (97.2973%, house edge 2.7027% ~ published 2.70%).

4. Empirical gate: 10M+ provably-fair spins on the vectorized BulkRng
   stream (deterministic default seed, one nonce per spin, every spin
   verifiable against the scalar path).  All 154 bets are settled against
   the same spin sequence; EVERY bet's empirical RTP must land within 3 SE
   of 97.30% (SE = analytic per-bet SD / sqrt(N)).

Prints a human-readable report plus a machine-readable JSON line prefixed
``ROULETTE_VALIDATION_JSON:``.  Exit code 0 iff every gate passes.

Usage:
    python scripts/validate_roulette.py [--rounds N] [--seed HEX64]
                                        [--client SEED] [--skip-sim]
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from fractions import Fraction
from pathlib import Path
from typing import Dict, List

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from spinquest_sim import rng as sq_rng                      # noqa: E402
from spinquest_sim.games import roulette as rl               # noqa: E402
from spinquest_sim.games.roulette import Roulette            # noqa: E402
from spinquest_sim.rng import BulkRng                        # noqa: E402

STAKE_MD = _ROOT / "references" / "stake" / "roulette.md"
WOO_MD = _ROOT / "references" / "woo" / "roulette.md"

# Deterministic default campaign seed (any 64-hex server seed works; this one
# is fixed so the reference validation run is exactly reproducible).
DEFAULT_SERVER_SEED = (
    "5f70b1435a4b8e2f6d3c0a9184e7d2c5b8a1f4e7d0c3b6a9582e1f4c7d0a3b69"
)
DEFAULT_CLIENT_SEED = "spinquest-roulette-validation"

# Stake table row label -> engine bet types it covers.
_STAKE_ROW_MAP = {
    "Straight up": ["straight"],
    "Split": ["split"],
    "Street": ["street"],
    "Corner": ["corner"],
    "Line (six line)": ["line"],
    "Dozen": ["dozen"],
    "Column": ["column"],
    "Red / Black": ["red", "black"],
    "Odd / Even": ["odd", "even"],
    "High / Low": ["high", "low"],
}


def parse_stake_reference() -> Dict[str, Dict[str, object]]:
    """Parse section-5 payout table and the color lists from the Stake md."""
    text = STAKE_MD.read_text()
    rows: Dict[str, Dict[str, object]] = {}
    row_re = re.compile(
        r"^\|\s*([^|]+?)\s*\|\s*(\d+)\s*\|\s*(\d+):1\s*\|\s*(\d+)x\s*\|"
        r"\s*(\d+)/37\s*\|",
        re.M,
    )
    for label, cov, odds, mult, num in row_re.findall(text):
        for key, types in _STAKE_ROW_MAP.items():
            if label.startswith(key):
                rows[key] = {
                    "bet_types": types,
                    "coverage": int(cov),
                    "odds": int(odds),
                    "multiplier": int(mult),
                    "win_prob": Fraction(int(num), 37),
                }
                break
    reds = re.search(r"^- Red: ([\d, ]+)$", text, re.M)
    blacks = re.search(r"^- Black: ([\d, ]+)$", text, re.M)
    he = re.search(r"house edge \*\*(\d+\.\d+)%\*\*, RTP \*\*(\d+\.\d+)%\*\*", text)
    assert reds and blacks and he, "failed to parse Stake reference"
    return {
        "rows": rows,
        "red": {int(x) for x in reds.group(1).split(",")},
        "black": {int(x) for x in blacks.group(1).split(",")},
        "house_edge_pct": float(he.group(1)),
        "rtp_pct": float(he.group(2)),
    }


def parse_woo_reference() -> Dict[str, float]:
    """Parse the derived single-zero SD table from the WoO md."""
    text = WOO_MD.read_text()
    section = text.split("Bet (single-zero)")[1]
    even = re.search(r"Any even-money bet \| ([\d.]+)", section)
    single = re.search(r"Single number \| ([\d.]+)", section)
    assert even and single, "failed to parse WoO reference"
    return {"even_money": float(even.group(1)), "straight": float(single.group(1))}


def check(passed: bool, label: str, detail: str, failures: List[str]) -> None:
    print(f"  [{'PASS' if passed else 'FAIL'}] {label}: {detail}")
    if not passed:
        failures.append(f"{label}: {detail}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rounds", type=int, default=10_000_000,
                    help="empirical spins (default 10M)")
    ap.add_argument("--seed", default=DEFAULT_SERVER_SEED,
                    help="server seed (64-char hex)")
    ap.add_argument("--client", default=DEFAULT_CLIENT_SEED, help="client seed")
    ap.add_argument("--skip-sim", action="store_true",
                    help="skip the empirical 10M-spin gate")
    args = ap.parse_args()

    failures: List[str] = []
    summary: Dict[str, object] = {"game": "roulette", "gates": {}}

    # ------------------------------------------------------------------
    print("=" * 72)
    print("GATE 1 — payout-for-payout vs references/stake/roulette.md")
    print("=" * 72)
    stake = parse_stake_reference()
    table = rl.full_payout_table()
    n_rows = 0
    for label, ref in stake["rows"].items():
        for bet_type in ref["bet_types"]:
            row = table[bet_type]
            ok = (
                row["payout_odds"] == f"{ref['odds']}:1"
                and row["multiplier"] == ref["multiplier"]
                and row["coverage"] == ref["coverage"]
                and Fraction(row["coverage"], 37) == ref["win_prob"]
            )
            check(
                ok, f"{label} -> {bet_type}",
                f"odds {row['payout_odds']} mult {row['multiplier']}x "
                f"cov {row['coverage']} p {row['coverage']}/37 "
                f"(ref {ref['odds']}:1 {ref['multiplier']}x {ref['coverage']} "
                f"{ref['win_prob']})",
                failures,
            )
            n_rows += 1
    check(
        n_rows == len(rl.BET_TYPES) and set(stake["rows"]) == set(_STAKE_ROW_MAP),
        "row coverage",
        f"{n_rows} bet types matched against {len(stake['rows'])} reference rows",
        failures,
    )
    check(
        stake["red"] == set(rl.RED_NUMBERS)
        and stake["black"] == set(rl.BLACK_NUMBERS),
        "wheel colors",
        f"red {sorted(stake['red']) == sorted(rl.RED_NUMBERS)} "
        f"black {sorted(stake['black']) == sorted(rl.BLACK_NUMBERS)} (verbatim)",
        failures,
    )
    max_payout_diff = max(
        abs(table[t]["multiplier"] - (ref["odds"] + 1))
        for ref in stake["rows"].values()
        for t in ref["bet_types"]
    )
    summary["gates"]["stake_payout_table"] = not failures
    summary["max_payout_diff"] = max_payout_diff

    # ------------------------------------------------------------------
    print("=" * 72)
    print("GATE 2 — analytic RTP/edge, all 154 legal bets")
    print("=" * 72)
    prior = len(failures)
    bets = [(bt, sel, Roulette(bt, sel)) for bt, sel in rl.all_bets()]
    bad = [
        (bt, sel) for bt, sel, e in bets
        if e.rtp_exact != Fraction(36, 37)
        or e.multiplier_exact != Fraction(36, e.coverage)
    ]
    check(
        len(bets) == 154 and not bad, "exact RTP",
        f"{len(bets)} bets, all RTP = 36/37 = {float(Fraction(36, 37)):.6%}, "
        f"house edge {1 / 37:.6%} (published {stake['house_edge_pct']}% / "
        f"{stake['rtp_pct']}%)",
        failures,
    )
    check(
        round(100 / 37, 2) == stake["house_edge_pct"]
        and round(3600 / 37, 2) == stake["rtp_pct"],
        "published rounding",
        f"1/37 -> {100 / 37:.4f}% rounds to {stake['house_edge_pct']}%",
        failures,
    )
    summary["gates"]["analytic_rtp"] = len(failures) == prior
    summary["analytic_rtp"] = 36 / 37
    summary["analytic_house_edge"] = 1 / 37

    # ------------------------------------------------------------------
    print("=" * 72)
    print("GATE 3 — per-bet SD vs references/woo/roulette.md")
    print("=" * 72)
    prior = len(failures)
    woo = parse_woo_reference()
    even_sd = Roulette("red").std_per_unit
    straight_sd = Roulette("straight", 17).std_per_unit
    exact_even = math.sqrt(1 - (1 / 37) ** 2)
    exact_straight = math.sqrt((35**2 + 36) / 37 - (1 / 37) ** 2)
    check(
        abs(even_sd - exact_even) < 1e-12
        and abs(straight_sd - exact_straight) < 1e-12,
        "WoO formula sqrt(E[X^2]-EV^2)",
        f"even {even_sd:.7f} (exact {exact_even:.7f}), "
        f"straight {straight_sd:.7f} (exact {exact_straight:.7f})",
        failures,
    )
    check(
        round(even_sd, 6) == woo["even_money"]
        and round(straight_sd, 4) == round(woo["straight"], 4),
        "WoO printed figures",
        f"even {even_sd:.6f} vs ref {woo['even_money']}; straight "
        f"{straight_sd:.4f} vs ref {woo['straight']} (ref prints 5.8378 "
        "zero-padded; exact is 5.8378379)",
        failures,
    )
    sd_table = {t: table[t]["std_per_unit"] for t in rl.BET_TYPES}
    print("  per-type SD/unit:", {t: round(s, 4) for t, s in sd_table.items()})
    summary["gates"]["woo_sd"] = len(failures) == prior
    summary["sd_even_money"] = even_sd
    summary["sd_straight"] = straight_sd
    summary["sd_by_type"] = sd_table

    # ------------------------------------------------------------------
    print("=" * 72)
    print("GATE 4 — scalar vs vectorized provably-fair stream")
    print("=" * 72)
    prior = len(failures)
    spot = BulkRng(args.seed, args.client, nonce_start=0, workers=1)
    bulk_pockets = spot.roulette_pockets(250)
    mismatch = sum(
        1 for i in range(250)
        if bulk_pockets[i] != sq_rng.roulette_pocket(
            sq_rng.generate_floats(args.seed, args.client, i, 0, 1)[0]
        )
    )
    check(
        mismatch == 0, "bulk == scalar",
        f"250/250 pockets bit-identical (nonces 0..249, cursor 0, "
        f"floor(float*37))",
        failures,
    )
    summary["gates"]["stream_agreement"] = len(failures) == prior

    # ------------------------------------------------------------------
    if not args.skip_sim:
        print("=" * 72)
        print(f"GATE 5 — empirical: {args.rounds:,} provably-fair spins, "
              "all 154 bets within 3 SE of 97.30%")
        print("=" * 72)
        prior = len(failures)
        rng = BulkRng(args.seed, args.client, nonce_start=0)
        print(f"  server_seed_hash: {rng.server_seed_hash}")
        print(f"  client_seed: {rng.client_seed}  nonce range: "
              f"[0, {args.rounds})")
        counts = np.zeros(rl.POCKETS, dtype=np.int64)
        chunk = 2_000_000
        done = 0
        t0 = time.perf_counter()
        while done < args.rounds:
            step = min(chunk, args.rounds - done)
            counts += np.bincount(
                rng.roulette_pockets(step), minlength=rl.POCKETS
            )
            done += step
            rate = done / (time.perf_counter() - t0)
            print(f"  {done:,}/{args.rounds:,} spins ({rate:,.0f}/s)",
                  flush=True)
        elapsed = time.perf_counter() - t0
        n = args.rounds
        assert int(counts.sum()) == n

        worst = {"z": 0.0, "bet": None, "rtp": None}
        n_fail = 0
        per_type: Dict[str, Dict[str, float]] = {}
        for bt, sel, eng in bets:
            cov_hits = int(counts[sorted(eng.covered)].sum())
            rtp_emp = cov_hits / n * eng.multiplier
            se = eng.std_per_unit / math.sqrt(n)
            z = (rtp_emp - eng.rtp) / se
            if abs(z) > 3.0:
                n_fail += 1
                print(f"  [FAIL] {bt} {sel}: RTP {rtp_emp:.6%} z={z:+.2f}")
            if abs(z) > abs(worst["z"]):
                worst = {"z": z, "bet": f"{bt} {sel}", "rtp": rtp_emp}
            info = per_type.setdefault(
                bt, {"n_bets": 0, "max_abs_z": 0.0, "rtp_sum": 0.0}
            )
            info["n_bets"] += 1
            info["max_abs_z"] = max(info["max_abs_z"], abs(z))
            info["rtp_sum"] += rtp_emp

        print(f"  {'type':10s} {'bets':>4s} {'mean RTP':>10s} {'max|z|':>7s} "
              f"{'SE(RTP)':>9s}")
        for bt in rl.BET_TYPES:
            info = per_type[bt]
            se = Roulette(*rl._CANONICAL[bt]).std_per_unit / math.sqrt(n)
            print(f"  {bt:10s} {info['n_bets']:>4d} "
                  f"{info['rtp_sum'] / info['n_bets']:>10.5%} "
                  f"{info['max_abs_z']:>7.2f} {se:>9.6f}")
        zero_freq = counts[0] / n
        print(f"  pocket-0 frequency: {zero_freq:.6f} (expect {1 / 37:.6f}); "
              f"throughput {n / elapsed:,.0f} spins/s, {elapsed:.1f}s")
        check(
            n_fail == 0, "empirical 3-SE",
            f"154/154 bets within 3 SE over {n:,} spins; worst "
            f"{worst['bet']} z={worst['z']:+.2f} RTP {worst['rtp']:.5%}",
            failures,
        )
        chi2 = float(((counts - n / 37) ** 2 / (n / 37)).sum())
        check(
            chi2 < 79.0, "uniformity chi-square",   # 99.99% quantile, 36 dof
            f"chi2(36 dof) = {chi2:.1f}",
            failures,
        )
        summary["gates"]["empirical_3se"] = len(failures) == prior
        summary["empirical"] = {
            "rounds": n,
            "worst_bet": worst["bet"],
            "worst_z": worst["z"],
            "worst_rtp": worst["rtp"],
            "n_outside_3se": n_fail,
            "chi2_36dof": chi2,
            "pocket0_freq": zero_freq,
            "rounds_per_sec": n / elapsed,
            "server_seed_hash": rng.server_seed_hash,
            "client_seed": rng.client_seed,
            "per_type_max_abs_z": {
                bt: per_type[bt]["max_abs_z"] for bt in rl.BET_TYPES
            },
        }

    # ------------------------------------------------------------------
    ok = not failures
    summary["passed"] = ok
    summary["failures"] = failures
    print("=" * 72)
    print(f"OVERALL: {'PASS' if ok else 'FAIL'} "
          f"({len(failures)} failure(s))")
    print("ROULETTE_VALIDATION_JSON:" + json.dumps(summary, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
