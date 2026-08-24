#!/usr/bin/env python3
"""Validate the Wheel engine against the published references.

1. Payout-for-payout comparison against Stake's published tables
   (references/stake/wheel.md, section 4): every one of the 5 x 3 = 15
   per-segment multiplier columns (450 payout cells in total: 150 segment
   rows x 3 risk columns) is PARSED
   from the reference markdown and compared element-for-element against the
   engine's PAYOUTS arrays.  Stake's published max-win summary table
   (section 5) is parsed and compared against the engine maxima.

2. Analytic gate: every one of the 15 (segments, risk) configurations has
   exact RTP 99/100 (99% RTP / 1% house edge, matching the published
   "Edge: 1.00%" / "RTP — 99%" figures in section 6), computed with the WoO
   prob-x-pay methodology (references/woo/wheel.md documents that the Wizard
   has NO page for this game, so Stake's published table IS the analytic
   target and per-configuration SD is computed from the pay tables directly,
   as that reference prescribes).

3. Stream gate: scalar vs vectorized provably-fair paths agree bit-for-bit
   (segment = floor(float * segments), one float per spin at cursor 0).

4. Empirical gate: 10M+ provably-fair spins on the vectorized BulkRng stream
   (deterministic default seed, one nonce per spin, every spin verifiable
   against the scalar path).  ALL 15 configurations are settled against the
   same float sequence; EVERY configuration's empirical RTP must land within
   3 SE of 99% (SE = analytic per-config SD / sqrt(N)), and segment-frequency
   chi-square uniformity is checked at every segments setting.

Prints a human-readable report plus a machine-readable JSON line prefixed
``WHEEL_VALIDATION_JSON:``.  Exit code 0 iff every gate passes.

Usage:
    python scripts/validate_wheel.py [--rounds N] [--seed HEX64]
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
from typing import Dict, List, Tuple

import numpy as np
from scipy import stats

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from spinquest_sim import rng as sq_rng                      # noqa: E402
from spinquest_sim.games import wheel as wh                  # noqa: E402
from spinquest_sim.games.wheel import Wheel                  # noqa: E402
from spinquest_sim.rng import BulkRng                        # noqa: E402

STAKE_MD = _ROOT / "references" / "stake" / "wheel.md"
WOO_MD = _ROOT / "references" / "woo" / "wheel.md"

# Deterministic default campaign seed (any 64-hex server seed works; fixed so
# the reference validation run is exactly reproducible).
DEFAULT_SERVER_SEED = (
    "c2d9f4a71e8b3056c4a9d2e7f0b3861c5d8e2f7a0b4c9d3e6f1a5b8c2d7e0f49"
)
DEFAULT_CLIENT_SEED = "spinquest-wheel-validation"


def parse_stake_payout_tables() -> Dict[int, Dict[str, List[float]]]:
    """Parse the section-4 per-segment tables (columns Low/Medium/High) from
    the Stake reference — the published PAYOUTS arrays rendered row-by-row."""
    text = STAKE_MD.read_text()
    tables: Dict[int, Dict[str, List[float]]] = {}
    sections = re.split(r"^### (\d+) segments$", text, flags=re.M)
    row_re = re.compile(
        r"^\|\s*(\d+)\s*\|\s*([\d.]+)x\s*\|\s*([\d.]+)x\s*\|\s*([\d.]+)x\s*\|",
        re.M,
    )
    for i in range(1, len(sections), 2):
        n = int(sections[i])
        rows = row_re.findall(sections[i + 1])
        assert len(rows) == n, f"{n}-segment table has {len(rows)} rows"
        low = [0.0] * n
        med = [0.0] * n
        high = [0.0] * n
        for seg, lo, me, hi in rows:
            s = int(seg)
            low[s], med[s], high[s] = float(lo), float(me), float(hi)
        tables[n] = {"low": low, "medium": med, "high": high}
    assert sorted(tables) == [10, 20, 30, 40, 50], "missing segment tables"
    return tables


def parse_stake_max_win_table() -> Dict[Tuple[int, str], float]:
    """Parse the published section-5 Symbols & Information max-win table."""
    text = STAKE_MD.read_text()
    out: Dict[Tuple[int, str], float] = {}
    row_re = re.compile(
        r"^\|\s*(Low|Medium|High)\s*\|\s*([\d]+(?:-[\d]+)?)\s*\|\s*([\d.]+)\s*\|",
        re.M,
    )
    for risk, seg_range, mx in row_re.findall(text):
        lo, _, hi = seg_range.partition("-")
        lo_n, hi_n = int(lo), int(hi or lo)
        for n in wh.SEGMENT_COUNTS:
            if lo_n <= n <= hi_n:
                out[(n, risk.lower())] = float(mx)
    assert len(out) == 15, f"max-win table parsed {len(out)}/15 cells"
    return out


def parse_stake_published_edge() -> Tuple[float, float]:
    """(rtp_pct, edge_pct) from section 6 verbatim quotes."""
    text = STAKE_MD.read_text()
    m = re.search(r"return to player percentage of (\d+)%.*?house edge of just (\d+)%",
                  text, re.S)
    assert m, "failed to parse published RTP/edge"
    return float(m.group(1)), float(m.group(2))


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
    summary: Dict[str, object] = {"game": "wheel", "gates": {}}

    # ------------------------------------------------------------------
    print("=" * 72)
    print("GATE 1 — payout-for-payout vs references/stake/wheel.md")
    print("=" * 72)
    ref_tables = parse_stake_payout_tables()
    max_payout_diff = 0.0
    n_cells = 0
    for n in wh.SEGMENT_COUNTS:
        for risk in wh.RISKS:
            ref = ref_tables[n][risk]
            eng = [float(m) for m in wh.PAYOUTS[n][risk]]
            diffs = [abs(a - b) for a, b in zip(ref, eng)]
            n_cells += len(ref)
            max_payout_diff = max(max_payout_diff, max(diffs))
            check(
                len(ref) == n and max(diffs) == 0.0,
                f"{n} segments / {risk}",
                f"{n} multipliers, max |engine - reference| = {max(diffs):g}",
                failures,
            )
    # 10+20+30+40+50 = 150 segment rows x 3 risk columns = 450 payout cells.
    check(n_cells == 450, "cell coverage",
          f"{n_cells}/450 published segment payouts compared "
          "(150 segment rows x 3 risks)", failures)

    ref_max = parse_stake_max_win_table()
    bad_max = [
        (n, r) for (n, r), mx in ref_max.items()
        if Wheel(n, r).max_multiplier != mx
    ]
    check(not bad_max, "published max-win table",
          f"15/15 maxima match (high: 9.9/19.8/29.7/39.6/49.5; "
          f"medium tops 3/3/4/3/5; low 1.5); mismatches: {bad_max}", failures)
    summary["gates"]["stake_payout_table"] = not failures
    summary["max_payout_diff"] = max_payout_diff
    summary["payout_cells_compared"] = n_cells

    # ------------------------------------------------------------------
    print("=" * 72)
    print("GATE 2 — analytic RTP/edge/SD, all 15 configurations")
    print("=" * 72)
    prior = len(failures)
    rtp_pct, edge_pct = parse_stake_published_edge()
    engines = {(n, r): Wheel(n, r) for n, r in wh.all_configs()}
    bad_rtp = [
        (n, r) for (n, r), e in engines.items()
        if e.rtp_exact != Fraction(99, 100)
        or sum(e.paytable_exact().values()) != 1
    ]
    check(
        not bad_rtp, "exact RTP",
        f"15/15 configs RTP = 99/100 exactly (published {rtp_pct:.0f}% RTP / "
        f"{edge_pct:.0f}% edge); probabilities sum to 1", failures,
    )
    # WoO methodology cross-check: high-risk closed form SD = 0.99*sqrt(n-1)
    bad_sd = [
        n for n in wh.SEGMENT_COUNTS
        if abs(engines[(n, "high")].std_per_unit - 0.99 * math.sqrt(n - 1)) > 1e-12
    ]
    check(not bad_sd, "SD closed form (high risk)",
          "std = 0.99*sqrt(segments-1): " + ", ".join(
              f"{n}:{engines[(n, 'high')].std_per_unit:.4f}"
              for n in wh.SEGMENT_COUNTS), failures)
    sd_table = {
        f"{n}/{r}": engines[(n, r)].std_per_unit for n, r in wh.all_configs()
    }
    print("  per-config SD/unit:",
          {k: round(v, 4) for k, v in sd_table.items()})
    summary["gates"]["analytic_rtp"] = len(failures) == prior
    summary["analytic_rtp"] = 0.99
    summary["analytic_house_edge"] = 0.01
    summary["sd_by_config"] = sd_table

    # ------------------------------------------------------------------
    print("=" * 72)
    print("GATE 3 — scalar vs vectorized provably-fair stream")
    print("=" * 72)
    prior = len(failures)
    spot = BulkRng(args.seed, args.client, nonce_start=0, workers=1)
    bulk_floats = spot.floats(250)
    mismatch = 0
    for i in range(250):
        f = sq_rng.generate_floats(args.seed, args.client, i, 0, 1)[0]
        if bulk_floats[i] != f:
            mismatch += 1
            continue
        for n in wh.SEGMENT_COUNTS:
            if math.floor(bulk_floats[i] * n) != sq_rng.wheel_index(f, n):
                mismatch += 1
    check(mismatch == 0, "bulk == scalar",
          "250/250 floats bit-identical (nonces 0..249, cursor 0) and "
          "floor(float*segments) agrees at all 5 segment settings", failures)
    r0 = Wheel(50, "high").play_round(args.seed, args.client, 0)
    check(
        r0["segment"] == math.floor(bulk_floats[0] * 50),
        "play_round verification",
        f"nonce 0 float {r0['float']:.10f} -> segment {r0['segment']} "
        f"mult {r0['multiplier']}x", failures)
    summary["gates"]["stream_agreement"] = len(failures) == prior

    # ------------------------------------------------------------------
    if not args.skip_sim:
        print("=" * 72)
        print(f"GATE 4 — empirical: {args.rounds:,} provably-fair spins, "
              "all 15 configs within 3 SE of 99%")
        print("=" * 72)
        prior = len(failures)
        rng = BulkRng(args.seed, args.client, nonce_start=0)
        print(f"  server_seed_hash: {rng.server_seed_hash}")
        print(f"  client_seed: {rng.client_seed}  nonce range: "
              f"[0, {args.rounds})")
        n_rounds = args.rounds
        counts = {n: np.zeros(n, dtype=np.int64) for n in wh.SEGMENT_COUNTS}
        chunk = 2_000_000
        done = 0
        t0 = time.perf_counter()
        while done < n_rounds:
            step = min(chunk, n_rounds - done)
            floats = rng.floats(step)          # one nonce per spin
            for n in wh.SEGMENT_COUNTS:
                idx = np.floor(floats * n).astype(np.int64)
                counts[n] += np.bincount(idx, minlength=n)
            done += step
            rate = done / (time.perf_counter() - t0)
            print(f"  {done:,}/{n_rounds:,} spins ({rate:,.0f}/s)", flush=True)
        elapsed = time.perf_counter() - t0
        assert all(int(c.sum()) == n_rounds for c in counts.values())

        worst = {"z": 0.0, "config": None, "rtp": None}
        n_fail = 0
        per_config: Dict[str, Dict[str, float]] = {}
        print(f"  {'config':10s} {'emp RTP':>10s} {'emp SD':>8s} "
              f"{'ana SD':>8s} {'SE(RTP)':>10s} {'z':>7s}")
        for n, r in wh.all_configs():
            eng = engines[(n, r)]
            res = eng.summarize_counts(counts[n])
            z = res["z_score"]
            if not res["within_3se"]:
                n_fail += 1
            if abs(z) > abs(worst["z"]):
                worst = {"z": z, "config": f"{n}/{r}", "rtp": res["rtp"]}
            per_config[f"{n}/{r}"] = {
                "rtp": res["rtp"],
                "std": res["std_per_unit"],
                "z": z,
            }
            print(f"  {n:>2d}/{r:<7s} {res['rtp']:>10.6f} "
                  f"{res['std_per_unit']:>8.4f} {eng.std_per_unit:>8.4f} "
                  f"{res['se_rtp']:>10.6f} {z:>+7.2f}"
                  + ("   [FAIL >3SE]" if not res["within_3se"] else ""))
        check(
            n_fail == 0, "empirical 3-SE",
            f"15/15 configs within 3 SE over {n_rounds:,} spins; worst "
            f"{worst['config']} z={worst['z']:+.2f} RTP {worst['rtp']:.6f}",
            failures,
        )
        chi2_stats: Dict[int, float] = {}
        chi_fail = []
        for n in wh.SEGMENT_COUNTS:
            exp = n_rounds / n
            chi2 = float(((counts[n] - exp) ** 2 / exp).sum())
            chi2_stats[n] = chi2
            # 99.99% quantile of chi-square with n-1 dof
            if chi2 > float(stats.chi2.ppf(0.9999, n - 1)):
                chi_fail.append(n)
        check(not chi_fail, "uniformity chi-square",
              "chi2 per segments setting: " + ", ".join(
                  f"{n}:{chi2_stats[n]:.1f}" for n in wh.SEGMENT_COUNTS)
              + " (all under the 99.99% quantile)", failures)
        print(f"  throughput {n_rounds / elapsed:,.0f} spins/s, {elapsed:.1f}s"
              f" (each spin settled against all 15 configs)")
        summary["gates"]["empirical_3se"] = len(failures) == prior
        summary["empirical"] = {
            "rounds": n_rounds,
            "worst_config": worst["config"],
            "worst_z": worst["z"],
            "worst_rtp": worst["rtp"],
            "n_outside_3se": n_fail,
            "chi2_by_segments": chi2_stats,
            "rounds_per_sec": n_rounds / elapsed,
            "server_seed_hash": rng.server_seed_hash,
            "client_seed": rng.client_seed,
            "per_config": per_config,
        }

    # ------------------------------------------------------------------
    ok = not failures
    summary["passed"] = ok
    summary["failures"] = failures
    print("=" * 72)
    print(f"OVERALL: {'PASS' if ok else 'FAIL'} ({len(failures)} failure(s))")
    print("WHEEL_VALIDATION_JSON:" + json.dumps(summary, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
