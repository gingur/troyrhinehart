#!/usr/bin/env python3
"""Validate the Keno engine against the published references.

1. Payout-for-payout comparison of the engine's four risk paytables against
   ALL 260 cells of Stake's published Classic/Low/Medium/High tables
   (references/stake/keno.md §6, Stake's own KenoPayouts API response).
   The comparison is exact — Stake publishes the multipliers themselves,
   not rounded displays.

2. Analytic RTP: our hypergeometric enumeration
   ``sum_k pay[k] * C(n,k) C(40-n,10-k) / C(40,10)`` must reproduce Stake's
   published RTP verification table for all 40 (picks, risk) configurations
   at its printed 2-decimal precision, and sit at ~99% as Stake states.

3. Wizard-of-Odds cross-check (references/woo/keno.md): WoO has NO
   Stake-specific keno page; his closest match is the Gamesys 40-ball game
   (same 40-number / 10-draw structure, different paytable).  We apply our
   hypergeometric machinery to WoO's published 40-ball paytable and must
   reproduce his published RTP column (picks 3-10) — a methodology check
   on the shared config (40 numbers, 10 drawn), not a paytable match.

4. Provably-fair cross-check: a block of vectorized BulkRng rounds must
   bit-match the scalar verifier path (spinquest_sim.rng.keno_hits) draw
   for draw, and the engine's payout must equal the paytable lookup on the
   recomputed hit count for every round in the block.

5. Empirical check: 10M+ provably-fair rounds per configured (risk, picks)
   on the vectorized BulkRng stream; empirical RTP must land within 3 SE
   of the analytic value.

Hardened to ALWAYS return a verdict: every gate (including the reference
parsers) runs under a crash guard, so a thrown exception is converted into
a failing gate instead of a missing report; the machine-readable JSON line
prefixed ``KENO_VALIDATION_JSON:`` is printed on every path, crash
included.  Parser-sanity gates fail loudly if the reference markdown
drifts (wrong number of risk tables / RTP cells / WoO rows) rather than
passing vacuously on empty comparisons.  Exit code 0 iff every gate passes.

Usage:
    python scripts/validate_keno.py [--rounds N] [--configs risk:picks,...]
                                    [--skip-sim]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import traceback
from pathlib import Path
from typing import Callable, Dict, List, Tuple

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from spinquest_sim import rng as sq_rng  # noqa: E402
from spinquest_sim.games.keno import (  # noqa: E402
    DRAW_COUNT,
    MAX_PICKS,
    MIN_PICKS,
    POOL_SIZE,
    RISKS,
    Keno,
    hit_probability_exact,
    paytable,
    rtp_exact,
)
from spinquest_sim.rng import BulkRng  # noqa: E402

STAKE_MD = _ROOT / "references" / "stake" / "keno.md"
WOO_MD = _ROOT / "references" / "woo" / "keno.md"

# Stake's RTP table and WoO's return column are printed to 2 decimals of a
# percent; accept up to half of the last printed digit.
PCT_TOL = 0.005 + 1e-9

DEFAULT_CONFIGS: List[Tuple[str, int]] = [
    ("classic", 1),
    ("classic", 10),
    ("low", 9),
    ("medium", 5),
    ("high", 10),
]
DEFAULT_ROUNDS = 10_000_000

# Deterministic, reproducible campaign seeds (fixed 64-hex server seed of
# the same form Stake generates; hash commitment printed in the summary).
SIM_SERVER_SEED = hashlib.sha256(b"spinquest keno validation v1").hexdigest()
SIM_CLIENT_SEED = "spinquest-keno"


# ---------------------------------------------------------------------------
# Reference parsers
# ---------------------------------------------------------------------------

def parse_stake_paytables(path: Path = STAKE_MD) -> Dict[str, Dict[int, List[float]]]:
    """Parse the four §6 markdown payout tables -> {risk: {picks: [pays]}}."""
    tables: Dict[str, Dict[int, List[float]]] = {}
    risk: str | None = None
    for line in path.read_text().splitlines():
        line = line.strip()
        heading = re.match(r"^###\s+(\w+)\s+risk\s*$", line)
        if heading:
            risk = heading.group(1).lower()
            tables[risk] = {}
            continue
        if line.startswith("#"):
            risk = None  # any other heading ends the current risk section
            continue
        if risk is None or not line.startswith("|"):
            continue
        parts = [c.strip() for c in line.strip("|").split("|")]
        if not parts or not re.fullmatch(r"\d+", parts[0]):
            continue
        picks = int(parts[0])
        row: List[float] = []
        for cell in parts[1:]:
            if cell in ("—", "-", ""):
                break
            row.append(float(cell.rstrip("x")))
        tables[risk][picks] = row
    return tables


def parse_stake_rtp_table(path: Path = STAKE_MD) -> Dict[str, Dict[int, float]]:
    """Parse the §6 'RTP verification' percent table -> {risk: {picks: pct}}."""
    out: Dict[str, Dict[int, float]] = {r: {} for r in RISKS}
    order = ("classic", "low", "medium", "high")  # reference column order
    for line in path.read_text().splitlines():
        match = re.match(
            r"^\|\s*(\d+)\s*\|" + r"\s*([\d.]+)%\s*\|" * 4 + r"\s*$",
            line.strip(),
        )
        if not match:
            continue
        picks = int(match.group(1))
        if not MIN_PICKS <= picks <= MAX_PICKS:
            continue
        for i, risk in enumerate(order):
            out[risk][picks] = float(match.group(2 + i))
    return out


def parse_woo_40ball(path: Path = WOO_MD) -> Tuple[Dict[int, Dict[int, float]], Dict[int, float]]:
    """Parse WoO's Gamesys 40-ball paytable + return column.

    Returns ({picks: {catch: pay}}, {picks: return_pct}).
    """
    pays: Dict[int, Dict[int, float]] = {}
    rets: Dict[int, float] = {}
    in_40ball = False
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith("## "):
            # Only the "Closest equivalent: 40-Ball Keno" section holds the
            # Gamesys tables; later sections reuse "- Pick n:" lines for
            # unrelated video-keno pay tables and must be ignored.
            in_40ball = line.startswith("## Closest equivalent")
            continue
        if not in_40ball:
            continue
        pay_row = re.match(r"^- Pick (\d+): (.+)$", line)
        if pay_row:
            picks = int(pay_row.group(1))
            pays[picks] = {
                int(c): float(p)
                for c, p in re.findall(r"(\d+)→(\d+)", pay_row.group(2))
            }
            continue
        ret_row = re.match(r"^\|\s*(\d+)\s*\|\s*([\d.]+)%", line)
        if ret_row:
            picks = int(ret_row.group(1))
            if 3 <= picks <= 10:
                rets[picks] = float(ret_row.group(2))
    return pays, rets


# ---------------------------------------------------------------------------
# Validation sections
# ---------------------------------------------------------------------------

def check_stake_paytables() -> Dict[str, object]:
    ref = parse_stake_paytables()
    expected_cells = 4 * sum(n + 1 for n in range(1, 11))  # 4 * 65 = 260
    cells = 0
    mismatches: List[Dict[str, object]] = []
    for risk in RISKS:
        for picks in range(MIN_PICKS, MAX_PICKS + 1):
            ref_row = ref.get(risk, {}).get(picks)
            ours = paytable(risk, picks)
            if ref_row is None or len(ref_row) != picks + 1:
                mismatches.append(
                    {"risk": risk, "picks": picks, "error": "reference row missing",
                     "reference": ref_row}
                )
                continue
            cells += len(ref_row)
            for hits, (rv, ov) in enumerate(zip(ref_row, ours)):
                if rv != ov:  # exact — Stake publishes the multipliers
                    mismatches.append(
                        {"risk": risk, "picks": picks, "hits": hits,
                         "reference": rv, "computed": ov}
                    )
    return {
        "cells_compared": cells,
        "cells_expected": expected_cells,
        "mismatches": mismatches,
        "pass": cells == expected_cells and not mismatches,
    }


def check_stake_rtp() -> Dict[str, object]:
    ref = parse_stake_rtp_table()
    rows: List[Dict[str, object]] = []
    mismatches = 0
    worst = 0.0
    for risk in RISKS:
        for picks in range(MIN_PICKS, MAX_PICKS + 1):
            ours_pct = float(rtp_exact(risk, picks) * 100)
            ref_pct = ref[risk].get(picks)
            diff = abs(ours_pct - ref_pct) if ref_pct is not None else float("inf")
            worst = max(worst, diff)
            ok = ref_pct is not None and diff <= PCT_TOL
            mismatches += 0 if ok else 1
            rows.append(
                {"risk": risk, "picks": picks, "rtp_pct": ours_pct,
                 "reference_pct": ref_pct, "match": ok}
            )
    rtps = [r["rtp_pct"] for r in rows]
    return {
        "configs": rows,
        "n_configs": len(rows),
        "worst_abs_diff_pct": worst,
        "rtp_pct_min": min(rtps),
        "rtp_pct_max": max(rtps),
        "all_near_99": all(98.5 <= v <= 99.5 for v in rtps),
        "pass": mismatches == 0 and len(rows) == 40
        and all(98.5 <= v <= 99.5 for v in rtps),
    }


def check_woo_methodology() -> Dict[str, object]:
    pays, rets = parse_woo_40ball()
    rows: List[Dict[str, object]] = []
    mismatches = 0
    for picks in sorted(rets):
        table = pays.get(picks, {})
        ret = sum(
            pay * hit_probability_exact(picks, catch)
            for catch, pay in table.items()
        )
        ours_pct = float(ret * 100)
        diff = abs(ours_pct - rets[picks])
        ok = diff <= PCT_TOL
        mismatches += 0 if ok else 1
        rows.append(
            {"picks": picks, "woo_return_pct": rets[picks],
             "computed_pct": ours_pct, "match": ok}
        )
    return {
        "note": (
            "WoO publishes no Stake-keno analysis; this reproduces his "
            "Gamesys 40-ball returns (same 40-number/10-draw config, "
            "different paytable) with our hypergeometric enumeration."
        ),
        "configs": rows,
        "n_configs": len(rows),
        "pass": mismatches == 0 and len(rows) == 8,
    }


def check_provably_fair(n_rounds: int = 512) -> Dict[str, object]:
    """Bulk-vs-scalar bit-match gate, run inside the validation script.

    Row i of a BulkRng campaign must reproduce the scalar verifier draw
    (sq_rng.keno_hits — the critic-verified port of Stake's published
    byteGenerator -> floats -> Fisher-Yates chain) at nonce_start + i,
    number for number in draw order; and the engine's play_round payout
    must equal the paytable lookup on the independently recomputed hit
    count for every round checked.
    """
    nonce_start = 12345
    bulk = BulkRng(
        server_seed=SIM_SERVER_SEED,
        client_seed=SIM_CLIENT_SEED,
        nonce_start=nonce_start,
    )
    drawn_bulk = bulk.keno_hits(n_rounds)
    draw_mismatches = 0
    payout_mismatches = 0
    game = Keno(10, "high")
    sel = set(range(1, 11))
    for i in range(n_rounds):
        nonce = nonce_start + i
        scalar = sq_rng.keno_hits(SIM_SERVER_SEED, SIM_CLIENT_SEED, nonce)
        if list(drawn_bulk[i]) != list(scalar):
            draw_mismatches += 1
            continue
        res = game.play_round(SIM_SERVER_SEED, SIM_CLIENT_SEED, nonce)
        n_hits = len(sel & set(scalar))
        if res["n_hits"] != n_hits or res["payout"] != paytable("high", 10)[n_hits]:
            payout_mismatches += 1
    shape_ok = (
        drawn_bulk.shape == (n_rounds, DRAW_COUNT)
        and bool((drawn_bulk >= 1).all())
        and bool((drawn_bulk <= POOL_SIZE).all())
        and all(len(set(row.tolist())) == DRAW_COUNT for row in drawn_bulk)
    )
    return {
        "rounds_checked": n_rounds,
        "draw_mismatches": draw_mismatches,
        "payout_mismatches": payout_mismatches,
        "shape_and_uniqueness_ok": shape_ok,
        "pass": draw_mismatches == 0 and payout_mismatches == 0 and shape_ok,
    }


def _guarded(name: str, fn: Callable[[], Dict[str, object]]) -> Dict[str, object]:
    """Run one gate under a crash guard: an exception becomes a failing
    gate with the traceback attached, never a missing verdict."""
    try:
        return fn()
    except Exception:  # noqa: BLE001 — any crash must yield a verdict
        tb = traceback.format_exc()
        print(f"[{name}] CRASHED:\n{tb}", file=sys.stderr, flush=True)
        return {"pass": False, "error": tb.strip().splitlines()[-1], "crashed": True}


def run_empirical(configs: List[Tuple[str, int]], n_rounds: int) -> Dict[str, object]:
    results = []
    ok = True
    for i, (risk, picks) in enumerate(configs):
        game = Keno(picks, risk)
        bulk = BulkRng(
            server_seed=SIM_SERVER_SEED,
            client_seed=SIM_CLIENT_SEED,
            nonce_start=i * n_rounds,
        )
        print(f"[sim] {risk} picks={picks}: {n_rounds:,} rounds ...", flush=True)
        res = game.simulate(n_rounds, bulk=bulk, progress=False)
        ok = ok and res["within_3se"]
        print(
            f"[sim] {risk} picks={picks}: rtp={res['rtp']:.6f} "
            f"(analytic {res['analytic_rtp']:.6f}, se={res['se_rtp']:.6f}, "
            f"z={res['z_score']:+.3f}, "
            f"{'PASS' if res['within_3se'] else 'FAIL'}) "
            f"sd={res['std_per_unit']:.3f} "
            f"{res['rounds_per_sec']:,.0f} rounds/s",
            flush=True,
        )
        results.append(
            {
                "risk": risk,
                "picks": picks,
                "n_rounds": res["n_rounds"],
                "rtp": res["rtp"],
                "analytic_rtp": res["analytic_rtp"],
                "se_rtp": res["se_rtp"],
                "z_score": res["z_score"],
                "within_3se": res["within_3se"],
                "std_per_unit": res["std_per_unit"],
                "analytic_std_per_unit": res["analytic_std_per_unit"],
                "hit_histogram": res["hit_histogram"],
                "rounds_per_sec": res["rounds_per_sec"],
                "elapsed_s": res["elapsed_s"],
            }
        )
    return {"configs": results, "pass": ok}


def parse_configs_arg(text: str) -> List[Tuple[str, int]]:
    """Parse and validate --configs 'risk:picks,...' with clear errors."""
    configs: List[Tuple[str, int]] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        pieces = part.split(":")
        if len(pieces) != 2:
            raise SystemExit(f"--configs: expected 'risk:picks', got {part!r}")
        risk, picks_s = pieces[0].strip().lower(), pieces[1].strip()
        if risk not in RISKS:
            raise SystemExit(f"--configs: risk must be one of {RISKS}, got {risk!r}")
        try:
            picks = int(picks_s)
        except ValueError:
            raise SystemExit(f"--configs: picks must be an int, got {picks_s!r}")
        if not MIN_PICKS <= picks <= MAX_PICKS:
            raise SystemExit(
                f"--configs: picks must be in {MIN_PICKS}..{MAX_PICKS}, got {picks}"
            )
        configs.append((risk, picks))
    if not configs:
        raise SystemExit("--configs: no configurations given")
    return configs


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    ap.add_argument(
        "--configs",
        type=str,
        default=",".join(f"{r}:{n}" for r, n in DEFAULT_CONFIGS),
        help="comma-separated risk:picks pairs",
    )
    ap.add_argument("--skip-sim", action="store_true")
    args = ap.parse_args(argv)
    if args.rounds < 1:
        raise SystemExit(f"--rounds must be positive, got {args.rounds}")
    configs = parse_configs_arg(args.configs)

    print("=" * 72)
    print("KENO VALIDATION — Stake 4-risk paytables + RTP + WoO 40-ball + empirical")
    print("=" * 72)

    table = _guarded("table", check_stake_paytables)
    if table.get("crashed"):
        print(f"[table] CRASHED ({table['error']}) -> FAIL")
    else:
        print(
            f"[table] {table['cells_compared']}/{table['cells_expected']} payout cells "
            f"compared EXACTLY against Stake's 4 published risk tables; "
            f"mismatches: {len(table['mismatches'])} -> "
            f"{'PASS' if table['pass'] else 'FAIL'}"
        )
        for bad in table["mismatches"][:10]:
            print(f"  MISMATCH {bad}")

    rtp_check = _guarded("rtp", check_stake_rtp)
    if rtp_check.get("crashed"):
        print(f"[rtp]   CRASHED ({rtp_check['error']}) -> FAIL")
    else:
        print(
            f"[rtp]   {rtp_check['n_configs']}/40 (picks, risk) configs: analytic "
            f"hypergeometric RTP vs Stake's published table, worst |diff| = "
            f"{rtp_check['worst_abs_diff_pct']:.4f} pp (printed precision 0.01); "
            f"range {rtp_check['rtp_pct_min']:.2f}%..{rtp_check['rtp_pct_max']:.2f}% "
            f"(Stake states 99% RTP / 1% edge) -> "
            f"{'PASS' if rtp_check['pass'] else 'FAIL'}"
        )

    woo = _guarded("woo", check_woo_methodology)
    if woo.get("crashed"):
        print(f"[woo]   CRASHED ({woo['error']}) -> FAIL")
    else:
        print(
            f"[woo]   no Stake-specific WoO page (documented); Gamesys 40-ball "
            f"cross-check on the matching 40/10 config: "
            f"{sum(1 for r in woo['configs'] if r['match'])}/{woo['n_configs']} "
            f"published returns reproduced (picks 3-10) -> "
            f"{'PASS' if woo['pass'] else 'FAIL'}"
        )
        for row in woo["configs"]:
            print(
                f"[woo]     pick {row['picks']}: WoO {row['woo_return_pct']:.2f}% "
                f"vs computed {row['computed_pct']:.4f}% "
                f"({'ok' if row['match'] else 'MISMATCH'})"
            )

    fair = _guarded("fair", check_provably_fair)
    if fair.get("crashed"):
        print(f"[fair]  CRASHED ({fair['error']}) -> FAIL")
    else:
        print(
            f"[fair]  {fair['rounds_checked']} vectorized BulkRng rounds "
            f"bit-matched against the scalar Stake verifier path: "
            f"{fair['draw_mismatches']} draw mismatches, "
            f"{fair['payout_mismatches']} payout mismatches, "
            f"shape/uniqueness {'ok' if fair['shape_and_uniqueness_ok'] else 'BAD'} "
            f"-> {'PASS' if fair['pass'] else 'FAIL'}"
        )

    if args.skip_sim:
        sim = {"configs": [], "pass": True, "skipped": True}
        print("[sim]   skipped (--skip-sim)")
    else:
        sim = _guarded("sim", lambda: run_empirical(configs, args.rounds))
        if sim.get("crashed"):
            print(f"[sim]   CRASHED ({sim['error']}) -> FAIL")

    overall = bool(
        table["pass"] and rtp_check["pass"] and woo["pass"] and fair["pass"]
        and sim["pass"]
    )
    summary = {
        "game": "keno",
        "overall_pass": overall,
        "stake_paytables": (
            table if table.get("crashed") else {
                "cells_compared": table["cells_compared"],
                "cells_expected": table["cells_expected"],
                "n_mismatches": len(table["mismatches"]),
                "pass": table["pass"],
            }
        ),
        "stake_rtp": {k: v for k, v in rtp_check.items() if k != "configs"},
        "woo_40ball": woo,
        "provably_fair": fair,
        "empirical": sim,
        "meets_10m_bar": bool(args.skip_sim is False and args.rounds >= 10_000_000),
        "sim_seeds": {
            "server_seed": SIM_SERVER_SEED,
            "client_seed": SIM_CLIENT_SEED,
        },
    }
    print("KENO_VALIDATION_JSON: " + json.dumps(summary, default=float))
    print(f"OVERALL: {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001 — even a crash must emit a verdict
        tb = traceback.format_exc()
        print(tb, file=sys.stderr, flush=True)
        print(
            "KENO_VALIDATION_JSON: "
            + json.dumps(
                {
                    "game": "keno",
                    "overall_pass": False,
                    "error": tb.strip().splitlines()[-1],
                }
            )
        )
        print("OVERALL: FAIL")
        raise SystemExit(1)
