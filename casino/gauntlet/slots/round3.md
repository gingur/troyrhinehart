# Slots — gauntlet round 3 (independent critic)

Reviewer: fresh-eyes adversarial critic. Nothing below comes from the builder's
tests, docstrings, or validator output except where explicitly labelled "engine
says"; every number was recomputed with code written for this review.

**Verdict: FAIL. `ours_wins = false`.**
`payout_match = true`. `stats_pass = true`. The blind test is what fails.

Files under review:
- `/home/user/troyrhinehart/casino/spinquest_sim/games/slots.py`
- `/home/user/troyrhinehart/casino/scripts/calibrate_slots.py`
- `/home/user/troyrhinehart/casino/scripts/validate_slots.py`
- `/home/user/troyrhinehart/casino/tests/test_slots.py`

References (only ground truth used):
- `/home/user/troyrhinehart/casino/references/woo/slots.md`
- `/home/user/troyrhinehart/casino/references/stake/slots.md`

My review scripts (kept for reproduction, all under
`/tmp/claude-0/-home-user-troyrhinehart/b3ce270f-e608-55a6-8515-5735b66f4ebe/scratchpad/`):
`indep3.py` (from-scratch exact enumeration, different loop factorization),
`shape3.py` (par-sheet forensics), `mysim3.py` (12M-round driver, my seeds/SE),
`mech3.py` (raw-HMAC round replay), `dist3.py` (win-size distribution + 3-seed
bias re-check), `edge3.py` (edge cases + constant-leak scan).

---

## 1. Round 2's headline finding is genuinely fixed

Round 2 failed the piece because three of the eight published Atkins figures
printed the wrong last digit (97.047 / 26.611 / 23.791825) and because
`WOO_ATKINS_TOL` had been widened 4×–2000× on exactly and only the failing
figures. Both are fixed, and I verified the fix independently rather than
trusting the validator.

My enumerator is a genuinely separate implementation: my own line-pay rule, my
own LSB-first symbol-tuple LUT, outer loop over **reel 5** (the engine loops
over reel 1), `Fraction`/`int` arithmetic throughout, plus three cross-checks
that share no code with the engine — the per-line marginal from symbol counts
only, the scatter pmf by explicit convolution, and `E[T]` / `E[spins]` /
`E[T²]` by **fixed-point iteration instead of the closed form**.

| Published figure | WoO printed | my exact value | prints | Δ | half-ULP |
|---|---|---|---|---|---|
| total return | 97.046 % | 97.045769021 % | **97.046** | 2.31e-06 | 5e-06 |
| line pays | 63.460 % | 63.459655643 % | **63.460** | 3.44e-06 | 5e-06 |
| scatter pay | 6.976 % | 6.975620985 % | **6.976** | 3.79e-06 | 5e-06 |
| bonus feature | 26.610 % | 26.610492393 % | **26.610** | 4.92e-06 | 5e-06 |
| hit freq / line | 5.45 % | 5.450439453 % | **5.45** | 4.39e-06 | 5e-05 |
| P(3+ scatters) | 0.011185 | 0.011184811592 | **0.011185** | 1.88e-07 | 5e-07 |
| E[spins / bonus] | 11.259335 | 11.259335457 | **11.259335** | 4.57e-07 | 5e-07 |
| E[bonus win] | 23.791632 | 23.791632228 | **23.791632** | 2.28e-07 | 5e-07 |

Eight for eight on the printed string, eight for eight inside a **true**
half-ULP. I re-derived the half-ULPs myself and they are correct; the fudged
tolerance table is gone and `test_atkins_tolerances_are_true_half_ulp` now
pins it. My exact values are bit-identical to the engine's floats
(`rtp = 0.9704576902097589`, `std = 4.4539946109470385`), so the engine's
arithmetic is right and my check is a real second opinion, not a re-print.

Cross-checks: counts-only line return `21293527/33554432` equals the joint
enumeration as an exact `Fraction`; convolution `P(3+) = 0.01118481159210205`
matches to 1e-16; the fixed-point bonus chain matches the closed form.

