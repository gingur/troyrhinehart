# Blackjack — Gauntlet Round 2 (independent critic, fresh eyes)

**Verdict: FAIL — and nothing was remediated since Round 1.**

The engine implements the **wrong resplit cap** (split to 3 hands instead of 4), so its
exact analytic house edge is **0.5207655%** where the reference ground truth is
**0.511734%**. I re-derived this from scratch — my own DP, my own HMAC stream, my own
30M-round campaign, my own SE — without reading Round 1's conclusion into my code. I land
on the same defect, and I can now show it is **empirically detectable at 10M rounds**,
which Round 1 concluded it was not.

### Round 2 has no build to review

| File | mtime |
|---|---|
| `spinquest_sim/games/blackjack.py` | 2026-08-24 **02:39:53** |
| `tests/test_blackjack.py` | 2026-08-24 03:09:52 |
| `scripts/validate_blackjack.py` | 2026-08-24 03:11:33 |
| `gauntlet/blackjack/round1.md` | 2026-08-24 **04:27:11** |

Every blackjack source file predates the Round 1 report. `Blackjack(max_hands=4)` still
raises `ValueError`. `ABS_ANALYTIC_TOL` is still `1.5e-4`. The six-step fix Round 1 spelled
out was not started. This round is therefore a re-audit, and its value is the **new
evidence** in §4 and §5.

---

## 1. What I did (nothing trusted — not the builder's, not Round 1's)

| Artifact | Purpose |
|---|---|
| `indep2.py` | From-scratch infinite-deck DP: my own dealer recursion, hit/stand/double DP, **general pending-hand split recursion** `g(m,b)` with a genuine `max(split, play-out)` decision, and a separate payout-**distribution** recursion `gd(m,b)` on a **41-bin ±10** lattice (deliberately wider than the engine's ±6, so out-of-range mass has somewhere to land) |
| `cmp2.py` | Engine vs my DP across 8 rule variants; bin-by-bin distribution diff |
| `strat2.py` | My DP's five strategy tables vs the engine's, cell by cell (660 cells) |
| `replay2.py` | My own `byteGenerator` + `generateFloats` + `floor(f*52)` + my own round player, replayed against `play_round` **and** `simulate`; `float_budget` sweep; end-to-end paytable exercise |
| `bigsim2.py` | **30,000,000 rounds** through the engine's public API, fresh seeds, my own SE, χ² against both candidate laws, and the `|net|>6` counter |
| 1M `play_round` calls | Measured hands-per-round distribution |

Scratch scripts are throwaway by design (session scratchpad).

---

## 2. THE FINDING — resplit cap 3 vs 4 (confirmed independently)

`references/woo/blackjack.md:19` states the target rule set as *"Infinite deck, S17, DAS,
split to 3 hands (aces once, one card), no surrender — 0.511734%"*, while its own
methodology note at line 60 says *"published tables **cap resplits at three** (aces
excluded)"*. Three **resplits** = **four hands**. The two lines contradict each other; the
number settles it.

I solved the rule set numerically over all 16 combinations of
(`max_hands` ∈ {3,4}) × (peek) × (S17/H17) × (DAS/no-DAS):

```
  M=3 peek=True  h17=False das=True   edge=0.5207655%     <- what the engine does
  M=3 peek=False h17=False das=True   edge=-0.0726519%
  M=4 peek=True  h17=False das=True   edge=0.5117336%     <== UNIQUE MATCH
  M=4 peek=False h17=False das=True   edge=-0.0813516%
  M=4 peek=True  h17=True  das=True   edge=0.7310958%
  M=4 peek=True  h17=False das=False  edge=0.6525383%
  (all 16 printed in the run log; only one matches)
```

and swept the cap further:

```
  max_hands=2  0.5703880%   diff +5.865e-04
  max_hands=3  0.5207655%   diff +9.032e-05   <- engine
  max_hands=4  0.5117336%   diff -3.632e-09   <== 0.511734% to 7 s.f.
  max_hands=5  0.5099072%   diff -1.827e-05
  max_hands=6  0.5095133%   diff -2.221e-05
  max_hands=8  0.5094039%   diff -2.330e-05
```

`max_hands=4` with dealer **peek**, **S17**, **DAS**, aces split once/one card is the
**only** rule set within 1.8e-5 of the published figure, and it reproduces it to
**3.6e-09**. Resplit-aces variants are 0.24–0.37% (off by 2.4e-3) and no-peek variants are
negative-edge — both excluded by orders of magnitude. The identification is unambiguous.

