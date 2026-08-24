# Mines — Gauntlet Round 4 (independent critic)

**Verdict: DOES NOT WIN.**

Everything that can be computed, simulated, or stress-tested about this engine is
clean — the analytic core, the provably-fair binding, the WoO cross-check, 120
million rounds of my own simulation, edge cases, memory behaviour. I could not
break any of it.

It fails on exactly one thing, and it is the headline requirement: **it does not
reproduce Stake's published 24×24 table. 7 of 300 cells disagree at published
precision.** These are the *same 7 cells* that Round 1 identified, with the same
root cause, and Round 1 published the exact recipe that fixes them. Three rounds
later the code is unchanged and the builder's gate still waives them by
tolerance.

Reviewed:
- `/home/user/troyrhinehart/casino/spinquest_sim/games/mines.py`
- `/home/user/troyrhinehart/casino/scripts/validate_mines.py`
- `/home/user/troyrhinehart/casino/tests/test_mines.py`

Ground truth: `/home/user/troyrhinehart/casino/references/stake/mines.md` and
`/home/user/troyrhinehart/casino/references/woo/mines.md` only. No live site
touched. No git commands run.

---

## 1. What I did — nothing reused from the builder

I did not read `gauntlet/mines/round1.md` until after I had reached my
conclusion independently; my forensics below were derived from scratch and then
found to agree with it.

| Check | Method |
|---|---|
| Reference parse | My own markdown parser, keeping cell **strings** (not floats) so rounding is never laundered through a float compare. |
| Analytic table | All 300 multipliers recomputed in `fractions.Fraction` from `0.99·C(25,k)/C(25−m,k)`, zero engine imports. |
| Rounding forensics | 7 accumulation orders × 2 rounding rules, 14-way matrix over all 300 cells, to identify the generator that produces the reference. |
| Provably-fair path | From-scratch reimplementation of Stake's `byteGenerator` / `generateFloats` / Fisher-Yates using only `hmac`+`hashlib`; compared against `rng.mines_positions` and `BulkRng.mines_positions`. |
| Empirical | **120,000,000 rounds** through the engine's public API (`Mines.simulate`) across 10 configs, with my own SE and z recomputed from `math.comb` from first principles. |
| Extra statistics | Mine-placement chi-square (6M rounds, 25 tiles, per-draw-slot and union) — a test the validator does not contain. |
| Anti-fudge | Sabotage injection into `check_stake_table`; exact-tie census; `DISPLAY_TOL` epsilon audit; edge-case fuzzing; search for hardcoded empirical constants. |
| Builder's own scripts | `scripts/validate_mines.py` run to completion (50M rounds) → `OVERALL: PASS`, exit 0. `pytest tests/test_mines.py` → 33 passed. |

---

## 2. The failure — 7 of 300 published cells are wrong

`display_multiplier(m,k)` is `round(float(Fraction(99,100)/P(win)), 2)`.
Compared as **strings** against `references/stake/mines.md`:

```
mines  gems |     reference |          ours |  exact rational
    1     7 |         1.37x |         1.38x |            11/8
    1    15 |         2.47x |         2.48x |           99/40
    1    23 |        12.37x |        12.38x |            99/8
    2     9 |         2.47x |         2.48x |           99/40
    7    17 |    59,486.63x |    59,486.62x |        475893/8
    9    15 |   202,254.53x |   202,254.52x |      8090181/40
   15     5 |       208.73x |       208.72x |         8349/40
```

Score: **293/300 exact at published precision.** Max |diff| = 0.01 (one cent).

### This is not an unavoidable tie, and not a reference defect

24 of the 300 cells are exact half-cent values (`e = n/200`, n odd). Every one of
them is a coin flip *for a closed-form evaluator* — but not for Stake, because
Stake's published client does **not** evaluate the closed form. It evaluates a
left-to-right float64 accumulation:

```js
e = qe.range(0, t.length + 1)
      .reduce((a, i) => a * (xe.length - i) / (xe.length - s - i), gn);
```

That accumulation lands on **different sides** of the same tie depending on
whether you walk `(m,k)` or `(k,m)`, because the operand sequence differs. Which
is why the reference table is **internally asymmetric in exactly 7 cell-pairs**
even though `0.99·C(25,k)/C(25−m,k)` is provably symmetric in `(m,k)`:

```
ref[(1,7)]=1.37x       ref[(7,1)]=1.38x        exact 11/8
ref[(1,15)]=2.47x      ref[(15,1)]=2.48x       exact 99/40
ref[(1,23)]=12.37x     ref[(23,1)]=12.38x      exact 99/8
ref[(2,9)]=2.47x       ref[(9,2)]=2.48x        exact 99/40
ref[(5,15)]=208.72x    ref[(15,5)]=208.73x     exact 8349/40
ref[(7,17)]=59,486.63x ref[(17,7)]=59,486.62x  exact 475893/8
ref[(9,15)]=202,254.53x ref[(15,9)]=202,254.52x exact 8090181/40
```

I confirmed the mechanism directly. For `(1,7)` the float64 product is
`1.37499999999999955591` (below the tie → 1.37); for `(7,1)` it is exactly
`1.37500000000000000000` (at the tie → 1.38). For `(9,15)` it is
`202254.52500000008149` (above → .53); for `(15,9)` `202254.52499999999418`
(below → .52). The asymmetry is *caused by* the accumulation order.

### The reference is 100% reproducible

My 14-way forensic matrix over all 300 cells:

| accumulation order | rounding rule | mismatches |
|---|---|---|
| **JS left-to-right `a*(25−i)/(25−m−i)`** | **round-half-even (`round`)** | **0** ← exact |
| JS left-to-right | half-up (`toFixed`) | 3 |
| `a*((25−i)/(25−m−i))` | half-even / half-up | 9 / 11 |
| exact rational → double | round-half-even | **7** ← ours today |
| exact rational → double | half-up | 11 |
| `0.99*C/C` in float | half-even / half-up | 8 / 12 |
| `0.99/P` via float product | half-even / half-up | 12 / 14 |

There is one recipe that scores 300/300 and the engine is not using it.

*(Footnote in the reference's disfavour, recorded for honesty: real JS `toFixed`
rounds half-**up**, so for the three cells whose JS product is an exactly
representable tie — (3,1)=1.125, (19,1)=4.125, (17,7)=59486.625 — a genuine Stake
client would print 1.13 / 4.13 / 59486.63 while the .md prints 1.12 / 4.12 /
59486.62. The .md was evidently generated with Python's `round` on the JS-ordered
double. The .md is the designated ground truth, so JS-order + half-even is the
300/300 recipe; a faithful `toFixed` emulation scores 297/300. Both beat 293/300.)*

---

## 3. The gate that lets it through

`scripts/validate_mines.py:58`

```python
DISPLAY_TOL = 0.005 + 1e-9      # actual value 0.0050000010000000004
```

Three separate problems:

1. **It compares the exact float against the printed value**, not printed value
   against printed value. A cell whose *display* is off by a full cent passes as
   long as its *exact* value is within half a cent of the printed one — which is
   precisely the failure mode here.

2. **The `+1e-9` epsilon is load-bearing.** I measured the diffs:

   ```
   m=15 k= 9  |diff| = 0.005000000004656613   > 0.005
   m= 9 k=15  |diff| = 0.005000000004656613   > 0.005
   m=15 k= 7  |diff| = 0.005000000000109139   > 0.005
   m= 7 k=15  |diff| = 0.005000000000109139   > 0.005
   m=23 k= 1  |diff| = 0.005000000000000782   > 0.005
   m= 1 k=23  |diff| = 0.005000000000000782   > 0.005
   ```

   Delete the `+1e-9` and the builder's own gate goes red on 6 cells. The
   validator's report line prints `max |diff| = 0.005000`, which reads as "at the
   boundary"; the true value is `0.005000000004656613`, i.e. **over** it.

3. **The label is misleading.** The output line reads
   `293 exact 2dp matches, 7 exact half-cent tie cells`. "7 exact half-cent tie
   cells" sounds like a property of the reference. It is not: there are **24**
   half-cent tie cells in the table, the engine prints **17** of them the same as
   the reference and **7** differently. The number 7 is a count of the engine's
   disagreements, presented as a count of the reference's ambiguities.

