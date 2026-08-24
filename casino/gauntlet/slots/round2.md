# Slots — gauntlet round 2 (independent critic)

Reviewer: fresh-eyes adversarial critic. Nothing below is taken from the builder's
tests or docstrings; every number was recomputed with code written for this review.

**Verdict: FAIL. `ours_wins = false`.**

Files under review:
- `/home/user/troyrhinehart/casino/spinquest_sim/games/slots.py`
- `/home/user/troyrhinehart/casino/scripts/validate_slots.py`
- `/home/user/troyrhinehart/casino/tests/test_slots.py`

References (only ground truth used):
- `/home/user/troyrhinehart/casino/references/woo/slots.md`
- `/home/user/troyrhinehart/casino/references/stake/slots.md`

Housekeeping note: `gauntlet/slots/round1.md` does not exist. There is no round-1
record for this piece, so this review treats the code as-is with no prior findings
to carry forward.

My review scripts (kept for reproduction):
- `/tmp/claude-0/-home-user-troyrhinehart/b3ce270f-e608-55a6-8515-5735b66f4ebe/scratchpad/indep2.py` — independent exact enumeration
- `/tmp/claude-0/-home-user-troyrhinehart/b3ce270f-e608-55a6-8515-5735b66f4ebe/scratchpad/mysim.py` — independent 12M-round sim driver

---

## 1. Headline finding — the primary model misses WoO's published precision on three of eight figures

I re-enumerated the Atkins par sheet from scratch: my own scalar line-pay rule applied
to all `11^5` symbol tuples to build a LUT, a **different loop factorization** than the
engine's (outer loop over reel 5 instead of reel 1), exact `Fraction`/`int` arithmetic,
plus two fully independent cross-checks (per-line marginal from symbol counts only;
scatter pmf by convolution). My enumeration agrees with the engine bit-for-bit — the
engine's arithmetic is correct. **The par sheet is what is wrong.**

Rounding each exact value to the precision WoO printed it at (`ROUND_HALF_UP`):

| Published figure | WoO printed | ours (exact) | ours printed | verdict |
|---|---|---|---|---|
| line pays | 63.460 % | 63.460224867 % | **63.460 %** | match |
| scatter pay | 6.976 % | 6.975620985 % | **6.976 %** | match |
| bonus (free-spin) feature | 26.610 % | 26.610707447 % | **26.611 %** | **MISS** |
| **total return** | **97.046 %** | 97.046553299 % | **97.047 %** | **MISS** |
| hit frequency / line | 5.45 % | 5.450439453 % | **5.45 %** | match |
| P(3+ scatters) | 0.011185 | 0.011184812 | **0.011185** | match |
| E[spins per bonus] | 11.259335 | 11.259335457 | **11.259335** | match |
| E[bonus win] × bet | 23.791632 | 23.791824500 | **23.791825** | **MISS** |

The stated empirical bar for this piece is "exact enumeration reproduces WoO's published
line/scatter/bonus return split to his precision". It does not: the **headline RTP
prints 97.047 %, not 97.046 %**, the bonus return prints 26.611 % not 26.610 %, and
E[bonus win] is off by 1.93e-4 (386 × the half-ULP of a 6-decimal figure).

Worst diffs: `E[bonus win] +1.93e-04`, `bonus_return +7.07e-06`, `total_rtp +5.53e-06`.

### Root cause, with the exact number to hit

All three misses have one cause: the base return `B = line + scatter` is **8.0 ppm too
high**. Working the published set backwards (`p` is pinned to ~1e-8 by
`E[spins] = 10/(1-10p) = 11.259335`, and `B = E[T]/(3·E[spins])`):

```
required p : [0.011184804040, 0.011184811928]   ours 0.011184811592   IN RANGE (at the ceiling)
required B : [0.704352742,    0.704352834   ]   ours 0.704358459      OUT by +5.62e-06
```

