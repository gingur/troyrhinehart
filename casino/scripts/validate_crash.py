#!/usr/bin/env python3
"""Validate the Crash engine against the published references.

1. Published-spec parity (references/stake/crash.md): the module's constants
   (terminating hash, block-584,500 salt, chain length, 1% edge, 1,000,000x
   cashout cap) and the verbatim crash-point formula are re-parsed from the
   reference document and asserted equal.

2. Payout-for-payout comparison: Crash has no discrete paytable — the
   published payout rule is continuous (cashout target w pays w iff the
   crash point >= w, with P(crash >= w) = 0.99/w and RTP = 0.99 at EVERY
   target).  We therefore compare, on a grid of targets, the exact
   float64-semantics analytic P(win)/RTP against the reference's closed
   forms; RTP must sit within the 32-bit quantization bound w/2^32 of 0.99.

3. Chain-mechanics check: a 10,001-hash chain is built and verified
   (terminating hash reached by re-hashing, per-game verification steps,
   streamed simulator bit-identical to scalar chain play).

4. Empirical bar: 10M+ provably-fair rounds per mechanism —
   (a) vectorized BulkRng stream (critic-verified rng core), and
   (b) Stake's ACTUAL salted hash-chain mechanism, streamed.
   At every target, empirical P(win) and RTP must land within 3 SE of the
   exact analytic values.

5. Wizard-of-Odds comparison (references/woo/crash.md): WoO analyzes
   SmartSoft's JetX (97% RTP, 3% edge, tick-based mechanism), NOT Stake's
   Crash.  A side-by-side table is printed as a documented comparison —
   the numbers intentionally do NOT match and are not a pass/fail target;
   only the shared shape (P = RTP/w, flat edge) is checked.

Prints a human-readable report plus a machine-readable JSON line prefixed
``CRASH_VALIDATION_JSON:``.  Exit code 0 iff every gate passes.

Usage:
    python scripts/validate_crash.py [--rounds N] [--chain-rounds N]
                                     [--targets w,w,...] [--skip-sim]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Dict, List

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from spinquest_sim.games.crash import (  # noqa: E402
    EDGE_MULTIPLIER,
    HOUSE_EDGE,
    MAX_CASHOUT,
    STAKE_CHAIN_LENGTH,
    STAKE_SALT,
    STAKE_TERMINATING_HASH,
    TWO32,
    Crash,
    HashChain,
    analytic_table,
    build_hash_chain,
    crash_int_from_hash,
    crash_point_from_int,
    instant_bust_probability,
    next_chain_hash,
    simulate_chain_targets,
    simulate_targets,
    verify_game_hash,
)
from spinquest_sim.games import crash as crash_mod  # noqa: E402
from spinquest_sim.rng import BulkRng  # noqa: E402

STAKE_MD = _ROOT / "references" / "stake" / "crash.md"
WOO_MD = _ROOT / "references" / "woo" / "crash.md"

DEFAULT_TARGETS = [1.01, 1.5, 2.0, 5.0, 10.0, 100.0, 1000.0]
PAYTABLE_TARGETS = [
    1.01, 1.02, 1.1, 1.23, 1.5, 1.98, 2.0, 2.5, 3.0, 3.33, 5.0, 10.0,
    20.0, 33.33, 50.0, 100.0, 250.0, 1000.0, 10_000.0, 100_000.0, 1_000_000.0,
]
DEFAULT_ROUNDS = 10_000_000
DEFAULT_CHAIN_ROUNDS = 10_000_000

# Deterministic, reproducible campaign seeds.
SIM_SERVER_SEED = hashlib.sha256(b"spinquest crash validation v1").hexdigest()
SIM_CLIENT_SEED = "spinquest-crash"
SIM_CHAIN_SECRET = hashlib.sha256(b"spinquest crash chain v1").hexdigest()


# ---------------------------------------------------------------------------
# Reference parsers
# ---------------------------------------------------------------------------

def parse_stake_reference(path: Path = STAKE_MD) -> Dict[str, object]:
    """Re-parse the published constants and formula from the reference doc."""
    text = path.read_text()
    hashes = re.findall(r"`([0-9a-f]{64})`", text)
    term = next(h for h in hashes if not h.startswith("0000000000"))
    salt = next(h for h in hashes if h.startswith("0000000000"))
    chain_len = int(
        re.search(r"chain of \*\*([\d,]+)\s*\n?\s*SHA256 hashes", text)
        .group(1).replace(",", "")
    )
    edge = float(re.search(r"House edge.*?\*\*([\d.]+)%\*\*", text).group(1)) / 100
    max_cash = float(
        re.search(r"Maximum cashout value.*?\*\*([\d,]+)[x×]\*\*", text)
        .group(1).replace(",", "")
    )
    formula_found = (
        "Math.max(1, (2 ** 32 / (int + 1)) * (1 - 0.01))" in text
        and "hmac.digest('hex').substr(0, 8)" in text
        and "createHmac('sha256', gameHash)" in text
        and "hmac.update(blockHash)" in text
    )
    return {
        "terminating_hash": term,
        "salt": salt,
        "chain_length": chain_len,
        "house_edge": edge,
        "max_cashout": max_cash,
        "formula_found": formula_found,
        "min_crash_is_1": "lowest\ncrashpoint of 1" in text
        or "lowest crashpoint of 1" in text.replace("\n", " "),
    }


def parse_woo_reference(path: Path = WOO_MD) -> Dict[str, object]:
    """JetX facts from the WoO reference (comparison only, not a target)."""
    text = path.read_text()
    rtp = float(re.search(r"Return \(RTP\): \*\*(\d+)%\*\*", text).group(1)) / 100
    edge = float(re.search(r"House edge: \*\*(\d+)%\*\*", text).group(1)) / 100
    pwin = re.search(r"P\(win\) = ([\d.]+) / w", text).group(1)
    example = re.search(
        r"goal 3x → P\(win\) = 0\.97/3 ≈ ([\d.]+)%", text
    )
    goal_range = re.search(r"\*\*([\d.]+)x to ([\d.]+)x\*\*", text)
    return {
        "game": "JetX (SmartSoft Gaming)",
        "rtp": rtp,
        "house_edge": edge,
        "p_win_formula": f"{pwin} / w",
        "p_win_numerator": float(pwin),
        "example_3x_pct": float(example.group(1)) if example else None,
        "goal_min": float(goal_range.group(1)) if goal_range else None,
        "goal_max": float(goal_range.group(2)) if goal_range else None,
    }


# ---------------------------------------------------------------------------
# Validation sections
# ---------------------------------------------------------------------------

def check_spec_parity() -> Dict[str, object]:
    ref = parse_stake_reference()
    checks = {
        "terminating_hash": ref["terminating_hash"] == STAKE_TERMINATING_HASH,
        "salt_block_584500": ref["salt"] == STAKE_SALT,
        "chain_length_10M": ref["chain_length"] == STAKE_CHAIN_LENGTH,
        "house_edge_1pct": ref["house_edge"] == HOUSE_EDGE,
        "max_cashout_1Mx": ref["max_cashout"] == MAX_CASHOUT,
        "verbatim_formula_present": bool(ref["formula_found"]),
        "edge_multiplier_is_1_minus_001": EDGE_MULTIPLIER == 1 - 0.01 == 0.99,
        "min_crash_1": crash_point_from_int(TWO32 - 1) == 1.0,
    }
    return {"reference": ref, "checks": checks, "pass": all(checks.values())}


def check_payout_table() -> Dict[str, object]:
    """The continuous 'paytable': exact vs published closed forms per target."""
    rows = analytic_table(PAYTABLE_TARGETS)
    worst_rtp_dev = 0.0
    worst_p_reldev = 0.0
    ok = True
    bust = instant_bust_probability()
    for r in rows:
        rtp_dev = abs(r["rtp"] - 0.99)
        p_reldev = abs(r["win_probability"] - r["win_probability_ideal"]) / r[
            "win_probability_ideal"
        ]
        worst_rtp_dev = max(worst_rtp_dev, rtp_dev)
        worst_p_reldev = max(worst_p_reldev, p_reldev)
        r["rtp_dev_from_099"] = rtp_dev
        r["within_quantization"] = rtp_dev <= r["rtp_quantization_bound"] + 1e-12
        ok = ok and r["within_quantization"]
    bust_ok = abs(bust - 0.01) < 1e-4
    return {
        "rows": rows,
        "worst_rtp_dev_from_099": worst_rtp_dev,
        "worst_p_rel_dev_from_ideal": worst_p_reldev,
        "instant_bust_probability": bust,
        "instant_bust_ok": bust_ok,
        "pass": ok and bust_ok,
    }


def check_chain_mechanics() -> Dict[str, object]:
    """Build and fully verify a 10,001-hash chain (10,000 playable games)."""
    seed = "validation-chain-secret"
    length = 10_001
    chain = build_hash_chain(seed, length)
    term = chain[-1]
    # terminating hash reachable from the chain's oldest hash in length-1 steps
    h = chain[0]
    for _ in range(length - 1):
        h = next_chain_hash(h)
    term_ok = h == term
    # spot verification steps for games 1, 100, 10,000
    steps_ok = all(
        verify_game_hash(chain[-1 - g], term, length) == g
        for g in (1, 100, length - 1)
    )
    # streamed simulator bit-identical to scalar HashChain play (all 10k games)
    hc = HashChain(seed, length=length)
    scalar_ints = [
        crash_int_from_hash(hc.pop_hash()[1], STAKE_SALT)
        for _ in range(length - 1)
    ]
    ints, term_stream = crash_mod._stream_chain_ints(
        seed, length - 1, STAKE_SALT, progress=False
    )
    stream_ok = term_stream == term and ints.tolist() == scalar_ints
    return {
        "chain_length": length,
        "terminating_hash": term,
        "terminating_reachable": term_ok,
        "verification_steps_ok": steps_ok,
        "stream_bit_identical_to_scalar": stream_ok,
        "pass": term_ok and steps_ok and stream_ok,
    }


def _sim_rows(res: Dict[str, object]) -> List[Dict[str, object]]:
    return [
        {
            "target": r["config"]["target"],
            "n_rounds": r["n_rounds"],
            "wins": r["wins"],
            "win_rate": r["win_rate"],
            "analytic_win_probability": r["analytic_win_probability"],
            "rtp": r["rtp"],
            "analytic_rtp": r["analytic_rtp"],
            "se_rtp": r["se_rtp"],
            "z_score": r["z_score"],
            "within_3se": r["within_3se"],
            "std_per_unit": r["std_per_unit"],
            "analytic_std_per_unit": r["analytic_std_per_unit"],
        }
        for r in res["targets"]
    ]


def _print_sim(label: str, res: Dict[str, object]) -> None:
    for r in res["targets"]:
        w = r["config"]["target"]
        print(
            f"[sim:{label}] w={w:<8g} p={r['win_rate']:.8f} "
            f"(exact {r['analytic_win_probability']:.8f}) "
            f"rtp={r['rtp']:.6f} (exact {r['analytic_rtp']:.6f}, "
            f"se={r['se_rtp']:.6f}, z={r['z_score']:+.3f}) "
            f"{'PASS' if r['within_3se'] else 'FAIL'}",
            flush=True,
        )
    print(
        f"[sim:{label}] {res['n_rounds']:,} rounds in {res['elapsed_s']:.1f}s "
        f"({res['rounds_per_sec']:,.0f} rounds/s) -> "
        f"{'PASS' if res['pass'] else 'FAIL'}",
        flush=True,
    )


def run_empirical_bulk(targets: List[float], n_rounds: int) -> Dict[str, object]:
    bulk = BulkRng(
        server_seed=SIM_SERVER_SEED, client_seed=SIM_CLIENT_SEED, nonce_start=0
    )
    print(
        f"[sim:bulk] {n_rounds:,} provably-fair BulkRng rounds, "
        f"{len(targets)} targets ...",
        flush=True,
    )
    res = simulate_targets(targets, n_rounds, bulk=bulk)
    _print_sim("bulk", res)
    return {
        "mechanism": "seed_pair_bulk",
        "n_rounds": n_rounds,
        "rounds_per_sec": res["rounds_per_sec"],
        "elapsed_s": res["elapsed_s"],
        "targets": _sim_rows(res),
        "verification": res["verification"],
        "pass": res["pass"],
    }


def run_empirical_chain(targets: List[float], n_rounds: int) -> Dict[str, object]:
    print(
        f"[sim:chain] {n_rounds:,} rounds of the ACTUAL salted hash-chain "
        f"mechanism (sequential SHA-256 walk + HMAC) ...",
        flush=True,
    )
    res = simulate_chain_targets(
        targets, n_rounds, secret_seed=SIM_CHAIN_SECRET, salt=STAKE_SALT
    )
    _print_sim("chain", res)
    return {
        "mechanism": "hash_chain",
        "n_rounds": n_rounds,
        "rounds_per_sec": res["rounds_per_sec"],
        "elapsed_s": res["elapsed_s"],
        "targets": _sim_rows(res),
        "verification": res["verification"],
        "pass": res["pass"],
    }


def check_woo_comparison(targets: List[float]) -> Dict[str, object]:
    woo = parse_woo_reference()
    # Shape check only: WoO's published P(win) = 0.97/w with his example.
    shape_ok = (
        abs(woo["p_win_numerator"] - woo["rtp"]) < 1e-12
        and abs(woo["rtp"] - (1 - woo["house_edge"])) < 1e-12
    )
    example_ok = (
        woo["example_3x_pct"] is None
        or abs(100 * woo["rtp"] / 3 - woo["example_3x_pct"]) < 0.005
    )
    rows = []
    for w in targets:
        game = Crash(w)
        p_jetx = woo["rtp"] / w if w >= (woo["goal_min"] or 1.01) else None
        rows.append(
            {
                "target": w,
                "stake_p_win": game.win_probability,
                "stake_rtp": game.rtp,
                "stake_std": game.std_per_unit,
                "jetx_p_win": p_jetx,
                "jetx_rtp": woo["rtp"] if p_jetx is not None else None,
                "jetx_std": math.sqrt(woo["rtp"] * w - woo["rtp"] ** 2)
                if p_jetx is not None
                else None,
            }
        )
    return {
        "woo_reference": woo,
        "comparison_rows": rows,
        "shape_ok": shape_ok,
        "example_ok": example_ok,
        # DOCUMENTED comparison, not a numeric target: pass = parse + shape.
        "pass": shape_ok and example_ok,
    }


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    ap.add_argument("--chain-rounds", type=int, default=DEFAULT_CHAIN_ROUNDS)
    ap.add_argument(
        "--targets", type=str,
        default=",".join(str(w) for w in DEFAULT_TARGETS),
    )
    ap.add_argument("--skip-sim", action="store_true")
    args = ap.parse_args(argv)
    targets = [float(w) for w in args.targets.split(",") if w]

    print("=" * 72)
    print("CRASH VALIDATION — Stake hash-chain math + WoO comparison + empirical")
    print("=" * 72)

    spec = check_spec_parity()
    for name, ok in spec["checks"].items():
        print(f"[spec]  {name}: {'PASS' if ok else 'FAIL'}")
    print(f"[spec]  -> {'PASS' if spec['pass'] else 'FAIL'}")

    table = check_payout_table()
    print(
        "[table] target      P(win) exact    0.99/w          RTP exact   "
        "|dev|      bound"
    )
    for r in table["rows"]:
        print(
            f"[table] {r['target']:<11g} {r['win_probability']:<15.10f} "
            f"{r['win_probability_ideal']:<15.10f} {r['rtp']:<11.8f} "
            f"{r['rtp_dev_from_099']:<10.2e} {r['rtp_quantization_bound']:.2e}"
            f" {'PASS' if r['within_quantization'] else 'FAIL'}"
        )
    print(
        f"[table] worst |RTP - 0.99| = {table['worst_rtp_dev_from_099']:.3e} "
        f"(all within the 32-bit quantization bound w/2^32); "
        f"worst rel |P - 0.99/w| = {table['worst_p_rel_dev_from_ideal']:.3e}"
    )
    print(
        f"[table] instant-bust P(crash=1) = "
        f"{table['instant_bust_probability']:.8f} (published ~1%) -> "
        f"{'PASS' if table['pass'] else 'FAIL'}"
    )

    chain = check_chain_mechanics()
    print(
        f"[chain] 10,001-hash chain: terminating reachable="
        f"{chain['terminating_reachable']}, per-game verification steps ok="
        f"{chain['verification_steps_ok']}, streamed simulator bit-identical "
        f"to scalar play={chain['stream_bit_identical_to_scalar']} -> "
        f"{'PASS' if chain['pass'] else 'FAIL'}"
    )

    woo = check_woo_comparison(targets)
    print(
        "[woo]   COMPARISON ONLY (documented, not a target): WoO analyzes "
        "SmartSoft's JetX — 97% RTP / 3% edge, tick-based with 3% instant "
        "runway crash — vs Stake Crash 99% RTP / 1% edge, pre-committed "
        "salted hash chain."
    )
    print("[woo]   target    Stake P(win)  Stake RTP   JetX P(win)   JetX RTP")
    for r in woo["comparison_rows"]:
        jp = f"{r['jetx_p_win']:.8f}" if r["jetx_p_win"] is not None else "n/a"
        jr = f"{r['jetx_rtp']:.2f}" if r["jetx_rtp"] is not None else "n/a"
        print(
            f"[woo]   {r['target']:<9g} {r['stake_p_win']:<13.8f} "
            f"{r['stake_rtp']:<11.6f} {jp:<13} {jr}"
        )
    print(
        f"[woo]   shared shape P = RTP/w and flat edge: "
        f"{'PASS' if woo['pass'] else 'FAIL'} (numeric gap ~2pp is the "
        f"different published game, as expected)"
    )

    if args.skip_sim:
        bulk_sim = {"targets": [], "pass": True, "skipped": True}
        chain_sim = {"targets": [], "pass": True, "skipped": True}
        print("[sim]   skipped (--skip-sim)")
    else:
        bulk_sim = run_empirical_bulk(targets, args.rounds)
        chain_sim = run_empirical_chain(targets, args.chain_rounds)

    overall = bool(
        spec["pass"] and table["pass"] and chain["pass"] and woo["pass"]
        and bulk_sim["pass"] and chain_sim["pass"]
    )
    summary = {
        "game": "crash",
        "overall_pass": overall,
        "spec_parity": {"checks": spec["checks"], "pass": spec["pass"]},
        "payout_table": {
            "worst_rtp_dev_from_099": table["worst_rtp_dev_from_099"],
            "worst_p_rel_dev_from_ideal": table["worst_p_rel_dev_from_ideal"],
            "instant_bust_probability": table["instant_bust_probability"],
            "n_targets": len(table["rows"]),
            "pass": table["pass"],
        },
        "chain_mechanics": chain,
        "woo_comparison": {
            "woo_reference": woo["woo_reference"],
            "shape_ok": woo["shape_ok"],
            "pass": woo["pass"],
        },
        "empirical_bulk": bulk_sim,
        "empirical_chain": chain_sim,
        "sim_seeds": {
            "server_seed": SIM_SERVER_SEED,
            "client_seed": SIM_CLIENT_SEED,
            "chain_secret_seed": SIM_CHAIN_SECRET,
        },
    }
    print("CRASH_VALIDATION_JSON: " + json.dumps(summary, default=float))
    print(f"OVERALL: {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
