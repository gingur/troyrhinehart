# Blackjack — Gauntlet Round 4 (independent critic, fresh eyes)

**Verdict: PASS.** The Round-1/Round-2 defect (resplit cap of 3 hands) is fixed, and the
fix is real, not cosmetic. I rebuilt the entire analysis from scratch — my own infinite-deck
DP, my own payout-distribution recursion, my own HMAC-SHA256 byte stream, my own round
player, my own 60,000,000-round campaign, my own SE — and the engine reproduces the
Wizard of Odds infinite-deck figure to **3.6e-09** and my independent payout law
**bit-for-bit in all 18 support bins to 18 significant digits**. The blind comparison is a
coin flip on every quantity either reference publishes.

Residual findings are two documentation/API defects (§6) that do not touch the reference
path.

---

## 1. What I did (nothing trusted — not the builder's code, not Rounds 1–3)

| Artifact | Purpose |
|---|---|
| `indep4.py` | From-scratch infinite-deck analytics. Deliberately different formulation: **explicit acyclic value-iteration** over (total, soft) states with a written dependency proof (hard 21→12, then soft 21→12, then hard 11→4) instead of the engine's recursive memo; peek/no-peek switch; **greedy-vs-optimal resplit switch**; payout distribution on a **49-bin ±12** lattice, deliberately wider than the engine's ±8 so any out-of-range mass has somewhere to land |
| `cmp4.py` | Engine vs my DP on 12 rule variants: EV, every distribution bin, SD, and all 660 strategy cells |
| `chart4.py` | Engine chart vs the **textbook 4–8 deck S17/DAS chart I wrote by hand** — an external check the previous rounds never ran |
| `replay4.py` | My own `byteGenerator` / `generateFloats` / `floor(f·52)` + my own round player, replayed against `play_round` **and** `simulate`; `float_budget` sweep; payout contract exercised per round |
| `edge4.py` | Edge cases: `bj_payout` ∈ {0.5, 1.0, 1.5, 2.0}, `max_hands` ∈ {2,3,4}, all-bust rounds, 4-hand rounds, double-after-split, split aces, my own analytic **hands-per-round** recursion vs measurement, constant-leakage grep |
| `bigsim4.py` | **60,000,000 rounds** through the engine's public API on a fresh secret seed, my own SE from the **empirical** SD, χ² vs **my** analytic law, my own tail counts |

Scratch scripts are throwaway by design (session scratchpad).

---

## 2. The Round-1/2 defect is genuinely fixed

Round 1 and Round 2 both failed the engine for `max_hands=3` (edge 0.5207655% vs the
published 0.511734%), and Round 2 additionally found the wrong cap **locked in** by
`pytest.raises(ValueError): Blackjack(max_hands=4)` and `cfg["max_hands"] == 3`.

Current state, verified by me:

```
Blackjack().config()["max_hands"]            -> 4
Blackjack().house_edge                       -> 0.511733636839 %
references/woo/blackjack.md published        -> 0.511734 %          residual -3.63e-09
tests: max_hands=4 is the default and asserted; ValueError now raised for max_hands=5
validate_blackjack.py: ANALYTIC_EDGE_TOL = 5e-7  (was 1.5e-4, sized to the bug)
```

I re-derived the rule set independently rather than taking anyone's word. Sweeping
48 combinations of (`max_hands` ∈ {2,3,4,5,6,8}) × (S17/H17) × (DAS/no-DAS) × (peek/no-peek)
through **my** DP:

```
  |d|=3.632e-09  M=4 h17=F das=T peek=T  edge=0.5117336%   <== UNIQUE MATCH
  |d|=1.827e-05  M=5 h17=F das=T peek=T  edge=0.5099072%
  |d|=2.221e-05  M=6 h17=F das=T peek=T  edge=0.5095133%
  |d|=9.032e-05  M=3 h17=F das=T peek=T  edge=0.5207655%   (what Rounds 1-2 rejected)
  |d|=5.865e-04  M=2 h17=F das=T peek=T  edge=0.5703880%
```

