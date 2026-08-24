# Baccarat — Gauntlet Round 1 (independent critic)

Reviewer: fresh-eyes critic. Nothing in `tests/test_baccarat.py` or
`scripts/validate_baccarat.py` was taken on trust — every number below was
recomputed from the reference markdown with throwaway code that does not
import `spinquest_sim.games.baccarat`.

**Verdict: ours_wins = FALSE.** Payouts match exactly, statistics pass
comfortably, no fudges found — but the blind side-by-side is *not* a coin
flip. It is decided by absence, not by error.

---

## 1. Independent recomputation of the reference math

Throwaway enumerator (`indep_enum.py`): exact `Fraction` recursion over the
shoe, drawing rules typed in from the Stake §4 prose only, no engine import.

| Decks | Banker HE | Player HE | Tie HE | WoO published |
|---|---|---|---|---|
| 8 | 1.0579% | 1.2351% | 14.3596% | 1.06 / 1.24 / 14.36 ✓ |
| 6 | 1.0558% | 1.2374% | 14.4382% | 1.06 / 1.24 / 14.44 ✓ |
| 1 | 1.0117% | 1.2864% | 15.7461% | 1.01 / 1.29 / 15.75 ✓ |
| Infinite | 1.0640% | 1.2281% | 14.1170% | 1.064 / 1.228 / 14.117 ✓ |

8-deck win probabilities: P(player) 0.446247, P(banker) 0.458597,
P(tie) 0.095156 → 44.62 / 45.86 / 9.52% ✓.
Per-unit SDs: 0.9512 / 0.9274 / 2.6409 → 0.95 / 0.93 / 2.64 ✓.

All 16 house-edge cells, all 3 probabilities and all 3 SDs of the WoO page
reproduce from first principles. My ground truth is therefore established
independently of the builder.

## 2. Engine vs that ground truth

`Baccarat(bet, decks).house_edge / .std_per_unit` and
`outcome_probabilities(decks)` agree with my enumerator **to full double
precision** on all four deck configurations (not just to published dp).

`total_grid()` compared cell-by-cell as exact rationals against my grid:

* `total_grid(8)`: **0 of 100 cells differ**; denominator
  `4,998,398,275,503,360 == 416·415·414·413·412·411` (WoO Appendix-1 total
  combinations).
* `total_grid(None)`: **0 of 100 cells differ**; denominator `52**6`.

### Payout-for-payout vs Stake §5

| Bet | Stake published | Engine (`PAYOUT_ODDS` / `MULTIPLIERS`) | Diff |
|---|---|---|---|
| Player | 1:1 → 2.00 | `Fraction(1)` → 2.00 | 0 |
| Banker | 0.95:1 → 1.95 | `Fraction(19,20)` → 1.95 | 0 |
| Tie | 8:1 → 9.00 | `Fraction(8)` → 9.00 | 0 |

Worst payout difference across all three bets: **0** (exact `Fraction`
equality, not float-tolerance). Tie pushes Player/Banker (`payouts_for_outcomes`
returns 1.0 on code 2) ✓.

Drawing table re-derived from the §4 prose and compared row-for-row:
0/1/2 → all; 3 → all but 8; 4 → 2–7; 5 → 4–7; 6 → 6–7; 7 → stand; rows 8/9
unreachable and all-False; player stands on 6–7 → banker draws on 0–5. All
match `BANKER_DRAW_TABLE`. Table is `write=False`.

## 3. Fudge hunt

* **Hardcoded empirical results:** none. `grep` for `1.06 | 45.86 | 14.36 |
  98.9 | 0.93` in `games/baccarat.py` hits **docstring comments only** —
  no reference constant is consumed by any code path. Every published
  figure is *derived* from `_enumerate`.
* **Sim not actually using the engine:** refuted. I rebuilt the whole
  pipeline independently — my own `pool.pop(floor(f·len))` without-replacement
  draw and my own settle — and `bc.deal_rounds(rng, 200_000, 8)` is
  **bit-for-bit equal** to it. `_cards_matrix(decks=8)` also equals my slow
  pool-pop draw on 3,000 rows, and equals `_cards_scalar` on 300 rounds.
