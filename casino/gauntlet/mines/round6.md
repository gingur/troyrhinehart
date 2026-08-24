# Mines — Round 6 critic report (round 2 of 3)

Critic: independent, fresh eyes. Every number below comes from my own scripts, my own
markdown parser, my own from-spec port of Stake's published HMAC/Fisher-Yates, and my
own `/proc/<pid>/smaps_rollup` process-tree sampler. The builder's
`scripts/validate_mines.py` and `tests/test_mines.py` were read for *claims* and then
re-derived from scratch before being believed; both were also executed, but only after
my own numbers were in hand.

My scripts (scratchpad): `c6_table.py`, `c6_blind.py`, `c6_tofixed.py`, `c6_woo.py`,
`c6_woo2.py`, `c6_rng.py`, `c6_sim.py`, `c6_uniform.py`, `c6_tile2.py`, `c6_tile3.py`,
`c6_mem.py`, `c6_mem2.py`.

---

## VERDICT

**ours_wins = TRUE.**

| criterion | result |
|---|---|
| Round-4 gap (7 display cells / float64 reduce) | **CLOSED** — 0/300 mismatches, reproduced independently |
| Round-5 gap (500 MB chunking budget) | **CLOSED** — 220 MB peak tree PSS at the shipped default (was 610 MB) |
| Round-5 secondaries (a)-(d) | **all four closed** — verified individually below |
| payout-for-payout parity vs the Stake reference | **PASS** — 300/300 string-exact, zero tolerance |
| exact-arithmetic RTP identity | **PASS** — `mult x P(win) == 99/100` as `Fraction` in all 300 cells |
| 10M-round empirical, public API | **PASS** — 10 configs x 10,000,000 rounds, worst \|z\| = 1.595 |
| blind comparison | **PASS** — reference's 78 table lines regenerated with **0** differing characters |
| RNG core not regressed | **PASS** — `rng.py` untouched (mtime 02:39, predates round 5); 159 rng tests pass |

Nothing I could find rises to the level of a gap. The one thing I would still change is
an API-shape nit (`full_payout_table()`), recorded in §6 — it makes no published number
wrong and is not visible in the blind comparison.

---

## 1. The Round-4 gap: CLOSED (reproduced from scratch)

`gap.md` demanded that `display_multiplier()` round Stake's left-to-right float64
reduce rather than the exact `Fraction`, and that the 7 named cells stop being wrong.

I wrote my own parser of the three markdown table blocks in
`references/stake/mines.md` (not `VAL.parse_stake_table`). It recovered 300 cells and
I asserted set-equality with `{(m,k) : 1<=m<=24, 1<=k<=25-m}` — nothing silently
dropped, nothing extra.

```
tables parsed: 3   cells: 300   coverage == full valid set: True
display_multiplier() vs published, ZERO tolerance   : 0 mismatches / 300
my own from-scratch js reduce vs published          : 0 mismatches / 300
CONTROL (old path: exact rational + round-half-even): 7 mismatches / 300
module multiplier_display_float == my reduce, bitwise: True (all 300)
```

The 7 control mismatches are exactly the cells `gap.md` named — the regression is real,
not a moved goalpost:
`(1,7) 1.37/1.38 · (1,15) 2.47/2.48 · (1,23) 12.37/12.38 · (2,9) 2.47/2.48 ·
(7,17) 59,486.63/.62 · (9,15) 202,254.53/.52 · (15,5) 208.73/208.72`.

**Asymmetry fingerprint.** The reference contains 7 internally asymmetric cell-pairs
(same exact rational, different displayed cent). My scrape found exactly 7; our
displayed table produces exactly 7; **the two sets are identical**:
`(1,7) (1,15) (1,23) (2,9) (5,15) (7,17) (9,15)`.

**The payout path is untouched.** In `Fraction` arithmetic,
`multiplier_exact x win_probability_exact == 99/100` in **all 300 cells, 0 failures**,
and a third, independent derivation `0.99 * C(25,k)/C(25-m,k)` equals
`multiplier_exact` in all 300.

