# Mines — Gauntlet Round 1 (independent critic)

**Verdict: DOES NOT YET WIN.** The math core, the RNG binding and every statistic
I could compute are clean. The piece fails on one thing, and it is the thing the
brief made the headline requirement: it does **not** reproduce Stake's published
24×24 table exactly. **7 of 300 cells disagree at displayed precision**, and the
builder's own gate hides them behind a tolerance that is tuned to within 5×10⁻¹²
of failing.

Reviewed: `/home/user/troyrhinehart/casino/spinquest_sim/games/mines.py`,
`/home/user/troyrhinehart/casino/scripts/validate_mines.py`,
`/home/user/troyrhinehart/casino/tests/test_mines.py`.
Ground truth: `references/stake/mines.md`, `references/woo/mines.md` only.

---

## 1. What I did (nothing reused from the builder)

| Check | Method |
|---|---|
| Analytic table | Own parser of the three markdown tables (keeps the **strings**, not floats); all 300 multipliers recomputed in `fractions.Fraction` from `C(25,k)/C(25-m,k)`; compared as decimal strings. |
| Rounding forensics | 3 accumulation orders × 3 rounding rules, 9-way matrix, all 300 cells; cross-checked against **real `node` v22** running Stake's published `reduce` + `toFixed(2)`. |
| Provably-fair path | From-scratch re-implementation of Stake's `byteGenerator`/`generateFloats`/Fisher-Yates (`hmac` + `hashlib` only, zero `spinquest_sim` imports) vs `rng.mines_positions` and vs `BulkRng.mines_positions` rows, m ∈ {1,3,5,7,24}. |
| Empirical | **110,000,000 rounds** (11 configs × 10M) through `BulkRng.mines_positions` with **my own** win rule on **non-prefix tile sets** (defeats the engine's `pos < picks` fast path), my own SE, my own z, plus exact binomial p-values and 99.73% Clopper–Pearson intervals. |
| Ladder test | 16,000,000 more rounds: full chi-square on the distribution of "safe picks before first mine" for m ∈ {1,3,7,12} — 78 ladder rungs. The builder never tests the ladder, only terminal configs. |
| Anti-fudge | `simulate()` recounted independently on identical seeds (5 configs); positional-bias chi-square on mine placement (2M rounds); peak-RSS measurement of the 24-mine chunk. |
| Builder's scripts | `scripts/validate_mines.py --rounds 10000000` executed (50M rounds): **PASS**. `pytest tests/test_mines.py`: 24 passed. |

---

## 2. The failure: 7 of 300 published cells are wrong

`display_multiplier(m, k)` is `round(float(Fraction(99,100)/P), 2)`. Compared
against the strings in `references/stake/mines.md`:

```
mines  gems |          ours |     reference
    1     7 |          1.38 |          1.37
    1    15 |          2.48 |          2.47
    1    23 |         12.38 |         12.37
    2     9 |          2.48 |          2.47
    7    17 |     59,486.62 |     59,486.63
    9    15 |    202,254.52 |    202,254.53
   15     5 |        208.72 |        208.73
```

This is not a reference defect and not an unavoidable tie. **The reference is
exactly reproducible.** 24 of the 300 cells are exact half-cent values
(`e × 100` ends in `.5` as a rational — e.g. `(9,15) = 8090181/40`), and Stake's
published client does **not** evaluate the closed form. It evaluates a
left-to-right float64 product:

```js
e = range(0, t.length+1).reduce((a, i) => a * (25 - i) / (25 - s - i), 0.99)
```

which lands on *different sides* of the tie depending on `(m,k)` — which is why
the reference table itself contains **14 asymmetric cells** (7 pairs) even though
the exact multiplier is symmetric in `(m,k)`. Replaying that accumulation in
float64 and then rounding half-even reproduces the published table **300/300**:

```
accumulation order            rounding rule              mismatches
js left-to-right              round-half-even (py round)      0   <-- exact
js left-to-right              half-up (JS toFixed)            3
exact rational -> double      round-half-even                 7   <-- ours today
exact rational -> double      half-up                        11
a*((25-i)/(25-m-i))           any                            9-11
```

Verified in real Node: `bn(5,15).toFixed(2) === "208.72"`, `bn(15,5).toFixed(2)
=== "208.73"` — the asymmetry is genuine client behaviour, and our symmetric
column is the tell.

*(Honest footnote, in the reference's disfavour: for the 3 cells whose JS product
is an exactly-representable tie — (3,1)=1.125, (19,1)=4.125, (17,7)=59486.625 —
real `toFixed` rounds up (1.13 / 4.13 / 59486.63) while the .md prints 1.12 /
4.12 / 59486.62. The .md was evidently generated with a half-even rounder on the
JS-ordered double. Since the .md is the designated ground truth, JS-order +
half-even is the recipe that scores 300/300; a pure `toFixed` emulation scores
297/300. Both beat today's 293/300.)*

## 3. The tolerance is load-bearing, not decorative

`validate_mines.py` line 58: `DISPLAY_TOL = 0.005 + 1e-9`, and it compares the
*exact* float against the printed value rather than comparing the *printed*
values. Its own report prints `max |diff| = 0.005000` — the actual value is
`0.005000000004656613`. Six cells fail a clean `0.005`:

```
mines=15 picks=9  diff=0.005000000005     mines=1  picks=23 diff=0.005000000000
mines=9  picks=15 diff=0.005000000005     mines=23 picks=1  diff=0.005000000000
mines=7  picks=15 diff=0.005000000000     mines=15 picks=7  diff=0.005000000000
```

Remove the `+1e-9` and the builder's own gate goes red. The label
"exact half-cent tie cells: 7" in the output reads as a property of the
reference; it is in fact a count of cells the engine prints differently from the
reference. `tests/test_mines.py::test_all_300_cells_match_reference` inherits the
same tolerance, and `test_published_spot_checks` only checks the 4 cells the
reference itself spot-checks — all of which happen to be non-ties. **There is no
test anywhere that asserts a printed multiplier equals the published string.**

## 4. Everything else I could break — held

**Analytic.** All 300 cells: `multiplier_exact × win_probability_exact ==
Fraction(99,100)` exactly (rationals, not floats). WoO's methodology
(prob × pay) applied to Stake's table returns 0.99 everywhere, worst float
deviation 1.1e-16. Our `P(win)` matches all 300 rows of WoO's published
probability column within 5e-7 (his column is 6 dp). The WoO discrepancy is
handled correctly and stated explicitly in the validation output — his page is
the BetFury ~95% table (my recomputation of his pays × exact P: mean 0.9493 for
2–24 mines), and both of his >100% rows (15/1 and 16/5) are captured as known
typos rather than smoothed away. Nothing hardcoded; no empirical constants in
`mines.py`.

**RNG binding.** My from-scratch port (HMAC-SHA256 over `client:nonce:round`,
`b0/256 + b1/256² + b2/256³ + b3/256⁴`, 24 events, pool of 25, `floor(f*len)`
Fisher-Yates) reproduces `rng.mines_positions` for m ∈ {1,3,7,24} × 50 nonces and
`BulkRng` row-for-row. All 24 events are always generated and truncated to
`mine_count`, matching Stake's "3 increments per game for 24 possible bomb
locations". Mine placement shows no positional bias (2M rounds, 3 mines:
inclusion χ²=10.93/df 24, p=0.99; first-drawn-tile χ²=25.52/df 24, p=0.38) — WoO
flags a real positional bias in the CryptoGames build; ours does not have one.

**The simulator is not a fake.** `Mines.simulate` win counts match my independent
recount bit-for-bit on identical seeds, including custom pick orders, max-picks
(1 mine / 24 picks) and 24-mine / 1-pick edge cases:

```
m=3 k=3 default   engine 133620 == mine 133620
m=3 k=3 [24,12,5] engine 133820 == mine 133820
m=1 k=24          engine   8067 == mine   8067
m=24 k=1 [17]     engine   8079 == mine   8079
m=2 k=23          engine    688 == mine    688
```

Peak RSS for a 1M-round chunk at 24 mines: **405 MB** — under the 500 MB budget,
and the source comment (416 MB) is honest.

## 5. My empirical run — 110M rounds, all inside 3 SE

Own win logic, own SE `= M·√(p(1−p)/n)` with the **analytic** p (null SE, not the
plug-in SE the engine could flatter itself with), own z.

| mines | picks | rounds | wins | exp wins | RTP | SE | z | exact binom p |
|---|---|---|---|---|---|---|---|---|
| 1 | 1 | 10M | 9,600,654 | 9,600,000 | 0.990067 | 0.000064 | +1.06 | 0.29 |
| 3 | 3 | 10M | 6,696,546 | 6,695,652 | 0.990132 | 0.000220 | +0.60 | 0.55 |
| 5 | 5 | 10M | 2,918,384 | 2,918,125 | 0.990088 | 0.000488 | +0.18 | 0.86 |
| 7 | 3 | 10M | 3,550,428 | 3,547,826 | 0.990726 | 0.000422 | +1.72 | 0.086 |
| 10 | 10 | 10M | 9,232 | 9,187 | 0.994852 | 0.010324 | +0.47 | 0.64 |
| 24 | 1 | 10M | 399,348 | 400,000 | 0.988386 | 0.001534 | −1.05 | 0.29 |
| 1 | 24 | 10M | 399,114 | 400,000 | 0.987807 | 0.001534 | −1.43 | 0.15 |
| 2 | 23 | 10M | 33,344 | 33,333 | 0.990317 | 0.005413 | +0.06 | 0.95 |
| 5 | 15 | 10M | 46,989 | 47,431 | 0.980778 | 0.004535 | **−2.03** | 0.042 |
| 12 | 12 | 10M | 17 | 25.0 | 0.673 | 0.198 | −1.60 | 0.13 |
| 16 | 9 | 10M | 9 | 4.9 | 1.820 | 0.447 | +1.86 | 0.069 |

Worst |z| = **2.03** over 11 configs (P(max of 11 |N(0,1)| > 2.03) ≈ 0.37 — nothing).
Every config inside 3 SE. The builder's own script at 10M×5 also passes, worst
|z| = 0.68.

**Ladder test** (the one the builder doesn't run) — distribution of safe picks
before the first mine, i.e. every rung of the multiplier ladder at once:

```
mines=1  chi2=15.22 df=24 p=0.914   worst rung z=-1.57 (k=1)
mines=3  chi2=25.17 df=22 p=0.289   worst rung z=+2.08 (k=3)
mines=7  chi2=27.10 df=18 p=0.077   worst rung z=-2.91 (k=13)
mines=12 chi2= 8.80 df=13 p=0.788   worst rung z=+1.47 (k=7)
```

78 rungs tested, max |z| = 2.91 — exactly what you expect as the max of 78
standard normals (E[max] ≈ 2.9). Clean.

## 6. Blind comparison

Two unlabeled 300-cell columns, headers and provenance stripped, diff shown in
§2. **An expert calls it immediately, and not from the diff:** column A is
perfectly symmetric under (m,k)↔(k,m) in all 300 cells; column B has 14
asymmetric cells. Anyone who has read Stake's `mines.svelte` `reduce` knows the
real client accumulates in float64 and therefore *must* break symmetry on
half-cent cells. The too-clean column is the imitation. **Blind test: lost, not a
coin flip.**

## 7. Secondary gaps (do not block on their own)

1. **No display surface.** `full_payout_table()` returns exact floats. Nothing in
   the package renders the published table, so "reproduce Stake's table" is
   currently only ever asserted through a tolerance, never produced.
2. **The empirical gate has no power where the table is most extreme.** All 5
   default configs have p ≥ 9.2e-4. At (12,12) 10M rounds buy 25 expected wins
   and at (16,9) just 4.9 — `within_3se` there is a normal approximation to a
   Poisson(5) and would wave through a multiplier that is wrong by 2×. Either
   drop the pretence for those cells or switch to an exact binomial/Poisson
   criterion and say what the test can and cannot detect.
3. `test_empirical_rtp_within_5se_at_200k` uses 5 SE at 200k rounds — a gate
   nothing plausible could fail.
4. `picks=0` (cash out before any reveal, 1.00×) is rejected with `ValueError`
   rather than documented as out-of-model; the "0-hit" analogue of keno's
   0-catch row is simply absent from the table logic. Defensible, but undeclared.

---

## THE ONE CHANGE THAT CLOSES THE DISTANCE

Stop computing the displayed multiplier from the closed form. **Replay Stake's
published accumulation in float64 —**

```python
def _stake_float_multiplier(mines: int, picks: int) -> float:
    e = 0.99                                    # gn in Stake's module
    for i in range(picks):
        e = e * (GRID_TILES - i) / (GRID_TILES - mines - i)
    return e

def display_multiplier(mines, picks):
    return round(_stake_float_multiplier(mines, picks), 2)
```

— keep `multiplier_exact`/`Fraction` for RTP and variance (unchanged, still
exactly 0.99), then **delete `DISPLAY_TOL`** and replace the table check with a
string-equality assertion over all 300 formatted cells (`f"{v:,.2f}"` against the
reference token). That single change takes the table from 293/300 to 300/300,
removes the epsilon-tuned tolerance from both the validator and the test suite,
and reproduces the reference's 14 asymmetric cells for the right reason.
