# Video Poker — Round 3 critic report

Reviewer: independent critic, fresh eyes. Nothing in the builder's own tests or
`scripts/validate_video_poker.py` was taken on trust; every number below was
re-derived by code I wrote from scratch (own hand evaluator, own subset indexing,
own U-tables, own inclusion–exclusion, own SE arithmetic) and cross-checked
against the engine.

Files under review:
- `/home/user/troyrhinehart/casino/spinquest_sim/games/video_poker.py`
- `/home/user/troyrhinehart/casino/scripts/validate_video_poker.py`
- `/home/user/troyrhinehart/casino/tests/test_video_poker.py`

References (only ground truth):
- `/home/user/troyrhinehart/casino/references/stake/video_poker.md`
- `/home/user/troyrhinehart/casino/references/woo/video_poker.md`

My scratch work: `/tmp/claude-0/-home-user-troyrhinehart/b3ce270f-e608-55a6-8515-5735b66f4ebe/scratchpad/vp/`
(`indep_solver.py`, `crosscheck.py`, `mysim.py`, `strategy.py`, `multihand.py`).

---

## 1. Verdict

**ours_wins = false** — not because any number is wrong (I could not break a single
one), but because the deliverable reproduces **2 of the ~16 quantitative claims**
in the captured references. The reference (Wizard of Odds) publishes a return
table, a pay-table-variant table and an Appendix-3 multihand SD table; ours ships
one RTP and one SD. In a blind side-by-side, the shorter artifact is the imitation
— and I proved (§5) that the missing 14 cells reproduce *exactly* from the same
solve the engine already runs.

Everything the piece *does* claim, it nails. This is a narrow-scope failure, not a
correctness failure.

---

## 2. What I verified independently (all PASS)

### 2.1 Hand evaluator — exhaustive, not spot-checked
I wrote a structurally different evaluator (sorted rank-count signatures, ace-low
by explicit rank set, no `np.select` cascade) and compared it to
`vp.evaluate_hands` on **all 2,598,960 hands**:

```
evaluator: engine vs mine on ALL 2,598,960 hands -> mismatches: 0
order-invariance over 200,000 shuffled hands     -> mismatches: 0
category counts: [2062860, 337920, 123552, 54912, 10200, 5108, 3744, 624, 36, 4]
```
Counts match textbook poker combinatorics (10,240 straights − 40 = 10,200;
5,148 flushes − 40 = 5,108; 4 high-pair ranks × 84,480 = 337,920).

### 2.2 U-tables and the optimal-hold table — exhaustive, not spot-checked
The engine builds `U_4` from the scored hands and then derives `U_3..U_1` by a
divisibility recurrence, then converts to per-hold completion counts with a signed
Möbius transform over the 5-bit hold lattice. I built `U_1..U_4` by a completely
different route (direct scatter of every hand into its C(5,k) subsets, then
spot-verified 16 random subsets against **explicit enumeration of every
completion**), and replaced the Möbius transform with the literal 3^5 = 243-term
inclusion–exclusion sum:

```
engine U0 == mine: True
engine U_1..U_4 == mine: True   (all four tables, every cell)
9/6   : pattern-table mismatches over all 2,598,960 deals = 0
stake : pattern-table mismatches over all 2,598,960 deals = 0
```

Independent structural check of the hold-all-5 count (9/6 table): 18,864.
Derivation from first principles: pat hands never broken = SF 40 + FH 3,744 +
flush 5,108 + straight 10,200 = 19,092; minus flushes containing a 4-card royal
(4 suits × 5 four-subsets × 8 remaining suited cards − 4 straight flushes = 156)
and straights containing a 4-card royal (5×4×3 + 4×3 = 72). 19,092 − 228 =
**18,864**. Exact. (Quads correctly tie-break to a 4-card hold: EV is 25 either way.)

### 2.3 Exact analytics — matched to the last digit of a Fraction
My solver and the engine agree on the *exact rationals*, not just the floats:

| | 9/6 benchmark | Stake 800/60/22 |
|---|---|---|
| exact RTP | `1653526326983/1661102543100` | `410892309848/415275635775` |
| float | 0.9954390436951225 | 0.989444779444333 |
| SD | 4.417541898735777 | 4.396812602297481 |
| all 10 category probabilities | identical Fractions | identical Fractions |