`scripts/calibrate_slots.py` now exists, runs in ~4 minutes, and **reproduces
both shipped strip tuples byte-for-byte** — I ran it. Stage 1's claim is real:
the published set does pin the line-pay sum to the unique integer
M\* = 21,293,527 (window `(21293526.2772, 21293527.2706)`), and the engine hits
it exactly.

## 2. Payouts: 104/104 cells exact — payout_match = true

I wrote my own markdown parser (not the validator's) and diffed every cell of
Stake §4 and §5 against the engine tables:

- Scarab Spin: 13 rows × match-2/3/4/5 = **52 cells, 0 mismatches**
- Tome of Life: 13 rows × match-2/3/4/5 = **52 cells, 0 mismatches**
- em-dash blanks preserved as `None`, scatter row 2.00/6.00/50.00/500.00 exact
- Reel geometry (30, 30, 30, 30, 41) matches the reference text, the engine,
  and `rng.SCARAB_SPIN_REELS`
- Scarab exact RTP 0.9783814920405637 → prints "97.84" / edge "2.16"
  (Δ −1.85e-05 vs a 5e-05 half-ULP)

**Worst payout diff across all 104 cells: 0.00.**

## 3. Mechanics: I could not break them

- **Raw-HMAC replay.** I re-implemented a full round from
  `HMAC_SHA256(serverSeed, "client:nonce:round")` — my own byte→float fold, my
  own `floor(f·L)` stop map, my own window/line/scatter evaluation, my own
  retrigger loop — and compared to `play_round` for nonces 0–3999 on both
  models: **0 mismatches** (58 / 31 triggered rounds, deepest chain 30 free
  spins). Bonus spin *j* really does consume cursor `20(j+1)` of the *same*
  nonce, matching Stake's "Slots: the incremental number is only utilised for
  bonus rounds".
- **Bulk == scalar.** `simulate(30000, chunk_rounds=7777)` (deliberately not a
  divisor, so chunk boundaries fall mid-stream) vs the sum of 30 000
  `play_round` calls: delta +8.4e-15 (atkins) / +4.0e-14 (scarab).
- **No hardcoded empirical results.** I scanned the bodies of
  `enumerate_exact`, `play_round`, `simulate`, `_bulk_spin_cents`,
  `_resolve_bonuses`, `marginal_line_stats` for any reference to
  `WOO_ATKINS_PUBLISHED` / `STAKE_SCARAB_PUBLISHED` / the literals
  `97.046`, `0.9784`, `23.791`: **all clean**. The published dicts are read
  only by the validator and the tests.
- **Edge cases.** `F·p ≥ 1` raises; `simulate(0)` raises; `simulate(2501,
  chunk=1000)` handles the ragged tail; `simulate(1)` works; the k>top scatter
  extension is right.
- **One latent bug survives from round 2 (still unfixed, still unreachable).**
  A `scatter_pays` dict with an interior hole silently pays 0 in the gap:
  `{2: 1.00, 5: 100.00}` builds `_scatter_cents = [0,0,2000,0,0,200000,…]`, so
  k=3 and k=4 pay nothing while k=2 pays and k=5 pays. Not reachable with
  either shipped config, but it is a trap for the next model added.

## 4. Empirical: my own 54M rounds, my own SE — stats_pass = true

Through the public API `SlotMachine.simulate(...)`, my own seeds
(`server_seed = "7d41" + "b8"×30`, `client_seed = "critic-r3-<model>"`,
`nonce_start = 5,000,000`), and SE computed from **my** independently
enumerated SD, not the engine's:

| model | rounds | empirical RTP | my target | my SE | my z | 3 SE |
|---|---|---|---|---|---|---|
| atkins | 12,000,000 | 0.96784739 | 0.970457690 | 0.00128576 | **−2.030** | pass |
| scarab | 12,000,000 | 0.97724092 | 0.978381492 | 0.00090997 | **−1.253** | pass |

atkins' z = −2.03 is large enough to be worth ruling out as bias, so I re-ran
three more independent seeds at 10M rounds each: **z = +0.979, −0.228,
−0.709**. Combined with the validator's own 10M campaign (atkins z = +2.042,
scarab z = −0.211) the residuals scatter around zero — no systematic leak in
the bonus-resolution path. Total simulated for this review: **54,000,000
rounds**, plus 20,000,000 in the official validator run.