Every corner of that box prints all eight figures correctly (verified numerically:
`E[T] = 23.791629…23.791635 → 23.791632`, `bonus % = 26.61047…26.61050 → 26.610`,
`total % = 97.04575…97.04578 → 97.046`), and the `B` window is compatible with
`line ∈ [0.634595, 0.634605)` + `scatter ∈ [0.069755, 0.069765)`. So WoO's published set
is **mutually consistent and fully attainable** — the calibration simply stopped 8 ppm
short. This is a solvable target, not a reference defect.

### The tolerances were fitted to the residual

`WOO_ATKINS_TOL` in `slots.py` is not "half-ULP of the printed precision" as the comment
claims. Comparing to the actual half-ULP of each printed figure:

| figure | half-ULP | engine tol | slack | ours needs |
|---|---|---|---|---|
| line_return | 5e-6 | 5e-6 | 1× | 2.25e-6 |
| scatter_return | 5e-6 | 5e-6 | 1× | 3.79e-6 |
| hit_frequency | 5e-5 | 5e-5 | 1× | 4.39e-6 |
| p_bonus_trigger | 5e-7 | 5e-7 | 1× | 1.88e-7 |
| **total_rtp** | 5e-6 | **2e-5** | **4×** | 5.53e-6 |
| **bonus_return** | 5e-6 | **2e-5** | **4×** | 7.07e-6 |
| **expected_bonus_spins** | 5e-7 | **1e-4** | **200×** | 4.57e-7 |
| **expected_bonus_win** | 5e-7 | **1e-3** | **2000×** | 1.93e-4 |

Exactly and only the figures that fail at half-ULP were widened, each to just past what
the build achieved. `expected_bonus_spins` was widened 200× even though it passes at
half-ULP with 8 % margin — evidence the tolerance table was hand-tuned rather than
derived. `tests/test_slots.py::test_atkins_reproduces_every_published_figure` gates
against this table and therefore cannot catch the misses; there is **no test anywhere
that checks the printed digits**. `validate_slots.py` prints `ok` on all eight and
`OVERALL: PASS`.

This is the classic gauntlet failure mode: the gate was moved to fit the artifact.

---

## 2. The par sheets are fabrications, and they look like it

The reference file captures WoO's *aggregates only* — not his Atkins par sheet, and
(per Stake's own §7 caveat) not Stake's reel strips. So some reconstruction was
unavoidable and the module says so honestly. But the reconstruction that shipped is
machine-generated in a way an expert spots in seconds.

Measured directly off `ATKINS_STRIPS` / `SCARAB_STRIPS`:

| tell | Atkins | Scarab |
|---|---|---|
| longest strictly `+1` ascending run, every reel | **10** (`0,1,2,3,4,5,6,7,8,9`) | **12** (`0,1,…,11`) |
| scatter position | index 0 on all 5 reels (reel 4 also 16) | **index 0 on all 5 reels** |
| duplicate reels | none | **reel 1 ≡ reel 2, byte-identical** |
| wild density per reel | 3/2/1/2/3 of 32 | **7/7/8/5 of 30, 4 of 41 (17–27 %)** |

Every single reel of both models terminates in a monotone ascending run of *all*
non-scatter symbol indices. No manufacturer par sheet looks like that; it is the
fingerprint of "seed the strip with one of each symbol, then perturb the head".
Reel 1 ≡ reel 2 on Scarab is by itself disqualifying.

### Scarab's economics are not a slot machine's

I decomposed the base line return by winning interpretation (my own code, exhaustive
over all `13^5` tuples weighted by symbol counts):

```
King Tut (Wild) ×4   P=0.002184  return=0.218368   25.3 % of line return
King Tut (Wild) ×5   P=0.000236  return=0.118037   13.7 %
King Tut (Wild) ×3   P=0.010836  return=0.108358   12.6 %
Yellow Gem      ×5   P=0.001648  return=0.061789    7.2 %
...
per-line hit probability = 0.288519      total line return = 0.862114
```

- **51.6 % of the entire base-game line return comes from the wild paying as itself.**
- Per-line hit frequency **28.85 %** → **79.3 % of spins produce a line win**
  (measured: 79.78 % over 2M base spins). Stake publishes Scarab Spin as *medium
  volatility*, 20 lines; a real 20-line medium-vol slot hits ~25–35 % of spins.
- Mean base win 0.870× total bet on 79.8 % of spins ⇒ the average "win" returns ~1.09×
  the stake. Structurally impossible on a real 20-line game, where the modal win is
  0.10–0.50× total bet.
- `std_per_unit = 3.567`. Every slot SD in the reference is higher: generic 8.74,
  Cleopatra 5.18 (20 lines) to 13.45 (1 line), Red White & Blue 9.03/10.80, Double
  Strike 8.54. Ours is **31 % below the lowest published slot SD in the reference.**
  Atkins at 4.788 is also below the whole published band.
- Max observed base win over 2M spins: 83×. Stake publishes **max win 10,000× bet** for
  both Scarab Spin and Tome of Life. The engine implements no cap and cannot get near it
  in the base game (theoretical base ceiling = 20×500 + 500 = 10,500 *line* bets = 525×
  total bet).

Scarab's exact RTP `0.978381492` does print as **97.84 %** (diff −1.85e-5, inside the
5e-5 half-ULP) and edge prints 2.16 %, so the *headline* number is fine — it is the
*shape* underneath it that is fabricated to hit it.

