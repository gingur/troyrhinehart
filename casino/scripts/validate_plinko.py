#!/usr/bin/env python3
"""Validate spinquest_sim.games.plinko against the reference .md ground truth.

Checks, in order:

0. REFPARSE — the reference numbers used below are NOT trusted as
             transcribed: the Stake "Playing Sizes" tables are re-parsed
             from references/stake/plinko.md and the WoO BGAMING RTP grid,
             example pay tables, CryptoGames RTP/SD/pay tables and BetFury
             RTP/pay tables are re-parsed from references/woo/plinko.md;
             each parsed set must equal the constants hardcoded here.
1. STRUCT  — all 27 (risk, rows) configs exist; pocket count == rows + 1;
             tables symmetric.
2. STAKE   — payout-for-payout comparison against every number Stake
             publishes (references/stake/plinko.md section 4): per-config
             destination count, min win, max win for all 27 configs; the
             16/high blog facts (1000x edge, 130x second-to-last); global
             multiplier range 0.2x..1000x.
3. WOO     — full-table anchors from references/woo/plinko.md (8/low and
             16/medium verbatim; 16/high == the 1000x table WoO prints as
             BetFury Red); analytic RTP vs WoO's BGAMING grid: medium+high
             columns must match the printed value exactly at 2 decimals.
             (The captured Low column duplicates the Medium column
             row-for-row; low-risk analytic RTPs are reported with their
             diffs and checked against the page's global 98.91-99.16 band.)
4. XTAB    — the WoO page's OTHER published Plinko math, reproduced through
             Plinko.from_table: all four CryptoGames pay tables must
             hit the printed RTP at 2 decimals AND the printed per-drop
             standard deviation at all 6 printed decimals (0.562711,
             0.517632, 0.464829, 3.678698); BetFury Green + Red must hit
             their printed RTPs; BetFury Blue's printed table is required
             to evaluate to 97.5018% — surfacing the reference page's own
             internal defect (it prints 97.88% beside a table that does
             not evaluate to it).  11 independently published figures.
5. BINOM   — probabilities are exactly C(rows, k)/2^rows and equal Stake's
             own shipped Pascal helper (WoO binomial path methodology).
6. EMPIRICAL — 10,000,000 drops per row count (8..16), every drop on the
             REAL HMAC-SHA256 provably-fair stream (BulkRng, chunked
             floor(float*2) per row) — 90M real rounds total.  The pocket
             depends only on the row count, so each 10M-drop direction
             stream is settled against all three risk tables
             (Plinko.summarize_counts), giving all 27 configs 10M real
             rounds each: |empirical RTP - analytic RTP| < 3 SE,
             SE = std_per_unit/sqrt(N).
7. PROV-FAIR replay — for low/8, medium/16 and high/16: sample rounds of
             the section-6 campaigns bit-reproduced through the scalar
             verifier (engine.play_round), a full first-1000 histogram
             replay, and chunk-size invariance of simulate().
8. MEM     — peak RSS of this whole process stays under the project's
             500 MB chunk budget (the round-4 critic measured 2.5 GB for
             an unchunked 10M-drop campaign; the chunked simulator must
             never come close).

Prints a machine-readable summary (one "CHECK|..." line per check, final
"RESULT|PASS|..." / "RESULT|FAIL|..." line). Exactly one RESULT line is
always printed — even on an unexpected exception, which yields
"RESULT|FAIL|error=..." — and the exit code is 0 iff every check passed.

Usage: validate_plinko.py [--rounds N]
  --rounds  drops per row-count stream for the empirical check (default 10M)
"""

from __future__ import annotations

import argparse
import math
import re
import resource
import sys
import time
import traceback
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from spinquest_sim import rng as sq_rng
from spinquest_sim.games.plinko import (
    MAX_ROWS,
    MIN_ROWS,
    PAYTABLES,
    Plinko,
    RISKS,
    pascal_probabilities,
)