SD converges too: empirical 4.4377 vs my analytic 4.4540 (atkins), 3.1478 vs
3.1522 (scarab). Trigger rates 0.01111758 / 0.00721508 vs exact 0.01118481 /
0.00725610. Bonus spins resolved: 1,500,870 and 1,458,585.

Runtime: 12M rounds in 43.8 s / 39.6 s (≈320–350 k rounds/s); exact 32⁵
enumeration 7.0 s; 30⁴·41 enumeration ≈5 s; `calibrate_slots.py` ≈4 min.
Memory stayed far under 500 MB (500 k-round chunks; enumeration chunks over one
reel). `pytest tests/test_slots.py` → **22 passed**;
`validate_slots.py --rounds 10000000` → **OVERALL: PASS**.

---

## 5. Why it still fails: the Scarab par sheet is INVERTED

Round 2's fix list item #2 asked for shape constraints in the calibration
search. What actually shipped is a new tie-break inside `arrange()` that
reshuffles the *order* of the strips. Strip order affects variance only. The
**count matrices are unchanged from round 2** — I verified this directly:
Scarab's per-line hit probability (0.288519), line return (0.862114) and wild
share are identical to the values round 2 measured. The cosmetic tells were
painted over; the structural ones were not touched.

I ranked every symbol by its 5-of-a-kind pay and correlated that rank against
its total count across the strips. A real par sheet is essentially monotone:
the better a symbol pays, the fewer of them exist.

**Scarab: Spearman(pay rank ascending, strip count) = −0.880.**

| rank | symbol | 5-of-a-kind | total stops | per reel |
|---|---|---|---|---|
| 1 | King Tut (Wild) | **500.00** | **31** | 7 / 7 / 8 / 5 / 4 |
| 2 | Red Gem | 37.50 | 15 | 3 / 3 / 2 / 3 / 4 |
| 3 | Yellow Gem | 37.50 | 16 | 3 / 3 / 3 / 3 / 4 |
| 4 | Purple Gem | 20.00 | 16 | 3 / 3 / 3 / 3 / 4 |
| … | … | … | … | … |
| 10 | Diamond | **5.00** | **7** | 1 / 1 / 1 / 1 / 3 |

The 500× wild is the **single most common symbol on the machine** — 31 of 161
stops (19.3 %), 23 %/23 %/27 %/17 %/10 % by reel — while the 5.00× Diamond is
the rarest at 7. The par sheet runs backwards. Consequences I measured:

- **Wild-as-itself carries 52.3 % of the entire base line return** (round 2:
  51.6 % — unchanged).
- **Per-line hit frequency 28.85 %; 92.16 % of spins produce a line win;
  93.3 % of spins pay something.** Stake publishes Scarab Spin as *medium
  volatility*, 20 lines. The only published 20-line hit frequency anywhere in
  the references is Cleopatra's **35.88 %**.
- 61.8 % of *all* spins return a win **smaller than half the stake**; median
  win given a win is 0.245× total bet. It is a metronome, not a slot.
- **Reels 1 and 2 have byte-identical count vectors** `(2,1,1,1,1,2,2,3,3,3,3,7,1)`.
  Round 2 flagged byte-identical *strips*; `test_no_duplicate_reels` now
  asserts `len(set(SCARAB_STRIPS)) == 5`, which the reordering satisfies while
  leaving the two reels statistically identical. That test is written to the
  letter of the round-2 finding, not its substance.
- **Reel 5's counts are eight 3s, four 4s and one scatter** (cv = 0.244) — the
  fingerprint of "spread 40 stops as evenly as possible", not a designed reel.

### Standard deviation went backwards

