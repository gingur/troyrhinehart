# SpinQuest — final status scorecard

Date: 2026-08-24 (final stabilization sweep). All claims below were re-checked in this
sweep; nothing is carried forward on trust.

## Sweep results (this pass)

- **Test suite**: `python3 -m pytest tests/ -q` → **1002 passed, 2 xfailed** (192 s).
  The 2 xfails are the documented Scarab limitation in `tests/test_slots.py` (see below).
  No fixes were needed anywhere in the repo this pass.
- **Validators**: all 10 `scripts/validate_*.py` re-run this sweep at a **reduced
  1,000,000-round** campaign (`--rounds 1000000`; blackjack `--allow-small`, roulette
  `--allow-short`; crash also `--chain-rounds 1000000`), each well inside a 190 s cap.
  This is a smoke-level re-run, NOT the 10M+ empirical bar — the 10M+ campaigns were run
  during the gauntlet rounds and are recorded in `gauntlet/*/`. Results: **9 PASS, 1 FAIL
  (slots — the documented Scarab limitation; the Atkins model passes every gate)**.
- **Demo report**: `scripts/demo_report.py` regenerated
  `gauntlet/report/demo_report.html` (2,000 real-engine bets, stop-loss latched at
  seq 547, exit 0) and the HTML was rendered with headless Chromium
  (`/opt/pw-browsers/chromium-1194`, `--headless --screenshot`) — all six chart panels,
  the KPI strip and the key-metrics table render correctly.

## Scorecard — 17 pieces

States: **passed blind gauntlet** = final critic round returned ours_wins TRUE;
**fixed-and-verified** = final critic round failed, the fix landed afterward and is
pinned by tests that reproduce the critic's exact exploit plus a passing validator (no
fresh blind critic round ran after the fix); **built-and-tested (no gauntlet)** = never
went through a blind critic round, verified by the unit suite only;
**documented limitation** = a known, honestly-surfaced gap.