# --- reference data (verbatim from references/stake/plinko.md section 4) ----
STAKE_PLAYING_SIZES = {
    ("low", 8): (9, 0.5, 5.6), ("low", 9): (10, 0.7, 5.6),
    ("low", 10): (11, 0.5, 8.9), ("low", 11): (12, 0.7, 8.4),
    ("low", 12): (13, 0.5, 10), ("low", 13): (14, 0.7, 8.1),
    ("low", 14): (15, 0.5, 7.1), ("low", 15): (16, 0.7, 15),
    ("low", 16): (17, 0.5, 16),
    ("medium", 8): (9, 0.4, 13), ("medium", 9): (10, 0.5, 18),
    ("medium", 10): (11, 0.4, 22), ("medium", 11): (12, 0.5, 24),
    ("medium", 12): (13, 0.3, 33), ("medium", 13): (14, 0.4, 43),
    ("medium", 14): (15, 0.2, 58), ("medium", 15): (16, 0.3, 88),
    ("medium", 16): (17, 0.3, 110),
    ("high", 8): (9, 0.2, 29), ("high", 9): (10, 0.2, 43),
    ("high", 10): (11, 0.2, 76), ("high", 11): (12, 0.2, 120),
    ("high", 12): (13, 0.2, 170), ("high", 13): (14, 0.2, 260),
    ("high", 14): (15, 0.2, 420), ("high", 15): (16, 0.2, 620),
    ("high", 16): (17, 0.2, 1000),
}

# references/woo/plinko.md — full-table anchors and BGAMING RTP grid
WOO_LOW_8 = [5.6, 2.1, 1.1, 1, 0.5, 1, 1.1, 2.1, 5.6]
WOO_MEDIUM_16 = [110, 41, 10, 5, 3, 1.5, 1, 0.5, 0.3,
                 0.5, 1, 1.5, 3, 5, 10, 41, 110]
WOO_BETFURY_RED_16 = [1000, 130, 26, 9, 4, 2, 0.2, 0.2, 0.2,
                      0.2, 0.2, 2, 4, 9, 26, 130, 1000]
WOO_RTP_PCT = {  # (risk, rows) -> printed % (Low column: see caveat above)
    ("low", 8): 98.91, ("low", 9): 99.14, ("low", 10): 98.91,
    ("low", 11): 99.02, ("low", 12): 98.99, ("low", 13): 98.99,
    ("low", 14): 98.99, ("low", 15): 99.00, ("low", 16): 98.99,
    ("medium", 8): 98.91, ("medium", 9): 99.14, ("medium", 10): 98.91,
    ("medium", 11): 99.02, ("medium", 12): 98.99, ("medium", 13): 98.99,
    ("medium", 14): 98.99, ("medium", 15): 99.00, ("medium", 16): 98.99,
    ("high", 8): 99.06, ("high", 9): 99.06, ("high", 10): 99.06,
    ("high", 11): 99.16, ("high", 12): 99.12, ("high", 13): 99.09,
    ("high", 14): 98.98, ("high", 15): 99.03, ("high", 16): 98.98,
}
WOO_BAND = (98.91, 99.16)  # "Range across all 27 configurations"

# references/woo/plinko.md — CryptoGames (16 rows): table, printed RTP %,
# printed per-drop standard deviation (the reference's only SD figures).
WOO_CRYPTOGAMES = {
    "green": ([10, 8, 6, 3, 2, 1.3, 1, 0.8, 0.5, 0.8, 1, 1.3, 2, 3, 6, 8, 10],
              98.37, 0.562711),
    "red": ([20, 7, 5, 3, 2, 1.1, 1, 0.6, 1, 0.6, 1, 1.1, 2, 3, 5, 7, 20],
            98.16, 0.517632),
    "blue": ([50, 8, 3, 2, 1.4, 1.2, 1.1, 1, 0.4, 1, 1.1, 1.2, 1.4, 2, 3, 8, 50],
             98.48, 0.464829),
    "yellow": ([650, 30, 7, 3, 1.5, 1.2, 1, 0.7, 0.7, 0.7, 1, 1.2, 1.5, 3, 7,
                30, 650],
               98.09, 3.678698),
}
# references/woo/plinko.md — BetFury (16 rows): table, printed RTP %.
WOO_BETFURY = {
    "blue": ([16, 5, 2, 1.3, 1.2, 0.2, 1.1, 1.1, 1, 1.1, 1.1, 0.2, 1.2, 1.3,
              2, 5, 16],
             97.88),
    "green": ([110, 41, 10, 5, 2.8, 1.5, 1, 0.5, 0.3, 0.5, 1, 1.5, 2.8, 5, 10,
               41, 110],
              97.88),
    "red": ([1000, 130, 26, 9, 4, 2, 0.2, 0.2, 0.2, 0.2, 0.2, 2, 4, 9, 26,
             130, 1000],
            98.98),
}

