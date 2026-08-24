# Baccarat — Gauntlet Round 4 (independent critic)

Reviewed: `/home/user/troyrhinehart/casino/spinquest_sim/games/baccarat.py`,
`/home/user/troyrhinehart/casino/scripts/validate_baccarat.py`,
`/home/user/troyrhinehart/casino/tests/test_baccarat.py`.
Ground truth: `references/stake/baccarat.md` and `references/woo/baccarat.md` only.
None of the builder's tests were trusted as evidence — every number below was
re-derived by the critic with code that imports nothing from `spinquest_sim`.

**Verdict: ours_wins = FALSE.** Not for a wrong number — I could not find one.
The math is exact, the empirical gates pass with room to spare, and the fudge
hunt came up empty. It fails the blind test the same way rounds 1–3 did, one
notch smaller: the reference column has five filled cells where ours has
em-dashes, and **three of those five are exactly derivable** from the same
enumeration the engine already runs. See §7.

---

## 1. Independent analytic ground truth

Script: `…/scratchpad/bacc4/indep.py`. Deliberately built at **rank**
granularity (13 ranks, not 10 baccarat values) so that pair probabilities fall
out of the *same* enumerator that produces the house edges — a different
internal representation from the engine's value-level `_enumerate`, so
agreement is not structural. Rules typed by hand from the Stake §4 prose;
shoe = fresh 52·D cards, 6 ordered positions always consumed without
replacement.

| decks | denominator | HE Banker | HE Player | HE Tie | HE Pair (11:1) |
|---|---|---|---|---|---|
| 8 | 4,998,398,275,503,360 | 1.057906% | 1.235081% | 14.359629% | 10.361446% |
| 6 | 878,869,206,895,680 | 1.055849% | 1.237415% | 14.438160% | 11.254019% |
| 1 | 14,658,134,400 | 1.011748% | 1.286372% | 15.746127% | 29.411765% |
| ∞ | 13⁶ = 4,826,809 | 1.063999% | 1.228141% | 14.116987% | 7.692308% |

Rounded to WoO's printed precision: **1.06 / 1.24 / 14.36 / 10.36**,
**1.06 / 1.24 / 14.44 / 11.25**, **1.01 / 1.29 / 15.75 / 29.41**,
**1.064 / 1.228 / 14.117 / 7.69** — all 16 published house-edge cells.
8-deck win probabilities 45.859742 / 44.624661 / 9.515597 → **45.86 / 44.62 /
9.52**; per-unit SDs 0.927372 / 0.951153 / 2.640872 → **0.93 / 0.95 / 2.64**;
8-deck RTPs 98.94 / 98.76 / 85.64 / 89.64. Every published WoO figure
reproduces from first principles, so my ground truth stands on its own.

## 2. Engine vs that ground truth — exact rationals, not floats

`…/scratchpad/bacc4/cmp_exact.py`, comparing `Fraction`s (and `object`-dtype
integer grids), across decks = 8 / 6 / 1 / 2 / 4 / 100 / ∞:

* `total_grid(d)` — **all 100 cells and the denominator identical**, every shoe.
  (The infinite-deck grid is the one apparent "mismatch": mine normalises over
  13⁶, theirs over 52⁶. Verified every cell is exactly ×4096 — same
  distribution, different reduction. Not a defect.)
* `outcome_probabilities(d)` — exact `Fraction` equality, every shoe
  (e.g. 8-deck P(tie) = 55825015601/588262274145 on both sides).
* `house_edge_exact` / `rtp_exact` — exact equality, 3 bets × 7 shoes.
* `std_per_unit` — equal to 12 decimals, all bets, all shoes.
* `pair_probability(d)` — equal to my **enumerated** pair weight (not just to
  the closed form): 31/415, 23/311, 1/17, 1/13, 5/69 (d=2), 133/1733 (d=100).
  The closed form (4D−1)/(52D−1) is therefore confirmed against a full
  6-card enumeration, not assumed.

**Total mismatches: 0.**

## 3. Payout-for-payout vs Stake §5

| Bet | Stake published | engine `PAYOUT_ODDS` | Stake total return | engine `MULTIPLIERS` | diff |
|---|---|---|---|---|---|
| Player | 1:1 | `Fraction(1)` | 2.00 | `Fraction(2)` | 0 |
| Banker | 0.95:1 | `Fraction(19,20)` | 1.95 | `Fraction(39,20)` | 0 |
| Tie | 8:1 | `Fraction(8)` | 9.00 | `Fraction(9)` | 0 |
| Pair (WoO) | 11:1 | `Fraction(11)` | 12.00 | `Fraction(12)` | 0 |

