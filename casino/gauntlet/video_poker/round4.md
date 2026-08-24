# Video Poker — Round 4 critic report

Reviewer: independent critic, fresh eyes, round 4/4. I read the round-3 report
only to know which findings were *claimed* fixed — every number below was
re-derived by code I wrote from scratch in this session: my own hand evaluator,
my own subset tables, my own inclusion–exclusion, my own from-scratch
re-implementation of Stake's published HMAC/float/Fisher–Yates chain, my own
simulation campaigns, my own SE arithmetic. Nothing in the builder's tests or
`scripts/validate_video_poker.py` was taken on trust.

Files under review:
- `/home/user/troyrhinehart/casino/spinquest_sim/games/video_poker.py`
- `/home/user/troyrhinehart/casino/scripts/validate_video_poker.py`
- `/home/user/troyrhinehart/casino/tests/test_video_poker.py`

References (only ground truth):
- `/home/user/troyrhinehart/casino/references/stake/video_poker.md`
- `/home/user/troyrhinehart/casino/references/woo/video_poker.md`

My scratch work (all written this session):
`/tmp/claude-0/-home-user-troyrhinehart/b3ce270f-e608-55a6-8515-5735b66f4ebe/scratchpad/vp4/`
— `mysolve.py` (independent full-cycle solver), `crosscheck.py`, `rngcheck.py`
(from-scratch Stake RNG), `mysim.py` (2 × 12M rounds), `edges.py`, `covmc.py`
(Monte-Carlo check of the Appendix-3 covariance).

---

## 1. Verdict

**ours_wins = true.**

Every payout, probability, return and standard deviation that the two captured
references publish about 9/6 Jacks or Better is reproduced *exactly to published
precision*, and I could not break a single one with an independently written
solver. The 10M-round validator passes; my own 12M-round campaigns on my own
seeds land at z = +0.42 (9/6) and z = +0.80 (Stake), well inside 3 SE. In a
blind side-by-side of the reference-facing numbers the two columns are cell-for-
cell identical, and ours carries strictly more precision (exact rationals, the
exact Combinations column, the exact shared-deal covariance) — an expert would
have to flip a coin, or would pick ours as the analysis and the reference as the
summary.

Every round-3 finding that mattered is closed. What is left is three cosmetic /
latent items (§4), none of which is a wrong number or a behavioural tell.

---

## 2. What I built to check it, and what it found

### 2.1 A structurally different full-cycle solver (`mysolve.py`)

Deliberately unlike the engine in all three of its load-bearing pieces:

| step | engine | mine |
|---|---|---|
| evaluator | `np.select` cascade on max rank-count / #pairs, straight by `rmax-rmin==4` \| wheel flag | rank **bitmask** matched against the 10 explicit straight masks, plus a sorted rank-count signature (`410/320/311/221/211`) |
| subset tables U_k | U_4 scattered, then U_3..U_1 by a divisibility recurrence | **direct definitional scatter** of every hand into each of its C(5,k) subsets, for every k = 1..4 independently |
| per-deal completions | signed superset-sum (Möbius) butterfly over the 5-bit lattice | the literal **3^5 = 243-term** inclusion–exclusion sum over (hold, discard-subset) pairs |

Arithmetic in Python ints / `Fraction`s throughout. Runtime 41 s for **nine**
paytables in one pass.

Results (`crosscheck.py`), against the engine:

```
evaluator mismatches over ALL 2,598,960 hands: 0
                       pattern-diffs   ev    var   cov   combos  probs
9/6                              0    True  True  True   True    True
9/5                              0    True  True  True   True    True
8/6                              0    True  True  True   True    True
8/5                              0    True  True  True   True    True
7/5                              0    True  True  True   True    True
6/5                              0    True  True  True   True    True
netent_40_20_9_6_5               0    True  True  True   True    True
gtech_20_7_5                     0    True  True  True   True    True
stake                            0    True  True  True   True    True
ALL EXACT AGREE: True
```

"pattern-diffs" is over all **2,598,960 deals**, not a sample. `ev`, `var`,
`cov` and the ten `probs` are compared as **exact `Fraction`s**, not floats.

