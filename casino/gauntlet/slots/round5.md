# Slots — gauntlet round 5 (independent critic, round 1/4 of this pass)

Reviewer: fresh-eyes adversarial critic. Every figure below was recomputed with code
written for this review. Nothing is taken from the builder's docstrings, tests or
`validate_slots.py` except where a line is explicitly labelled "engine says".

**Verdict: FAIL. `ours_wins = false`.**
`payout_match = true`. `stats_pass = true`. The flagged gap from `gap.md` **is closed**
— all six of its demands are met. But the piece still fails the blind test, because the
return concentration that round 3 found on the wild's reel stops and round 4 found on
the wild-drop overlay has been relocated a **third** time: it now sits on the scatter
column and an unpublished near-critical retrigger chain.

Files reviewed
- `/home/user/troyrhinehart/casino/spinquest_sim/games/slots.py`
- `/home/user/troyrhinehart/casino/scripts/calibrate_slots.py`
- `/home/user/troyrhinehart/casino/scripts/validate_slots.py`
- `/home/user/troyrhinehart/casino/tests/test_slots.py`

Ground truth (only sources consulted)
- `/home/user/troyrhinehart/casino/references/stake/slots.md`
- `/home/user/troyrhinehart/casino/references/woo/slots.md`

My review scripts (scratchpad, all reproducible):
`/tmp/claude-0/-home-user-troyrhinehart/b3ce270f-e608-55a6-8515-5735b66f4ebe/scratchpad/`
→ `pay5.py` (markdown-parsed payout parity), `indep5.py` (from-scratch exact
analytics), `shape5.py` (par-sheet forensics), `bonus5.py` (exact free-spin chain
distribution), `tome5.py` (rule-variant stress test), `knob5.py` (scatter-density
sweep), `mech5.py` (raw-HMAC replay), `mysim5.py` (22M rounds, my seeds/SE),
`tail5.py` (chain tail / safety-cap bias).

---

## 1. The flagged gap IS closed — I reproduced the probe

`gap.md` demanded six things. I verified each one independently.

| gap.md demand | my check | result |
|---|---|---|
| delete the fabricated wild-drop overlay | grep for `FIRE_K` / `WILD_TILE_K` / overlay code | **gone** (only historical mentions in comments/tests) |
| put the King Tut wild back on the reel strips | my own recount of `SCARAB_STRIPS` | wild column = **[1, 1, 2, 2, 1]**, 7 stops machine-wide |
| re-solve the count matrix incl. the wild column for 97.84% | my own exact 30⁴·41 enumeration | exact RTP **7,005,731/7,160,400 = 0.9783993911** (Δ −6.09e−7 vs 0.9784; half-ULP window 5e−5) → prints **"97.84"** / **"2.16"** |
| base spin restricted to the 5 published floats | `SlotMachine.floats_per_spin` + my raw-HMAC replay | **5** (= 20 bytes, fits one 32-byte digest, matches `rng.EVENT_COUNTS["scarab_spin"]`) |
| route through `rng.scarab_spin_stops` | my own float fold vs `rng.scarab_spin_stops` vs `play_round` | identical stops; **routed** |
| remove the one-knob 32-bit RTP fit | grep of the `SlotMachine` body for any published literal | **no** published constant anywhere in the class body |

The round-4 pathologies it was meant to kill are genuinely dead:

| round-4 artifact | round 4 | **round 5 (my recomputation)** |
|---|---|---|
| wild's share of line return | 91.41 % | **5.53 %** (engine's definition: line return lost with the wild pay-row removed) / **0.38 %** (my max-achieving attribution) |
| wild stops on the strips | 0 | **7** (1–2 per reel) |
| floats per base spin | 21 | **5** |
| non-feature vs feature spin return | 0.0072× vs 18.06× | **identical** — every spin, base or free, has the same distribution (multiplier 1, same reels) |
| fitted 32-bit constant | `SCARAB_WILD_FIRE_K=203404370` | **none** |

Also verified: `SCARAB_COUNTS` matches a recount of `SCARAB_STRIPS` cell-for-cell;
scatter spacing ≥ 3 on every reel (min gap 15, 15, 15, 15, 13); the shape gates the
builder wrote pass on Scarab — Spearman(5-oak pay, total count) **−0.9329** ≤ −0.9,
per-reel cv **0.429 / 0.521 / 0.492 / 0.548 / 0.463** ≥ 0.4, SD **12.6004** inside
5.18–13.45, distinct reel count vectors, monotone ladder over the 11 line symbols.
`pytest tests/test_slots.py` → **39 passed**; `validate_slots.py --skip-sim` →
**OVERALL: PASS**.

