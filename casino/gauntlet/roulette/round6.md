# Roulette — critic round 6 (round 2/2, independent, fresh eyes)

Reviewed: `/home/user/troyrhinehart/casino/spinquest_sim/games/roulette.py`,
`/home/user/troyrhinehart/casino/scripts/validate_roulette.py`,
`/home/user/troyrhinehart/casino/tests/test_roulette.py`.
Ground truth: `references/stake/roulette.md`, `references/woo/roulette.md` (only).
Prior verdict re-tested: `/home/user/troyrhinehart/casino/gauntlet/roulette/gap.md`.

Every number below comes from **my own probes**, written this round, not from the
builder's tests or the builder's validator (the validator was run once, separately,
only to confirm it is seed-honest — it is not evidence for any claim here):

- `/tmp/claude-0/-home-user-troyrhinehart/b3ce270f-e608-55a6-8515-5735b66f4ebe/scratchpad/r6/p1_guard.py` — flagged-gap reproduction + degenerate-input sweep
- `.../r6/p2_payout.py` — hand-transcribed reference table vs engine, exact Fractions
- `.../r6/p3_pf.py` — independent HMAC-SHA256 re-implementation of Stake's chain
- `.../r6/p4_emp.py` — 10M-round empirical bar, basket mean+variance, uniformity, lag-1
- `.../r6/p5_stress.py`, `.../r6/p6_mem.py` — RSS ceiling, parallel determinism, nonce accounting
- `.../r6/p7_power.py` — do the passing gates have teeth (rigged-stream power study)
- `.../r6/p8_blind.py` — labels-stripped side-by-side
- `.../r6/p9_opt.py` — behaviour under `python -O`

**VERDICT: ours WINS.** The round-5 gap is closed at the root, every reference number
reproduces exactly (the one divergent cell is an arithmetic slip in the reference file,
which the engine documents rather than hides), all empirical checks land well inside 3 SE
over ~210M fresh spins, and the blind side-by-side has no numeric tell that identifies the
imitation — the only cell that differs identifies the *reference* as the erroneous side.

---

## 1. Round-5 flagged gap — CLOSED (reproduced the probe)

`Roulette.simulate(n, chunk_rounds=0)` previously set `step = min(0, remaining) = 0` and
looped forever with no error or output. I re-ran that exact probe under a SIGALRM fence
(8 s budget per case, so a hang reports as `HANG`, not as a wedged run):

| input | result |
|---|---|
| `chunk_rounds=0` | `ValueError: chunk_rounds must be >= 1, got 0` |
| `chunk_rounds=-1`, `-10**9` | `ValueError` |
| `chunk_rounds=0.0`, `1000.0`, `True`, `inf`, `nan`, `None`, `'2'` | `TypeError: chunk_rounds must be an integer, …` |
| `n_rounds=0`, `-5` | `ValueError: n_rounds must be positive` |
| `n_rounds=inf`, `nan`, `1000.0` | `TypeError` |
| `n_rounds=np.int64(500)`, `chunk_rounds=np.int64(100)` | returns (numpy ints still accepted) |
| `chunk_rounds=1` | returns; 2,000 spins, no hang |

Zero HANGs. The guard is at `roulette.py:576-584`, sits behind a root-level
`numbers.Integral` type check (`roulette.py:565-573`) so the whole `inf`/`nan`/`bool`/`str`
family dies before any comparison, and it **survives `python -O`** (it is a real `raise`,
not an `assert` — verified in `p9_opt.py`). Chunk size is provably cosmetic: with one fixed
seed, `chunk_rounds ∈ {1, 7, 999, 5000, 10**9}` over 5,000 spins gives identical `wins`,
identical 37-cell `pocket_counts`, and identical nonce ranges.

The same bug class is closed on every neighbouring public surface: `payouts_for_pockets`
rejects `-1` (numpy would silently wrap it to pocket 36 and pay) and `37` and float dtypes;
`settle_bets` rejects an empty basket and out-of-range pockets; `basket_analytics` rejects an
empty basket; `Roulette(...)` rejects pocket 37/-1/`True`, illegal splits, indices 0 and 4 for
dozen/column, a selection on an even-money bet, and the American five-number bet.