`max_hands=4` (3 resplits), aces once/one card, S17, DAS, dealer peek is the only rule set
within 1.8e-05 of the published number, and it reproduces it to seven significant figures.
The reference file's two lines ("split to 3 hands" in the table vs "cap resplits at three"
in the methodology note) contradict each other; the number settles it, and the engine now
implements the right one.

I also checked the modelling assumption the fix rests on: the engine's split recursion
**always** resplits when a pair reappears and budget remains, rather than taking
`max(split, play-out)`. I ran both policies over 12 rule variants:

```
  M=3/4/5 x S17/H17 x DAS/no-DAS:  greedy == optimal, diff 0.00e+00 in every case
```

So the greedy resplit is not an approximation here — it is the optimal policy. No fudge.

---

## 3. Engine vs my independent analytics — exact everywhere

**Expected value, 12 rule variants, zero difference:**

```
  M=2 h17=0 das=0: engine 0.6902366391%  mine 0.6902366391%  dEV 0  dBin 0  dSD 0
  M=2 h17=0 das=1: engine 0.5703880123%  mine 0.5703880123%  dEV 0  dBin 0  dSD 0
  M=2 h17=1 das=0: engine 0.9113148716%  mine 0.9113148716%  dEV 0  dBin 0  dSD 0
  M=2 h17=1 das=1: engine 0.7892105050%  mine 0.7892105050%  dEV 0  dBin 0  dSD 0
  M=3 h17=0 das=0: engine 0.6583432317%  mine 0.6583432317%  dEV 0  dBin 0  dSD 0
  M=3 h17=0 das=1: engine 0.5207655180%  mine 0.5207655180%  dEV 0  dBin 0  dSD 0
  M=3 h17=1 das=0: engine 0.8802116992%  mine 0.8802116992%  dEV 0  dBin 0  dSD 0
  M=3 h17=1 das=1: engine 0.7400445566%  mine 0.7400445566%  dEV 0  dBin 0  dSD 2e-16
  M=4 h17=0 das=0: engine 0.6525382541%  mine 0.6525382541%  dEV 0  dBin 0  dSD 0
  M=4 h17=0 das=1: engine 0.5117336368%  mine 0.5117336368%  dEV 0  dBin 0  dSD 0   <- reference
  M=4 h17=1 das=0: engine 0.8745505538%  mine 0.8745505538%  dEV 0  dBin 0  dSD 0
  M=4 h17=1 das=1: engine 0.7310957721%  mine 0.7310957721%  dEV 0  dBin 0  dSD 0
```

**Payout distribution — every bin identical to 18 significant digits** (my ±12 lattice vs
the engine's ±8; my lattice puts zero mass outside ±8, so the engine's width is exactly
right, not a truncation):

```
 net    engine                 independent            diff
 -8.0   0.000000235278373544   0.000000235278373544   0.0e+00
 -7.0   0.000002938567390839   0.000002938567390839   0.0e+00
 -6.0   0.000021626778713500   0.000021626778713500   0.0e+00
 -5.0   0.000104708131392708   0.000104708131392708   0.0e+00
 -4.0   0.000521394954841032   0.000521394954841032   0.0e+00
 -3.0   0.002109921557287097   0.002109921557287097   0.0e+00
 -2.0   0.041586089752454460   0.041586089752454460   0.0e+00
 -1.0   0.434313721237187589   0.434313721237187589   0.0e+00
 +0.0   0.088305918924648064   0.088305918924648064   0.0e+00
 +1.0   0.326744400047543182   0.326744400047543182   0.0e+00
 +1.5   0.045096460207975919   0.045096460207975919   0.0e+00
 +2.0   0.057767236480117938   0.057767236480117938   0.0e+00
 +3.0   0.002442301438704952   0.002442301438704952   0.0e+00
 +4.0   0.000766921316349800   0.000766921316349800   0.0e+00
 +5.0   0.000164124365755601   0.000164124365755601   0.0e+00
 +6.0   0.000043896628976077   0.000043896628976077   0.0e+00
 +7.0   0.000007326769294728   0.000007326769294728   0.0e+00
 +8.0   0.000000777562993346   0.000000777562993346   0.0e+00
```