| # | Piece | State | Critic rounds | Evidence (one line) |
|---|-------|-------|---------------|---------------------|
| 1 | `spinquest_sim/rng.py` | passed blind gauntlet | 4 (rng_core) + 2 (rng_polish) | Core round 4: 0 byte/bit mismatches vs a Node 22 run of the verbatim published JS (864 bytes, 1.2M bulk floats), "Ours wins"; polish round 2: 0/78 differing blind cells, scalar path bit-identical. |
| 2 | `games/baccarat.py` | fixed-and-verified | 4 (r1,2,4,5) | Round 5 failed only on 2 blind em-dashes (Stake's 1.10% overall edge); post-round fix (`implied_banker_weight`, `house_edge_excluding_ties`, `tie_odds` param) round-trips 1.10% exactly as Fractions — validator 72/72 PASS this sweep, worst \|z\| 1.71 @ 1M. |
| 3 | `games/blackjack.py` | passed blind gauntlet | 3 (r1,2,4) | Round 4 PASS: critic's own DP reproduces WoO infinite-deck edge to 3.6e-09 and the payout law bit-for-bit in all 18 bins; validator 16/16 this sweep. |
| 4 | `games/crash.py` | fixed-and-verified | 4 (r1,3,4,5) | Round 5 salt/seed-grind exploit (rigged chain stamped `fair_ordering: True`) fixed after the round: >=8 leading-zero-nibble PoW floor, mandatory `revealed_at` strictly after commitment, verifier-side `verify_salt_against_beacon`; `tests/test_crash.py` (82 tests) reproduces the grind attacks; validator OVERALL PASS. Critic-confirmed core math: 0 payout mismatches over 20,000 HMAC pairs. |
| 5 | `games/keno.py` | passed blind gauntlet | 3 (r1,2,4) | Round 4: ours_wins = true (critic's own re-derivation of both references); validator OVERALL PASS this sweep. |
| 6 | `games/mines.py` | passed blind gauntlet | 4 (r1,4,5,6) | Round 6: ours_wins = TRUE — display path reproduces Stake's left-to-right float64 rendering 300/300 cells including all 7 asymmetric pairs; validator PASS this sweep (smoke rounds noted honestly by the script). |
| 7 | `games/plinko.py` | passed blind gauntlet | 3 (r1,4,5) | Round 5: ours_wins = TRUE — 27/27 Stake tables exact, round-4 memory blow-up fixed (validator measures peak RSS 391 MB vs the 2,541 MB the critic caught); 149/149 checks this sweep. |
| 8 | `games/roulette.py` | passed blind gauntlet | 4 (r1,4,5,6) | Round 6: "ours WINS" — round-5 gap closed at the root, every reference number reproduced; validator PASS (0 failures) this sweep. |
| 9 | `games/slots.py` | documented limitation (Scarab); Atkins exact | 4 (r2,3,4,5) | Atkins Diet is exact: all 8 WoO published figures at printed precision via full 33.5M-outcome enumeration, validator Atkins gates all pass. **Scarab caveat**: round 5 demanded the wild go back on the reel strips with the published 5-float budget and published bonus rules — that rebuild landed (wild on strips, 5 floats/spin, 3x multiplier, wild doubling, 180-spin cap, all shape gates pass) but the par-sheet re-solve to the published 97.84% was interrupted at wrap-up: exact RTP is currently 126.77%, so `validate_slots.py` honestly FAILs its Scarab RTP/attribution gates and 2 strict=False xfails in `tests/test_slots.py` pin the gap. Do not use the Scarab model for odds; use Atkins. |
| 10 | `games/video_poker.py` | passed blind gauntlet | 2 (r3,4) | Round 4: ours_wins = true; this sweep: exact 9/6 solve = 1653526326983/1661102543100 (matches WoO 99.5439% / SD 4.417542), all 8 variants + multihand SDs exact, validator OVERALL PASS. |
| 11 | `games/wheel.py` | passed blind gauntlet | 1 | Round 1: ours_wins = true — 450/450 published segment payouts, 15/15 RTPs/SDs/max-wins exact, blind table 0/90 differing cells; validator PASS (0 failures) this sweep. |
| 12 | `spinquest_sim/session.py` | fixed-and-verified | 2 (r5,6) | Round 6 blocker (open drawdown episode excluded from longest-DD duration) fixed after the round: episodes now close at last observation (`longest_drawdown_bets/days` include the open episode; `summary()` reconciles); pinned by `tests/test_session.py` (72 tests, incl. `test_open_episode_closed_at_last_observation`). |
| 13 | `spinquest_sim/harness.py` | documented limitation | 0 | A 1-line docstring stub — never built. Nothing imports it; its role (large-scale campaigns) is served by the engines' own chunked `simulate()` methods and the validator scripts. Left as-is rather than shipping an untested surface in a bounded wrap-up. |
| 14 | `spinquest_sim/selector.py` | built-and-tested (no gauntlet) | 0 | 402-config grid pulls RTP/edge/SD live from the critic-verified engines (nothing hardcoded); `tests/test_selector.py` 24 tests green. |
| 15 | `spinquest_sim/sizing.py` | built-and-tested (no gauntlet) | 0 | Survival-optimal sizing/stop math; `tests/test_sizing.py` 39 tests green; exercised end-to-end by the demo report's recommendations. |
| 16 | `spinquest_sim/report.py` | built-and-tested (no gauntlet) | 0 | `tests/test_report.py` 30 tests green; this sweep regenerated the 2,000-bet demo tear sheet and confirmed it renders in headless Chromium (charts + tables verified visually via screenshot). |
| 17 | `mcp_server/server.py` | built-and-tested (no gauntlet) | 0 | FastMCP stdio server over the verified engines; `tests/test_mcp.py` 16 tests green. |

## Validator scorecard (this sweep, 1M-round smoke re-run)

| Validator | Result | Note |
|---|---|---|
| validate_baccarat.py | PASS | 72/72 checks, incl. exact 1.10% portfolio round-trip |
| validate_blackjack.py | PASS | 16/16 (campaign-size gate waived via `--allow-small`, printed honestly) |
| validate_crash.py | PASS | bulk + chain campaigns, beacon-provenance gates |
| validate_keno.py | PASS | |
| validate_mines.py | PASS | prints "smoke-level empirical rounds, below the 10M bar" |
| validate_plinko.py | PASS | 149/149; peak RSS 391 MB < 500 MB budget |
| validate_roulette.py | PASS | 0 failures (`--allow-short`) |
| validate_slots.py | **FAIL** | Scarab RTP 126.77% vs published 97.84% + attribution/chain gates — the documented limitation; Atkins gates and both empirical sims all pass |
| validate_video_poker.py | PASS | exact solves + both empirical campaigns (notes 1M < 10M requirement) |
| validate_wheel.py | PASS | 0 failures |

## Known caveats

1. **Slots / Scarab** (the headline caveat): the Scarab par sheet does not reproduce the
   published 97.84% RTP (currently 126.77% exact). The mechanics rebuild demanded by
   critic round 5 is in place and verified; only the joint count-matrix re-solve is
   missing. Surfaced in three places: 2 strict=False xfails in `tests/test_slots.py`,
   the honest FAIL in `validate_slots.py`, and `gauntlet/slots/round5.md`.
2. **harness.py is a stub** (found in this sweep) — see row 13.
3. This sweep's validator runs were 1M-round smoke re-runs for turnaround; the 10M+
   evidence lives in the gauntlet records (`gauntlet/*/round*.md`, `gauntlet/*/gap.md`).
4. Crash, baccarat and session carry post-final-critic fixes verified by exploit-pinning
   tests and validators, but no fresh blind critic round ran after those fixes.
