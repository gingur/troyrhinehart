#!/usr/bin/env python3
"""Validate the Roulette engine against the published references.

1. Payout-for-payout comparison against Stake's published table
   (references/stake/roulette.md, section 5): the reference markdown table is
   PARSED and every row's odds, total-return multiplier, coverage and win
   probability are compared against the engine.  The red/black color lists
   are parsed and compared verbatim, and the pocket mapping
   floor(float * 37) is spot-verified scalar-vs-bulk.

2. Wizard-of-Odds SD cross-check (references/woo/roulette.md): every bet
   type's analytic SD is checked to 1e-12 against the closed form of WoO's
   stated formula sqrt(E[X^2] - EV^2), which for coverage c on the
   single-zero wheel is SD = (36/37) * sqrt((37-c)/c) — even money
   sqrt(1368)/37 = 0.9996347, straight up 216/37 = 5.8378378.  The
   reference file's derived straight-up cell prints "5.837800", which
   disagrees with its own formula in the 5th decimal (WoO's double-zero
   figure 5.762617 is 6dp-correct, so 6 dp is the convention): that cell is
   a reference-side rounding slip, reported as such — the gate requires the
   engine to match the FORMULA exactly and the reference cell within 5e-5,
   with the discrepancy printed, not hidden behind asymmetric rounding.

3. Analytic gate: every one of the 157 legal bets (the full European
   catalogue incl. zero trios and first four) has exact RTP 36/37
   (97.2973%, house edge 2.7027% ~ published 2.70%).

4. Provably-fair stream + settlement robustness: pinned verifier vector,
   bulk == scalar agreement, and rejection of out-of-range pockets (a
   negative pocket must raise, never wrap to pocket 36 and pay).

5. Empirical gate, two statistically honest layers over one campaign of
   10M+ provably-fair spins (one nonce per spin, every spin verifiable
   against the scalar path):

   a. THE STATED BAR — each of the 13 bet types, settled through the
      engine's PUBLIC ``payouts_for_pockets`` path over the full campaign,
      must land within 3 SE of 97.30% (SE = analytic per-type SD / sqrt(N)).

   b. FAMILY GATE — all 157 individual bets must land within the
      Sidak-corrected bound for a 157-test family at family alpha = 0.0027
      (|z| <= ~4.30, computed at runtime from scipy.stats.norm).  A bare
      3-SE gate over 157 near-independent tests fails ~1 run in 3 on any
      honest seed (E[offenders] = 157 * 0.0027 = 0.42); the count of bets
      outside 3 SE is reported against that expectation as information,
      not gated.  This removes the previous version's dependence on a
      lucky committed seed: the default seed is reproducible but NOT
      load-bearing — pass ``--fresh-seed`` to prove it on a random one.

   Plus a chi-square uniformity check of the 37 pocket counts at the true
   99.99% quantile (scipy.stats.chi2.isf(1e-4, 36) = 76.36, not the
   mislabeled 79.0 of earlier rounds), and a first-chunk cross-check that
   the fast bincount settlement used for the 157-bet family agrees
   bet-for-bet with the public settlement path.

Prints a human-readable report plus a machine-readable JSON line prefixed
``ROULETTE_VALIDATION_JSON:``.  That line is ALWAYS emitted, exactly once —
even if a gate crashes, and even on bad command-line arguments — so a
caller parsing the output always gets a verdict.  Exit code 0 iff every
gate passes (2 on internal/usage error).

Hardened (round 3): no bare ``assert`` on the validation path (they vanish
under ``python -O``); reference parsing raises ``ValidationError`` with the
exact unparsed piece; the server seed is syntax-checked (64-char hex); the
empirical gate refuses < 10,000,000 rounds unless ``--allow-short`` is
passed (the bar is "10M+ spins"); every gate is bookkept independently so
one gate's failure cannot mask or fake another's.

Hardened (round 4): the verdict line survives argparse errors (SystemExit
is caught); the empirical gates are seed-honest as described above; the
stated 13-type bar runs through the public settlement API; statistical
thresholds are computed from scipy, not hand-copied.

Usage:
    python scripts/validate_roulette.py [--rounds N] [--seed HEX64]
                                        [--fresh-seed] [--client SEED]
                                        [--skip-sim] [--allow-short]
"""

from __future__ import annotations

