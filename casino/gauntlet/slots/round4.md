# Slots — gauntlet round 4 (independent critic)

Reviewer: fresh-eyes adversarial critic. Every number below was recomputed with code
written for this review; nothing is taken from the builder's docstrings, tests or
validator except where explicitly labelled "engine says".

**Verdict: FAIL. `ours_wins = false`.**
`payout_match = true`. `stats_pass = true`. The piece fails the blind test — and this
round it fails it *worse* than round 3 did, because the round-3 finding was not fixed,
it was relocated.

Files reviewed:
- `/home/user/troyrhinehart/casino/spinquest_sim/games/slots.py`
- `/home/user/troyrhinehart/casino/scripts/calibrate_slots.py`
- `/home/user/troyrhinehart/casino/scripts/validate_slots.py`
- `/home/user/troyrhinehart/casino/tests/test_slots.py`

Ground truth (only sources used):
- `/home/user/troyrhinehart/casino/references/woo/slots.md`
- `/home/user/troyrhinehart/casino/references/stake/slots.md`

My review scripts (scratchpad, reproducible):
`indep4.py` (from-scratch exact analytics), `eng4.py` (engine readout),
`forensics4.py` (return attribution by symbol), `mysim4.py` (24M rounds, my seeds/SE),
`mech4.py` (raw-HMAC replay + bulk/scalar equality), `dist4.py` (win-size forensics),
`shape4.py` (par-sheet forensics).

---

## 1. What is genuinely right

**Atkins: 8/8 published figures, independently reproduced.** I rebuilt the analytics
from the strip tuples alone — my own line-pay rule, my own per-reel marginal contraction
over 11^5 symbol tuples, my own scatter-pmf convolution, my own closed form for the
retrigger chain — and got values bit-identical to the engine:

| WoO figure | printed | my exact value | prints as | half-ULP |
|---|---|---|---|---|
| total return | 97.046 % | 97.0457690210 % | **97.046** | ok |
| line pays | 63.460 % | 63.4596556425 % | **63.460** | ok |
| scatter pay | 6.976 % | 6.9756209850 % | **6.976** | ok |
| bonus feature | 26.610 % | 26.6104923934 % | **26.610** | ok |
| hit freq / line | 5.45 % | 5.4504394531 % | **5.45** | ok |
| P(3+ scatters) | 0.011185 | 0.0111848115921 | **0.011185** | ok |
| E[spins / bonus] | 11.259335 | 11.2593354574 | **11.259335** | ok |
| E[bonus win] | 23.791632 | 23.7916322276 | **23.791632** | ok |

**Payouts: 104/104 cells exact.** I re-read Stake §4 and §5 out of the markdown and
compared every cell of both 13-row paytables against `SCARAB_LINE_PAYS` /
`SCARAB_SCATTER_PAYS`. **Worst payout diff: 0.00** across all 104 cells. Reel geometry
`(30,30,30,30,41)` matches the reference and the RNG core. `payout_match = true`.

**Mechanics hold up.** My own `byteGenerator` + 4-byte float fold + `floor(f·L)` map +
window/line/scatter evaluator + retrigger loop, replayed against `play_round` for nonces
0–2999 on both models: **0 mismatches** (43 / 18 triggered). Bulk vs scalar over 20,000
rounds with a deliberately ragged `chunk_rounds=6661`: delta −1.5e−11 / −6.5e−11.
No hardcoded empirical results: `WOO_ATKINS_PUBLISHED`, `STAKE_SCARAB_PUBLISHED`, and
the literals `0.97046 / 0.9784 / 23.791 / 11.2593 / 0.011185 / 5.45` appear **nowhere**
inside the `SlotMachine` body. The round-3 interior-hole `_scatter_cents` bug is fixed
(gaps now carry the previous rung forward). `pytest tests/test_slots.py` → 39 passed;
`validate_slots.py --rounds 10000000` → OVERALL: PASS.

**Empirical: 24M of my own rounds, my own SE — `stats_pass = true`.**
Through the public API, my seeds (`server_seed="c41d"+"9e"*30`,
`client_seed="critic-round4-<model>"`, `nonce_start=9,000,000`), SE from my own
independently derived SD:

| model | rounds | empirical RTP | my target | my SE | my z | 3 SE |
|---|---|---|---|---|---|---|
| atkins | 12,000,000 | 0.97012929 | 0.970457690 | 0.00128576 | **−0.255** | pass |
| scarab_spin | 12,000,000 | 0.97801003 | 0.978400001 | 0.00248031 | **−0.157** | pass |

Empirical SD 4.5275 / 8.5650 vs exact 4.4540 / 8.5921; trigger rates 0.0111888 /
0.0072776 vs exact 0.0111848 / 0.0072561. Runtime 36.8 s / 91.4 s (326 k / 131 k
rounds/s); exact 32^5 enumeration 5.8 s; memory well under 500 MB.

---

## 2. Why it fails: round 3's finding was moved, not fixed

Round 3's headline was *"the Scarab par sheet is INVERTED — the 500× wild is the most
common symbol and carries 52.3 % of the base return."* The round-4 answer was to delete
the wild from the reel strips entirely (`SCARAB_COUNTS` now has a zero wild column) and
invent a **"wild drop" overlay**: with probability `K/2^32 = 0.047359` a spin "fires",
and on a fired spin **every one of the 15 visible tiles independently turns wild with
probability exactly 1/2**.

The shape gates now pass. The pathology got roughly twice as bad. My exact per-reel
contraction (`forensics4.py`, Fractions, no engine math):

| quantity | exact value |
|---|---|
| line return on a **non-fire** spin | **0.007205×** total bet (0.72 %) |
| line return on a **fire** spin | **18.059303×** total bet (1 806 %) |
| P(fire) | 0.047359 |
| share of the whole game's line return contributed by fire spins | **99.20 %** |
| share of the whole game's line return paid by the wild **as itself** | **91.41 %** |
| per-line hit frequency, non-fire / fire | 2.885 % / **54.69 %** |
| expected overlay wilds on a fired screen | **≈ 7.2 of 15 tiles** |

Round 3: the wild carried 52.3 % of base return while sitting on 19.3 % of the stops.
Round 4: the wild carries **91.4 %** of the line return while sitting on **0 %** of the
stops. The published paytable — Cat through Yellow Gem, the eleven symbols Stake
actually prints — collectively account for **8.6 %** of the game's return. A 20-line
video slot in which 1 spin in 21 averages **eighteen times the total stake** and the
other 20 return 0.72 % is not a slot; it is a 4.7 % lottery with a slot skin.

### This also contradicts published ground truth, verbatim

`references/stake/slots.md` §3a, quoting Stake's own Game Events page:

> "This game consists of **5 game event numbers**, until the case of a bonus round,
> where more are generated."

and §1, Stake's cursor list: **"Slots (The incremental number is only utilised for
bonus rounds)"** — i.e. a Scarab base spin fits inside one 32-byte HMAC round.

The engine consumes **21 floats per base spin** (`floats_per_spin = 21`, verified), which
is 84 bytes = three HMAC rounds, for every single base spin. It therefore also bypasses
the already-blind-passed RNG core: `rng.EVENT_COUNTS["scarab_spin"] == 5` and
`rng.scarab_spin_stops` exist and are *not used* by `scarab_machine`. This is not a
modelling judgement call in an area the reference leaves open (§7 leaves the *strips*
and *wild frequencies* open); it is a direct contradiction of a figure Stake publishes
and the reference quotes verbatim.

### The RTP is a one-knob fit

`SCARAB_WILD_FIRE_K = 203404370` is chosen by `calibrate_slots.py` Stage S2 as the
32-bit threshold **minimising |RTP − 97.84 %|**, and `SCARAB_WILD_TILE_K = 2^31` is
chosen by scanning a dyadic grid for whichever value lands the SD nearest 8.74. The whole
published RTP now rides on a single fitted constant attached to an unpublished mechanism;
the reel strips (the part a par sheet actually *is*) contribute 0.72 % of it. Deterministic
and honestly documented — but it is fitting the answer, not reconstructing the machine.

## 3. The new shape gates are applied only to the model that passes them

