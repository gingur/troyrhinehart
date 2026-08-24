# Roulette — Gauntlet Round 1 (independent critic)

Reviewer: fresh-eyes critic. Ground truth: `references/stake/roulette.md`,
`references/woo/roulette.md`. Nothing from the builder's own tests was trusted; every
number below was recomputed or re-simulated with throwaway scripts written from the
reference tables by hand.

**Verdict: ours does NOT win round 1.** The engine's math is exact and the empirical
bar is met, but the shipped validator's headline claim is a property of one hardcoded
seed, the bet catalogue is internally incoherent versus a real European mat, and one
public settlement method returns a silent wrong answer.

---

## What I did

| Check | Method |
|---|---|
| Analytic recompute | Hand-typed the 10 rows of Stake §5 into a throwaway `Fraction` script; derived RTP, house edge, per-unit SD from scratch |
| Paytable diff | Compared my model cell-by-cell to `full_payout_table()` / `Roulette` properties for all 13 types |
| Builder's validator | Ran `scripts/validate_roulette.py` unmodified |
| Independent sim (public API) | `Roulette.simulate(12_000_000)` per bet type on a fresh random server seed; z recomputed from the returned raw `pocket_counts`, never from the engine's own `z_score` |
| Seed robustness | 8 fresh seeds × 12M spins (all 154 bets); 20 fresh seeds × 10M spins (13 canonical types) |
| RNG mapping exactness | Full 2^32 float-lattice analysis of `floor(float*37)`, boundary points, bulk-vs-scalar at nonces 0 / 2M / 8M / 2^31 / 2^40, serial vs 4-process |
| Fudge hunt | grep for hardcoded RTP/edge constants; read every line of `games/roulette.py` and `validate_roulette.py` |

Total spins simulated: **~462M** (156M public-API + 96M multi-seed 154-bet + 200M
multi-seed per-type + 10M validator). Wall clock ≈ 8 min 10 s on 4 cores.

---

## Payout ground truth — PASS, exact

Every published cell reproduces exactly. Max |engine multiplier − (published odds + 1)|
= **0.0** across all 13 types.

| Bet | Cov | Odds | Mult | P(win) | RTP | ours matches |
|---|---|---|---|---|---|---|
| Straight up | 1 | 35:1 | 36x | 1/37 | 36/37 | yes |
| Split | 2 | 17:1 | 18x | 2/37 | 36/37 | yes |
| Street | 3 | 11:1 | 12x | 3/37 | 36/37 | yes |
| Corner | 4 | 8:1 | 9x | 4/37 | 36/37 | yes |
| Line | 6 | 5:1 | 6x | 6/37 | 36/37 | yes |
| Dozen / Column | 12 | 2:1 | 3x | 12/37 | 36/37 | yes |
| Red/Black, Odd/Even, High/Low | 18 | 1:1 | 2x | 18/37 | 36/37 | yes |

`rtp_exact` is a `Fraction(36,37)` for all 154 enumerated bets — exact rational, no float
slop. 1/37 → 2.7027% rounds to the published 2.70%; 36/37 → 97.2973% rounds to 97.30%.
Red/black lists match the reference verbatim. Zero correctly loses odd/even/high/low.
The American five-number bet is correctly refused (`Roulette("five_number")` raises).

**No hardcoded empirical results found.** No RTP/edge constant is baked into the engine;
every number derives from `coverage` and `PAYOUT_ODDS`. The simulator genuinely runs
through `BulkRng`, which is genuinely the verified HMAC stream (checked below).

## RNG / mapping — PASS, and stronger than it claims

- `floor(float*37)` is exact in float64 at **every one of the 74 lattice boundary points**
  (`k·37 < 2^38` is integral, so no rounding can cross an integer). Max float
  0.9999999997671694 → pocket 36, never 37.
- Bulk == scalar at nonce_start 0, 1,999,999, 8,000,000, 2^31 and 2^40 (64 spins each) —
  the validator only checks nonces 0..249, so I extended it.
- 4-process parallel output byte-identical to serial over 600k spins.
- One float, cursor 0, one nonce per spin — matches the reference's "1 incremental number".

## Empirical bar — PASS as stated (13 bet types)

My own 12M-spin run per type, fresh random seed, through `Roulette.simulate()`
(the public API the validator never exercises), z recomputed independently:

```
straight 96.8292% z -2.78 | split 97.0022% z -2.51 | street 97.0860% z -2.23
corner   97.1419% z -1.93 | line  97.1801% z -1.84 | dozen  97.2393% z -1.43
column   97.3405% z +1.06 | red   97.2700% z -0.95 | black  97.3206% z +0.81
odd      97.2953% z -0.07 | even  97.2952% z -0.07 | low    97.2613% z -1.25
high     97.3293% z +1.11
```