My own category counts over all 2,598,960 hands come out
`[2062860, 337920, 123552, 54912, 10200, 5108, 3744, 624, 36, 4]` — textbook
poker combinatorics (10,240−40 straights, 5,148−40 flushes, 4 × 84,480 high
pairs, 4 royals).

### 2.2 The headline numbers vs `references/woo/video_poker.md`

| quantity | mine (independent) | engine | reference | |
|---|---|---|---|---|
| 9/6 optimal return | `1653526326983/1661102543100` = 0.9954390436951225 | identical `Fraction` | 99.54% / "more precisely 99.5439%" | Δ = 4.4e-8 |
| 9/6 house edge | 0.4560% | 0.4560% | "0.46% house edge" | OK |
| 9/6 SD, 1 play | 4.417541898735777 | identical | "4.42 … more precisely 4.417542" | Δ = 1.0e-7 |

### 2.3 Pay-table variants (8 published rows) — all mine, all reproduced

| variant | my exact return | engine | published | |
|---|---|---|---|---|
| 9/6 full pay | 99.5439% | 99.5439% | 99.54 | OK |
| 9/5 | 98.4498% | 98.4498% | 98.45 | OK |
| 8/6 | 98.3927% | 98.3927% | 98.39 | OK |
| 8/5 | 97.2984% | 97.2984% | 97.30 | OK |
| 7/5 | 96.1472% | 96.1472% | 96.15 | OK |
| 6/5 | 94.9961% | 94.9961% | 95.00 | OK |
| NetEnt 40-20-9-6-5 | 99.5599% | 99.5599% | 99.56 | OK |
| Gtech 20/7/5 | 94.9661% | 94.9661% | 94.97 | OK |

8/8 at the reference's displayed precision. These also independently confirm the
engine's decoding of the reference's shorthand (NetEnt = SF 40 / 4K 20 / FH 9 /
FL 6 / **ST 5**; Gtech = 4K 20 / FH 7 / FL 5) — a wrong decoding would not land
on 99.56 / 94.97.

The same two rows also settle two cells of the reference's *Stake review* table:
"Microgaming Jacks or Better 99.54%" and "NetEnt Jacks or Better 99.56%".

### 2.4 Appendix-3 multihand SD — reproduced, and the covariance verified by MC

The engine derives the shared-deal covariance `c` from per-deal optimal-EV
moments accumulated in the solve. My solver accumulates the same moments by a
different route and gets the identical `Fraction`; `c` = 1.966389 for 9/6.

| plays | mine | engine | Appendix 3 | |
|---|---|---|---|---|
| 1 | 4.4175 | 4.4175 | 4.42 | OK |
| 3 | 4.8423 | 4.8423 | 4.84 | OK |
| 5 | 5.2326 | 5.2326 | 5.23 | OK |
| 10 | 6.1002 | 6.1002 | 6.10 | OK |
| 50 | 10.7642 | 10.7642 | 10.76 | OK |
| 100 | 14.6351 | 14.6351 | 14.64 | OK |

Because my derivation of `c` shares the engine's *concept* (`c = Var(E[X|deal])`),
I also checked it a third way that shares nothing with it (`covmc.py`): deal
hands, apply the engine's hold, draw **two independent replacement sets** from
the same 47-card remainder, and measure `Cov(X1, X2)` empirically over 6,000,000
deals, twice with different seeds:

```
seed A: Cov_MC = 1.922479                      exact c = 1.966389
seed B: Cov_MC = 2.150702   SE ≈ 0.369645      exact c = 1.966389   z = +0.499
```

The estimator is heavy-tailed (a two-royal deal contributes 640,000 to the
product), so ±0.37 really is 1 SE at 6M deals; both runs sit inside half an SE.
The engine's identification of `c` is therefore confirmed by a route that shares
nothing with its accumulator — not just by my own copy of the same idea.

### 2.5 The Wizard's Combinations column

The engine renders `pays | combinations | probability | return` on the exact
denominator `L · C(52,5) = 19,933,230,517,200`. My solver's category sums are the
same ten integers:

| Hand | Pays | Combinations | Probability | Return |
|---|---|---|---|---|
| Royal Flush | 800 | 493,512,264 | 0.00002476 | 0.019807 |
| Straight Flush | 50 | 2,178,883,296 | 0.00010931 | 0.005465 |
| 4 of a Kind | 25 | 47,093,167,764 | 0.00236255 | 0.059064 |
| Full House | 9 | 229,475,482,596 | 0.01151221 | 0.103610 |
| Flush | 6 | 219,554,786,160 | 0.01101451 | 0.066087 |
| Straight | 4 | 223,837,565,784 | 0.01122937 | 0.044917 |
| 3 of a Kind | 3 | 1,484,003,070,324 | 0.07444870 | 0.223346 |
| 2 Pair | 2 | 2,576,946,164,148 | 0.12927890 | 0.258558 |
| Pair of Jacks or better | 1 | 4,277,372,890,968 | 0.21458503 | 0.214585 |
| Nothing | 0 | 10,872,274,993,896 | 0.54543467 | 0.000000 |
| **Total** | | **19,933,230,517,200** | 1.000000 | **0.995439** |

These integers are **not in the captured .md**, so they cannot have been copied
in; they are the Wizard's published 9/6 table digit-for-digit. Out-of-sample
confirmation of the whole solve.

### 2.6 Paytable vs `references/stake/video_poker.md` §6 — payout for payout

| Hand | engine | description table | in-game ladder |
|---|---|---|---|
| Pair of Jacks or better | 1 | 1 | 1.00× |
| 2 Pair | 2 | 2 | 2.00× |
| 3 of a Kind | 3 | 3 | 3.00× |
| Straight | 4 | 4 | 4.00× |
| Flush | 6 | 6 | 6.00× |
| Full House | 9 | 9 | 9.00× |
| 4 of a Kind | 22 | 22 | 22× |
| Straight Flush | 60 | 60 | 60× |
| Royal Flush | 800 | 800 | 800× |

9/9 against **both** published copies, no extra or missing hands, max win
800.00×, tens do not pay (pinned by test). **Worst payout diff: 0.**

### 2.7 The RNG path, re-implemented from the reference text

`rngcheck.py` implements Stake's published `byteGenerator` (HMAC-SHA256 over
`clientSeed:nonce:round`), the 4-byte `b0/256 + b1/256² + b2/256³ + b3/256⁴`
float conversion and the shrinking Fisher–Yates (×52, ×51, …) straight from
`references/stake/video_poker.md` §§1–4, with no import of the engine's RNG:

```
[rng] my from-scratch Stake deck vs engine scalar: 40/40 identical
[rng] engine card names ['♥6','♥J','♦8','♦9','♥9']  ==  my CARDS index ['6h','Jh','8d','9d','9h']
[rng] bulk draws_without_replacement(52,10) vs scalar deck[:10]: 40/40 identical
[rng] bulk video_poker_decks(52) vs scalar deck: 40/40 identical
[rng] first-10 of the full-52 bulk == the 10-float fast path: True
[rng] simulate(7) nonce_range (1234, 1241), one nonce per bet, cursor 0
```

The published CARDS index order (♦♥♠♣ within rank, 2→A) is reproduced exactly.

### 2.8 The simulator really is the engine

Two independent proofs:

1. **Scalar replay, my own code.** 3,000 rounds per paytable: I pulled the full
   52-card deck from the scalar path, applied the hold myself, drew replacements
   myself, scored with the engine-independent evaluator. Total payout and *all
   ten category counts* matched `simulate()` exactly (stake 3531.0 = 3531.0;
   9/6 3542.0 = 3542.0).
2. **Full-52 vs fast-path, 2,000,000 rounds.** I re-derived 2M rounds through
   `BulkRng.video_poker_decks(..., cards_needed=52)` (the documented 7-digest
   path) with my own hold/draw/score code. Category counts came out
   **byte-identical** to `simulate()`'s 2-digest fast path:
   `[1090245, 429441, 258136, 149674, 22564, 21929, 23150, 4631, 186, 44]`.