* **Settle logic:** `_settle_matrix` checked against my independent settle on
  **all 10^6 possible value vectors** (exhaustive, `10**6 × 6`): 0 mismatches.
  Scalar `settle_values` matches on 20k random vectors including
  `events_used` and both totals.
* **Provably-fair integrity:** `deal_rounds` varies with server seed, varies
  with `nonce_start`, and is reproducible with the same seed.
  `play_round(ss, cs, i)["outcome"]` equals `deal_rounds` row *i* over 200
  rounds. `play_round`'s `player_cards`/`banker_cards` are exactly a partition
  of the first `events_used` dealt cards (checked 2,000 rounds), and their
  named-card totals reproduce `player_total`/`banker_total`.
* **Nonce accounting:** one nonce per coup, contiguous. 10M-round run reports
  `nonce_range == (0, 10_000_000)`; a chunked run
  (`chunk_rounds=400_000`, `nonce_start=777`) reports `(777, 2_500_777)`.
  6 events, 1 digest, `CURSOR_INCREMENTS['baccarat'] == 1` ✓.
* **Shoe integrity:** finite-shoe rounds draw 6 **distinct** pool ids in
  [0,416) (0 duplicate rows in 20k), and no card index appears >8 times in a
  round.
* **Edge cases:** all 11 invalid-input paths raise —
  wrong float/value count, value 10, card index 52, unknown bet type,
  `decks=0`, `decks=True` (bool-as-int trap closed), `n_rounds<=0`,
  `banker_draws(8, ·)`, `banker_draws(3, 10)`, wrong matrix shape.
  `decks=1` (52 cards, 6 draws) and `decks=100` both enumerate to exactly 1.
* **Float precision:** `floor(f·(416−j))` — `k·411` is ≤41 bits over a
  power-of-two denominator, exact in float64; no rounding bias. Max float
  `1 − 256⁻⁴ < 1`, so no index overflow.
* **Builder's own suite:** `pytest tests/test_baccarat.py` → 39 passed.
  `scripts/validate_baccarat.py` → **51/51 PASS**, exit 0.

## 4. My own empirical runs (not the builder's seed)

The validation script ships a *fixed* default seed, so I ran my own seeds.

**4 independent seeds × 10M rounds, `decks=8`, through the public
`bc.deal_rounds` API**, SE computed by me as `analytic_SD / sqrt(N)`:

| Seed | z(player) | z(banker) | z(tie) | 3-cat χ² (df 2) p |
|---|---|---|---|---|
| 0 | −0.265 | +0.252 | −1.724 | 0.219 |
| 1 | −1.564 | +1.575 | +1.435 | 0.104 |
| 2 | +1.453 | −1.457 | −0.534 | 0.301 |
| 3 | −0.581 | +0.588 | +0.858 | 0.583 |

Worst |z| = **1.724**, well inside 3 SE. Builder's own 10M run:
z = −0.63 / +0.62 / −1.47.

**Sharper test — 20M rounds, 100-cell (player_total, banker_total) grid vs my
exact grid:** χ² = **92.07, df = 99, p = 0.676**, all 100 cells with E ≥ 5,
worst standardized residual z = +2.47 at (6,7). This is a far more
discriminating test than the 3-cell RTP gate and it passes cleanly.