**Rounding-mode forensic (round 5's secondary (b), now documented in the module).** I
implemented ECMA-262 `toFixed(2)` exactly, over the *exact decimal value of the double*
(`Decimal(x).quantize(0.01, ROUND_HALF_UP)`):

```
float64 reduce + JS toFixed(2)   : 3 mismatches — (3,1) 1.13 vs 1.12, (19,1) 4.13 vs 4.12,
                                                 (17,7) 59,486.63 vs 59,486.62
float64 reduce + round-half-even : 0 mismatches   <- what we ship
cells whose reduce lands EXACTLY on .xx5: 6 — (3,1) 1.125, (7,1) 1.375, (13,7) 600.875,
                                              (17,7) 59486.625, (19,1) 4.125, (23,1) 12.375
```

All 6 exact ties print the **half-even** cent in Stake's published table (1.12, 1.38,
600.88, 59,486.62, 4.12, 12.38). So the reference's §6 prose (`toFixed`) contradicts its
own §7 table, uniformly, in 6 of 6 tie cells; siding with the table is right and is now
stated in `display_multiplier`'s docstring and pinned by
`test_tofixed_ties_away_would_break_three_cells`. Verified: `DISPLAY_TOL` no longer
exists anywhere in the codebase; `test_symmetry_in_mines_and_picks` is gone and the two
asymmetry tests are present and pass.

---

## 2. The Round-5 gap (memory budget): CLOSED

Round 5's probe: `_SIM_CHUNK_ROUNDS = 1_000_000` peaked at ~600 MB tree PSS / ~2.4 GB
tree RSS, busting the 500 MB budget, behind a confident in-code comment backed by a
parent-only `tracemalloc` measurement. Builder set the constant to **200,000**.

I wrote my own sampler (recursive `/proc/<pid>/task/<pid>/children` walk +
`smaps_rollup`, 20 ms period) and ran each case in a fresh subprocess.

| case | peak tree PSS | peak tree RSS |
|---|---|---|
| idle import baseline | 25.9 MB | 29.5 MB |
| **`Mines(24,1).simulate(10_000_000)` — shipped default** | **219.8 MB** | 525.8 MB |
| `Mines(12,13).simulate(10_000_000)` — shipped default | 199.0 MB | 604.7 MB |
| `Mines(24,1).simulate(10_000_000, picks=[17])` — `np.isin` path | 226.1 MB | 569.6 MB |
| `Mines(24,1).simulate(2_000_000, chunk_rounds=1_000_000)` — **old default** | **609.5 MB** | **2,412.3 MB** |

The last row reproduces round 5's headline number to within 1 % (609.5 vs 601-617 PSS,
2,412 vs 2,412 RSS), so the probe is the same probe and the fix is measured on the same
scale. The builder's own gate, run end to end, reads **208.3 MB PSS** — consistent with
my 208-226 MB across configs.

**No throughput was traded away.** 157,646 rounds/s at the 200k default vs 155,545
rounds/s at the old 1M chunk (same box, same worst-case config) — the in-code claim of
"no throughput loss" is accurate, and 200k x 3 digests = 600k still clears
`_PARALLEL_MIN_DIGESTS = 400_000`, so the call stays on the parallel digest path.

**Is PSS the right yardstick?** Yes, and I checked it against the engines that already
passed their gauntlets rather than taking the comment's word:

| engine, 3M rounds at its own default | tree PSS | tree RSS | max single-process RSS |
|---|---|---|---|
| **mines (24,1)** | **208.6 MB** | 525.5 MB | **221.4 MB** |
| roulette (red) | 158.8 MB | 336.8 MB | 158.2 MB |
| plinko (16/high) | 342.8 MB | 834.6 MB | 355.8 MB |

Tree-RSS above 500 MB is a fork copy-on-write artifact shared by the whole house
(plinko, which passed, is at 834 MB), while PSS and largest-single-process RSS — the
two numbers that mean anything to an OOM killer or a cgroup — put mines second-lowest of
the three. Mines is no longer the outlier; it is now the *tightest* of the wide-matrix
engines.

### Round 5's four secondaries — all four verified closed

- **(a) `chunk_rounds=0` hang.** `mines.py:346-351` now raises. Verified live:
  `chunk_rounds=0 -> ValueError("chunk_rounds must be >= 1, got 0")`, same for `-1`.
  Pinned by `test_chunk_rounds_zero_or_negative_raise_instead_of_hanging`.
- **(b) undocumented rounding mode.** Now a 12-line docstring paragraph naming the
  §6-vs-§7 contradiction and the 3 cells, plus a regression test. Verified in §1.
- **(c) vacuous `empirical_within_3se` under `--skip-sim`.** Gate is now
  `None if args.skip_sim else ...`, and `overall = all(v for v in gates.values() if v is
  not None)`. The same treatment was given to the new `memory_budget_500mb` gate.
- **(d) rounded print hiding precision.** The validator now prints
  `max |exact - published| = 0.005000000004656613` (`!r`, full precision) instead of
  `0.005000`.

---

## 3. Core bar re-verified

### 3a. RNG path — independent from-spec port

I re-implemented `byteGenerator`, `generateFloats` and the Mines Fisher-Yates draw from
`references/stake/mines.md` §1-§3 only (24 events, `floor(f * remaining)`, `list.pop`
order), then compared against the shipped paths:

