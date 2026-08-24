# Keno — Gauntlet Round 2 (independent critic review)

Reviewer: fresh-eyes harsh critic, round 2/4. Nothing below is taken from the
builder's own test output or from round 1's report — I re-transcribed the
reference tables by hand, re-derived every probability in exact rational
arithmetic, re-ported Stake's published RNG from the JS, and ran my own
130M-round campaign through the engine's public API.

Ground truth: `references/stake/keno.md` (payouts) and
`references/woo/keno.md` (statistical methodology / 40-ball cross-check).

---

## 0. HEADLINE: the code did not change between round 1 and round 2

```
spinquest_sim/games/keno.py   modified 2026-08-24 03:16:20
scripts/validate_keno.py      modified 2026-08-24 03:19:00
tests/test_keno.py            modified 2026-08-24 03:18:35
gauntlet/keno/round1.md       written  2026-08-24 04:43:21
```

Every source file predates round 1's report by ~85 minutes. **No round-1
defect was addressed.** I verified each one still reproduces rather than
trusting the timestamps:

| Round-1 defect | Status in round 2 |
|---|---|
| A — `win: True` on a net-losing round | **STILL PRESENT**, and materially worse than round 1 described (§4) |
| B — silent infinite hang on `chunk_rounds=0` | **STILL PRESENT** (§5) |
| C — empirical gate covers 5 of 40 configs | **STILL PRESENT** (§6) |
| D — no test pins the top-cell payouts | **STILL PRESENT** (§6) |
| E — `PAYTABLES` mutable, dead branch | **STILL PRESENT** (§6) |

So round 2's verdict is largely forced. What I add over round 1 is (a) fully
independent confirmation that the *math* really is as clean as round 1
claimed, (b) a materially stronger characterisation of defect A — it is not
two edge configs, it is 7 configs where ~50% of rounds are mislabeled, and
(c) the finding that the shipped test suite **pins the buggy semantics as a
contract**, so the fix is not a pure one-liner any more.

---

## 1. What I did (all independent)

| # | Check | Scale |
|---|---|---|
| 1 | Hand-transcribed all 260 payout cells + the RTP table + WoO's 40-ball table from the reference markdown; recomputed `sum_k pay[k]·C(n,k)C(40−n,10−k)/C(40,10)` in exact `Fraction` arithmetic | 260 cells, 40 RTPs, 8 WoO returns |
| 2 | From-scratch port of Stake's published `byteGenerator` / `generateFloats` / partial Fisher-Yates from the JS in the reference; diffed against both engine RNG paths | 1,280 nonces + 300k structural rows |
| 3 | Ran `scripts/validate_keno.py` myself, unmodified, full sim | 50M rounds, 5 configs |
| 4 | My own campaign through the engine's **public API** — own seeds, disjoint nonce blocks, scattered selection, all statistics recomputed by me from my own paytables | 130M rounds → all 40 configs |
| 5 | Mutation-tested the shipped validator; corrupted a copy of the reference to prove the parser reads the file | 3 mutations + 1 |
| 6 | Forced full-catch / zero-catch / near-top rounds to exercise cells no simulation can reach | 348 assertions |
| 7 | Label-stripped blind comparison — paytable grid **and** bet-record transcripts | 40 rows + 8 rounds |

Scripts: `/tmp/claude-0/-home-user-troyrhinehart/b3ce270f-e608-55a6-8515-5735b66f4ebe/scratchpad/keno2/`
(`critic_math.py`, `critic_rng.py`, `critic_sim.py`, `critic_fudge.py`, `critic_blind.py`).

---

## 2. The math is clean — independently confirmed

### 2.1 Payout table: 260/260 cells exact

My hand transcription vs `spinquest_sim.games.keno.PAYTABLES`, compared in
exact rational arithmetic (the engine stores multipliers as *strings* →
`Fraction`, so `0.47`, `3.68`, `2.25`, `1.38` are exact, not binary floats):

```
=== engine paytable vs MY transcription: 260 cells, 0 mismatches ===
```

