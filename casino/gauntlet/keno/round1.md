# Keno — Gauntlet Round 1 (independent critic review)

Reviewer: fresh-eyes critic. Nothing below is taken from the builder's own
test output; every number was recomputed or re-simulated by me.
Ground truth: `references/stake/keno.md` (payouts) and
`references/woo/keno.md` (statistical methodology / 40-ball cross-check).

**Verdict: ours does NOT win round 1.** The math is flawless — all 260 payout
cells, all 40 analytic RTPs, all 8 WoO 40-ball returns, and 120M of my own
simulated rounds are clean with room to spare. It loses on a *behavioral*
tell in the public API (see §7-A) plus a silent-hang defect (§7-B). Both are
one-liners; round 2 should be trivially winnable.

---

## 1. What I did (all independent of the builder's code)

| # | Check | Tool |
|---|---|---|
| 1 | Hand-transcribed all 260 payout cells + the RTP table straight out of `references/stake/keno.md`, recomputed `sum_k pay[k]·C(n,k)C(40−n,10−k)/C(40,10)` in exact `Fraction` arithmetic | my script, no engine import on the reference side |
| 2 | Wrote a from-scratch port of Stake's published `byteGenerator` / `generateFloats` / Fisher-Yates JS and diffed it against both engine RNG paths | my script |
| 3 | Ran `scripts/validate_keno.py` myself (full, no `--skip-sim`) | 50M rounds, 5 configs |
| 4 | My own 120M-round campaign through the engine's **public API**, own seeds, own nonce blocks, scattered selection, all statistics recomputed by me | 12M × 10 pick counts → **all 40 configs** |
| 5 | Mutation-tested the shipped validator (does it actually fail when the paytable is wrong?) | 3 mutations |
| 6 | Forced max-catch / zero-catch rounds to exercise cells no 10M sim can reach | 152 assertions |
| 7 | Label-stripped blind side-by-side | 40 rows × 2 unlabeled columns |

---

## 2. Payout table — 260/260 cells exact

I transcribed the four §6 tables by hand and compared against
`spinquest_sim.games.keno.PAYTABLES` cell by cell in exact rational
arithmetic (the engine stores the multipliers as strings → `Fraction`, so
`0.47`, `3.68`, `2.25` are exact, not binary floats).

```
260 cells compared exactly (expected 260)
0 mismatches
```

Row lengths are correct everywhere (`picks+1`, so the "—" impossible cells
are genuinely absent, not zero-padded). Both quirks the reference calls out
are present: **Low pick-1 pays 0.7x on 0 hits** and **Medium pick-1 pays
0.4x on 0 hits**.

**Worst payout diff across all 260 cells: 0.**

## 3. Analytic RTP — 40/40 configs, exact-Fraction identity with mine

My independent hypergeometric enumeration vs Stake's published RTP table:

```
picks  classic     low     medium    high        (my recomputation, %)
  1    99.0000  98.7500   98.7500  99.0000
  2    99.0385  98.8462   98.6538  98.6538
  3    99.0182  98.8664   98.9879  98.9879
  4    98.9605  98.9222   98.7827  98.9058
  5    98.9858  98.9031   98.9441  98.8894
  6    98.9665  99.0084   98.8347  98.9988
  7    98.9815  98.9388   98.9618  98.9618
  8    99.0228  99.0042   98.9236  98.9571
  9    98.9753  99.0689   98.9420  98.9645
 10    99.0374  98.7597   98.9743  99.0083

worst |mine − published| = 0.004665 pp   (published to 2 dp → tolerance 0.005)
```

Engine `rtp_exact(risk, picks)` vs my `Fraction`: **identical for all 40**
(`max engine-vs-critic analytic rtp delta = 0.00e+00`). Same for
`variance_exact` — 40/40 exact-Fraction identity. Probabilities sum to
exactly 1 for every pick count. `rtp_exact("classic", 1) == 99/100` exactly.

## 4. WoO 40-ball methodology cross-check — 8/8

`references/woo/keno.md` correctly documents that the Wizard has **no
Stake-keno page**; the engine does not fabricate a match, it reproduces his
Gamesys 40-ball column with the same machinery. My own transcription of his
pay table gives:

```
pick  3: WoO 97.47%  mine 97.4696%    pick  7: WoO 95.66%  mine 95.6550%
pick  4: WoO 96.48%  mine 96.4766%    pick  8: WoO 97.48%  mine 97.4822%
pick  5: WoO 96.15%  mine 96.1538%    pick  9: WoO 96.87%  mine 96.8656%
pick  6: WoO 96.63%  mine 96.6326%    pick 10: WoO 97.90%  mine 97.8980%
```

All 8 within 0.005 pp. This is the only place the WoO reference and the
Stake config overlap, and it is handled honestly.

