# Baccarat — Gauntlet Round 2 (independent critic)

Reviewed: `/home/user/troyrhinehart/casino/spinquest_sim/games/baccarat.py`,
`/home/user/troyrhinehart/casino/scripts/validate_baccarat.py`,
`/home/user/troyrhinehart/casino/tests/test_baccarat.py`.
Ground truth: `references/stake/baccarat.md`, `references/woo/baccarat.md` only.
Everything below was measured by the critic; none of the builder's own tests were
trusted as evidence.

**Verdict: ours does NOT win.** Not because anything is wrong — the math is
flawless — but because the blind side-by-side has 5 cells where our column is
blank and the reference's is not. See §6.

---

## 1. Independent analytic recomputation (from-scratch enumerator)

Script: `/tmp/.../scratchpad/bacc/indep_enum.py` — written from the reference
rules text, importing nothing from `spinquest_sim`. Model: fresh shoe of 52·D
cards, 6 ordered positions always consumed without replacement (so the common
denominator is the falling factorial), values A=1 / 2–9 pip / 10-J-Q-K=0.

My enumerator's 8-deck combination counts:

| | combinations |
|---|---|
| Banker wins | 2,292,252,566,437,888 |
| Player wins | 2,230,518,282,592,256 |
| Tie | 475,627,426,473,216 |
| **Total** | **4,998,398,275,503,360** = 416·415·414·413·412·411 |

That total is WoO's published 8-deck denominator, which is itself the proof that
the fresh-416-shoe / 6-positions convention is the one the reference's
"exact combinatorial analysis" uses. Derived edges: Banker 1.057906%, Player
1.235081%, Tie 14.359629% → **1.06 / 1.24 / 14.36** ✔; SDs 0.927372 / 0.951153 /
2.640872 → **0.93 / 0.95 / 2.64** ✔; win probs 45.859742 / 44.624661 / 9.515597 →
**45.86 / 44.62 / 9.52** ✔.

Engine vs mine, compared as **exact `Fraction`s, not floats**, for
decks = 8 / 6 / 1 / infinite:

* `outcome_probabilities(d)` — exact equality, all 4 shoes.
* `total_grid(d)` — **all 100 cells** exact equality, all 4 shoes; denominators
  identical (4,998,398,275,503,360 / 878,869,206,895,680 / 14,658,134,400 /
  19,770,609,664).
* `house_edge_exact` — exact equality for all 3 bets × 4 shoes.

Every published WoO row reproduces at printed precision, including the two the
builder could easily have fudged: 6-deck Tie **14.44%** and 1-deck
**1.01 / 1.29 / 15.75**, and the infinite row at 3 dp **1.064 / 1.228 / 14.117**.

## 2. Payout-for-payout vs the Stake reference (§5)

| Bet | Stake published | engine `PAYOUT_ODDS` | Stake total return | engine `MULTIPLIERS` |
|---|---|---|---|---|
| Player | 1:1 | `Fraction(1)` = 1:1 | 2.00 | `2` |
| Banker | 0.95:1 | `Fraction(19,20)` = 0.95:1 | 1.95 | `39/20` = 1.95 |
| Tie | 8:1 | `Fraction(8)` = 8:1 | 9.00 | `9` |

Worst payout discrepancy: **0** (exact rationals, not floats — `19/20` and
`39/20`, so no 0.9499999 drift). Tie pushes Player and Banker: confirmed via
`payouts_for_outcomes([2]) == 1.0` for both. Per-bet published edges 1.06 / 1.24 /
14.36 and RTPs 98.94 / 98.76 / 85.64 all reproduce. Stake's headline "1.10%
overall" is not derivable from the published data (a banker/player blend needs an
unpublished ≈76/24 weighting; any tie weight would have to be negative) — the
engine correctly declines to invent it and only bounds it.