The engine cannot express it:

```python
>>> Blackjack(max_hands=4)
ValueError: max_hands must be 2 or 3
```

### The engine's algebra is exactly right for the wrong rules

My structurally different recursion (queue-based, with a real `max()` at every resplit
node) agrees with the engine to **every printed digit** on all eight variants it can
express, and its payout distribution matches the engine's **bin for bin to 8.7e-19**:

```
  M=2 h17=F das=T: engine 0.5703880%  mine 0.5703880%  diff +0.00e+00
  M=2 h17=F das=F: engine 0.6902366%  mine 0.6902366%  diff +0.00e+00
  M=2 h17=T das=T: engine 0.7892105%  mine 0.7892105%  diff +0.00e+00
  M=2 h17=T das=F: engine 0.9113149%  mine 0.9113149%  diff +0.00e+00
  M=3 h17=F das=T: engine 0.5207655%  mine 0.5207655%  diff +0.00e+00
  M=3 h17=F das=F: engine 0.6583432%  mine 0.6583432%  diff +0.00e+00
  M=3 h17=T das=T: engine 0.7400446%  mine 0.7400446%  diff +0.00e+00
  M=3 h17=T das=F: engine 0.8802117%  mine 0.8802117%  diff +0.00e+00

  worst |engine − mine| over 41 distribution bins: 8.674e-19
```

I also confirmed the greedy-vs-optimal resplit question is a non-issue: forcing
always-resplit gives an identical 0.5117336% at M=4, so the engine's greedy closed form is
not the problem. **The defect is the cap, not the algebra** — and the module docstring's
claim that this is a *"closed-form approximation"* is false, which matters because it
points the fix in the wrong direction.

---

## 3. THE FUDGES

### 3a. Tolerance sized to the bug — unchanged

`scripts/validate_blackjack.py:76`

```python
ABS_ANALYTIC_TOL = 1.5e-4   # engine exact edge vs WoO 0.511734% (see doc)
```

Observed error **9.03e-5**; tolerance **1.5e-4** — 1.66× the error. The reference figure is
correctly *parsed* from the markdown (`woo_infinite_deck_edge: 0.00511734`, honest — no
hardcoding), then compared at a tolerance **three orders of magnitude looser than the six
decimal places the reference publishes**. The validator's own PASS line prints the
mismatch:

```
ok    exact house edge vs WoO infinite deck 0.511734%: engine 0.520766%
      (diff +9.03e-05 < 1.5e-04; closed-form resplit model)
```

### 3b. NEW — the test suite doesn't merely tolerate the bug, it *locks it in*

`tests/test_blackjack.py:242`

```python
with pytest.raises(ValueError):
    Blackjack(max_hands=4)
```

The correct rule set is asserted to be **rejected**. `tests/test_blackjack.py:152` asserts
`cfg["max_hands"] == 3`. So the wrong cap is now a regression-protected contract: applying
the fix will *break* two green tests. Round 1 called the tolerance a fudge; this is worse —
it is the defect promoted to a specification. All **20/20** tests pass, including these.

### 3c. NEW — the "empirical SD vs WoO ~1.15" gate is self-referential

`validate_blackjack.py:336` names the check `f"empirical SD vs analytic {…:.4f} (WoO ~1.15)"`
but compares `res["std_per_unit"]` against **the engine's own analytic SD**, at
`SD_EMPIRICAL_TOL = 0.01`. It is an engine-vs-itself consistency check wearing a
reference-check label; it cannot fail because of a wrong rule set. (The genuine
reference-facing gate, `|SD − 1.15| < 0.02`, is satisfied by both 1.1521 and the correct
1.1538 — see §5 cell 8.)

### 3d. Clean — no hardcoded empirical results

I grepped for `0.005207`, `0.5207`, `1.15206`, `0.520766`, `0.99479` across the package: no
leakage into `harness.py`, `report.py`, `selector.py`, or `mcp_server/`. Reference constants
are parsed from the markdown at run time. The simulator genuinely burns one nonce per round
off `BulkRng.card_hands` — no shortcut.

---

## 4. NEW: the empirical gate is a null test — but a same-cost test rejects at 18σ

Round 1 concluded the bias needed ≈1.46 **billion** rounds to detect and left it there.
That is true **only of the mean**. The two laws differ far more sharply in their *shape*,
and that difference is free.

