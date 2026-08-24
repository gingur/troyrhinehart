# Keno — Gauntlet Round 4 (independent critic)

Reviewed: `spinquest_sim/games/keno.py`, `scripts/validate_keno.py`,
`tests/test_keno.py`, and the keno paths in `spinquest_sim/rng.py`.
Ground truth: `references/stake/keno.md` (payouts) and
`references/woo/keno.md` (statistics + methodology). No live site touched;
no git commands run.

Everything below was measured by me, from my own scripts, against my own
re-derivation of the reference. I did not run or trust the builder's tests
as evidence — I ran them only to see what they pin.

---

## 1. What I did (nothing here reuses the builder's arithmetic)

| # | Check | Method |
|---|---|---|
| 1 | Re-derived all 260 payout cells | Regex-parsed the four §6 markdown tables out of `references/stake/keno.md` into `Fraction`s, independently of the engine's transcription |
| 2 | Re-derived all 40 analytic RTPs | `sum_k pay[k]·C(n,k)C(40−n,10−k)/C(40,10)` in exact rational arithmetic, from my parse |
| 3 | Re-implemented Stake's RNG from the published JS | Fresh port of `byteGenerator` / `generateFloats` / `SQUARES` / Fisher-Yates written from the JS quoted in the reference, using `hmac`+`hashlib` only |
| 4 | Ran `scripts/validate_keno.py` | `--rounds 10000000`, 5 configs, full gate |
| 5 | My own 120M-round campaign | 12M rounds × 10 pick counts through `BulkRng.keno_hits`, scattered (non-prefix) selections, my paytable, my SE, my chi-square — scoring **all 40** configs |
| 6 | Mutation-tested the validator | 5 injected defects; confirmed each is caught |
| 7 | Blind side-by-side | Three unlabeled A/B artifacts (paytable+RTP, bet record, prose behaviours) |
| 8 | API abuse / edge cases | 30+ hostile inputs incl. max picks, 0-hit, sub-unit payouts, chunking, memory |
| 9 | WoO cross-checks | 40-ball RTP column **and** the published variance figure |

---

## 2. Payout and probability fidelity — PASS, worst diff exactly 0

My independent parse → my own hypergeometric RTP reproduces the
reference's own RTP verification column **40/40 at its printed 2-decimal
precision**, and my paytable `Fraction`s are **identical objects** to
`keno.PAYTABLES` for all 260 cells:

```
paytable cells compared: 260; mismatches: NONE
exact RTP mismatches (Fraction ==): NONE
probability mismatches (vs my own C(n,k)C(40-n,10-k)/C(40,10)): NONE
sum_k P(k|n) == 1 exactly for n = 1..10: yes
```

Worst payout difference is **0**, not "within tolerance" — the engine
stores the multipliers as `Fraction("0.47")` etc., so `0.47` is exact and
comparison is by identity, not float tolerance. Spot anchors all hold:
`P(10 of 10) = 1/C(40,10) = 1/847660528` exactly;
`P(0 hits | 10 picks) = C(30,10)/C(40,10) = 0.035444631438589294`.

Prose consistency: Classic max 100x, Low/Medium/High 10-of-10 = 1000x,
RTP range 98.65%–99.07% around Stake's stated 99%. All reproduce.

## 3. RNG fidelity — PASS, bit-for-bit against my own port

My from-scratch port of the published JS agrees with **both** engine paths:

```
scalar  spinquest_sim.rng.keno_hits : 300/300 random (seed, client, nonce) rounds identical
bulk    BulkRng.keno_hits           : 2000/2000 rows identical, 2 client seeds x 2 nonce origins
parallel vs serial BulkRng          : byte-identical over 60,000 rows
```

Cursor accounting matches the reference's verbatim "Keno (2 increments for
every game)": `digests_for_events(10) == 2`.

Draw-level uniformity over 3M rounds (30M drawn squares):

```
per-square marginal    chi2 =  23.37 / 39 dof   p = 0.978   (min 748672, max 751764, exp 750000)
draw position 1        chi2 =  37.42 / 39 dof   p = 0.542
draw position 10       chi2 =  50.00 / 39 dof   p = 0.112
P(squares 1 AND 2 both drawn)  emp 0.058020  exact C(38,8)/C(40,10) = 0.057692  z = +1.99
```

## 4. Empirical — PASS, all 40 configs, 120M rounds, max |z| = 2.071

The hit histogram is a function of `picks` only (the draw stream does not
depend on risk), so I ran **one 12M-round campaign per pick count** and
scored all four risk tables off each — 120M rounds total, 593.6 s, ~160k–257k
rounds/s. Seeds independent of `validate_keno.py`'s. Selections deliberately
scattered (`{2,5,8,13,19,22,25,31,37,40}` prefixes) so the engine's
`drawn <= picks` fast path is never taken.