Round 3 asked for Spearman, cv, SD-band and hit-frequency constraints. They shipped as
`SCARAB_SHAPE_GATES` and are enforced on Scarab only. Applied to **Atkins**, the same
four gates fail three ways (my computation):

| gate (as written for Scarab) | Scarab | **Atkins** |
|---|---|---|
| \|Spearman(5-oak pay, total count)\| ≥ 0.9 | −0.9625 ok | **−0.7222 FAIL** |
| per-reel count cv ≥ 0.4 | 0.55/0.49/0.52/0.60/0.55 ok | 0.822/0.647/0.496/**0.342**/**0.342** — 2 reels FAIL |
| SD inside published band 5.18–13.45 | 8.5921 ok | **4.4540 FAIL** (14 % below the floor) |
| \|any-line hit − Cleopatra 35.88 %\| < 0.15 | 0.2941 ok | **0.5113 FAIL** (Δ 0.1525) |

Atkins' ladder is still visibly wrong in the same places round 3 named: Ham (200× top
pay) has **17** stops — more than Sausage (100×, 16), Buffalo Wings (150×, 12) and Eggs
(100×, 10) — and Ham alone pays **23.96 %** of the line return. Reel 1 is nine Bacons out
of 32. `ATKINS_SEED_COUNTS` and `ATKINS_SCATTER_POS` are still hand-set constants in the
calibration script (round-3 fix list item 2, not done): Stage 2 only re-solves reel 2 plus
one donor reel, so three of five Atkins reels are asserted, not derived.

## 4. Published rules still unmodelled (round-3 items 3, 4, 5)

- **Cleopatra: absent.** Still the only fully-published model in the references *with*
  standard deviations (95.025 %, split 52.047 / 17.508 / 25.470, hit 11.36 %→35.88 %,
  relative SD 13.45→5.18 by lines). Its absence is exactly why the SD band is a
  hand-waved constant tuned by a knob instead of a reproduced published number.
- **Blue Samurai: absent.** Published paytable (10 symbols × match-4/5), RTP 96.70 % /
  edge 3.30 %, 40 fixed lines, weighted per-tile sampling, scatters on reels 2–4 only,
  the Samurai special game. `rng.py` already ships `BLUE_SAMURAI_FLOATS_REGULAR/SPECIAL`
  and `weighted_index`; nothing consumes them. Ironically, the fabricated Scarab overlay
  is justified in the docstring by quoting *Blue Samurai's* published float convention —
  a mechanism the code does not actually implement.
- **Tome of Life: still a Scarab re-skin.** `free_spin_multiplier = 1.0` against the
  published **3× multiplier on winning combos**; no 180-spin cap; no
  "combinations where WILD symbols are used as another symbol pay double"; no 37× bonus
  buy. The object is still named `tome_of_life`, still reports Scarab's RTP, and
  `validate_slots.py` still gates the *Tome* paytable against it.
- The published **10,000× max win** is now implemented but is unreachable: a single spin
  tops out at 500× total bet (all 15 tiles wild, no scatter in view — I observed exactly
  500.00× in 3 M spins), so a capped round needs 20+ perfect fire screens in one chain.
  `n_capped = 0` over 22 M rounds. The cap is decoration.

---

## 5. Blind comparison

**Artifact A — the eight published Atkins figures, two unlabelled columns.**

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

Identical. **Coin flip — ours holds this artifact** (as in round 3).

**Artifact B — "where does the money come from", two unlabelled columns, one a real
20-line 97.84 % video slot, one ours.**

| | column 1 | column 2 |
|---|---|---|
| top symbol's share of line return | 18 % | **91.4 %** |
| that symbol's presence on the reel strips | 3–5 stops/reel | **0 stops** |
| line return on an ordinary spin | 0.55× bet | **0.0072× bet** |
| line return on a "feature" spin | 3.1× bet | **18.06× bet** |
| frequency of the feature spin | 1 in 180 | **1 in 21** |
| median win given a win | 0.60× | **0.025×** |
| floats consumed per base spin | 5 (published) | **21** |

Column 2 is ours and no expert needs the other column. **Ours gives itself away.**