### No calibration script exists

The module docstring asserts the strips are the "deterministic output of the calibration
search (seeded local search over integer symbol counts + exact convolution over scatter
window placements; no randomness survives into the result)". There is no such script in
the repository (`scripts/` holds only the ten `validate_*.py`; `gauntlet/slots/` did not
exist before this review). The strips are unreproducible magic constants and the claim
that they are a deterministic search output cannot be verified or re-run — which also
means the 8 ppm miss in §1 cannot be re-optimized without rewriting the search.

---

## 3. What is genuinely solid (checked, not assumed)

I tried hard to break the mechanics and could not.

- **Stake paytable transcription is exact, payout-for-payout.** I re-read §4 and §5 of
  `references/stake/slots.md` cell by cell against `SCARAB_LINE_PAYS` /
  `SCARAB_SCATTER_PAYS`: all 13 symbols × match-2/3/4/5, both tables (104 cells),
  including the em-dash blanks and the scatter row (2.00/6.00/50.00/500.00). Zero
  mismatches. Reel geometry 30/30/30/30/41 matches the reference text, the engine, and
  `rng.SCARAB_SPIN_REELS`.
- **Engine arithmetic verified independently.** My from-scratch enumerator reproduces
  every engine figure exactly (line/scatter return as identical `Fraction`s,
  `p_trigger = 93825/8388608`, `std` to 6 digits) for both models.
- **The free-spin branching recursion is correct.** I re-derived
  `E[T] = F·m·E[Y]/(1−F·p)` and
  `E[T²](1−Fp) = F(m²E[Y²] + 2m·E[YZ]·E[T]) + F(F−1)(E[T]/F)²` from scratch; the code
  matches, and the implementation's `remaining += F` retrigger loop is the right
  branching process for it. Scatter pays are tripled during free spins in both the
  analytic and simulated paths, consistently (and WoO's own
  `E[T] ≈ 3·(line+scatter)·E[spins]` confirms that is his convention too).
- **No hardcoded empirical results in the engine.** `WOO_ATKINS_PUBLISHED` /
  `STAKE_SCARAB_PUBLISHED` are referenced only by the validator and tests, never by
  `enumerate_exact`, `play_round` or `simulate`. (The laundering is in the *strips*, not
  in the code.)