import argparse
import json
import math
import re
import secrets
import sys
import time
import traceback
from fractions import Fraction
from pathlib import Path
from typing import Dict, List

import numpy as np
from scipy.stats import chi2 as chi2_dist
from scipy.stats import norm

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from spinquest_sim import rng as sq_rng                      # noqa: E402
from spinquest_sim.games import roulette as rl               # noqa: E402
from spinquest_sim.games.roulette import Roulette            # noqa: E402
from spinquest_sim.rng import BulkRng                        # noqa: E402

STAKE_MD = _ROOT / "references" / "stake" / "roulette.md"
WOO_MD = _ROOT / "references" / "woo" / "roulette.md"

# Deterministic default campaign seed: any 64-hex server seed passes the
# gates below (they are family-wise corrected, so no seed is load-bearing);
# this one is fixed only so the reference validation run is exactly
# reproducible.  Use --fresh-seed to run on a random seed.
DEFAULT_SERVER_SEED = (
    "5f70b1435a4b8e2f6d3c0a9184e7d2c5b8a1f4e7d0c3b6a9582e1f4c7d0a3b69"
)
DEFAULT_CLIENT_SEED = "spinquest-roulette-validation"

N_BETS = 157            # full European catalogue (incl. zero trios + first four)
MIN_EMPIRICAL_ROUNDS = 10_000_000
# Family-wise empirical gate: same family error rate as a single two-sided
# 3-sigma test (alpha = 0.0026998), Sidak-corrected across the 157 bets.
FAMILY_ALPHA = 2.0 * float(norm.sf(3.0))


class ValidationError(RuntimeError):
    """A reference file could not be parsed / an internal invariant broke.

    Raised instead of bare ``assert`` so the checks survive ``python -O``
    and so the crash path still emits the machine-readable verdict line.
    """


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


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
    _require(
        set(rows) == set(_STAKE_ROW_MAP),
        f"Stake payout table parse incomplete: got rows {sorted(rows)}, "
        f"expected {sorted(_STAKE_ROW_MAP)} from {STAKE_MD}",
    )
    reds = re.search(r"^- Red: ([\d, ]+)$", text, re.M)
    blacks = re.search(r"^- Black: ([\d, ]+)$", text, re.M)
    he = re.search(r"house edge \*\*(\d+\.\d+)%\*\*, RTP \*\*(\d+\.\d+)%\*\*", text)
    _require(bool(reds), f"failed to parse '- Red:' color list from {STAKE_MD}")
    _require(bool(blacks), f"failed to parse '- Black:' color list from {STAKE_MD}")
    _require(bool(he), f"failed to parse house edge/RTP header from {STAKE_MD}")
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
    parts = text.split("Bet (single-zero)")
    _require(len(parts) >= 2, f"'Bet (single-zero)' table missing from {WOO_MD}")
    section = parts[1]
    even = re.search(r"Any even-money bet \| ([\d.]+)", section)
    single = re.search(r"Single number \| ([\d.]+)", section)
    _require(bool(even), f"failed to parse even-money SD from {WOO_MD}")
    _require(bool(single), f"failed to parse single-number SD from {WOO_MD}")
    return {"even_money": float(even.group(1)), "straight": float(single.group(1))}


def check(passed: bool, label: str, detail: str, failures: List[str]) -> None:
    print(f"  [{'PASS' if passed else 'FAIL'}] {label}: {detail}")
    if not passed:
        failures.append(f"{label}: {detail}")