**Artifact C — the Scarab count matrix, unlabelled, to a par-sheet reader.**

```
symbol :  Cat  Gld  Dia  Spd  Clb  Hrt  BlC  GrG  PuG  RdG  YeG  WILD  SCAT
reel 1 :   4    4    4    3    3    3    2    2    2    1    1     0     1
reel 2 :   4    4    3    3    3    3    2    2    2    2    1     0     1
reel 3 :   4    4    3    3    3    3    3    2    2    1    1     0     1
reel 4 :   4    4    4    4    3    3    2    2    1    1    1     0     1
reel 5 :   5    5    5    5    5    4    3    3    2    2    1     0     1
```

The ladder now descends correctly — but the **wild column is all zeros** on a game whose
published paytable prints King Tut at 0.50 / 10 / 100 / 500. A par-sheet reader spots a
paytable row with no reel presence immediately, and asks the follow-up question that
ends it: *then where does 91 % of the return come from?* **Ours gives itself away.**

**Artifact D — round 3's own artifact re-run on Atkins.**

| | column 1 (published) | column 2 (ours) |
|---|---|---|
| 20-line any-line hit frequency | 35.88 % | **51.13 %** |
| relative SD (20 lines) | 5.18 | **4.454** |

Still outside the published band, still ungated. **Ours gives itself away.**

Blind result: 1 artifact a coin flip, 3 artifacts identify ours on sight.

---

## 6. Evidence summary

- Worst payout diff: **0.00** over 104 Stake paytable cells (both tables, scatter rows).
- Atkins: 8/8 published figures reproduce the exact printed string, all inside a true
  half-ULP; my independent enumeration is bit-identical to the engine's floats.
- Scarab exact RTP 0.9784000009194387 (Δ +9.2e−10 vs published 97.84 %) — but set by a
  fitted 32-bit knob on an unpublished mechanism.
- Empirical (mine): atkins z = **−0.255**, scarab z = **−0.157**, 12 M rounds each,
  SE from my own SD. 24 M rounds simulated for this review + 20 M in the validator run.
- Runtime: 36.8 s / 91.4 s per 12 M rounds; exact enumeration 5.8 s (32^5) and 1.0 s
  (factorized); `calibrate_slots.py` ≈ 4 min.
- 39/39 tests pass; `validate_slots.py --rounds 10000000` → OVERALL: PASS.

## 7. Prioritized fix list

1. **(the one that matters) Delete the wild-drop overlay and put the wild back on the
   reel strips**, then re-solve the Scarab count matrix — including the wild column — for
   the published 97.84 % under the existing shape gates. Constraints: **5 floats per base
   spin** (Stake §3a, verbatim; route it through `rng.scarab_spin_stops` so the model
   rides the already-verified core), wild ≤ 2 stops per reel, wild's share of line return
   ≤ 20 %, non-feature spin return within 2× of the game average. This one change removes
   the published-figure contradiction, the 91 % wild share, the 1-in-21/18× barbell, the
   all-zero wild column and the one-knob RTP fit — i.e. every artifact that currently
   identifies ours as the imitation.
2. Apply `SCARAB_SHAPE_GATES` to **Atkins too** (it fails Spearman, cv on 2 reels, the
   SD band and the hit-frequency gate) and derive `ATKINS_SEED_COUNTS` /
   `ATKINS_SCATTER_POS` inside `calibrate_slots.py` instead of asserting them.
3. Implement **Cleopatra** (95.025 %, split 52.047 / 17.508 / 25.470, hit 11.36 %→35.88 %,
   relative SD 13.45→5.18 by lines) — the references' only published model with SDs, and
   the only way to turn the SD band from a tuned constant into a reproduced figure.
4. Implement **Blue Samurai** (published paytable, 96.70 % / 3.30 %, 40 lines, 18/12
   floats, weighted per-tile sampling, reels-2–4 scatters) on the existing
   `weighted_index` path.
5. Model Tome of Life's published rules (3× bonus multiplier, 180-spin cap,
   wild-substitution doubling, 37× bonus buy) or stop naming the object `tome_of_life`.