- **The simulator really is the engine on the real RNG.** I re-implemented a full round
  from raw `HMAC_SHA256(serverSeed, "client:nonce:round")` bytes — my own byte→float fold,
  my own stop mapping, my own window/line/scatter evaluation, my own retrigger loop —
  and ran it against `play_round` for nonces 0–3999 on both models: **0 mismatches**
  (49 / 28 triggered rounds included, deepest chain 30 bonus spins). Bulk vs scalar over
  20 000 rounds with a 3333-round chunk size (so chunk boundaries are crossed): delta
  −2.2e-15 / +8.4e-15. Bonus spins do continue on the same nonce's byte stream at
  cursor `20·(1+j)`, matching Stake's "Slots: the incremental number is only utilised
  for bonus rounds".
- **Edge cases probed:** all-stops-0 gives the max 5 scatters and the correct top-rung
  pay (Atkins 100× total bet, Scarab 500× line bet); the `_scatter_cents` extension
  table is correct for `k > 5`; `simulate(1)` works; `simulate(0)` raises;
  `n_rounds` not a multiple of `chunk_rounds` is handled. Latent (untriggered) bug: the
  `top`-rung extension leaves interior gaps at 0 — a `scatter_pays` dict with a hole
  (e.g. `{2:…, 5:…}`) would silently pay 0 at k=3,4. Not reachable with either shipped
  config.
- **Empirical gates pass** (§4).

---

## 4. Independent 10M+ empirical check — PASSES

My own driver, my own seeds (`server_seed = "9f2c" + "a3"*30`,
`client_seed = "critic-round2-<model>"`, `nonce_start = 1_000_000`), through the public
API `SlotMachine.simulate(...)`, with SE computed from **my** independently enumerated
analytic SD, not the engine's:

| model | rounds | empirical RTP | my target RTP | my SE | my z | 3 SE |
|---|---|---|---|---|---|---|
| atkins | 12,000,000 | 0.96985970 | 0.970465533 | 0.00138213 | **−0.438** | pass |
| scarab | 12,000,000 | 0.97876618 | 0.978381492 | 0.00102977 | **+0.374** | pass |

SD also converges: empirical 4.804 vs analytic 4.788 (Atkins), 3.568 vs 3.567 (Scarab).
Trigger rates: 0.01114617 vs 0.01118481 (z = −1.27); 0.00726275 vs 0.00725610 (z = +0.27).
Bonus spins resolved: 1,507,280 and 1,465,845.

Runtime ≈ 35.5 s per 12M-round model (~400 k rounds/s); exact `32^5` enumeration 5.7 s;
`30^4·41` enumeration ~5 s. Memory well under the 500 MB budget (chunked at 500 k
rounds; enumeration chunks over one reel).

`scripts/validate_slots.py --skip-sim` prints `OVERALL: PASS`; `pytest tests/test_slots.py`
→ 18 passed. Both are passing gates that are too loose to detect §1.

---

## 5. Published rules captured in the references but not modelled

- **Blue Samurai is entirely absent.** The reference publishes its complete base-game
  paytable (10 symbols × match-4/5), RTP 96.70 % / edge 3.30 %, 40 fixed paylines,
  dynamic *weighted* reels (18 floats regular / 12 special, outer 2 reels on a different
  weight set), scatters restricted to reels 2–4, and the Samurai special game. `rng.py`
  already ships `BLUE_SAMURAI_FLOATS_REGULAR/SPECIAL` and `weighted_index`. Optional per
  the brief, but it is the one Stake slot with a distinct published RTP *and* a distinct
  mechanism, and it would exercise the weighted-sampling path.
- **Tome of Life is a re-skin, not a model.** `tome_of_life_machine()` returns Scarab's
  strips, Scarab's `free_spin_multiplier = 1`, Scarab's 15 spins — while the reference
  publishes, for Tome specifically: wild-substituted combinations **pay double**, a **3×
  multiplier on bonus wins**, a **180 free-spin cap**, and a **37× bonus buy**. None are
  implemented, yet the object is named `tome_of_life`, reports RTP 97.838 %, and
  `validate_slots.py` gates the *Tome* paytable against it. `test_tome_of_life_shares_scarab_model`
  asserts the identity rather than flagging it.
