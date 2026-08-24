# Blackjack — Gauntlet Round 1 (independent critic)

**Verdict: FAIL.** The engine is well-engineered and its internal math is exact — but it
implements the **wrong rule set**, so its headline house edge is **0.520766%** where the
reference ground truth is **0.511734%**. The builder's validator hides this behind a
hand-picked tolerance (`ABS_ANALYTIC_TOL = 1.5e-4`, sized just above the 9.03e-5 error)
and a false comment calling the gap a "closed-form approximation".

---

## 1. What I did (nothing trusted from the builder)

| Artifact | Purpose |
|---|---|
| `indep_bj.py` | From-scratch infinite-deck EV DP (my own dealer recursion, my own hit/stand/double DP, my own **sequential pending-hand split recursion** `g(m,b)`) |
| `indep_dist.py` | From-scratch exact **payout-distribution** calculator → variance/SD, independent of the EV DP |
| `strat_cmp.py` | My strategy chart vs the engine's five tables, cell by cell |
| `indep_replay.py` | My own HMAC-SHA256 `byteGenerator` + `generateFloats` + `floor(f*52)` + my own round player, replayed against `play_round` **and** `simulate` |
| 60M-round run | My own campaign (fresh seed `c0ffee11…`, client `critic-independent-run-r1`) through the engine's public API, my own SE |

(Scratch scripts live in the session scratchpad; they are throwaway by design.)

---

## 2. THE FINDING — wrong resplit cap → wrong house edge

`references/woo/blackjack.md` gives the target as
`Infinite deck, S17, DAS, split to 3 hands (aces once, one card), no surrender — 0.511734%`,
and its methodology note says *"published tables **cap resplits at three** (aces excluded)"*.

Three **resplits** = **four hands**. The builder read the summary phrase literally as
"three hands" and hard-wired `max_hands ∈ {2, 3}`. I solved the rule set from the number:

```
target WoO infinite-deck: 0.511734%
  max_hands=3 resplit_aces=False: 0.520766%      <- what the engine does
  max_hands=3 resplit_aces=True : 0.267463%
  max_hands=4 resplit_aces=False: 0.511734%      <== EXACT MATCH
  max_hands=4 resplit_aces=True : 0.248247%
  max_hands=5 resplit_aces=False: 0.509907%
```

To full precision my independent DP gives **0.5117336368%**, which rounds to the published
**0.511734%** — a six-significant-digit hit. No other variant is within 0.008 percentage
points. The rule set behind WoO's figure is unambiguously **split to 4 hands (3 resplits),
aces split once and one card each**.

The engine cannot even *express* it:

```python
>>> Blackjack(max_hands=4)
ValueError: max_hands must be 2 or 3
```

**Consequence:** the engine's house edge is 1.77% too high in relative terms
(0.520766% vs 0.511734%, +9.03e-05 absolute).

### The engine's math is NOT approximate — it is exactly right for the wrong rules

The module docstring and validator both claim the closed-form resplit model is a
"~9e-5 approximation of WoO's". That is false, and it matters because it misdirects the fix.
My structurally different recursion agrees with the engine to **every printed digit** on
eight rule variants:

```
  mh=2 h17=F das=T: engine 0.5703880%  mine 0.5703880%  diff +0.00e+00
  mh=2 h17=F das=F: engine 0.6902366%  mine 0.6902366%  diff +0.00e+00
  mh=2 h17=T das=T: engine 0.7892105%  mine 0.7892105%  diff +0.00e+00
  mh=2 h17=T das=F: engine 0.9113149%  mine 0.9113149%  diff +0.00e+00
  mh=3 h17=F das=T: engine 0.5207655%  mine 0.5207655%  diff +0.00e+00
  mh=3 h17=F das=F: engine 0.6583432%  mine 0.6583432%  diff +0.00e+00
  mh=3 h17=T das=T: engine 0.7400446%  mine 0.7400446%  diff +0.00e+00
  mh=3 h17=T das=F: engine 0.8802117%  mine 0.8802117%  diff +0.00e+00
```

Its closed form `3·pr·e0 + s_ne + (1−pr)·(2·pr·e0 + s_ne)` is precisely `g(2, 1)` of the
general recursion. It is exact — for a 3-hand cap. The defect is the cap, not the algebra.

---

## 3. THE FUDGE — tolerance sized to the bug

`scripts/validate_blackjack.py:76`

```python
ABS_ANALYTIC_TOL = 1.5e-4   # engine exact edge vs WoO 0.511734% (see doc)
```