Variance 1.331142820305, SD **1.153751628517**, mass 1.0, distribution mean == EV DP to
3.1e-17.

**A second, independent corroboration of the variance** (a route neither previous round
used). The WoO variance appendix publishes a 6-deck benchmark variance of **1.295**
(S17, no DAS, no surrender, no resplit aces) and a published DAS rule effect of
**+0.03753**. 1.295 + 0.03753 = **1.33253**; the engine's infinite-deck S17/DAS/split-to-4
variance is **1.331143** — a 0.1% gap, entirely accounted for by infinite-deck vs 6-deck and
the resplit cap. The SD is right for reasons independent of my DP.

**Strategy — 0/660 cells disagree with my DP, and exactly the 2 deviations WoO names.**
This is the check the earlier rounds did not do: I hand-wrote the textbook 4–8 deck
S17/DAS chart and diffed the engine against it.

```
deviations from the textbook 4-8 deck S17/DAS chart:
   soft 15 vs upcard 4 : engine H, 4-deck book D
   soft 13 vs upcard 5 : engine H, 4-deck book D
total deviations: 2   (WoO methodology: "Strategy differs from 4-deck play only in
                       hitting soft 13 vs 5 and soft 15 vs 4")
```

Exactly two, exactly the two named, nothing else. Hard 11 vs A is a hit (correct for S17);
A7 doubles vs 3–6 and hits vs 9/10/A; 4,4 splits only vs 5–6; 6,6 splits vs 2–6; 2,2 and 3,3
split vs 2–7 — all textbook DAS.

---

## 4. The simulator is real, and it is the engine

- **My own HMAC-SHA256 stream** (`hmac.new(server, f"{client}:{nonce}:{round}")`, 4-byte
  floats `Σ bᵢ/256^(i+1)`, `floor(f·52)`) plus **my own round player** reproduced the
  engine's **card index list, card names, and net payout for 40,000/40,000 nonces** on the
  scalar path, and `simulate()`'s vectorized output for the same 40,000 rounds with
  **max |diff| = 0.0**. `simulate` consumes nonces 1…40001 — exactly one per round, off
  `BulkRng.card_hands`.
- **Overflow fallback is exact.** `float_budget` ∈ {6, 7, 9, 14, 24, 40} → overflow counts
  {3073, 913, 127, 4, 0, 0} over 20,000 rounds, payouts **bit-identical across all six**.
  No infinite loop (every clamped redraw strictly increases the hand total, so the play
  loop terminates), no silent truncation.
- **Reproducible and worker-invariant**: same seed → identical payout vector, and
  `workers=1` matches the parallel digest path.
- **`hand_value`**: 0 mismatches vs an independent implementation over 200,000 random hands.
- **No hardcoded empirical results.** Grepping `0.51173`, `1.15375`, `0.99488`, `1.1538`,
  `0.0049`, `0.492060` across `spinquest_sim/` and `mcp_server/` returns only the docstring
  citation of the published WoO figure — no leakage into `harness.py`, `report.py`,
  `selector.py`, or the MCP server. The validator **parses** both reference figures out of
  the markdown at run time.
- **Hands-per-round matches my own analytic recursion** (a structural check, not a mean
  check) over 300,000 `play_round` calls:

```
    1 hand : obs 292127  exp 292248.2  z=-0.22
    2 hands: obs   6985  exp   6855.3  z=+1.57
    3 hands: obs    722  exp    733.4  z=-0.42
    4 hands: obs    166  exp    163.2  z=+0.22
```