- **Max-win caps** (Scarab/Tome 10,000×; Tome 40 BTC) and the 180-spin cap are not
  implemented; the engine's only limit is `_SAFETY_SPIN_CAP = 100_000`.
- **Cleopatra** (95.025 %, split 52.047/17.508/25.470, hit freq 11.36 %→35.88 %,
  relative SD 13.45→5.18 by lines bet) is a second fully-specified published model in the
  reference and the only one with published SDs to validate against. Not implemented, and
  no SD gate exists anywhere in the slots validator as a result.

---

## 6. Blind comparison

**Artifact A — the eight published Atkins figures, two unlabeled columns:**

| | column 1 | column 2 |
|---|---|---|
| total return | 97.046 % | 97.047 % |
| line pays | 63.460 % | 63.460 % |
| scatter pay | 6.976 % | 6.976 % |
| bonus feature | 26.610 % | 26.611 % |
| hit freq / line | 5.45 % | 5.45 % |
| P(3+ scatters) | 0.011185 | 0.011185 |
| E[spins / bonus] | 11.259335 | 11.259335 |
| E[bonus win] | 23.791632 | 23.791825 |

Three cells differ. Both columns happen to be internally self-consistent
(`63.460 + 6.976 + 26.611 = 97.047` too), so consistency does not separate them — but
the columns are *not identical*, and the reference's own text names 97.046 % / 26.610 % /
23.791632. Column 2 (ours) is identified as the imitation on sight. **Not a coin flip.**

**Artifact B — a reel-strip block, unlabeled, shown to a par-sheet reader:**

```
reel 1: 12 11  7 11  8 11  9 11 10 11  0  5  6  7  8  9 10 11  0  1  2  3  4  5  6  7  8  9 10 11
reel 2: 12 11  7 11  8 11  9 11 10 11  0  5  6  7  8  9 10 11  0  1  2  3  4  5  6  7  8  9 10 11
```

Two byte-identical reels, the scatter parked at index 0, and a 12-long ascending
`0,1,…,11` tail. Add the derived shape — wild carrying 51.6 % of base return, 79.8 % of
spins paying, SD 3.57 against a published slot-SD floor of 5.18 — and any expert
identifies this as generated, not a par sheet. **Ours gives itself away.**

---

## 7. Prioritized fix list

1. **(the one that matters)** Re-run the strip calibration for Atkins to land
   `B = line + scatter ∈ [0.7043527, 0.7043528]` (currently 0.7043585, +8.0 ppm) while
   holding `p_trigger ≈ 0.0111848`. That flips `bonus_return → 26.610 %`,
   `total_rtp → 97.046 %`, `E[bonus win] → 23.791632` simultaneously. Then **restore
   `WOO_ATKINS_TOL` to true half-ULP for all eight figures** and add a test that asserts
   the *printed strings* (`f"{100*rtp:.3f}" == "97.046"`), not a float tolerance.
2. Commit the calibration script under `scripts/` so the strips are reproducible, and
   add shape constraints to the search so the output can survive a blind par-sheet read:
   no duplicate reels, no monotone symbol runs, wild ≤ 2 per reel and absent from reel 1
   (or, for Scarab, modelled as Stake's published *random overlay* wilds rather than
   strip symbols), scatter positions varied, and a target SD inside the reference's
   published 5.18–13.45 band.
3. Re-derive Scarab's strips against a plausibility constraint set (per-line hit
   frequency ≈ 5–8 %, total hit frequency ≈ 30 %, wild contributing < 15 % of base
   return), then re-check that it still prints 97.84 %.
4. Model Tome of Life's published rules (wild-sub ×2, bonus ×3, 180-spin cap) or rename
   the object so it does not claim to be Tome of Life.
5. Add Blue Samurai (published paytable + 96.70 % + weighted reels + reels-2–4 scatters)
   and/or Cleopatra (the only published model with SDs, giving the validator its first
   real volatility gate). Implement the 10,000× max-win cap.