```
configs = 40   passed 3SE = 40   max |z| = 2.071 (medium picks=9)   mean z = +0.087
```

Extremes, for the record:

| risk | picks | empirical RTP | analytic | SE | z |
|---|---|---|---|---|---|
| medium | 9 | 0.9880488 | 0.9894202 | 0.0006621 | −2.071 |
| high | 10 | 0.9918662 | 0.9900832 | 0.0010393 | +1.715 |
| low | 10 | 0.9879264 | 0.9875974 | 0.0001964 | +1.676 |
| low | 9 | 0.9901506 | 0.9906886 | 0.0003337 | −1.612 |
| high | 6 | 0.9899548 | 0.9899880 | 0.0047500 | −0.007 |

Hit-count goodness of fit (cells with expected ≥ 5), per pick count:
p = 0.333, 0.990, 0.649, 0.325, 0.097, 0.197, 0.599, 0.841, 0.169, 0.309 —
10/10 clean, no cell under 0.09.

The repo's own gate agrees: `validate_keno.py --rounds 10000000` returns
**OVERALL: PASS**, 5 configs × 10M (max |z| = 2.492 at classic picks=1).

Second moment, 40/40 configs: empirical SD / analytic SD ∈ [0.979, 1.089].
The one large ratio (low picks=10, +8.9%) is **not** a defect — the campaign
caught one 10-of-10 (expected 0.0142 in 12M), and a single 1000x event
inflates Ê[X²] by 0.083 against an analytic E[X²] of 1.438. That is the
expected behaviour of an SD estimator on a jackpot-heavy table at this
sample size, and it is the same on the reference paytable because it *is*
the reference paytable.

## 5. Fudge hunt — nothing found

Mutation test (I corrupted the engine in-process and re-ran the gates):

| Injected defect | table gate | rtp gate | woo gate | empirical |
|---|---|---|---|---|
| classic p7/2hits 0.47 → 0.48 | **FAIL** ✓ | **FAIL** ✓ | pass | — |
| high p10/10hits 1000 → 999 | **FAIL** ✓ | pass¹ | pass | — |
| `POOL_SIZE` 40 → 41 | pass² | **FAIL** ✓ | **FAIL** ✓ | — |
| `BulkRng.keno_hits` rigged (square 1 always drawn) | — | — | — | **z = +249.63, within_3se=False** ✓ (clean, same seed: z = +0.54) |
| classic p5 paytable zeroed | — | — | — | `simulate()` returns rtp = 0.0 ✓ |

¹ Correct behaviour, not a hole: `P(10/10) = 1.18e-9`, so a 1000→999 change
moves RTP by ~1e-9, far below the reference's printed 0.01 pp. The table
gate catches it exactly. ² The table gate compares transcription only, so
it is properly insensitive to the combinatorial constant.

No hardcoded empirical constants anywhere in `keno.py` or
`validate_keno.py`. The simulation demonstrably flows through `BulkRng`
(rigging the RNG breaks it) and demonstrably reads the live paytable
(zeroing it zeroes the result). `simulate()`'s aggregate total payout
matches the sum of 300 independent `play_round()` calls on the same nonces
to the last cent.

I also checked the fast path is not a shortcut that changes answers: for
one selection, prefix mode (`drawn <= picks`), explicit `[1,2,3,4]`, and the
generic `np.isin` path (`[4,3,2,1]`) return byte-identical histograms.

## 6. Edge cases — clean

- **Max picks (10)**: full paytable, `P(10 hits) = 1/C(40,10)`, verified.
- **0-hit keno**: `high` picks-10 all-miss selection → payout 0.00,
  profit −1.00, win False. Correct.
- **Sub-unit consolation cells** (the round-1/round-2 killer): `low` picks-1
  0 hits → 0.70 / −0.30 / False; `medium` picks-1 0 hits → 0.40 / −0.60 /
  False; `classic` picks-5 1 hit → 0.25 / −0.75 / False. Exact push (1.00x)
  is `win=False`, `profit=+0.00`. **Round 1 and round 2 both lost on this
  and it is now fixed and pinned by tests.**
- Rejects: picks 0/11/−1/1.5/True/"3"; risk ""/None/5/"extreme"; duplicate,
  out-of-range, and wrong-length selections; `n_rounds` ≤ 0;
  `chunk_rounds` < 1 (the round-2 silent-hang defect — fixed); float nonces.
- Accepts case-insensitive risk, numpy selections, `chunk_rounds=1`.
- Memory: `BulkRng.keno_hits(1_000_000)` peaks at **315 MB**,
  `Keno.simulate(3M)` at **404 MB** (tracemalloc) — inside the 500 MB budget.
- `tests/test_keno.py`: 41 passed in 2.17 s.

## 7. WoO cross-checks

