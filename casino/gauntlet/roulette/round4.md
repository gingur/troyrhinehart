# Roulette — Gauntlet Round 4 (independent critic)

Reviewer: fresh-eyes critic, round 4/4. Ground truth: `references/stake/roulette.md`
(payouts, RNG, colors) and `references/woo/roulette.md` (SD / methodology). Nothing
from the builder's tests, docstrings or validator output was taken on trust: every
number below was recomputed from the reference tables by hand or re-simulated with
throwaway scripts, including an independent from-scratch port of Stake's published
`byteGenerator`/`generateFloats` JS.

**Verdict: ours does NOT quite win — by one line of code.** Every payout, probability,
RTP and SD reproduces the references exactly (or, in one cell, correctly where the
reference file is wrong); 136M independently simulated spins across 11 fresh random
seeds clear the 3-SE bar with room to spare; the blind comparison favours ours. The
piece is blocked only by a residual public-API defect: `simulate(n, chunk_rounds=0)`
spins forever with no error — the last unguarded parameter of the same class the round-1
critique already flagged on its sibling.

---

## What I did

| Check | Method |
|---|---|
| Analytic recompute | Hand-typed Stake §5 into a throwaway `Fraction` script; derived P(win), RTP, edge, per-unit SD from scratch; recomputed WoO's **published** double-zero SDs (0.998614 / 5.762617) with the same formula to pin his convention |
| Paytable diff | Cell-by-cell diff of my model vs `full_payout_table()` / `Roulette` properties, 13 types × 6 cells, plus all 157 enumerated bets |
| RNG fidelity | Own HMAC-SHA256 port from the reference JS vs scalar path (8 nonces incl. 2^31, 2^40), vs `BulkRng` (2×2000 nonces from two starts), vs `play_round` (50 nonces); exact 2^32-lattice analysis of `floor(f*37)` at all 108 boundary points |
| Shipped validator | `scripts/validate_roulette.py` run unmodified (default seed **and** `--fresh-seed`), plus `--rounds 0`, `--rounds 100000`, `--skip-sim`, `python -O`, conflicting flags |
| Independent empirical | 8 fresh random 64-hex server seeds × **12,000,000** spins, all 157 bets settled through the public `payouts_for_pockets`, z recomputed here from raw payout sums (never from the engine's `z_score`/`within_3se`) |
| Gate-design null study | 20,000 synthetic campaigns drawn from `multinomial(10M, 1/37)` (a perfect wheel, no HMAC) put through the validator's two gates |
| Extra statistics | lag-1 37×37 pair chi-square (1368 dof) and red/black runs test over 10M spins; 10M-spin multi-bet basket vs an exactly-computed basket variance |
| Fudge hunt | grep for baked-in RTP/edge/SD constants; read every line of `games/roulette.py`, `validate_roulette.py`, `tests/test_roulette.py`; degenerate-input sweep of the public API |

Engine spins simulated by me: **136,000,000** (96M multi-seed 157-bet + 10M independence
+ 10M basket + 20M validator). Wall clock ≈ 11 min on 4 cores.

---

## Payouts / probabilities — PASS, exact, worst diff 0.0

My independent model, built only from the reference table, against the engine:

| Bet | Cov | Odds | Mult | P(win) | RTP | SD/unit | engine |
|---|---|---|---|---|---|---|---|
| Straight up | 1 | 35:1 | 36x | 1/37 | 36/37 | 5.837838 | exact |
| Split | 2 | 17:1 | 18x | 2/37 | 36/37 | 4.070238 | exact |
| Street | 3 | 11:1 | 12x | 3/37 | 36/37 | 3.275515 | exact |
| Corner | 4 | 8:1 | 9x | 4/37 | 36/37 | 2.794652 | exact |
| Line | 6 | 5:1 | 6x | 6/37 | 36/37 | 2.211597 | exact |
| Dozen / Column | 12 | 2:1 | 3x | 12/37 | 36/37 | 1.404366 | exact |
| Red/Black, Odd/Even, High/Low | 18 | 1:1 | 2x | 18/37 | 36/37 | 0.999635 | exact |

- Max |engine − reference| over every cell of every type: **0.0** (multipliers) and
  **< 1e-15** (SDs vs my `sqrt(E[X²] − EV²)`).
- All **157** legal bets return `rtp_exact == Fraction(36, 37)` and
  `multiplier_exact == Fraction(36, coverage)` — exact rationals, no float slop.
  1/37 → 2.7027% rounds to the published 2.70%; 36/37 → 97.2973% → 97.30%.
- Full-wheel identity independently verified: settling each of the 157 bets over one
  pass of the wheel (`np.arange(37)`) returns exactly 36.0 — for all 157.
- Colors match the reference lists verbatim; 0 is green and loses every outside bet
  (exactly 7 bets cover 0: straight-0, 3 zero splits, 2 trios, first four).
- The American five-number bet is refused. No hardcoded RTP/edge/SD constant exists in
  `games/roulette.py`: every figure derives from `coverage` and `PAYOUT_ODDS`.

**The one cell where ours differs from the reference file, ours is right.** WoO's
single-zero straight-up SD is printed as `5.837800`; the closed form of his own formula
is 216/37 = **5.8378378**. I confirmed the convention by reproducing his *published*
double-zero figures with the identical formula: 0.998614 and 5.762617, both exact to
6 dp. So the reference cell is a 5th-decimal slip and the engine's 5.837838 is correct;
the validator now says so explicitly instead of hiding it behind 4-dp rounding
(round 1's finding #5 — resolved).

## RNG — PASS, verified against my own port, not theirs

- My from-scratch port of the published JS reproduces the pinned vector
  (`'a'*64` / `clientseed` / nonce 1 → float 0.4767664363607764 → pocket 17) and agrees
  with the engine's scalar path at every nonce tried, including 2^31 and 2^40.
- `BulkRng.roulette_pockets` == my port over 2×2000 consecutive nonces from starts 0 and
  5,000,000; `play_round` == my port over 50 nonces including payout settlement.
- Serial vs 4-process output byte-identical over 600k spins.
- One float, cursor 0, one nonce per spin — matches "Games with only 1 incremental number".
- `floor(float*37)` in float64 equals the exact integer partition at all 108 lattice
  boundary points; max float → pocket 36, never 37.
- Lattice: 2^32 mod 37 = 7, so pockets {0, 5, 10, 15, 21, 26, 31} carry one extra
  lattice point out of 116,080,197. True straight-up RTP ∈ [0.972972971387,
  0.972972979769]. This is inherent to Stake's own algorithm and the module now
  documents it (round 1's finding #6 — resolved), though the docstring's stated
  "maximum relative deviation ... ≈ 8.6e-9" is a loose bound: the actual maximum is
  **6.985e-9**.
- Independence, 10M spins: lag-1 37×37 contingency χ²(1368) = 1447.6 (z = +1.52,
  99.99% quantile 1571.1); red/black alternation rate 0.500095 (z = +0.59 over 9.73M
  colored spins); marginal χ²(36) = 30.8.

## Empirical bar — PASS on every fresh seed I threw at it

8 fresh random server seeds × 12M spins, all 157 bets settled through the public
`payouts_for_pockets`, z recomputed by me (SE = analytic per-bet SD / √N; 3-SE window
is ±0.0866 pp for even money, ±0.5056 pp for straight up at 12M):

```
13 bet types within 3 SE:   8/8 campaigns, 104/104 type-checks   worst |z| = 2.71
157-bet family, Sidak 4.298: 8/8 campaigns, 1256/1256 checks     worst |z| = 3.12
bets outside plain 3 SE:     mean 0.125 per run (null expectation 0.42)
uniformity χ²(36):           max 44.7 over 8 runs (99.99% quantile 76.4)
empirical vs analytic SD:    max relative error 0.0024 (straight up, ≈ 2.2 SE of ŝ)
```

Worst single observation over 96M spins: `low` at 97.37563% (z = +2.71) against a 3-SE
window of [97.2107%, 97.3839%]. The shipped validator passes on the default seed
(worst type z = +2.35) and on a fresh one (worst type z = +1.92; one of 157 bets at
z = +3.50, correctly reported as informational and inside the family bound).

The seed-shopping problem that sank round 1 is genuinely fixed. My null study (20,000
perfect-wheel campaigns at 10M) confirms the new design: the Sidak family gate fires on
**0.20%** of honest runs (target 0.27% — slightly conservative because the 157 tests are
positively correlated), against **23.0%** for the bare 3-SE-over-157 gate the previous
version shipped. The validator's printed expectation of 0.42 offenders per run is also
right (my measured mean: 0.418).

---

## Findings — what still separates this from reference-grade

### 1. (Blocker) `simulate(n, chunk_rounds=0)` hangs forever

```python
Roulette("red").simulate(10, chunk_rounds=0)   # never returns; no error, no output
```

`step = min(chunk_rounds, n_rounds - done)` is 0, `rng.roulette_pockets(0)` returns an
empty array, `done` never advances. Every other degenerate input on this path is
guarded — `n_rounds <= 0` raises, `chunk_rounds=-1` raises inside `_take_nonces`,
out-of-range pockets raise both ways — which is exactly why the gap is conspicuous:
this is the same bug class as round 1's finding #2 (an unvalidated public-API parameter
producing non-error misbehaviour), fixed on `payouts_for_pockets` and missed one method
below. A silent infinite loop is strictly worse than the wrong number it replaced.
One line: `if chunk_rounds <= 0: raise ValueError(...)`.

### 2. No independent variance test exists anywhere in the piece

For a single roulette bet the payout is two-valued, so the "empirical SD" column the
validator prints beside every RTP,

```
sd_emp = multiplier * sqrt(p̂ (1 − p̂))
```

is a **deterministic function of the win rate that produced the RTP in the same row**.
It cannot disagree with the RTP check; it is the RTP check restated. So although the bar
asks for "SDs per bet vs WoO figures", the piece has *zero* empirical variance evidence —
only an analytic identity (which is exact) and a redundant column dressed as a check.
The one place roulette variance is genuinely testable is a **basket of simultaneous
bets**, where the covariance structure matters — and `settle_bets()` (the API added in
response to round 1) is never simulated by the validator at all. I ran that test myself,
10M spins on a 10-bet basket including overlapping and zero-covering bets, against a
basket variance I computed exactly over the 37 pockets:

```
mean 9.724825 vs exact 360/37 = 9.729730   z = -1.47
SD  10.547977 vs exact      10.548853      z = -0.27   (SE 0.003189, kurtosis 4.656)
```

So `settle_bets` is correct — but that is my evidence, not the piece's, and the engine
offers no analytic counterpart (no basket EV/variance function) to test against. Note
also 10.5489 ≠ 9.3718 = √Σvar: the covariance term is 27% of the variance, so this is
information nothing else in the piece captures.

### 3. The stated 13-type 3-SE gate still flakes ~1 run in 38

Measured on 20,000 perfect-wheel campaigns: the 157-bet family gate fires on 0.20% of
honest runs, but gate (a) — 13 correlated bet types, each at a bare |z| ≤ 3 — fires on
**2.62%** (max|z| p50 = 1.78, p99 = 3.31). That is the bar as literally stated, so it is
not a defect; but the validator computes and prints the null expectation for the 157-bet
family and not for the 13-type gate it actually gates on, which is the asymmetry a
reference-grade report would not leave. Printing "expected false-alarm rate 2.6%" beside
bar (a) costs one line and makes the headline claim honest about itself.

### 4. Trio and basket are shipped under the wrong bet names

Round 1's catalogue incoherence is fixed — 0-1-2, 0-2-3 and 0-1-2-3 are now legal and
the catalogue is the standard 157. But they are folded into existing types, so a trio is
`Roulette("street", (0,1,2))` and reports `bet_type: "street"`, `payout_odds: "11:1"`,
and the validator prints the catalogue as "14 street (incl. 2 zero trios), 23 corner
(incl. first four)". No roulette reference ever says a European mat has 14 streets and
23 corners; it says 12 streets, 2 trios, 22 corners, 1 basket. The numbers are all right
(coverage 3 and 4, RTP 36/37), only the nomenclature is invented — and `bet_type` is a
user-visible field in every `config()` and every round record.

### 5. Smaller notes

- Duplicate pockets in a selection are silently collapsed: `Roulette("street", (1,1,2,3))`
  is accepted as street (1,2,3), `Roulette("split", (1,2,2))` as split (1,2). A 4-element
  "street" should not validate.
- `--skip-sim` exits 0 with `passed: true` and no empirical gate at all; a caller parsing
  only `passed` gets a green light with no simulation behind it. (`gates` lacks the
  `empirical` key, so it is detectable — but only if you look.)
- On a rejected under-powered run (`--rounds 100000`), the JSON still reports
  `empirical_3se_types: true` / `empirical_family: true` from the 100k campaign. The
  aggregate is correctly false, but those sub-keys assert a bar that was not met.
- `settle_bets` reaches into `bet._mask`; a non-`Roulette` element gives
  `AttributeError: 'object' object has no attribute '_mask'` rather than a typed error.
- `tests/test_roulette.py::test_std_matches_woo_figures` still compares the straight-up
  SD to the reference cell at 4 dp while holding the even-money one at 6 dp — the
  asymmetric rounding the validator has since stopped doing.
- Module docstring's lattice bound "≈ 8.6e-9" overstates the true maximum, 6.985e-9.
- `harness.py`, `selector.py`, `session.py`, `sizing.py`, `report.py` and the MCP server
  are all still 1-line stubs, so roulette is wired into nothing. Project-wide, not this
  piece's fault — noted for scope, unchanged since round 1.

---

## Blind comparison (labels stripped)

Two unlabeled columns, one built by parsing the reference `.md` files, one emitted by
the engine, restricted to content the references actually publish:

```
--------------------------------- COLUMN X ---------------------------------
  Straight up        1   35:1   36x    1/37  36/37 = 97.30%   5.837838
  Split              2   17:1   18x    2/37    97.30%
  ... (Street 11:1 / Corner 8:1 / Line 5:1 / Dozen 2:1 / Column 2:1) ...
  Red / Black       18    1:1    2x   18/37    97.30%         0.999635
  Odd / Even        18    1:1    2x   18/37    97.30%         0.999635
  High / Low        18    1:1    2x   18/37    97.30%         0.999635
  house edge 2.70%   RTP 97.30%   European single zero, 37 pockets
  pocket = floor(float * 37); float = b0/256+b1/256^2+b2/256^3+b3/256^4; cursor 0
  red: 1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36
--------------------------------- COLUMN Y ---------------------------------
  (identical, cell for cell, except:)
  Straight up        1   35:1   36x    1/37  36/37 = 97.30%   5.837800
----------------------------------------------------------------------------
```

**Could an expert tell?** Every payout, multiplier, coverage, probability, RTP, house
edge, color list and RNG formula is identical — a coin flip. The single differing cell
is the straight-up SD, and an expert who evaluates 216/37 marks **Y** as the column with
the arithmetic error. Y is the reference file. So the blind test does not identify ours
as the imitation anywhere, and on the one cell where they diverge it favours ours. The
round-1 tell (the catalogue line) is gone; the residual nomenclature issue (finding #4)
only shows up in the engine's own catalogue enumeration, which no reference publishes,
so it does not enter this comparison.

## Scoreboard

| Gate | Result |
|---|---|
| Payout / probability, 13 types vs Stake §5 | **PASS** — max diff 0.0 |
| Analytic RTP, all 157 legal bets = 36/37 exactly | **PASS** |
| WoO SD, formula + printed figures (incl. his double-zero cells) | **PASS** — ref's 5.837800 cell is the ref's error |
| RNG vs my own port of the published JS (scalar, bulk, play_round, lattice) | **PASS** |
| Empirical 3 SE, 13 types, 12M spins × 8 fresh seeds | **PASS** — 104/104, worst \|z\| 2.71 |
| Empirical family, 157 bets × 8 fresh seeds | **PASS** — 1256/1256, worst \|z\| 3.12 |
| Uniformity / lag-1 independence / runs | **PASS** |
| Multi-bet basket mean and variance (my exact model) | **PASS** — z −1.47 / −0.27 |
| Seed-honesty of the shipped gates | **PASS** for the family gate (0.20% vs 0.27% target); 2.6% flake on the stated 13-type bar |
| Public-API robustness | **FAIL** — `simulate(chunk_rounds=0)` hangs forever |
| Independent variance validation | **ABSENT** — per-bet "empirical SD" is a restatement of the RTP check; basket API never simulated |
| Bet nomenclature | **FAIL (cosmetic)** — trio/basket shipped as "street"/"corner" |

## The one change that most closes the distance

**Guard the degenerate chunk size in `Roulette.simulate` (`chunk_rounds <= 0` → raise),
and while in there, add the basket variance the piece is missing.** The guard is the
only *failing* check in this round and the only thing between the piece and a clean win:
a public simulator that hangs silently on a degenerate argument is not reference-grade,
and it is the last survivor of exactly the bug class round 1 already made the builder
fix one method away. The second half is what would make the empirical bar mean what it
claims: give `settle_bets` an analytic partner (basket EV and variance over the 37
pockets) and have the validator settle one mixed basket through it for the 10M-spin
campaign. That is the only variance evidence roulette can actually produce — everything
the piece currently prints under "SD" is either an exact identity or the RTP column
wearing a hat.