To be fair to the tolerance: it is not a broad correctness hole. I injected a
uniform −0.00499 shift into every multiplier and `check_stake_table` correctly
went red with 86 mismatches. `DISPLAY_TOL` is narrowly tailored — it admits
essentially nothing except the 24 half-cent cells. That makes it a **targeted
waiver for exactly the cells the engine gets wrong**, which is worse in
character than a sloppy tolerance, not better.

### The test suite enshrines the defect

- `tests/test_mines.py::test_all_300_cells_match_reference` inherits
  `VAL.DISPLAY_TOL` verbatim.
- `test_published_spot_checks` checks only the 4 cells the reference itself
  spot-checks — (1,1), (24,1), (1,24), (3,22) — **all four are non-tie cells**.
- `test_symmetry_in_mines_and_picks` asserts
  `multiplier_exact(9,15) == multiplier_exact(15,9)` and
  `multiplier_exact(7,17) == multiplier_exact(17,7)`. Both assertions are true of
  the exact multiplier and both are cells where the *displayed* reference values
  differ. The suite has turned the symptom into a specification.
- **No test anywhere asserts that a rendered multiplier string equals the
  published string.** All 33 tests pass, and would keep passing under the fix or
  without it.

---

## 4. Blind comparison — ours is identifiable on sight

Two unlabelled artifacts, both presented as "Mines payout table, 5×5 grid,
0.99·C(25,k)/C(25−m,k), rounded to 2 dp as displayed in-game". The only
structural probe an expert needs is the symmetry of the payout function:

```
SYMMETRY PROBE — cell(m,k) vs cell(k,m) at 2 dp

  ARTIFACT X: 7 cell-pairs where cell(m,k) != cell(k,m)
      (1,7)=1.37x    vs  (7,1)=1.38x
      (2,9)=2.47x    vs  (9,2)=2.48x
      (1,15)=2.47x   vs  (15,1)=2.48x
      (5,15)=208.72x vs  (15,5)=208.73x
      (7,17)=59,486.63x  vs (17,7)=59,486.62x
      (1,23)=12.37x  vs  (23,1)=12.38x
      (9,15)=202,254.53x vs (15,9)=202,254.52x

  ARTIFACT Y: 0 cell-pairs where cell(m,k) != cell(k,m)
```

**Not a coin flip.** X is the reference; Y is ours. An expert who knows the
formula is symmetric reasons in one step: a table produced by real float64
accumulation *must* show order-dependent tie-breaks; a perfectly symmetric table
is the signature of someone who re-derived the values in exact arithmetic and
rounded once. Artifact Y is the imitation and announces itself. Worse, the 7
asymmetries are the exact fingerprint of Stake's published `reduce` — the most
authenticating detail in the whole table is the one we sanded off.

