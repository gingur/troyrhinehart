# Gauntlet — Wheel, round 1 (independent critic)

Reviewed: `spinquest_sim/games/wheel.py`, `scripts/validate_wheel.py`, `tests/test_wheel.py`,
and the wheel paths in `spinquest_sim/rng.py` (`wheel_index`, `BulkRng.wheel_indices`,
`BulkRng.floats`).
Ground truth: `references/stake/wheel.md`, `references/woo/wheel.md`. No live site touched.

Nothing below is taken from the builder's own tests or from `validate_wheel.py`'s output.
Every number in sections 1–4 was produced by scripts I wrote for this review
(`/tmp/claude-0/-home-user-troyrhinehart/b3ce270f-e608-55a6-8515-5735b66f4ebe/scratchpad/`:
`indep_paytable.py`, `indep_rng_check.py`, `indep_sim.py`, `blind.py`, `edge.py`).

---

## 1. Independent re-derivation of the paytable

The builder's validator parses **section 4** of the reference (the rendered per-segment
markdown tables). I deliberately parsed a **different source inside the same reference** —
**section 3, the verbatim JavaScript `const PAYOUTS = {...}` block** — so that a
transcription error introduced when section 4 was rendered from section 3 would show up as
a disagreement rather than being silently shared by both sides.

| Check | Result |
|---|---|
| Section 3 (JS arrays) vs section 4 (markdown tables), 450 cells | **0 mismatches** — reference is internally consistent |
| Engine `PAYOUTS` vs section-3 JS, cell by cell (exact `Fraction`, not float) | **450/450 identical, max abs diff 0.0** |
| Array lengths 10/20/30/40/50 for all 3 risks | correct |
| Exact RTP per config, `Fraction` arithmetic | **15/15 = 99/100 exactly** |
| Per-config SD recomputed from the reference arrays vs `Wheel.std_per_unit` | **15/15 agree to <1e-12** |
| Published max-win table (section 5), 15 cells | **15/15 match** |

Independently recomputed analytic table (mine, from the reference; the engine's values are
bit-identical — see §4):

```
 cfg        RTP(exact)   SD/unit   P(win)   max
 10/low      99/100     0.502892   0.8000   1.50
 10/medium   99/100     1.063438   0.5000   3.00
 10/high     99/100     2.970000   0.1000   9.90
 20/low      99/100     0.502892   0.8000   1.50
 20/medium   99/100     1.028056   0.5000   3.00
 20/high     99/100     4.315310   0.0500  19.80
 30/low      99/100     0.502892   0.8000   1.50
 30/medium   99/100     1.095247   0.5000   4.00
 30/high     99/100     5.331313   0.0333  29.70
 40/low      99/100     0.502892   0.8000   1.50
 40/medium   99/100     1.064847   0.5000   3.00
 40/high     99/100     6.182548   0.0250  39.60
 50/low      99/100     0.502892   0.8000   1.50
 50/medium   99/100     1.133534   0.5000   5.00
 50/high     99/100     6.930000   0.0200  49.50
```

`references/woo/wheel.md` documents that WoO publishes **no** Stake-Wheel page, so the
analytic target is Stake's own table under WoO prob×pay methodology — which is exactly what
the engine does (`sum p_i·pay_i` "for one", `SD = sqrt(E[X²] − EV²)`). The high-risk SDs
satisfy the closed form `0.99·sqrt(n−1)` and the low-risk SD is size-invariant, both of
which I verified independently rather than taking the module's word for it.

**Verdict on payouts: exact, to full published precision. No fudge found.**

## 2. Is the engine actually running Stake's published RNG?

I wrote a from-scratch port of `byteGenerator` + `generateFloats` using only `hmac`/`hashlib`
(no `spinquest_sim` import) and compared it to the engine:

- `Wheel.play_round` float and segment vs my port: **0 mismatches** over nonces 0–200 ×
  all 15 configs (601 × 15 comparisons of float, segment and multiplier).
- `BulkRng.floats` vs my port: **0/5000 mismatches**.
- Floats all in `[0,1)`, granularity exactly `1/2³²`; `floor(f·segments)` in range for all
  five segment counts over 200 000 draws.
- Wheel consumes **one** float at cursor 0 (`EVENT_COUNTS["wheel"] == 1`), matching the
  reference's statement that Wheel is not a multi-increment game.