My own 30M-round campaign (engine public API, fresh seed `9d4c2ab7e…`, client
`critic-round2-independent-30M`, my own SE from the **empirical** SD):

```
rounds        30,000,000     runtime 189.6 s  (158,262 rounds/s)   overflow 0
empirical mean -0.004896867  edge 0.489687%
empirical SD   1.151986605   SE = SD/sqrt(N) = 2.103230e-04
3-SE band on edge: [0.426590%, 0.552784%]

  vs WoO published 0.511734%   z = -1.048   PASS
  vs engine analytic 0.520766% z = -1.478   PASS     <- both pass: no discriminating power
```

The mean gate passes against **both** hypotheses, exactly as Round 1 said. But at the same
30M rounds:

```
=== rounds with |net| > 6 units ===
  reference rule set  P(|net|>6) = 1.127818e-05  -> expected 338.3 in 30,000,000
  engine              P(|net|>6) = 0   (lattice hard-capped at +-6)
  OBSERVED            0
  P(observe 0 | reference rules) = exp(-338.3) ~ 1e-147     -> ~18 sigma rejection

=== chi-square, my 30M histogram vs my independent analytic laws ===
  vs engine's law (M=3):     chi2 =    9.78  df=13  p = 0.712    <- simulator is faithful
  vs reference law (M=4):    chi2 = 2585     df=17  p = 0.000    <- law REJECTED
```

Under the reference rules a round can net ±7 or ±8 (four hands, some doubled) once in
88,667. The engine's payout lattice `_LATTICE = arange(-12,13)/2` **cannot represent those
outcomes at all**, and `simulate`'s histogram would silently `.clip()` them into the ±6 bins
if they ever arose. At 10M rounds the reference predicts ~113 such rounds; the engine
produces 0. **This is a decisive empirical test that fits inside the stated 10M-round
budget** — the bar as written just doesn't ask for it.

A second, even stronger discriminator, measured through `play_round` over 1M rounds:

```
measured hands-per-round (engine, 1,000,000 rounds):
   1 hand : 974,481   2 hands: 22,590   3 hands: 2,929   4 hands: 0
reference analytic:            22,850            2,445           544
   3-hand count z vs reference: +9.8    (at only 1M rounds)
   4-hand count: 0 observed vs 544 expected -> structurally impossible in the engine
```

The engine over-produces 3-hand rounds by 20% relative, because the mass that should flow
to a fourth hand piles up at the cap. That is a **+9.8σ** tell at one-thirtieth of the
required sample size.

---

## 5. Blind comparison (labels stripped)

Two unlabeled columns. One is the reference, one is ours.

| # | Quantity (infinite deck, S17, DAS, aces once/one card, no surrender, peek, optimal play) | **A** | **B** |
|---|---|---|---|
| 1 | Player expected return | −0.511734% | −0.520766% |
| 2 | Return to player | 99.488266% | 99.479234% |
| 3 | House edge, 2 dp | 0.51% | 0.52% |
| 4 | Max hands after resplitting non-aces | 4 | 3 |
| 5 | P(round is played as 4 hands) | 5.439e-04 | 0 |
| 6 | P(round is played as 3 hands) | 2.445e-03 | 2.929e-03 |
| 7 | P(net outcome outside ±6 units) | 1.128e-05 | 0 |
| 8 | Per-round SD (unit initial bet) | 1.153752 | 1.152068 |
| 9 | Standard win / blackjack / insurance, total returned per unit | 2.00 / 2.50 / 3.00 | 2.00 / 2.50 / 3.00 |
| 10 | CARDS index 0 / 51 | ♦2 / ♣A | ♦2 / ♣A |
| 11 | Basic strategy: soft 13 v 5, soft 15 v 4 | hit, hit | hit, hit |
| 12 | Strategy cells disagreeing with an independent optimal-play DP | — | 0 / 660 |

**Could an expert tell? Yes — immediately, on five independent tells.**

1. **Cell 1** is decisive on its own. The published constant is `0.511734%`. Column B misses
   it at *every* rounding precision — not 6 dp, not 4 dp, not even 2 dp (0.52% vs 0.51%).
   Anyone with the WoO infinite-deck page open picks A in one second.
2. **Cell 4.** "Split to a maximum of 3 hands" is not a rule any real blackjack game or any
   WoO analysis uses; split-to-4 is the universal convention. B reads as a modelling
   shortcut, not a casino rule.