By the stated rule ("if any cell, figure, or behavior gives ours away as the
imitation, ours does not win"), this alone settles the verdict.

---

## 5. Everything else I tried to break — it held

### Analytic core
- `multiplier_exact(m,k) × win_probability_exact(m,k) == Fraction(99,100)` in
  exact rational arithmetic for all 300 cells. Zero float tolerance. Verified
  independently.
- All **276 non-tie cells** match the reference exactly at 2 dp. Of the 24
  half-cent cells, 17 match. The 7 misses are the entire defect.
- No hardcoded multipliers, no baked-in empirical constants, no lookup tables
  anywhere in `mines.py`. Everything derives from `math.comb`.

### WoO cross-check — fully verified, correctly framed
Re-derived independently from `references/woo/mines.md`:
- 300 rows parsed; my hypergeometric `P(win)` matches **300/300** of WoO's
  probability column within 5e-7 (his column is 6 dp).
- WoO's own `Return` column reproduces `pays × P(win)` for **300/300** rows.
- WoO's methodology applied to **Stake's** table returns exactly `99/100` in
  every cell (worst float deviation 1.11e-16).
- The discrepancy is stated explicitly and correctly: WoO analyzes the BetFury
  ~95% paytable. My independent recomputation of his pays × exact P over 2–24
  mines excluding his two anomalies gives mean return **0.9493** vs Stake's
  0.9900 — a ~4.1 pp paytable gap with identical mechanics.
- Both of his >100% rows are captured, not smoothed: 15 mines/1 pick (pays 2.51,
  return 1.0040) and 16 mines/5 picks (pays 458, return 1.0862).
- His documented 1-mine exception reproduces: min return 0.3584 at 1 mine/21
  picks, max 0.9888 at 1 mine/1 pick.

This section of the work is honest and complete. No complaints.

### Provably-fair binding
My from-scratch port (HMAC-SHA256 over `clientSeed:nonce:round`,
`b0/256 + b1/256² + b2/256³ + b3/256⁴`, 24 events, pool of 25, `floor(f·len)`
pop-order Fisher-Yates), with **zero `spinquest_sim` imports** for generation:

```
independent-spec vs engine scalar  : 0 mismatches / 400 nonces
independent-spec vs engine BulkRng : 0 mismatches / 400 nonces
prefix consistency (m mines == first m of 24): 0 failures over 60 nonces × m=1..24
24 positions distinct: True   within 0..24: True   floats in [0,1): True
```

All 24 mine events are always generated and truncated to `minesCount`, matching
the published "3 increments per game for 24 possible bomb locations". Correct.

### My own empirical campaign — 120,000,000 rounds

Run through the engine's **public API** (`Mines.simulate`), configs deliberately
disjoint from the builder's defaults `[(1,1),(3,3),(5,5),(10,10),(24,1)]`, with
SE and z recomputed by me from `math.comb`:

```
  m   k   p_analytic             mult       wins    rtp_emp   SE(mine)  z(mine)  |z|<3
  1  24    4.000e-02          24.7500    480,705   0.991454   0.001400   +1.039   True
  2  23    3.333e-03         297.0000     39,902   0.987575   0.004942   -0.491   True
  5  15    4.743e-03         208.7250     56,949   0.990557   0.004140   +0.134   True
 12  12    2.500e-06      396022.8462         29   0.957055   0.180753   -0.182   True
  7  17    1.664e-05       59486.6250        178   0.882385   0.070054   -1.536   True
 24   1    4.000e-02          24.7500    480,643   0.991326   0.001400   +0.947   True
 15   5    4.743e-03         208.7250     57,465   0.999532   0.004140   +2.302   True
```

12M rounds each, 84M total, 500 s. Worst |z| = **2.302** at (15,5) — inside the
bar. **My SE and the engine's `se_rtp` agree to 7.9e-14**, so the engine's
statistics are honest, not reverse-engineered to pass.

Non-prefix pick path at scale (12M each, 36M more rounds) — this is the code path
`validate_mines.py` never exercises above n=400:

```
 scattered picks=[20,7,13,2,24]  wins=3,500,305 rtp=0.989591 se=0.000445 z=-0.918
   reverse picks=[24,23,22,21,20] wins=3,500,655 rtp=0.989690 se=0.000445 z=-0.696
    prefix picks=None             wins=3,503,235 rtp=0.990420 se=0.000445 z=+0.943
```

The `np.isin` slow path and the `pos < picks` fast path agree statistically. Clean.

### Mine-placement uniformity — the validator's blind spot, tested by me
```
first-mine tile counts, 4,000,000 rounds: chi2=19.52 df=24 p=0.7235
  (min cell 159,466 / max 160,711 / expected 160,000)
5-mine draws, 2,000,000 rounds:
  draw slot 0: chi2= 10.57 p=0.9918      draw slot 3: chi2= 17.96 p=0.8047
  draw slot 1: chi2= 29.58 p=0.1991      draw slot 4: chi2= 19.13 p=0.7452
  draw slot 2: chi2= 25.82 p=0.3624      union of 5: chi2= 31.27 p=0.1460
```
No positional bias. The engine passes a test it does not contain.

### Edge cases — all correct
```
Mines(0,1) ValueError    Mines(25,1) ValueError    Mines(1,25) ValueError
Mines(1,0) ValueError    Mines(24,2) ValueError    Mines(-1,1) ValueError
Mines(1.5,2) TypeError   Mines(True,1) TypeError   (bool correctly rejected)
```
Max picks per mines count is right (`m=1→k=24` at 24.75x, `m=24→k=1` at 24.75x,
`m=2→k=23` at 297.00x = `m=23→k=2`). Full-clear rounds, 24-mine rounds and
mine-hit paths all produce coherent result dicts with a complete
`(server_seed, client_seed, nonce)` verification triple.

### Builder's own artifacts, run by me
```
scripts/validate_mines.py  →  OVERALL: PASS  (exit 0, 50M rounds)
   [table] 300/300 cells parsed; 293 exact 2dp matches, 7 exact half-cent tie
           cells, max |diff| = 0.005000, mismatches beyond tolerance: 0 -> PASS
pytest tests/test_mines.py →  33 passed in 3.89s
```
The validator's own output line contains the confession. It is printed as a
pass.

---

## 6. The single biggest gap — and the fix

**Model the display the way Stake's client actually computes it: replay the
published left-to-right float64 `reduce`, then round. Keep the exact rational
for all payout and RTP math.**

Concretely, in `spinquest_sim/games/mines.py`:

```python
def multiplier_display_float(mines: int, picks: int) -> float:
    """Stake's published reduce, evaluated in IEEE-754 double left-to-right
    exactly as the client does — this is the value the client rounds for
    display.  Payout/RTP math stays on multiplier_exact()."""
    _validate(mines, picks)
    a = 0.99
    for i in range(picks):
        a = a * (GRID_TILES - i) / (GRID_TILES - mines - i)
    return a


def display_multiplier(mines: int, picks: int) -> float:
    return round(multiplier_display_float(mines, picks), 2)
```

I verified this end-to-end:

```
FIX: exact-match cells at published 2 dp precision: 300/300  (mismatches: 0)
FIX: display float vs exact rational, worst relative error = 6.307e-16
```

Payout math is untouched — `multiplier_exact` stays `Fraction`, so the
`× P(win) == 99/100` gate and every simulated RTP are unaffected (worst relative
drift 6.3e-16, ~10⁻¹⁴ of one SE at 12M rounds).

Then, and this matters as much as the code change:

1. **Delete `DISPLAY_TOL` entirely.** Compare rendered strings to published
   strings: `f"{display_multiplier(m,k):,.2f}x" == reference_cell_string`, all
   300, exact equality. The gate should be capable of failing.
2. **Replace `test_symmetry_in_mines_and_picks`** with an assertion on
   `multiplier_exact` symmetry *plus* an assertion that the **displayed** table
   reproduces the reference's 7 asymmetric pairs. The asymmetry is the
   authenticating fingerprint; test for it, do not test against it.
3. **Add the 7 cells as named spot checks** alongside the reference's own four,
   so a regression names itself.

---

## 7. Secondary gaps (do not block on their own)

- **No string-level test exists anywhere.** Every comparison in the suite goes
  through `float`, which is how a one-cent display error survived four rounds.
- **`DEFAULT_CONFIGS` are all prefix-pick and all moderate-probability.** The
  `np.isin` non-prefix branch is exercised at n=400 in pytest and never in the
  validator. I ran it at 36M rounds and it is fine — but that is my evidence, not
  the project's.
- **No mine-placement uniformity gate.** RTP-only testing on prefix picks would
  not catch a placement bias that happened to preserve the marginal survival
  rate. Fold my chi-square in; it costs seconds.
- **`check_scalar_bulk_bitmatch` re-implements the win rule** (`np.any(pos < k)`)
  rather than calling `simulate()`, so `simulate()`'s own vectorized win logic is
  cross-checked only in pytest at n=1000, not in the validator gate.
- **The validator prints `max |diff| = 0.005000`** for a value of
  `0.005000000004656613`. Print more digits, or the number reads as a pass when
  it is a fail.

---

## 8. Bottom line

| Gate | Result |
|---|---|
| All 300 payouts reproduce reference exactly at published precision | **FAIL — 293/300** |
| Exact RTP identity `mult × P(win) == 99/100`, 300 cells, rationals | PASS |
| WoO methodology cross-check + discrepancy stated | PASS |
| RNG binding vs independent from-spec port | PASS |
| 10M+ rounds within 3 SE (my own sim, 120M rounds, 10 configs) | PASS — worst \|z\| = 2.302 |
| Mine-placement uniformity (my chi-square, 6M rounds) | PASS |
| Edge cases / fudge audit | PASS |
| **Blind comparison** | **FAIL — ours identifiable in one probe** |

The engine is one ~5-line function away from 300/300 and from being genuinely
indistinguishable. The recipe was published in Round 1 and verified again here.
Until `display_multiplier` replays Stake's float accumulation instead of rounding
an exact rational, the table carries a perfectly symmetric column that the real
one does not have, and an expert spots it in a single glance.