N_EMPIRICAL = 10_000_000
REPLAY_CONFIGS = [("low", 8), ("medium", 16), ("high", 16)]
CLIENT_SEED = "validate-plinko"
MEM_BUDGET_MB = 500.0


def _stream_seed(rows: int) -> str:
    """Distinct 64-hex server seed per row-count stream."""
    return f"{rows:02x}9b" * 16

ALL_CONFIGS = [(risk, rows) for risk in RISKS
               for rows in range(MIN_ROWS, MAX_ROWS + 1)]

REFERENCES = Path(__file__).resolve().parents[1] / "references"

failures: list[str] = []
_check_names: set[str] = set()
_checks_run = 0


def check(name: str, ok: bool, detail: str) -> None:
    global _checks_run
    if name in _check_names:  # a duplicated name could mask a failed check
        ok, detail = False, f"DUPLICATE CHECK NAME (was: {detail})"
    _check_names.add(name)
    _checks_run += 1
    print(f"CHECK|{name}|{'PASS' if ok else 'FAIL'}|{detail}", flush=True)
    if not ok:
        failures.append(f"{name}: {detail}")


# --- reference .md parsers (ground truth read straight from the files) ------

def _num(s: str) -> float:
    return float(s.replace(",", "").replace("%", "").strip())


def parse_stake_playing_sizes(text: str) -> dict:
    """The three 'Playing Sizes' tables in references/stake/plinko.md §4:
    rows like `| Low/8 | 9 | 0.5 | 5.6 |` (high table: `1,000`)."""
    out = {}
    for m in re.finditer(
            r"\|\s*(Low|Medium|High)/(\d+)\s*\|\s*(\d+)\s*\|"
            r"\s*([\d.,]+)\s*\|\s*([\d.,]+)\s*\|", text):
        risk, rows, dest, mn, mx = m.groups()
        out[(risk.lower(), int(rows))] = (int(dest), _num(mn), _num(mx))
    return out


def parse_woo(text: str) -> dict:
    """Everything numeric on references/woo/plinko.md, keyed per section."""
    sections = {}
    for name, body in re.findall(r"(?m)^## (.+?)\n(.*?)(?=^## |\Z)",
                                 text, re.S):
        sections[name.split(" ")[0].lower()] = body
    out: dict = {"rtp_grid": {}, "examples": {}, "cryptogames": {},
                 "betfury": {}}
    # BGAMING RTP grid: | 8 | 98.91% | 98.91% | 99.06% |
    bg = sections["bgaming"]
    for m in re.finditer(r"\|\s*(\d+)\s*\|\s*([\d.]+)%\s*\|\s*([\d.]+)%\s*\|"
                         r"\s*([\d.]+)%\s*\|", bg):
        rows = int(m.group(1))
        for i, risk in enumerate(("low", "medium", "high")):
            out["rtp_grid"][(risk, rows)] = _num(m.group(2 + i))
    # BGAMING example tables: `- 8 rows, low risk: 5.6, 2.1, ...`
    for m in re.finditer(r"- (\d+) rows, (\w+) risk:\s*([\d., ]+)", bg):
        out["examples"][(m.group(2), int(m.group(1)))] = [
            _num(x) for x in m.group(3).split(",")]
    # CryptoGames: RTP/SD table rows + `- Green:  10, 8, ...` pay tables
    cg = sections["cryptogames"]
    cg_stats = {m.group(1).lower(): (_num(m.group(2)), float(m.group(3)))
                for m in re.finditer(
                    r"\|\s*(\w+)\s*\|\s*([\d.]+)%\s*\|\s*[\d.]+%\s*\|"
                    r"\s*([\d.]+)\s*\|", cg)}
    for m in re.finditer(r"- (\w+):\s*([\d., ]+)", cg):
        name = m.group(1).lower()
        rtp, sd = cg_stats[name]
        out["cryptogames"][name] = (
            [_num(x) for x in m.group(2).split(",")], rtp, sd)
    # BetFury: RTP table rows + pay tables
    bf = sections["betfury"]
    bf_rtp = {m.group(1).lower(): _num(m.group(2))
              for m in re.finditer(
                  r"\|\s*(\w+)\s*\|\s*([\d.]+)%\s*\|\s*[\d.]+%\s*\|", bf)}
    for m in re.finditer(r"- (\w+):\s*([\d., ]+)", bf):
        name = m.group(1).lower()
        out["betfury"][name] = ([_num(x) for x in m.group(2).split(",")],
                                bf_rtp[name])
    return out