## 5. RNG path — bit-identical to Stake's published verifier

I re-implemented `byteGenerator` / `generateFloats` / the partial
Fisher-Yates from the JS in the reference, with zero engine imports on my
side:

```
scalar  rng.keno_hits         : 500 nonces, 0 mismatches
BulkRng.keno_hits (row-wise)  : 500 rows,   0 mismatches, nonce_next = 500
BulkRng at nonce_start=10,000,000 : 50 rows, 0 mismatches
distinctness  : 0 duplicate-within-row events in 200,000 rows; range [1,40]
square marginals : chi2 = 27.69 on 39 df (0.1% crit = 72.1)
draw-position-1  : chi2 = 39.87 on 39 df
P(square in 1..10) : z = −0.746
```

`CURSOR_INCREMENTS["keno"] == 2`, computed from `EVENT_COUNTS["keno"] == 10`
via `ceil(10·4/32)` — matches the reference's verbatim "Keno (2 increments
for every game)". One round = 10 floats = 40 bytes = cursor rounds 0 and 1.
The engine adds no randomness of its own; the whole draw is the
already-gauntleted RNG core.

Note on Stake's inherent lattice bias: `floor(f·40)` over a 2^32 float
lattice gives 16 of 40 indices one extra lattice point — a relative
deviation of ~3.7e-9. That is faithful to Stake and five orders of magnitude
below the 10M-round SE, so it is a non-issue; I checked it explicitly
because the engine's *default* selection is the low squares `{1..picks}`,
which is exactly where such a bias would land.

## 6. Empirical — my own 120M rounds, all 40 configs inside 3 SE

Setup deliberately different from the shipped validator: my own 64-hex
server seed, my own client seed, disjoint 50M-wide nonce blocks per pick
count, and a **scattered** selection `[3,9,14,17,22,26,31,34,38,40][:picks]`
so the engine's `drawn <= picks` fast path is bypassed (`np.isin` path
exercised instead). I take **only the hit histogram** back from the engine
and recompute RTP, SE, z and chi-square myself from my own hand-transcribed
paytables.

```
picks  1 chi2=  0.81 df= 1 p=0.370 | clas .989556 z=-0.897  low .987371 z=-0.897  medi .987236 z=-0.897  high .989556 z=-0.897
picks  2 chi2=  1.01 df= 2 p=0.605 | clas .990394 z=+0.026  low .988425 z=-0.109  medi .986589 z=+0.132  high .987392 z=+0.742
picks  3 chi2=  2.43 df= 3 p=0.488 | clas .990158 z=-0.059  low .988175 z=-0.598  medi .988589 z=-0.809  high .987637 z=-0.870
picks  4 chi2=  0.50 df= 4 p=0.974 | clas .989579 z=-0.062  low .989459 z=+0.178  medi .988081 z=+0.171  high .990279 z=+0.337
picks  5 chi2=  5.95 df= 5 p=0.311 | clas .989823 z=-0.061  low .989815 z=+0.446  medi .990381 z=+0.417  high .988493 z=-0.139
picks  6 chi2=  6.94 df= 6 p=0.327 | clas .990004 z=+0.696  low .988561 z=-0.766  medi .987543 z=-0.288  high .990936 z=+0.200
picks  7 chi2= 15.39 df= 7 p=0.031 | clas .989250 z=-1.110  low .989796 z=+0.301  medi .990545 z=+0.397  high .993173 z=+1.190
picks  8 chi2=  7.64 df= 8 p=0.470 | clas .990820 z=+0.992  low .990230 z=+0.360  medi .989994 z=+0.656  high .990905 z=+0.440
picks  9 chi2=  4.60 df= 9 p=0.868 | clas .990063 z=+0.588  low .990863 z=+0.523  medi .990075 z=+0.988  high .990675 z=+0.444
picks 10 chi2= 13.91 df=10 p=0.177 | clas .990626 z=+0.644  low .987699 z=+0.516  medi .989873 z=+0.312  high .989778 z=-0.294

TOTAL 120,000,000 rounds in 543.3s (~220k rounds/s under 4-core contention)
configs: 40   outside 3 SE: 0   max |z| = 1.190
worst |empirical − target| = 0.003556 (medium/6, SE = 0.002791)
min hit-distribution chi2 p = 0.031 over 10 tests (expected: P(min<0.031) ≈ 27%)
```

The chi-square goodness-of-fit on the full hit-count histogram is a strictly
stronger test than RTP alone — it would catch a distributional error that
mean-matching hides. All 10 pass.

I also ran the shipped gate myself, unmodified:

