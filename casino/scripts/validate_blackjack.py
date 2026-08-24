#!/usr/bin/env python3
"""Validate the Blackjack engine against the published references.

1. Payout-for-payout comparison against Stake's published table
   (references/stake/blackjack.md, section 4): the three published payout
   rows (standard win 1:1 -> 2.00 total, blackjack 3:2 -> 2.50 total,
   insurance 2:1 -> 3x stake) are PARSED from the reference markdown and
   compared against the engine's configuration; the 52-entry CARDS index
   table (section 3) is parsed row-for-row and compared against
   spinquest_sim.rng.CARDS and the engine's blackjack CARD_VALUES; the
   published cursor reservation of 13 is checked; Stake's headline
   "Edge: 0.57%" is parsed and reported (Stake does not publish the dealer
   rules that produce it — it matches WoO's classic 6-deck S17 benchmark
   0.573%, not the infinite-deck math of the actual dealing procedure).

2. Analytic gate vs Wizard of Odds (references/woo/blackjack.md): the
   infinite-deck expected-return figure (house edge 0.511734%, the rule set
   S17 / DAS / resplit non-aces to 4 hands / aces once / no surrender that
   this engine adopts for everything Stake leaves unpublished) is parsed
   and the engine's EXACT analytic house edge must reproduce it to
   ANALYTIC_EDGE_TOL = 5e-7 — half the last digit WoO publishes (measured
   residual -3.6e-9).  The analytic per-unit SD must be within 0.02 of
   WoO's published ~1.15.

3. Empirical gate: 10M+ provably-fair basic-strategy rounds on the
   vectorized BulkRng stream (deterministic default seed, ONE nonce per
   round, every round bit-replayable on the scalar path — spot-verified for
   the first 200 nonces).  The empirical house edge must land within 3 SE
   of BOTH the WoO figure and the engine's own analytic edge
   (SE = analytic SD / sqrt(N)); the empirical per-unit SD must be within
   0.01 of WoO's published ~1.15 AND within 0.005 of the engine's exact
   analytic SD; and the |net| > 6 tail (4-hand rounds with doubles,
   analytic P ~ 1.13e-5) must be populated consistently with the exact
   distribution — a structural check no +-6-capped engine can pass.

Hardened contract: the machine-readable JSON line prefixed
``BLACKJACK_VALIDATION_JSON:`` is ALWAYS emitted, exactly once, even when
reference parsing or the engine itself blows up (then with
``all_pass: false`` and an ``error`` field).  Exit code 0 iff every gate
passes; 1 on gate failure; 2 on crash.  Reference parsing raises real
exceptions (never bare ``assert``, so ``python -O`` cannot skip the
checks) and every parsed figure is sanity-bounded before it is used as a
gate target.  The 10M-round empirical bar is itself a recorded gate: a
smaller ``--rounds`` smoke run FAILS that gate unless ``--allow-small``
is passed (which records it as an explicitly waived non-gate).

Usage:
    python scripts/validate_blackjack.py [--rounds N] [--seed HEX64]
                                         [--client SEED] [--skip-sim]
                                         [--allow-small]
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from pathlib import Path
from typing import Dict, List

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from spinquest_sim import rng as sq_rng                      # noqa: E402
from spinquest_sim.games import blackjack as bj_mod          # noqa: E402
from spinquest_sim.games.blackjack import (                  # noqa: E402
    CARD_VALUES,
    INSURANCE_PAYS,
    Blackjack,
)
from spinquest_sim.rng import BulkRng                        # noqa: E402

STAKE_MD = _ROOT / "references" / "stake" / "blackjack.md"
WOO_MD = _ROOT / "references" / "woo" / "blackjack.md"

# Deterministic default campaign seed (any 64-hex server seed works; this
# one is fixed so the reference validation run is exactly reproducible).
DEFAULT_SERVER_SEED = (
    "9c41ad2b7e6f05d8c3a1b49e2f7d60c5a8b31f4e7d09c6b3a5821e4f7c0d3a96"
)
DEFAULT_CLIENT_SEED = "spinquest-blackjack-validation"

ANALYTIC_EDGE_TOL = 5e-7      # engine exact edge vs WoO 0.511734%: half
                              # the last published digit (measured -3.6e-9)
SD_ANALYTIC_TOL = 0.02        # analytic SD vs WoO's published ~1.15
SD_EMPIRICAL_WOO_TOL = 0.01   # empirical SD vs WoO's published ~1.15
                              # (+5 SE(s), see below; WoO rounds to 1.15)
SD_EMPIRICAL_AN_TOL = 0.005   # empirical SD vs engine exact analytic SD
                              # (floor; widened to 5 SE(s) for small N)
SCALAR_SPOT_CHECK = 200       # nonces replayed scalar vs the bulk stream
MIN_CAMPAIGN_ROUNDS = 10_000_000  # the empirical bar is 10M+ rounds


class ReferenceParseError(RuntimeError):
    """A published figure could not be parsed (or fails sanity bounds)."""


def _require(cond: bool, msg: str) -> None:
    """assert-like guard that survives ``python -O`` and names the field."""
    if not cond:
        raise ReferenceParseError(msg)


def _fail(checks: List[Dict[str, object]], name: str, detail: str) -> None:
    checks.append({"check": name, "pass": False, "detail": detail})
    print(f"  FAIL  {name}: {detail}")


def _ok(checks: List[Dict[str, object]], name: str, detail: str = "") -> None:
    checks.append({"check": name, "pass": True, "detail": detail})
    print(f"  ok    {name}" + (f": {detail}" if detail else ""))


# ---------------------------------------------------------------------------
# reference parsing
# ---------------------------------------------------------------------------

def parse_stake_reference(text: str) -> Dict[str, object]:
    """Pull the published payouts, edge/RTP and CARDS table from the md."""
    out: Dict[str, object] = {}

    # Payout table rows (section 4).
    m = re.search(
        r"Beat the dealer with a standard hand\s*\|\s*(\d+):(\d+)\s*\|\s*"
        r"([\d.]+)", text
    )
    _require(m is not None, "standard-win payout row not found in stake md")
    out["standard_odds"] = (int(m.group(1)), int(m.group(2)))
    out["standard_total"] = float(m.group(3))

    m = re.search(
        r"Beat the dealer with Blackjack[^|]*\|\s*(\d+):(\d+)\s*\|\s*"
        r"([\d.]+)", text
    )
    _require(m is not None, "blackjack payout row not found in stake md")
    out["bj_odds"] = (int(m.group(1)), int(m.group(2)))
    out["bj_total"] = float(m.group(3))

    m = re.search(r"Insurance bet wins[^|]*\|\s*(\d+):(\d+)\s*\|\s*(\d+)", text)
    _require(m is not None, "insurance payout row not found in stake md")
    out["ins_odds"] = (int(m.group(1)), int(m.group(2)))
    out["ins_total"] = float(m.group(3))

    # Headline edge / RTP (section 5).
    m = re.search(r'"Edge:\s*([\d.]+)%"', text)
    _require(m is not None, "published edge not found in stake md")
    out["stake_edge"] = float(m.group(1)) / 100.0
    m = re.search(r"return to player percentage of \*\*([\d.]+)%\*\*", text)
    _require(m is not None, "published RTP not found in stake md")
    out["stake_rtp"] = float(m.group(1)) / 100.0

    # 52-entry CARDS index table (section 3): rows "| 0 | ♦2 | 13 | ♥5 |..."
    cards: Dict[int, str] = {}
    for row in re.findall(r"^\|(?:\s*\d+\s*\|\s*[♦♥♠♣][0-9JQKA]+\s*\|)+\s*$",
                          text, re.M):
        for idx, card in re.findall(r"(\d+)\s*\|\s*([♦♥♠♣][0-9JQKA]+)", row):
            cards[int(idx)] = card
    _require(len(cards) == 52,
             f"parsed {len(cards)} CARDS entries, expected 52")
    _require(sorted(cards) == list(range(52)),
             "CARDS table indices are not exactly 0..51")
    out["cards"] = [cards[i] for i in range(52)]

    m = re.search(r"curser of (\d+) to generate 52 possible game events", text)
    _require(m is not None, "cursor reservation not found in stake md")
    out["cursor_reservation"] = int(m.group(1))

    # Sanity bounds: a corrupted reference must not become a gate target.
    _require(out["standard_odds"][1] > 0 and out["bj_odds"][1] > 0
             and out["ins_odds"][1] > 0, "zero denominator in payout odds")
    _require(1.0 <= out["standard_total"] <= 3.0
             and 1.0 <= out["bj_total"] <= 3.5
             and 2.0 <= out["ins_total"] <= 4.0,
             "published payout totals out of sane range")
    _require(0.0 < out["stake_edge"] < 0.05,
             f"published edge {out['stake_edge']} out of sane range")
    _require(0.90 < out["stake_rtp"] < 1.0,
             f"published RTP {out['stake_rtp']} out of sane range")
    _require(abs(out["stake_edge"] + out["stake_rtp"] - 1.0) < 5e-4,
             "published edge and RTP are inconsistent")
    _require(1 <= out["cursor_reservation"] <= 64,
             "cursor reservation out of sane range")
    return out


def parse_woo_reference(text: str) -> Dict[str, float]:
    """Pull the infinite-deck edge and headline SD figures from the md."""
    out: Dict[str, float] = {}
    m = re.search(
        r"Infinite deck[^|]*\|\s*\*\*([\d.]+)%\*\*\s*\(player EV", text
    )
    _require(m is not None, "infinite-deck house edge not found in woo md")
    out["infinite_deck_edge"] = float(m.group(1)) / 100.0
    _require(0.001 < out["infinite_deck_edge"] < 0.02,
             f"woo infinite-deck edge {out['infinite_deck_edge']} out of "
             "sane range")
    m = re.search(r"headline\)\s*\|\s*~?[\d.]+\s*\|\s*\*\*([\d.]+)\*\*", text)
    _require(m is not None, "headline SD not found in woo md")
    out["headline_sd"] = float(m.group(1))
    _require(1.0 < out["headline_sd"] < 1.4,
             f"woo headline SD {out['headline_sd']} out of sane range")
    m = re.search(r"Six-deck benchmark \(S17, no DAS, no surrender, no "
                  r"resplit aces\), basic strategy[^|]*\|\s*\*\*([\d.]+)%\*\*",
                  text)
    out["six_deck_benchmark_edge"] = float(m.group(1)) / 100.0 if m else None
    return out


# ---------------------------------------------------------------------------
# gates
# ---------------------------------------------------------------------------

def payout_gate(game: Blackjack, stake: Dict[str, object],
                checks: List[Dict[str, object]]) -> None:
    print("[1] payout-for-payout vs references/stake/blackjack.md")

    a, b = stake["standard_odds"]
    net = a / b
    name = f"standard win {a}:{b} -> total {stake['standard_total']:.2f}"
    if net == 1.0 and stake["standard_total"] == 1.0 + net and \
            game.config()["standard_win_pays"] == net:
        _ok(checks, name, "engine pays net +1 per unit")
    else:
        _fail(checks, name, "engine standard-win payout mismatch")

    a, b = stake["bj_odds"]
    net = a / b
    name = f"blackjack {a}:{b} -> total {stake['bj_total']:.2f}"
    if game.bj_payout == net and stake["bj_total"] == 1.0 + net:
        _ok(checks, name, f"engine pays net +{game.bj_payout} per unit")
    else:
        _fail(checks, name,
              f"engine bj_payout {game.bj_payout} != published {net}")

    a, b = stake["ins_odds"]
    name = f"insurance {a}:{b} -> {stake['ins_total']:.0f}x stake"
    ins_ev = Blackjack.insurance_ev()
    if INSURANCE_PAYS == a / b and stake["ins_total"] == 1.0 + a / b and \
            abs(ins_ev - (-1.0 / 13.0)) < 1e-15:
        _ok(checks, name,
            f"engine EV per insurance unit {ins_ev:+.6f} (= -1/13); "
            "basic strategy declines it")
    else:
        _fail(checks, name, "engine insurance payout mismatch")

    # CARDS index table, entry for entry.
    mismatches = [
        (i, stake["cards"][i], sq_rng.CARDS[i])
        for i in range(52) if stake["cards"][i] != sq_rng.CARDS[i]
    ]
    if not mismatches:
        _ok(checks, "CARDS index table (52 entries)",
            "reference table == spinquest_sim.rng.CARDS, entry for entry")
    else:
        _fail(checks, "CARDS index table (52 entries)",
              f"{len(mismatches)} mismatches, first: {mismatches[0]}")

    # Blackjack values derived from those cards.
    bad = []
    for i in range(52):
        rank = stake["cards"][i][1:]
        want = 10 if rank in ("10", "J", "Q", "K") else (
            11 if rank == "A" else int(rank))
        if int(CARD_VALUES[i]) != want:
            bad.append((i, rank, int(CARD_VALUES[i]), want))
    if not bad:
        _ok(checks, "card values over published index",
            "2-9 pip, tens/faces 10, ace 11 (demotable)")
    else:
        _fail(checks, "card values over published index", f"first: {bad[0]}")

    if sq_rng.CURSOR_INCREMENTS["blackjack"] == stake["cursor_reservation"]:
        _ok(checks, "cursor reservation",
            f"published {stake['cursor_reservation']} digests (52 events)")
    else:
        _fail(checks, "cursor reservation",
              f"engine {sq_rng.CURSOR_INCREMENTS['blackjack']} != "
              f"published {stake['cursor_reservation']}")


def analytic_gate(game: Blackjack, stake: Dict[str, object],
                  woo: Dict[str, float],
                  checks: List[Dict[str, object]]) -> None:
    print("[2] analytic gate vs references/woo/blackjack.md")
    woo_edge = woo["infinite_deck_edge"]
    diff = game.house_edge - woo_edge
    name = f"exact house edge vs WoO infinite deck {woo_edge:.6%}"
    if abs(diff) < ANALYTIC_EDGE_TOL:
        _ok(checks, name,
            f"engine {game.house_edge:.8%} (residual {diff:+.2e} < "
            f"{ANALYTIC_EDGE_TOL:.1e}; exact pending-hand split recursion, "
            f"max_hands={game.max_hands})")
    else:
        _fail(checks, name,
              f"engine {game.house_edge:.8%}, diff {diff:+.2e}")

    name = f"analytic SD vs WoO ~{woo['headline_sd']:.2f}"
    sd_diff = game.std_per_unit - woo["headline_sd"]
    if abs(sd_diff) < SD_ANALYTIC_TOL:
        _ok(checks, name,
            f"engine {game.std_per_unit:.4f} (diff {sd_diff:+.4f})")
    else:
        _fail(checks, name, f"engine {game.std_per_unit:.4f}")

    # Distribution self-consistency (also asserted inside _build).
    dist = game.payout_dist
    mass = float(dist.sum())
    mean = float(dist @ bj_mod._LATTICE)
    p_tail = float(dist[np.abs(bj_mod._LATTICE) > 6.0].sum())
    if abs(mass - 1.0) < 1e-12 and abs(mean - game.ev) < 1e-12 \
            and 0.0 < p_tail < 1e-4:
        _ok(checks, "payout distribution",
            f"mass 1, mean == EV {game.ev:+.6f}, support on half-unit "
            f"lattice [-8, +8]; P(|net|>6) = {p_tail:.3e} (4-hand rounds)")
    else:
        _fail(checks, "payout distribution",
              f"mass {mass}, mean {mean}, P(|net|>6) {p_tail:.3e}")

    # Stake's own headline number — informational context, not a gate:
    # Stake never publishes the dealer rules behind "0.57%", and 0.57%
    # matches WoO's classic 6-deck S17 benchmark (0.573%), not any
    # infinite-deck rule set.
    six = woo.get("six_deck_benchmark_edge")
    print(
        f"  info  Stake publishes edge {stake['stake_edge']:.2%} / RTP "
        f"{stake['stake_rtp']:.2%} with no dealer-rule detail; WoO 6-deck "
        f"S17 benchmark is {six:.3%}; engine infinite-deck analytic edge "
        f"is {game.house_edge:.4%}"
        if six is not None else
        f"  info  Stake publishes edge {stake['stake_edge']:.2%} "
        f"(no rule detail); engine analytic {game.house_edge:.4%}"
    )


def empirical_gate(game: Blackjack, woo: Dict[str, float], n_rounds: int,
                   server_seed: str, client_seed: str,
                   checks: List[Dict[str, object]]) -> Dict[str, object]:
    print(f"[3] empirical gate: {n_rounds:,} provably-fair rounds")
    bulk = BulkRng(server_seed, client_seed, nonce_start=1)
    print(f"  server_seed_hash (commitment): {bulk.server_seed_hash}")
    t0 = time.perf_counter()
    res = game.simulate(n_rounds, bulk=bulk, progress=True)
    elapsed = time.perf_counter() - t0

    # Scalar spot check: first SCALAR_SPOT_CHECK nonces bit-replayed.
    hist = np.asarray(res["payout_hist"], dtype=np.int64)
    lat = np.asarray(res["payout_lattice"])
    spot_bad = 0
    spot_nets = []
    for nonce in range(1, SCALAR_SPOT_CHECK + 1):
        spot_nets.append(game.play_round(server_seed, client_seed, nonce)["net"])
    spot_res = game.simulate(
        SCALAR_SPOT_CHECK,
        bulk=BulkRng(server_seed, client_seed, nonce_start=1, workers=1),
        progress=False, keep_payouts=True,
    )
    spot_bad = int((np.asarray(spot_nets) != spot_res["payouts"]).sum())
    if spot_bad == 0:
        _ok(checks, f"scalar replay of first {SCALAR_SPOT_CHECK} nonces",
            "vectorized payouts identical bit for bit")
    else:
        _fail(checks, f"scalar replay of first {SCALAR_SPOT_CHECK} nonces",
              f"{spot_bad} mismatches")

    emp_edge = res["house_edge"]
    se = res["se_rtp"]
    woo_edge = woo["infinite_deck_edge"]

    z_woo = (woo_edge - emp_edge) / se
    name = f"empirical edge within 3 SE of WoO {woo_edge:.6%}"
    detail = (f"edge {emp_edge:.6%}, SE {se:.3e}, z {z_woo:+.2f}")
    if abs(z_woo) <= 3.0:
        _ok(checks, name, detail)
    else:
        _fail(checks, name, detail)

    z_an = res["z_score"]
    name = "empirical edge within 3 SE of engine analytic"
    detail = (f"analytic {game.house_edge:.6%}, z {z_an:+.2f}")
    if abs(z_an) <= 3.0:
        _ok(checks, name, detail)
    else:
        _fail(checks, name, detail)

    # Asymptotic SE of the SAMPLE standard deviation, from the EXACT 2nd
    # and 4th central moments of the payout distribution:
    #   SE(s) = sqrt((mu4 - sigma^4) / (4 sigma^2 N)).
    # The SD gates are 5-SE gates with the fixed tolerances as floors, so
    # they are exactly as strict at 10M rounds but statistically sound
    # (not N-specific) for any campaign size.
    lat_c = lat - float(game.payout_dist @ lat)
    mu4 = float(game.payout_dist @ lat_c**4)
    sig2 = game.variance_per_unit
    se_sd = math.sqrt(max(mu4 - sig2 * sig2, 0.0) / (4.0 * sig2 * n_rounds))

    woo_sd = woo["headline_sd"]
    sd_diff_woo = res["std_per_unit"] - woo_sd
    tol_woo = max(SD_EMPIRICAL_WOO_TOL, 0.005 + 5.0 * se_sd)  # 1.15 is
    name = f"empirical SD vs WoO published ~{woo_sd:.2f}"     # rounded
    if abs(sd_diff_woo) < tol_woo:
        _ok(checks, name,
            f"empirical {res['std_per_unit']:.4f} (diff {sd_diff_woo:+.5f}, "
            f"tol {tol_woo:.4f})")
    else:
        _fail(checks, name,
              f"empirical {res['std_per_unit']:.4f} (diff {sd_diff_woo:+.5f}"
              f" > tol {tol_woo:.4f})")

    sd_diff = res["std_per_unit"] - game.std_per_unit
    tol_an = max(SD_EMPIRICAL_AN_TOL, 5.0 * se_sd)
    name = f"empirical SD vs engine exact analytic {game.std_per_unit:.4f}"
    if abs(sd_diff) < tol_an:
        _ok(checks, name,
            f"empirical {res['std_per_unit']:.4f} (diff {sd_diff:+.5f}, "
            f"SE(s) {se_sd:.2e}, tol {tol_an:.4f})")
    else:
        _fail(checks, name,
              f"empirical {res['std_per_unit']:.4f} (diff {sd_diff:+.5f} > "
              f"tol {tol_an:.4f})")

    if int(hist.sum()) == n_rounds and \
            abs(float(hist @ lat) / n_rounds - res["mean_net"]) < 1e-9:
        _ok(checks, "payout histogram", "counts sum to N, mean consistent")
    else:
        _fail(checks, "payout histogram", "inconsistent with mean")

    # Structural tail check: 4-hand rounds with doubles put mass beyond
    # +-6 (analytic P ~ 1.13e-5, ~113 rounds in 10M).  Observed count must
    # be Poisson-consistent with the exact distribution and NONZERO — a
    # 3-hand or +-6-capped engine shows a structural zero here (~18 sigma).
    p_tail = float(game.payout_dist[np.abs(lat) > 6.0].sum())
    tail_obs = int(hist[np.abs(lat) > 6.0].sum())
    tail_exp = n_rounds * p_tail
    z_tail = (tail_obs - tail_exp) / math.sqrt(tail_exp) if tail_exp else 0.0
    name = "|net| > 6 tail populated (4-hand rounds with doubles)"
    detail = (f"observed {tail_obs}, expected {tail_exp:.1f} "
              f"(P {p_tail:.3e}), z {z_tail:+.2f}")
    # Nonzero is only a structural requirement once the expectation makes
    # zero impossible for a correct engine (P(0) < 5e-5 at exp >= 10; a
    # +-6-capped engine at the 10M bar shows 0 vs ~113, an 11-sigma zero).
    if tail_exp >= 10.0:
        gate_ok = tail_obs > 0 and abs(z_tail) <= 5.0
    else:
        gate_ok = abs(z_tail) <= 5.0
        detail += " (small campaign: nonzero not required)"
    if gate_ok:
        _ok(checks, name, detail)
    else:
        _fail(checks, name, detail)

    print(
        f"  sim: {n_rounds:,} rounds in {elapsed:,.1f}s "
        f"({res['rounds_per_sec']:,.0f} rounds/s), "
        f"overflow scalar replays: {res['overflow_rounds']}"
    )
    return res


# ---------------------------------------------------------------------------

def _parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rounds", type=int, default=MIN_CAMPAIGN_ROUNDS)
    ap.add_argument("--seed", default=DEFAULT_SERVER_SEED)
    ap.add_argument("--client", default=DEFAULT_CLIENT_SEED)
    ap.add_argument("--skip-sim", action="store_true")
    ap.add_argument(
        "--allow-small", action="store_true",
        help="waive the 10M-round campaign-size gate (dev smoke runs only)",
    )
    args = ap.parse_args(argv)
    if args.rounds < 1:
        ap.error("--rounds must be a positive integer")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", args.seed):
        ap.error("--seed must be a 64-character hex server seed")
    if not args.client or len(args.client) > 256:
        ap.error("--client must be a non-empty seed string (<= 256 chars)")
    return args


def run(args: argparse.Namespace) -> Dict[str, object]:
    """All gates; returns the summary dict (never prints the JSON line)."""
    print("=" * 72)
    print("BLACKJACK VALIDATION  (Stake Original rules, infinite deck)")
    print("=" * 72)

    stake = parse_stake_reference(STAKE_MD.read_text(encoding="utf-8"))
    woo = parse_woo_reference(WOO_MD.read_text(encoding="utf-8"))

    game = Blackjack()
    checks: List[Dict[str, object]] = []

    payout_gate(game, stake, checks)
    analytic_gate(game, stake, woo, checks)

    sim_summary: Dict[str, object] = {}
    if not args.skip_sim:
        # The empirical bar is a recorded gate, not an implicit default:
        # a short smoke run cannot masquerade as the 10M+ campaign.
        name = f"campaign size >= {MIN_CAMPAIGN_ROUNDS:,} rounds"
        if args.rounds >= MIN_CAMPAIGN_ROUNDS:
            _ok(checks, name, f"{args.rounds:,} rounds requested")
        elif args.allow_small:
            print(f"  info  {name}: WAIVED by --allow-small "
                  f"({args.rounds:,} rounds — smoke run, not the bar)")
        else:
            _fail(checks, name,
                  f"only {args.rounds:,} requested (pass --allow-small for "
                  "an explicit smoke run)")
        res = empirical_gate(game, woo, args.rounds, args.seed, args.client,
                             checks)
        sim_summary = {
            "n_rounds": res["n_rounds"],
            "empirical_rtp": res["rtp"],
            "empirical_house_edge": res["house_edge"],
            "empirical_std_per_unit": res["std_per_unit"],
            "se": res["se_rtp"],
            "z_vs_analytic": res["z_score"],
            "overflow_rounds": res["overflow_rounds"],
            "rounds_per_sec": res["rounds_per_sec"],
            "server_seed_hash": res["verification"]["server_seed_hash"],
            "client_seed": args.client,
            "nonce_range": list(res["verification"]["nonce_range"]),
        }

    n_pass = sum(1 for c in checks if c["pass"])
    all_pass = n_pass == len(checks)
    print("-" * 72)
    print(f"RESULT: {n_pass}/{len(checks)} checks passed"
          + ("" if all_pass else "  ***FAILURES***"))

    return {
        "game": "blackjack",
        "all_pass": all_pass,
        "checks": checks,
        "analytic": {
            "rtp": game.rtp,
            "house_edge": game.house_edge,
            "std_per_unit": game.std_per_unit,
            "woo_infinite_deck_edge": woo["infinite_deck_edge"],
            "edge_diff_vs_woo": game.house_edge - woo["infinite_deck_edge"],
            "stake_published_edge": stake["stake_edge"],
        },
        "simulation": sim_summary,
        "config": game.config(),
    }


def main(argv: List[str] | None = None) -> int:
    """Wrapper enforcing the output contract: the JSON summary line is
    ALWAYS printed exactly once, even on crash.  Exit 0 = all gates pass,
    1 = at least one gate failed, 2 = crash (parse error, engine error)."""
    args = _parse_args(argv)
    try:
        summary = run(args)
    except Exception as exc:  # noqa: BLE001 - contract: always emit JSON
        import traceback

        traceback.print_exc()
        summary = {
            "game": "blackjack",
            "all_pass": False,
            "error": f"{type(exc).__name__}: {exc}",
            "checks": [],
        }
        print("BLACKJACK_VALIDATION_JSON: " + json.dumps(summary))
        return 2
    print("BLACKJACK_VALIDATION_JSON: " + json.dumps(summary))
    return 0 if summary["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