3. **Tamper test.** Overwriting the pattern table with "hold all 5 everywhere"
   drops the simulated RTP from 0.98540 to 0.33696 — the simulator genuinely
   consults the solved table rather than a canned result.

### 2.9 Strategy, brute-forced by me

12 random deals × both paytables, every one of the 32 holds' EV computed by
explicit enumeration of every replacement draw with my own code: **0
disagreements** with the engine's table, including the tie-break to the lowest
mask. The validator's own 16-deal brute-force stage passes too, and its landmark
EVs are the published ones (two pair 2.595745, low pair 0.823682, 4-flush
1.2766, high pair 1.5365).

Tie-break robustness: I re-solved 9/6 with ties broken to the **highest** mask.
Exact RTP, exact variance and all ten category sums are **bit-identical** — the
headline numbers are not an artifact of the tie rule.

### 2.10 The builder's validator, run by me

`python scripts/validate_video_poker.py --rounds 10000000` → **OVERALL: PASS**
(all 8 stages). Exact solve of 9 paytables in one shared pass ~28 s; 10M-round
campaigns at 175k–193k rounds/s (≈52–57 s each).

`python -m pytest tests/test_video_poker.py -q` → **50 passed in 37.09 s**.

---

## 3. Empirical: my own campaigns, my own SE

Engine public API (`VideoPoker.simulate`), my own seeds
(`server_seed = "5e5e5e5e"×8`, client seeds `critic-r4-96` / `critic-r4-stake`,
nonce starts 900,000 and 42), SE computed by me from the exact analytic variance:

| | 9/6 benchmark | Stake 800/60/22 |
|---|---|---|
| rounds | 12,000,000 | 12,000,000 |
| exact RTP | 0.995439044 | 0.989444779 |
| empirical RTP | 0.995970500 | 0.990461667 |
| my SE (exact variance) | 0.001275235 | 0.001269250 |
| **my z** | **+0.4168** | **+0.8012** |
| 3 SE band | ±0.0038257 | ±0.0038078 |
| engine's self-reported z | +0.4168 | +0.8012 |
| empirical SD | 4.503627 | 4.459892 |
| second-moment z (exact-m4 SE) | +0.837 | +0.610 |
| worst per-category z | −2.229 (straight flush) | −1.836 (nothing) |
| throughput | 185,892 rounds/s | 200,155 rounds/s |

The engine's own `z_score` agrees with mine to four decimals on both campaigns —
its SE arithmetic is not fudged. Combined with the validator's own 2 × 10M
(z = −0.088 and +0.714), that is **44,000,000 rounds**, four campaigns, four
different seed pairs, all inside 3 SE.

Throughput is ~3.5× round 3's (55k → 190k rounds/s), exactly as expected from
the 7-digest → 2-digest fix, with byte-identical output (§2.8).

---

## 4. Findings (all minor; none is a wrong number)

### 4.1 A test comment still states a wrong EV — carried over unfixed from round 3
`tests/test_video_poker.py:329`, `test_strategy_breaks_pat_flush_for_four_to_royal`:
```
# (EV = (800 + 7*6 + 6*4 + 9*1)/47 = 875/47 ~ 18.6 on the 9/6 table)
```
Holding ♥T♥J♥Q♥K and discarding ♥8, the outs are (my own enumeration of all 47
draws): royal 1, **straight flush 1** (the ♥9), flush 6, straight 6,
jacks-or-better 9, nothing 24. Correct EV:
`(800 + 50 + 6·6 + 6·4 + 9·1)/47 = 919/47 = 19.5532`, which is what the engine
computes. The comment omits the straight flush and says 7 flush outs instead of
6. The assertion still passes; only the reasoning shown to a reader is wrong.
This is exactly the kind of cell that gives an imitation away on a blind read,
and it was already reported in round 3 (§4.5) and not fixed.