**Worst payout difference across every bet: exactly 0** — exact rational
equality, so no 0.94999… drift anywhere. Published per-bet edges reproduce at
Stake's printed 2 dp: 1.24 / 1.06 / 14.36. Tie pushes Player and Banker:
`payouts_for_outcomes([0,1,2])` returns `[2, 0, 1]` / `[0, 1.95, 1]` /
`[0, 0, 9]` — correct on all three spots.

Drawing table re-transcribed by hand from §4 and compared row-for-row:
0/1/2 → all; 3 → all but 8; 4 → {2–7}; 5 → {4–7}; 6 → {6,7}; 7 → ∅; rows 8–9
∅. **All 10 rows identical.** Player-stands branch: banker draws on 0–5 (the
standard punto banco completion of Stake's player-third-card-only phrasing —
independently confirmed correct because it is what makes §1 land on WoO's
numbers).

## 4. Is the simulator really the engine + the published RNG?

`…/scratchpad/bacc4/indep_round.py` — a complete from-scratch round: raw
`hmac.new(server, f"{client}:{nonce}:{round}", sha256)`, float =
Σ bᵢ/256^(i+1), `floor(f·52)` (infinite) or my own `pool.pop(floor(f·len))`
over 416 cards (finite), my own value map, my own drawing rules, my own settle.

| check | result |
|---|---|
| my round vs `Baccarat.play_round`, 500 nonces × 2 shoe models | **0** mismatches on cards, floats, totals, outcome, `events_used`, pair flags, seat lists |
| my round vs bulk `deal_rounds` / `deal_cards`, 500 nonces × 2 shoe models | **0** mismatches |
| `nonce_next` after 500 rounds | 500 (one nonce per coup, cursor 0, 6 events, 1 digest) |
| `_settle_matrix` vs my scalar settle, **all 10⁶ value 6-tuples** | **0** mismatches (exhaustive) |
| `_cards_matrix` vs my pop-based scalar, 60,000 rows × decks 1/2/6/8/100 | **0** mismatches |
| boundary floats 0.0 and 1−2⁻³² | matrix == scalar == mine, all shoes |
| chunk-size invariance (`chunk_rounds` = 7,919 / 100k / 1M / 3M, 2M rounds) | identical outcome counts, identical nonce range |
| `nonce_start=777`, 500k rounds | range (777, 500777) |
| seat transcripts, 3,000 rounds | `player_cards`+`banker_cards` partition the used cards exactly; named-card totals reproduce `banker_total`; **0** mismatches |
| finite-shoe integrity, 30,000 rounds | 6 distinct pool ids every row; no card index dealt >8× in a round |

**Fudge hunt:** `grep -E "1\.06\|1\.24\|14\.36\|45\.86\|98\.9\|0\.93\|10\.36\|89\.64"`
over `games/baccarat.py` hits **docstring prose only** — no reference constant
is read by any code path. Nothing is hardcoded; every published figure is
*derived* from `_enumerate` or the closed form. The simulator genuinely runs
the engine on the verified RNG core.

**Input validation** is real, not decorative — 20/20 bad-input paths raise
`ValueError`: unknown bet, `decks` = 0 / −3 / `True` (bool-as-int trap closed) /
`8.0`, `card_value(±)`, `card_rank(52)`, `banker_draws(8,·)`,
`banker_draws(3,10)`, wrong float/value counts, wrong matrix shape,
`n_rounds ≤ 0` on all three entry points, bad pair-bet name.
`decks=1` (52 cards, 6 draws — the maximum-depletion case, where a value can
be exhausted mid-round) and `decks=100` both enumerate to probability exactly 1.

## 5. My own empirical campaigns

All through the **public API** (`bc.deal_cards`), my own server seeds, my own
settle applied on top, SEs computed by me as σ_exact/√N with σ from **my**
enumerator. `…/scratchpad/bacc4/mysim.py`.

| campaign | N | worst \|z\| | detail |
|---|---|---|---|
| 8-deck, seed A | 25,000,000 | 1.148 | HE player 1.225616% vs exact 1.235081% (3SE ±0.057069%, z +0.50); banker 1.066966% vs 1.057906% (±0.055642%, z −0.49); tie 14.298976% vs 14.359629% (±0.158452%, z +1.15) |
| 8-deck, seed B | 25,000,000 | 1.081 | HE 1.055269 / 1.237948 / 14.416732% |
| infinite-deck | 15,000,000 | 1.191 | HE 1.069159 / 1.223073 / 14.195980% vs exact 1.063999 / 1.228141 / 14.116987% |
| 1-deck | 12,000,000 | 1.167 | HE 0.986462 / 1.312108 / 15.676225% |

