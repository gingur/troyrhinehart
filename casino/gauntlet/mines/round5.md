# Mines — Round 5 critic report (round 1 of 3)

Critic: independent, fresh eyes. Every number below comes from my own code, my own
parser of `references/stake/mines.md`, and my own from-spec port of the published
HMAC/Fisher-Yates. The builder's `scripts/validate_mines.py` and `tests/test_mines.py`
were read for *claims*, then re-derived independently before being believed.

Scripts I wrote (scratchpad):
`crit_table.py`, `crit_tofixed.py`, `crit_rng.py`, `crit_sim.py`, `crit_uniform.py`,
`crit_mem.py`, `crit_mem2.py`, `crit_mem3.py`, `crit_blind.py`.

---

## VERDICT

**ours_wins = FALSE.**

The Round-4 gap is **fully closed** — the payout table is now perfect and the blind
comparison is not merely a coin flip, it is byte-identical. But the piece ships a
`_SIM_CHUNK_ROUNDS` default that **busts the project's 500 MB chunking budget by
~25 % (PSS) / ~5x (RSS)**, while carrying an in-code comment asserting the opposite,
backed by a measurement method that is structurally blind to most of the footprint.
That is the same class of defect this gauntlet already caught in plinko, and it is a
one-constant fix.

| criterion | result |
|---|---|
| payout-for-payout parity vs the Stake reference | **PASS** — 300/300 exact strings |
| 10M-round empirical checks within 3 SE | **PASS** — 9 configs x 10M, worst \|z\| = 1.616 |
| blind comparison | **PASS** — reference table regenerated with 0 differing lines |
| memory budget (<500 MB) | **FAIL** — 617 MB PSS / 2.4 GB RSS at the shipped default |

---

## 1. The Round-4 gap: CLOSED

Round 4's verdict: `display_multiplier()` rounded an exact `Fraction` instead of
replaying Stake's published left-to-right float64 reduce, so 7 of 300 published cells
were off by one cent.

The builder added `multiplier_display_float(m, k)`
(`spinquest_sim/games/mines.py:115-130`) and made `display_multiplier` round *that*.
I reproduced the probe from scratch.