Round 2 asked for a target SD inside the reference's published band. Both
models moved the wrong way:

| model | round 2 SD | round 3 SD | published slot SDs in the reference |
|---|---|---|---|
| atkins | 4.788 | **4.454** | Cleopatra 20 lines **5.18**, Double Strike 8.54, |
| scarab | 3.567 | **3.152** | generic **8.74**, RW&B 9.03 / 10.80, Cleopatra 1 line 13.45 |

Scarab at 3.152 is **39 % below the lowest published slot SD** in the
references and sits closer to the reference's 9/6 Jacks video-poker figure
(~4.4) than to any slot. The reference's own words: slots carry "the highest
standard deviation of any game class on his table". Ours is the lowest.

### Atkins is much better but not clean

Spearman = **+0.673** — right sign, wrong shape. Ham (rank 3, 200× top pay) has
17 stops, more than Sausage (rank 5, 16) and Butter (rank 7, 16), and Ham alone
carries 24 % of the line return. Eggs (rank 6) has 10 stops, fewer than the
rank-3 symbol. Reel 1 carries nine Bacons out of 32. SD 4.454 is below the
entire published band; any-line hit frequency 51.1 % against Cleopatra's
published 35.88 % for the same 20-line geometry.

### The "calibrated" claim is still broader than the search

`calibrate_slots.py` is deterministic and reproduces the strips — real
progress. But its inputs are magic:

- `ATKINS_SEED_COUNTS` — a "draft par sheet" with no derivation; Stage 2 only
  re-solves **reel 2 plus one donor reel**. Three of five Atkins reels are
  hand-set constants.
- `SCARAB_COUNTS` — **no search at all**. All five Scarab count vectors are
  asserted, with only a comment claiming they "land on the published 97.84 %".
- `ATKINS_SCATTER_POS` / `SCARAB_SCATTER_POS` — hand-set.

So `slots.py`'s "the strips are the verbatim output of the calibration search"
is true of the *arrangement* and of two Atkins reels; it is not true of the
Scarab par sheet, which is where the damage is.

### Published rules still not modelled

Unchanged from round 2, all captured in the references:

- **Blue Samurai** absent entirely — published paytable (10 symbols ×
  match-4/5), RTP 96.70 % / edge 3.30 %, 40 fixed lines, dynamic *weighted*
  reels (18 floats regular / 12 special, outer 2 reels on a separate weight
  set), scatters restricted to reels 2–4, the Samurai special game. `rng.py`
  already ships `BLUE_SAMURAI_FLOATS_REGULAR/SPECIAL` and `weighted_index`.
- **Cleopatra** absent — 95.025 %, split 52.047 / 17.508 / 25.470, hit
  frequency 11.36 %→35.88 %, relative SD 13.45→5.18 by lines bet. It is the
  only fully-published model in the references **with SDs**, and therefore the
  only one that could give the validator a real volatility gate. Its absence is
  exactly why SD is drifting downward unchallenged across rounds.
- **Tome of Life** is still a re-skin: `free_spin_multiplier = 1` against the
  published 3× bonus multiplier, no 180-spin cap, no wild-substitution
  doubling, no 37× bonus buy — yet the object is named `tome_of_life`, reports
  Scarab's RTP, and `validate_slots.py` gates the *Tome* paytable against it.
- **Max-win caps** (Scarab/Tome 10,000×, Tome 40 BTC) not implemented. Measured
  ceiling: Scarab's single base spin tops out at 525× total bet (82.1× observed
  over 400 k spins); atkins 5100× ceiling, 277× observed.

---

## 6. Blind comparison

**Artifact A — the eight published Atkins figures, two unlabeled columns:**

| | column 1 | column 2 |
|---|---|---|
| total return | 97.046 % | 97.046 % |
| line pays | 63.460 % | 63.460 % |
| scatter pay | 6.976 % | 6.976 % |
| bonus feature | 26.610 % | 26.610 % |
| hit freq / line | 5.45 % | 5.45 % |
| P(3+ scatters) | 0.011185 | 0.011185 |
| E[spins / bonus] | 11.259335 | 11.259335 |
| E[bonus win] | 23.791632 | 23.791632 |