```
from-spec vs rng.mines_positions (scalar) : 0 mismatches / 1,200
   (4 server seeds x 4 client seeds x 25 nonces x mine_count in {1,5,24})
from-spec vs BulkRng.mines_positions      : 0 mismatches / 900
Mines.play_round vs from-spec outcome+payout : 0 mismatches (5 configs x 59 nonces)
Mines.simulate win-count vs from-spec        : 0 mismatches / 3 configs
```

Prefix consistency holds: `mines_positions(24,·)[:, :m] == mines_positions(m,·)` in
every case tested, so the mine-count setting never perturbs the stream.

### 3b. Empirical — 100,000,000 rounds through the public API

My own seeds (`sha256("critic-round6-mines-independent")`, client `critic6-mines`), my
own configs, chosen disjoint from the validator's `[(1,1),(3,3),(5,5),(10,10),(24,1)]`
and from the tests' seeds. Every reported statistic recomputed independently from
`Fraction` math before comparison.

| mines | picks | pick set | wins / 10M | empirical RTP | z |
|---|---|---|---|---|---|
| 1 | 24 | prefix | 400,122 | 0.990302 | +0.197 |
| 2 | 23 | prefix | 33,518 | 0.995485 | +1.013 |
| 4 | 7 | prefix | 2,419,126 | 0.990063 | +0.113 |
| 7 | 17 | prefix | 187 | 1.112400 | **+1.595** |
| 12 | 12 | prefix | 18 | 0.712841 | −1.400 |
| 15 | 5 | prefix | 47,238 | 0.985975 | −0.888 |
| 20 | 4 | prefix | 4,004 | 1.002882 | +0.818 |
| 23 | 2 | prefix | 33,515 | 0.995395 | +0.997 |
| 6 | 6 | custom `[24,0,13,7,19,2]` | 1,532,816 | 0.990517 | +0.703 |
| 3 | 5 | custom `[20,21,22,23,24]` | 4,958,245 | 0.990344 | +1.090 |

Worst \|z\| = **1.595**, all ten inside 3 SE. My independently recomputed `rtp`, `se_rtp`
and `z_score` matched the engine's to 1e-12 in all ten (the engine is not marking its own
homework with a different formula). Throughput 121k-152k rounds/s under load.

The builder's validator, run end to end at the full bar (5 configs x 10M), also passes:
z = +0.269, −0.123, +0.358, −0.668, +0.681; `OVERALL: PASS`, all seven gates true.

### 3c. Pick-order invariance (my test, absent from the suite)

The engine has two code paths — `np.any(pos < picks)` for prefix picks and
`np.isin(pos, pick_arr)` otherwise. A permuted pick *set* must give the identical win
count on the identical nonce stream:

```
m=3  k=3  picks=[2,0,1]          : 334,839 vs 334,839  MATCH
m=5  k=7  picks=[6,5,4,3,2,1,0]  :  80,804 vs  80,804  MATCH
m=12 k=5  picks=[4,3,2,1,0]      :  12,291 vs  12,291  MATCH
```

### 3d. Mine placement uniformity — one scare, chased down, not real

My first probe (25 configs of `Mines(5,1).simulate(400_000, picks=[t])`, one tile each,
disjoint nonce ranges) gave chi2 = 48.53 on **25** df (25 independent samples, not a
multinomial), p = 0.003. I did not let that stand either way:

```
replication A (fresh seed): chi2=18.32 df=25 p=0.829  max|z|=2.11
replication B (fresh seed): chi2=31.73 df=25 p=0.166  max|z|=2.53
replication C (fresh seed): chi2=31.62 df=25 p=0.169  max|z|=1.94
20,000,000-round multinomial on the FIRST-drawn mine: chi2=33.88 df=24 p=0.087
   per-tile share range 0.039868 .. 0.040107 (expect 0.040000)
20,000,000-round "tile is among the 5 mines" marginals: max|z| = 2.88 over 25 bins
```

70 M further rounds show no per-tile structure and no repeat of the low p-value; the
first probe was a 1-in-300 fluctuation, and I record it here rather than deleting it.
`play_round` mine-position integrity: 0 failures in 1,999 rounds (always 24 distinct
tiles in 0..24).

### 3e. Wizard of Odds cross-check (independent parse)