**Index-mapping exactness (stronger than the shipped tests).** `float64` multiplication
`k/2³² · n` is exact for every `k < 2³²` and `n ≤ 50` (the product `k·n < 2³⁸` fits the
53-bit significand), so `floor` can never disagree with exact rational arithmetic. I
confirmed this empirically on **100 000 000 random floats × 5 segment counts** and on every
float within ±2 ULP-of-`k` of all 155 segment boundaries: **0 disagreements**, `math.floor`
scalar path and `np.floor` bulk path identical. There is no off-by-one boundary bug here.

## 3. My own empirical run — 240 M rounds through the public API

**Run A — `Wheel.simulate()`, the engine's advertised public simulator, 12 M rounds ×
15 configs = 180 M rounds**, each config on its **own independent server/client seed**
(SHA-256 of `critic-wheel-<n>-<risk>`), not the validator's default seed. RTP, SD, SE and z
recomputed by me from the *reference-parsed* multiplier arrays, ignoring
`summarize_counts`'s own figures.

```
cfg          emp RTP    target    SD       SE          z       chi2 p
10/low     0.9898564   0.9900   0.5029   0.0001452   -0.989    0.040
10/medium  0.9898496   0.9900   1.0634   0.0003070   -0.490    0.900
10/high    0.9896964   0.9900   2.9700   0.0008574   -0.354    0.689
20/low     0.9900232   0.9900   0.5029   0.0001452   +0.160    0.962
20/medium  0.9895448   0.9900   1.0281   0.0002968   -1.534    0.792
20/high    0.9896502   0.9900   4.3153   0.0012457   -0.281    0.992
30/low     0.9897339   0.9900   0.5029   0.0001452   -1.833    0.196
30/medium  0.9898644   0.9900   1.0952   0.0003162   -0.429    0.616
30/high    0.9896312   0.9900   5.3313   0.0015390   -0.240    0.863
40/low     0.9898168   0.9900   0.5029   0.0001452   -1.262    0.672
40/medium  0.9905580   0.9900   1.0648   0.0003074   +1.815    0.801
40/high    0.9890496   0.9900   6.1825   0.0017847   -0.533    0.731
50/low     0.9899417   0.9900   0.5029   0.0001452   -0.402    0.188
50/medium  0.9897707   0.9900   1.1335   0.0003272   -0.701    0.709
50/high    0.9904207   0.9900   6.9300   0.0020005   +0.210    0.502
```

- **15/15 within 3 SE**, worst `|z| = 1.833` (30/low). Configs outside 3 SE: **0**.
- Engine-reported RTP vs my recomputation: **max delta 0.0** across all 15 (bit-identical) —
  `summarize_counts` is not inventing numbers.
- Min chi-square p over 15 tests: 0.040 (expected for 15 tests; no over- or under-dispersion).
- Throughput 0.5–1.0 M spins/s, 246.8 s wall for 180 M rounds.

**Run B — 20 M rounds × 3 configs = 60 M more**, settled through `Wheel.payouts_for_floats`,
adding two checks the shipped validator does not perform:

```
50/high    N=20M  rtp=0.9880497 (-1.26 SE)  empSD 6.92331 vs 6.93000
           chi2=60.71 df=49  upper p=0.1219  lower p=0.8781   lag-1 rho=-0.000178 (0.79 SE)
50/medium  N=20M  rtp=0.9900341 (+0.13 SE)  empSD 1.13373 vs 1.13353
           chi2=53.13 df=49  upper p=0.3182  lower p=0.6818   lag-1 rho=-0.000103 (0.46 SE)
10/low     N=20M  rtp=0.9900936 (+0.83 SE)  empSD 0.50280 vs 0.50289
           chi2= 5.71 df= 9  upper p=0.7685  lower p=0.2315   lag-1 rho=-0.000097 (0.44 SE)
```

Per-multiplier hit frequencies vs analytic probability, worst `|z|` across all 12 multiplier
rows: **1.26** (50/high, 49.50x at p=0.020000 observed 0.019961). No two-sided chi-square
anomaly (no over-uniformity), no lag-1 autocorrelation.

**Total independent evidence: 240 000 000 rounds through the engine's public API on
independent seeds. Statistics pass everywhere, with margin.**

I also ran `scripts/validate_wheel.py` myself: exit 0, all four gates PASS, worst z −1.59
(50/low) over its own 10 M spins, chi² 3.7/8.0/17.6/23.2/39.4.

## 4. Blind comparison