Row lengths are `picks+1` everywhere, so the reference's "—" impossible
cells are genuinely absent rather than zero-padded. Both quirks the
reference explicitly flags are present: **Low pick-1 pays 0.7x on 0 hits**,
**Medium pick-1 pays 0.4x on 0 hits**.

**Worst payout diff across all 260 cells: 0.**

### 2.2 Analytic RTP: 40/40, exact-Fraction identity

```
picks  classic     low     medium    high      (my independent recomputation, %)
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

worst |mine − published| = 0.004665 pp  (published to 2 dp → tolerance 0.005)
violations = 0 / 40
```

The engine's `rtp_exact` and `variance_exact` are **bit-identical
`Fraction`s to my own** for all 40 configurations — not merely within
tolerance. `rtp_exact("classic", 1) == Fraction(99, 100)` exactly. Hit
probabilities sum to exactly 1 for all 10 pick counts.

### 2.3 WoO 40-ball methodology cross-check: 8/8

`references/woo/keno.md` correctly documents that the Wizard publishes **no
Stake-keno analysis**. The engine does not fabricate a match; it reproduces
his Gamesys 40-ball column with the same hypergeometric machinery. My own
transcription of his pay table:

```
pick  3: WoO 97.47%  mine 97.4696%    pick  7: WoO 95.66%  mine 95.6550%
pick  4: WoO 96.48%  mine 96.4766%    pick  8: WoO 97.48%  mine 97.4822%
pick  5: WoO 96.15%  mine 96.1538%    pick  9: WoO 96.87%  mine 96.8656%
pick  6: WoO 96.63%  mine 96.6326%    pick 10: WoO 97.90%  mine 97.8980%
```

All 8 within 0.005 pp. This is the only place the WoO reference and the
Stake config overlap, and it is handled honestly — the reference's "NONE"
finding is propagated into the code comments and the validator's own
printed caveat rather than being papered over.

---

## 3. RNG path — bit-identical to my from-scratch port of Stake's verifier

I re-implemented `byteGenerator`, `generateFloats` and the partial
Fisher-Yates directly from the JS quoted in the reference, with zero engine
imports on my side:

```
scalar  rng.keno_hits vs my port      : 600 nonces, 0 mismatches
BulkRng.keno_hits (row-wise)          : 600 rows,   0 mismatches, nonce_next=600
BulkRng at nonce_start=12,345,678     : 80 rows,    0 mismatches
rows with duplicate squares           : 0 / 300,000   (range [1,40])
square marginal chi2                  : 39.65 on 39 df (0.1% crit 72.1)
draw-position-1 chi2                  : 33.66 on 39 df
EVENT_COUNTS['keno']=10, CURSOR_INCREMENTS['keno']=2
```

The cursor bookkeeping matches the reference's verbatim "Keno (2 increments
for every game due to 10 possible outcomes)": one round = 10 floats = 40
bytes = cursor rounds 0 and 1. The engine adds no randomness of its own.

**Does the simulator actually use the engine?** Yes. I recomputed the hit
histogram myself directly off raw `BulkRng.keno_hits` output and compared to
`Keno.simulate`'s histogram for five (picks, selection) combinations
including two scattered selections that bypass the `drawn <= picks` fast
path — identical every time:

```
picks= 1 default   : engine hist == my hist off raw RNG: True
picks= 7 default   : True
picks=10 default   : True
picks= 5 scattered : True
picks=10 scattered : True
```

---

## 4. DEFECT A (round 1's headline) — unfixed, and worse than reported

Round 1 framed this as affecting "the two configurations the reference
explicitly flags" — Low pick-1 and Medium pick-1 on 0 hits. That
understates it. `play_round` sets

```python
"win": payout > 0.0,
```

and there is **no `profit` / `net` field at all**. So *every* paytable cell
with a payout in `(0, 1]` is reported as a win while the player loses money
or breaks even. I enumerated all of them:

```
cells reported win=True that are NOT net wins:
  classic  picks= 4 hits= 1  pay=0.80x  P=0.444250
  classic  picks= 5 hits= 1  pay=0.25x  P=0.416484
  classic  picks= 7 hits= 2  pay=0.47x  P=0.343967
  low      picks= 1 hits= 0  pay=0.70x  P=0.750000
  medium   picks= 1 hits= 0  pay=0.40x  P=0.750000
plus two exact PUSHES also labelled win=True:
  classic  picks= 3 hits= 1  pay=1.00x  P=0.440283
  classic  picks= 6 hits= 2  pay=1.00x  P=0.321288
```

Aggregated as a rate of mislabeled rounds:

```
  classic  picks= 3:  44.03% of rounds mislabeled
  classic  picks= 4:  44.42%
  classic  picks= 5:  41.65%
  classic  picks= 6:  32.13%
  classic  picks= 7:  34.40%
  low      picks= 1:  75.00%
  medium   picks= 1:  75.00%

configs affected: 7 / 40
mean over the 7 affected configs: 49.52% of rounds mislabeled
mean over all 40 configs (uniform config choice): 8.67%
```

This is not an edge case. On Classic picks=5 — an ordinary, popular
configuration — **41.6% of all rounds** are reported `win: True` while
returning 0.25x, i.e. losing 75% of the stake. Stake's own bet record for
that round carries a negative `profit` and renders as a loss.

### 4.1 New finding: the test suite pins the buggy semantics

`tests/test_keno.py:212`:

```python
assert res["win"] == (res["payout"] > 0)
```

The wrong rule is asserted as a contract. (It happens to be exercised on
`Keno(7, "high")`, whose paytable has no sub-1x cell, so the assertion would
not itself break on a fix — but it documents the wrong invariant and must be
rewritten as part of the fix.) Round 1 called defect A a "two-line" change;
with this test it is a three-file change (engine, test, and the round-trip
assertion in `test_outcome_consistent_with_draw`).

---

## 5. DEFECT B — silent infinite hang, unfixed

```
chunk_rounds=0  -> STILL RUNNING AFTER 6s = INFINITE HANG (confirmed)
chunk_rounds=-5 -> ValueError: size must be >= 0
```

`step = min(chunk_rounds, n_rounds - done)` yields `step = 0`, `done` never
advances, and `while done < n_rounds` spins forever with no output and no
error. Note the asymmetry: the *invalid* input (`-5`) is rejected deep inside
`BulkRng`, while the *degenerate* input (`0`) hangs. `simulate` guards
`n_rounds <= 0` but not `chunk_rounds < 1`.

---

## 6. Remaining round-1 defects, all confirmed unfixed

- **C — coverage.** `DEFAULT_CONFIGS` is still 5 pairs; 35 of 40
  configurations get no empirical check in the repo. The freebie round 1
  identified is still on the table: the draw stream does not depend on risk,
  so one campaign per pick count scores all four risk tables from the same
  histogram. My own campaign (§7) does exactly that — 10 campaigns, 40
  configs — and proves all 40 pass. The gap is that the repo cannot
  demonstrate it.
- **D — top cells untested.** Nothing in `tests/test_keno.py` forces a full
  catch, and no simulation ever will: P(10 of 10) = 1.18e-9, i.e. 0.012
  expected occurrences in 10M rounds. Every 1000x and the Classic 100x are
  covered by the transcription test only. I wrote the forced test myself —
  348 assertions across all 40 configs (full catch, zero catch, near-top),
  **0 failures**, and the top cells do return 100x / 1000x / 1000x / 1000x.
  The engine is correct here; it is simply unpinned.
- **E — minor.** `PAYTABLES` is still a plain mutable dict: during my
  mutation test I rewrote the project's ground truth in-process with no
  error. The dead branch in `hit_probability_exact` still cannot fire for
  any `picks` in 1..10 (I enumerated all 65 (picks, hits) pairs; zero
  trigger). `Keno` is still unwired from `selector.py` / `harness.py` /
  `report.py`, but those are stubs and no other game is wired either, so
  this is not keno-specific.