Independently (my own parse, my own arithmetic) the Gamesys 40-ball RTP
column reproduces **8/8**, worst |diff| 0.0050 pp against a printed 0.01 pp:
97.4696 / 96.4766 / 96.1538 / 96.6326 / 95.6550 / 97.4822 / 96.8656 /
97.8980 vs published 97.47 / 96.48 / 96.15 / 96.63 / 95.66 / 97.48 / 96.87 /
97.90. Range 95.66–97.90 and "greatest return is the pick-10" both hold.

Note in the builder's favour: `parse_woo_40ball` explicitly scopes itself to
the "Closest equivalent" section because the later multi-card-variance
section reuses `- Pick N:` lines in a different format. My first naive regex
fell straight into that trap and silently produced 0% for picks 6, 9 and 10.
The builder's parser is the more careful one.

I also reproduced the **variance** figure the WoO page publishes (80-number /
20-draw video keno, pick 6, pays 3-4-68-1500): my second-moment computation
gives **Var = 305.3316, SD = 17.4737** against the published
**305.33 / 17.47**. Same machinery as `keno.variance_exact`. See §9.

## 8. Blind protocol

Labels stripped, reveal at the bottom of my script. Three artifacts, because
round 2 correctly observed that a paytable-only comparison has no power over
a behavioural tell.

**Artifact 1 — 40 rows of `risk | picks | payout cells | RTP to 4 dp`.**

```
A: classic  n=10 | 0 0 0 1.4 2.25 4.5 8 17 50 80 100    | RTP 99.0374%
B: classic  n=10 | 0 0 0 1.4 2.25 4.5 8 17 50 80 100    | RTP 99.0374%
A: low      n= 1 | 0.7 1.85                             | RTP 98.7500%
B: low      n= 1 | 0.7 1.85                             | RTP 98.7500%
A: high     n=10 | 0 0 0 0 3.5 8 13 63 500 800 1000     | RTP 99.0083%
B: high     n=10 | 0 0 0 0 3.5 8 13 63 500 800 1000     | RTP 99.0083%
```
**rows where A ≠ B: 0 / 40.** 260 payout cells, zero differences.

**Artifact 2 — the same 12 rounds rendered as a bet record, 1.00 staked.**
This is the artifact that decided rounds 1 and 2 against ours.

```
--- client A ---                          --- client B ---
classic p= 4 h=1 pay=  0.80 -0.20 False   classic p= 4 h=1 pay=  0.80 -0.20 False
classic p= 5 h=1 pay=  0.25 -0.75 False   classic p= 5 h=1 pay=  0.25 -0.75 False
classic p= 7 h=2 pay=  0.47 -0.53 False   classic p= 7 h=2 pay=  0.47 -0.53 False
classic p= 3 h=1 pay=  1.00 +0.00 False   classic p= 3 h=1 pay=  1.00 +0.00 False
classic p= 6 h=2 pay=  1.00 +0.00 False   classic p= 6 h=2 pay=  1.00 +0.00 False
low     p= 1 h=0 pay=  0.70 -0.30 False   low     p= 1 h=0 pay=  0.70 -0.30 False
medium  p= 1 h=0 pay=  0.40 -0.60 False   medium  p= 1 h=0 pay=  0.40 -0.60 False
high    p= 5 h=5 pay=450.00 +449.00 True  high    p= 5 h=5 pay=450.00 +449.00 True
low     p=10 h=2 pay=  1.10 +0.10 True    low     p=10 h=2 pay=  1.10 +0.10 True
high    p=10 h=0 pay=  0.00 -1.00 False   high    p=10 h=0 pay=  0.00 -1.00 False
medium  p= 9 h=3 pay=  2.00 +1.00 True    medium  p= 9 h=3 pay=  2.00 +1.00 True
low     p= 9 h=9 pay=1000.00 +999.00 True low     p= 9 h=9 pay=1000.00 +999.00 True
```
**rows where A ≠ B: 0 / 12.**

**Artifact 3 — five published-prose behaviours** (Classic max over all
picks; Low/Med/High 10-of-10; Classic mid-range vs the others at picks 6;
first paying hit count for picks 8 across Low→Med→High; overall RTP range).
**All five identical.** (The Classic-mid-range claim evaluates False on
*both* sides — that is an internal inconsistency in Stake's own prose versus
its own paytable, reproduced faithfully rather than "corrected".)

`REVEAL: A = REFERENCE, B = OURS.` **No cell, figure, or behaviour I could
construct distinguishes them.** This is a coin flip.

---

## 9. What is still not as good as it should be

None of these is a fidelity defect, a blind tell, or a bar failure. They are
the honest residue.