Two unlabeled columns, A and B. A is derived by me from the reference markdown; B from the
engine's public API (`Wheel.rtp`, `.house_edge`, `.std_per_unit`, `.win_probability`,
`.max_multiplier`, `.paytable()`). 15 configs × 6 statistics = 90 cells, plus the 15
multiplier→probability paytables.

```
           RTP                 edge                SD                  P(win)              max          #mult
10/low     0.990000|0.990000   0.010000|0.010000   0.502892|0.502892   0.800000|0.800000   1.50|1.50    3|3
10/medium  0.990000|0.990000   0.010000|0.010000   1.063438|1.063438   0.500000|0.500000   3.00|3.00    5|5
10/high    0.990000|0.990000   0.010000|0.010000   2.970000|2.970000   0.100000|0.100000   9.90|9.90    2|2
...        (all 15 rows identical in both columns)
50/high    0.990000|0.990000   0.010000|0.010000   6.930000|6.930000   0.020000|0.020000  49.50|49.50   2|2

differing cells: 0/90        differing paytable rows: 0/15
```

**Could an expert tell which column is the reference? No.** The columns are byte-identical
at published precision, the paytable rows are identical as exact rationals, and the derived
SDs are labelled and computed exactly as `references/woo/wheel.md` prescribes (from the pay
table, since no WoO figure exists). Nothing in the engine's output over-claims precision the
reference does not support, and nothing is missing that the reference publishes (the 450
segment payouts, the 15 max wins, "Edge 1.00% / RTP 99%", and the cursor-0 single-float
mechanic are all reproduced). **This is a coin flip.**

## 5. Defects found anyway (none fidelity- or statistics-affecting)

Ordered by severity. None of these changes a payout, a probability, or a simulated statistic;
all are robustness / evidence-quality problems.

### D1 — `Wheel.simulate(chunk_rounds=0)` hangs forever (confirmed)
`simulate` computes `step = min(chunk_rounds, n_rounds - done)`; with `chunk_rounds=0` the
loop advances by 0 forever. I hung it deliberately (`edge.py` test 7: killed at 5 s).
`n_rounds` is validated, `chunk_rounds` is not. Negative values happen to raise inside
`BulkRng._take_nonces`, so only 0 hangs. One-line fix.

### D2 — the shipped 10 M gate never executes `Wheel.simulate()`
`validate_wheel.py` GATE 4 pulls floats from `BulkRng` and settles them with an inline
`np.floor(floats * n).astype(np.int64)` + `np.bincount`, then calls `eng.summarize_counts`.
It never calls `Wheel.simulate()` and never calls `Wheel.payouts_for_floats` /
`payouts_for_segments`. So the engine's own advertised 10 M+ simulator is covered by exactly
one 200 000-round unit test (`test_simulate_contract_and_3se`), and the headline "10 M
provably-fair spins" validates a *re-implementation of two lines of the engine* rather than
the engine. (I closed this hole myself in §3 Run A — `simulate()` does pass at 180 M rounds —
but the shipped artifact does not demonstrate it.)

### D3 — "15/15 configs within 3 SE" is one stream reused 15 ways
GATE 4 settles all 15 configurations against **the same 10 M-float sequence**. The 15
z-scores are strongly correlated (the five low-risk configs in particular are near-duplicate
statistics of one another). The report reads as 150 M rounds of evidence; the independent
information content is ~10 M. My Run A used 15 independent seeds precisely because the
shipped run cannot support the claim it makes.

### D4 — uniformity gate is one-sided at the 99.99 % quantile
`if chi2 > stats.chi2.ppf(0.9999, n-1)` — with only five statistics at α = 1e-4 this
essentially never fires, and critically there is **no lower bound**. A fabricated engine that
cycled segments round-robin (or stratified them) would produce `chi2 ≈ 0`, exact 99 % RTP and
z ≈ 0, and would **pass GATE 2, GATE 4 and the chi-square check**. That is the exact fudge
class this gauntlet exists to catch. (GATE 3 would still catch it, but the statistical gate
should not be blind to it.) My Run B adds the missing two-sided p and a lag-1
autocorrelation check; the engine passes both.

### D5 — silent corruption paths around segment indices
- `summarize_counts` accepts negative counts: `[-5, 15, 0…]` on 10/low returns
  `rtp = 1.05` (RTP > 1) and `win_rate = 1.0` with no error.