**My own parser** of the three markdown table blocks in `references/stake/mines.md`
(not the builder's `parse_stake_table`) recovered exactly the 300 valid `(m, k)` cells
— coverage set equal to `{(m,k) : 1<=m<=24, 1<=k<=25-m}`, verified as a set equality,
so nothing was silently dropped.

```
display_multiplier() rendered vs published, ZERO tolerance:  0 mismatches / 300
control (old path: exact rational + round-half-even):        7 mismatches / 300
```

The 7 control mismatches are exactly the cells Round 4 named — the regression test is
real, not a rewritten goalpost:

| cell | published | old path | exact value | float64 reduce |
|---|---|---|---|---|
| (1,7)  | 1.37x       | 1.38x       | 11/8       | 1.3749999999999996 |
| (1,15) | 2.47x       | 2.48x       | 99/40      | 2.4749999999999996 |
| (1,23) | 12.37x      | 12.38x      | 99/8       | 12.374999999999996 |
| (2,9)  | 2.47x       | 2.48x       | 99/40      | 2.474999999999999  |
| (7,17) | 59,486.63x  | 59,486.62x  | 475893/8   | 59486.62500000003  |
| (9,15) | 202,254.53x | 202,254.52x | 8090181/40 | 202254.52500000008 |
| (15,5) | 208.73x     | 208.72x     | 8349/40    | 208.72500000000002 |

I wrote the reduce a second time straight out of the reference's §6 JS
(`reduce((a,i) => a*(25-i)/(25-s-i), 0.99)`), with no reference to the module:
**0 differences** vs `multiplier_display_float` across all 300 cells.

**Asymmetry fingerprint.** The reference contains 7 internally asymmetric cell-pairs
(same exact rational, different displayed cent). My scrape found exactly 7; our
displayed table produces exactly 7; **the two sets are identical**:

```
(1,7)/(7,1)    1.37x / 1.38x
(1,15)/(15,1)  2.47x / 2.48x
(1,23)/(23,1)  12.37x / 12.38x
(2,9)/(9,2)    2.47x / 2.48x
(5,15)/(15,5)  208.72x / 208.73x
(7,17)/(17,7)  59,486.63x / 59,486.62x
(9,15)/(15,9)  202,254.53x / 202,254.52x
```

**The payout path is untouched.** `multiplier_exact x win_probability_exact == 99/100`
in `Fraction` arithmetic for **all 300 cells, 0 failures**; `multiplier_exact` is
symmetric in (m,k) in **all** pairs (0 violations); worst relative drift of the display
reduce vs the exact rational is **6.307e-16** at (7,14). I also re-derived
`multiplier_exact` a third way from `C(25,k)/C(25-m,k)`: 0 mismatches.

**The two secondary demands of the gap are also done.**
- `DISPLAY_TOL` is gone from the codebase (grep: no hits). The gate is now
  string-vs-string with zero tolerance (`validate_mines.py:203-204, 284`).
- `test_symmetry_in_mines_and_picks` is gone. It is replaced by
  `test_reference_has_exactly_these_asymmetric_pairs` and
  `test_displayed_table_reproduces_reference_asymmetry`
  (`tests/test_mines.py:106-137`), which assert the asymmetry rather than the symmetry
  that used to give ours away.

**Fragility audit (mine, not asked for).** 24 cells have an exact value sitting on a
half-cent boundary; after the float64 reduce, **11 cells still land exactly on the
boundary (0.0 ULP)** and 18 are within 2 ULP. So the match is genuinely load-bearing on
the reduce *order*, not luck: a right-to-left reduce would print a different cent in 8
cells, and a "compute numerator and denominator products, then divide" implementation
would miss the same 7 the old code missed. The builder picked the one order the
reference actually used.

---

## 2. Core bar re-verified

### 2a. RNG path — independent from-spec port

I re-implemented `byteGenerator`, `generateFloats` and the Mines Fisher-Yates draw from
`references/stake/mines.md` §1-§3 only (`crit_rng.py`), then compared:

```
EVENT_COUNTS['mines'] = 24                                    (doc: 24 events, 3 cursor rounds)
scalar mines_positions:  0 mismatches / 800 (nonce, mine_count) cases
BulkRng.mines_positions: 0 mismatches / 200 rows at each of mine_count 1, 5, 24
prefix consistency (first mc of a 24-draw == an mc-draw):  0 failures / 2400
24-draw uniqueness + range 0..24:                          0 failures / 500
play_round(5 mines, 3 picks) vs spec replay:               0 disagreements / 300 nonces
play_round non-prefix picks [24,3,11,0]:                   0 disagreements / 300 nonces
simulate() vs spec replay, 2000 rounds:  m=5 k=3 1014/1014, m=7 k=4 502/502, m=24 k=1 75/75
```

The engine adds no randomness of its own and both its fast path (`pos < picks`) and its
`np.isin` path give the same answer as a literal replay.

### 2b. Empirical — 90,000,000 rounds through the public API

`Mines.simulate()` only, 10,000,000 rounds each, 9 configs chosen to be disjoint from
both the builder's `DEFAULT_CONFIGS` `[(1,1),(3,3),(5,5),(10,10),(24,1)]` and Round 4's
set, including two non-prefix pick orders:

| mines | picks | picks kind | wins | empirical RTP | z |
|---|---|---|---|---|---|
| 3 | 8 | prefix | 2,954,516 | 0.989328 | -1.390 |
| 6 | 6 | prefix | 1,533,856 | 0.991189 | **+1.616** |
| 10 | 3 | prefix | 1,977,363 | 0.989551 | -0.713 |
| 17 | 2 | prefix | 934,003 | 0.990710 | +0.728 |
| 20 | 4 | prefix | 3,913 | 0.980089 | -0.630 |
| 13 | 11 | prefix | 25 | 0.919339 | -0.370 |
| 4 | 21 | prefix | 801 | 1.003132 | +0.373 |
| 8 | 5 | custom [22,4,17,1,9] | 1,165,271 | 0.990494 | +0.572 |
| 2 | 12 | custom [24,23,0,5,...] | 2,600,486 | 0.990185 | +0.350 |

All 9 within 3 SE. Worst \|z\| = 1.616. Joint `sum z^2 = 6.70` on 9 df, **p = 0.668** —
no over- *or* under-dispersion.

I recomputed `p`, `multiplier`, `variance`, `se_rtp`, `rtp` and `z` from scratch for
every config; the engine's reported values **agree with mine on all 9** (`se_rtp`
relative agreement < 1e-9, `z` < 1e-6). The engine is not grading its own homework with
a different formula.

The two rare configs sit where the normal approximation is weak, so I ran **exact
binomial** two-sided tests instead of trusting `z`:
- (13,11): 25 observed vs 26.92 expected, **p = 0.807**
- (20,4): 3,913 observed vs 3,952.57 expected, **p = 0.535**

### 2c. Mine-placement uniformity (my test; the validator has none)

4,000,000 rounds, per-draw-slot chi-square over 25 tiles (df=24):