### 6.1 New minor findings (not in round 1)

- **`simulate()` never reports which selection it used.** Neither the result
  dict nor `config()` contains `selection`, so a campaign run with a custom
  selection is not self-describing and cannot be reproduced from its own
  output. One key.
- **Negative nonces are accepted.** `play_round(seed, client, -1)` returns a
  normal-looking round. Stake nonces start at 1 and increment; a negative
  nonce is unverifiable against Stake's own verifier. (Non-integer nonces
  *are* correctly rejected by `rng.py`, so the type check exists and the
  range check is simply missing.)
- **Empty / short server seeds are accepted** (`server_seed=""` plays a
  round). The reference specifies a 64-hex server seed.
- **The RTP gate is insensitive to sub-precision paytable edits.** Mutating
  `classic/1` hit-1 from `3.96` to `3.9600001` leaves the RTP gate PASSing
  (worst diff 0.004665 pp, under the 0.005 tolerance). The *table* gate
  catches it exactly, so the suite as a whole has teeth — this is a note on
  gate layering, not a hole.

### 6.2 Anti-fudge audit — clean

- No hardcoded empirical results anywhere: zero suspicious RTP-shaped
  literals in `keno.py`; aggregation is exact `Fraction` arithmetic over the
  hit histogram, not float accumulation.
- The validator has teeth: mutating `high/7` hit-5 `90→91` and `low/10`
  hit-2 `1.1→1.101` (a 0.09% change) makes **both** the table and RTP gates
  FAIL.
- The reference parser genuinely reads the file: a corrupted copy of
  `references/stake/keno.md` (`3.96x → 3.95x`) parses as `[0.0, 3.95]`, so
  the comparison is not an engine-to-engine tautology.

---

## 7. Empirical — my own 130M rounds, all 40 configs inside 3 SE

Setup deliberately unlike the shipped validator: my own 64-hex server seed,
my own client seed, disjoint 60M-wide nonce blocks per pick count, and a
**scattered** selection `[3,9,14,17,22,26,31,34,38,40][:picks]` so the
`drawn <= picks` fast path is bypassed and the `np.isin` path is exercised
instead. I take **only the hit histogram** back from the engine and
recompute RTP, SE, z and chi-square myself from my own hand-transcribed
paytables.

```
picks  1 chi2=  0.01 df= 1 p=0.938 | clas .989963 z=-0.078 | low .987489 z=-0.078 | medi .987478 z=-0.078 | high .989963 z=-0.078
picks  2 chi2=  0.01 df= 2 p=0.996 | clas .990362 z=-0.066 | low .988443 z=-0.058 | medi .986512 z=-0.072 | high .986442 z=-0.087
picks  3 chi2=  0.71 df= 3 p=0.870 | clas .989927 z=-0.636 | low .988401 z=-0.334 | medi .989230 z=-0.424 | high .989153 z=-0.293
picks  4 chi2=  0.30 df= 4 p=0.990 | clas .989467 z=-0.340 | low .988696 z=-0.413 | medi .987201 z=-0.438 | high .987521 z=-0.442
picks  5 chi2=  2.71 df= 5 p=0.745 | clas .990122 z=+0.474 | low .990089 z=+0.627 | medi .990731 z=+0.596 | high .990241 z=+0.485
picks  6 chi2=  7.64 df= 6 p=0.266 | clas .990376 z=+1.518 | low .988040 z=-1.071 | medi .986161 z=-0.815 | high .986312 z=-0.806
picks  7 chi2=  7.58 df= 7 p=0.371 | clas .989322 z=-1.008 | low .988491 z=-0.689 | medi .988413 z=-0.537 | high .987724 z=-0.660
picks  8 chi2=  3.71 df= 8 p=0.883 | clas .990202 z=-0.046 | low .990271 z=+0.456 | medi .989184 z=-0.047 | high .989833 z=+0.090
picks  9 chi2= 12.55 df= 8 p=0.128 | clas .989281 z=-0.932 | low .990468 z=-0.687 | medi .989411 z=-0.014 | high .989836 z=+0.086
picks 10 chi2=  9.01 df= 8 p=0.341 | clas .990812 z=+1.162 | low .987678 z=+0.425 | medi .990269 z=+1.319 | high .990918 z=+0.836

TOTAL 130,000,000 rounds in 531.3s (244,703 rounds/s)
configs scored: 40   outside 3 SE: 0   max |z| = 1.518
worst |empirical - target| = 0.003676  at high/6 (SE = 0.004564)
min hit-histogram chi2 p = 0.1282 over 10 tests
```