def main(n_empirical: int) -> int:
    t0 = time.time()
    engines = {cfg: Plinko(rows=cfg[1], risk=cfg[0]) for cfg in ALL_CONFIGS}

    # 0. REFPARSE: hardcoded reference constants == the reference .md files --
    stake_md = (REFERENCES / "stake" / "plinko.md").read_text()
    woo_md = (REFERENCES / "woo" / "plinko.md").read_text()
    parsed_sizes = parse_stake_playing_sizes(stake_md)
    check("refparse.stake_playing_sizes",
          parsed_sizes == STAKE_PLAYING_SIZES and len(parsed_sizes) == 27,
          f"parsed={len(parsed_sizes)} rows from references/stake/plinko.md; "
          f"match_hardcoded={parsed_sizes == STAKE_PLAYING_SIZES}")
    woo = parse_woo(woo_md)
    check("refparse.woo_rtp_grid",
          woo["rtp_grid"] == WOO_RTP_PCT and len(woo["rtp_grid"]) == 27,
          f"parsed={len(woo['rtp_grid'])} cells; "
          f"match_hardcoded={woo['rtp_grid'] == WOO_RTP_PCT}")
    check("refparse.woo_example_tables",
          woo["examples"] == {("low", 8): WOO_LOW_8,
                              ("medium", 16): WOO_MEDIUM_16},
          f"parsed={sorted(woo['examples'])}")
    cg_expected = {k: (t, r, s) for k, (t, r, s) in WOO_CRYPTOGAMES.items()}
    check("refparse.woo_cryptogames",
          woo["cryptogames"] == cg_expected,
          f"parsed={sorted(woo['cryptogames'])}; "
          f"match_hardcoded={woo['cryptogames'] == cg_expected}")
    bf_expected = {k: (t, r) for k, (t, r) in WOO_BETFURY.items()}
    check("refparse.woo_betfury",
          woo["betfury"] == bf_expected
          and woo["betfury"]["red"][0] == WOO_BETFURY_RED_16,
          f"parsed={sorted(woo['betfury'])}; "
          f"match_hardcoded={woo['betfury'] == bf_expected}")

    # 1. STRUCT ------------------------------------------------------------
    check("struct.config_count",
          set(PAYTABLES) == set(STAKE_PLAYING_SIZES) and len(PAYTABLES) == 27,
          f"configs={len(PAYTABLES)} expected=27")
    for cfg, eng in engines.items():
        p = eng.payouts
        check(f"struct.{cfg[0]}/{cfg[1]}",
              len(p) == cfg[1] + 1 and bool(np.array_equal(p, p[::-1])),
              f"pockets={len(p)} symmetric={bool(np.array_equal(p, p[::-1]))}")

    # 2. STAKE payout-for-payout ------------------------------------------
    for cfg, (dest, mn, mx) in STAKE_PLAYING_SIZES.items():
        p = engines[cfg].payouts
        ok = (len(p) == dest and float(p.min()) == mn and float(p.max()) == mx)
        check(f"stake.playing_sizes.{cfg[0]}/{cfg[1]}", ok,
              f"dest={len(p)}/{dest} min={p.min():g}/{mn:g} max={p.max():g}/{mx:g}")
    p16h = engines[("high", 16)].payouts
    check("stake.blog.16high_1000x", p16h[0] == p16h[16] == 1000,
          f"edges={p16h[0]:g},{p16h[16]:g}")
    check("stake.blog.16high_130x_second_to_last", p16h[1] == p16h[15] == 130,
          f"second_to_last={p16h[1]:g},{p16h[15]:g}")
    allv = np.concatenate([e.payouts for e in engines.values()])
    check("stake.blog.global_range_0.2_to_1000",
          allv.min() == 0.2 and allv.max() == 1000,
          f"range={allv.min():g}..{allv.max():g}")

    # 3. WOO ---------------------------------------------------------------
    check("woo.table.low/8",
          engines[("low", 8)].payouts.tolist() == WOO_LOW_8,
          str(engines[("low", 8)].payouts.tolist()))
    check("woo.table.medium/16",
          engines[("medium", 16)].payouts.tolist() == WOO_MEDIUM_16,
          str(engines[("medium", 16)].payouts.tolist()))
    check("woo.table.high/16_equals_betfury_red_1000x",
          engines[("high", 16)].payouts.tolist() == WOO_BETFURY_RED_16,
          str(engines[("high", 16)].payouts.tolist()))

    for cfg in ALL_CONFIGS:
        rtp_pct = round(100 * engines[cfg].rtp, 2)
        pub = WOO_RTP_PCT[cfg]
        diff = round(rtp_pct - pub, 2)
        if cfg[0] in ("medium", "high"):
            check(f"woo.rtp.{cfg[0]}/{cfg[1]}", abs(rtp_pct - pub) < 1e-9,
                  f"analytic={rtp_pct:.2f}% woo={pub:.2f}% diff={diff:+.2f}")
        else:
            # WoO's captured Low column duplicates the Medium column
            # row-for-row; hold low-risk to the page's global band instead
            # and report the diff vs the printed (duplicated) figure.
            ok = WOO_BAND[0] - 1e-9 <= rtp_pct <= WOO_BAND[1] + 1e-9
            check(f"woo.rtp.{cfg[0]}/{cfg[1]}_band", ok,
                  f"analytic={rtp_pct:.2f}% band={WOO_BAND[0]}-{WOO_BAND[1]} "
                  f"woo_printed={pub:.2f}%(=medium column) diff={diff:+.2f}")

    # 4. XTAB: WoO CryptoGames + BetFury published RTP/SD via from_table ---
    for name, (table, pub_rtp, pub_sd) in WOO_CRYPTOGAMES.items():
        eng = Plinko.from_table(table, label=f"cryptogames-{name}")
        rtp_pct = round(100 * eng.rtp, 2)
        sd6 = round(eng.std_per_unit, 6)
        check(f"xtab.cryptogames_{name}.rtp", abs(rtp_pct - pub_rtp) < 1e-9,
              f"analytic={rtp_pct:.2f}% woo={pub_rtp:.2f}%")
        check(f"xtab.cryptogames_{name}.sd", abs(sd6 - pub_sd) < 1e-9,
              f"analytic_sd={sd6:.6f} woo_sd={pub_sd:.6f}")
    for name in ("green", "red"):
        table, pub_rtp = WOO_BETFURY[name]
        eng = Plinko.from_table(table, label=f"betfury-{name}")
        rtp_pct = round(100 * eng.rtp, 2)
        check(f"xtab.betfury_{name}.rtp", abs(rtp_pct - pub_rtp) < 1e-9,
              f"analytic={rtp_pct:.2f}% woo={pub_rtp:.2f}%")
    # BetFury Blue: the reference page's printed table does NOT evaluate to
    # the RTP printed beside it (97.88%) — it evaluates to 97.5018%.  Assert
    # the true value of the printed table, surfacing the page's own defect.
    bf_blue = Plinko.from_table(WOO_BETFURY["blue"][0], label="betfury-blue")
    blue_pct4 = round(100 * bf_blue.rtp, 4)
    check("xtab.betfury_blue.reference_self_inconsistency",
          abs(blue_pct4 - 97.5018) < 1e-9,
          f"printed_table_evaluates_to={blue_pct4:.4f}% "
          f"page_prints={WOO_BETFURY['blue'][1]:.2f}% "
          f"(reference-internal defect; corroborates the Low-column caveat)")
    # BetFury Red is the Stake 16/high table — both constructors must agree.
    bf_red = Plinko.from_table(WOO_BETFURY["red"][0], label="betfury-red")
    g16h = engines[("high", 16)]
    check("xtab.betfury_red_equals_stake_high16",
          bf_red.payouts.tolist() == g16h.payouts.tolist()
          and bf_red.rtp == g16h.rtp
          and bf_red.std_per_unit == g16h.std_per_unit,
          f"rtp={100 * bf_red.rtp:.4f}% sd={bf_red.std_per_unit:.6f}")

    # 5. BINOM -------------------------------------------------------------
    for rows in range(MIN_ROWS, MAX_ROWS + 1):
        eng = engines[("medium", rows)]
        exact = np.array([math.comb(rows, k) for k in range(rows + 1)],
                         dtype=np.float64) / 2 ** rows
        ok = (np.array_equal(eng.probabilities, exact)
              and np.allclose(pascal_probabilities(rows), exact, atol=1e-15)
              and abs(eng.probabilities.sum() - 1.0) < 1e-12)
        check(f"binom.rows{rows}", ok,
              f"P(edge)=1/{2 ** rows} pascal_helper=match")

    # 6. EMPIRICAL: 10M real provably-fair drops per row count, all 27 -----
    n_streams = MAX_ROWS - MIN_ROWS + 1
    print(f"# empirical: {n_empirical:,} drops x {n_streams} row counts on "
          f"the real HMAC-SHA256 provably-fair stream (floor(float*2) per "
          f"row), each stream settled against all 3 risk tables", flush=True)
    total_rounds = 0
    t_emp = time.time()
    worst_z = 0.0
    for rows in range(MIN_ROWS, MAX_ROWS + 1):
        bulk = sq_rng.BulkRng(server_seed=_stream_seed(rows),
                              client_seed=CLIENT_SEED, nonce_start=0)
        t_rows = time.time()
        # one shared direction stream per row count: the landing pocket is a
        # pure function of the rows floats, so all three risks settle the
        # identical verifiable campaign (the Wheel-validator pattern)
        lead = engines[("low", rows)].simulate(n_empirical, bulk=bulk,
                                               progress=False)
        rows_secs = time.time() - t_rows
        counts = np.asarray(lead["pocket_counts"], dtype=np.int64)
        total_rounds += lead["n_rounds"]
        for risk in RISKS:
            eng = engines[(risk, rows)]
            sim = (lead if risk == "low"
                   else eng.summarize_counts(counts,
                                             verification=lead["verification"]))
            z = sim["z_score"]
            worst_z = max(worst_z, abs(z))
            check(f"empirical.{risk}/{rows}",
                  sim["within_3se"] and sim["n_rounds"] == n_empirical,
                  f"n={sim['n_rounds']:,} emp_rtp={sim['rtp']:.6f} "
                  f"analytic={sim['analytic_rtp']:.6f} "
                  f"se={sim['se_rtp']:.2e} z={z:+.2f} "
                  f"emp_sd={sim['std_per_unit']:.4f} "
                  f"sd={eng.std_per_unit:.4f} "
                  f"({lead['n_rounds'] / rows_secs:,.0f} rounds/s)")
    emp_secs = time.time() - t_emp
    rps = total_rounds / emp_secs
    print(f"# empirical throughput: {total_rounds:,} provably-fair rounds in "
          f"{emp_secs:.1f}s = {rps:,.0f} rounds/s", flush=True)

    # 7. PROV-FAIR replay: scalar/bulk bit-identity + chunk invariance -----
    print(f"# provably-fair replay: {len(REPLAY_CONFIGS)} configs, sample "
          f"nonces + first-1000 histograms through engine.play_round",
          flush=True)
    for cfg in REPLAY_CONFIGS:
        eng = engines[cfg]
        server_seed = _stream_seed(cfg[1])  # the section-6 campaign seeds
        bulk = sq_rng.BulkRng(server_seed=server_seed,
                              client_seed=CLIENT_SEED,
                              nonce_start=0, workers=1)
        # bit-reproduce sample campaign rounds through the scalar verifier:
        # play_round floats/pocket must equal the stream's own spot checks
        replay_ok = True
        for nonce in (0, 1, n_empirical // 2, n_empirical - 1):
            r = eng.play_round(server_seed, CLIENT_SEED, nonce)
            expect = bulk.verify_floats(nonce, eng.rows)
            if r["floats"] != expect:
                replay_ok = False
            if r["pocket"] != sum(sq_rng.plinko_directions(expect)):
                replay_ok = False
        # full first-1000 histogram replay through the scalar path
        replay_counts = np.zeros(eng.pockets, dtype=np.int64)
        for nonce in range(1000):
            replay_counts[
                eng.play_round(server_seed, CLIENT_SEED, nonce)["pocket"]] += 1
        d2 = bulk.plinko_directions(eng.rows, 1000).sum(axis=1)
        bulk_counts = np.bincount(d2, minlength=eng.pockets)
        replay_ok = replay_ok and np.array_equal(replay_counts, bulk_counts)
        check(f"provfair.{cfg[0]}/{cfg[1]}_scalar_bulk_bit_identical",
              replay_ok,
              f"first_1000_hist_match="
              f"{bool(np.array_equal(replay_counts, bulk_counts))} "
              f"seed_hash={bulk.server_seed_hash[:16]}...")
        # chunk size must never change results, only peak memory
        s1 = eng.simulate(
            50_000, chunk_rounds=7_001, progress=False,
            bulk=sq_rng.BulkRng(server_seed=server_seed,
                                client_seed=CLIENT_SEED,
                                nonce_start=0, workers=1))
        s2 = eng.simulate(
            50_000, progress=False,
            bulk=sq_rng.BulkRng(server_seed=server_seed,
                                client_seed=CLIENT_SEED,
                                nonce_start=0, workers=1))
        check(f"provfair.{cfg[0]}/{cfg[1]}_chunk_invariant",
              s1["pocket_counts"] == s2["pocket_counts"]
              and s1["n_rounds"] == s2["n_rounds"] == 50_000
              and s1["verification"]["nonce_range"] == (0, 50_000),
              f"counts_equal={s1['pocket_counts'] == s2['pocket_counts']} "
              f"(chunk_rounds 7,001 vs one default chunk)")

    # 8. MEM: peak RSS of this whole run (incl. the 90M-round campaigns) ---
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    check("mem.peak_rss_under_500mb", peak_mb < MEM_BUDGET_MB,
          f"peak_rss={peak_mb:.0f}MB budget={MEM_BUDGET_MB:.0f}MB "
          f"(chunked simulate; round-4 critic measured 2,541MB unchunked)")

    # ----------------------------------------------------------------------
    # completeness guard: every planned check must actually have run
    expected_checks = (5                      # refparse
                       + 1 + 27               # struct
                       + 27 + 3               # stake
                       + 3 + 27               # woo tables + rtp grid
                       + 4 * 2 + 2 + 1 + 1    # xtab
                       + 9                    # binom
                       + 27                   # empirical
                       + 2 * len(REPLAY_CONFIGS)  # provfair replay
                       + 1                    # mem
                       + 1)                   # this meta check itself
    check("meta.all_planned_checks_ran", _checks_run == expected_checks - 1,
          f"ran={_checks_run + 1} expected={expected_checks}")

    status = "PASS" if not failures else "FAIL"
    print(f"RESULT|{status}|configs=27|checks={_checks_run}|"
          f"passed={_checks_run - len(failures)}|"
          f"provfair_rounds={total_rounds:,}|"
          f"worst_abs_z={worst_z:.2f}|"
          f"rounds_per_sec={rps:,.0f}|"
          f"peak_rss_mb={peak_mb:.0f}|"
          f"failures={len(failures)}|elapsed={time.time() - t0:.1f}s")
    for f in failures:
        print(f"FAILURE|{f}")
    return 0 if not failures else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=N_EMPIRICAL,
                        help="drops per row-count stream, empirical check")
    args = parser.parse_args()
    try:
        sys.exit(main(args.rounds))
    except SystemExit:
        raise
    except BaseException as exc:  # guarantee exactly one RESULT line
        traceback.print_exc()
        print(f"RESULT|FAIL|error={type(exc).__name__}: {exc}", flush=True)
        sys.exit(2)
