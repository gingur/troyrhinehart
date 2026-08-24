#!/usr/bin/env python3
"""Validate the Mines engine against the published references.

1. Payout-for-payout comparison of the analytic table against ALL 300 cells
   of Stake's published 24x24 payout table (references/stake/mines.md).
   Stake displays ``toFixed(2)`` values; exact half-cent ties (e.g. the
   exact 202,254.525x cell, printed as .52x in one place and .53x in the
   symmetric cell) are accepted, so the tolerance is |diff| <= 0.005+eps.

2. Wizard-of-Odds methodology cross-check (references/woo/mines.md):
   WoO's method is return = pays x P(win) with hypergeometric survival
   probability.  We (a) verify our P(win) against every probability WoO
   publishes, and (b) apply his prob-x-pay enumeration to STAKE's table,
   which must give 99.00% in every cell.  NOTE: WoO's own pays/returns are
   for a DIFFERENT ~95% (BetFury) paytable and intentionally do NOT match
   Stake's — the discrepancy is reported, not treated as an error.

3. Cross-verification gate: the vectorized BulkRng simulator is replayed
   round-for-round against the critic-verified scalar RNG path
   (``spinquest_sim.rng.mines_positions``); mine positions AND win/loss
   outcomes must bit-match, proving the 10M campaign runs on the verified
   provably-fair core.

4. Exactness gate: multiplier_exact x win_probability_exact == 99/100 in
   rational arithmetic (Fraction) for all 300 cells — no float tolerance.

5. Empirical check: 10M+ provably-fair rounds per (mines, picks) config on
   the vectorized BulkRng stream; empirical RTP must land within 3 SE of
   the analytic 99%.

Prints a human-readable report plus a machine-readable JSON line prefixed
``MINES_VALIDATION_JSON:`` (contains a named ``gates`` map).  Exit code 0
iff every gate passes; any unexpected exception exits nonzero with a FAIL
summary rather than a bare traceback.

Usage:
    python scripts/validate_mines.py [--rounds N] [--configs m:k,m:k,...]
                                     [--skip-sim]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import traceback
from fractions import Fraction
from pathlib import Path
from typing import Dict, List, Tuple

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from spinquest_sim import rng as sq_rng  # noqa: E402
from spinquest_sim.games.mines import (  # noqa: E402
    GRID_TILES,
    MAX_MINES,
    MIN_MINES,
    Mines,
    display_multiplier,
    multiplier,
    multiplier_exact,
    win_probability,
    win_probability_exact,
)
from spinquest_sim.rng import BulkRng  # noqa: E402


class ValidationError(RuntimeError):
    """A reference file is missing or structurally malformed."""

STAKE_MD = _ROOT / "references" / "stake" / "mines.md"
WOO_MD = _ROOT / "references" / "woo" / "mines.md"

# Display tolerance: table values are toFixed(2); exact .xx5 ties may be
# printed either way (both appear in Stake's own table for the same exact
# value), so accept up to half a cent.
DISPLAY_TOL = 0.005 + 1e-9

DEFAULT_CONFIGS: List[Tuple[int, int]] = [(1, 1), (3, 3), (5, 5), (10, 10), (24, 1)]
DEFAULT_ROUNDS = 10_000_000

# Deterministic, reproducible campaign seeds (any string is a valid server
# seed for the verifier; this one is a fixed 64-hex string like Stake's).
SIM_SERVER_SEED = hashlib.sha256(b"spinquest mines validation v1").hexdigest()
SIM_CLIENT_SEED = "spinquest-mines"


# ---------------------------------------------------------------------------
# Reference parsers
# ---------------------------------------------------------------------------

def parse_stake_table(path: Path = STAKE_MD) -> Dict[Tuple[int, int], float]:
    """Parse Stake's three markdown payout tables -> {(mines, picks): mult}.

    Hardened: raises :class:`ValidationError` on a missing file, malformed
    header, unparseable cell, duplicate cell, out-of-range coordinates, or a
    per-mines-column cell count different from the structural 25 - m.
    """
    if not path.is_file():
        raise ValidationError(f"reference file missing: {path}")
    cells: Dict[Tuple[int, int], float] = {}
    mine_cols: List[int] = []
    for lineno, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line.startswith("|"):
            continue
        parts = [c.strip() for c in line.strip("|").split("|")]
        if parts and parts[0] == "Gems picked":
            headers = [re.fullmatch(r"(\d+) mines?", c) for c in parts[1:]]
            if not headers or any(h is None for h in headers):
                raise ValidationError(f"{path}:{lineno}: malformed header: {line!r}")
            mine_cols = [int(h.group(1)) for h in headers]
            continue
        if not mine_cols or not parts or not re.fullmatch(r"\d+", parts[0]):
            continue
        picks = int(parts[0])
        if not 1 <= picks <= 24:
            continue
        for m, cell in zip(mine_cols, parts[1:]):
            if cell in ("—", "-", ""):
                continue
            if not re.fullmatch(r"[\d,]+(?:\.\d+)?x", cell):
                raise ValidationError(
                    f"{path}:{lineno}: unparseable multiplier cell {cell!r}"
                )
            if not (MIN_MINES <= m <= MAX_MINES and picks <= GRID_TILES - m):
                raise ValidationError(
                    f"{path}:{lineno}: impossible cell mines={m} picks={picks}"
                )
            if (m, picks) in cells:
                raise ValidationError(
                    f"{path}:{lineno}: duplicate cell mines={m} picks={picks}"
                )
            cells[(m, picks)] = float(cell.replace(",", "").rstrip("x"))
    # Structural completeness: each mines column must hold exactly 25-m cells.
    for m in range(MIN_MINES, MAX_MINES + 1):
        got = sum(1 for (mm, _) in cells if mm == m)
        if got != GRID_TILES - m:
            raise ValidationError(
                f"{path}: mines={m} column has {got} cells, expected {GRID_TILES - m}"
            )
    return cells


def parse_woo_table(path: Path = WOO_MD) -> List[Dict[str, float]]:
    """Parse WoO's 300-row analysis table -> [{mines,picks,pays,prob,ret}].

    Hardened: raises :class:`ValidationError` on a missing file, duplicate
    (mines, picks) rows, or a row count different from the 300 valid combos.
    """
    if not path.is_file():
        raise ValidationError(f"reference file missing: {path}")
    rows: List[Dict[str, float]] = []
    seen: set = set()
    pat = re.compile(
        r"^\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|$"
    )
    for lineno, line in enumerate(path.read_text().splitlines(), 1):
        match = pat.match(line.strip())
        if not match:
            continue
        m, k = int(match.group(1)), int(match.group(2))
        if not (MIN_MINES <= m <= MAX_MINES and 1 <= k <= GRID_TILES - m):
            continue
        if (m, k) in seen:
            raise ValidationError(
                f"{path}:{lineno}: duplicate WoO row mines={m} picks={k}"
            )
        seen.add((m, k))
        rows.append(
            {
                "mines": m,
                "picks": k,
                "pays": float(match.group(3)),
                "prob": float(match.group(4)),
                "ret": float(match.group(5)),
            }
        )
    expected = sum(GRID_TILES - m for m in range(MIN_MINES, MAX_MINES + 1))
    if len(rows) != expected:
        raise ValidationError(
            f"{path}: parsed {len(rows)} WoO rows, expected {expected}"
        )
    return rows


# ---------------------------------------------------------------------------
# Validation sections
# ---------------------------------------------------------------------------

def check_stake_table() -> Dict[str, object]:
    ref = parse_stake_table()
    expected_cells = sum(GRID_TILES - m for m in range(1, 25))  # 300
    mismatches: List[Dict[str, object]] = []
    exact_2dp = 0
    tie_cells = 0
    max_diff = 0.0
    for (m, k), ref_val in sorted(ref.items()):
        ours = multiplier(m, k)
        diff = abs(ours - ref_val)
        max_diff = max(max_diff, diff)
        if abs(round(ours, 2) - ref_val) < 1e-9:
            exact_2dp += 1
        elif diff <= DISPLAY_TOL:
            tie_cells += 1  # exact .xx5 half-cent tie, printed the other way
        else:
            mismatches.append(
                {"mines": m, "picks": k, "reference": ref_val, "computed": ours}
            )
    return {
        "cells_parsed": len(ref),
        "cells_expected": expected_cells,
        "exact_2dp_matches": exact_2dp,
        "half_cent_tie_cells": tie_cells,
        "max_abs_diff": max_diff,
        "mismatches": mismatches,
        "pass": len(ref) == expected_cells and not mismatches,
    }


def check_spot_checks() -> Dict[str, object]:
    """Verbatim in-game spot checks published in references/stake/mines.md §7."""
    published = [
        (1, 1, 1.03),      # "1 mine / 1 gem = 1.03x"
        (24, 1, 24.75),    # "24 mines / 1 gem = 24.75x"
        (1, 24, 24.75),    # "1 mine / 24 gems (full clear) = 24.75x"
        (3, 22, 2277.00),  # "3 mines / 22 gems = 2,277.00x"
    ]
    checks = []
    ok = True
    for m, k, want in published:
        got = display_multiplier(m, k)
        good = abs(got - want) < 1e-9
        ok = ok and good
        checks.append({"mines": m, "picks": k, "published": want, "computed": got,
                       "match": good})
    return {"checks": checks, "pass": ok}


def check_exact_rtp_identity() -> Dict[str, object]:
    """multiplier_exact x win_probability_exact == 99/100 exactly (Fraction)
    for every one of the 300 valid cells — zero float tolerance."""
    target = Fraction(99, 100)
    bad: List[Tuple[int, int]] = []
    n = 0
    for m in range(MIN_MINES, MAX_MINES + 1):
        for k in range(1, GRID_TILES - m + 1):
            n += 1
            if multiplier_exact(m, k) * win_probability_exact(m, k) != target:
                bad.append((m, k))
    return {"cells_checked": n, "exact_failures": bad, "pass": n == 300 and not bad}


def check_scalar_bulk_bitmatch(
    n_rounds: int = 2_000, configs: List[Tuple[int, int]] = ((1, 24), (5, 5), (24, 1))
) -> Dict[str, object]:
    """Replay the vectorized simulator round-for-round against the verified
    scalar RNG path: mine positions AND simulated win/loss outcomes must
    bit-match at every nonce.  This is what licenses the 10M campaign."""
    import numpy as np

    results = []
    ok = True
    for m, k in configs:
        game = Mines(m, k)
        bulk = BulkRng(
            server_seed=SIM_SERVER_SEED, client_seed=SIM_CLIENT_SEED, nonce_start=0
        )
        pos_bulk = bulk.mines_positions(m, n_rounds)  # (n_rounds, m)
        pos_mismatch = 0
        outcome_mismatch = 0
        for nonce in range(n_rounds):
            scalar = sq_rng.mines_positions(
                SIM_SERVER_SEED, SIM_CLIENT_SEED, nonce, m
            )
            if list(pos_bulk[nonce]) != scalar:
                pos_mismatch += 1
            bulk_win = not bool(np.any(pos_bulk[nonce] < k))
            scalar_win = game.play_round(SIM_SERVER_SEED, SIM_CLIENT_SEED, nonce)["win"]
            if bulk_win is not scalar_win:
                outcome_mismatch += 1
        good = pos_mismatch == 0 and outcome_mismatch == 0
        ok = ok and good
        results.append(
            {
                "mines": m,
                "picks": k,
                "rounds_compared": n_rounds,
                "position_mismatches": pos_mismatch,
                "outcome_mismatches": outcome_mismatch,
                "pass": good,
            }
        )
    return {"configs": results, "pass": ok}


def check_woo_methodology() -> Dict[str, object]:
    rows = parse_woo_table()
    # (a) our survival probabilities vs every probability WoO publishes.
    prob_bad = [
        r
        for r in rows
        if abs(win_probability(int(r["mines"]), int(r["picks"])) - r["prob"]) > 5e-7
    ]
    # (b) WoO's exact methodology (prob x pay enumeration) applied to
    # STAKE's paytable: every cell must return exactly 0.99.
    stake_ret_min, stake_ret_max = 1.0, 0.0
    worst_dev = 0.0
    for m in range(1, 25):
        for k in range(1, 25 - m + 1):
            ret = multiplier(m, k) * win_probability(m, k)
            stake_ret_min = min(stake_ret_min, ret)
            stake_ret_max = max(stake_ret_max, ret)
            worst_dev = max(worst_dev, abs(ret - 0.99))
    # WoO's own (BetFury) table returns: the same enumeration on his pays,
    # using the EXACT hypergeometric probability (his printed prob column is
    # rounded to 6dp, which is useless for the tiny-probability rows).
    # WoO: "In cases of 2 to 24 mines, the expected return is always close to
    # 95%"; the 1-mine rows are his documented exception (as low as ~36%).
    woo_returns = [
        r["pays"] * win_probability(int(r["mines"]), int(r["picks"])) for r in rows
    ]
    anomalies = [r for r in rows if r["ret"] > 1.0]  # his two known typo rows
    clean = [
        r["pays"] * win_probability(int(r["mines"]), int(r["picks"]))
        for r in rows
        if r["ret"] <= 1.0 and r["mines"] >= 2
    ]
    return {
        "woo_rows_parsed": len(rows),
        "prob_column_matches": len(rows) - len(prob_bad),
        "prob_mismatches": prob_bad[:5],
        "stake_table_return_min": stake_ret_min,
        "stake_table_return_max": stake_ret_max,
        "stake_table_worst_dev_from_099": worst_dev,
        "woo_table_mean_return": sum(woo_returns) / len(woo_returns),
        "woo_table_mean_return_2plus_mines": sum(clean) / len(clean),
        "woo_anomalous_rows": [
            {"mines": r["mines"], "picks": r["picks"], "pays": r["pays"], "ret": r["ret"]}
            for r in anomalies
        ],
        "pass": not prob_bad and worst_dev < 1e-12 and len(rows) == 300,
    }


def run_empirical(configs: List[Tuple[int, int]], n_rounds: int) -> Dict[str, object]:
    results = []
    ok = True
    for i, (m, k) in enumerate(configs):
        game = Mines(m, k)
        bulk = BulkRng(
            server_seed=SIM_SERVER_SEED,
            client_seed=SIM_CLIENT_SEED,
            nonce_start=i * n_rounds,
        )
        print(f"[sim] mines={m} picks={k}: {n_rounds:,} rounds ...", flush=True)
        res = game.simulate(n_rounds, bulk=bulk)
        ok = ok and res["within_3se"]
        print(
            f"[sim] mines={m} picks={k}: rtp={res['rtp']:.6f} "
            f"(analytic 0.990000, se={res['se_rtp']:.6f}, z={res['z_score']:+.3f}, "
            f"{'PASS' if res['within_3se'] else 'FAIL'}) "
            f"{res['rounds_per_sec']:,.0f} rounds/s",
            flush=True,
        )
        results.append(
            {
                "mines": m,
                "picks": k,
                "n_rounds": res["n_rounds"],
                "wins": res["wins"],
                "rtp": res["rtp"],
                "analytic_rtp": res["analytic_rtp"],
                "se_rtp": res["se_rtp"],
                "z_score": res["z_score"],
                "within_3se": res["within_3se"],
                "std_per_unit": res["std_per_unit"],
                "analytic_std_per_unit": res["analytic_std_per_unit"],
                "rounds_per_sec": res["rounds_per_sec"],
                "elapsed_s": res["elapsed_s"],
            }
        )
    return {"configs": results, "pass": ok}


def _parse_configs(text: str) -> List[Tuple[int, int]]:
    configs: List[Tuple[int, int]] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        match = re.fullmatch(r"(\d+):(\d+)", part)
        if not match:
            raise SystemExit(f"--configs: expected mines:picks, got {part!r}")
        m, k = int(match.group(1)), int(match.group(2))
        Mines(m, k)  # raises ValueError with a clear message if invalid
        configs.append((m, k))
    if not configs:
        raise SystemExit("--configs: no valid mines:picks pairs given")
    return configs


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    ap.add_argument(
        "--configs",
        type=str,
        default=",".join(f"{m}:{k}" for m, k in DEFAULT_CONFIGS),
        help="comma-separated mines:picks pairs",
    )
    ap.add_argument("--skip-sim", action="store_true")
    args = ap.parse_args(argv)
    if args.rounds < 1:
        raise SystemExit("--rounds must be >= 1")
    configs = _parse_configs(args.configs)

    print("=" * 72)
    print("MINES VALIDATION — Stake 24x24 table + WoO methodology + empirical")
    print("=" * 72)

    table = check_stake_table()
    print(
        f"[table] {table['cells_parsed']}/{table['cells_expected']} cells parsed; "
        f"{table['exact_2dp_matches']} exact 2dp matches, "
        f"{table['half_cent_tie_cells']} exact half-cent tie cells, "
        f"max |diff| = {table['max_abs_diff']:.6f}, "
        f"mismatches beyond tolerance: {len(table['mismatches'])} -> "
        f"{'PASS' if table['pass'] else 'FAIL'}"
    )
    for bad in table["mismatches"][:10]:
        print(f"  MISMATCH {bad}")

    spots = check_spot_checks()
    for c in spots["checks"]:
        print(
            f"[spot]  mines={c['mines']} picks={c['picks']}: published "
            f"{c['published']}x, computed {c['computed']}x -> "
            f"{'OK' if c['match'] else 'MISMATCH'}"
        )
    print(f"[spot]  verbatim published spot checks -> "
          f"{'PASS' if spots['pass'] else 'FAIL'}")

    exact = check_exact_rtp_identity()
    print(
        f"[exact] Fraction identity mult x P(win) == 99/100 on "
        f"{exact['cells_checked']}/300 cells, failures: "
        f"{len(exact['exact_failures'])} -> {'PASS' if exact['pass'] else 'FAIL'}"
    )

    bitmatch = check_scalar_bulk_bitmatch()
    for c in bitmatch["configs"]:
        print(
            f"[xver]  mines={c['mines']} picks={c['picks']}: "
            f"{c['rounds_compared']} rounds vs verified scalar path — "
            f"{c['position_mismatches']} position mismatches, "
            f"{c['outcome_mismatches']} outcome mismatches -> "
            f"{'PASS' if c['pass'] else 'FAIL'}"
        )
    print(
        f"[xver]  vectorized simulator bit-matches verified scalar RNG core -> "
        f"{'PASS' if bitmatch['pass'] else 'FAIL'}"
    )

    woo = check_woo_methodology()
    print(
        f"[woo]   prob column: {woo['prob_column_matches']}/{woo['woo_rows_parsed']} "
        f"rows match our hypergeometric P(win) (tol 5e-7)"
    )
    print(
        f"[woo]   WoO prob-x-pay enumeration applied to STAKE table: every cell "
        f"returns 0.99 (min={woo['stake_table_return_min']:.15f}, "
        f"max={woo['stake_table_return_max']:.15f}, "
        f"worst |dev| = {woo['stake_table_worst_dev_from_099']:.2e}) -> "
        f"{'PASS' if woo['pass'] else 'FAIL'}"
    )
    print(
        "[woo]   DISCREPANCY (expected, documented): WoO's own page analyzes the "
        "BetFury ~95% paytable, NOT Stake's 99% schedule."
    )
    print(
        f"[woo]   mean return of WoO's published table (2-24 mines, ex his 2 "
        f"typo rows) = {woo['woo_table_mean_return_2plus_mines']:.4f} vs Stake "
        f"0.9900 exactly — the ~4pp gap is paytable choice, mechanics are "
        f"identical. (All-rows mean {woo['woo_table_mean_return']:.4f}: the "
        f"1-mine rows are WoO's documented exception, returns down to ~0.36.)"
    )
    for r in woo["woo_anomalous_rows"]:
        print(
            f"[woo]   known WoO typo row (captured, excluded): mines={r['mines']} "
            f"picks={r['picks']} pays={r['pays']} return={r['ret']:.4f} > 1"
        )

    if args.skip_sim:
        sim = {"configs": [], "pass": True, "skipped": True}
        print("[sim]   skipped (--skip-sim) — empirical gate NOT exercised")
    else:
        if args.rounds < DEFAULT_ROUNDS:
            print(
                f"[sim]   NOTE: --rounds {args.rounds:,} is below the official "
                f"{DEFAULT_ROUNDS:,}-round empirical bar (smoke run only)",
                flush=True,
            )
        sim = run_empirical(configs, args.rounds)
        sim["skipped"] = False
        sim["meets_10m_bar"] = args.rounds >= DEFAULT_ROUNDS

    gates = {
        "stake_table_300_cells": bool(table["pass"]),
        "published_spot_checks": bool(spots["pass"]),
        "exact_rtp_identity": bool(exact["pass"]),
        "scalar_bulk_bitmatch": bool(bitmatch["pass"]),
        "woo_methodology": bool(woo["pass"]),
        "empirical_within_3se": bool(sim["pass"]),
    }
    overall = all(gates.values())
    summary = {
        "game": "mines",
        "overall_pass": overall,
        "gates": gates,
        "stake_table": {kk: vv for kk, vv in table.items() if kk != "mismatches"}
        | {"n_mismatches": len(table["mismatches"])},
        "spot_checks": spots,
        "exact_rtp_identity": {
            "cells_checked": exact["cells_checked"],
            "exact_failures": exact["exact_failures"],
            "pass": exact["pass"],
        },
        "scalar_bulk_bitmatch": bitmatch,
        "woo_methodology": woo,
        "woo_discrepancy_note": (
            "references/woo/mines.md analyzes the BetFury ~95% paytable; "
            "Stake's schedule is 0.99/P(win) (99% RTP). WoO's prob-x-pay "
            "methodology applied to Stake's table returns 0.99 in every cell; "
            "WoO's own published pays intentionally do not match Stake's."
        ),
        "empirical": sim,
        "empirical_skipped": bool(sim.get("skipped", False)),
        "sim_seeds": {
            "server_seed": SIM_SERVER_SEED,
            "client_seed": SIM_CLIENT_SEED,
        },
    }
    print("MINES_VALIDATION_JSON: " + json.dumps(summary, default=float))
    verdict = "PASS" if overall else "FAIL"
    if overall and summary["empirical_skipped"]:
        verdict += " (analytic gates only — empirical sim skipped)"
    elif overall and not sim.get("meets_10m_bar", True):
        verdict += " (smoke-level empirical rounds, below the 10M bar)"
    print(f"OVERALL: {verdict}")
    return 0 if overall else 1


def _guarded_main() -> int:
    try:
        return main()
    except ValidationError as exc:
        print(f"VALIDATION ERROR: {exc}", file=sys.stderr)
        print(
            "MINES_VALIDATION_JSON: "
            + json.dumps({"game": "mines", "overall_pass": False,
                          "error": str(exc)})
        )
        print("OVERALL: FAIL")
        return 2
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        traceback.print_exc()
        print(
            "MINES_VALIDATION_JSON: "
            + json.dumps({"game": "mines", "overall_pass": False,
                          "error": f"{type(exc).__name__}: {exc}"})
        )
        print("OVERALL: FAIL")
        return 3


if __name__ == "__main__":
    raise SystemExit(_guarded_main())