Worst |z| = 2.78 (straight up; SE = 5.837838/√12M = 0.0016853, so the 3-SE window is
97.2973% ± 0.5056 pp = [96.7917%, 97.8029%] — 96.8292% is inside).
Empirical per-unit SDs track analytic to ≤0.24% relative on every type.
Repeating the per-type bar on **20 more fresh seeds × 10M spins: 0/20 failures**,
max|z| over all 260 type-checks = 2.80. The engine is statistically clean.

---

## Findings — why this is not yet reference-grade

### 1. (Biggest) The validator's headline gate is a property of the committed seed, not of the engine

`validate_roulette.py` Gate 5 asserts **all 154 individual bets** land within 3 SE and
exits non-zero otherwise, using a hardcoded `DEFAULT_SERVER_SEED`. On that seed it passes
with worst |z| = 2.66. On **8 fresh random seeds at 12M spins each it failed 3 times**:

```
seed 2f89cedb8142  worst|z| 3.24  split (4,5)              1 offender
seed 9973c4741849  worst|z| 3.50  corner (8,9,11,12)       2 offenders
seed a64a0280dbdc  worst|z| 3.03  straight 24              1 offender
(5 other seeds clean; 4 offenders total)
```

This is exactly the predicted rate, not a bug in the wheel: 154 near-independent
two-sided 3-SE tests give E[offenders] = 154 × 0.0027 = **0.416** and
P(≥1) = **34.1%** — observed 3/8. So the shipped script fails roughly one run in three
on any seed that was not pre-selected, and the "154/154 within 3 SE" line in its output
is a coin-flip claim presented as a gate. That is the seed-shopping smell the audit was
looking for, and it is the single thing that makes the piece untrustworthy on re-run.
Fix: gate the family at a family-wise-corrected bound (Šidák/Bonferroni for 154 tests at
family α = 0.0027 → **|z| ≤ 4.294**), or gate the 13 bet *types* (the stated bar; 0/20
seeds fail), and report the max-|z| distribution against its own null instead of a bare
pass/fail. Either way the default seed should stop being load-bearing.

### 2. Silent wrong answer on negative pocket indices (correctness bug)

```python
Roulette("red").payouts_for_pockets(np.array([37]))   # IndexError  (good)
Roulette("red").payouts_for_pockets(np.array([-1]))   # -> array([2.])  (WRONG)
```

`self._mask[pockets]` lets numpy wrap negatives: −1 indexes pocket 36, which is red, so a
nonsense pocket **pays a full win**. Out-of-range high is caught, out-of-range low is not.
Any caller feeding a signed sentinel, an int8 overflow, or a masked/-1 "no spin" row gets
fabricated wins with no error. One-line fix (`if pockets.min() < 0: raise`), but it is a
public settlement method returning money for an impossible outcome.

### 3. Bet catalogue is internally incoherent versus a real European mat

The engine accepts the three **zero splits** (0-1, 0-2, 0-3), justified in its own
docstring as "0 borders the whole first row on the European mat" — a piece of domain
knowledge the Stake reference never states. Having accepted that adjacency, it then
rejects the bets that follow from the identical adjacency:

- **trio** 0-1-2 and 0-2-3 (street payout 11:1, coverage 3) — `ValueError`
- **basket / first four** 0-1-2-3 (corner payout 8:1, coverage 4) — `ValueError`

Standard European catalogue = 157 bets; ours = 154. Both missing shapes have
coverage 3 and 4, so RTP is unaffected (36/37 either way) — the defect is credibility,
not math. It is also the one cell that gives ours away blind (see below).

### 4. Chi-square threshold is mislabeled

`check(chi2 < 79.0, ... # 99.99% quantile, 36 dof)`. The true χ²(36) 99.99% quantile is
**76.365**; P(χ²₃₆ > 79.0) = 4.66e-05, i.e. 79.0 is the 99.9953% point. The test is
looser than its own comment claims. Cosmetic, but it is a wrong number in a file whose
whole purpose is being right about numbers.

### 5. The WoO SD discrepancy is papered over rather than resolved

Engine: 5.837838. Reference prints **5.837800**. The engine is right — the exact closed
form is **216/37 = 5.8378378…**, and generally SD = 36·√((37−c)/c)/37 — while the
reference's derived cell is simply wrong in the 5th decimal (WoO's own double-zero figure
5.762617 is correct to 6 dp, so 6 dp is his convention). The validator "passes" by
comparing that one number at **4 dp** while holding the even-money number at **6 dp**.
The asymmetry is documented in a comment, which is honest, but the right move is to state
the closed form 216/37, flag the reference cell as a rounding error, and compare both at
6 dp against the formula.