**A. `validate_keno.py` still empirically covers 5 of 40 configs.**
Flagged in round 1 (§C) and round 2 (secondary #2); still `DEFAULT_CONFIGS =
[classic:1, classic:10, low:9, medium:5, high:10]`. 35 configurations have
no empirical gate in the repo. The irritating part is that fixing it makes
the gate **cheaper**: the hit histogram depends on `picks` only, so 10
campaigns score all 40 configs, versus today's 5 campaigns scoring 5.
`Keno.simulate` is parameterised on risk and re-draws per risk, which is what
forces the waste. I proved all 40 pass; the repo still cannot.

**B. The engine's only second-moment output is validated against nothing
external.** `variance_exact` / `std_per_unit` appear in every result dict
and in `analytic_summary()`, and no gate checks them against any published
figure. `references/woo/keno.md` publishes exactly one reproducible one
(pick 6, 3-4-68-1500 → variance 305.33, SD 17.47) and our machinery hits it
to 4 dp — a ~10-line gate that is currently missing. The config is 80/20 not
40/10, so it is a methodology check like the existing 40-ball gate, not a
paytable match.

**C. `PAYTABLES` is a plain mutable dict of dicts.** Round 1 (§E) and round 2
(secondary #4); still open. I silently overwrote the project's ground truth
in-process during §5 — `K.PAYTABLES['low'][10] = (Fraction(999),)*11` then
`rtp('low',10) == 999.0`, no complaint. `MappingProxyType` makes that
tamper-evident.

**D. `simulate()`'s result does not record the selection it played.**
Round 2 (secondary #4); still open. A campaign run with a custom selection
returns a dict from which the selection cannot be recovered — `config()`
carries `picks`/`risk`/`paytable` but not the numbers. `play_round()` does
record it, so the two result shapes disagree.

**E. The 9- and 10-hit cells are pinned by transcription only.**
Round 1 (§D), partially closed: `tests/test_keno.py` now forces sub-unit and
0-hit outcomes, but nothing forces a full catch. A 10-of-10 arrives once per
848M rounds, so no simulation will ever reach those cells — and they include
every 1000x. `selection = drawn[:picks]` closes it in ~6 lines across all 40
configs.

**F. Cosmetic.** `hit_probability_exact`'s `if DRAW_COUNT - hits > POOL_SIZE
- picks` branch is unreachable for picks ≤ 10 (round 1 §E, still there).
`play_round` accepts a negative nonce and any-length server seed, so it can
emit a bet record Stake's own verifier could not re-check — but the published
JS does not validate either, and this is RNG-layer, not keno-layer.

---

## 10. Verdict

| Gate | Result |
|---|---|
| Every payout cell reproduces the reference exactly | **PASS** — 260/260, worst diff **0** |
| Every probability / analytic RTP reproduces to published precision | **PASS** — 40/40, exact `Fraction` identity with my own derivation |
| WoO 40-ball cross-check | **PASS** — 8/8, worst 0.0050 pp |
| 10M+ rounds within 3 SE | **PASS** — my own 120M rounds, **40/40** configs, max &#124;z&#124; = 2.071; repo gate 5/5 at 10M |
| Hit-distribution goodness of fit | **PASS** — 10/10 chi-square, min p = 0.097 |
| Draw-level uniformity | **PASS** — per-square p = 0.978, positions 1 and 10 clean |
| RNG matches published algorithm | **PASS** — bit-identical to my from-scratch JS port, 2300 rounds |
| No fudges / sim really uses the engine | **PASS** — 5/5 mutations detected |
| Memory / chunking discipline | **PASS** — 315 MB peak per 1M-round chunk |
| Blind comparison (paytable + RTP) | **PASS** — 0/40 rows differ |
| Blind comparison (bet-record behaviour) | **PASS** — 0/12 rows differ (**round 1 & 2 defect fixed**) |
| Blind comparison (prose behaviours) | **PASS** — 5/5 identical |
| Round-1/round-2 primary defects addressed | **PASS** — win/profit semantics and the `chunk_rounds` hang both fixed and pinned |

**ours_wins = true.**

I went after this piece from an independent transcription, an independent
RNG port, an independent 120M-round campaign, and three blind artifacts, and
I could not find a cell, a figure, or a behaviour that identifies ours as the
imitation. The tell that decided rounds 1 and 2 — a 0.25x return on a 1.00
stake reported as a win with no profit field — is gone, and there is now a
test that will not let it come back.

### Highest-value remaining change (not a bar failure)

**Sweep all 40 configs in `validate_keno.py` by reusing one draw campaign per
pick count** (§9-A). It is the third round in a row this has been raised, it
makes the gate cheaper rather than more expensive, and it is the difference
between "the critic proved all 40 configs pass" and "the repo proves all 40
configs pass". Then, in order: the WoO variance gate (§9-B),
`MappingProxyType` on `PAYTABLES` (§9-C), `selection` in the `simulate`
result (§9-D), and a forced-full-catch test for the top cells (§9-E).