**Worst z-score anywhere across 77,000,000 of my own rounds: 1.19.** Every bet,
every shoe, comfortably inside 3 SE.

Pair bets at rank granularity, same campaigns: 8-deck player/banker
z = −0.15 / −0.20 (seed A), −0.24 / +0.13 (seed B); infinite −0.38 / −1.19;
1-deck −0.77 / −1.12.

Empirical per-unit SDs at 25M (8-deck): player **0.9511**, banker **0.9273**,
tie **2.6417** — matching WoO's published **0.95 / 0.93 / 2.64** at printed
precision.

**Sharper test.** The 3-cell RTP gate is weak: a wrong third-card rule can
leave the three win probabilities near-right while wrecking the shape. So I ran
the 100-cell (player_total, banker_total) grid against my exact grid at 25M
rounds — min expected cell 97,848, so χ² is well-conditioned:

> **χ² = 114.33, df = 99, p = 0.139**, worst standardized residual |z| = 3.09
> (the expected maximum of 100 standard normals).

Rank uniformity of each of the 6 dealt positions (13 bins, df 12) at 25M:
p = 0.636 / 0.590 / 0.086 / 0.358 / 0.730 / 0.061 — no position is
non-uniform.

Builder's own artifacts, run by me unmodified: `scripts/validate_baccarat.py`
→ **64/64 PASS**, exit 0, 10M rounds in 22.3 s (448k rounds/s), plus a 2M
infinite-deck rank audit. `pytest tests/test_baccarat.py` → **50 passed**.