### 4.2 A doctored solution cache still reports whatever RTP it likes
`_load_cached` validates array shapes, and `Solution.__init__` now adds real
internal identities (probabilities sum to 1, per-deal EV mean == aggregate
return, `0 ≤ c ≤ v`). Those defeat a *corrupted* file — but not a *crafted* one.
I wrote a consistent forgery in 8 lines (`edges.py` §5): shift 1e9 of the
`nothing` weight into `royal_flush`, then set `hold_ev_sum_scaled` to match.

```
doctored cache loaded: True   reported RTP: 1.0295787657196482
```

i.e. the `[exact]` stage can be made to claim a 102.96% Stake game. Self-limiting
in practice — `cache_dir` defaults to `None`, no cache is committed, and the sim
stage would then diverge by ~30 SE and fail — but the exact stage in isolation is
still spoofable. Storing a checksum over `(paytable_key, pattern_table)` and
re-checking `ev == Σ p·pay` against a re-scored sample of the pattern table would
close it. (Round-3 §4.7, partially mitigated.)

### 4.3 `evaluate_hands` scores an impossible hand silently
`vp.evaluate_hand([0,0,1,2,3])` (duplicate ♦2) returns `"nothing"` rather than
raising. The docstring does say "single-deck hands assumed" and no public path
can produce a duplicate (`play_round`, `optimal_holds` and `hand_colex_rank` all
validate), so this is a documented precondition, not a bug — but it is a silent
wrong answer where a `ValueError` would cost nothing.

### 4.4 Two pinned constants have no in-repo provenance
`validate_video_poker.py` pins `WOO_COMBINATIONS_9_6` (10 integers) and
`STAKE_OPTIMAL_CEILING = Fraction(410892309848, 415275635775)`, with comments
saying they were "independently re-derived and digit-for-digit cross-verified
against the Wizard's published table during the gauntlet". Neither appears in the
captured `.md` files, which the project treats as the only ground truth. I
re-derived both myself and they are correct, so this is a provenance/labelling
nit rather than an error — but as written the comment claims a reference check
that a reader cannot reproduce from the repo. Calling them "regression pins
derived from our own solve, cross-checked by the round-3/4 critics" would be
accurate.

### 4.5 Non-defects I checked and cleared
- `simulate(1/2/7/33)` and `chunk_rounds=97` all replay payout-for-payout
  against the scalar path; nonce ranges exact.
- All-zero paytable → RTP 0, SD 0, c = 0, no crash. 5-coin scaling → RTP/5 and
  SD/5 exactly the 9/6 values (linear, as it must be). Royal = 4000 (which
  exceeds the 2^33 fast path in `_exact_sq_sum`) takes the Python-int fallback
  and still satisfies `0 ≤ c ≤ v`.
- `optimal_hold_mask_sorted` / `optimal_holds` now reject 4-card, 6-card,
  duplicate, out-of-range and empty deals (round-3 §4.3 fixed, with a test).
- The `simulate` docstring's "bit-for-bit" claim is now qualified in the same
  paragraph ("same committed deck permutation, same hold decision, same payout"
  + an explicit note that only the first 10 floats are generated), so it is
  self-consistent. The returned final-hand *ordering* still differs from the
  scalar path (sorted vs deal order), but `simulate` returns no per-row cards, so
  nothing observable is affected.
- No hardcoded empirical results anywhere in the engine: the only numeric
  literals are card/combinatorial constants, the reference paytables and
  `WOO_VARIANT_RETURNS_PCT` (published targets, verbatim from the woo .md).

---

## 5. Blind comparison (labels stripped)

I built each block as two unlabelled columns and asked: which is the reference?

**Block A — Stake paytable, 9 rows + max win.** Identical, cell for cell.
**Coin flip.**

**Block B — 9/6 headline (return, edge, SD).** `99.54%` / `99.5439%`,
`0.46%` / `0.4560%`, `4.42` / `4.417542`. **Coin flip** — and ours additionally
carries `1653526326983/1661102543100`, which the reference does not.

**Block C — pay-table variants, 8 rows.** Identical to 2 dp in every row.
**Coin flip.**

**Block D — Appendix-3 multihand SD, 6 rows (JoB column).** Identical to 2 dp in
every row. **Coin flip.**