Drawing rules re-transcribed by hand from §4 and compared to
`BANKER_DRAW_TABLE`: rows 0–2 all, row 3 = {0–7,9}, row 4 = {2–7}, row 5 = {4–7},
row 6 = {6,7}, row 7 = ∅ — identical. Player-stands branch (banker draws 0–5) is
the standard punto banco completion of Stake's player-third-card-only phrasing;
it is what makes the WoO numbers come out, so it is confirmed by §1.

## 3. Is the simulator actually the engine + the published RNG?

* I reimplemented Stake's `byteGenerator`/`generateFloats` from the §1/§2 JS
  (raw `hmac.new(server, f"{client}:{nonce}:{round}", sha256)`, float =
  Σ bᵢ/256^(i+1)). Bit-identical to `sq_rng.generate_floats` and to
  `BulkRng.float_matrix` over 300 nonces × 6 floats.
* I wrote a **complete independent round** (raw HMAC → `floor(f·52)` → my own
  value map → my own drawing rules) and it matched
  `Baccarat(decks=None).play_round` on **400/400** nonces.
* `deal_rounds` == `play_round` outcome-for-outcome over 500 consecutive nonces,
  for **both** deck models; `nonce_next` advanced exactly 500 (one nonce per
  round, cursor 0, 6 events, 1 digest — as published).
* Parallel + chunked bulk path (3M rows, `workers=4`, crosses both the
  `_PARALLEL_MIN_DIGESTS`=400k and `_CHUNK_FLOAT_BUDGET` boundaries): 48 sampled
  rows including every chunk seam are bit-identical to the scalar path.
* Seed dependence: three different server seeds → three different outcome counts
  and RTPs. No hardcoded results anywhere; the only occurrences of `1.06`,
  `14.36`, `0.93` etc. in the module are docstring prose.

## 4. Settle-logic torture test

* **Exhaustive**: all 10⁶ value 6-tuples through `bc._settle_matrix` vs my
  independent scalar settler → **identical on every one**. Also `settle_values`
  (scalar) vs `_settle_matrix` on a 200k subset → identical.
* `CARD_VALUES` rebuilt independently from the published index table (idx//4 =
  rank, ♦♥♠♣ within rank) → identical; spot checks ♦2=2, ♦10=0, ♦A=1, ♣A=1.
* `_cards_matrix` (vectorised rank-correction) == `_cards_scalar` (pop-order
  Fisher–Yates on the 52·D pool) over 3000 rows × 4 shoe models. The 8-deck pool
  ids are distinct in all 2000 sampled rounds (no card copy dealt twice).
* Boundary floats 0.0 and 1−2⁻³² behave (`[0,1,2,3,4,5]` / `[51,50,49,48,47,46]`
  finite; `[0]*6` / `[51]*6` infinite), matrix == scalar at both extremes.
* Input validation is real, not decorative: bad bet type, `decks=0/-3/True/8.0`,
  `card_value(±out of range)`, `banker_draws(8,·)`, `banker_draws(3,10)`,
  6-element contracts, `n_rounds<=0` all raise `ValueError`.

## 5. My own empirical runs (all through the public API)

Fresh server seeds of my own, `simulate_all_bets` / `Baccarat.simulate`,
chunked at 2M rounds (≈96 MB peak float matrix). SEs computed by me as
σ_exact/√N with σ from **my** enumerator.

**200,000,000 rounds, 8-deck** (`z` on house edge):

| Bet | empirical edge | exact | 3 SE | z |
|---|---|---|---|---|
| Player | 1.243675% | 1.235081% | ±0.020177% | **+1.278** |
| Banker | 1.049543% | 1.057906% | ±0.019673% | **−1.275** |
| Tie | 14.365225% | 14.359629% | ±0.056021% | **+0.300** |

Win probs at 200M: P(player) z=−1.13, P(banker) z=+1.31, P(tie) z=−0.30.

Other campaigns, every z inside ±3:

| campaign | N | max \|z\| |
|---|---|---|
| 8-deck | 40,000,000 | 2.23 (P(banker)) |
| infinite-deck | 20,000,000 | 2.04 (P(banker)); edges → 1.0268 / 1.2664 / 14.1807 vs exact 1.0640 / 1.2281 / 14.1170 |
| 6-deck | 12,000,000 | 1.61 |
| 1-deck (hardest depletion: a value can be exhausted mid-round) | 12,000,000 | 1.04 |

**100-cell total-grid χ²** (the strong test — a wrong third-card rule can leave
the 3 win probabilities near-right while wrecking the total distribution):
20,000,000 rounds, engine card path + *my* rules, all 100 cells expected ≥ 5:
**χ² = 112.66, df = 99, p = 0.165**. Worst single cell (P=1,B=2) z = −3.30, which
is the expected max of 100 standard normals. Engine `_settle_matrix` codes
disagreed with my codes on **0 of 20,000,000** rounds.

`scripts/validate_baccarat.py` run by me, unmodified: **51/51 PASS**, 10M rounds
in 16.7 s (598k rounds/s). My runs measured 549k–1,006k rounds/s. `_enumerate(8)`
cold 0.14 s. `pytest tests/test_baccarat.py`: 39 passed.

Total rounds I put through the engine: **~340 million**, wall ~11 min.

## 6. Blind side-by-side (labels stripped)

34 published quantities, two unlabelled columns:

```
quantity                 |                 col X |                 col Y | match
-------------------------+-----------------------+-----------------------+------
Player payout            |                   1:1 |                   1:1 | =
Banker payout            |                0.95:1 |                0.95:1 | =
Tie payout               |                   8:1 |                   8:1 | =
Player / Banker / Tie total return  2.00 1.95 9.00 | same              | =
Tie -> P/B bets          |                  push |                  push | =
edge Banker/Player/Tie 8d|   1.06% 1.24% 14.36%  |   1.06% 1.24% 14.36%  | =
edge Banker/Player/Tie 6d|   1.06% 1.24% 14.44%  |   1.06% 1.24% 14.44%  | =
edge Banker/Player/Tie 1d|   1.01% 1.29% 15.75%  |   1.01% 1.29% 15.75%  | =
edge Banker/Player/Tie inf| 1.064% 1.228% 14.117%| 1.064% 1.228% 14.117% | =
edge Pair 8d             |                10.36% |                     — | DIFF
edge Pair 6d             |                11.25% |                     — | DIFF
edge Pair 1d             |                29.41% |                     — | DIFF
edge Pair inf            |                 7.69% |                     — | DIFF
P(Banker/Player/Tie) 8d  |  45.86% 44.62% 9.52%  |  45.86% 44.62% 9.52%  | =
RTP Banker/Player/Tie 8d |  98.94% 98.76% 85.64% |  98.94% 98.76% 85.64% | =
RTP Pair 8d              |                89.64% |                     — | DIFF
SD Banker/Player/Tie     |    0.93  0.95   2.64  |    0.93  0.95   2.64  | =
8d combo denominator     | 4,998,398,275,503,360 | 4,998,398,275,503,360 | =
```

**29 of 34 cells are character-identical. The 5 that are not are all the
pair-bet column, and in every one of them our column is an em-dash.** An expert
handed these two columns needs about two seconds: the one with holes in it is the
imitation. That is not a coin flip, so by the stated rule ours does not win.

Behavioural artifacts (`play_round` transcripts, e.g. nonce 0:
`P[♠A,♦Q,♦8]=9 B[♦2,♠J,♣A]=3, used=6 → player`) are indistinguishable from a real
punto banco log — card names from the published CARDS index, `events_used` always
equal to the number of cards actually shown (0 mismatches in 5000 rounds), 4/5/6
card rounds in the right proportions. Nothing there gives ours away.

## 7. The one gap, and why it is not merely "out of scope"