Empirical SD vs analytic SD on four configs, with `SE(s)` derived from the
exact 4th central moment by the delta method — no config is off:

```
config        analytic SD  empirical SD   SE(s)     z
classic/10       1.3591       1.3560     0.0030   -1.04
low/9            1.1560       1.1207     0.0594   -0.59
medium/5         7.8078       7.7852     0.1095   -0.21
high/10          3.6004       3.5226     0.1010   -0.77
```

Memory: peak 317 MB traced for the default 1M-round chunk (`tracemalloc`),
inside the 500 MB budget.

The chi-square goodness-of-fit on the full hit-count histogram is a strictly
stronger test than RTP alone — it would catch a distributional error that
mean-matching hides.

I also ran the shipped gate myself, unmodified:

```
[table] 260/260 payout cells compared EXACTLY -> PASS
[rtp]   40/40 configs, worst |diff| = 0.0047 pp -> PASS
[woo]   8/8 published returns reproduced -> PASS
[sim] classic picks=1 : rtp=0.991351 (analytic 0.990000, se=0.000542, z=+2.492) PASS
[sim] classic picks=10: rtp=0.990772 (analytic 0.990374, se=0.000430, z=+0.927) PASS
[sim] low     picks=9 : rtp=0.991236 (analytic 0.990689, se=0.000366, z=+1.497) PASS
[sim] medium  picks=5 : rtp=0.985873 (analytic 0.989441, se=0.002469, z=-1.445) PASS
[sim] high    picks=10: rtp=0.990878 (analytic 0.990083, se=0.001139, z=+0.698) PASS
OVERALL: PASS
```

The `z=+2.492` on classic/1 is a single-seed fluctuation, not a bias — for a
two-point payout the SD is a deterministic function of the mean, so it
carries no extra information, and my independent campaign on the same config
returned `z=-0.078`. `pytest tests/test_keno.py`: 31 passed.

---

## 8. Blind comparison (labels stripped)

Full artifact: `/tmp/claude-0/-home-user-troyrhinehart/b3ce270f-e608-55a6-8515-5735b66f4ebe/scratchpad/keno2/keno_blind_r2.txt`
Two unlabeled sources, order set by a coin flip revealed only at the bottom.

### 8.1 Artifact 1 — payout grid + RTP: coin flip (ours passes)

One column is the reference parsed by **my own** parser, the other is the
engine.

```
paytable rows where A != B:  0 / 40
RTP rows where A != B:       0 / 10
```

Byte-identical. There is no cell in the paytable/RTP artifact that could
identify the imitation. **On the numbers, ours is indistinguishable.**

### 8.2 Artifact 2 — bet records: ours is identified instantly

A paytable-only blind test has no power over defect A, because the tell is
behavioral. So I rendered the *same 8 rounds* as a bet record from each
client (1.00 unit staked):