**Infinite-deck path (Stake's actual published mechanism), 10M rounds** via
`rng.baccarat_cards` + my own settle: 100-cell χ² = **86.38, df = 99,
p = 0.813**. Through `simulate_all_bets(10M, decks=None)`:
z = +1.539 / −1.526 / +1.545, `pass = True`.

**Serial structure:** lag-1 3×3 transition χ² = 6.857, df 4, p = 0.144.
Run-length distribution over 3 seeds × 10M: p = 0.158 / 0.461 / 0.826 —
statistically indistinguishable from a numpy-PRNG control at the same p
(0.381 / 0.398 / 0.521). (An earlier p = 0.002 I saw was my own
misspecified test — fixed p, truncated with no tail cell — not the engine.)

**Card-layer rank fidelity:** first-two-cards pair rate over 5M rounds:
player 0.074984, banker 0.074613 vs exact 31/415 = 0.074699 (z = +2.43 /
−0.73). The rank information needed for pair bets is present and correct in
the stream.

Totals: ~**125M rounds** simulated by me (plus the builder's 10M), at
**608k–636k rounds/s** single-threaded; 10M rounds in 12.3–16.2 s.

## 5. Blind comparison (labels stripped)

Two unlabeled columns, 34 published cells drawn from `woo/baccarat.md` +
`stake/baccarat.md`, each rendered to the reference's own precision:

```
              | COLUMN X   | COLUMN Y
8 banker      | 1.06%      | 1.06%
8 player      | 1.24%      | 1.24%
8 tie         | 14.36%     | 14.36%
8 pair        | 10.36%     | —              <-- differs
6 banker/…    | 1.06/1.24/14.44%  | identical
6 pair        | 11.25%     | —              <-- differs
1 banker/…    | 1.01/1.29/15.75%  | identical
1 pair        | 29.41%     | —              <-- differs
inf banker/…  | 1.064/1.228/14.117% | identical
inf pair      | 7.69%      | —              <-- differs
RTP bnk/plr/tie | 98.94/98.76/85.64% | identical
RTP pair      | 89.64%     | —              <-- differs
P(b)/P(p)/P(t)| 45.86/44.62/9.52%  | identical
SD b/p/t      | 0.93/0.95/2.64     | identical
pay p/b/t     | 1:1 / 0.95:1 / 8:1 | identical
ret p/b/t     | 2.00 / 1.95 / 9.00 | identical
overall edge  | 1.10%      | —              <-- differs
overall RTP   | 98.90%     | —              <-- differs
```

**27 of 34 cells are identical. 7 differ, and every one of the 7 is a hole,
not a wrong number.** An expert asked "which is the imitation?" picks
Column Y instantly — it is the one with blanks. That is not a coin flip.

Two of the seven (`1.10% overall`, `98.90% RTP`) are Stake marketing figures
whose bet-mix weighting the reference itself says is unpublished; **no**
faithful implementation could fill them, so I do not hold those against the
engine. `validate_baccarat.py` only checks that 1.10% lies between the exact
banker and player edges — a band-check any value in [1.058%, 1.235%] would
pass — which is honest but very weak.

The other five are the **Pair bets (11:1)** column, and those are a real gap.

## 6. The gap

`woo/baccarat.md` — the designated *statistical ground truth* — publishes a
fourth column the engine cannot produce at all:

| | 8 deck | 6 deck | 1 deck | Infinite | RTP (8d) |
|---|---|---|---|---|---|
| Pair bets (11:1) | 10.36% | 11.25% | 29.41% | 7.69% | 89.64% |

I verified independently that these are exactly derivable in closed form —
`P(pair) = (4d−1)/(52d−1)`, RTP `= 12·P`:

```
 8 decks: 31/415 = 0.074699 → RTP 0.896386 → HE 10.3614%  ✓ 10.36
 6 decks: 23/311 = 0.073955 → RTP 0.887460 → HE 11.2540%  ✓ 11.25
 1 deck :   3/51 = 0.058824 → RTP 0.705882 → HE 29.4118%  ✓ 29.41
 infinite:  1/13 = 0.076923 → RTP 0.923077 → HE  7.6923%  ✓  7.69
```

Three aggravating factors:

1. **The engine already reproduces rows Stake does not offer.** It publishes
   the 6-deck, 1-deck and infinite-deck edges — configurations no Stake table
   has. "Stake has no pair spot" therefore cannot be the reason this column
   is absent; the engine's own posture is to reproduce the whole WoO table.
2. **The exact analytics are structurally incapable of it.** `_enumerate`
   works on card *values*, collapsing 10/J/Q/K into value 0, so rank — and
   hence "pair" — is unrecoverable from anything the module exposes. This is
   not a missing wrapper, it is a missing dimension in the analytic model.
   The *card* layer does carry rank (confirmed: empirical pair rate matches
   31/415), so only the analytic/settle layer needs the work.
3. **The validator hides it.** `gate_woo_analytics`'s regex
   `^\|\s*(8 \(standard\)|6|1|Infinite)\s*\|\s*\**([\d.]+)%\**\s*\|…` has
   three capture groups for a four-column table — it silently drops the Pair
   bets column, and the "Equivalent RTP … Pair bets 89.64%" line is never
   parsed. The suite reports 51/51 PASS on a table it only reads ¾ of. A
   validator that parses a reference table should fail loudly on a column it
   cannot account for.

**Single change that most closes the distance:** add rank-level pair analytics
— a `PAIR_ODDS = Fraction(11)` row plus `pair_probabilities(decks)` returning
`Fraction(4d−1, 52d−1)` (and `Fraction(1,13)` for infinite), a
`player_pair`/`banker_pair`/`either_pair` settle off the existing
rank-carrying card stream, and a 10M-round empirical gate on it — then widen
the `gate_woo_analytics` regex to four columns so the Pair row is checked like
the other three. That turns a 27/34 blind column into 32/34, leaving only the
two underivable Stake marketing cells, which every faithful clone shares.

### Secondary observations (not the gap, but worth recording)

* **No configuration is simultaneously Stake-native and WoO-8-deck-gated.**
  Gate 1 verifies the published `floor(float·52)` mapping on
  `sq_rng.baccarat_cards` (infinite deck); Gate 3's 10M rounds run
  `decks=8`, whose Fisher–Yates-over-416 mapping the Stake reference §2
  explicitly excludes for baccarat. Neither is wrong — they are two different
  games and the engine documents both — but the shipped validator gives the
  Stake-native config no empirical gate at all. I ran one myself (§4, passes),
  so this is a coverage gap, not a defect. Cheap fix: run the empirical gate
  over both `decks=8` and `decks=None`.
* **`config()` does not disclose the per-coup reshuffle.** It reports
  `{"variant": "punto_banco", "decks": 8}`, which reads as a shoe; the
  module actually deals 6 cards from a *freshly shuffled* 416-card shoe every
  round (correct for matching WoO's fresh-shoe combinatorics, and correct for
  Stake, which has no shoe — but a consumer reading `config()` would assume
  shoe continuity, card-removal drift and the streak behaviour WoO's later
  appendices describe). Add `"shoe_reset_per_coup": True`.
* **Event 4/5 seat assignment when the player stands on 6–7** uses physical
  shoe order (event 4 becomes the *banker's* third card) rather than fixed
  slots. Stake does not publish this mapping; shoe order is the more
  defensible reading of "we only ever need 6 game events", the module says so
  explicitly, and it is statistically neutral under exchangeability. Not a
  defect — flagged only because it is the one round-level behaviour an expert
  with access to Stake's verifier could use to distinguish.
* `harness.py`, `selector.py`, `session.py`, `report.py`, `games/__init__.py`
  and `mcp_server` are all bare stubs — baccarat is not wired into any
  pipeline. This is uniform across every game, so it is a project-level gap,
  not a baccarat one.

## 7. Scorecard

| Criterion | Result |
|---|---|
| Payouts reproduce Stake exactly | **PASS** — worst diff 0, exact Fractions |
| Probabilities reproduce WoO to published precision | **PASS** — 16/16 edge cells, 3/3 probs, 3/3 SDs, full double precision vs my enumerator |
| 10M+ rounds within 3 SE | **PASS** — 4 seeds × 10M, worst \|z\| = 1.724; 20M-round 100-cell χ² p = 0.676 |
| No fudges | **PASS** — no hardcoded results, sim provably runs the engine, all edge cases raise |
| Blind comparison a coin flip | **FAIL** — 27/34 identical, 7 blanks give it away |