`references/woo/baccarat.md` is designated statistical ground truth. Its
house-edge table has **five** columns and the engine reproduces four; its RTP line
publishes four figures and the engine reproduces three. Pair bets 11:1 —
10.36% (8d) / 11.25% (6d) / 29.41% (1d) / 7.69% (inf), RTP 89.64% — are absent
entirely (`grep pair|rank` over `bc.__all__` → nothing).

The tempting defence is scope: Stake's game page lists three spots
(Player/Tie/Banker), so a pair *bet spot* would be wrong for Stake. Fair. But
that is not the whole story, and here is why it matters:

**The engine's exact analytics are value-only.** `_enumerate` carries state in
baccarat values 0–9, with 16 cards collapsed into "value 0". Rank identity — the
thing that separates ♦10 from ♦J — does not exist anywhere in the analytic layer.
So the *one* published statistic that would test the shoe model at **rank**
granularity is exactly the one the analytics structurally cannot express. Right
now the 8-deck shoe is verified at value granularity only, and that gap is
invisible in the current 51-check validator.

I closed that hole myself, and the good news is the card path is correct: closed
form P(pair) = (4D−1)/(52D−1), = 1/13 for infinite, so edge = 1 − 12·P →
**10.3614% / 11.2540% / 29.4118% / 7.6923%**, reproducing WoO's column exactly.
Measured through `bc._cards_matrix` at 8M rounds per shoe:

| decks | exact P(pair) | empirical | z |
|---|---|---|---|
| 8 | 0.074699 | 0.074605 | −1.01 |
| 6 | 0.073955 | 0.073748 | −2.24 |
| 1 | 0.058824 | 0.058673 | −1.81 |
| ∞ | 0.076923 | 0.077025 | +1.08 |

and 8-deck player pair z=−0.30 / banker pair z=−1.34 at 4M. So the fix is not a
bug fix — it is ~30 lines of coverage that turns the last blank column in the
blind table into a filled one and upgrades the shoe verification from value-level
to rank-level.

**Biggest remaining gap (the single change):** add rank-level pair analytics —
`pair_probability(decks)` / `pair_house_edge(decks)` as exact `Fraction`s from
(4D−1)/(52D−1) (1/13 infinite) at 11:1, expose them from
`full_payout_table`, and add a Gate-2 check parsing WoO's pair column
(10.36 / 11.25 / 29.41 / 7.69 and RTP 89.64%) plus a Gate-3 empirical
rank-granularity gate on the dealt card indices. Keep them clearly marked as
WoO-cross-check quantities, not Stake bet spots (Stake offers three spots).

## 8. Smaller notes (none verdict-changing)

1. **8-deck default vs Stake's own §3.** Stake's primary source says
   "we utilise an unlimited amount of decks", i.e. `floor(float·52)` with
   replacement, whose edges are 1.064 / 1.228 / 14.117 — not the 1.06 / 1.24 /
   14.36 Stake prints on the same site. The WoO file itself admits it has no
   Stake-specific page and is *assuming* 8-deck. The engine implements both,
   documents the contradiction, and defaults to 8 to match the stated bar. That
   is the strongest available handling of a genuine conflict in the sources; I
   would only ask that `config()` surface a flag naming which of the two
   published mechanisms is active in a way a report can print, since "decks: 8"
   alone reads as if Stake published 8 decks.
2. **Fresh shoe every round.** A physical 8-deck table deals from a continuing
   shoe; this reshuffles per nonce. That is both what WoO's combinatorics assume
   and the only coherent model for a per-nonce provably-fair game. Correct, but
   worth one sentence in `config()` so nobody reads `decks=8` as shoe-tracking
   being possible.
3. **Seat-assignment order of the 6 events** is unpublished (the reference says
   so explicitly) and, because the 6 positions are exchangeable, cannot affect
   any distribution. Unverifiable, harmless, honestly documented.
4. `full_payout_table` constructs three `Baccarat` objects per row. Cosmetic.
5. Not registered in any harness/report registry — but no game in this repo is,
   so that is a project convention, not a baccarat defect.