```
--- client A ---
  risk=classic  picks= 4 hits= 1 payout=    0.80  win=False  profit=-0.20
  risk=classic  picks= 5 hits= 1 payout=    0.25  win=False  profit=-0.75
  risk=classic  picks= 7 hits= 2 payout=    0.47  win=False  profit=-0.53
  risk=classic  picks= 3 hits= 1 payout=    1.00  win=False  profit=+0.00
  risk=classic  picks= 6 hits= 2 payout=    1.00  win=False  profit=+0.00
  risk=low      picks= 1 hits= 0 payout=    0.70  win=False  profit=-0.30
  risk=medium   picks= 1 hits= 0 payout=    0.40  win=False  profit=-0.60
  risk=high     picks= 5 hits= 5 payout=  450.00  win=True   profit=+449.00

--- client B ---
  risk=classic  picks= 4 hits= 1 payout=    0.80  win=True   profit=<not reported>
  risk=classic  picks= 5 hits= 1 payout=    0.25  win=True   profit=<not reported>
  risk=classic  picks= 7 hits= 2 payout=    0.47  win=True   profit=<not reported>
  risk=classic  picks= 3 hits= 1 payout=    1.00  win=True   profit=<not reported>
  risk=classic  picks= 6 hits= 2 payout=    1.00  win=True   profit=<not reported>
  risk=low      picks= 1 hits= 0 payout=    0.70  win=True   profit=<not reported>
  risk=medium   picks= 1 hits= 0 payout=    0.40  win=True   profit=<not reported>
  risk=high     picks= 5 hits= 5 payout=  450.00  win=True   profit=<not reported>

REVEAL: A = REFERENCE ; B = OURS
```

**Not a coin flip.** Client B calls a 0.25x return on a 1.00 stake a win and
cannot state a profit at all. Any expert — indeed any player — picks B as
the imitation on the first row. Per the blind protocol ("if any cell,
figure, or behavior gives ours away as the imitation, ours does not win"),
ours loses round 2.

---

## 9. Verdict

| Gate | Result |
|---|---|
| Every payout cell reproduces the reference exactly | **PASS** — 260/260, worst diff 0 |
| Every analytic probability / RTP reproduces to published precision | **PASS** — 40/40, worst 0.0047 pp; exact-`Fraction` identity with my own computation |
| WoO 40-ball cross-check | **PASS** — 8/8 within 0.005 pp |
| 10M+ rounds within 3 SE | **PASS** — 130M rounds, 40/40 configs (see §7) |
| Hit-distribution goodness of fit | **PASS** — 10/10 chi-square |
| No fudges / sim really uses the engine | **PASS** — mutation-tested; histograms cross-checked against raw RNG |
| Blind comparison (paytable/RTP artifact) | **PASS** — 0/40 rows differ |
| Blind comparison (behavioral artifact) | **FAIL** — §8.2 |
| Public API free of hangs | **FAIL** — §5 |
| Round-1 defects addressed | **FAIL** — 0 of 5 |

**ours_wins = false.**

The math and statistics are, as far as I can break them, perfect — and I
tried hard, from an independent transcription and an independent RNG port.
This piece does not lose on the numbers. It loses because **the builder
shipped no changes between round 1 and round 2**, so the behavioral tell
that decided round 1 decides round 2 unchanged, and my sharper measurement
of it makes the case worse rather than better.

### Biggest remaining gap (the single highest-value change)

**Fix the win/profit semantics in `Keno.play_round`: emit
`profit = payout - 1.0`, set `win = payout > 1.0`, and update the assertion
in `tests/test_keno.py` that currently pins `win == (payout > 0)`.** This is
the only thing in the entire piece that identifies ours as the imitation
under a blind side-by-side, and it is not a rare edge case — it mislabels
~50% of rounds in 7 of the 40 configurations, including Classic picks 3-7.

Secondary, in priority order:

1. Guard `chunk_rounds < 1` in `simulate` (§5) — one line, kills a silent
   infinite hang.
2. Sweep all 40 configs in `validate_keno.py` by reusing one draw campaign
   per pick count (§6-C) — the histogram is risk-independent, so this is
   ~4x cheaper than the current 5-campaign gate and covers 8x more.
3. Add a forced-full-catch test for the top cells (§6-D) — ~6 lines; I
   verified 348 such assertions pass, they are simply unpinned.
4. `MappingProxyType` on `PAYTABLES`; add `selection` to the `simulate`
   result; range-check nonce and server-seed length (§6, §6.1).