3. **Cells 5 and 7** are *structural zeros*. A real blackjack game produces four-hand rounds
   and ±7/±8 net results. A column in which those probabilities are exactly 0 is not a
   noisy imitation — it is a different game, and it is the imitation by construction.
4. **Cell 6** is a 20%-relative discrepancy in a directly observable frequency, measurable
   at +9.8σ from 1M rounds.

**Correction to Round 1:** Round 1 listed the SD (cell 8) as a tell. It is **not** one at
published precision — the reference publishes only "~1.15" (and 1.142 for a different rule
set), and 1.153752 and 1.152068 both round to 1.15. Cells 9–12 are genuine coin flips:
the Stake paytable, the 52-entry CARDS index, and the entire basic-strategy chart are
indistinguishable from the reference. **The tell is confined entirely to the resplit cap and
its consequences** — which is exactly why one change fixes it.

**The blind test does not favour ours. It is not a coin flip.**

---

## 6. Everything that IS correct (re-verified with my own code, not the builder's)

- **Payouts vs `references/stake/blackjack.md` §4 — exact, and exercised end-to-end.** I hunted
  live rounds off my own HMAC stream: standard win → `total_returned 2.00`; natural →
  `2.50`; dealer natural → `0.00`; insurance EV `−0.076923076923` = exactly `−1/13`
  (`2·4/13 − 9/13`), i.e. the published 2:1 → 3× stake. **Worst payout diff: 0.**
- **RNG wiring is real.** My own `byteGenerator` / `generateFloats` / `floor(f·52)` +
  my own round player reproduced the engine's **card index list and net payout for
  40,000/40,000 nonces**, on the scalar path *and* against `simulate()`'s vectorized
  output. `simulate` consumes nonces 1…40001 — one per round.
- **Scalar-fallback path is honest.** `float_budget` ∈ {6,7,9,14,24,40} → overflow counts
  {3139, 914, 120, 3, 0, 0} over 20k rounds, payouts **bit-identical across all six**. No
  infinite loop, no silent truncation.
- **Basic strategy is derived and optimal.** My independent DP disagrees with the engine's
  five tables in **0 of 660 cells**, and the chart is textbook S17/DAS *including* both
  infinite-deck quirks WoO names (soft 13 v 5 → hit, soft 15 v 4 → hit, where the 4-deck
  chart doubles). Crucially, the **SPLIT table is bit-identical at M=3 and M=4**, so the
  rule fix requires **no strategy change**.
- **Analytic distribution and variance are exact** for the rules implemented (mass 1.0,
  distribution mean == EV DP to 1e-15, worst bin diff 8.7e-19 vs my independent calculator).
- **Simulator faithfully realizes its own analytic law** (χ² = 9.78, df 13, p = 0.71 at 30M;
  empirical SD 1.151987 vs analytic 1.152068, Δ = 8.1e-05).
- **No hardcoded empirical results.** Reference figures are parsed from the markdown.
- Builder's own gates: `validate_blackjack.py` **14/14 pass** (10M rounds, 54.8 s);
  `pytest tests/test_blackjack.py` **20/20 pass**. Both pass *because* of §3, not despite it.

---

## 7. THE ONE CHANGE THAT CLOSES THE GAP

**Change the resplit cap from 3 hands to 4 hands (3 resplits), aces still split once.**
Analytic edge moves 0.5207655% → **0.5117336368%**, the published 0.511734% to seven
significant figures (residual 3.6e-09), with **no change to the strategy tables** and none
to the RNG. Concretely, unchanged from Round 1 because none of it was done:

1. `Blackjack.__init__`: accept `max_hands=4` and make it the **default**.
2. Replace the hard-wired 3-hand closed form in `_build` (`ev_split`, `split_dist`) with the
   general pending-hand recursion `g(m,b)` / `gd(m,b)`: `m` pending one-card hands, `b`
   splits left, decision `max(split, play-out)` at each `c == r`; initial call
   `g(2, max_hands − 2)`. (I verified both my `g` and `gd` reproduce the engine exactly at
   `max_hands=3`, so this is a safe generalization, and greedy-vs-optimal is immaterial.)
3. Generalize `play_round` and `_play_chunk` from the special-cased A-then-B branches to the
   same pending-queue model — widen `ft`/`wg` from 3 columns to 4.