def _hex64(value: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise argparse.ArgumentTypeError(
            "server seed must be a 64-character hex string"
        )
    return value.lower()


def _positive_int(value: str) -> int:
    n = int(value)
    if n <= 0:
        raise argparse.ArgumentTypeError("--rounds must be a positive integer")
    return n


def closed_form_sd(coverage: int) -> float:
    """WoO per-unit SD, closed form for the single-zero wheel:
    SD = sqrt(M^2 p (1-p)) with M = 36/c, p = c/37  ==  (36/37)*sqrt((37-c)/c).
    """
    return 36.0 / 37.0 * math.sqrt((37.0 - coverage) / coverage)


def run(args: argparse.Namespace, summary: Dict[str, object],
        failures: List[str]) -> None:
    """All validation gates.  Appends to ``failures``/``summary`` in place so
    a crash partway through still leaves everything gathered so far for the
    guaranteed verdict line printed by :func:`main`."""
    # ------------------------------------------------------------------
    print("=" * 72)
    print("GATE 1 — payout-for-payout vs references/stake/roulette.md")
    print("=" * 72)
    prior = len(failures)
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
    summary["gates"]["stake_payout_table"] = len(failures) == prior
    summary["max_payout_diff"] = max_payout_diff

    # ------------------------------------------------------------------
    print("=" * 72)
    print(f"GATE 2 — analytic RTP/edge, all {N_BETS} legal bets "
          "(full European catalogue)")
    print("=" * 72)
    prior = len(failures)
    bets = [(bt, sel, Roulette(bt, sel)) for bt, sel in rl.all_bets()]
    breakdown: Dict[str, int] = {}
    for bt, _sel, _e in bets:
        breakdown[bt] = breakdown.get(bt, 0) + 1
    bad = [
        (bt, sel) for bt, sel, e in bets
        if e.rtp_exact != Fraction(36, 37)
        or e.multiplier_exact != Fraction(36, e.coverage)
    ]
    check(
        len(bets) == N_BETS and not bad, "exact RTP",
        f"{len(bets)} bets ({breakdown['straight']} straight, "
        f"{breakdown['split']} split, {breakdown['street']} street "
        f"(incl. 2 zero trios), {breakdown['corner']} corner (incl. first "
        f"four), {breakdown['line']} line, 3 dozen, 3 column, 6 even-money), "
        f"all RTP = 36/37 = {float(Fraction(36, 37)):.6%}, house edge "
        f"{1 / 37:.6%} (published {stake['house_edge_pct']}% / "
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
    summary["n_bets"] = len(bets)
    summary["analytic_rtp"] = 36 / 37
    summary["analytic_house_edge"] = 1 / 37

    # ------------------------------------------------------------------
    print("=" * 72)
    print("GATE 3 — per-bet SD vs references/woo/roulette.md")
    print("=" * 72)
    prior = len(failures)
    woo = parse_woo_reference()
    # Closed form of WoO's formula for EVERY bet type, to 1e-12.
    sd_bad = [
        t for t in rl.BET_TYPES
        if abs(table[t]["std_per_unit"] - closed_form_sd(table[t]["coverage"]))
        > 1e-12
    ]
    even_sd = Roulette("red").std_per_unit
    straight_sd = Roulette("straight", 17).std_per_unit
    check(
        not sd_bad, "WoO formula sqrt(E[X^2]-EV^2), closed form "
        "(36/37)*sqrt((37-c)/c), all 13 types",
        f"even {even_sd:.7f} (= sqrt(1368)/37), straight {straight_sd:.7f} "
        f"(= 216/37 = {216 / 37:.7f}); max |diff| <= 1e-12"
        + (f"; MISMATCH {sd_bad}" if sd_bad else ""),
        failures,
    )
    # Printed reference figures.  The even-money cell 0.999635 is 6dp-exact.
    # The straight-up cell prints 5.837800 while the reference's OWN formula
    # gives 216/37 = 5.8378378 — a 5th-decimal rounding slip in the derived
    # reference cell (WoO's published double-zero 5.762617 is 6dp-correct).
    # Gate: engine == formula (above) AND |engine - ref cell| < 5e-5, with
    # the discrepancy reported, not hidden.
    straight_ref_diff = abs(straight_sd - woo["straight"])
    check(
        round(even_sd, 6) == woo["even_money"] and straight_ref_diff < 5e-5,
        "WoO printed figures",
        f"even {even_sd:.6f} == ref {woo['even_money']} (6dp exact); "
        f"straight {straight_sd:.6f} vs ref cell {woo['straight']} "
        f"(|diff| = {straight_ref_diff:.1e}: the ref cell is a 5th-decimal "
        "rounding slip against its own formula 216/37 = 5.8378378)",
        failures,
    )
    sd_table = {t: table[t]["std_per_unit"] for t in rl.BET_TYPES}
    print("  per-type SD/unit:", {t: round(s, 4) for t, s in sd_table.items()})
    summary["gates"]["woo_sd"] = len(failures) == prior
    summary["sd_even_money"] = even_sd
    summary["sd_straight"] = straight_sd
    summary["sd_straight_ref_cell_diff"] = straight_ref_diff
    summary["sd_by_type"] = sd_table

    # ------------------------------------------------------------------
    print("=" * 72)
    print("GATE 4 — provably-fair stream + settlement robustness")
    print("=" * 72)
    prior = len(failures)
    # Pinned verifier vector (same vector the test suite pins): a spin is
    # floor(float * 37) of the first 4-byte float at cursor 0.
    pin_f = sq_rng.generate_floats("a" * 64, "clientseed", 1, 0, 1)[0]
    pin_pocket = sq_rng.roulette_pocket(pin_f)
    check(
        abs(pin_f - 0.4767664363607764) < 1e-15 and pin_pocket == 17,
        "pinned verifier vector",
        f"serverSeed 'a'*64 / clientSeed 'clientseed' / nonce 1 -> float "
        f"{pin_f:.16f} -> pocket {pin_pocket} (expect 0.4767664363607764 -> 17)",
        failures,
    )
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
    # Settlement robustness: out-of-range pockets must raise, never pay.
    # (numpy fancy indexing would silently wrap -1 to pocket 36.)
    robust = []
    for bad_pockets, exc in [
        (np.array([-1]), (ValueError,)),
        (np.array([37]), (ValueError,)),
        (np.array([0.5]), (TypeError,)),
    ]:
        try:
            rl.Roulette("red").payouts_for_pockets(bad_pockets)
            robust.append(f"{bad_pockets!r} settled without error")
        except exc:
            pass
        except Exception as unexpected:  # noqa: BLE001
            robust.append(f"{bad_pockets!r} raised {type(unexpected).__name__}")
    check(
        not robust, "out-of-range settlement rejected",
        "pockets -1 / 37 / 0.5 all raise (no negative-index wraparound "
        "payout)" + ("; " + "; ".join(robust) if robust else ""),
        failures,
    )
    summary["gates"]["stream_agreement"] = len(failures) == prior

    # ------------------------------------------------------------------
    if not args.skip_sim:
        z_family = float(norm.isf((1.0 - (1.0 - FAMILY_ALPHA) ** (1.0 / N_BETS)) / 2.0))
        print("=" * 72)
        print(f"GATE 5 — empirical: {args.rounds:,} provably-fair spins")
        print(f"  bar (a): 13 bet types within 3 SE of 97.30% "
              "(public settlement path)")
        print(f"  bar (b): all {N_BETS} bets within the Sidak family bound "
              f"|z| <= {z_family:.3f} (family alpha = {FAMILY_ALPHA:.5f})")
        print("=" * 72)
        prior = len(failures)
        if args.rounds < MIN_EMPIRICAL_ROUNDS and not args.allow_short:
            check(
                False, "round count",
                f"--rounds {args.rounds:,} is below the required "
                f"{MIN_EMPIRICAL_ROUNDS:,} (the bar is 10M+ spins; pass "
                "--allow-short for a quick smoke run)",
                failures,
            )
        rng = BulkRng(args.seed, args.client, nonce_start=0)
        print(f"  server_seed: {args.seed}"
              + ("  (FRESH random seed)" if args.fresh_seed else "  (default)"))
        print(f"  server_seed_hash: {rng.server_seed_hash}")
        print(f"  client_seed: {rng.client_seed}  nonce range: "
              f"[0, {args.rounds})")
        canonical = {bt: Roulette(*rl._CANONICAL[bt]) for bt in rl.BET_TYPES}
        counts = np.zeros(rl.POCKETS, dtype=np.int64)
        pay_totals = {bt: 0.0 for bt in rl.BET_TYPES}
        crosscheck_bad: List[str] = []
        chunk = 2_000_000
        done = 0
        t0 = time.perf_counter()
        first_chunk = True
        while done < args.rounds:
            step = min(chunk, args.rounds - done)
            pockets = rng.roulette_pockets(step)
            chunk_counts = np.bincount(pockets, minlength=rl.POCKETS)
            counts += chunk_counts
            # Stated bar settles through the PUBLIC settlement API.
            for bt, eng in canonical.items():
                pay_totals[bt] += float(eng.payouts_for_pockets(pockets).sum())
            if first_chunk:
                # Cross-check: the fast bincount settlement used for the
                # 157-bet family must agree bet-for-bet with the public path.
                for bt, sel, eng in bets:
                    fast = int(chunk_counts[sorted(eng.covered)].sum())
                    public = int(
                        np.count_nonzero(eng.payouts_for_pockets(pockets))
                    )
                    if fast != public:
                        crosscheck_bad.append(f"{bt} {sel}: {fast} != {public}")
                first_chunk = False
            done += step
            rate = done / (time.perf_counter() - t0)
            print(f"  {done:,}/{args.rounds:,} spins ({rate:,.0f}/s)",
                  flush=True)
        elapsed = time.perf_counter() - t0
        n = args.rounds
        _require(
            int(counts.sum()) == n,
            f"internal: pocket counts sum {int(counts.sum())} != rounds {n}",
        )
        check(
            not crosscheck_bad, "settlement cross-check",
            f"bincount settlement == public payouts_for_pockets for all "
            f"{len(bets)} bets on the first chunk"
            + ("; MISMATCH " + "; ".join(crosscheck_bad[:5])
               if crosscheck_bad else ""),
            failures,
        )

        # --- (a) THE STATED BAR: 13 bet types, public path, 3 SE ----------
        print(f"  {'type':10s} {'RTP':>10s} {'z':>7s} {'SE(RTP)':>9s} "
              f"{'emp SD':>8s} {'ana SD':>8s}")
        type_stats: Dict[str, Dict[str, float]] = {}
        worst_type = {"z": 0.0, "type": None, "rtp": None}
        n_type_fail = 0
        for bt, eng in canonical.items():
            rtp_emp = pay_totals[bt] / n
            se = eng.std_per_unit / math.sqrt(n)
            z = (rtp_emp - eng.rtp) / se
            p_hat = rtp_emp / eng.multiplier
            sd_emp = eng.multiplier * math.sqrt(max(p_hat * (1 - p_hat), 0.0))
            if abs(z) > 3.0:
                n_type_fail += 1
            if abs(z) > abs(worst_type["z"]):
                worst_type = {"z": z, "type": bt, "rtp": rtp_emp}
            type_stats[bt] = {
                "rtp": rtp_emp, "z": z, "se": se, "sd_emp": sd_emp,
                "sd_analytic": eng.std_per_unit,
            }
            print(f"  {bt:10s} {rtp_emp:>10.5%} {z:>+7.2f} {se:>9.6f} "
                  f"{sd_emp:>8.5f} {eng.std_per_unit:>8.5f}")
        check(
            n_type_fail == 0, "empirical 3-SE (13 bet types, stated bar)",
            f"13/13 types within 3 SE over {n:,} spins via "
            f"payouts_for_pockets; worst {worst_type['type']} "
            f"z={worst_type['z']:+.2f} RTP {worst_type['rtp']:.5%}",
            failures,
        )

        # --- (b) FAMILY GATE: all 157 bets, Sidak-corrected ---------------
        worst = {"z": 0.0, "bet": None, "rtp": None}
        n_outside_3se = 0
        n_family_fail = 0
        for bt, sel, eng in bets:
            cov_hits = int(counts[sorted(eng.covered)].sum())
            rtp_emp = cov_hits / n * eng.multiplier
            se = eng.std_per_unit / math.sqrt(n)
            z = (rtp_emp - eng.rtp) / se
            if abs(z) > 3.0:
                n_outside_3se += 1
            if abs(z) > z_family:
                n_family_fail += 1
                print(f"  [FAIL] {bt} {sel}: RTP {rtp_emp:.6%} z={z:+.2f} "
                      f"(> family bound {z_family:.3f})")
            if abs(z) > abs(worst["z"]):
                worst = {"z": z, "bet": f"{bt} {sel}", "rtp": rtp_emp}
        expected_outside = N_BETS * FAMILY_ALPHA
        print(f"  bets outside plain 3 SE: {n_outside_3se} "
              f"(expected ~{expected_outside:.2f} of {N_BETS} honest tests; "
              "informational, not gated)")
        check(
            n_family_fail == 0,
            f"empirical family gate ({N_BETS} bets, |z| <= {z_family:.3f})",
            f"{N_BETS - n_family_fail}/{N_BETS} bets inside the Sidak bound; "
            f"worst {worst['bet']} z={worst['z']:+.2f} RTP {worst['rtp']:.5%}",
            failures,
        )

        # --- pocket uniformity --------------------------------------------
        chi2_threshold = float(chi2_dist.isf(1e-4, 36))
        chi2 = float(((counts - n / 37) ** 2 / (n / 37)).sum())
        zero_freq = counts[0] / n
        print(f"  pocket-0 frequency: {zero_freq:.6f} (expect {1 / 37:.6f}); "
              f"throughput {n / elapsed:,.0f} spins/s, {elapsed:.1f}s")
        check(
            chi2 < chi2_threshold, "uniformity chi-square",
            f"chi2(36 dof) = {chi2:.1f} < {chi2_threshold:.3f} "
            "(true 99.99% quantile via scipy.stats.chi2.isf(1e-4, 36))",
            failures,
        )
        summary["gates"]["empirical_3se_types"] = n_type_fail == 0
        summary["gates"]["empirical_family"] = (
            n_family_fail == 0 and not crosscheck_bad
        )
        summary["gates"]["empirical"] = len(failures) == prior
        summary["empirical"] = {
            "rounds": n,
            "fresh_seed": bool(args.fresh_seed),
            "type_stats": {
                bt: {k: v for k, v in s.items()} for bt, s in type_stats.items()
            },
            "worst_type": worst_type["type"],
            "worst_type_z": worst_type["z"],
            "worst_bet": worst["bet"],
            "worst_bet_z": worst["z"],
            "n_outside_3se_of_157": n_outside_3se,
            "expected_outside_3se": expected_outside,
            "family_z_bound": z_family,
            "chi2_36dof": chi2,
            "chi2_threshold": chi2_threshold,
            "pocket0_freq": zero_freq,
            "rounds_per_sec": n / elapsed,
            "server_seed_hash": rng.server_seed_hash,
            "client_seed": rng.client_seed,
        }


def main() -> int:
    failures: List[str] = []
    summary: Dict[str, object] = {
        "game": "roulette",
        "gates": {},
        "error": None,
    }
    # The verdict line below is guaranteed: any crash inside run() — and any
    # argparse usage error (SystemExit) — is caught, recorded, and still
    # produces exactly one ROULETTE_VALIDATION_JSON line with passed=false,
    # so a parser always gets a verdict.
    exit_code_on_fail = 1
    try:
        ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
        ap.add_argument("--rounds", type=_positive_int,
                        default=MIN_EMPIRICAL_ROUNDS,
                        help="empirical spins (default 10M; the bar is 10M+)")
        ap.add_argument("--seed", type=_hex64, default=None,
                        help="server seed (64-char hex; default: the "
                             "documented reproducible seed)")
        ap.add_argument("--fresh-seed", action="store_true",
                        help="use a fresh random server seed (proves no seed "
                             "is load-bearing; the seed is printed for "
                             "reproduction)")
        ap.add_argument("--client", default=DEFAULT_CLIENT_SEED,
                        help="client seed")
        ap.add_argument("--skip-sim", action="store_true",
                        help="skip the empirical 10M-spin gate")
        ap.add_argument("--allow-short", action="store_true",
                        help="permit --rounds below 10M (smoke runs only; "
                             "the official gate requires 10M+)")
        args = ap.parse_args()
        if args.fresh_seed and args.seed is not None:
            ap.error("--fresh-seed and --seed are mutually exclusive")
        if args.seed is None:
            args.seed = (secrets.token_hex(32) if args.fresh_seed
                         else DEFAULT_SERVER_SEED)
        summary["rounds_requested"] = args.rounds if not args.skip_sim else 0
        summary["server_seed"] = args.seed
        run(args, summary, failures)
    except SystemExit as exc:                     # argparse error/usage exit
        if exc.code in (0, None):
            return 0                              # --help
        summary["error"] = f"usage error (argparse exit {exc.code})"
        failures.append(summary["error"])
        exit_code_on_fail = 2
    except Exception as exc:                      # noqa: BLE001 — verdict must survive
        summary["error"] = f"{type(exc).__name__}: {exc}"
        failures.append(f"internal error: {summary['error']}")
        traceback.print_exc()
        exit_code_on_fail = 2

    ok = not failures and summary["error"] is None
    summary["passed"] = ok
    summary["failures"] = failures
    print("=" * 72)
    print(f"OVERALL: {'PASS' if ok else 'FAIL'} "
          f"({len(failures)} failure(s))")
    print("ROULETTE_VALIDATION_JSON:" + json.dumps(summary, default=str))
    return 0 if ok else exit_code_on_fail


if __name__ == "__main__":
    sys.exit(main())