```
slot 0: chi2=20.59 p=0.663    slot 3: chi2=22.81 p=0.531
slot 1: chi2=41.85 p=0.013    slot 4: chi2=22.98 p=0.521
slot 2: chi2=23.97 p=0.463
'tile among first 5 mines' rate: min 0.199452, max 0.200456, mean 0.200000 (expect 0.2)
```

Fisher-Yates tail and joint independence, 1,000,000 rounds:

```
final draw slot 23:            chi2= 29.45 df= 24  p=0.204
ordered (slot0, slot1) pairs:  chi2=584.26 df=599  p=0.659   (all 600 ordered pairs)
duplicate tile in slots 0,1:   0 occurrences
```

The last-drawn tile is as uniform as the first (no pool-exhaustion bias), and the joint
distribution of the first two draws is flat over all 600 ordered pairs.

Slot 1's p = 0.013 is the only eyebrow. With 5 tests, P(min p < 0.0134) = 6.5 % — not
significant after multiplicity, and it is the *only* low value across 5 marginal tests
plus the tail-slot and pairwise tests below. Not a finding.

### 2d. Wizard of Odds cross-check (independent parse)

300 rows parsed. Our `win_probability` matches WoO's published `Prob. win` column in
**300/300** rows within 5e-7. His `Return` column reproduces `Pays x P(win)` in
**300/300** rows. Mean return of his (BetFury) table over mines>=2, excluding his two
documented typo rows, is **0.9493** vs Stake's **0.990000** exactly (max deviation from
0.99 across all 300 Stake cells: **0.00e+00** in exact arithmetic). The module and the
validator both document this as a deliberate paytable difference, not an error — correct.

Applying WoO's own methodology to Stake's *displayed* (2dp-rounded) cells gives returns
in [0.9856, 0.9936], mean 0.989959 — i.e. the rounding noise is where it should be.

### 2e. Builder's own gates

`pytest tests/test_mines.py tests/test_rng.py` -> **194 passed**.
`python scripts/validate_mines.py --skip-sim` -> **OVERALL: PASS**, exit 0, all six
gates true.

---

## 3. BLIND PROTOCOL

I regenerated the reference's three markdown table blocks (`Mines 1-8`, `9-16`,
`17-24`) **purely from `display_multiplier()`** — header row, separator row, `—` for
impossible cells, `,` thousands separators, `x` suffix — and diffed them line-for-line
against the reference file's own lines (`crit_blind.py`):

```
mines  1-8 : reference rows 26, ours 26, diff lines 0
mines  9-16: reference rows 26, ours 26, diff lines 0
mines 17-24: reference rows 26, ours 26, diff lines 0
TOTAL differing lines across all 300 published cells: 0
```

Strip the labels and there is nothing to point at: the two tables are the same 78 lines
of text, including all 7 asymmetric fingerprint cells. **An expert cannot tell which is
the imitation.** This is not "a coin flip" — it is identity. The blind test is passed
outright.

---

## 4. BIGGEST REMAINING GAP — memory budget

`spinquest_sim/games/mines.py:69-72` says:

```python
# Keep per-chunk arrays small: 1M rounds x 24 mine cols x 8 bytes = 192 MB;
# measured (tracemalloc) whole-call peak for a 1M-round chunk at the 24-mine
# worst case is 416 MB, inside the 500 MB budget.
_SIM_CHUNK_ROUNDS = 1_000_000
```

and `simulate()`'s docstring says "Chunked so per-chunk arrays stay <200 MB even at
24 mines."

**Both claims are false at the shipped default.** Measured with PSS (which charges
shared pages once — the honest number for a process tree) over the whole process tree:

| call | tree PSS | tree RSS |
|---|---|---|
| idle baseline | 21 MB | 30 MB |
| **`Mines(24,1).simulate(2M)` — shipped default** | **601-617 MB** | **2,412 MB** |
| `Mines(24,1).simulate(2M, chunk_rounds=250_000)` | 272 MB | 678 MB |
| `Mines(24,1).simulate(2M, chunk_rounds=200_000)` | 247 MB | — |
| `Mines(24,1).simulate(2M, chunk_rounds=50_000)` | 108 MB | 117 MB |
| `Mines(24,1).simulate(2M)` with `workers=1` | 631 MB | 641 MB |
| `BulkRng.mines_positions(24, 1M)` alone (RNG core) | 412 MB | 1,463 MB |
| **`Keno(...).simulate(2M)` at *its* default chunk** | **397 MB** | — |

Four things this establishes:

1. **It is not the RNG core's fault.** The core alone at a 1M-row mines block is 412 MB
   PSS — inside budget. The overshoot is the ~190 MB of `(1M, 24) int64` output plus
   `np.any(pos < picks, axis=1)` temporaries that *the mines module* asks for in one
   call.