---

## 2. The core bar re-verified

### Payout-for-payout parity — `payout_match = true`

I re-parsed both 13-row paytables straight out of `references/stake/slots.md` §4 and §5
(my own markdown parser, my own float conversion) and compared every cell against
`SCARAB_LINE_PAYS` / `SCARAB_SCATTER_PAYS`, symbol names included.

- Scarab Spin: **52 cells, worst diff 0.00, 0 problems.**
- Tome of Life: **52 cells, worst diff 0.00, 0 problems.**
- Reel geometry (30, 30, 30, 30, 41) matches the reference text, the engine and
  `rng.SCARAB_SPIN_REELS`. Max win 10,000×, 15 free spins, "5 game event numbers",
  "random wilds in the base game" all present verbatim in the reference.

### Atkins: 8/8 published figures, independently reproduced

My own enumerator (own line-pay rule, own LUT built scalar-side over 11⁵ tuples, own
count contraction in `Fraction`/big ints, own scatter convolution, own free-spin
recursion derived from scratch) over all 32⁵ = 33,554,432 outcomes:

| WoO figure | printed | my exact value | prints as | half-ULP |
|---|---|---|---|---|
| total return | 97.046 % | 0.9704576902097589 | **97.046** | ok |
| line pays | 63.460 % | 0.6345965564250946 | **63.460** | ok |
| scatter pay | 6.976 % | 0.0697562098503113 | **6.976** | ok |
| bonus feature | 26.610 % | 0.2661049239343530 | **26.610** | ok |
| hit freq / line | 5.45 % | 0.0545043945312500 | **5.45** | ok |
| P(3+ scatters) | 0.011185 | 0.0111848115921020 | **0.011185** | ok |
| E[spins / bonus] | 11.259335 | 11.259335457437079 | **11.259335** | ok |
| E[bonus win] | 23.791632 | 23.791632227605707 | **23.791632** | ok |

Bit-identical to the engine's floats. Exact RTP as a rational:
60,651,793,523,489 / 62,498,132,721,664.

### Empirical — `stats_pass = true`

My seeds (`server_seed="a7"*32`, `client_seed="critic-r5-<model>"`,
`nonce_start=17,000,000`), through the public `simulate()` API, with the target and the
SE taken from **my own** exact enumeration, not the engine's:

| model | rounds | empirical RTP | my exact target | my SD | my SE | **my z** | 3 SE |
|---|---|---|---|---|---|---|---|
| scarab_spin | **10,000,000** | 0.97582886 | 0.97839939 | 12.6004 | 0.00398459 | **−0.645** | pass |
| atkins | **12,000,000** | 0.96964142 | 0.97045769 | 4.4540 | 0.00128576 | **−0.635** | pass |

Recomputing the SE from the *empirical* SD instead gives z = −0.647 / −0.632 — same
verdict. Empirical SD 12.5646 / 4.4712 vs exact 12.6004 / 4.4540; trigger rates
0.060968 / 0.011187 vs exact 0.060917 / 0.011185; bonus spins per trigger 173.32 /
11.27 vs exact 173.93 / 11.26. 22M rounds ≈ 130M spins simulated for this review.
Throughput 26,980 / 225,199 rounds per second; peak RSS **298 MB / 282 MB** (under the
500 MB rule); my exact enumerations 6.7 s each.

### Mechanics

My own `byteGenerator` transliterated from the reference's published JS, my own 4-byte
float fold, my own `floor(f·L)` map, my own window/line/scatter evaluator, my own
retrigger loop, replayed against `play_round` for nonces 0–1499 on both models:
**0 mismatches** (83 / 14 triggered). `floats_per_spin = 5` on both. Base spin = 20
bytes ≤ 32, so the cursor increments only inside a bonus — exactly what Stake publishes.
No published literal appears anywhere in the `SlotMachine` body. Bulk/scalar agree.
The safety cap (`_SAFETY_SPIN_CAP = 100,000`) truncates the analytic chain with
probability ~3.7e−20; RTP bias ~4.7e−19 — negligible, so the analytics and the
simulator really are measuring the same thing.