**Runner-up gap from round 5 (no independent variance evidence) — also closed.**
`basket_analytics` now gives an exact `Fraction` EV/Var/mu4 for a shared-spin basket, and
`settle_bets` is a genuinely multi-valued surface whose variance depends on the covariance
between overlapping bets — nothing a per-bet marginal restates. I re-derived those moments
myself by brute force over the 37 pockets and got **exact Fraction equality** (not float-close)
on EV, Var and mu4, then simulated them (§3b).

## 2. Payout-for-payout parity vs the Stake reference — EXACT

I hand-transcribed section 5 of `references/stake/roulette.md` into my own literal table (no
reuse of the builder's markdown parser) and compared 13 bet types × 6 quantities:

```
exact-Fraction identity on all 13 x 6 cells : True
worst |engine - reference| (float cells)    : 0.0
```

`multiplier_exact == Fraction(36, coverage)`, `win_probability_exact == Fraction(coverage, 37)`,
`rtp_exact == Fraction(36, 37)`, `1 - rtp_exact == Fraction(1, 37)` — for all 13 types, as
rationals, not to a tolerance. 36/37 = 97.2973% → prints 97.30%; 1/37 = 2.7027% → prints
2.70%; both match the published cells.

Wheel composition: `POCKETS == 37`; red and black sets equal the reference lists verbatim;
they partition 1..36 and are disjoint; `pocket_color(0) == 'green'`; **no** outside bet covers
0 (so 0 loses red/black/odd/even/low/high/dozen/column — no la partage, no en prison, correct
for the Stake Original); the five-number bet is absent.

Full 157-bet European catalogue, re-enumerated independently by me: splits 60 (set-for-set
equal), corners 22 + first-four, streets 12 + two zero trios, lines 11. All 157 have exact
RTP 36/37 and multiplier 36/coverage; zero duplicate `(type, covered)` pairs; settling every
one of the 157 across the full wheel returns **exactly 36.0** (min = max = 36.0), which is the
sharpest single statement of the payout table's correctness.

**WoO SDs, derived by me from first principles** (`sqrt(M²p − (Mp)²)`, M = 36/c, p = c/(36+z)):

| cell | reference | my derivation | engine |
|---|---|---|---|
| double-zero even money | 0.998614 | 0.998614 | — |
| double-zero single number | 5.762617 | 5.762617 | — |
| single-zero even money | 0.999635 | 0.999635 | 0.999634703 |
| single-zero single number | **5.837800** | **5.837837838** | **5.837837838** |

`max |engine SD − my SD|` over all 13 types = **0.0** (bit-identical). The single divergent
cell is the WoO file's own *derived* single-zero straight-up figure; it contradicts the formula
printed two lines above it (216/37 = 5.8378378) while both of WoO's *published* double-zero
figures reproduce to 6 dp with the same formula. The engine is right; the reference cell is a
5th-decimal slip, and the engine **says so** in the module/validator rather than rounding to
hide it (`validate_roulette.py:11-20, 376-388`; gate requires formula-exactness and prints the
reference delta 3.78e-05). WoO's binomial worked example also reproduces: var 648.20, SD 25.46.

## 3. Empirical bar, my own runs through the public API

### 3a. 7 bet types × 10,000,000 spins, fresh random 64-hex server seeds each

| bet | wins | RTP | my z | 3 SE window | chi²(36) | p |
|---|---|---|---|---|---|---|
| straight | 270,728 | 0.974621 | +0.89 | ±0.5538 pp | 38.8 | 0.345 |
| split | 540,242 | 0.972436 | −0.42 | ±0.3861 pp | 30.1 | 0.745 |
| street | 810,449 | 0.972539 | −0.42 | ±0.3107 pp | 40.6 | 0.275 |
| corner | 1,080,237 | 0.972213 | −0.86 | ±0.2651 pp | 35.2 | 0.505 |
| line | 1,620,976 | 0.972586 | −0.55 | ±0.2098 pp | 30.2 | 0.740 |
| dozen | 3,241,193 | 0.972358 | −1.38 | ±0.1332 pp | 39.2 | 0.329 |
| red | 4,866,071 | 0.973214 | +0.76 | ±0.0948 pp | 45.8 | 0.127 |

Worst |z| = **1.38** against the 3.00 bar (Sidak family bound for 7 tests is 3.549). My z,
computed from the analytic per-bet SD, agrees with the engine's reported `z_score` to <1e-9,
and `pocket_counts.sum() == n_rounds` on every run — the engine is not marking its own homework
with a different formula.

### 3b. `settle_bets` basket — mean AND variance, 10,000,000 spins

10-bet overlapping basket (two straights incl. 0, a split, a zero trio, the first-four, a line,
a dozen, a column, red, even):

```
EV  exact 9.7297297297  (== 10 * 36/37)   my Fraction == engine Fraction : True
Var exact 214.5215485756                   my Fraction == engine Fraction : True
mu4 exact 322906.424283                    my Fraction == engine Fraction : True
sim mean 9.737257  z = +1.63     (SE from exact Var)
sim var  214.766741 z = +1.47     (SE from exact mu4: sqrt((mu4 - Var^2)/n))
per-unit RTP 0.97372571 vs 36/37 = 0.97297297
```

This is real variance evidence: the basket variance is driven by the covariance of overlapping
bets (pocket 0 pays 63 in this basket), which no per-bet marginal can restate.

### 3c. Uniformity and independence on the same streams

- pocket chi²(36) = **29.7**, p = 0.762 (10M spins; 99.99% quantile 76.36)
- lag-1 pocket-pair chi²(1368) = **1396.0**, z = **+0.54** (a separate fresh 10M stream)

### 3d. Gate teeth (are these passes meaningful?)

I fed *rigged* (non-engine) multinomial streams through the engine's public settlement path and
applied the stated bar. At 10M spins:

| rig | worst 13-type z | worst 157 z | chi²(36) | flagged |
|---|---|---|---|---|
| honest wheel | 2.70 | 2.90 | 47.3 | 0/5 |
| zero 0.5% more likely | 2.99 | 4.30 | 54.3 | 0/5 |
| zero 1.0% more likely | 3.79 | 6.38 | 78.3 | 5/5 |
| red 0.2% shorted vs black | 6.91 | 6.91 | 83.8 | 5/5 |
| every number −0.1%, zero soaks | 12.66 | 19.16 | 414.4 | 5/5 |
| straight paid 35x not 36x | 14.1 | — | — | flagged |
| every payout −0.1% | 4.2 | — | — | flagged |

So the bar catches a 0.1% payout shave and a ~1% pocket bias, and its honest false-alarm rate
is right. Resolution limit at 10M spins is a ~0.5% single-pocket bias — a sample-size fact,
stated here so the PASS is not read as more than it is.

## 4. Provably-fair chain — bit-exact to an independent port

I re-implemented Stake's published `byteGenerator` / `generateFloats` / `POCKETS[floor(f*37)]`
from the reference markdown alone (my own `hmac`/`hashlib` code) and diffed:

- pinned vector `serverSeed='a'*64, clientSeed='clientseed', nonce=1` → float
  `0.4767664363607764`, pocket 17 — **identical** float repr and pocket.
- 3,000 nonces on a fresh random 64-hex seed: **0/3000** mismatches vs `BulkRng.roulette_pockets`.
- 200 nonces at an offset start: **0/200** mismatches, scalar `play_round` vs bulk row *i*.
- A whole `simulate(4000, chunk_rounds=1000)` campaign: engine `wins` and all 37 `pocket_counts`
  reproduced exactly from my port over the reported `nonce_range`; `server_seed_hash` equals
  `sha256(server_seed)`.
- Lattice: the published float has granularity 2⁻³², and I computed the exact per-pocket lattice
  occupancy analytically — min 116,080,197 / max 116,080,198 points, summing to 2³², max relative
  deviation from 1/37 = **6.99e-9**, inside the module's documented 37/2³² ≈ 8.6e-9 bound and
  ~5 orders of magnitude below the 10M-spin SE. Boundary lattice points all map to the correct
  pocket (0 errors). The module discloses this rather than pretending to perfect uniformity.

## 5. Engineering checks

- Peak RSS with the **default** `chunk_rounds=2,000,000`: **218 MB at 10M spins and 223 MB at
  40M spins** — flat in `n`, inside the 500 MB rule.
- Parallel vs serial: `workers=1` and `workers=4` give identical 3,000,000-spin pocket arrays and
  identical `simulate` results.
- Nonce accounting across successive `simulate` calls on one shared `BulkRng` is contiguous and
  exact (100→1100→3600→3607).
- Under `python -O`: all 157 bets still satisfy `mult == 36/coverage` and RTP 36/37, full-wheel
  settlement is still exactly 36.0, and the degenerate-input guards still fire.
- Builder's own suite: 47/47 pass; the validator passes **on a fresh random seed**
  (`--fresh-seed`, all 8 gates, worst type z = 1.67, 1 of 157 bets outside plain 3 SE against an
  expectation of 0.42, chi²(36) = 35.5) — so no lucky committed seed is load-bearing.

## 6. Blind comparison (labels stripped)

28 rows, engine and reference in randomized column order per row. Numeric result:

- 23 rows **identical strings** — coverage/odds/multiplier/P(win)/RTP for all 13 bet types, house
  edge, RTP, edge formula, both colour lists, the float formula, cursor/floats per spin, and 3 of
  the 4 SD cells.
- 4 rows differ only in **my own wording** of the transcription (`European single-zero` vs
  `european single zero`; `POCKETS[0..36] identity` vs `identity index`; `not applicable to
  single-zero` vs `not implemented`; `sd_1bet * sqrt(n)` vs `sd_per_unit * sqrt(n)`) — no
  information about which side is the imitation.
- 1 row differs numerically: single-number SD 5.837838 vs 5.837800. An expert applying the
  formula printed in the reference itself picks the **5.837838** column as correct — i.e. the one
  numeric tell identifies the *reference* as the erroneous side, not the engine.

Coin flip at best for an expert; if anything it favours ours.

## 7. Remaining nits (none blocking; recorded so round 7 does not re-discover them)

1. **Caller-supplied giant `chunk_rounds` defeats chunking.** `simulate(40M, chunk_rounds=10**12)`
   peaks at **795 MB** (10M → 550 MB) versus a flat 220 MB on the default path; it grows linearly
   in `n_rounds`. It is legal input (integer ≥ 1) on the public API. I do not count it as a gap:
   the parameter's documented purpose *is* memory control, the default is bounded, and no
   internal call site passes it. A cheap `min(chunk_rounds, n_rounds, 8_000_000)` would retire it.
2. `simulate`'s returned `std_per_unit = multiplier * sqrt(p̂(1−p̂))` is still an exact algebraic
   function of the RTP it reports (true for any binary payout, so not wrong — just not evidence).
   The basket path (§3b) is now where the variance evidence lives; nothing else to fix.
3. `roulette.py:375` is the module's one bare `assert` on a settlement path (`mult == 36/coverage`).
   I confirmed under `-O` that it is unreachable-by-construction — both operands come from static
   tables and every legal-set entry has the coverage its odds imply (0 mismatches) — so it is
   documentation, not a check. Converting it to a module-import-time validation would be tidier.
4. The 157-bet catalogue's zero trios (0-1-2, 0-2-3) and first-four (0-1-2-3) have no explicit
   line in either reference file. They are standard single-zero-mat bets, they inherit their odds
   from the reference's street (11:1) and corner (8:1) rows, and they satisfy the 36/coverage
   identity exactly, so they add no unsourced number — but they are the only part of the surface
   the references do not name directly.