Observed error 9.03e-5; tolerance 1.5e-4 — 1.66× the error. `tests/test_blackjack.py:114`
repeats it (`assert abs(game.house_edge - WOO_INFINITE_DECK_HOUSE_EDGE) < 1.5e-4`), with the
same "documented slight approximation" comment. Both gates are calibrated to pass the
defect rather than to detect it. For a quantity the reference publishes to **six decimal
places**, a 1.5e-4 gate is three orders of magnitude looser than the published precision.

`spinquest_sim/games/blackjack.py:25-27` also states 0.511734% is *"the analytic and
empirical target here"* — a target the module then misses by 1.8%.

### The empirical gate has no power to catch it either

| N | SE | bias / SE |
|---|---|---|
| 10M (validator's) | 3.643e-04 | **0.248** |
| 60M (mine) | 1.487e-04 | 0.607 |
| 1.46e9 | 3.01e-05 | 3.000 |

To separate 0.520766% from 0.511734% at 3 SE needs **≈1.46 billion rounds**. At 10M the
"empirical edge within 3 SE of WoO" check passes *identically* whether the engine is right
or wrong — it is a null test, not a gate. My own 60M run confirms it: **z = +0.32 vs WoO
and z = −0.28 vs the engine's own (different) analytic** — both comfortably inside 3 SE.

---

## 4. Everything that IS correct (verified independently)

- **Payouts vs `references/stake/blackjack.md` §4 — exact.** Standard win net +1 → 2.00
  returned; blackjack net +1.5 → 2.50 returned; insurance 2:1 → 3× stake. Confirmed at the
  round level: `play_round` returns `total_returned` 2.50 on a natural, 2.00 on a standard
  win, 0.00 on a dealer natural.
- **Insurance EV** = 2·(4/13) − 9/13 = **−1/13** exactly; basic strategy declines it.
- **CARDS index table** — rank-major `♦♥♠♣`, index 0 `♦2` … 51 `♣A`; `CARD_VALUES` derived
  from `index//4`; matches the published table entry for entry (16 tens, 4 aces).
- **RNG wiring is real, not faked.** My own HMAC-SHA256 stream + `floor(f·52)` reproduced
  the engine's **card index list** and net payout for **30,000/30,000 nonces**, on both the
  scalar and the vectorized path. `simulate` genuinely burns one nonce per round off
  `BulkRng.card_hands`.
- **Basic strategy is correct and genuinely derived.** All five tables match my independent
  DP in **0/510 cells disagreeing**, and reproduce the classic S17/DAS chart *including*
  both infinite-deck quirks WoO names: **soft 13 vs 5 → hit** and **soft 15 vs 4 → hit**
  (the 4-deck chart doubles both). The split chart is identical at `max_hands` 3 and 4, so
  the rule-set fix does not disturb it.
- **Analytic distribution & variance — exact.** My independent distribution calculator
  matches the engine bin for bin, worst diff **8.7e-19**; mass 1.0 to 1e-15;
  var 1.327260626, sd **1.152067978**.
- **Simulator faithfully realizes the analytic distribution.** χ² of my 60M-round histogram
  against my independent analytic distribution: **χ² = 13.33, df = 13, p = 0.42**.
  Empirical SD 1.15209651 vs analytic 1.15206798 (Δ = 2.9e-05).
- **Overflow / scalar-fallback path is honest.** Forcing `float_budget` to 6 and 8 (31,289
  and 3,093 fallbacks over 200k rounds) gives payouts **bit-identical** to `float_budget=24`
  (0 fallbacks). No infinite loop, no silent truncation. Max cards seen in 50k rounds: 17.
- **No hardcoded empirical results anywhere.** No blackjack constants leak into
  `harness.py` / `report.py` / `selector.py` / `mcp_server`.

---

## 5. Blind comparison (labels stripped)

Two unlabeled columns. One is the reference, one is ours.

| # | Quantity (infinite deck, S17, DAS, aces once/one card, no surrender, optimal play) | **A** | **B** |
|---|---|---|---|
| 1 | Player expected return | −0.511734% | −0.520766% |
| 2 | Return to player | 99.488266% | 99.479234% |
| 3 | House edge, 2 dp | 0.51% | 0.52% |
| 4 | Maximum hands after resplitting non-aces | 4 | 3 |
| 5 | Per-round SD (unit initial bet) | 1.1538 | 1.1521 |
| 6 | P(net outcome outside ±6 units) | 1.13e-05 | 0 |

**Could an expert tell?** Yes, instantly, on two independent tells:

1. **Cell 1.** The published constant is `0.511734%`. Column B does not match it at *any*
   rounding precision — not 6 dp, not 4 dp, not 2 dp (0.52% vs 0.51%). Anyone who has the
   WoO infinite-deck page open picks A in one second.
2. **Cell 4.** "Split to a maximum of 3 hands" is not a rule any real blackjack game or any
   WoO analysis uses; split-to-4 is the universal convention. B reads as a modelling
   shortcut, not a casino rule.

Cell 6 is a third, subtler tell: under the reference rules a round can net ±7 or ±8 (four
hands, some doubled) about once in 88,000 — the engine's payout lattice is hard-capped at
±6 and cannot represent those outcomes at all.

**The blind test does not favour ours. It does not even come out a coin flip.**

---

## 6. THE ONE CHANGE THAT CLOSES THE GAP

**Change the resplit cap from 3 hands to 4 hands (3 resplits), aces still split once.**
That single rule change moves the analytic edge from 0.520766% to **0.5117336368%** —
the published 0.511734% to six significant figures — and needs no change to the strategy
tables (verified identical) or the RNG. Concretely:

1. `Blackjack.__init__`: accept `max_hands=4`, make it the **default**.
2. Replace the hard-wired 3-hand closed form in `_build` (`ev_split`, `split_dist`) with the
   general pending-hand recursion `g(m, b)` / `gd(m, b)` — `m` pending single-card hands,
   `b` splits left, decision `max(split, play-out)` at each `c == r`. Initial call
   `g(2, max_hands − 2)`.
3. Generalize `play_round` and `_play_chunk` from the special-cased A-then-B branches to the
   same pending-queue model (I verified the queue model is behaviourally identical to the
   engine's current branches at 3 hands over 30k nonces, so this is a safe refactor).
4. **Widen the payout lattice** `_LATTICE`/`_NBINS` from ±6 (25 bins) to ±8 (33 bins),
   update `_lat_idx`'s bound, the `conv` slice `[12:37] → [16:49]`, and — importantly — the
   `+12` offset and `.clip(0, _NBINS-1)` in `simulate`'s histogram, which would otherwise
   **silently misbin** the ~113 out-of-range rounds per 10M into the ±6 bins.
5. Delete `ABS_ANALYTIC_TOL = 1.5e-4` and the matching test tolerance; assert
   `abs(house_edge − 0.00511734) < 5e-7` (achieved margin: 3.6e-09).
6. Correct the false "closed-form resplit model is a ~9e-5 approximation" claims in
   `blackjack.py`'s docstring, `validate_blackjack.py`'s docstring, and
   `test_blackjack.py:111`.

### Secondary items (do not block, but note)

- `simulate()`'s `se_rtp`/`z_score` use the **analytic** SD as the SE, so a wrong analytic
  silently propagates into the z-score. Prefer the empirical SD, or report both.
- `outcome_probabilities()["blackjack_win"]` reads bin `_lat_idx(bj_payout)`. Safe at 1.5
  (only naturals land on a half-integer), but with the constructor's permitted
  `bj_payout=2.0` that bin also collects ordinary doubled wins and the field becomes wrong.
- Insurance exists only as a static EV constant; there is no playable insurance path in
  `play_round`. Defensible (basic strategy declines) but it means the published 2:1 payout
  is never exercised end-to-end.

---

## 7. Numbers

```
Payouts:            all 3 published Stake rows reproduce exactly (2.00 / 2.50 / 3×)
Worst payout diff:  0
Worst analytic-probability diff (my dist vs engine, 25 bins):  8.7e-19
Analytic house edge — engine 0.5207655180%  |  reference 0.511734%  |  DIFF +9.03e-05  ✗
Analytic SD         — engine 1.152067978    |  reference ~1.15                          ✓
Correct-rules value — 0.5117336368% (my independent DP; rounds to published 0.511734%)

My 60M-round run (engine public API, seed c0ffee11…, client critic-independent-run-r1):
  rounds        60,000,000        runtime 330.5 s   (181,558 rounds/s)   overflow 0
  mean net      -0.005165617      empirical edge 0.5165617%
  empirical SD  1.152096506       SE = SD/sqrt(N) = 1.4874e-04
  edge vs WoO 0.511734%    : 0.5165617% ± 3SE = [0.4719%, 0.5612%]  → z = +0.32  PASS
  edge vs engine 0.520766% : z = −0.28  PASS   (both pass — the test cannot discriminate)
  histogram vs my analytic dist: chi2 = 13.33, df = 13, p = 0.42

Builder's own validator: 14/14 pass, 10M rounds, 58.5 s — but check [2] passes only
because ABS_ANALYTIC_TOL was set to 1.5e-4 and check [3] has 0.25-SE resolving power.
```