The columns are **identical**. No expert can pick the imitation.
**Coin flip — ours wins this artifact.** This is a real advance on round 2.

**Artifact B — one 5-reel count matrix, unlabeled, handed to a par-sheet
reader alongside a genuine one:**

```
symbol :  A    B    C    D    E    F    G    H    I    J    K   WILD  SCAT
reel 1 :  2    1    1    1    1    2    2    3    3    3    3    7     1
reel 2 :  2    1    1    1    1    2    2    3    3    3    3    7     1
reel 3 :  1    2    1    1    2    2    1    3    3    2    3    8     1
reel 4 :  2    1    1    2    2    2    2    3    3    3    3    5     1
reel 5 :  3    3    3    3    3    3    3    3    4    4    4    4     1
```

Reels 1 and 2 are the same vector. Reel 5 is eight 3s and four 4s. The wild —
which pays 500× and is the top symbol on the published paytable — is the most
common symbol on four of five reels. Any par-sheet reader picks this out in
under ten seconds, without needing the other column.

**Artifact C — derived behaviour, two unlabeled columns:**

| | column 1 | column 2 |
|---|---|---|
| 20-line hit frequency | 35.88 % | **93.3 %** |
| relative SD (20 lines) | 5.18 | **3.15** |
| top symbol's share of line return | (spread) | **52.3 % on the wild** |
| max win | 10,000× (published) | 525× ceiling |

Column 2 is ours, and it is obvious. **Ours gives itself away.**

---

## 7. Prioritized fix list

1. **(the one that matters)** Extend `calibrate_slots.py`'s Stage-2 exact
   solver to **derive the Scarab count matrix instead of asserting
   `SCARAB_COUNTS`**, under a par-sheet shape constraint set: counts monotone
   non-decreasing as 5-of-a-kind pay decreases (Spearman ≥ +0.9), wild ≤ 2 per
   reel and absent from reel 1 (or modelled as Stake's published *random
   overlay* wilds rather than strip symbols), no two reels sharing a count
   vector, per-reel count cv ≥ 0.4, and a target relative SD inside the
   references' published 5.18–13.45 band — then re-check that it still prints
   "97.84" / "2.16". This single change simultaneously fixes the inverted
   ladder, the 52 % wild share, the 93 % hit frequency, the reel-1≡reel-2
   duplicate, and the SD, and it is the artifact that currently identifies
   ours as the imitation on sight.
2. Apply the same constraint set to the Atkins search (Spearman +0.673 → ≥ +0.9;
   SD 4.454 → ≥ 5.18) and derive `ATKINS_SEED_COUNTS` / the scatter positions
   inside the script rather than shipping them as constants, so the whole par
   sheet is reproducible rather than two reels of it.
3. Implement **Cleopatra** (95.025 %, split 52.047 / 17.508 / 25.470, hit
   11.36 %→35.88 %, relative SD 13.45→5.18) — the references' only published
   model with SDs, and the only way to give `validate_slots.py` a volatility
   gate. Without one, SD will keep drifting down every round unnoticed.
4. Model Tome of Life's published rules (bonus ×3, 180-spin cap,
   wild-substitution doubling, 37× bonus buy) or rename the object so it stops
   claiming to be Tome of Life; implement the 10,000× max-win cap.
5. Add **Blue Samurai** (published paytable, 96.70 % / 3.30 %, 40 lines,
   weighted per-tile sampling, reels-2–4 scatters) — the one Stake slot with a
   distinct published RTP *and* a distinct mechanism, and it would exercise the
   already-shipped `weighted_index` path.
6. Fix the interior-hole bug in `_scatter_cents` (fill gaps with the highest
   rung ≤ k, not only above the top rung).
7. Replace `test_no_duplicate_reels` with a test on **count vectors**, not
   strip tuples — the current test passes a matrix whose reels 1 and 2 are
   statistically identical.