Round 2's decisive tell (3-hand rounds over-produced at +9.8σ, 4-hand rounds structurally
zero) is gone: the 4-hand mass is present and at the right frequency.

---

## 5. My own 60,000,000-round campaign

Fresh secret server seed `865908218c98…`, client `critic-round4-independent`, engine public
API, **my own SE computed from the empirical SD** (not the engine's `se_rtp`, which uses the
analytic SD):

```
rounds        60,000,000     runtime 330.1 s (181,772/s)   overflow 0
mean net      -0.004981008   empirical edge 0.4981008%
empirical SD  1.153827584    my analytic SD 1.153751629    SE = SD/sqrt(N) = 1.489585e-04
3-SE band on edge: [0.453413%, 0.542788%]

  edge vs WoO published 0.511734%   z = -0.915   PASS
  edge vs my independent DP         z = -0.915   PASS
  edge vs engine analytic           z = -0.915   PASS

  SD: empirical 1.153828 vs analytic 1.153752, SE(s) 7.49e-05, z = +1.01
      |SD - WoO's published ~1.15| = 0.0038

  chi2 of the 60M histogram vs MY analytic law: 21.26, df = 17, p = 0.215
      (all 18 support bins used, zero dropped mass)
  |net| > 6 : observed 690, expected 676.7, z = +0.51
  |net| > 7 : observed  59, expected  60.8, z = -0.23
  worst single-bin z over 18 bins: +2.05 (net +5.0)
```

The tails that Round 2 used to reject the old engine at ~18σ are now populated at exactly
the right rate. The builder's own `scripts/validate_blackjack.py`, which I ran myself,
passes **17/17** at 10M rounds (edge 0.492060%, z +0.54; |net|>6 observed 128 vs expected
112.8, z +1.43; 53.2 s). `pytest tests/test_blackjack.py`: **28 passed**.

---

## 6. What I still found wrong

### 6a. `outcome_probabilities()["blackjack_win"]` is silently wrong at `bj_payout=2.0`

Flagged as a secondary item in Rounds 1 **and** 2; still unfixed. The field reads the single
lattice bin `_lat_idx(self.bj_payout)`. At the Stake rule (1.5) only naturals land there, so
the default is correct — but the constructor explicitly permits `bj_payout` up to 2.0, and at
2.0 the bin also collects every ordinary **doubled** win:

```
  bj_payout=0.5  reported 0.045096460  true 0.045096460  OK
  bj_payout=1.0  reported nan          (documented)      OK
  bj_payout=1.5  reported 0.045096460  true 0.045096460  OK
  bj_payout=2.0  reported 0.102863697  true 0.045096460  *** WRONG (2.28x) ***
```

Fix: compute it as `p_player_bj · Σ_u P(u)·(1 − p_dealer_bj(u))` (a quantity `_build`
already has) instead of reading a payout bin, or reject `bj_payout == 2.0`.
Off the reference path, so not a fidelity failure — but it is a two-round-old known bug in
a public API.

### 6b. The explanation of Stake's published 0.57% is unsupported and probably wrong

`blackjack.py:29`, `validate_blackjack.py:13` and the validator's info line all assert that
Stake's headline "Edge: 0.57%" *"matches WoO's classic 6-deck S17 benchmark 0.573%, **not
the infinite-deck math of the actual dealing procedure**."* That second clause is false, and
the engine itself disproves it:

```
infinite deck, S17, DAS, split-to-2 (NO resplit):  edge 0.570388%  ->  0.57%   RTP 99.43%
infinite deck, S17, DAS, split-to-3             :  edge 0.520766%  ->  0.52%   RTP 99.48%
infinite deck, S17, DAS, split-to-4 (default)   :  edge 0.511734%  ->  0.51%   RTP 99.49%
```

`Blackjack(max_hands=2)` reproduces Stake's published **0.57% and 99.43% to both published
digits**. And the Stake reference's own quoted rules text says only *"you can decide to
split your hand in two"* — it never mentions resplitting. So the most parsimonious reading
of the payout reference is that Stake Original Blackjack is a **split-to-2** game and its
0.57% *is* infinite-deck math for the actual dealing procedure.