300 rows parsed by my own regex. Our `win_probability` matches WoO's published
`Prob. win` column in **300/300** rows within 5e-7. His `Return` column equals
`Pays x P(win)` in **300/300** rows when the *exact* probability is used (using his
6dp-rounded probability column instead breaks 183 rows — that is his rounding, not our
math, and the builder's test correctly uses the exact probability). Mean of his Return
column over mines>=2 excluding his two documented typo rows = **0.9493** vs Stake's
**0.9900 exactly** (worst deviation from `99/100` across all 300 Stake cells: **0** in
exact arithmetic). WoO's methodology applied to Stake's *displayed* cells gives returns
in [0.9856, 0.9936], mean 0.989959 — rounding noise exactly where it should be. The
BetFury-vs-Stake paytable difference is documented in the module docstring, the
validator output and a test.

### 3f. Builder's own gates

`pytest tests/test_mines.py` -> **39 passed**. `pytest tests/test_rng.py` -> **159
passed**. `python scripts/validate_mines.py` (full, 50M rounds + memory gate) ->
**OVERALL: PASS**, `"overall_pass": true`. `spinquest_sim/rng.py` has not been touched
since 02:39 — before round 5 — so the passed RNG core carries no new risk.

Test tolerances are tight and honest: the table gate is string-vs-string with zero
tolerance; the loosest numeric tolerance anywhere in the file is `rel=1e-12` on a
variance identity. There is no `approx` hiding a cent.

---

## 4. BLIND PROTOCOL

I regenerated the reference's three markdown table blocks **purely from
`display_multiplier()`** — header row with the `1 mine` / `n mines` pluralisation,
separator row, `—` for impossible cells, comma thousands separators, `x` suffix — and
diffed them line-for-line against the reference file's own lines:

```
mines  1-8 : reference rows 26, ours 26, differing lines 0
mines  9-16: reference rows 26, ours 26, differing lines 0
mines 17-24: reference rows 26, ours 26, differing lines 0
TOTAL differing lines across all 78 rows / 300 published cells: 0
prose spot checks (1/1, 24/1, 1/24, 3/22): 4/4 OK
```

Strip the labels and there is nothing left to point at: the two tables are the same 78
lines of text, including all 7 asymmetric fingerprint cells and all 6 exact half-cent
ties. This is not a coin flip — it is identity. An expert cannot tell which is the
imitation, because at the level of the artifact being compared there is no imitation.

I looked for a second-order tell as well and found none: the reference's own
distinguishing features — the float-order asymmetry, the half-even tie behaviour, the
em-dash triangle, the thousands separators, the 99 % return identity — are all
reproduced, and the RNG stream underneath is bit-identical to a port written from the
published spec by someone who had not read the module.

---

## 5. What I did NOT find

- No cell where our table differs from the reference in any character.
- No off-by-one in the pick order, the mine draw, or the prefix fast path; the two
  win-detection paths agree exactly.
- No stat the engine computes differently from an independent recompute (1e-12).
- No mine-placement bias over 90 M rounds of targeted testing.
- No memory growth across chunks, no worker-fan-out blow-up at the shipped default, no
  divergence between scalar and vectorized paths (0 / 2,100 rows).
- No vacuous gate: every skipped gate reports JSON `null`, and `overall` ignores nulls.

---

## 6. Remaining nits (none of them a gap)

**(a) `full_payout_table()` is the one public entry point that still renders the
round-4 defect.** It returns `multiplier()` (the float image of the exact rational), so
`f"{table[m][k]:.2f}"` reproduces the same 7 wrong cents the gauntlet spent two rounds
removing:

```
full_payout_table() rendered at 2dp vs published: 7 mismatches
  (1,7) 1.37/1.38 · (1,15) 2.47/2.48 · (1,23) 12.37/12.38 · (2,9) 2.47/2.48 ·
  (7,17) 59,486.63/.62 · (9,15) 202,254.53/.52 · (15,5) 208.73/208.72
```

This is *correct* for its documented purpose (payout math must stay exact) and is not a
tell in the blind comparison, which uses the exported `display_multiplier`. But mines is
the only engine that ships a single table function: keno and wheel both pair
`paytable()` with `paytable_exact()`. A three-line `full_display_table()` (plus a note
in `full_payout_table`'s docstring that its values must not be rendered at 2dp) would
close the last route by which a consumer can re-create the round-4 bug. Recommended, not
required.

**(b) Progress output got 5x noisier.** `progress=True` prints once per chunk, so
dropping the chunk from 1M to 200k turned a 10M-round config from 10 progress lines into
50; the validator's full run now emits ~250 of them. Cosmetic, but it is an unremarked
side effect of the memory fix — gating the print on elapsed time or on every Nth chunk
would keep both properties.

**(c) `simulate()` rejects a float `n_rounds` with a `TypeError` from inside numpy**
(`'float' object cannot be interpreted as an integer`) rather than the clean `ValueError`
the neighbouring `n_rounds <= 0` and `chunk_rounds < 1` guards raise. Trivial.