4. **Widen the payout lattice** `_LATTICE`/`_NBINS` from ±6 (25 bins) to ±8 (33 bins), update
   `_lat_idx`'s bound, the `conv` slice `[12:37] → [16:49]`, and the `+12` offset and
   `.clip(0, _NBINS-1)` in `simulate`'s histogram — which would otherwise **silently misbin**
   the ~113 out-of-range rounds per 10M into the ±6 bins.
5. Delete `ABS_ANALYTIC_TOL = 1.5e-4` and the matching test tolerance; assert
   `abs(house_edge − 0.00511734) < 5e-7` (achieved margin 3.6e-09). **Delete the
   `pytest.raises(ValueError): Blackjack(max_hands=4)` assertion and flip
   `cfg["max_hands"] == 3` to `== 4`** — these two now enforce the defect.
6. Correct the false *"closed-form resplit model is a ~9e-5 approximation"* claims in
   `blackjack.py`'s docstring, `validate_blackjack.py`'s docstring, and
   `test_blackjack.py:111`.
7. **Add the tests that actually have power** (this round's new contribution): assert
   `P(|net| > 6) > 0` analytically, and add an empirical gate on the 4-hand-round frequency
   and the `|net| > 6` count. Both reject the wrong cap at >9σ within the existing
   10M-round budget, where the mean-based 3-SE gate needs 1.46e9.

### Secondary items (do not block)

- `simulate()`'s `se_rtp`/`z_score` use the **analytic** SD as the SE, so a wrong analytic
  silently propagates into the z-score. Prefer the empirical SD, or report both.
- `outcome_probabilities()["blackjack_win"]` reads bin `_lat_idx(self.bj_payout)`. Safe at
  1.5, but with the constructor's permitted `bj_payout=2.0` that bin also collects ordinary
  doubled wins and the field becomes silently wrong.
- Insurance exists only as a static EV constant; there is no playable insurance path in
  `play_round`. Defensible (basic strategy declines it) but the published 2:1 payout is
  never exercised end-to-end as an actual settlement.
- `validate_blackjack.py`'s "empirical SD vs WoO ~1.15" gate compares against the engine's
  own analytic SD (§3c). Point it at 1.15 from the reference file, or rename it.

---

## 8. Numbers

```
Payouts:              all 3 published Stake rows reproduce exactly (2.00 / 2.50 / 3x)
Worst payout diff:    0
Insurance EV:         -0.076923076923 = -1/13 exactly
CARDS index table:    52/52 entries match; 16 tens, 4 aces
Strategy:             0/660 cells disagree with my independent optimal-play DP
Worst analytic-prob diff (my dist vs engine, 41 bins):   8.674e-19

Analytic house edge - engine    0.5207655180%
                    - reference 0.511734%          DIFF +9.03e-05   *** FAIL ***
                    - correct rules (my DP, M=4) 0.5117336368%  (residual -3.6e-09)
Analytic SD         - engine 1.152067978 | reference(M=4) 1.153751629 | WoO ~1.15   PASS

My 30M-round run (engine public API, seed 9d4c2ab7e..., client critic-round2-independent-30M):
  rounds        30,000,000     runtime 189.6 s  (158,262 rounds/s)   overflow 0
  mean net      -0.004896867   empirical edge 0.489687%
  empirical SD  1.151986605    SE = SD/sqrt(N) = 2.1032e-04
  edge vs WoO 0.511734%    : 0.489687% +- 3SE = [0.4266%, 0.5528%]  z = -1.048  PASS
  edge vs engine 0.520766% : z = -1.478  PASS   (both pass - the mean gate cannot discriminate)
  histogram chi2 vs engine's own law (M=3):     9.78  df=13  p=0.712   PASS
  histogram chi2 vs the REFERENCE law (M=4): 2585      df=17  p=0.000   *** FAIL ***
  rounds with |net|>6: observed 0, reference expects 338.3 -> ~18 sigma rejection

Hands-per-round, 1M play_round calls: 4-hand rounds 0 vs reference 544 (impossible);
  3-hand rounds 2,929 vs reference 2,445  -> z = +9.8 at 1M rounds

Independent replay:   40,000/40,000 nonces exact (cards AND net), scalar + vectorized
float_budget sweep:   6/7/9/14/24/40 -> bit-identical payouts, overflow 3139/914/120/3/0/0
Builder's validator:  14/14 pass, 10M rounds, 54.8 s  (check [2] passes only because
                      ABS_ANALYTIC_TOL = 1.5e-4; check [3] has ~0.25-SE resolving power)
Builder's tests:      20/20 pass, including one that asserts max_hands=4 is REJECTED
```
