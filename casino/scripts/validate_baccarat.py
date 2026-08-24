#!/usr/bin/env python3
"""Validate the Baccarat (punto banco) engine against the published references.

1. Payout-for-payout comparison against Stake's published table
   (references/stake/baccarat.md sec. 5): the reference markdown table is
   PARSED and every row's winnings odds, total-return multiplier and
   published per-bet house edge are compared against the engine (exact
   Fractions for odds/multipliers; the published edges to the 2 decimals
   Stake prints).  The published banker third-card table (sec. 4) is parsed
   row-for-row and compared against BANKER_DRAW_TABLE, and the published
   card mapping floor(float * 52) plus the 6-events / 1-digest budget are
   spot-verified scalar-vs-bulk on the verified RNG core.

2. Wizard-of-Odds cross-check (references/woo/baccarat.md): ALL FIVE
   columns of the published house-edge table (Banker / Player / Tie 8:1 /
   Pair bets 11:1) for every published deck count (8 / 6 / 1 / infinite),
   the 8-deck win probabilities, the published per-unit SDs (Banker 0.93 /
   Player 0.95 / Tie 2.64), the published pair-bet odds (11:1) and the
   8-deck pair RTP (89.64%) are parsed and compared to the engine's EXACT
   analytics — the pair column against the exact rank-level Fractions
   (4D-1)/(52D-1) — rounded to the reference's printed precision.

3. Empirical gate: 10M+ provably-fair 8-deck rounds on the vectorized
   BulkRng stream (deterministic default seed, ONE nonce per round, 6 game
   events per round, every round verifiable against the scalar path).  All
   three bets are settled against the SAME rounds; every bet's empirical
   RTP must land within 3 SE of its exact RTP (SE = analytic per-unit SD /
   sqrt(N)), and every empirical per-unit SD must match WoO's published SD
   to the printed 2 decimals.  The SAME campaign (identical seeds/nonces)
   is then re-audited at RANK granularity (card index // 4, which the
   value-level analytics cannot see): both 11:1 pair side bets must land
   within 3 SE of the exact (4D-1)/(52D-1) win probability, and the rank
   distribution of every one of the 6 dealt positions must pass a 13-bin
   chi-squared uniformity test; a shorter infinite-deck campaign repeats
   the rank audit on Stake's published unlimited-deck mechanism.

Prints a human-readable report plus a machine-readable JSON line prefixed
``BACCARAT_VALIDATION_JSON:``.  Exit code 0 iff every gate passes.

Usage:
    python scripts/validate_baccarat.py [--rounds N] [--seed HEX64]
                                        [--client SEED] [--skip-sim]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
import traceback
from fractions import Fraction
from pathlib import Path
from typing import Dict, List

import numpy as np
from scipy.stats import chi2 as chi2_dist

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from spinquest_sim import rng as sq_rng                      # noqa: E402
from spinquest_sim.games import baccarat as bc               # noqa: E402
from spinquest_sim.games.baccarat import Baccarat            # noqa: E402
from spinquest_sim.rng import BulkRng                        # noqa: E402

STAKE_MD = _ROOT / "references" / "stake" / "baccarat.md"
WOO_MD = _ROOT / "references" / "woo" / "baccarat.md"

CHECKS: List[Dict[str, object]] = []

# Every check() call lands here — a gate that crashes mid-way leaves its
# completed checks in place and adds one explicit FAIL for the crash, so
# the machine-readable summary is emitted no matter what goes wrong.
EXPECTED_MIN_CHECKS_ANALYTIC = 45   # gates 1+2 emit 51 today; floor guards silent skips
EXPECTED_MIN_CHECKS_FULL = 55       # incl. gate 3 (12 more today)


def check(name: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append({"name": name, "pass": bool(ok), "detail": detail})
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""),
          flush=True)
    return bool(ok)


def run_gate(name: str, fn, *args):
    """Run one gate; a raised exception becomes a recorded FAIL instead of
    killing the run before the JSON summary is printed."""
    try:
        return fn(*args)
    except Exception as e:  # noqa: BLE001 — deliberately broad: report, don't die
        traceback.print_exc()
        check(f"gate '{name}' completed without exceptions", False,
              f"{type(e).__name__}: {e}")
        return None


# ---------------------------------------------------------------------------
# 1. Stake reference: payouts, drawing rules, provably-fair mechanics
# ---------------------------------------------------------------------------

def parse_stake_payout_table(text: str) -> Dict[str, Dict[str, object]]:
    """Rows of sec. 5: | Bet | odds | total returned | published edge |."""
    out: Dict[str, Dict[str, object]] = {}
    for m in re.finditer(
        r"^\|\s*(Player|Banker|Tie)\s*\|\s*([\d.]+):1\s*\|\s*([\d.]+)[^|]*\|\s*"
        r"([\d.]+)%\s*\|",
        text,
        re.M,
    ):
        bet, odds, total, edge = m.groups()
        out[bet.lower()] = {
            "odds": Fraction(odds),
            "multiplier": Fraction(total),
            "published_edge_pct": float(edge),
        }
    return out


# Published banker rows (sec. 4) -> the set of player-third-card values the
# bank draws on.  Parsed from the verbatim phrasing.
def parse_stake_banker_rows(text: str) -> Dict[int, List[int]]:
    rows: Dict[int, List[int]] = {}
    # "| 3 | "Bank draws if the player's third card is 0-7 or 9. ..." |"
    for m in re.finditer(
        r"^\|\s*([0-7](?:\s*/\s*\d)*)\s*\|\s*\"Bank (draws|stands)([^|]*)\|",
        text,
        re.M,
    ):
        totals = [int(t) for t in re.findall(r"\d", m.group(1))]
        body = m.group(3)
        if m.group(2) == "stands":
            draw_on: List[int] = []
        elif "all instances" in body:
            draw_on = list(range(10))
        else:
            # "third card is L-H" or "third card is L-H or X"; anything
            # else is a reference-format drift -> drop the row so the
            # per-row comparison FAILS loudly instead of crashing here.
            spans = re.search(r"third card is (\d)\s*-\s*(\d)(?: or (\d))?", body)
            if spans is None:
                continue
            lo, hi = int(spans.group(1)), int(spans.group(2))
            draw_on = list(range(lo, hi + 1))
            if spans.group(3):
                draw_on.append(int(spans.group(3)))
        for t in totals:
            rows[t] = sorted(draw_on)
    return rows


def gate_stake_payouts() -> None:
    print("\n== Gate 1: Stake published payouts & rules (payout-for-payout) ==")
    text = STAKE_MD.read_text(encoding="utf-8")

    table = parse_stake_payout_table(text)
    check("parsed all 3 bet rows from stake/baccarat.md sec.5",
          set(table) == {"player", "banker", "tie"}, str(sorted(table)))
    for bet in bc.BET_TYPES:
        row = table.get(bet, {})
        eng = Baccarat(bet, decks=8)
        check(
            f"{bet}: winnings odds {row.get('odds')}:1 == engine",
            row.get("odds") == bc.PAYOUT_ODDS[bet],
            f"engine {bc.PAYOUT_ODDS[bet]}:1",
        )
        check(
            f"{bet}: total-return multiplier {float(row.get('multiplier', -1)):.2f}"
            " == engine",
            row.get("multiplier") == bc.MULTIPLIERS[bet],
            f"engine {float(bc.MULTIPLIERS[bet]):.2f}",
        )
        check(
            f"{bet}: Stake published edge {row.get('published_edge_pct')}% == "
            "exact 8-deck edge (2 dp)",
            round(100 * eng.house_edge, 2) == row.get("published_edge_pct"),
            f"exact {100 * eng.house_edge:.4f}%",
        )

    # Stake's headline "1.10% overall" is a blended figure whose weighting
    # Stake does not publish — sanity-check only that it sits between the
    # exact banker and player edges (any banker/player mix does).
    m = re.search(r"house edge of just ([\d.]+)% overall", text)
    overall = float(m.group(1)) if m else None
    lo = 100 * Baccarat("banker", 8).house_edge
    hi = 100 * Baccarat("player", 8).house_edge
    check(
        f"Stake overall edge {overall}% lies between exact banker/player edges",
        overall is not None and lo <= overall <= hi,
        f"banker {lo:.4f}% .. player {hi:.4f}%",
    )

    rows = parse_stake_banker_rows(text)
    check("parsed banker third-card rows 0..7", set(rows) == set(range(8)),
          str(sorted(rows)))
    for total in range(8):
        engine_draw_on = sorted(
            v for v in range(10) if bc.BANKER_DRAW_TABLE[total, v]
        )
        check(
            f"banker two-card total {total}: draws on player third card "
            f"{rows.get(total)}",
            rows.get(total) == engine_draw_on,
            f"engine {engine_draw_on}",
        )

    # published card mapping + event budget on the verified RNG core
    ss = hashlib.sha256(b"validate_baccarat spot seed").hexdigest()
    cs = "validate-baccarat"
    ok_map = True
    for nonce in range(200):
        floats = sq_rng.generate_floats(ss, cs, nonce, 0, 6)
        if sq_rng.baccarat_cards(ss, cs, nonce) != [
            math.floor(f * 52) for f in floats
        ]:
            ok_map = False
            break
    check("card mapping floor(float*52) over 200 scalar rounds", ok_map)
    check(
        "6 game events per round, 1 incremental number (1 digest)",
        bc.EVENTS_PER_ROUND == 6
        and sq_rng.EVENT_COUNTS["baccarat"] == 6
        and sq_rng.CURSOR_INCREMENTS["baccarat"] == 1,
    )
    rng = BulkRng(ss, cs, nonce_start=0)
    bulk_cards = rng.baccarat_cards(50)
    ok_bulk = all(
        list(bulk_cards[i]) == sq_rng.baccarat_cards(ss, cs, i) for i in range(50)
    ) and rng.last_nonce_range == (0, 50)
    check("bulk path bit-identical to scalar path, one nonce per round", ok_bulk)

    # tie pushes player/banker (blog quote sec. 4): engine payout table
    tie_code = np.array([2])
    ok_push = (
        Baccarat("player", 8).payouts_for_outcomes(tie_code)[0] == 1.0
        and Baccarat("banker", 8).payouts_for_outcomes(tie_code)[0] == 1.0
    )
    check("tie pushes Player and Banker bets (stake returned)", ok_push)


# ---------------------------------------------------------------------------
# 2. Wizard of Odds cross-check (exact analytics vs published figures)
# ---------------------------------------------------------------------------

def gate_woo_analytics() -> None:
    print("\n== Gate 2: Wizard of Odds published figures vs exact analytics ==")
    text = WOO_MD.read_text(encoding="utf-8")

    # house-edge rows, ALL FIVE columns:
    # | 8 (standard) | **1.06%** | **1.24%** | **14.36%** | 10.36% |
    edges: Dict[str, Dict[str, float]] = {}
    for m in re.finditer(
        r"^\|\s*(8 \(standard\)|6|1|Infinite)\s*\|\s*\**([\d.]+)%\**\s*\|\s*"
        r"\**([\d.]+)%\**\s*\|\s*\**([\d.]+)%\**\s*\|\s*\**([\d.]+)%\**\s*\|",
        text,
        re.M,
    ):
        key = m.group(1).split()[0].lower()
        edges[key] = {
            "banker": float(m.group(2)),
            "player": float(m.group(3)),
            "tie": float(m.group(4)),
            "pair": float(m.group(5)),
        }
    check("parsed WoO house-edge rows incl. pair column (8/6/1/infinite)",
          set(edges) == {"8", "6", "1", "infinite"}
          and all("pair" in row for row in edges.values()),
          str(sorted(edges)))

    deck_map = {"8": 8, "6": 6, "1": 1, "infinite": None}
    for key, decks in deck_map.items():
        nd = 3 if key == "infinite" else 2
        for bet in bc.BET_TYPES:
            pub = edges.get(key, {}).get(bet)
            exact = 100 * Baccarat(bet, decks).house_edge
            check(
                f"WoO {key}-deck {bet} edge {pub}% == exact ({nd} dp)",
                pub is not None and round(exact, nd) == pub,
                f"exact {exact:.4f}%",
            )
        # pair column (rank-level): exact 1 - 12*(4D-1)/(52D-1), 1/13 inf.
        pub = edges.get(key, {}).get("pair")
        exact_frac = bc.pair_house_edge(decks)
        check(
            f"WoO {key}-deck pair-bet (11:1) edge {pub}% == exact "
            f"{exact_frac} (2 dp)",
            pub is not None and round(100 * float(exact_frac), 2) == pub,
            f"exact {100 * float(exact_frac):.4f}% "
            f"[P(pair) = {bc.pair_probability(decks)}]",
        )

    # published pair-bet odds ("Pair bets pay 11:1") and 8-deck pair RTP
    m = re.search(r"Pair bets pay (\d+):1", text)
    check(
        f"WoO pair-bet odds {m.group(1) if m else None}:1 == engine",
        m is not None and Fraction(m.group(1)) == bc.PAIR_PAYOUT_ODDS,
        f"engine {bc.PAIR_PAYOUT_ODDS}:1 (multiplier {float(bc.PAIR_MULTIPLIER):g})",
    )
    m = re.search(r"Pair bets ([\d.]+)%", text)
    check(
        f"WoO 8-deck pair RTP {m.group(1) if m else None}% == exact (2 dp)",
        m is not None
        and round(100 * float(bc.pair_rtp(8)), 2) == float(m.group(1)),
        f"exact {100 * float(bc.pair_rtp(8)):.4f}% = 12 * 31/415",
    )
    # full_payout_table must surface the pair bets (no blank column)
    fpt = bc.full_payout_table(8)
    check(
        "full_payout_table(8) surfaces player_pair & banker_pair analytics",
        {"player_pair", "banker_pair"} <= set(fpt)
        and all(
            fpt[b]["multiplier"] == 12.0
            and round(100 * fpt[b]["house_edge"], 2) == edges["8"]["pair"]
            for b in ("player_pair", "banker_pair")
        ),
        f"rtp {fpt['player_pair']['rtp']:.6f}, "
        f"sd {fpt['player_pair']['std_per_unit']:.4f}",
    )

    # win probabilities (8-deck): "- Banker wins: 45.86%" etc.
    probs = bc.outcome_probabilities(8)
    for name, pat in (
        ("banker", r"Banker wins:\s*([\d.]+)%"),
        ("player", r"Player wins:\s*([\d.]+)%"),
        ("tie", r"Tie:\s*([\d.]+)%"),
    ):
        m = re.search(pat, text)
        pub = float(m.group(1)) if m else None
        exact = 100 * float(probs[name])
        check(
            f"WoO 8-deck P({name}) {pub}% == exact (2 dp)",
            pub is not None and round(exact, 2) == pub,
            f"exact {exact:.4f}%",
        )

    # per-unit SDs: | Banker | **0.93** |
    for bet, pat in (
        ("banker", r"^\|\s*Banker\s*\|\s*\**([\d.]+)\**\s*\|"),
        ("player", r"^\|\s*Player\s*\|\s*\**([\d.]+)\**\s*\|"),
        ("tie", r"^\|\s*Tie\s*\|\s*\**([\d.]+)\**\s*\|"),
    ):
        m = re.search(pat, text, re.M)
        pub = float(m.group(1)) if m else None
        exact = Baccarat(bet, 8).std_per_unit
        check(
            f"WoO {bet} per-unit SD {pub} == exact (2 dp)",
            pub is not None and round(exact, 2) == pub,
            f"exact {exact:.4f}",
        )

    # RTP identity: rtp = 1 - edge, and probabilities sum to exactly 1
    check("P(player)+P(banker)+P(tie) == 1 exactly (8-deck & infinite)",
          sum(bc.outcome_probabilities(8).values()) == 1
          and sum(bc.outcome_probabilities(None).values()) == 1)


# ---------------------------------------------------------------------------
# 3. Empirical gate: 10M+ provably-fair rounds, 3 SE, WoO SDs
# ---------------------------------------------------------------------------

def gate_empirical(n_rounds: int, server_seed: str, client_seed: str) -> Dict[str, object]:
    print(f"\n== Gate 3: empirical — {n_rounds:,} provably-fair 8-deck rounds ==")
    rng = BulkRng(server_seed, client_seed, nonce_start=0)
    print(f"  server_seed_hash (commitment): {rng.server_seed_hash}")
    res = bc.simulate_all_bets(n_rounds, decks=8, bulk=rng, progress=True)
    print(
        f"  {res['n_rounds']:,} rounds in {res['elapsed_s']:.1f}s "
        f"({res['rounds_per_sec']:,.0f} rounds/s); outcomes: "
        + ", ".join(f"{k} {v:,}" for k, v in res["outcome_counts"].items())
    )
    woo_sd = {"banker": 0.93, "player": 0.95, "tie": 2.64}
    for bet in bc.BET_TYPES:
        r = res["bets"][bet]
        check(
            f"{bet}: empirical edge {100 * r['house_edge']:.4f}% within 3 SE of "
            f"exact {100 * r['analytic_house_edge']:.4f}%",
            r["within_3se"],
            f"z = {r['z_score']:+.2f}, SE = {100 * r['se_rtp']:.4f}%",
        )
        # Empirical per-unit SD vs the exact SD, judged against the exact
        # sampling error of a sample SD: Var(s^2) ~= (mu4 - sigma^4)/n, so
        # SE(s) ~= sqrt(mu4 - sigma^4) / (2 sigma sqrt(n)); mu4 computed
        # exactly from the outcome distribution (net result o / 0 / -1).
        # (WoO's printed 0.93 / 0.95 / 2.64 are pinned analytically in
        # Gate 2 — this check ties the SIMULATION to that same exact SD.)
        eng = Baccarat(bet, 8)
        o = float(eng.payout_odds)
        pw, pp = eng.win_probability, eng.push_probability
        pl = 1.0 - pw - pp
        mu = o * pw - pl
        sigma = eng.std_per_unit
        mu4 = pw * (o - mu) ** 4 + pp * mu ** 4 + pl * (-1 - mu) ** 4
        se_sd = math.sqrt(max(mu4 - sigma ** 4, 0.0)) / (
            2 * sigma * math.sqrt(res["n_rounds"])
        )
        check(
            f"{bet}: empirical per-unit SD {r['std_per_unit']:.4f} within 4 SE "
            f"of exact {sigma:.4f} (WoO {woo_sd[bet]})",
            abs(r["std_per_unit"] - sigma) <= 4 * se_sd
            and round(sigma, 2) == woo_sd[bet],
            f"SE(SD) = {se_sd:.5f}",
        )
    # spot-verify 25 random rounds of the campaign against the scalar path
    eng = Baccarat("player", 8)
    codes = {"player": 0, "banker": 1, "tie": 2}
    rng2 = BulkRng(server_seed, client_seed, nonce_start=0)
    sample = bc.deal_rounds(rng2, 25, 8)
    ok = all(
        codes[eng.play_round(server_seed, client_seed, i)["outcome"]] == sample[i]
        for i in range(25)
    )
    check("campaign rounds bit-reproducible from (seed, client, nonce)", ok)

    # ---- rank granularity: audit the SAME campaign at card-index level ----
    # (identical seeds + nonce range -> deal_cards re-deals the very same
    # cards the outcomes above settled; ranks = index // 4 distinguish
    # 10/J/Q/K, which all collapse to value 0 in the outcome analytics.)
    print(f"  rank-level audit of the same {n_rounds:,} rounds "
          "(pair bets 11:1 + rank uniformity):")
    pres = bc.simulate_pairs(
        n_rounds, decks=8,
        bulk=BulkRng(server_seed, client_seed, nonce_start=0), progress=False,
    )
    assert pres["verification"]["nonce_range"] == res["verification"]["nonce_range"]
    for bet in ("player_pair", "banker_pair"):
        r = pres["bets"][bet]
        check(
            f"{bet}: empirical P(pair) {100 * r['win_rate']:.4f}% within 3 SE "
            f"of exact 31/415 = {100 * r['analytic_win_probability']:.4f}%",
            r["within_3se"],
            f"z = {r['z_score']:+.2f}; empirical edge "
            f"{100 * r['house_edge']:.4f}% vs exact "
            f"{100 * r['analytic_house_edge']:.4f}% (WoO 10.36%)",
        )
    pvals = [
        float(chi2_dist.sf(x, pres["rank_chi2_df"]))
        for x in pres["rank_chi2_per_position"]
    ]
    check(
        "rank uniformity (13 ranks x 6 dealt positions): all chi2 p-values "
        "> 1e-4",
        all(p > 1e-4 for p in pvals),
        "chi2(df 12) = "
        + "/".join(f"{x:.1f}" for x in pres["rank_chi2_per_position"])
        + f"; min p = {min(pvals):.4f}; max cell |z| = "
        f"{pres['max_rank_cell_z']:.2f}",
    )
    # pair flags of play_round match the bulk rank path, round for round
    ok = True
    rng3 = BulkRng(server_seed, client_seed, nonce_start=0)
    cards25 = bc.deal_cards(rng3, 25, 8)
    for i in range(25):
        r = eng.play_round(server_seed, client_seed, i)
        ranks = cards25[i] // 4
        if (r["player_pair"], r["banker_pair"]) != (
            bool(ranks[0] == ranks[2]), bool(ranks[1] == ranks[3])
        ) or list(cards25[i]) != r["cards"]:
            ok = False
            break
    check("pair flags & card indices bit-reproducible (scalar vs bulk)", ok)

    # secondary campaign: Stake's published infinite-deck mechanism
    n_inf = max(min(n_rounds // 5, 5_000_000), 1_000_000)
    pres_inf = bc.simulate_pairs(
        n_inf, decks=None,
        bulk=BulkRng(server_seed, client_seed, nonce_start=0), progress=False,
    )
    pvals_inf = [
        float(chi2_dist.sf(x, pres_inf["rank_chi2_df"]))
        for x in pres_inf["rank_chi2_per_position"]
    ]
    check(
        f"infinite-deck rank audit ({n_inf:,} rounds): both pair bets within "
        "3 SE of exact 1/13 and rank chi2 p-values > 1e-4",
        pres_inf["pass"] and all(p > 1e-4 for p in pvals_inf),
        "z = "
        + "/".join(f"{pres_inf['bets'][b]['z_score']:+.2f}"
                   for b in ("player_pair", "banker_pair"))
        + f"; min p = {min(pvals_inf):.4f}; exact edge "
        f"{100 * float(bc.pair_house_edge(None)):.4f}% (WoO 7.69%)",
    )
    res["pairs"] = pres
    res["pairs_infinite"] = pres_inf
    return res


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rounds", type=int, default=10_000_000)
    ap.add_argument(
        "--seed",
        default=hashlib.sha256(b"spinquest baccarat validation 2026-08-24").hexdigest(),
        help="64-char hex server seed (deterministic default)",
    )
    ap.add_argument("--client", default="baccarat-validation")
    ap.add_argument("--skip-sim", action="store_true")
    args = ap.parse_args()

    # fail fast on unusable inputs (clear message, no half-run)
    if args.rounds < 1:
        ap.error(f"--rounds must be >= 1, got {args.rounds}")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", args.seed):
        ap.error("--seed must be a 64-character hex string")
    if not args.client:
        ap.error("--client must be non-empty")

    t0 = time.perf_counter()
    print("Baccarat validation — 8-deck punto banco (Stake payouts, WoO math)",
          flush=True)
    run_gate("stake payouts & rules", gate_stake_payouts)
    run_gate("WoO analytics", gate_woo_analytics)
    sim: Dict[str, object] = {}
    if not args.skip_sim:
        if args.rounds < 10_000_000:
            print(f"  (note: --rounds {args.rounds:,} is below the 10M bar)",
                  flush=True)
        sim = run_gate("empirical", gate_empirical,
                       args.rounds, args.seed, args.client) or {}

    # meta-gates: a silently-skipped block of checks (regex drift, gate
    # crash) must not read as success — require the expected check volume,
    # and never declare a vacuous pass on an empty check list.
    floor = EXPECTED_MIN_CHECKS_ANALYTIC if args.skip_sim else EXPECTED_MIN_CHECKS_FULL
    check(f"check-count floor: ran >= {floor} checks", len(CHECKS) - 1 >= floor,
          f"{len(CHECKS) - 1} substantive checks recorded")
    n_pass = sum(1 for c in CHECKS if c["pass"])
    all_pass = len(CHECKS) > 0 and n_pass == len(CHECKS)
    print(f"\n{'ALL CHECKS PASSED' if all_pass else 'FAILURES PRESENT'}: "
          f"{n_pass}/{len(CHECKS)} in {time.perf_counter() - t0:.1f}s",
          flush=True)

    summary = {
        "game": "baccarat",
        "variant": "punto_banco_8deck",
        "pass": all_pass,
        "checks_passed": n_pass,
        "checks_total": len(CHECKS),
        "failed": [c["name"] for c in CHECKS if not c["pass"]],
    }
    try:
        summary["analytic"] = {
            bet: {
                "rtp": Baccarat(bet, 8).rtp,
                "house_edge": Baccarat(bet, 8).house_edge,
                "std_per_unit": Baccarat(bet, 8).std_per_unit,
                "win_probability": Baccarat(bet, 8).win_probability,
            }
            for bet in bc.BET_TYPES
        } | {
            bet: {
                k: bc.pair_summary(8, bet)[k]
                for k in ("rtp", "house_edge", "std_per_unit",
                          "win_probability")
            }
            for bet in bc.PAIR_BET_TYPES
        }
        summary["empirical"] = {
            "n_rounds": sim.get("n_rounds"),
            "rounds_per_sec": sim.get("rounds_per_sec"),
            "outcome_counts": sim.get("outcome_counts"),
            "bets": {
                bet: {
                    k: sim["bets"][bet][k]
                    for k in ("rtp", "house_edge", "std_per_unit", "z_score",
                              "within_3se")
                }
                for bet in bc.BET_TYPES
            } if sim else None,
            "pair_bets": {
                bet: {
                    k: sim["pairs"]["bets"][bet][k]
                    for k in ("rtp", "house_edge", "win_rate", "z_score",
                              "within_3se")
                }
                for bet in bc.PAIR_BET_TYPES
            } if sim else None,
            "rank_chi2_per_position": sim["pairs"]["rank_chi2_per_position"]
            if sim else None,
            "max_rank_cell_z": sim["pairs"]["max_rank_cell_z"] if sim else None,
            "infinite_deck_rank_audit": {
                "n_rounds": sim["pairs_infinite"]["n_rounds"],
                "pass": sim["pairs_infinite"]["pass"],
            } if sim else None,
            "verification": sim.get("verification"),
        } if sim else None
    except Exception as e:  # noqa: BLE001 — summary must still be emitted
        traceback.print_exc()
        summary["pass"] = all_pass = False
        summary["summary_error"] = f"{type(e).__name__}: {e}"
    line = "BACCARAT_VALIDATION_JSON: " + json.dumps(summary)
    assert json.loads(line.split(": ", 1)[1])["game"] == "baccarat"  # round-trips
    print(line, flush=True)
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