### 6. Smaller notes

- **Lattice bias undocumented.** 2^32 mod 37 = 7, so 7 of 37 pockets carry one extra
  lattice point. True straight-up RTP is 0.972972971387…0.972972979769, not exactly 36/37
  (max relative deviation 6.99e-09 — undetectable at 10M). This is inherent in Stake's own
  published algorithm, so the engine is faithful; but `rtp_exact → Fraction(36,37)` and the
  docstring's "exact RTP" assert an idealized wheel with no note that the implemented one
  is a 2^32 lattice. A reference-grade module says so.
- **Gate 5 bypasses the engine's settlement path.** The validator's 154-bet campaign
  settles with its own `counts[sorted(eng.covered)].sum()` numpy, not
  `payouts_for_pockets` or `simulate`. It reads `covered`/`multiplier` from the engine so
  it is not a fake sim, but the public settle method is exercised only by one 5-element
  unit test — which is why finding #2 survived.
- **No multi-bet API.** `payouts_for_pockets` advertises "shared-spin evaluation across
  bets" in its docstring, but nothing in the engine settles a basket of simultaneous bets
  on one spin — the normal way roulette is actually played. `simulate()` handles exactly
  one bet.
- `simulate(1)` happily returns `z_score = 1.03, within_3se = True` for a single spin.
  Harmless, but a 1-round "within 3 SE" verdict is meaningless output.
- The rest of the stack (`harness.py`, `selector.py`, `session.py`, `sizing.py`,
  `report.py`) is a 1-line stub, so roulette is not wired into anything. Project-wide, not
  this piece's fault — noted for scope.

---

## Blind comparison (labels stripped)

Two unlabeled artifacts, one built from the references, one emitted by the engine:

```
------------------------------- COLUMN X -------------------------------
  Straight up       1   35:1   36x    1/37   97.30%    5.837800
  Split             2   17:1   18x    2/37   97.30%
  ...
  Red / Black      18    1:1    2x   18/37   97.30%    0.999635
  catalogue: 37 straight | 60 split | 12 street + 2 trios | 22 corner + 1 basket
             | 11 line | 3 dozen | 3 column | 6 even-money   = 157
------------------------------- COLUMN Y -------------------------------
  Straight up       1   35:1   36x    1/37   97.30%    5.837838
  Split             2   17:1   18x    2/37   97.30%
  ...
  Red / Black      18    1:1    2x   18/37   97.30%    0.999635
  catalogue: 37 straight | 60 split | 12 street | 22 corner
             | 11 line | 3 dozen | 3 column | 6 even-money   = 154
------------------------------------------------------------------------
```

**Could an expert tell?** On the payout/probability/RTP block: no — every cell is
identical, coin flip. On the SD cell: they'd flag X as arithmetically wrong (216/37), so
that cell favours **Y** (ours). On the catalogue line: **yes, instantly.** A roulette
expert sees a mat that offers the 0-1 split but refuses the 0-1-2 trio and the 0-1-2-3
basket and knows immediately that Y was assembled by someone working from a payout list
rather than from a betting layout. Column Y is identifiable as the imitation on one line,
so the blind test does not come out a coin flip.

## Scoreboard

| Gate | Result |
|---|---|
| Payout / probability, all 13 types vs Stake §5 | **PASS** — max diff 0.0 |
| Analytic RTP, all 154 enumerated bets = 36/37 exactly | **PASS** |
| WoO SD formula sqrt(E[X²]−EV²) | **PASS** (ref's printed 5.837800 is the ref's error) |
| Bulk == scalar provably-fair stream | **PASS**, extended to nonce 2^40 and 4-way parallel |
| Empirical 3 SE, 13 bet types, 10M+ | **PASS** — 0/20 fresh seeds fail, worst \|z\| 2.80 |
| Empirical 3 SE, all 154 bets, 10M+ | **SEED-DEPENDENT** — 3/8 fresh seeds fail |
| Settlement API robustness | **FAIL** — negative pocket pays out |
| Bet catalogue completeness | **FAIL** — 154 of 157 European bets; incoherent about zero |

## The one change that most closes the distance

Replace the seed-fragile 154-bet 3-SE gate with a statistically honest one — family-wise
corrected bound |z| ≤ 4.294 for the 154-bet family (or gate the 13 bet types, which is
the stated bar and survives 20/20 fresh seeds) — and make the validator run a fresh
random seed by default with `--seed` only for reproduction. Right now the piece's
headline quality claim is a 66%-of-the-time claim dressed as a gate, and that is the
gap that most separates it from a reference-grade artifact.