This does **not** make the engine's default wrong: the assignment names the WoO
infinite-deck figure (0.511734%) as the statistical bar, and the Stake reference explicitly
warns that the dealer rules are unpublished and must not be assumed from third-party
sources. The two references genuinely conflict and the builder adjudicated as instructed.
But the *justification sentence* is a claim the engine's own code refutes, and it is the
one thing in the deliverable an expert would immediately challenge. It should read: "Stake
publishes no dealer rules; 0.57% is reproduced by this engine at `max_hands=2` (0.570388%)
and also matches WoO's 6-deck benchmark 0.573% — the WoO infinite-deck rule set
(`max_hands=4`, 0.511734%) is adopted per the stated statistical target."

### 6c. Minor / non-blocking

- **Insurance is never settled end to end.** The published 2:1 row exists as
  `INSURANCE_PAYS = 2.0` plus a static `insurance_ev() = −1/13`; `play_round` has no
  insurance branch at all (`"insurance" in play_round source -> False`). Defensible — basic
  strategy declines it and `config()["insurance_taken"] is False` is honest — but the third
  published payout row is the only one never exercised by an actual round.
- `simulate()`'s `se_rtp`/`z_score` still use the **analytic** SD as the SE. Legitimate now
  that the analytic SD is verified exact (it is the true SD, so it is the better estimator),
  but it means the shipped z-score cannot detect an analytic error. My §5 numbers use the
  empirical SD and agree to within 0.007%.
- The "empirical SD vs WoO published ~1.15" gate has a tolerance of 0.01 against a figure the
  reference publishes to 2 dp. It is as tight as the reference allows; just note it can never
  discriminate 1.1538 from 1.1421 (the 6-deck value).

---

## 7. Blind comparison (labels stripped)

Two unlabeled columns. One is the reference set (Stake game page + WoO infinite-deck /
variance pages); one is ours.

| # | Quantity | **A** | **B** |
|---|---|---|---|
| 1 | Beat the dealer, standard hand | 1:1 → 2.00 returned | 1:1 → 2.00 returned |
| 2 | Beat the dealer with blackjack | 3:2 → 2.50 returned | 3:2 → 2.50 returned |
| 3 | Insurance | 2:1 → 3× stake | 2:1 → 3× stake |
| 4 | CARDS index 0 / 32 / 51 | ♦2 / ♦10 / ♣A | ♦2 / ♦10 / ♣A |
| 5 | Cursor reservation | 13 | 13 |
| 6 | Deck model | unlimited decks, `floor(float·52)` | unlimited decks, `floor(float·52)` |
| 7 | Infinite-deck optimal player EV | −0.511734% | −0.5117336% |
| 8 | RTP | 99.488% | 99.4883% |
| 9 | Per-hand SD (unit initial bet) | ~1.15 | 1.1538 |
| 10 | Variance (benchmark 1.295 + DAS 0.03753) | 1.33253 | 1.331143 |
| 11 | Strategy deviations vs the 4-deck chart | soft 13 v 5 hit, soft 15 v 4 hit — and nothing else | soft 13 v 5 hit, soft 15 v 4 hit — and nothing else |
| 12 | Hard 11 v A | hit | hit |
| 13 | A,7 v 2 / v 3 / v 9 | stand / double / hit | stand / double / hit |
| 14 | Max hands after resplitting non-aces | 4 | 4 |
| 15 | P(round settles as 4 hands) | 5.4395e-04 | 5.4395e-04 |
| 16 | P(|net| > 6) | 1.1278e-05 | 1.1278e-05 |
| 17 | Support of the round payout | −8 … +8 in half units | −8 … +8 in half units |
| 18 | Insurance EV per unit | −1/13 | −0.076923076923077 |

