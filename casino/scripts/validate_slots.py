#!/usr/bin/env python3
"""Validate the slots engine against the published references.

1. Payout-for-payout comparison against references/stake/slots.md: the
   Scarab Spin (Sect. 4) AND Tome of Life (Sect. 5) paytables are parsed
   straight out of the reference markdown (13 symbols x match 2/3/4/5,
   scatter row included) and compared cell-for-cell with the engine's
   tables; the published reel geometry (Sect. 3a: 30/30/30/30/41 central
   stops, floor(float * reel)) is checked against both the engine and the
   verified RNG core constant, and the published RTP/edge/free-spin figures
   are re-read from the reference text.

2. WoO Atkins deconstruction (references/woo/slots.md): exact 32^5
   enumeration of the calibrated par sheet must reproduce EVERY published
   aggregate BOTH within half an ULP of its printed precision
   (WOO_ATKINS_TOL) AND — the stronger gate — printing as the exact string
   WoO printed: f"{100*rtp:.3f}" == "97.046", line "63.460", scatter
   "6.976", bonus "26.610", hit frequency "5.45", trigger probability
   "0.011185", E[spins/bonus] "11.259335", E[bonus win] "23.791632".
   (The strips are the deterministic output of scripts/calibrate_slots.py,
   which re-derives and reproduces them byte-for-byte.)

3. Scarab exact analytics: total RTP within half an ULP of the published
   97.84% and printing exactly "97.84" / edge "2.16" (also carried as an
   exact Fraction).  The reconstruction models Stake's published "random
   wilds in the base game" as the calibrated wild-drop overlay over
   descending-ladder strips (scripts/calibrate_slots.py derives every
   constant deterministically; Stake does not publish strips or wild
   frequencies — reference Sect. 7).  Par-sheet shape gates: counts
   monotone non-increasing in 5-of-a-kind pay on every reel,
   Spearman(pay, total count) <= -0.9 with the wild on ZERO strip stops,
   no two reels sharing a count vector, per-reel count cv >= 0.4,
   full-round SD inside the published slot band 5.18-13.45, and the
   no-wild base game's any-line hit frequency in the neighbourhood of the
   only published 20-line figure (Cleopatra 35.88%).  The factorized
   analytics' no-wild component is cross-checked against the brute-force
   30^4*41 stop enumeration (exact Fraction equality on first moments).

4. Empirical check: 10M+ provably-fair rounds per model on the vectorized
   BulkRng stream (one nonce per round; triggered rounds resolve their free
   spins from the same nonce's continuing byte stream, bit-identical to the
   scalar verifier path); empirical RTP must land within 3 SE of the exact
   value.

Prints a human-readable report plus a machine-readable JSON line prefixed
``SLOTS_VALIDATION_JSON:``.  Exit code 0 iff every gate passes.

Usage:
    python scripts/validate_slots.py [--rounds N] [--models atkins,scarab]
                                     [--skip-sim]
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from spinquest_sim import rng as sq_rng  # noqa: E402
from spinquest_sim.games.slots import (  # noqa: E402
    SCARAB_COUNTS,
    SCARAB_LINE_PAYS,
    SCARAB_SCATTER,
    SCARAB_SCATTER_PAYS,
    SCARAB_SHAPE_GATES,
    SCARAB_STRIPS,
    SCARAB_SYMBOLS,
    SCARAB_WILD,
    STAKE_SCARAB_PRINTED,
    STAKE_SCARAB_PUBLISHED,
    STAKE_SCARAB_RTP_TOL,
    TOME_SYMBOLS,
    WOO_ATKINS_PRINTED,
    WOO_ATKINS_PUBLISHED,
    WOO_ATKINS_TOL,
    WOO_CLEOPATRA_HIT_20LINE,
    WOO_SLOT_SD_BAND,
    SlotMachine,
    atkins_machine,
    scarab_machine,
)
from spinquest_sim.rng import BulkRng  # noqa: E402

STAKE_MD = _ROOT / "references" / "stake" / "slots.md"
WOO_MD = _ROOT / "references" / "woo" / "slots.md"

# Deterministic campaign seeds (verifiable: hash committed in the output).
SIM_SERVER_SEED = (
    "5107a5bc10f56de3ba7e0b6194b0da967d1d7913b2fc8b5ac33e5c47a8691c2d"
)
SIM_CLIENT_SEED = "spinquest-slots-validation"


# ---------------------------------------------------------------------------
# 1. Stake reference parsing + payout-for-payout comparison
# ---------------------------------------------------------------------------

_ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([\d.]+|[––-])\s*\|"
                     r"\s*([\d.]+|[––-])\s*\|\s*([\d.]+|[––-])\s*\|"
                     r"\s*([\d.]+|[––-])\s*\|\s*$")


def _parse_section_table(text: str, start_pat: str, end_pat: str
                         ) -> Dict[str, Tuple[Optional[float], ...]]:
    m = re.search(start_pat, text)
    if not m:
        raise SystemExit(f"cannot find section {start_pat!r} in {STAKE_MD}")
    section = text[m.end():]
    e = re.search(end_pat, section)
    if e:
        section = section[: e.start()]
    rows: Dict[str, Tuple[Optional[float], ...]] = {}
    for line in section.splitlines():
        mm = _ROW_RE.match(line.strip())
        if not mm:
            continue
        name = mm.group(1).strip()
        if name.lower() in ("symbol", "---", ""):
            continue
        vals = []
        for g in mm.groups()[1:]:
            vals.append(None if g in ("–", "-", "–") else float(g))
        rows[name] = tuple(vals)
    return rows


def check_stake_paytables() -> Dict[str, object]:
    text = STAKE_MD.read_text(encoding="utf-8")
    result: Dict[str, object] = {"tables": [], "pass": True}
    specs = [
        ("scarab_spin", r"## 4\. Scarab Spin", r"\n---", SCARAB_SYMBOLS,
         "King Tut \\(Wild\\)", "Scarab Beetle Scatter"),
        ("tome_of_life", r"## 5\. Tome of Life", r"\n---", TOME_SYMBOLS,
         "Tome of Life \\(Wild\\)", "Healer \\(Scatter\\)"),
    ]
    for name, start, end, symbols, _w, _s in specs:
        ref_rows = _parse_section_table(text, start, end)
        mismatches: List[str] = []
        cells = 0
        # engine rows keyed by the model's symbol names, in published order
        for idx in range(11):
            eng_name = symbols[idx]
            row = ref_rows.get(_ref_name(eng_name, ref_rows))
            if row is None:
                mismatches.append(f"missing symbol row {eng_name!r}")
                continue
            for pos, k in enumerate((2, 3, 4, 5)):
                cells += 1
                mine = SCARAB_LINE_PAYS[idx].get(k)
                if mine != row[pos]:
                    mismatches.append(f"{eng_name} match-{k}: engine {mine} "
                                      f"!= reference {row[pos]}")
        # wild row
        wild_key = _ref_name(symbols[11], ref_rows)
        wild_row = ref_rows.get(wild_key)
        for pos, k in enumerate((2, 3, 4, 5)):
            cells += 1
            mine = SCARAB_LINE_PAYS[11].get(k)
            if wild_row is None or mine != wild_row[pos]:
                mismatches.append(f"wild match-{k}: engine {mine} != "
                                  f"reference {wild_row}")
        # scatter row
        sc_key = _ref_name(symbols[12], ref_rows)
        sc_row = ref_rows.get(sc_key)
        for pos, k in enumerate((2, 3, 4, 5)):
            cells += 1
            mine = SCARAB_SCATTER_PAYS.get(k)
            if sc_row is None or mine != sc_row[pos]:
                mismatches.append(f"scatter match-{k}: engine {mine} != "
                                  f"reference {sc_row}")
        ok = not mismatches
        result["tables"].append({
            "table": name, "cells_compared": cells,
            "rows_parsed": len(ref_rows), "mismatches": mismatches,
            "pass": ok,
        })
        result["pass"] = result["pass"] and ok
        print(f"[stake] {name}: {cells} cells vs reference "
              f"({len(ref_rows)} rows parsed) — "
              f"{'ok' if ok else 'MISMATCH: ' + '; '.join(mismatches)}")

    # published game-event geometry (Sect. 3a) and headline figures
    geom_ok = ("The first 4 reels have a length of 30 possible outcomes, "
               "whilst the last reel has 41") in text
    eng_geom = tuple(scarab_machine().reel_lengths)
    rng_geom = tuple(sq_rng.SCARAB_SPIN_REELS)
    geometry_pass = geom_ok and eng_geom == (30, 30, 30, 30, 41) == rng_geom
    rtp_quoted = "97.84%" in text and "2.16" in text
    fs_quoted = "15 bonus free spins" in text
    wilds_quoted = "random wilds in the base game" in text
    maxwin_quoted = "10,000" in text
    result["geometry"] = {
        "reference_text_found": geom_ok,
        "engine_reels": list(eng_geom),
        "rng_core_reels": list(rng_geom),
        "published_rtp_9784_found": rtp_quoted,
        "published_15_free_spins_found": fs_quoted,
        "published_random_wilds_found": wilds_quoted,
        "published_max_win_found": maxwin_quoted,
        "pass": (geometry_pass and rtp_quoted and fs_quoted
                 and wilds_quoted and maxwin_quoted),
    }
    result["pass"] = result["pass"] and bool(result["geometry"]["pass"])
    print(f"[stake] geometry 30/30/30/30/41 (engine==reference==rng core): "
          f"{'ok' if geometry_pass else 'MISMATCH'}; RTP 97.84%/edge 2.16% "
          f"quoted: {rtp_quoted}; 15 free spins quoted: {fs_quoted}; "
          f"'random wilds in the base game' quoted: {wilds_quoted}; "
          f"10,000x max win quoted: {maxwin_quoted}")
    return result


def _ref_name(engine_name: str, ref_rows: Dict[str, Tuple]) -> str:
    """Engine symbol name -> reference row name (the reference writes the
    scatter rows without parentheses)."""
    if engine_name in ref_rows:
        return engine_name
    stripped = engine_name.replace("(", "").replace(")", "")
    for cand in (stripped, engine_name.split(" (")[0]):
        if cand in ref_rows:
            return cand
    for k in ref_rows:
        if k.replace("(", "").replace(")", "") == stripped:
            return k
    return engine_name


# ---------------------------------------------------------------------------
# 2 + 3. Exact enumeration vs published figures
# ---------------------------------------------------------------------------

def check_atkins_enumeration() -> Tuple[Dict[str, object], object]:
    woo_text = WOO_MD.read_text(encoding="utf-8")
    # confirm the published figures we are gating on still sit in the
    # reference verbatim
    quoted = {
        "97.046%": "total return", "63.460%": "line pays",
        "6.976%": "scatter pay", "26.610%": "bonus",
        "0.011185": "trigger probability", "11.259335": "expected spins",
        "23.791632": "expected bonus win", "5.45%": "hit frequency",
        "33,554,432": "32^5 outcomes",
    }
    missing = [q for q in quoted if q not in woo_text]
    if missing:
        print(f"[woo]   WARNING: figures not found verbatim: {missing}")

    machine = atkins_machine()
    ex = machine.enumerate_exact()
    rows = []
    ok_all = not missing
    key_map = {
        "line_return": "line_return", "scatter_return": "scatter_return",
        "bonus_return": "bonus_return", "total_rtp": "rtp",
        "hit_frequency": "hit_frequency",
        "p_bonus_trigger": "p_bonus_trigger",
        "expected_bonus_spins": "expected_bonus_spins",
        "expected_bonus_win": "expected_bonus_win",
    }
    for name, key in key_map.items():
        mine = float(ex[key])
        pub = WOO_ATKINS_PUBLISHED[name]
        tol = WOO_ATKINS_TOL[name]
        _, scale, spec, want = WOO_ATKINS_PRINTED[name]
        printed = format(scale * mine, spec)
        ok = abs(mine - pub) <= tol and printed == want
        ok_all = ok_all and ok
        rows.append({"figure": name, "published": pub, "enumerated": mine,
                     "diff": mine - pub, "tol": tol,
                     "printed": printed, "printed_expected": want,
                     "pass": ok})
        print(f"[woo]   {name:22s} published {pub:<12} enumerated "
              f"{mine:.9f} diff {mine - pub:+.2e} (tol {tol:.0e}) "
              f"prints {printed!r} (want {want!r}) "
              f"{'ok' if ok else 'FAIL'}")
    assert ex["outcomes"] == 32 ** 5
    print(f"[woo]   exact enumeration over {ex['outcomes']:,} outcomes in "
          f"{ex['elapsed_s']:.1f}s; std_per_unit={ex['std_per_unit']:.4f}")
    return ({"figures": rows, "outcomes": int(ex["outcomes"]),
             "std_per_unit": float(ex["std_per_unit"]),
             "verbatim_figures_missing": missing, "pass": ok_all}, machine)


def _spearman(x, y):
    import numpy as np

    def ranks(a):
        a = np.asarray(a, dtype=np.float64)
        order = np.argsort(a, kind="stable")
        r = np.empty(len(a))
        srt = a[order]
        i = 0
        while i < len(a):
            j = i
            while j + 1 < len(a) and srt[j + 1] == srt[i]:
                j += 1
            r[order[i:j + 1]] = (i + j) / 2.0 + 1.0
            i = j + 1
        return r
    rx, ry = ranks(x), ranks(y)
    rx -= rx.mean()
    ry -= ry.mean()
    return float((rx * ry).sum()
                 / math.sqrt((rx ** 2).sum() * (ry ** 2).sum()))


def check_scarab_enumeration() -> Tuple[Dict[str, object], object]:
    import numpy as np

    machine = scarab_machine()
    ex = machine.enumerate_exact()
    rtp = float(ex["rtp"])
    pub = STAKE_SCARAB_PUBLISHED["rtp"]
    ok = abs(rtp - pub) <= STAKE_SCARAB_RTP_TOL
    printed = {}
    for fig, (key, scale, spec, want) in STAKE_SCARAB_PRINTED.items():
        got = format(scale * float(ex[key]), spec)
        printed[fig] = {"printed": got, "expected": want,
                        "pass": got == want}
        ok = ok and got == want
    print(f"[stake] scarab exact RTP {rtp:.10f} "
          f"(= {ex['rtp_fraction']}) vs published {pub} "
          f"(diff {rtp - pub:+.2e}, tol {STAKE_SCARAB_RTP_TOL:.0e}) "
          f"prints {printed['rtp']['printed']!r}/"
          f"{printed['house_edge']['printed']!r} (want '97.84'/'2.16') "
          f"{'ok' if ok else 'FAIL'}; "
          f"P(trigger)={float(ex['p_bonus_trigger']):.6f}, "
          f"E[spins/bonus]={ex['expected_bonus_spins']:.3f}, "
          f"P(wild drop)={float(ex['overlay']['fire_prob']):.6f}")

    # --- par-sheet shape gates (the round-4 must-pass set) ---
    sd = float(ex["std_per_unit"])
    lo_sd, hi_sd = WOO_SLOT_SD_BAND
    sd_ok = lo_sd <= sd <= hi_sd
    ladder_ok = all(all(SCARAB_COUNTS[r][i] >= SCARAB_COUNTS[r][i + 1]
                        for i in range(10)) for r in range(5))
    wild_off = all(SCARAB_WILD not in strip for strip in SCARAB_STRIPS)
    count_vecs = [tuple(strip.count(s) for s in range(13))
                  for strip in SCARAB_STRIPS]
    distinct_ok = len(set(count_vecs)) == 5
    cvs = []
    for strip in SCARAB_STRIPS:
        v = np.array([strip.count(s) for s in range(13)], dtype=np.float64)
        cvs.append(float(v.std() / v.mean()))
    cv_ok = all(c >= SCARAB_SHAPE_GATES["per_reel_cv_min"] for c in cvs)
    pays = [SCARAB_LINE_PAYS[s][5] for s in range(12)]
    totals = [sum(SCARAB_COUNTS[r][s] for r in range(5)) for s in range(11)]
    totals.append(sum(strip.count(SCARAB_WILD) for strip in SCARAB_STRIPS))
    rho = _spearman(pays, totals)
    rho_ok = rho <= -SCARAB_SHAPE_GATES["spearman_abs_min"]

    # --- brute-force cross-check of the no-wild component + base hit ---
    base = SlotMachine(
        name="scarab_base", symbols=SCARAB_SYMBOLS, strips=SCARAB_STRIPS,
        line_pays=SCARAB_LINE_PAYS, wild=SCARAB_WILD, scatter=SCARAB_SCATTER,
        scatter_pays=SCARAB_SCATTER_PAYS, scatter_pay_basis="line",
        free_spins=15, free_spin_multiplier=1)
    bex = base.enumerate_exact()
    comp = ex["components"]["base"]
    xcheck_ok = (comp["line_return"] == bex["line_return"]
                 and comp["hit_frequency"] == bex["hit_frequency"]
                 and ex["p_bonus_trigger"] == bex["p_bonus_trigger"]
                 and ex["scatter_return"] == bex["scatter_return"])
    h0 = float(bex["any_line_hit_frequency"])
    hit_ok = abs(h0 - WOO_CLEOPATRA_HIT_20LINE) < 0.15

    shape_ok = (sd_ok and ladder_ok and wild_off and distinct_ok and cv_ok
                and rho_ok and xcheck_ok and hit_ok)
    ok = ok and shape_ok
    print(f"[stake] scarab shape: SD {sd:.4f} in [{lo_sd}, {hi_sd}] "
          f"{'ok' if sd_ok else 'FAIL'}; ladder monotone "
          f"{'ok' if ladder_ok else 'FAIL'}; "
          f"Spearman(pay, count) {rho:+.4f} <= -0.9 "
          f"{'ok' if rho_ok else 'FAIL'}; wild on strips: "
          f"{'none (ok)' if wild_off else 'FAIL'}; distinct reel count "
          f"vectors {'ok' if distinct_ok else 'FAIL'}; per-reel cv "
          f"{['%.3f' % c for c in cvs]} >= 0.4 {'ok' if cv_ok else 'FAIL'}")
    print(f"[stake] scarab base game (no drop): any-line hit {h0:.4f} vs "
          f"published Cleopatra 20-line 35.88% "
          f"{'ok' if hit_ok else 'FAIL'}; per-line hit "
          f"{float(bex['hit_frequency']):.6f}; factorized-vs-brute-force "
          f"cross-check (30^4*41 outcomes, {bex['elapsed_s']:.1f}s): "
          f"{'EXACT MATCH' if xcheck_ok else 'MISMATCH'}")
    return ({"rtp": rtp, "rtp_fraction": str(ex["rtp_fraction"]),
             "published": pub, "diff": rtp - pub,
             "tol": STAKE_SCARAB_RTP_TOL, "printed": printed,
             "std_per_unit": sd, "sd_band": [lo_sd, hi_sd],
             "shape": {"sd_in_band": sd_ok, "ladder_monotone": ladder_ok,
                       "spearman_pay_count": rho, "spearman_ok": rho_ok,
                       "wild_on_strips": not wild_off,
                       "distinct_reel_count_vectors": distinct_ok,
                       "per_reel_cv": cvs, "cv_ok": cv_ok,
                       "base_any_line_hit": h0, "base_hit_ok": hit_ok,
                       "factorized_vs_brute_force_exact": xcheck_ok},
             "wild_drop": {
                 "fire_prob": float(ex["overlay"]["fire_prob"]),
                 "tile_prob": float(ex["overlay"]["tile_prob"]),
                 "floats_per_spin": ex["overlay"]["floats_per_spin"]},
             "pass": ok}, machine)


# ---------------------------------------------------------------------------
# 4. Empirical simulation
# ---------------------------------------------------------------------------

def run_empirical(machines: Dict[str, object], n_rounds: int
                  ) -> Dict[str, object]:
    out: Dict[str, object] = {"configs": [], "pass": True}
    for name, machine in machines.items():
        bulk = BulkRng(server_seed=SIM_SERVER_SEED,
                       client_seed=f"{SIM_CLIENT_SEED}-{name}",
                       nonce_start=0)
        print(f"[sim]   {name}: {n_rounds:,} provably-fair rounds ...")
        sim = machine.simulate(n_rounds, bulk=bulk, progress=True)
        ok = bool(sim["within_3se"])
        out["pass"] = out["pass"] and ok
        row = {
            "model": name, "n_rounds": n_rounds,
            "empirical_rtp": sim["rtp"], "analytic_rtp": sim["analytic_rtp"],
            "empirical_std": sim["std_per_unit"],
            "analytic_std": sim["analytic_std_per_unit"],
            "se": sim["se_rtp"], "z": sim["z_score"], "within_3se": ok,
            "n_triggered": sim["n_triggered"],
            "n_bonus_spins": sim["n_bonus_spins"],
            "rounds_per_sec": sim["rounds_per_sec"],
            "elapsed_s": sim["elapsed_s"],
            "server_seed_hash": sim["verification"]["server_seed_hash"],
            "nonce_range": list(sim["verification"]["nonce_range"]),
        }
        out["configs"].append(row)
        print(f"[sim]   {name}: rtp {sim['rtp']:.6f} vs exact "
              f"{sim['analytic_rtp']:.6f}  z={sim['z_score']:+.3f}  "
              f"sd {sim['std_per_unit']:.3f} (exact "
              f"{sim['analytic_std_per_unit']:.3f})  "
              f"{sim['rounds_per_sec']:,.0f} rounds/s  "
              f"{'ok' if ok else 'FAIL (outside 3 SE)'}")
    return out


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rounds", type=int, default=10_000_000,
                    help="empirical rounds per model (default 10M)")
    ap.add_argument("--models", type=str, default="atkins,scarab")
    ap.add_argument("--skip-sim", action="store_true")
    args = ap.parse_args()

    print("=== slots validation ===")
    stake = check_stake_paytables()
    woo, atkins = check_atkins_enumeration()
    scarab_chk, scarab = check_scarab_enumeration()

    wanted = [m.strip() for m in args.models.split(",") if m.strip()]
    machines = {}
    if "atkins" in wanted:
        machines["atkins"] = atkins
    if "scarab" in wanted:
        machines["scarab"] = scarab
    if args.skip_sim:
        sim = {"configs": [], "pass": True, "skipped": True}
        print("[sim]   skipped (--skip-sim)")
    else:
        sim = run_empirical(machines, args.rounds)

    overall = bool(stake["pass"] and woo["pass"] and scarab_chk["pass"]
                   and sim["pass"])
    summary = {
        "game": "slots",
        "overall_pass": overall,
        "stake_paytables": stake,
        "woo_atkins_enumeration": woo,
        "scarab_enumeration": scarab_chk,
        "empirical": sim,
        "sim_seeds": {
            "server_seed": SIM_SERVER_SEED,
            "client_seed_prefix": SIM_CLIENT_SEED,
        },
    }
    print("SLOTS_VALIDATION_JSON: " + json.dumps(summary, default=float))
    print(f"OVERALL: {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