---

## 3. Why it still fails: the concentration moved to the scatter

`gap.md`'s fix list said the one change "removes … every artifact that currently
identifies ours as the imitation." It removed the round-4 artifacts and created a new
set. My exact enumeration of the shipped Scarab par sheet (`indep5.py`, `shape5.py`,
Fractions, no engine math):

| quantity | exact value |
|---|---|
| base-spin return μ | **0.0843810×** total bet |
| — of which **line pays** (the whole 12-row published paytable) | **0.0213410×** (2.134 %) |
| — of which the **scatter row alone** | **0.0630400×** (6.304 %) |
| P(3+ scatters) = P(trigger) | **0.0609171** → one bonus per **16.4 spins** |
| free-spin amplification 1/(1 − 15p) | **11.595×** |
| E[free spins per bonus] | **173.93** |
| **scatter row's share of the game's 97.84 % RTP** | **74.71 %** |
| **free-spin feature's share of the RTP** | **89.402 / 97.840 = 91.38 %** |
| entire 12-row line paytable's share of the RTP | **25.29 %** |

The headline number, **91.38 %**, is numerically the same concentration round 4 found
on the wild (91.41 %). It has simply changed column.

### It contradicts the reference's own published bonus rules

`references/stake/slots.md` §4, verbatim: *"Land 3 scatter symbols to trigger the free
spins bonus game and receive **15 bonus free spins**."* No retrigger is published for
Scarab at all. §5, for Tome of Life — which the reference's own note says is the
**same math model with the same published 2.16 % edge** — publishes the retrigger and
its ceiling: *"the chance for respins up to an impressive **180 times** … Bonus rounds
are capped at **180 free spins**."*

I solved the chain-length distribution exactly (forward DP on (spins played, spins
remaining), `bonus5.py`) and re-scored the **shipped par sheet** under each published
rule set:

| rule set | source | RTP of the shipped par sheet |
|---|---|---|
| **as shipped**: multiplier 1, retriggers **uncapped** | not published anywhere | **97.840 %** |
| Scarab as published: 15 free spins, no retrigger | Stake §4 verbatim | **16.148 %** |
| either game with the published 180-spin cap, multiplier 1 | Stake §5 verbatim | **41.927 %** |
| Tome as published: 3× multiplier + 180-spin cap | Stake §5 verbatim | **108.904 %** |
| Tome as published: 3× multiplier, uncapped | Stake §5 | **276.644 %** |

The par sheet returns the published 97.84 % for exactly one rule set, and that rule set
is the only one Stake does **not** publish. Under the twin game's published rules the
same strips hand the player a **+8.9 % edge**.

Chain-length distribution (exact): median **30** spins, q75 **105**, q90 **360**,
q95 **750**, q99 **2,535**; **P(N > 180) = 16.5 %**, P(N > 500) = 7.4 %. **56.27 %** of
the free-spin return — i.e. ≈ 51 % of the whole game's RTP — is earned on free spins
numbered **past the 180th**, which the reference's own cap forbids. In just 1,500
replayed nonces I observed a single Scarab bonus that ran **5,055 free spins**.

### The one-knob RTP fit is still a one-knob fit — the knob moved

`calibrate_slots.py` Stage S1 sweeps the 243 per-reel scatter-count vectors in
{1,2,3}⁵ and picks the one whose implied line-return target sits mid-band. Its own
docstring states the mechanism plainly: *"the published free-spin engine amplifies the
per-spin base return μ into RTP = μ/(1 − 15p) … so the published 97.84 % demands the
exact line return lr\* = 0.9784·(1 − 15p) − sc."* That is the identical structure as
round 4's `SCARAB_WILD_FIRE_K`: one scalar knob is tuned until the published RTP falls
out. Round 4's knob was a 32-bit threshold; round 5's is the scatter count vector.

My own sweep of the same 243 configs (`knob5.py`) shows the knob has no sane setting
under the shipped rules: only 74 of 192 terminating configs give a positive required
line return at all, and **every one of them has P(3+) between 0.0437 and 0.0616** —
a bonus every 16 to 23 spins. The published anchor is Atkins' **0.011185**, one bonus
per 89 spins. So the *model family* is wrong, not just the setting: on Stake's published
paytable (top regular 5-of-a-kind 37.50 line-bets) with a descending ladder and the
self-imposed 4.5–6.2 % per-line hit window, line pays max out around 2 % of total bet,
and the only way left to 97.84 % is to drive the retrigger chain to the edge of
criticality (**15p = 0.9138**). A reconstruction that hits a published RTP only by
running a branching process at ρ = 0.914 has not reconstructed the machine; it has
found the one corner where the arithmetic closes.