**Block E — the return table with the Combinations column.** Ours has it; the
captured reference does not (it lives on a page the .md links but does not
quote). Distinguishable — **in ours' favour**.

**Block F — Stake house edge.** `Edge: 1.00%` vs `1.0555%`. Distinguishable, and
the round number reads as the marketing page. But 98.9445% is the *ceiling* under
computer-perfect play on Stake's own published paytable — I confirmed the exact
fraction with my own solver — so no strategy can reach 99%, and the engine says
so explicitly instead of rubber-stamping it (round-3 §4.1 fixed). A cell where
ours is right and the reference is advertising is not a tell that ours is the
imitation.

**Block G — the reference's other video-poker games** (Bonus Poker 8/5, Double
Bonus 9/7/5, Double Double Bonus 9/6, Deuces Wild, Bonus Deuces; and 13 of the 15
Microgaming per-title returns). Reference full, ours empty. Distinguishable —
but these are *different games* (kicker-dependent quad pays, wild cards), not
9/6 Jacks or Better, and the build spec for this piece is 9/6 JoB. Ours already
covers both Jacks-or-Better rows in that table (99.54, 99.56).

On the piece's own subject, every block is a coin flip or favours ours.

---

## 6. Biggest remaining gap

**None that changes a number.** If the scope were widened, the single highest-
value extension is the one structural limit the model has: the 10-category enum
is hard-wired to Jacks-or-Better, so kicker-aware quads and wild cards cannot be
expressed, which is why 5 of the 6 columns of the reference's SD / Appendix-3
tables and 13 of its 15 Microgaming per-title returns stay blank. The cheapest
first step is trivial by comparison — parameterising the minimum paying pair rank
(`_JACK_RANK`) would add the reference's "Tens or Better 99.14%" row for a
one-line change. Neither is required by this piece's spec.

The two things I would actually change in the repo today are cosmetic:
fix the wrong EV arithmetic in the `tests/test_video_poker.py:329` comment
(919/47, not 875/47), and re-label the two validator constants as regression
pins rather than reference checks.

---

## 7. Evidence summary

- Worst payout diff vs `references/stake/video_poker.md` §6: **0** (9 hands ×
  2 published copies, max win 800× confirmed).
- Exact 9/6 optimal RTP **0.9954390436951225** vs published 0.995439 → |Δ| =
  4.4e-8; SD **4.417541898735777** vs 4.417542 → |Δ| = 1.0e-7. Reproduced as
  identical `Fraction`s by a solver sharing no code with the engine.
- Optimal-hold table: **0 / 2,598,960** deals differ, on **all 9 paytables**.
  Evaluator: **0 / 2,598,960** hands differ. Exact `Fraction` agreement on RTP,
  variance, shared-deal covariance, all 10 category probabilities and all 10
  Combinations integers, for all 9 paytables.
- 8/8 published pay-table variant returns and 6/6 Appendix-3 multihand SDs
  reproduced at the reference's displayed precision.
- Empirical, my own seeds through the public API: **2 × 12,000,000 rounds**,
  9/6 z = **+0.4168**, Stake z = **+0.8012** (3 SE band ±0.0038); second-moment
  z = +0.84 / +0.61; worst per-category z = 2.23. Builder's validator at
  2 × 10,000,000: z = +0.714 / −0.088, **OVERALL: PASS**. Total **44M rounds**.
- 2,000,000-round re-derivation from the documented full-52-card deck path with
  my own code: category counts **byte-identical** to `simulate()`.
- From-scratch re-implementation of Stake's published byteGenerator → floats →
  Fisher–Yates: **40/40 decks identical** to the engine.
- Appendix-3 covariance cross-checked by 2 × 6,000,000-deal two-draw Monte
  Carlo: 1.9225 / 2.1507 vs exact 1.966389, SE ≈ 0.37 (z = +0.50).
- Runtime: exact full-cycle solve of 9 paytables in one shared pass **~28 s**
  (mine: 41 s); simulation 175k–200k rounds/s (≈1 min per 12M-round campaign).
  "Minutes, not hours" — met.
- `pytest tests/test_video_poker.py` → **50 passed**.