**Could an expert tell?** Rows 1–18: no. Rows 7–10 agree to every digit the reference
publishes; rows 11–13 are the WoO-named infinite-deck chart; rows 14–17 were the Round-2
structural tells (4-hand rounds, ±7/±8 outcomes) and are now identical. Row 10 is derived
through a route the engine never uses, and still lands within 0.1%.

The only cell that separates the two is Stake's game-page headline **0.57% / 99.43%** vs the
engine's 0.51% / 99.49% — and that cell separates the reference **from itself**: the Stake
page and the WoO infinite-deck page publish two irreconcilable numbers for "this game", and
the assignment adjudicates in favour of WoO. An expert shown row 19 would conclude the
composite reference column is internally inconsistent, not that ours is the imitation.

**The blind test is a coin flip.** Rounds 1 and 2 failed it on five independent tells; none
of them survives.

---

## 8. Numbers

```
Payouts vs references/stake/blackjack.md §4:  all 3 rows exact.  Worst payout diff: 0
  standard win  1:1  -> total_returned 2.00   (verified live off my own HMAC stream)
  blackjack     3:2  -> total_returned 2.50
  dealer natural     -> total_returned 0.00
  insurance     2:1  -> 3x stake, EV -0.076923076923077 = -1/13 exactly
CARDS index table: 52/52 entries match; 16 tens, 4 aces.  Cursor reservation 13. ✓

Analytic house edge  engine 0.511733636839%   reference 0.511734%   residual -3.63e-09  ✓
Analytic RTP         engine 99.4882663632%    reference 99.488%                          ✓
Analytic SD          engine 1.153751628517    reference ~1.15  (and 1.295+0.03753 route) ✓
Payout distribution  18 bins, worst |engine - independent| = 0.0e+00 (exact)             ✓
Strategy             0/660 cells vs my DP;  exactly 2 deviations vs the 4-deck book      ✓
Greedy vs optimal resplit: identical to 0.00e+00 on 12 rule variants                     ✓
RNG replay           40,000/40,000 nonces bit-identical, scalar AND vectorized           ✓
float_budget sweep   6/7/9/14/24/40 -> payouts bit-identical, 3073 overflows worst       ✓

My 60,000,000-round campaign (fresh secret seed, engine public API, my own SE):
  empirical edge 0.4981008%   SE 1.489585e-04   3-SE band [0.453413%, 0.542788%]
  z vs WoO 0.511734%          -0.915                                            PASS
  empirical SD 1.153828       z vs analytic +1.01                               PASS
  chi2 vs my analytic law     21.26  df=17  p=0.215                             PASS
  |net|>6  observed 690 / expected 676.7  (z +0.51)                             PASS
  runtime 330.1 s, 181,772 rounds/s, overflow scalar replays 0

Builder's gates, run by me:
  scripts/validate_blackjack.py   17/17 pass, 10M rounds, 53.2 s, exit 0
  pytest tests/test_blackjack.py  28 passed
  ANALYTIC_EDGE_TOL now 5e-7 (was 1.5e-4 sized to the bug); the Round-2
  "pytest.raises(ValueError): Blackjack(max_hands=4)" lock-in is gone.
```

## 9. The one change that most closes the remaining distance

Fix `outcome_probabilities()["blackjack_win"]` so it is computed from
`p_player_bj · Σ_u P(u)(1 − p_dealer_bj(u))` rather than by reading the
`_lat_idx(bj_payout)` bin — it is a three-round-old known bug that reports 0.102864 instead
of 0.045096 at the constructor-permitted `bj_payout=2.0` — and, in the same pass, replace
the "0.57% is not infinite-deck math" claim in `blackjack.py` / `validate_blackjack.py` with
the true statement that `Blackjack(max_hands=2)` reproduces Stake's published 0.57% / 99.43%
exactly, while the WoO infinite-deck rule set (`max_hands=4`) is adopted as the stated
statistical target. Neither changes a single reference number; both remove the only two
things in the deliverable an expert can currently challenge.
