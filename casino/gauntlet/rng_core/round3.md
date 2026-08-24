# rng_core — Round 3 adversarial review

**Verdict: DOES NOT WIN.** The seed-pair byte stream is flawless — I could not
break it. But the blind comparison is not a coin flip: **Dragon Tower gives ours
away as the imitation**, and it does so because ours consumes the wrong number of
floats per bet, which is a byte-stream divergence, not a cosmetic one.

Reviewed file: `/home/user/troyrhinehart/casino/spinquest_sim/rng.py`
Ground truth: `/home/user/troyrhinehart/casino/references/stake/core.md`,
`/home/user/troyrhinehart/casino/references/stake/crash.md`

## Method — I did not trust the builder's tests

I did not read or run `tests/test_rng.py` for evidence. Instead I transcribed
Stake's published JS **verbatim** into `ref.js` and **executed it under node
v22.22.2**, so the reference is the actual published program, not my paraphrase
of it. The only edits were the two that make Stake's snippet runnable at all:
`function byteGenerator` → `function*` (the published snippet `yield`s from a
non-generator — Stake's own bug), and `createHmac` imported / lodash `_.chunk`
replaced by a 3-line equivalent. Floats were compared as **IEEE-754 8-byte
big-endian hex**, so "match" means bit-identical, not `≈`.

Scratch artifacts: `.../scratchpad/r3/{ref.js,gen_vectors.js,compare.py,edge.js,bulk.py,stats.py}`

## What I could not break

| Check | Scope | Result |
|---|---|---|
| Bytes vs executed JS | 556 (seed, client, nonce, cursor) tuples × 70 bytes = **38,920 bytes** | 0 mismatches |
| Floats vs executed JS | 576 tuples × 20 floats = **11,520 floats**, bit-exact | 0 mismatches |
| Game mappings vs executed JS | 18 bets × 16 mappings = **288 events** | 0 mismatches |
| Edge cases vs executed JS | 38 cases: negative cursors (−1/−32/−33/−64), cursor 320,000, nonce 0/−7/2³¹/2³²/2⁵³, empty & unicode & colon-bearing client seeds, empty/65-char/emoji server seeds | 0 mismatches, 0 exceptions |
| `CARDS` index order | ♦2…♣A, suit-inner (♦♥♠♣), ranks 2→A, 52 entries | exact |
| Cursor-increment table | keno 2, mines 3, plinko 2, video poker 7, diamond poker 2, hilo/blackjack 13, six 1-increment games | exact |
| SHA-256 commitment | `sha256(utf8(seed_text))` | exact |
| Bulk == scalar | 47 checks: `float_matrix` widths 1,3,7,8,9,10,16,17,24,52,53,104 (incl. non-multiples of 8 and cross-digest reads); every game method; every `mine_count`; every wheel segment count | **bit-exact, 0 failures** |
| Parallel determinism | 500,000 bets `workers=1` vs `workers=4`; ragged 150,001×3 at `workers=3` | byte-identical |
| Nonce bookkeeping | contiguous, no reuse, no gaps; `size=0` is a no-op | correct |
| Fisher-Yates | pop-order (not swap-order) confirmed; 3-pool lattice enumeration → all 3! perms with exactly equal measure; 20k video-poker decks are true permutations of 0..51; 50k keno draws duplicate-free | correct |

Notably, **`BulkRng` is not a statistical twin** — it is the same stream. Row `i`
of every bulk call is bit-identical to the scalar helper at nonce `n0+i`. The KS
test the brief asked for is the weaker check here; exact equality passed instead.

### Empirical: 16,900,000 rounds, targets computed in closed form

Targets are exact lattice probabilities (e.g. `P(crash ≥ m) = (⌊99·2³²/100m⌋+1)/2³²`),
not "roughly 0.99", so the 3-SE test is a real test. **16/16 pass; worst |z| = 2.26.**

```
dice over-50.50 RTP      target 0.990000000  emp 0.989802970  3SE ±8.66e-04  z −0.68
limbo 1.5x / 2x / 10x / 100x RTP                                    z +0.27 +0.99 +0.41 +1.08
roulette straight-up     target 0.972972973  emp 0.969171000  3SE ±5.05e-03  z −2.26
roulette even-money      target 0.972972973  emp 0.973183000  3SE ±8.66e-04  z +0.73
wheel 10/low,med,high · 50/med,high (published tables)              z +1.77 −0.01 −0.69 +0.83 +0.60
keno P(square 1 drawn)   target 0.250000000  emp 0.249933000  3SE ±7.50e-04  z −0.27
mines P(tile 0 in first 3) target 0.120000000 emp 0.120412000 3SE ±7.96e-04  z +1.55
uniform float mean       target 0.499999999883                              z −1.22
```

Chi-square: dice 10,001 bins p=0.46; roulette 37 pockets p=0.41; keno square
marginals p=0.93 and per-draw-position (#1/#5/#10) p=0.77/0.87/0.32; mines
24-event marginals p=1.00; video-poker card #1/#26/#52 p=0.28/0.37/0.92.

One KS window came back p=0.0184 on the first seed. I chased it rather than
accepting it: on a second seed, 6 independent 2M windows gave Fisher-combined
p=0.714; all 32 bit positions of the 32-bit words are within |z|<3 (worst −2.30);
per-byte-position chi² p=0.64/0.22/0.92/0.009; lag-1 serial r = −1.5e-04 against
a 3SE of ±8.7e-04; max within-bet adjacent-float |r| = 1.4e-03 vs 3SE ±2.1e-03,
including across the 8-float digest boundary. **It was a fluke. The stream is clean.**

## Blind comparison — 15/17 identical, and the 2 tells are decisive

Two unlabeled columns, one from node-executed published JS, one from `rng.py`:

```
probe                   | column 1                                | column 2                  | tell?
bytes[0:8] cursor=0     | 149,252,89,75,55,191,182,22             | 149,252,89,75,55,191,182,22 |
bytes[0:8] cursor=33    | 21,198,12,63,121,93,3,109               | 21,198,12,63,121,93,3,109   |
float[0] (17 sig figs)  | 0.58588178711943328                     | 0.58588178711943328         |
card idx / name         | 30 ♠9                                   | 30 ♠9                       |
limbo crash             | 1.68                                    | 1.68                        |
keno 10 hits            | 24,9,11,36,7,1,5,12,13,15               | 24,9,11,36,7,1,5,12,13,15   |
video poker top 6       | 30,11,13,45,8,0                         | 30,11,13,45,8,0             |
scarab 5 stops          | 17,6,7,26,7                             | 17,6,7,26,7                 |
dice roll               | 58.59403752981452                       | 58.59                       | DIFFERS
dragon tower easy L0-L2 | [[0,1,3],[1,2,3],[0,2,3]]               | [[2,0,1],[3,0,1],[0,1,2]]   | DIFFERS
```
(9 further probes — cursor-32 floats, gem, roulette, wheel-50, plinko 16 dirs,
baccarat 6, mines first 5 — all identical; omitted for width.)

**Dice: this tell favours ours.** Column 1 is the verbatim snippet
`(float * 10001) / 100`, which is unfloored and can return 100.0099 — impossible
on a UI capped at 100.00 and inconsistent with the same page's own "10,001
outcomes" and its general floor rule. An expert picks column 2 as real Stake.
Ours is right; the doc snippet is another of the typos it already flags.

**Dragon Tower: this tell exposes ours, immediately.** Column 1's rows are all
sorted ascending and its first row is literally `[0,1,3]` — the doc's own worked
example. Column 2's rows are in draw order. Measured over 3,000 nonces × 9 rows:
ours produces a sorted row **16.6% of the time — exactly chance (1/6)**. The
reference form is sorted 100% of the time by construction. An expert reading
core.md L395 ("e.g. easy level `[0, 1, 3]` = eggs on tiles 1, 2 and 4") identifies
the reference on sight.

## The defect behind that tell

`dragon_tower_eggs` consumes `DRAGON_TOWER_ROWS * count` floats:

| difficulty | count/size | ours | doc | |
|---|---|---|---|---|
| easy | 3/4 | **27 floats (4 digests)** | 9 floats (2 digests) | ✗ 3× over |
| medium | 2/3 | **18 floats (3 digests)** | 9 floats (2 digests) | ✗ 2× over |
| hard | 1/2 | 9 | 9 | ✓ |
| expert | 1/3 | 9 | 9 | ✓ |
| master | 1/4 | 9 | 9 | ✓ |

core.md L393 states it explicitly: **"9 game events (one per tower level)."**
The structural evidence is overwhelming — `min(count, size−count) == 1` for **all
five** difficulties. That is not an accident: one float per level is enough for
every difficulty, because you draw the single *odd tile out* (the skull for
easy/medium, the egg for hard/expert/master) and the rest of the row follows.
That single reading explains all three published facts at once: the event count
of 9, the "no duplicate eggs per row" guarantee (free — there is only one draw),
and the sorted example `[0,1,3]` (the complement of one skull is always sorted).

Ours instead reads the prose "Fisher-Yates" literally and draws `count` eggs
sequentially, so for easy/medium **every level after level 0 reads the wrong
floats**, and the bet consumes 4 or 3 digests where a real Stake verifier reads 2.
A published-bet check would fail.

Why no test caught it: `dragon_tower` is absent from both `EVENT_COUNTS` and
`CURSOR_INCREMENTS`. The module's proudest safeguard — "this table is LIVE, the
helpers read their event counts from here, a test asserts the computed values
equal the doc's verbatim numbers" — simply does not cover Dragon Tower. Same
blind spot for `scarab_spin` and `blue_samurai` (also absent from both tables);
`blackjack`/`hilo`/`slots` are in `CURSOR_INCREMENTS` but not `EVENT_COUNTS`.

## Other gaps (ranked, not the headline)

2. **Crash's provable-fairness core is entirely absent.** `crash.md` publishes a
   complete, verifiable second scheme: a 10,000,000-link SHA-256 chain with
   terminating hash `78a9757d…`, the BTC block-584,500 salt
   `0000000000000000001b34dc…`, and
   `crashpoint = max(1, (2**32/(int+1)) * (1-0.01))`. `rng.py` has nothing —
   `grep` for chain/crash returns only `limbo_crash_point`. I implemented it in
   ~40 lines to confirm it is closeable: chain link property verified, and RTP at
   1.5×/2×/10× lands at z = +0.66/+0.22/+0.32 against exact targets. Defensible
   as out of scope for a module that declares "ONE byte stream", but then
   *something* must own it, and today nothing does.

3. **No seed-rotation / reveal API.** The doc's §0 commitment scheme is
   publish-hash → bet → rotate → reveal. `BulkRng` exposes `server_seed_hash` but
   has no `rotate()`, so the reveal half of the scheme is unmodelled.

4. **Bulk coverage is ~10 of 17 games.** No named `BulkRng` method for Baccarat,
   Diamond Poker, Dragon Tower, Scarab Spin, Blue Samurai, or multi-card
   Blackjack/Hilo hands. `float_matrix` is the only route, which pushes the
   event-budget decision into each game module — precisely the drift that
   produced defect #1.

5. **Cosmetic:** `card_name` returns `"♦2"` (suit-first) while the published
   `CARDS` literal reads `♦2` as one glyph pair — harmless, but the reference
   renders rank-agnostic suit-first too, so this one is fine as-is.

## The one change that most closes the distance

Rewrite `dragon_tower_eggs` to consume **exactly 9 floats — one per tower level** —
drawing the single minority tile with `floor(float * size)` and returning the row
as the sorted complement (or the singleton) accordingly; then add
`EVENT_COUNTS["dragon_tower"] = 9` and a `CURSOR_INCREMENTS` entry so the LIVE-table
discipline actually covers it, and backfill `scarab_spin` (5) and `blue_samurai`
(18/12) into the same tables. That removes the only probe in the blind test that
identifies ours as the imitation.
