# Baccarat — round 5 critic findings (independent, fresh eyes)

Reviewer stance: harsh, independent. I did not run or read the builder's tests as
evidence. Every number below comes from code I wrote in this session
(`indep.py`, `probe1..6.py`, `blind.py` in my scratchpad) or from the shipped
artifacts run by me end-to-end.

**Verdict: ours_wins = FALSE.** The flagged gap from `gap.md` is genuinely and
exactly closed, the core bar is re-verified, no regressions. But the blind table
still is not a coin flip: our column has two em-dashes where the Stake reference
prints numbers.

---

## 1. The flagged gap — CLOSED, verified exactly

`gap.md` demanded three WoO-published derived figures become reachable through a
public path: Banker/Player house edge **excluding ties** (~1.17% / ~1.36%) and
the Tie bet at **9:1** (~4.84%).

I reproduced the probe with a from-scratch **rank-level** enumerator
(13 ranks × 6 positions, integer falling-factorial weights, exact `Fraction`s,
`import`s nothing from `spinquest_sim` — deliberately a different internal
representation from the engine's value-level enumerator):

| figure | published | my independent value | engine | exact Fraction equality |
|---|---|---|---|---|
| 8d Banker HE excl. ties | ~1.17% | 1.169158% | 1.169158% | **True** |
| 8d Player HE excl. ties | ~1.36% | 1.364966% | 1.364966% | **True** |
| 8d Tie HE at 9:1 | ~4.84% | 4.844032% | 4.844032% | **True** |

Exact rationals the engine returns: `21516253449/1840320169690` (banker),
`7535923321/552096050907` (player). Rounded to 2 dp: 1.17 / 1.36 / 4.84 —
character-identical to the reference.

Structural checks on the fix (not just the three numbers):

- `house_edge_excluding_ties` is in `bc.__all__`; `tie_odds` is a real
  constructor parameter, not a module-dict monkey-patch.
- Identity `edge_excl == house_edge_exact / (1 - P(tie))` holds as exact
  Fractions for decks ∈ {8, 6, 1, ∞} × {player, banker}.
- Cross-model sweep: **0 mismatches** between mine and the engine over 7 shoe
  models (8/6/4/2/1/100/∞) × (2 excluding-ties bets + 4 tie-odds values
  8, 9, 9.5, 11).
- `full_payout_table(8)` surfaces `house_edge_excluding_ties` on the player and
  banker rows (1.1692% / 1.3650%) and `house_edge_9to1` on the tie row
  (4.8440%); the tie row correctly *lacks* the excluding-ties key (a tie bet
  never pushes, so the convention is undefined there) and
  `house_edge_excluding_ties("tie", …)` raises.
- Empirical confirmation of the newly exposed quantities on my own seeds:
  - excluding-ties HE recomputed from my own 12M-round outcome counts as
    `(losses − odds·wins)/resolved`: banker 1.2085% vs exact 1.1692%
    (3SE ±0.0888%, z = +1.33); player 1.3246% vs exact 1.3650%
    (3SE ±0.0910%, z = −1.33).
  - 9:1 tie variant driven end-to-end through `simulate_all_bets(...,
    tie_odds=Fraction(9))`, 10M rounds: empirical HE 4.9838% vs exact 4.8440%
    (3SE ±0.2784%, z = **+1.51**); the run's reported
    `config["payout_odds"] == "9:1"` and `analytic_house_edge == 4.844032%`.
  - `tie_odds` does not leak: player/banker `rtp_exact` and `variance_per_unit`
    are Fraction-identical at `tie_odds` 8 vs 9 for both shoe models; the 9:1
    tie RTP equals `10 · P(tie)` exactly.

## 2. Core bar — re-verified

**Payout-for-payout parity vs the Stake reference (exact Fractions, not floats):
worst difference = exactly 0.**

| bet | Stake published | engine odds | engine total return |
|---|---|---|---|
| Player | 1:1 → 2.00 | `1` | `2` |
| Banker | 0.95:1 → 1.95 | `19/20` | `39/20` |
| Tie | 8:1 → 9.00 | `8` | `9` |
| Pair (WoO) | 11:1 → 12.00 | `11` | `12` |

**Analytics.** My independent enumerator vs the engine: **0 mismatches** on all
16 WoO house-edge cells (4 deck counts × 4 bets), 8-deck RTPs
(98.94/98.76/85.64/89.64), win probabilities (45.86/44.62/9.52), per-unit SDs
(0.93/0.95/2.64, agreeing to 0.00e+00), `outcome_probabilities` as exact
Fractions, and **700 grid cells + 7 denominators** of `total_grid` across
decks 8/6/4/2/1/100/∞. `pair_probability` closed form confirmed against my own
brute-force 4-card rank enumeration: 1/17, 7/103, 5/69, 23/311, 31/415.

**Empirical — 48,000,000 rounds on my own seeds, my own SEs
(σ_exact/√N), my own z:**

| campaign | N | worst \|z\| | detail |
|---|---|---|---|
| 8-deck, seed `a…a` | 12,000,000 | 1.52 | player z −1.34, banker +1.33, tie −0.96; pair z −1.52 / +0.50 |
| infinite deck | 10,000,000 | 1.56 | player +0.47, banker −0.48, tie −1.56; pair +0.57 / −0.84 |
| 1-deck | 6,000,000 | 1.48 | player +0.80, banker −0.81, tie −0.23 |
| 9:1 tie variant | 10,000,000 | 1.51 | see §1 |
| 8-deck excl-ties re-derivation | (12M reused) | 1.33 | see §1 |

**Worst |z| anywhere in my 48M rounds = 1.56 — comfortably inside 3 SE.**
Empirical per-unit SDs at 12M: 0.9511/0.9273/2.6419 vs WoO 0.95/0.93/2.64.
Rank uniformity over all 6 dealt positions, 13 bins each, three shoe models:
chi²(df 12) p-values 0.061 – 0.984, none anomalous. Throughput 530k–800k
rounds/s.

**Fudge hunt — clean.**

- My own HMAC-SHA256 → 4-byte float → card → settle round, written from the
  Stake reference text with zero engine imports: **0 mismatches** vs
  `play_round` over 600 rounds × 4 shoe models (8/∞/1/6), including the float
  values, card indices, both totals, outcome and `events_used`.
- Bulk path: **0 mismatches** over 600 rows vs my scalar for `deal_cards` and
  `deal_rounds`.
- `_cards_matrix` vs my own `pool.pop()` scalar replay: **0 mismatches** over
  14,290 rows across decks 1/2/3/8/100 (small pools stress the ascending
  rank-correction hardest).
- Settle sweep: 40,000 of the 10⁶ possible value-tuples re-settled by my own
  scalar rules vs `_settle_matrix` — **0 mismatches**.
- Published 52-row card index table **parsed out of the reference markdown**:
  52/52 identical to `rng.card_name`, and 52/52 card values identical.
- Banker third-card table re-transcribed by hand from the reference prose:
  **80/80 cells identical**.
- No reference constant (1.06, 1.24, 14.36, 0.93, 45.86, 98.94, 1.17, 4.84, …)
  appears anywhere in `baccarat.py` outside docstrings (AST-based check that
  excludes docstring line ranges).
- Chunk invariance: `chunk_rounds` ∈ {7,919, 50k, 250k, 1M} give byte-identical
  outcome counts and nonce ranges. Nonce accounting: 1,000 rounds → `nonce_next
  == 1000` (one nonce per coup, cursor 0, 1 digest — matching the published
  "games with only 1 incremental number").
- Peak RSS during a 3M-round chunked campaign: **317 MB** (under the 500 MB bar).
- 22/22 adversarial inputs on the *new* surfaces rejected with `ValueError`
  (`tie_odds` ∈ {0, −1, −1/2, True, 1.5, "9", None, NaN}; bad bet names and bad
  deck counts into `house_edge_excluding_ties`; bad `tie_odds` into
  `simulate_all_bets`, rejected *before* any simulation work).

**Regressions from round 4 — all three fixed, none reintroduced:**

- `CARD_VALUES` is now `setflags(write=False)` (as are `CARD_RANKS` and
  `BANKER_DRAW_TABLE`); I tried to mutate all three and all three raised.
- `Baccarat.payout_odds` and `.tie_odds` are read-only properties; assignment
  raises `AttributeError`, so the desync I could previously induce (setting odds
  to 9 while RTP stayed at 0.856404) is impossible.
- `config()` now carries `shoe_mechanism`
  (`fisher_yates_without_replacement` / `independent_floor_52`) plus `tie_odds`.

**Shipped artifacts, run by me:** `scripts/validate_baccarat.py` → 68/68 PASS,
exit 0, 32.7 s (includes its own 10M 8-deck + 2M infinite campaigns).
`pytest tests/test_baccarat.py` → 55 passed, 14.4 s. The RNG core and the
already-passed engines were not touched.

## 3. Blind comparison — still NOT a coin flip

I built the side-by-side of every published quantity in
`references/stake/baccarat.md` + `references/woo/baccarat.md` against what our
engine emits, labels stripped (`blind.py`). 48 quantities. Two of the four
flagged "DIFF" rows are my own label wording for block comparisons (the 52-row
card table and the 80-cell banker table are verified identical cell by cell).

**Real result: 46 of 48 character-identical. Two holes, both in our column:**

| quantity | col A | col B |
|---|---|---|
| Stake overall house edge | **1.10%** | **—** |
| Stake overall RTP | **98.90%** | **—** |

Every other cell — the whole 16-cell WoO grid, the four 8-deck RTPs, the three
win probabilities, the three SDs, the three previously-missing derived figures,
all four payout odds and total returns, events/round 6, cursor 0, 1 digest,
card values, the CARDS endpoints — matches character for character.

An expert shown these two columns picks the one with the em-dashes as the
imitation on sight. That is exactly the argument `gap.md` used against the three
now-closed cells; the standard has to apply here too. **The blind comparison
favors the reference, so ours does not win.**

## 4. The ONE biggest remaining gap

**Stake's headline "1.10% overall house edge / 98.90% RTP" has no representation
anywhere in the engine's public surface, leaving the only two holes in the blind
table.**

I confirmed the previous critic's premise that it is not a bare mathematical
constant. I searched the obvious formulas against the exact 8-deck edges
(banker 1.057906%, player 1.235081%, tie 14.359629%):

| candidate | value | |diff to 1.10%| |
|---|---|---|
| harmonic mean(b,p) | 1.1396% | 0.0396 |
| banker alone | 1.0579% | 0.0421 |
| geometric mean(b,p) | 1.1431% | 0.0431 |
| P(win)-weighted(b,p) | 1.1453% | 0.0453 |
| arithmetic mean(b,p) | 1.1465% | 0.0465 |
| mean(b,p) at 6 decks / ∞ | 1.1466% / 1.1461% | 0.0466 / 0.0461 |
| mean(b,p,tie) | 5.5509% | 4.4509 |
| mean of excluding-ties edges | 1.2671% | 0.1671 |

Nothing lands near it. 1.10% is a *portfolio* figure: it needs a banker/player
weighting of **76.24% / 23.76%**, and any weight on the tie spot forces the
other weights negative. So it is not a constant to reproduce.

But "not a constant" is not the same as "not reachable" — and that is where the
current state fails. The blended edge of a bet mix is exact, ordinary engine
math, and the engine does not expose it at all: `grep` for `overall|blend|mix`
across `baccarat.py` returns **nothing** (`bc.__all__` has no such entry). The
only acknowledgement anywhere is a bracketing assertion buried in
`scripts/validate_baccarat.py:188-197` — "1.10 lies between the exact banker and
player edges" — which is honest but lives in the validator, never produces the
number, and is invisible to anyone reading the engine's payout table.

**The single change:** add an exact
`portfolio_house_edge(weights, decks=8) -> Fraction`
(Σ wᵢ · edgeᵢ over `player`/`banker`/`tie`, weights validated non-negative and
summing to 1) plus its exact inverse
`implied_banker_weight(target_edge, decks=8) -> Fraction`
(= (edge_player − target)/(edge_player − edge_banker), raising when the target
falls outside `[edge_banker, edge_player]`). Surface both from
`full_payout_table` as an `overall` block that reports the achievable edge range
`[1.0579%, 1.2351%]` and states that Stake's published 1.10% / 98.90%
corresponds exactly to a **76.24% banker / 23.76% player** mix — derived, with
the assumption named, not fabricated. Add Gate-2 checks that parse
`"house edge of just ([\d.]+)% overall"` and `"RTP\D*([\d.]+)%"` out of
`references/stake/baccarat.md` and verify `portfolio_house_edge` at the implied
mix round-trips to 1.10% and 98.90% to 2 dp. That fills both holes with exact
engine math and makes the blind table 48/48.

This is the same failure mode rounds 1–4 flagged for the pair column and then
for the excluding-ties column: a published figure that the engine's own
machinery can reach but no public path exposes. The pair-bet precedent (Stake
offers no pair spot, yet it was correctly added as a WoO cross-check) and the
just-completed excluding-ties precedent (a *derived-convention* figure, not a
raw constant, and it was still added) both close the "not a real constant"
defence.

## 5. Minor defects (not the gap, but worth fixing)

1. **Inconsistent config shape inside one table.** `pair_summary(...)["config"]`
   omits `tie_odds` and `tie_pushes_player_banker`, which `Baccarat.config()`
   carries, so the five rows of `full_payout_table` have two different config
   key sets. A consumer iterating the table and reading `row["config"]["tie_odds"]`
   crashes on the pair rows.
2. **`full_payout_table` builds three `Baccarat` objects per bet**
   (`analytic_summary()`, `win_probability`, `push_probability` each construct a
   fresh one) plus a fourth for the 9:1 tie row. Harmless (everything is
   `lru_cache`d underneath) but it is dead work in a hot-ish public API.
3. `house_edge_excluding_ties` correctly raises for `"tie"`, but the message
   says "player/banker only" without pointing at the reason surfaced in the
   docstring; a caller iterating `BET_TYPES` hits it. Consider returning the
   identical headline edge for `"tie"` instead of raising, or documenting the
   iteration hazard at the `full_payout_table` call site (which already handles
   it correctly).

None of these affect a single published number.

---

### Files

- Engine: `/home/user/troyrhinehart/casino/spinquest_sim/games/baccarat.py`
- Validator: `/home/user/troyrhinehart/casino/scripts/validate_baccarat.py`
  (the 1.10% bracketing check is at lines 188–197)
- Tests: `/home/user/troyrhinehart/casino/tests/test_baccarat.py`
- My independent enumerator and probes:
  `/tmp/claude-0/-home-user-troyrhinehart/b3ce270f-e608-55a6-8515-5735b66f4ebe/scratchpad/{indep,probe1,probe2,probe3,probe4,probe5,probe6,blind}.py`
