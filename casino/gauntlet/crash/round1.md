# Gauntlet — Crash, Round 1 (independent critic)

Piece: `spinquest_sim/games/crash.py`, `scripts/validate_crash.py`, `tests/test_crash.py`
References (only ground truth used): `references/stake/crash.md`, `references/woo/crash.md`
Date: 2026-08-24. Reviewer wrote and ran every check below independently; the builder's
own tests were read for *fudge-hunting*, not relied on for evidence.

**Verdict: ours does NOT win this round — but only on one non-numeric count.**
Every payout, probability, and empirical statistic reproduces the reference exactly or
within 3 SE. The single thing that gives ours away in a blind side-by-side is the
**provable-fairness commitment ordering**: the engine pairs a freshly generated hash
chain with Stake's 2019 salt, which inverts the "future bitcoin block" property the
reference explicitly names as the point of the design.

---

## 1. What I checked, and how (all scripts written from scratch)

| # | Check | Method | Result |
|---|---|---|---|
| 1 | Crash-point formula | Re-implemented the published JS from primitives: RFC-2104 HMAC-SHA256 built from raw SHA-256 + ipad/opad (no `hmac` module), `digest.hex()[:8]`, `parseInt(...,16)`, `max(1,(2**32/(i+1))*(1-0.01))`. Compared against `crash_int_from_hash` / `crash_point_from_hash` on 20,000 random game hashes. | **0 mismatches** |
| 2 | `win_count(w)` | Exact-rational recomputation with `Fraction`: `floor(2^32 · F(0.99) / F(w))`, plus a boundary re-evaluation of the *actual float64 formula* at `n-1` and `n` for every target. 29 targets from 1.000001 to 1,000,000. | **0 differences**, every boundary confirmed |
| 3 | Hash chain | From-scratch 1,000-hash chain (`sha256` over the ASCII hex of the previous hash); compared `build_hash_chain`, `HashChain` play order, `verify_game_hash` step counts, and the private streamed walk. | identical; game *g* verifies in exactly *g* steps; unrelated hash → `None` |
| 4 | Seed-pair float→int recovery | `generate_floats` output vs `k/2^32` for 500 nonces; `BulkRng.floats` vs scalar for 64 nonces. | exact, 0 mismatches |
| 5 | Shipped validator | `python scripts/validate_crash.py` (defaults: 10M bulk + 10M chain) | **OVERALL: PASS**, exit 0, 59.4 s |
| 6 | Shipped tests | `pytest tests/test_crash.py -q` | **57 passed** in 1.94 s |
| 7 | Independent 12M-round sim | Through the public API (`simulate_targets` on a `BulkRng` seeded differently from the validator), 10 targets, wins recounted by me, SE and z recomputed by me | all within 3 SE, worst \|z\| = **2.680** |
| 8 | Distribution goodness-of-fit | χ² over 4096 equal bins of the recovered 32-bit int (12M rounds); χ² over 40 log-spaced multiplier bands vs exact `win_count` differences (10M bulk, 5×1M chain) | all consistent (see §3) |
| 9 | Seed-shopping test | 60 independent seed pairs × 300k rounds at w=2 and w=10; KS-tested the z's against N(0,1) | z ~ N(0,1); validator seed is not special |
| 10 | Circularity break on the chain path | `simulate_chain_targets` counts wins as `int < win_count`; I recounted 1M real chain rounds by comparing **crash points** to the target via the public `HashChain.crash_points` | exact match at w = 1.5 / 2 / 10 |
| 11 | Fudge hunt | Read the module and validator for hardcoded empirical values, sim-not-using-the-engine, dead branches, memory blowups, extreme targets | **none found** (details §5) |

---

## 2. Payout / probability parity (payout-for-payout vs the reference)

Crash has no discrete paytable; the reference's payout rule is `bet × m` iff `m ≤ crash point`,
with the derived law `P(crash ≥ w) = 0.99/w` and RTP = 0.99 at every target. My exact-rational
recomputation against the engine, 29 targets:

```
   target   engine_wc  rational_wc  diff   P(win) engine     0.99/w        RTP exact     |dev|    w/2^32
 1.000001  4252013371   4252013371     0   0.9899990100  0.9899990100   0.990000000  6.20e-12  2.33e-10
     1.01  4209918438   4209918438     0   0.9801980196  0.9801980198   0.990000000  1.54e-10  2.35e-10
      1.5  2834678415   2834678415     0   0.6599999999  0.6600000000   0.990000000  1.26e-10  3.49e-10
     1.98  2147483648   2147483648     0   0.5000000000  0.5000000000   0.990000000  0.00e+00  4.61e-10
      2.0  2126008811   2126008811     0   0.4949999999  0.4950000000   0.990000000  2.42e-10  4.66e-10
      3.0  1417339207   1417339207     0   0.3299999998  0.3300000000   0.990000000  4.75e-10  6.98e-10
      5.0   850403524    850403524     0   0.1979999999  0.1980000000   0.989999999  7.08e-10  1.16e-09
       10   425201762    425201762     0   0.0989999999  0.0990000000   0.989999999  7.08e-10  2.33e-09
      100    42520176     42520176     0   0.0098999999  0.0099000000   0.989999995  5.36e-09  2.33e-08
     1000     4252017      4252017     0   0.0009899999  0.0009900000   0.989999855  1.45e-07  2.33e-07
    10000      425201       425201     0   0.0000989998  0.0000990000   0.989998225  1.77e-06  2.33e-06
    99999       42520        42520     0   0.0000099000  0.0000099001  *0.989985997  1.40e-05  2.33e-05
  1000000        4252         4252     0   0.0000009900  0.0000009900   0.989995897  4.10e-06  2.33e-04
```

`max |engine_wc − rational_wc| = 0` over all 29 targets. Worst `|RTP − 0.99|` = **1.400e-05**
(at w = 99,999; bound `w/2^32` = 2.33e-05); worst over the validator's own 21-target grid is
4.10e-06. Every deviation is the unavoidable 32-bit quantization of Stake's own formula, is
below `w/2^32`, and is in the direction the formula actually produces — an idealized
"RTP = 0.99 exactly" column would be *less* faithful to Stake's code, not more.

Instant bust: engine `P(crash = 1.00) = 0.010000000009313226` = 42,949,673 / 2^32.
My first rational surrogate said 42,949,672; re-evaluating the float formula at the boundary
shows the **engine is right and my surrogate was off by one** (`raw(4252017623) ≤ 1.0`). Good.

Extremes: `crash_point_from_int(2^32−1) = 1.0` (published "lowest crashpoint of 1"),
`crash_point_from_int(0) = 4,252,017,623.04` (raw max, correctly above the 1,000,000× cashout cap).
Target validation rejects 1.0, ≤0, >1e6, inf, nan; accepts `nextafter(1.0)` → RTP 0.98999999999.

---

## 3. Empirical bar — my own simulation, my own SE