```
$ python scripts/validate_keno.py
[table] 260/260 payout cells compared EXACTLY -> PASS
[rtp]   40/40 configs, worst |diff| = 0.0047 pp -> PASS
[woo]   8/8 published returns reproduced -> PASS
[sim] classic picks=1 : rtp=0.991351 (analytic 0.990000, se=0.000542, z=+2.492) PASS
[sim] classic picks=10: rtp=0.990772 (analytic 0.990374, se=0.000430, z=+0.927) PASS
[sim] low     picks=9 : rtp=0.991236 (analytic 0.990689, se=0.000366, z=+1.497) PASS
[sim] medium  picks=5 : rtp=0.985873 (analytic 0.989441, se=0.002469, z=-1.445) PASS
[sim] high    picks=10: rtp=0.990878 (analytic 0.990083, se=0.001139, z=+0.698) PASS
OVERALL: PASS   (exit 0)
```

The `z=+2.492` on classic/1 is a single-seed fluctuation, not a bias: for a
two-point payout the SD is a deterministic function of the mean, so it
carries no extra information, and my independent campaign on the same config
with different seeds returned `z=-0.897`.

Empirical SD vs analytic SD, with the SE of the sample SD derived from the
exact 4th central moment (delta method) — no config is off:

```
config        analytic SD  empirical SD   SE(s)    z
classic/10       1.3591       1.3600     0.0017  +0.51
low/9            1.1560       1.1800     0.0325  +0.74
medium/5         7.8078       7.7470     0.0600  -1.01
high/10          3.6004       3.6550     0.0553  +0.99
```

Memory: peak 317 MB per default 1M-round chunk (tracemalloc), inside the
500 MB budget.

## 7. Anti-fudge audit

Things I specifically tried to catch, and what I found:

- **Is the sim actually using the engine?** Yes. `Keno.simulate` calls
  `BulkRng.keno_hits`, which I proved row-identical to my own from-scratch
  Stake port. I also recomputed the hit histogram myself directly off raw
  `BulkRng.keno_hits` output for 4 different selections (prefix and
  scattered, picks 1/7/10/10) at 300k rounds each — **identical every time**.
- **Hardcoded empirical results?** None. No RTP constant appears anywhere
  outside the reference-derived tables. Aggregation is exact `Fraction`
  arithmetic over the histogram, not float accumulation.
- **Does the validator have teeth?** Mutation-tested:
  - `high/7` 5-hit cell `90 → 91`: paytable gate FAILS (1 mismatch), RTP gate FAILS. ✓
  - `low/10` 2-hit cell `1.1 → 1.101` (a 0.09% change): **both** gates still FAIL. ✓
  - Corrupting a copy of `references/stake/keno.md` (`3.96x → 3.95x`)
    changes what the parser returns → the parser genuinely reads the file,
    it is not an engine-to-engine tautology. ✓
- **Far-tail cells a 10M sim can never reach.** P(10 of 10) = 1.18e-9 →
  0.012 expected occurrences in 10M rounds; P(9 of 10) = 3.54e-7 → 3.5
  occurrences. So the empirical campaign has essentially **zero power** on
  the top one or two cells of every pick-10 table. I forced them instead by
  setting `selection = drawn[:picks]` (guaranteed full catch) and
  `selection = ` the 30 undrawn squares (guaranteed zero catch):
  **152 assertions across all 40 configs, 0 failures** — top cell, second
  cell, and the 0-hit cell (including Low-1 `0.7x` and Medium-1 `0.4x`).

## 8. Blind comparison (labels stripped)

Two unlabeled columns A/B, one the reference parsed with *my own* parser,
one the engine, order chosen by a coin flip printed only at the bottom of
the artifact. Full artifact:
`/tmp/claude-0/-home-user-troyrhinehart/b3ce270f-e608-55a6-8515-5735b66f4ebe/scratchpad/keno_blind.txt`

```
[risk mode 3]
  picks  9 | A: 0 0 0 0 4 11 56 500 800 1000     | B: 0 0 0 0 4 11 56 500 800 1000     |
  picks 10 | A: 0 0 0 0 3.5 8 13 63 500 800 1000 | B: 0 0 0 0 3.5 8 13 63 500 800 1000 |

rows where A != B: 0 / 40
```

**Result: pure coin flip.** All 40 rows are byte-identical; there is no cell
or figure in the paytable/RTP artifact that could identify the imitation.
The derived figures the reference does *not* publish (per-config SD,
P(payout>0), max win) are all plausible — 99% RTP band, Classic capped at
100x, the other three at 1000x, Low-1 `P(payout>0) = 1.0` because it pays on
0 hits.

So on the *artifact* the piece is indistinguishable. It is a **behavior**
that gives it away — §7-A below.

---

## 9. Defects found

### A. BEHAVIORAL TELL — `win: True` on a net-losing round (the blind-test failure)

```python
>>> Keno(1, "low").play_round(seed, client, n)   # a 0-hit round
{'n_hits': 0, 'payout': 0.7, 'multiplier': 0.7, 'win': True, ...}
```