### Round-4 fix items 2–5: still open

- **Item 2 — apply the shape gates to Atkins.** Not done. I applied
  `SCARAB_SHAPE_GATES` to Atkins myself: Spearman **−0.7222** (gate 0.9) **FAIL**;
  per-reel cv **0.822 / 0.647 / 0.496 / 0.342 / 0.342** — reels 4 and 5 **FAIL**;
  SD **4.4540** vs band 5.18–13.45 **FAIL**; any-line hit **0.5113** vs Cleopatra
  0.3588, Δ 0.1525 > the 0.15 gate **FAIL**. Ham (200× top pay) still has 17 stops,
  more than Sausage (100×, 16). `ATKINS_SEED_COUNTS` / `ATKINS_SCATTER_POS` are still
  hand-asserted constants in the calibration script.
- **Item 3 — Cleopatra.** Still absent. It remains the references' only published model
  *with* standard deviations, which is why the SD band is still a borrowed constant.
- **Item 4 — Blue Samurai.** Still absent. `rng.BLUE_SAMURAI_FLOATS_REGULAR/SPECIAL`
  and `weighted_index` still ship unused.
- **Item 5 — Tome of Life.** Still a byte-identical Scarab re-skin:
  `free_spin_multiplier = 1.0` against the published 3×, no 180-spin cap in the config
  at all, no wild-substitution doubling, no 37× bonus buy.
- The published 10,000× max win is still decoration: `n_capped = 0` over 22 M rounds,
  and at the model's own mean pace a 10,000× round needs ≈ **118,510** free spins —
  more than the 100,000-spin safety cap, so the cap is unreachable by construction.

### One more mis-anchored gate

`WOO_SLOT_SD_BAND = (5.18, 13.45)` is used as a two-sided band, but the reference is
explicit that **5.18 is Cleopatra's relative SD at 20 lines and 13.45 is her one-line
figure**. Scarab is a 20-line game; the like-for-like published comparator is **5.18**,
and ours is **12.6004** — 2.4× the only published 20-line number, sitting at the
one-line end of a band it should not be measured against. This is downstream of the
same cause: a game whose return is 91 % feature is necessarily this volatile.

---

## 4. Blind comparison

**Artifact A — the eight published Atkins figures, two unlabelled columns.**
Identical in every digit (table in §2). **Coin flip — ours holds this artifact.**

**Artifact B — the standard par-sheet return split, three unlabelled columns; two are
real published slots, one is ours.**

| | column 1 | column 2 | column 3 |
|---|---|---|---|
| line pays | 63.460 % | 52.047 % | **2.134 %** |
| scatter pay | 6.976 % | 17.508 % | 6.304 % |
| bonus feature | 26.610 % | 25.470 % | **89.402 %** |
| total return | 97.046 % | 95.025 % | 97.840 % |

Column 3 is ours. A 20-line video slot whose entire published paytable — eleven paying
symbols plus a 500× wild — contributes 2.1 % of the bet, and whose free-spin feature
contributes 89.4 %, is not a slot an expert has to think about. **Ours gives itself
away.**

**Artifact C — the bonus engine, unlabelled.**