**Run A — 12,000,000 rounds, public API (`simulate_targets` + `BulkRng`), seeds
`sha256("harsh-critic-round1-seed")` / `"critic-independent"` (different from the validator's).**
Engine-reported `se_rtp` and `z_score` reproduce my independent computation to <1e-9.
My independently recounted win totals match the engine's wins **exactly** at all 7 cross-checked targets.

```
   w       wins        p_hat        p_exact       my_SE     my_z      RTP     RTP_exact   3·SE(RTP)   ok
 1.01  11762164   0.980180333   0.980198020   4.022e-05   -0.440   0.989982   0.990000   1.22e-04  PASS
  1.1  10799907   0.899992250   0.900000000   8.660e-05   -0.089   0.989991   0.990000   2.86e-04  PASS
  1.5   7915749   0.659645750   0.660000000   1.367e-04   -2.591   0.989469   0.990000   6.15e-04  PASS
    2   5935655   0.494637917   0.495000000   1.443e-04   -2.509   0.989276   0.990000   8.66e-04  PASS
    3   3956716   0.329726333   0.330000000   1.357e-04   -2.016   0.989179   0.990000   1.22e-03  PASS
    5   2372301   0.197691750   0.198000000   1.150e-04   -2.680   0.988459   0.990000   1.73e-03  PASS
   10   1187303   0.098941917   0.099000000   8.622e-05   -0.674   0.989419   0.990000   2.59e-03  PASS
   50    237278   0.019773167   0.019800000   4.022e-05   -0.667   0.988658   0.990000   6.03e-03  PASS
  100    118720   0.009893333   0.009900000   2.858e-05   -0.233   0.989333   0.990000   8.57e-03  PASS
 1000     11979   0.000998250   0.000990000   9.078e-06   +0.909   0.998250   0.990000   2.72e-02  PASS
```
Worst \|z\| = 2.680 (the ten targets are nested events on one stream, so they are strongly
correlated — a shared −2.5σ excursion is one draw, not ten).

**Run B — extreme targets, 10,000,000 rounds** (`--targets` the validator never exercises):
w=1000 z=−0.151, w=10,000 z=+0.668, w=100,000 z=−2.010, w=1,000,000 z=+0.032 (λ=9.9, 10 wins).
All within 3 SE. The normal-approximation gate survives even at λ≈10.

**Run C — chain mechanism, 1,000,000 rounds, wins recounted from crash points** (public
`HashChain.crash_points`, breaking the engine's `int < win_count` shortcut):
w=1.5 → 659,357 (engine 659,357), w=2 → 495,087 (495,087), w=10 → 98,451 (98,451). Exact match;
terminating hash matches the streamed simulator's.

**Distribution-level goodness-of-fit (the validator does not do this; I did):**

| Test | n | statistic | p |
|---|---|---|---|
| χ² uniformity, 4096 equal bins of the recovered 32-bit int (bulk) | 12,000,000 | χ² = 4069.9, df = 4095 | 0.607 |
| χ² over 40 log-spaced multiplier bands vs exact `win_count` differences (bulk) | 10,000,000 | χ² = 45.9, df = 38 | 0.177 |
| same, chain mechanism, 5 independent chain secrets | 5 × 1,000,000 | df = 31 | 0.044 / 0.641 / 0.521 / 0.914 / 0.512 |
| instant-bust rate (bulk) | 12,000,000 | 0.01000742 vs 0.010000000009, z = +0.258 | — |
| 60-seed sweep, w = 2 | 60 × 300,000 | mean z = −0.017, sd = 1.055 | KS 0.806 |
| 60-seed sweep, w = 10 | 60 × 300,000 | mean z = +0.106, sd = 1.159 | KS 0.244 |

The 60-seed sweep is my seed-shopping test: the validator's fixed seed
(`sha256("spinquest crash validation v1")`) sits at the 10th percentile of \|z\| among 60 random
seeds — unremarkable, and the whole z-population is clean N(0,1). **No evidence of seed selection.**
Max observed multiplier over 12M rounds: 10,656,685.77× (raw formula max is 4,252,017,623.04×).

**Shipped validator, for the record:** 10M bulk @ 600k rounds/s (16.7 s), 10M chain @ 236k rounds/s
(42.3 s), worst \|z\| = 1.352, `OVERALL: PASS`, exit 0, 59.4 s total.

---

## 4. Blind comparison (labels stripped)

### 4a. Numeric artifact — could an expert pick the imitation?

| target | Column A: P(win) / RTP | Column B: P(win) / RTP |
|---|---|---|
| 1.01 | 0.9801980198 / 0.990000000000 | 0.9801980196 / 0.990000000000 |
| 2 | 0.4950000000 / 0.990000000000 | 0.4949999999 / 0.990000000000 |
| 10 | 0.0990000000 / 0.990000000000 | 0.0989999999 / 0.989999999292 |
| 1 000 | 0.0009900000 / 0.990000000000 | 0.0009899999 / 0.989999855123 |
| 1 000 000 | 0.0000009900 / 0.990000000000 | 0.0000009900 / 0.989995896816 |

**Coin flip, arguably favouring B.** A is the reference document's *derived* closed form
(`0.99/w`, "RTP = 99% for any cashout target" — an idealization the reference labels as derived,
not quoted). B is ours. B is what Stake's published code actually computes once the 32-bit
`int` is quantized; an expert who reruns `Math.max(1,(2**32/(int+1))*0.99)` gets B, not A.
B does not read as the imitation.

### 4b. Mechanism artifact — this is where ours gives itself away

| | Artifact X | Artifact Y |
|---|---|---|
| terminating hash | `78a9757d…e56752`, published 2019-07-08 | `6599d236…5b3e44bf`, generated 2026-08-24 |
| salt | block 584,500 hash, mined **2019-07-21** | block 584,500 hash, mined **2019-07-21** |
| chain length | 10,000,001 | 10,000,001 |
| commitment ordering | salt fixed **after** the chain was committed | salt was public **7 years before** the chain existed |

Y is ours (verbatim from `simulate_chain_targets`' `verification` dict in the validator's JSON
output). **Any provable-fairness expert picks Y as the imitation on sight.** The reference states
the design intent in one sentence — *"a future bitcoin block as a client seed so players can be
certain that we did not pick one in the house's favor"* — and Y voids exactly that guarantee: with
the salt already public, whoever generates the chain can grind the secret seed and choose the
outcome sequence. Numerically Y is indistinguishable; as a provably-fair artifact it is not.

---

## 5. Fudge hunt — what I looked for and did not find

- **Hardcoded empirical results:** none. No literal probabilities, win rates, or z-scores anywhere
  in `crash.py`. The only literals are the published constants (2^32, `1-0.01`, `0.01`, `1e6`, the
  2019 terminating hash / salt / chain length) and every one of them is re-parsed out of
  `references/stake/crash.md` by `check_spec_parity()` and asserted equal.
- **Sim not using the engine:** false alarm. `simulate_targets` really pulls from `BulkRng.floats`
  (verified bit-equal to the scalar `generate_floats` at 64 nonces) and really evaluates
  `max(1, 2^32/(k+1)·0.99) ≥ w`. `simulate_chain_targets` really walks a SHA-256 chain
  (236k rounds/s is the honest cost of 2 SHA-256 + 1 HMAC per round; a fake would be 100× faster).
- **Circular win counting:** `simulate_chain_targets` counts `ints < win_count_exact` instead of
  comparing crash points, so that path *cannot* falsify the analytic threshold. I broke the
  circularity two ways (exact boundary re-evaluation at `n−1`/`n` for 29 targets, and a 1M-round
  crash-point recount through `HashChain`) — the shortcut is exactly equivalent. Flagging it as a
  methodological weakness of the shipped gate, not a defect.
- **Vacuous checks:** `std_per_unit` empirical is `w·√(p̂(1−p̂))`, algebraically determined by the
  win rate, so comparing it to `analytic_std_per_unit` adds zero information beyond the z-test.
  Harmless, but it is decoration, not a check.
- **Dead branches:** `win_count`'s `return 0` and `return TWO32` are unreachable given
  `1 < w ≤ 1e6`. Cosmetic.
- **Memory:** bulk chunk = 2M float64 (~16 MB/array, 3 live); chain 10M = one int64 array + its
  reversed copy ≈ 160 MB peak. Both well under the 500 MB rule.
- **Edge cases:** `n_rounds ≤ 0` rejected; chain exhaustion raises; `build_hash_chain(len<2)` and
  `len > 2,000,000` rejected; `crash_point_from_int` rejects out-of-range; `crash_point_from_float`
  rejects 1.0. Targets 1.000000000000000 2 through 1,000,000 all behave.
- **WoO handling:** correct. `references/woo/crash.md` is JetX (97% / 3% edge / tick mechanism) and
  is printed as a labelled comparison table whose `pass` depends only on the *shape*
  (P = RTP/w, flat edge) and the Wizard's own 3× worked example — never on the 97% number matching.
  That is the right call and it is documented in three places.

---

## 6. Findings, ranked

**F1 (biggest gap, blind-visible). Freshly generated chains default to Stake's already-public
2019 salt, inverting the commitment ordering the reference names as the whole point.**
`HashChain.__init__(salt=STAKE_SALT)` and `simulate_chain_targets(salt=STAKE_SALT)` bind a chain
created *now* to Bitcoin block 584,500 (mined 2019-07-21). The reference: *"a future bitcoin block
as a client seed so players can be certain that we did not pick one in the house's favor."* With
the salt known in advance the guarantee is void — a house could grind `secret_seed` until the
resulting 10M-round outcome sequence suits it. Nothing in the module says so; the docstring
presents the salt as a neutral constant. This is the one cell in the blind side-by-side that
identifies ours as the imitation.
*Fix:* keep `STAKE_SALT` only for replaying/verifying Stake's own 2019 chain; make the salt a
**required** argument whenever a new chain is generated, record the commitment order
(`terminating_hash` published at t₀, salt from a block after t₀) in the `verification` dict, and
emit a warning if a caller pairs a fresh chain with a salt that predates it.

**F2. The shipped validator's empirical gate is thinner than the engine deserves.** It tests
7 marginal tail probabilities on **one** fixed seed pair per mechanism, and never tests the
crash-point *distribution* as a distribution. Every distribution-level test I added passes
comfortably (§3), so this is an evidence gap, not an engine gap — but as the artifact that stands
for "we validated this", it should carry a χ² / KS goodness-of-fit over multiplier bands, the
empirical instant-bust rate with its z, and a multi-seed sweep. ~30 lines.

**F3. Empirical coverage stops at w = 1000.** The analytic table runs to 1,000,000× but the
`DEFAULT_TARGETS` sim grid stops at 1000×, which is exactly where the 32-bit quantization becomes
visible (|RTP−0.99| grows from 1.5e-7 at w=1000 to 4.1e-6 at w=1e6). I ran 10M rounds at
10⁴/10⁵/10⁶ and all pass (§3, Run B), so extend `DEFAULT_TARGETS` — it costs nothing and closes
the "conveniently avoided regime" objection.

**F4. No public vectorized crash-point generator.** `simulate_targets` computes the whole
crash-point array and throws it away, returning only aggregated win counts; the only public way to
get a crash-point *sequence* is `HashChain.crash_points`, which is O(n) Python and capped at 2M by
`_MAX_STORED_CHAIN`. Anything downstream that wants manual cashout, laddering, two simultaneous
bets, or a multiplier histogram has to re-derive the formula. A public
`crash_points(n, bulk=…) -> np.ndarray` would fix it.

**F5 (nit, unresolved). Crash points are emitted at full float precision** (`3.3712893041231235`).
Real Stake histories are 2-decimal (`3.37`). The reference is silent on display rounding, so I am
**not** scoring this as a mismatch — and it is provably payout-neutral: for any 2-decimal target
`w`, `floor(raw·100)/100 ≥ w ⟺ raw ≥ w`. Worth a one-line note in the module either way.

**F6 (nit). `build_hash_chain` cannot build the published 10,000,000-hash chain** (`_MAX_STORED_CHAIN`
= 2,000,000), so per-game hashes for a Stake-scale chain are not retrievable — only the streaming
aggregate path reaches that size. The streaming path *does* run 10,000,001 in the validator, so
the published scale is exercised; only random access to a game hash is missing.

---

## 7. Bottom line

The math is right and I could not break it: formula bit-verbatim against a from-scratch
RFC-2104 reimplementation, `win_count` exact against rational arithmetic at every target from
1.000001× to 1,000,000×, worst RTP deviation 1.4e-5 and always below the 32-bit bound, 12M+
independent rounds inside 3 SE at ten targets with worst \|z\| = 2.680, uniformity χ² p = 0.607,
band-level GOF p = 0.177, and no seed shopping. On numbers alone this piece would win.

It loses the blind on one behavior: **a 2026 chain committed to a 2019 salt.** Fix the salt
commitment ordering and this is a round-2 win.