- `payouts_for_segments(np.array([-1]))` **silently wraps to the last segment** — which on
  every high-risk wheel is the jackpot (49.50x at 50 segments). A negative index yields a max
  win rather than an exception.
- `rng.wheel_index` / `BulkRng.wheel_indices` accept illegal segment counts:
  `wheel_index(0.5, 7) → 3`, `(0.5, 0) → 0`, `(0.5, -3) → -2`;
  `wheel_indices(7, 5) → [5 1 5 1 2]`, `wheel_indices(0, 5) → [0 0 0 0 0]`.
  Combined with the wrap above, `segments = -3` is a silent path to fabricated jackpots.
  `Wheel.__init__` guards its own use, so nothing in the game engine reaches this — but these
  are public, wheel-named API.
- `Wheel(10.0, "low")` is accepted (`10.0 in (10, 20, …)` is `True`); harmless, but
  inconsistent with the module's otherwise strict typing (`rng._check_nonce` explicitly
  rejects float/bool for exactly this reason).
- `play_round(seed, client, -1)` returns a normal-looking round for a **negative nonce**;
  Stake's nonce "increments as every new bet is made". Arguably the RNG core's business, but
  the game layer doesn't guard it either.

### D6 — `within_3se` is reported for n = 1
`Wheel(50,"high").simulate(1)` returns `rtp = 0.0, z = -0.143, within_3se = True`. Arithmetically
correct, informationally empty; a minimum-`n` guard (or dropping the flag below, say, 10 000
rounds) would stop a 1-round run from printing a passing verdict.

### D7 — not a wheel defect, noted for completeness
`play_round` has no `bet` parameter and returns `payout == multiplier`, though the reference's
step 4 is `payout = bet × multiplier`. Every other engine in the repo (roulette, mines, keno,
slots, crash) uses the same unit-stake convention, so this is a repo-wide design choice, not
a Wheel-specific gap, and I am not counting it against this piece.

## 6. What I checked for and did **not** find

- No hardcoded empirical constants anywhere in `wheel.py`, `test_wheel.py` or
  `validate_wheel.py` — every asserted number is either parsed from the reference or derived
  by `Fraction` arithmetic at import/run time.
- No shortcut RNG: the simulator really is HMAC-SHA256 per nonce, verified against my own
  independent port at both the scalar and bulk level.
- No paytable drift from the low/high *constructed* arrays (`_LOW_BLOCK * k`,
  `(0,)*(n-1) + (top,)`): all 450 cells were compared against the verbatim JS block.
- No fp boundary bug in `floor(float × segments)` (proven exact, plus 100 M-float check).
- No mutable global state: `PAYOUTS` entries are tuples, `config()` returns fresh copies,
  each `Wheel` builds its own `_pay_arr`.
- Chunked simulation is result-identical to unchunked (verified independently at two chunk
  sizes) and nonce accounting is contiguous.
- `tests/test_wheel.py`: 81 passed in 0.70 s; I read all of it and found no tautologies of the
  "assert engine == engine" kind on the payout side.

## 7. Verdict

**ours_wins = true.**

Every one of the 450 published segment payouts, all 15 exact RTPs, all 15 max wins, all 15
SDs, the paytable probabilities and the cursor-0/one-float provably-fair mechanic reproduce
`references/stake/wheel.md` **exactly**, verified against a source section the builder's own
parser does not read and against a from-scratch HMAC port. 240 M independent rounds through
the public API land 15/15 within 3 SE (worst |z| = 1.83), with clean two-sided chi-square and
no autocorrelation. The blind side-by-side is 0 differing cells out of 90 plus 15 identical
paytables — an expert cannot pick the imitation.

The defects in §5 are real and worth fixing, but not one of them alters a payout, a
probability, or a statistic, and none is visible in the blind artifact. Under the stated
verdict rules the piece wins this round.

**Single biggest remaining gap (fix first even though it does not flip the verdict):**
rebuild `validate_wheel.py` GATE 4 so the headline 10 M+ empirical claim actually runs
through `Wheel.simulate()` (D2) on an **independent seed per configuration** (D3), and gate
uniformity with a **two-sided** chi-square plus a lag-1 autocorrelation check (D4) — today a
round-robin/stratified fake would pass every statistical gate the script runs, and the
engine's own advertised simulator is exercised only 200 000 rounds. Fold in the one-line
`chunk_rounds <= 0` guard (D1) while touching `simulate()`.