| | published anchor | ours |
|---|---|---|
| P(bonus trigger) | 0.011185 (Atkins) | **0.060917** |
| one bonus per | 89 spins | **16.4 spins** |
| free spins awarded | 15 (Stake, verbatim) | 15 |
| E[free spins actually played] | ≤ 180 (Stake's published cap) | **173.93** |
| P(bonus exceeds the published 180 cap) | 0 | **16.5 %** |
| longest chain observed | ≤ 180 | **5,055** (in 1,500 rounds) |

**Ours gives itself away.**

**Artifact D — same par sheet, scored under each rule set the reference publishes.**
16.148 % / 41.927 % / 108.904 % / 276.644 % against a published 97.84 %. A genuine
Scarab par sheet must land near 97.84 % under Tome's published 3× + 180-cap too — the
reference states in Stake's own words that the two games share the math model and the
2.16 % edge. Ours hands the player an 8.9-point edge there. **Ours gives itself away.**

**Artifact E — relative SD at 20 lines.** Cleopatra published **5.18**; ours **12.60**.
**Ours gives itself away.**

Blind result: 1 artifact a coin flip, 4 artifacts identify ours on sight. Unchanged in
kind from round 4 — the tells have new coordinates, not fewer.

---

## 5. Evidence summary

- Worst payout diff **0.00** over 104 reference paytable cells (Scarab 52 + Tome 52,
  scatter rows and symbol names included), parsed by my own reader from the markdown.
- Atkins 8/8 published figures reproduce the exact printed string, all inside a true
  half-ULP; my independent enumeration is bit-identical to the engine.
- Scarab exact RTP **7,005,731/7,160,400 = 0.9783993911** (Δ −6.09e−7 vs published
  97.84 %, half-ULP 5e−5); prints "97.84"/"2.16".
- Empirical, my seeds and my SE: scarab **10,000,000** rounds z = **−0.645**;
  atkins **12,000,000** rounds z = **−0.635**. 22 M rounds ≈ 130 M spins.
- Runtime 370.6 s / 53.3 s; exact enumerations 6.7 s each; peak RSS 298 MB / 282 MB.
- Raw-HMAC replay: 0 mismatches over 1,500 nonces per model; 5 floats per spin;
  stops identical to `rng.scarab_spin_stops`.
- 39/39 tests pass; `validate_slots.py --skip-sim` → OVERALL: PASS.
- Shape (why it fails): line 2.134 % / scatter 6.304 % / feature 89.402 % of bet;
  scatter row = 74.71 % of RTP; feature = 91.38 % of RTP; P(trigger) 0.060917;
  E[bonus] 173.93 spins; P(N > 180) = 16.5 %; 56.27 % of feature return earned past the
  published 180-spin cap; same par sheet returns 16.148 % / 41.927 % / 108.904 % under
  the reference's own published rule variants.

## 6. Prioritized fix list

1. **(the one that matters) Stop manufacturing the RTP out of the free-spin chain.**
   Re-solve the Scarab model so the published 97.84 % is carried by the published
   paytable, under the reference's own published bonus rules: **15 free spins on 3
   scatters, retriggers capped at 180 total** (Stake §5, the only cap the reference
   publishes for this math model). Hard gates to add, all measurable from the exact
   enumeration already in the engine: P(3+ scatters) ≤ 0.02 (Atkins publishes 0.011185),
   E[free spins per bonus] ≤ 180 with **P(chain > 180) = 0**, free-spin feature ≤ 35 %
   of RTP (Atkins 27.4 %, Cleopatra 26.8 %), scatter row ≤ 25 % of RTP (Atkins 7.2 %,
   Cleopatra 18.4 %), line pays ≥ 50 % of RTP. If no par sheet on Stake's published
   paytable can satisfy those at 20 lines — and my sweep of all 243 scatter
   configurations says none can under the current rule model — then the missing piece is
   a published mechanic the engine is not modelling (Tome's 3× bonus multiplier and
   wild-substitution doubling are both published and both unimplemented), and *that* is
   what must be built, not a near-critical retrigger chain. Solve the two published rule
   sets **jointly**: one par sheet that returns 97.84 % as Scarab *and* 97.84 % as Tome.
2. Apply `SCARAB_SHAPE_GATES` to **Atkins** too (it fails Spearman, cv on reels 4–5,
   the SD band and the hit-frequency gate) and derive `ATKINS_SEED_COUNTS` /
   `ATKINS_SCATTER_POS` inside `calibrate_slots.py` instead of asserting them.
3. Fix the SD gate's anchor: compare a 20-line game against Cleopatra's **20-line**
   5.18, not against a band whose upper end is her one-line figure.
4. Implement **Cleopatra** (95.025 %, split 52.047 / 17.508 / 25.470, hit 11.36 % →
   35.88 %, relative SD 13.45 → 5.18 by lines) — the references' only published model
   with SDs, and the only way to turn the SD band into a reproduced published number.
5. Implement **Blue Samurai** (96.70 % / 3.30 %, 40 lines, 18/12 floats, weighted
   per-tile sampling, reels-2–4 scatters) on the existing `weighted_index` path, and
   model Tome of Life's published rules (3× multiplier, 180-spin cap, wild doubling,
   37× bonus buy) or stop naming the object `tome_of_life`.
