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
   exact Fraction).  The reconstruction puts the King Tut wild ON the
   reel strips ("random wilds in the base game" land from the reels — the
   only mechanism the published 5-floats-per-spin event math permits) and
   the whole model is the 13-column count matrix, derived exactly by
   scripts/calibrate_slots.py (Stake does not publish the strips —
   reference Sect. 7).  Par-sheet shape gates: counts monotone
   non-increasing in 5-of-a-kind pay on every reel, Spearman(pay, total
   count) <= -0.9 with the wild on 1-2 strip stops per reel, the wild's
   own pay row carrying <= 20% of the line return (exact attribution via
   a second LUT with the wild row removed), no two reels sharing a count
   vector, per-reel count cv >= 0.4, full-round SD inside the published
   slot band 5.18-13.45, the any-line hit frequency in the neighbourhood
   of the only published 20-line figure (Cleopatra 35.88%), exactly 5
   floats per spin (== rng.EVENT_COUNTS["scarab_spin"]), and every spin
   (base or free) identically distributed — base-spin return == per-spin
   average return (no fire/non-fire barbell).  The enumeration's first
   moments are cross-checked against an independent count-marginal
   big-integer contraction (exact Fraction equality).

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
    tome_of_life_machine,
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
    fs_quoted = ("15 bonus free spins" in text
                 and "15 free spins are awarded" in text)
    wilds_quoted = "random wilds in the base game" in text
    maxwin_quoted = "10,000" in text
    # the Sect. 5 bonus rule set of the shared math model, verbatim
    cap_quoted = ("Bonus rounds are capped at" in text
                  and "180 free spins" in text and "180 times" in text)
    mult_quoted = ("3x multiplier on winning combos" in text
                   and "except when 5 WILD symbols are spun" in text)
    double_quoted = ("Combinations where WILD symbols are used as another "
                     "symbol pay double") in text
    result["geometry"] = {
        "reference_text_found": geom_ok,
        "engine_reels": list(eng_geom),
        "rng_core_reels": list(rng_geom),
        "published_rtp_9784_found": rtp_quoted,
        "published_15_free_spins_found": fs_quoted,
        "published_180_cap_found": cap_quoted,
        "published_3x_multiplier_found": mult_quoted,
        "published_wild_doubling_found": double_quoted,
        "published_random_wilds_found": wilds_quoted,
        "published_max_win_found": maxwin_quoted,
        "pass": (geometry_pass and rtp_quoted and fs_quoted and cap_quoted
                 and mult_quoted and double_quoted and wilds_quoted
                 and maxwin_quoted),
    }
    result["pass"] = result["pass"] and bool(result["geometry"]["pass"])
    print(f"[stake] geometry 30/30/30/30/41 (engine==reference==rng core): "
          f"{'ok' if geometry_pass else 'MISMATCH'}; RTP 97.84%/edge 2.16% "
          f"quoted: {rtp_quoted}; 15 free spins quoted: {fs_quoted}; "
          f"180-spin bonus cap quoted: {cap_quoted}; 3x multiplier + 5-wild "
          f"exemption quoted: {mult_quoted}; wild-substitution doubling "
          f"quoted: {double_quoted}; 'random wilds in the base game' "
          f"quoted: {wilds_quoted}; 10,000x max win quoted: {maxwin_quoted}")
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
          f"E[spins/bonus]={ex['expected_bonus_spins']:.3f}")

    # --- published event math: exactly 5 floats per spin, verified core ---
    floats_ok = (machine.floats_per_spin == 5
                 == sq_rng.EVENT_COUNTS["scarab_spin"])

    # --- par-sheet shape gates (the round-4/5 must-pass set) ---
    sd = float(ex["std_per_unit"])
    lo_sd, hi_sd = WOO_SLOT_SD_BAND
    sd_ok = lo_sd <= sd <= hi_sd
    ladder_ok = all(all(SCARAB_COUNTS[r][i] >= SCARAB_COUNTS[r][i + 1]
                        for i in range(10)) for r in range(5))
    wild_cap = SCARAB_SHAPE_GATES["wild_max_stops_per_reel"]
    wild_counts = [strip.count(SCARAB_WILD) for strip in SCARAB_STRIPS]
    wild_on_ok = all(1 <= c <= wild_cap for c in wild_counts)
    count_vecs = [tuple(strip.count(s) for s in range(13))
                  for strip in SCARAB_STRIPS]
    counts_match_ok = count_vecs == [tuple(c) for c in SCARAB_COUNTS]
    distinct_ok = len(set(count_vecs)) == 5
    cvs = []
    for strip in SCARAB_STRIPS:
        v = np.array([strip.count(s) for s in range(13)], dtype=np.float64)
        cvs.append(float(v.std() / v.mean()))
    cv_ok = all(c >= SCARAB_SHAPE_GATES["per_reel_cv_min"] for c in cvs)
    pays = [SCARAB_LINE_PAYS[s][5] for s in range(12)]
    totals = [sum(SCARAB_COUNTS[r][s] for r in range(5)) for s in range(11)]
    totals.append(sum(wild_counts))
    rho = _spearman(pays, totals)
    rho_ok = rho <= -SCARAB_SHAPE_GATES["spearman_abs_min"]

    # --- wild-as-itself share of the line return (exact attribution) ---
    pays_nowild = {s: dict(r) for s, r in SCARAB_LINE_PAYS.items()
                   if s != SCARAB_WILD}
    nowild = SlotMachine(
        name="scarab_nowildrow", symbols=SCARAB_SYMBOLS,
        strips=SCARAB_STRIPS, line_pays=pays_nowild, wild=SCARAB_WILD,
        scatter=SCARAB_SCATTER, scatter_pays=SCARAB_SCATTER_PAYS,
        scatter_pay_basis="line", free_spins=15, free_spin_multiplier=3,
        free_spin_cap=180, wild_substitution_double=True,
        wild5_multiplier_exempt=True)
    lr_full, _hit_full = machine.marginal_line_stats()
    lr_nowild, _ = nowild.marginal_line_stats()
    wild_share = float(1 - lr_nowild / lr_full)
    share_ok = wild_share <= SCARAB_SHAPE_GATES["wild_line_return_share_max"]

    # --- independent count-marginal cross-check (exact equality) ---
    xcheck_ok = (lr_full == ex["line_return"]
                 and _hit_full == ex["hit_frequency"])

    # --- no barbell: every spin draws the same reels; free spins differ
    # ONLY by the published 3x multiplier + pure-5-wild exemption ---
    mu = float(ex["base_return"])
    ey, ew = float(ex["e_y"]), float(ex["e_w"])
    rules = SCARAB_SHAPE_GATES["published_bonus_rules"]
    uniform_ok = (SCARAB_SHAPE_GATES["same_reels_every_spin"]
                  and machine.free_spins == rules["free_spins"] == 15
                  and machine.free_spin_cap == rules["free_spin_cap"] == 180
                  and machine.free_spin_multiplier
                  == rules["free_spin_multiplier"] == 3
                  and machine.wild5_multiplier_exempt
                  and machine.wild_substitution_double
                  and ey < ew <= 3.0 * ey + 1e-15
                  and 0.0 <= 3.0 * ey - ew < 1e-3)

    # --- published capped retrigger chain (Sect. 5) ---
    import numpy as _np
    p_trig = float(ex["p_bonus_trigger"])
    e_spins = float(ex["expected_bonus_spins"])
    chain_pmf = ex["chain_pmf"]
    chain_ok = (
        ex["p_chain_exceeds_cap"] == 0.0
        and len(chain_pmf) == machine.free_spin_cap + 1
        and abs(float(_np.sum(chain_pmf)) - 1.0) < 1e-12
        and machine.free_spins <= e_spins
        <= SCARAB_SHAPE_GATES["expected_bonus_spins_max"]
        and p_trig <= SCARAB_SHAPE_GATES["p_trigger_max"]
        and machine.free_spins * p_trig
        <= SCARAB_SHAPE_GATES["chain_load_max"])

    # --- the published paytable carries the return: attribute every win
    # (base and free spins) to the paytable row that pays it ---
    kap = p_trig * e_spins
    line_rows_share = (float(ex["line_return"])
                       + kap * float(ex["bonus_line_return"])) / rtp
    scatter_row_share = (float(ex["scatter_return"])
                         + kap * float(ex["bonus_scatter_return"])) / rtp
    feature_share = float(ex["bonus_return"]) / rtp
    shares_ok = (
        line_rows_share
        >= SCARAB_SHAPE_GATES["line_rows_rtp_share_min"]
        and scatter_row_share
        <= SCARAB_SHAPE_GATES["scatter_row_rtp_share_max"]
        and abs(line_rows_share + scatter_row_share - 1.0) < 1e-9)

    h0 = float(ex["any_line_hit_frequency"])
    hit_ok = abs(h0 - WOO_CLEOPATRA_HIT_20LINE) < 0.15

    shape_ok = (floats_ok and sd_ok and ladder_ok and wild_on_ok
                and counts_match_ok and distinct_ok and cv_ok and rho_ok
                and share_ok and xcheck_ok and uniform_ok and chain_ok
                and shares_ok and hit_ok)
    ok = ok and shape_ok
    print(f"[stake] scarab events: floats/spin "
          f"{machine.floats_per_spin} == published 5 == rng core "
          f"{sq_rng.EVENT_COUNTS['scarab_spin']} "
          f"{'ok' if floats_ok else 'FAIL'}")
    print(f"[stake] scarab shape: SD {sd:.4f} in [{lo_sd}, {hi_sd}] "
          f"{'ok' if sd_ok else 'FAIL'}; ladder monotone "
          f"{'ok' if ladder_ok else 'FAIL'}; "
          f"Spearman(pay, count) {rho:+.4f} <= -0.9 "
          f"{'ok' if rho_ok else 'FAIL'}; wild on strips {wild_counts} "
          f"(1..{wild_cap}/reel) {'ok' if wild_on_ok else 'FAIL'}; "
          f"counts==strips {'ok' if counts_match_ok else 'FAIL'}; distinct "
          f"reel count vectors {'ok' if distinct_ok else 'FAIL'}; per-reel "
          f"cv {['%.3f' % c for c in cvs]} >= 0.4 "
          f"{'ok' if cv_ok else 'FAIL'}")
    print(f"[stake] scarab published bonus rules: 15 spins, cap 180, 3x "
          f"multiplier (pure-5-wild exempt), wild doubling, same reels "
          f"every spin {'ok' if uniform_ok else 'FAIL'}; capped chain: "
          f"P(trigger) {p_trig:.6f} <= "
          f"{SCARAB_SHAPE_GATES['p_trigger_max']}, 15p "
          f"{15 * p_trig:.4f} <= {SCARAB_SHAPE_GATES['chain_load_max']}, "
          f"E[spins/bonus] {e_spins:.3f} <= 180, P(N > 180) = "
          f"{ex['p_chain_exceeds_cap']} (support ends AT the published "
          f"cap; P(N = 180) = {float(ex['p_chain_at_cap']):.5f}) "
          f"{'ok' if chain_ok else 'FAIL'}")
    print(f"[stake] scarab return attribution: paytable line rows "
          f"{line_rows_share:.4f} >= "
          f"{SCARAB_SHAPE_GATES['line_rows_rtp_share_min']} of RTP, "
          f"scatter row {scatter_row_share:.4f} <= "
          f"{SCARAB_SHAPE_GATES['scatter_row_rtp_share_max']} "
          f"{'ok' if shares_ok else 'FAIL'} (round-5 shipped "
          f"25.29%/74.71%); standard split: line "
          f"{float(ex['line_return']):.4f} + scatter "
          f"{float(ex['scatter_return']):.4f} + feature "
          f"{float(ex['bonus_return']):.4f} (share {feature_share:.4f})")
    print(f"[stake] scarab return split: wild-as-itself share of line "
          f"return {wild_share:.4f} <= 0.20 {'ok' if share_ok else 'FAIL'}; "
          f"any-line hit {h0:.4f} vs published Cleopatra 20-line 35.88% "
          f"{'ok' if hit_ok else 'FAIL'}; per-line hit "
          f"{float(ex['hit_frequency']):.6f}; count-marginal vs "
          f"enumeration ({ex['elapsed_s']:.1f}s, 30^4*41 outcomes): "
          f"{'EXACT MATCH' if xcheck_ok else 'MISMATCH'}")
    return ({"rtp": rtp, "rtp_fraction": str(ex["rtp_fraction"]),
             "published": pub, "diff": rtp - pub,
             "tol": STAKE_SCARAB_RTP_TOL, "printed": printed,
             "std_per_unit": sd, "sd_band": [lo_sd, hi_sd],
             "floats_per_spin": machine.floats_per_spin,
             "shape": {"sd_in_band": sd_ok, "ladder_monotone": ladder_ok,
                       "spearman_pay_count": rho, "spearman_ok": rho_ok,
                       "wild_stops_per_reel": wild_counts,
                       "wild_on_strips_ok": wild_on_ok,
                       "counts_match_strips": counts_match_ok,
                       "distinct_reel_count_vectors": distinct_ok,
                       "per_reel_cv": cvs, "cv_ok": cv_ok,
                       "wild_line_return_share": wild_share,
                       "wild_share_ok": share_ok,
                       "any_line_hit": h0, "hit_ok": hit_ok,
                       "published_rules_ok": uniform_ok,
                       "p_trigger": p_trig,
                       "chain_load_15p": 15 * p_trig,
                       "expected_bonus_spins": e_spins,
                       "p_chain_at_cap": float(ex["p_chain_at_cap"]),
                       "p_chain_exceeds_cap": ex["p_chain_exceeds_cap"],
                       "chain_ok": chain_ok,
                       "line_rows_rtp_share": line_rows_share,
                       "scatter_row_rtp_share": scatter_row_share,
                       "feature_share": feature_share,
                       "shares_ok": shares_ok,
                       "marginal_vs_enumeration_exact": xcheck_ok},
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