Totals: **~89 million rounds** through the engine (77M mine + 12M the
validator's), ~176 s of simulation at 404k–546k rounds/s, plus the exhaustive
10⁶ settle sweep and 300k matrix-vs-scalar card rows.

## 6. Blind side-by-side (labels stripped)

Every published quantity in both reference files, 41 rows, two unlabeled
columns. One typed by me from the `.md`; one produced from the engine's public
API. (`…/scratchpad/bacc4/blind.py`.)

```
quantity                        |               COLUMN X |               COLUMN Y | match
--------------------------------+------------------------+------------------------+------
Player / Banker / Tie payout    |     1:1 0.95:1 8:1     |     1:1 0.95:1 8:1     | =
Pair-bet payout                 |                  11:1  |                  11:1  | =
total return  2.00 / 1.95 / 9.00|              identical |              identical | =
Tie -> Player/Banker bets       |                   push |                   push | =
events per round / cursor incr. |                  6 / 1 |                  6 / 1 | =
8-deck  HE  B / P / T / Pair    | 1.06 1.24 14.36 10.36% | 1.06 1.24 14.36 10.36% | =
6-deck  HE  B / P / T / Pair    | 1.06 1.24 14.44 11.25% | 1.06 1.24 14.44 11.25% | =
1-deck  HE  B / P / T / Pair    | 1.01 1.29 15.75 29.41% | 1.01 1.29 15.75 29.41% | =
inf.    HE  B / P / T / Pair    |1.064 1.228 14.117 7.69%|1.064 1.228 14.117 7.69%| =
8-deck RTP  B / P / T / Pair    |98.94 98.76 85.64 89.64%|98.94 98.76 85.64 89.64%| =
P(B) / P(P) / P(T) 8-deck       |   45.86 44.62 9.52%    |   45.86 44.62 9.52%    | =
SD  B / P / T                   |    0.93  0.95  2.64    |    0.93  0.95  2.64    | =
HE Banker EXCLUDING ties        |                  1.17% |                      — | DIFF
HE Player EXCLUDING ties        |                  1.36% |                      — | DIFF
HE Tie at 9:1 payout            |                  4.84% |                      — | DIFF
Overall game HE (all spots)     |                  1.10% |                      — | DIFF
Overall game RTP                |                 98.90% |                      — | DIFF

identical cells: 36/41   differing: 5
```

**36 of 41 cells are character-identical. All 5 differences are holes in
Column Y, not wrong numbers.** An expert handed these two columns needs two
seconds: the one with em-dashes is the imitation. That is not a coin flip, so
by the stated rule ours does not win.

Behavioural artifacts do *not* give ours away. `play_round` transcripts read as
genuine punto banco logs (card names from the published CARDS index,
`events_used` always equal to the cards actually shown — 0 mismatches in 3,000
rounds, seat lists a correct partition, 4/5/6-card rounds in the right
proportions). The seat-assignment order of the 6 events is unpublished
(the reference says so explicitly) and, the 6 positions being exchangeable,
cannot affect any distribution — unverifiable, harmless, honestly documented.

## 7. The gap

Two of the five holes — **1.10% overall edge / 98.90% overall RTP** — are not
derivable by anyone. Blending them needs a bet-mix weighting Stake never
published (banker/player alone would require ≈76.25/23.75, and any tie weight
would have to be negative). No faithful implementation could fill them, and the
engine is right to decline. I do not hold those two against it. (The validator
only checks that 1.10% lies between the exact banker and player edges — honest,
but a band any value in [1.058%, 1.235%] would pass.)

The other three are different. They are printed in
`references/woo/baccarat.md` — the file this round designates as *statistical
ground truth* — and I derived every one of them exactly, from the same 8-deck
enumeration the engine already computes:

| WoO published | my exact derivation | formula |
|---|---|---|
| Banker HE **excluding ties**, ~1.17% | **1.1692%** | HE_banker / (1 − P(tie)) |
| Player HE **excluding ties**, ~1.36% | **1.3650%** | HE_player / (1 − P(tie)) |
| Tie at **9:1**, ~4.84% | **4.8440%** | 1 − 10·P(tie) |

The engine exposes none of them: `bc.__all__` has no excluding-ties or
alternate-tie-odds entry, `Baccarat` has no such property, and
`grep "1\.17\|1\.36\|4\.84\|excluding\|9:1"` over the module, the validator and
the test suite returns **nothing**. The tie payout is frozen at
`Fraction(8)` in a module-level dict, so the 9:1 variant is not reachable
through any public path.

The "out of scope, Stake only offers three spots" defence is already closed by
the builder's own precedent: Stake does not offer a pair spot either, and
rounds 1–3 correctly argued the pair column belongs in the module as a
WoO cross-check. Having accepted that principle and shipped
`pair_probability` / `pair_house_edge` / `simulate_pairs`, leaving the last
three WoO-published derived figures out is inconsistent — and it is the whole
of what an expert uses to pick our column out of the pair.

**Biggest remaining gap (the single change):** expose the last three
WoO-published derived figures as exact `Fraction`s and gate them.
Concretely — add `house_edge_excluding_ties(bet, decks)` returning
`house_edge_exact / (1 − P(tie))` (→ 1.1692% / 1.3650%), and make the tie
payout a parameter (`Baccarat("tie", 8, tie_odds=Fraction(9))`, default 8) so
the commission-free-style 9:1 variant edge 4.8440% falls out of the existing
machinery instead of being unreachable; surface both from
`full_payout_table`, and add three Gate-2 checks that **parse** "~1.17%",
"~1.36%" and "~4.84%" out of `references/woo/baccarat.md` and compare at the
printed precision. That turns the last three fillable em-dashes into matching
cells and makes the blind table a genuine coin flip.

## 8. Smaller notes (none verdict-changing)

1. **`CARD_VALUES` is not write-protected.** `CARD_RANKS` and
   `BANKER_DRAW_TABLE` both call `setflags(write=False)`; `CARD_VALUES` does
   not. `bc.CARD_VALUES[0] = 9` silently corrupts every subsequent deal
   process-wide (I did it). One line, and the asymmetry is odd given the other
   two are protected.
2. **`Baccarat.payout_odds` is a mutable public attribute that desynchronises
   the object.** `rtp_exact` reads the private `_mult_exact` frozen at
   construction while `variance_per_unit` reads `self.payout_odds`. Setting
   `eng.payout_odds = Fraction(9)` leaves `rtp` at 0.856404 while
   `variance_per_unit` jumps 6.974 → 8.610 — an internally inconsistent object.
   Making it a read-only property (or the `tie_odds` parameter of §7) fixes
   both this and the 9:1 hole at once.
3. **`config()` still does not name the shoe mechanism** — round 2 asked for
   this and it was not done. It prints `"decks": 8` with no flag saying that
   this is the WoO combinatorial convention (a *fresh* 416-card shoe reshuffled
   every nonce) and **not** Stake's own published mechanism, which is
   `"we utilise an unlimited amount of decks"` with independent
   `floor(float·52)` draws. Reading `decks: 8` off a report, one would
   reasonably conclude Stake published 8 decks. The module docstring handles the
   contradiction well; `config()` should carry one string of it, e.g.
   `"shoe_model": "fresh 8-deck shoe per round (WoO convention)"`.
4. `full_payout_table` constructs three `Baccarat` objects per row. Cosmetic.
5. Not registered in any harness/report/selector registry — but `grep` shows
   **no** game in this repo is, so that is a project convention, not a
   baccarat defect.