Reference targets: **99.5439%** and **4.417542**. Reproduced exactly.
Tie-break robustness: re-solving with ties broken to the *highest* mask instead of
the lowest leaves both RTP and variance bit-identical, so the headline SD is not
an artifact of the tie rule.

### 2.4 The strongest corroboration the builder never printed
`_PROB_DEN` = 7,669,695 × 2,598,960 = **19,933,230,517,200** — the exact
denominator of the Wizard of Odds published 9/6 return table. Rendering the
engine's `cat_scaled_sums` as WoO's "Combinations" column:

| Hand | Pays | Combinations | Probability | Return |
|---|---|---|---|---|
| Royal Flush | 800 | 493,512,264 | 0.000025 | 0.019807 |
| Straight Flush | 50 | 2,178,883,296 | 0.000109 | 0.005465 |
| 4 of a Kind | 25 | 47,093,167,764 | 0.002363 | 0.059064 |
| Full House | 9 | 229,475,482,596 | 0.011512 | 0.103610 |
| Flush | 6 | 219,554,786,160 | 0.011015 | 0.066087 |
| Straight | 4 | 223,837,565,784 | 0.011229 | 0.044917 |
| 3 of a Kind | 3 | 1,484,003,070,324 | 0.074449 | 0.223346 |
| 2 Pair | 2 | 2,576,946,164,148 | 0.129279 | 0.258558 |
| Pair of Jacks or better | 1 | 4,277,372,890,968 | 0.214585 | 0.214585 |
| Nothing | 0 | 10,872,274,993,896 | 0.545435 | 0.000000 |
| **Total** | | **19,933,230,517,200** | 1.000000 | **0.995439** |

Every integer matches WoO's published table digit-for-digit. Those integers are
**not in the captured .md** — they cannot have been copied in, so this is a true
out-of-sample confirmation of the solver. It is also, however, buried:
`category_table()` returns floats only and nothing in the repo prints this column.

### 2.5 Paytable vs `references/stake/video_poker.md` §6
Payout-for-payout against **both** published copies (description table and
in-game ladder): 9/9 exact, no extra or missing hands, max win 800×.
`Pair of Jacks or better 1 / 2 Pair 2 / 3 of a Kind 3 / Straight 4 / Flush 6 /
Full House 9 / 4 of a Kind 22 / Straight Flush 60 / Royal Flush 800`.
Tens do not pay (pinned by test). Confirmed.