`play_round` sets `win = payout > 0.0`. For the two configurations the
reference explicitly flags — Low pick-1 (0.7x on 0 hits) and Medium pick-1
(0.4x on 0 hits) — every single 0-hit round is reported as a **win** while
returning 30% / 60% *less* than the stake. Stake's own bet record for that
round carries a negative `profit` and renders as a loss; no real client
labels a 0.7x return a win. Hand an expert two round transcripts and this is
the one field that identifies the imitation. It is also the only such field
I could find.

Fix: `win = payout > 1.0`, and add an explicit `profit` (or `net`) field
`payout - 1.0` so the sign is unambiguous. Two lines.

### B. Silent infinite hang on `chunk_rounds=0`

```python
Keno(3, "classic").simulate(100, bulk=BulkRng(), chunk_rounds=0)   # hangs forever
```

`step = min(chunk_rounds, n_rounds - done)` yields `step = 0`, `done` never
advances, the `while done < n_rounds` loop spins forever with no output and
no error. (`chunk_rounds=-5` correctly raises `ValueError` from deeper in
`BulkRng` — so the *invalid* input is handled and the *degenerate* one is
not.) Confirmed by running it on a 4-second watchdog thread. Needs
`if chunk_rounds < 1: raise ValueError(...)` alongside the existing
`n_rounds <= 0` guard.

### C. Shipped empirical gate covers 5 of 40 configs (12.5%)

`DEFAULT_CONFIGS` in `scripts/validate_keno.py` is 5 pairs. The stated bar
is per-`(picks, risk)`; 35 configurations get no empirical check at all in
the repo. This is nearly free to fix and the builder left the freebie on the
table: **the draw stream does not depend on risk** — the hit histogram is a
function of `picks` only, so one 12M-round campaign per pick count scores
all four risk tables from the same histogram. Today's gate runs 5 campaigns
for 5 configs; 10 campaigns would give all 40. (`Keno.simulate` is
parameterized on risk and re-draws for each, which is what forces the 4x
waste.) My run proves all 40 pass — the gap is that the repo can't
demonstrate it.

### D. No test pins the top-cell payouts

Nothing in `tests/test_keno.py` exercises a full catch, and no simulation
ever will (see §7). The 9- and 10-hit cells — including every 1000x — are
covered by the paytable-transcription test only. A forced-catch test
(`selection = drawn[:picks]`) is ~6 lines and closes it. I wrote one; it
passes 152/152.

### E. Minor

- `PAYTABLES` is a plain mutable module dict; I corrupted the project's
  ground truth in-process during the mutation test. `MappingProxyType`
  would make that tamper-evident.
- Dead branch: `hit_probability_exact`'s `if DRAW_COUNT - hits > POOL_SIZE -
  picks: return 0` can never fire for `picks <= 10` (`10 - hits <= 10 <= 30
  <= 40 - picks`).
- `Keno` is not wired into `selector.py` / `harness.py` / `report.py` — but
  those are 1-line stubs and no other game is either, so this is not a
  keno-specific gap.

---

## 10. Verdict

| Gate | Result |
|---|---|
| Every payout cell reproduces the reference exactly | **PASS** — 260/260, worst diff 0 |
| Every analytic probability / RTP reproduces to published precision | **PASS** — 40/40, worst 0.0047 pp; exact-Fraction identity with my own computation |
| WoO 40-ball cross-check | **PASS** — 8/8 within 0.005 pp |
| 10M+ rounds within 3 SE | **PASS** — 120M rounds, 40/40 configs, max &#124;z&#124; = 1.190 |
| Hit-distribution goodness of fit | **PASS** — 10/10 chi-square, min p = 0.031 |
| No fudges / sim really uses the engine | **PASS** — mutation-tested, histograms cross-checked against raw RNG |
| Blind comparison a coin flip | **PASS** — 0/40 rows differ |
| No behavior gives ours away | **FAIL** — §9-A |
| Public API free of hangs | **FAIL** — §9-B |

**ours_wins = false.** The math and statistics are, as far as I can break
them, perfect — this is the strongest piece I have reviewed on the numbers.
It loses round 1 on the blind protocol's behavior clause, not on the math.

**Biggest remaining gap (single highest-value change):** fix the win/profit
semantics in `Keno.play_round` — define `win = payout > 1.0` and emit an
explicit `profit = payout - 1.0`, so a Low pick-1 / Medium pick-1 0-hit
round reports the 0.7x / 0.4x return as the net loss Stake's own bet record
shows. It is the only field in the entire piece that identifies ours as the
imitation under a blind side-by-side.

Secondary, in order: guard `chunk_rounds < 1` (§9-B); sweep all 40 configs
in `validate_keno.py` by reusing one draw campaign per pick count (§9-C);
add a forced-full-catch test for the top cells (§9-D).