2. **It is not the worker fan-out.** `workers=1` — a single process, no children — still
   peaks at **631 MB PSS**. Blaming `ProcessPoolExecutor` would be wrong.
3. **`chunk_rounds` fully controls it**, monotonically: 1M -> 601 MB, 250k -> 272 MB,
   200k -> 247 MB, 50k -> 108 MB. This is a **one-constant fix**.
4. **Mines is the outlier, not the house style.** Keno ships the *same* 1M constant and
   peaks at 397 MB — inside budget — because it aggregates to a histogram instead of
   materializing a wide int64 matrix. Mines is the engine that busts it.

**Why the builder's number looked fine.** I reproduced their measurement: a single
1M-round 24-mine chunk gives `tracemalloc` peak 397 MB and parent RSS 404 MB — matching
their 416 MB. But `tracemalloc` only sees Python-traced allocations in the calling
process; it cannot see the digest bytes assembled in worker processes, and it
under-reports the `np.frombuffer`/`view`/`astype` chain in `_float_block`. The
measurement method is structurally blind to roughly half the footprint, which is exactly
why the comment reads as confident and is wrong. **A 10M-round campaign at the default —
the very bar this gauntlet asks to be run — peaks at 616 MB parent RSS**; my own 9x10M
campaign script peaked at 561 MB.

**Fix:** set `_SIM_CHUNK_ROUNDS = 200_000` (247 MB PSS, no measurable throughput loss at
~140k rounds/s), correct both the constant's comment and the `simulate()` docstring, and
re-measure with PSS over the process tree — not parent-only `tracemalloc`.

---

## 5. Secondary findings (not the biggest gap, but real)

**(a) `chunk_rounds=0` hangs forever.** `Mines.simulate(100, chunk_rounds=0)` sets
`step = min(0, remaining) = 0`, adds 0 to `done`, and spins with no error and no output.
I reproduced it — killed at a 20 s timeout. Roulette, plinko and keno all carry an
explicit guard added for exactly this
(`roulette.py:503-509`, with the comment "*chunk_rounds=0 would make step = min(0,
remaining) = 0 and loop forever with no error or output*"; `plinko.py:374-375`;
`keno.py:388-391`). Mines never got it. One line:

```python
if chunk_rounds < 1:
    raise ValueError(f"chunk_rounds must be >= 1, got {chunk_rounds}")
```

**(b) The display rounding mode contradicts the reference's own stated function, and
the module never says so.** `references/stake/mines.md` §6 states the display is
`multiplier.toFixed(2)`. JS `toFixed` breaks ties *away from zero*; Python `round`/
`format` break them to *even*. I implemented `toFixed(2)` exactly (ECMA-262: minimise
`|n/10^f - x|`, ties pick the larger `n`) over the exact decimal value of the double:

```
float64 reduce + JS toFixed(2)      : 3 mismatches vs the published table
float64 reduce + round-half-even    : 0 mismatches  <- what we ship
```

The three cells are (3,1) `1.12` vs `1.13`, (19,1) `4.12` vs `4.13`, (17,7)
`59,486.62` vs `59,486.63` — all landing *exactly* on `.xx5` after the reduce. So the
reference is internally inconsistent: its §7 table was generated with banker's rounding
while its §6 prose names `toFixed`. **Siding with the table is the right call** (the
table is the 300 data points; §6 is a parenthetical) and it is what makes the blind test
pass. But the module's docstring explains only the reduce-order fix and is silent on the
rounding-mode choice, so the next reader will not know that switching to a "more
faithful" `toFixed` would break 3 cells. Document it, and add a regression test pinning
those 3 cells.

**(c) `gates.empirical_within_3se` reports `true` under `--skip-sim`.** No rounds were
run, yet the JSON gate is `true`. It is *not* hidden — the text prints "skipped
(--skip-sim) — empirical gate NOT exercised" and the JSON carries
`"empirical_skipped": true`, and a test asserts both. But a consumer reading the `gates`
map alone is misled. Make the gate `None`/absent when skipped.

**(d) Cosmetic leftover.** The validator still prints
`max |exact - published| = 0.005000` while the JSON holds `0.005000000004656613` —
the same rounded-print that made Round 4's `+1e-9` epsilon invisible. It is no longer
load-bearing (the comparison is string-exact now), but the habit is what caused the
earlier miss.

---

## 6. What I did NOT find

- No off-by-one in the pick order, the mine draw, or the prefix fast path.
- No divergence between the scalar and vectorized paths (0/2400 rows).
- No stat that the engine computes differently from an independent recompute.
- No cell where our table differs from the reference in any character.
- No memory *growth* across chunks — settled RSS is flat at ~100 MB after 6 successive
  1M-round calls, so there is no leak; the problem is purely the per-chunk peak.