### 2.6 Strategy — engine vs my own brute force
23 canonical Jacks-or-Better discriminators, EVs computed by my own explicit
enumeration of every replacement draw: **0 engine disagreements** (every apparent
mismatch was my own expectation string, not the engine's hold). Landmarks vs the
published 9/6 strategy EVs:

| decision | my brute-force EV | published |
|---|---|---|
| two pair | 2.595745 | 2.5957 |
| high pair | 1.536540 | 1.5365 |
| 4 to a flush | 1.276596 | 1.2766 |
| low pair | 0.823682 | 0.8237 |
| 4 to an outside straight | 0.680851 | 0.6809 |
| three of a kind | 4.302500 | 4.3025 |
| 4 to a straight flush (wheel) | 3.531915 | 3.5319 |

Correct on the classic traps: pat straight flush is kept (50 > 19.66); pat flush
and pat straight are both broken for 4 to the royal; 4-flush beats a low pair;
low pair beats a 4-card outside straight; quads drop the kicker.

Also verified `hold_ev_exact == hold_ev_bruteforce` on 300 random (deal, mask)
pairs across all six hold sizes and both paytables: 0 mismatches.

### 2.7 Simulation — my own campaign, my own SE
I ran the engine's **public API** (`VideoPoker.simulate`) with my own seeds
(`server_seed="1234abcd"×8`, client seeds `critic-round3-independent-*`),
12,000,000 rounds per paytable, and computed SE/z myself from the exact variance:

| | 9/6 benchmark | Stake 800/60/22 |
|---|---|---|
| rounds | 12,000,000 | 12,000,000 |
| exact RTP | 0.995439044 | 0.989444779 |
| empirical RTP | 0.994197667 | 0.990283833 |
| my SE (exact variance) | 0.001275235 | 0.001269250 |
| **my z** | **−0.9735** | **+0.6611** |
| 3 SE band | ±0.0038257 | ±0.0038078 |
| empirical SD | 4.296436 | 4.500633 |
| my z on the SD | −1.167 | +0.995 |
| worst per-category z | 1.454 | 2.307 |
| throughput | 59,181 rounds/s | 52,055 rounds/s |

The engine's self-reported z agrees with mine to 4 decimals — its SE arithmetic is
not fudged.

I also re-derived 2,000,000 rounds **from the raw RNG decks**: pulled full 52-card
Fisher–Yates decks from `BulkRng.video_poker_decks(..., cards_needed=52)`, applied
the hold mask and replacement pointer with my own code, and scored with my own
evaluator. Category counts came out **byte-identical** to `simulate()`:
`[1091057, 429157, 257850, 149023, 22492, 22375, 23048, 4743, 198, 57]`.
The simulator is genuinely running the engine, not a shortcut.

### 2.8 The builder's own validator, run by me
`python scripts/validate_video_poker.py --rounds 12000000` → **OVERALL: PASS**
(exact solve 18.7 s; stake sim z = +0.495, 9/6 sim z = +0.424; 217 s / 213 s).

### 2.9 Edge cases probed
- `simulate(1)`, `simulate(2)`, `simulate(7)`, and `chunk_rounds=97` over 1,200
  rounds: all match the scalar `play_round` payout-for-payout; nonce range exact.
- hold-0 (discard all five) and hold-5 (stand pat) both occur in the solved table
  (84,360 / 18,864 deals) and both replay correctly through the scalar path.
- all-zero paytable → RTP 0, SD 0, no crash.
- 5-coin scaling (every pay ×5) → RTP/5 = 0.9954390436951226. Linear, as it must be.
- duplicate card in a deal → `ValueError`; card index 52 → `IndexError`.
- No hardcoded empirical constants anywhere; the only literals are the two
  reference figures used as assertion targets.

---

## 3. Blind comparison (labels stripped)

I built two unlabeled columns and asked: which is the reference?

**Block A — Stake paytable (9 rows + max win).** Columns identical. Coin flip.

**Block B — 9/6 headline.** `99.54% / 99.5439%` and `4.42 / 4.417542` in both
columns. Coin flip. Ours arguably *stronger* — it carries the exact rational
`1653526326983/1661102543100`, which the reference does not.

**Block C — Stake house edge.**
`Edge: 1.00%` vs `Edge: 1.0555%`. **Distinguishable.** An expert picks the round
number as the reference. But this is unfixable and the reference is the one at
fault: 98.9445% is the *maximum* return achievable on Stake's own published
paytable, so no strategy — Stake's included — can reach the advertised 99%. The
engine notices the tension and then defuses it dishonestly (§4.1).

**Block D — pay-table variant returns (8 rows).** Reference column full, ours
**empty**. Instantly distinguishable.

**Block E — Appendix-3 multihand SD (6 rows).** Reference column full, ours
**empty**. Instantly distinguishable.

Blocks D and E decide it: an expert separates the two artifacts in one second by
size, not by any wrong cell.

---

## 4. Findings

### 4.1 The Stake "Edge: 1.00%" check is a rubber stamp (moderate)
`validate_video_poker.py:146`
```python
stake_rtp_ok = abs(s_rtp - STAKE_PUBLISHED_RTP) < 0.006
```
A ±0.6 percentage-point band. It would also pass a 9/5 table (98.45%) or an 8/6
table (98.39%) as "OK", so it can distinguish essentially nothing. Worse, it
prints `-> OK` next to a claim (`1.00%`) that our own exact result proves is
**unattainable**: optimal play is the ceiling, so the true edge on Stake's table
is 1.0555% and cannot be lower. The module docstring says only "Stake does NOT
publish the strategy assumption behind that figure", which understates it — no
strategy assumption can close the gap in that direction. The honest move is to
assert the exact value (`Fraction(410892309848, 415275635775)`) and state the
impossibility as a finding about the reference.

### 4.2 The validator prints statistics it never asserts (moderate)
`run_sim()` computes a per-category z for all ten categories and an empirical SD,
prints both, and then `sim["pass"]` uses **only** `within_3se` on the aggregate RTP
plus a count-sum check (`validate_video_poker.py:363-368`). The docstring's claim
"per-category counts compared with the exact probabilities" is decorative. In the
builder's own 12M run the 9/6 full-house category came in at **z = +3.02** and
nothing flagged it. A category-distribution bug that left the aggregate RTP intact
would sail through. (I verified the distribution independently, so no such bug
exists today — but the check does not exist either.)

### 4.3 `optimal_hold_mask_sorted` silently accepts non-5-card deals (minor, real)
```python
>>> vp.VideoPoker().optimal_hold_mask_sorted([0,1,2,3])
15
>>> vp.VideoPoker().optimal_holds([0,1,2,3])
[True, True, True, True, False]
```
A 4-card input colex-ranks as a 4-subset (0..270,724), indexes the 2,598,960-entry
`pattern_table`, and returns a mask for an unrelated hand — plus a 5-element hold
list for a 4-card deal. `play_round` validates `holds` length but these two public
methods validate nothing. Silent wrong answer where a `ValueError` belongs.
(6 cards raises `IndexError`, and duplicates raise, so only the short case leaks.)

### 4.4 `simulate()` overclaims "bit-for-bit" (minor)
Docstring: *"Row i is bit-for-bit verifiable against the scalar path at nonce
`nonce_start + i` (same deck permutation, same hold decision)."* The vectorized
path assigns replacements to discarded slots in **sorted** deal order; `play_round`
assigns them in **deal** order. The final-hand *multiset* is identical (hence the
category and the payout), but the returned card ordering is not. "Payout- and
category-identical" is the true claim.

### 4.5 Wrong arithmetic in a test comment (minor)
`tests/test_video_poker.py:~178`, `test_strategy_breaks_pat_flush_for_four_to_royal`:
```
# (EV = (800 + 7*6 + 6*4 + 9*1)/47 = 875/47 ~ 18.6 on the 9/6 table)
```
Holding ♥T♥J♥Q♥K and discarding ♥8, the ♥9 draw makes a **straight flush** (50),
which the comment omits, and the flush outs are 6 not 7. Correct value:
(800 + 50 + 6·6 + 6·4 + 9·1)/47 = **919/47 = 19.5532**, which is what the engine
actually computes. The assertion still passes; only the reasoning shown to a
reader is wrong. In a blind read this is the kind of cell that gives an imitation
away.

### 4.6 3.5× of the simulator's HMAC work is provably dead (minor, efficiency)
`VideoPoker.simulate` calls `video_poker_decks(step, cards_needed=10)` and the
docstring justifies generating all 52 events as "doc-faithful nonce/cursor
accounting". It is not load-bearing: each bet has its own nonce and starts at
cursor 0, so the first ten Fisher–Yates draws depend only on the first ten floats.
Verified:
```
first 10 of full 52-event deck: [49, 22, 6, 12, 29, 40, 7, 32, 10, 19]
from only 10 floats          : [49, 22, 6, 12, 29, 40, 7, 32, 10, 19]   IDENTICAL
```
52 floats = 208 bytes = **7 HMAC digests** per bet where 10 floats = 40 bytes =
**2 digests** would be byte-identical, plus 52 Fisher–Yates steps where 10 would
do. `video_poker_decks` accepts `cards_needed` but only uses it to slice the
output. At ~55k rounds/s a 12M-round campaign is ~3.6 minutes; most of that is
avoidable. (This lives in the verified RNG core's bulk path — add a `floats_needed`
parameter rather than touching the scalar path.)

### 4.7 `cache_dir` loads unverified results from disk (minor, fudge vector)
`_load_cached` checks only array shapes. A doctored
`vp_solution_v1_<key>.npz` makes the `[exact]` stage report any RTP and SD you
like. Partially self-limiting (the simulator would then diverge and fail 3 SE),
but the exact-analysis stage alone can be spoofed. No cache is committed to the
repo and the default is `None`, so this is latent. A stored checksum of the
paytable key plus a re-check that `sum(category_probs) == 1` and that
`ev == sum(p·pay)` would close it.

---

## 5. Biggest remaining gap — and proof it closes

**The engine reproduces 2 of the ~16 quantitative claims in the captured
references, and the missing 14 all fall out of the solve it already runs.**

I checked every one of them.

**(a) The eight pay-table variant returns** (`references/woo/video_poker.md`,
"Jacks or Better pay-table variants"). `solve_paytables` already accepts a list
and shares the U-tables, so all eight cost one pass — yet nothing in the repo ever
solves them. One pass, 22 s total:

| variant | ours | reference | |
|---|---|---|---|
| 9/6 full pay | 99.5439 | 99.54 | OK |
| 9/5 | 98.4498 | 98.45 | OK |
| 8/6 | 98.3927 | 98.39 | OK |
| 8/5 | 97.2984 | 97.30 | OK |
| 7/5 | 96.1472 | 96.15 | OK |
| 6/5 | 94.9961 | 95.00 | OK |
| NetEnt 40-20-9-6-5 | 99.5599 | 99.56 | OK |
| Gtech 20/7/5 | 94.9661 | 94.97 | OK |

Eight for eight, to the published precision. (The last two also confirm the
reference's shorthand decoding: SF 40 / 4K 20 / FH 9 / FL 6 / **ST 5** for NetEnt,
4K 20 / FH 7 / FL 5 for Gtech.)

**(b) The Appendix-3 multihand SD table** — the structural half of the gap. The
reference gives `n·v + n(n−1)·c` with `c` the covariance between two hands of the
same deal. Because the two hands share the deal and the hold but draw replacements
independently, `c = Var over deals of the optimal hold's EV` — computable in the
same sweep. The engine's `Solution` accumulates only category sums and **throws the
per-deal optimal EV away**, so `c` is not recoverable without a full re-solve.
That is why this is the one item that needs a change to the solver, not just to
the reporting. Adding two int accumulators (Σ ev·L and Σ (ev·L)²) over the chosen
holds gives, for 9/6, `c = 1.966389` and:

| n plays | ours SD/hand | reference |
|---|---|---|
| 1 | 4.4175 | 4.42 |
| 3 | 4.8423 | 4.84 |
| 5 | 5.2326 | 5.23 |
| 10 | 6.1002 | 6.10 |
| 50 | 10.7642 | 10.76 |
| 100 | 14.6351 | 14.64 |

All six rows to the published two decimals.

**(c) The WoO combinations column** (§2.4) — already exact inside
`Solution.cat_scaled_sums`, just never rendered.

### The single change
Accumulate `Σ ev_best·L` and `Σ (ev_best·L)²` alongside `cat_sums` in
`solve_paytables`, expose `Solution.hold_ev_variance` → `VideoPoker.n_play_std(n)`
and a `VideoPoker.return_table()` that emits WoO's `pays | combinations |
probability | return` rows with the exact integer denominator 19,933,230,517,200;
then add two validator stages that assert (i) all eight variant returns and
(ii) the six Appendix-3 multihand SDs. That takes the artifact from "one number
matches" to "every published number in both references matches", which is the only
thing standing between this piece and a blind coin flip.

---

## 6. Evidence summary

- Worst payout diff vs `references/stake/video_poker.md` §6: **0** (9/9 hands,
  both published copies, max win 800×).
- Exact optimal-play RTP 9/6: **0.9954390436951225** vs target 0.995439 —
  |Δ| = 4.4e-8, i.e. exact to published precision. SD **4.417541898735777** vs
  4.417542 — |Δ| = 1.0e-7.
- Exact rationals reproduced by my independent solver: RTP, variance and all ten
  category probabilities identical as `Fraction`s for both paytables.
- Optimal-hold table: **0 / 2,598,960** deals differ from my independent solve,
  both paytables. Evaluator: **0 / 2,598,960** hands differ.
- Empirical (my own seeds, engine public API): 12,000,000 rounds × 2 paytables.
  9/6 RTP 0.994197667, z = **−0.9735**; Stake RTP 0.990283833, z = **+0.6611**;
  3 SE band ±0.00383. Empirical SD z: −1.17 and +1.00. Worst per-category z: 2.31.
- Builder's validator re-run at 12M rounds: **OVERALL: PASS** (z = +0.424, +0.495).
- Runtime: exact full-cycle solve **18.7 s** for both paytables in one pass;
  simulation 52k–59k rounds/s (≈3.5 min per 12M-round campaign).
- Blind comparison: identical on the paytable and on the 9/6 headline; ours is
  empty where the reference has an 8-row variant table and a 6-row multihand
  table, and reads `1.0555%` where the reference reads `1.00%`.
