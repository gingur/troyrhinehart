# rng_core — round 4 critique (independent, fresh-eyes)

Reviewer stance: harsh critic. I did **not** run `tests/test_rng.py` or trust any claim
in `rng.py`'s docstrings. Ground truth for this round is a **Node 22 execution of the
verbatim JavaScript printed in `references/stake/core.md`** — transcribed by me, edits
limited to `function*` (the page prints `function` while the body yields), `require('crypto')`,
and a 12-line local `_.chunk` (lodash is not installed). Second, independent ground truth:
a from-scratch Python transcription of the same pseudocode used to re-derive 1.2M floats.

Artifacts (all re-runnable):

| file | what it does |
|---|---|
| `…/scratchpad/rngcheck/ref.js` | verbatim published JS → 9 test vectors as JSON |
| `…/scratchpad/rngcheck/cmp.py` | byte/float/mapping diff, ours vs node |
| `…/scratchpad/rngcheck/bulk_check.py` | bulk↔scalar identity, chunking, parallel, cursor table, edge floats |
| `…/scratchpad/rngcheck/stats.py` | 12M-round campaign + 1.2M-sample exact match |
| `…/scratchpad/rngcheck/edge.py` | hostile seeds/nonces, 13-digest reservation, bulk API coverage |
| `…/scratchpad/rngcheck/blind.py`, `blind.txt` | label-stripped side-by-side |

(Full path prefix: `/tmp/claude-0/-home-user-troyrhinehart/b3ce270f-e608-55a6-8515-5735b66f4ebe/scratchpad/rngcheck/`)

Two bugs surfaced during the run were **mine, not theirs** (a JS `map` arity bug feeding
the array index into `houseEdge`, and a harness that re-called a bulk method inside a
comprehension and so burned fresh nonces per iteration). Both fixed before scoring; I
mention them because the first one is exactly the kind of error that would have produced
a false "ours diverges on limbo" headline.

---

## 1. Byte-for-byte / float-for-float vs the published JS

9 (serverSeed, clientSeed, nonce, cursor) tuples, deliberately including the awkward ones:
mid-digest cursor 7, unaligned cursor 100 (round 3, byte 4), cursor 416 (round 13 —
the blackjack/hilo reservation), empty client seed, a client seed containing `:`
(collides with the message delimiter), a non-ASCII client seed, and nonce 999,999.

| check | cells compared | mismatches |
|---|---|---|
| raw bytes (`generate_bytes`, 96 per tuple) | 864 | **0** |
| floats, compared as **float64 bit patterns**, not decimals | 216 | **0** |
| card index → `CARDS` name (52-entry published order) | 216 | **0** |
| gem index → `GEMS` (7 entries) | 216 | **0** |
| limbo crash point (published op order) | 216 | **0** |
| roulette pocket (×37) | 216 | **0** |
| plinko direction (×2) | 216 | **0** |
| keno Fisher-Yates (10 from 40, squares 1..40) | 90 | **0** |
| mines Fisher-Yates (24 from 25) | 216 | **0** |
| video poker Fisher-Yates (52 from 52) + card names | 936 | **0** |
| seed-level helpers (`keno_hits`, `mines_positions`, `video_poker_deck`, `baccarat_cards`, `diamonds_gems`, `diamond_poker_hands`) | 6 tuples × 6 helpers | **0** |
| SHA-256 seed commitment vs node `createHash` | 3 | **0** |
| dice (`floor(f*10001)/100`) vs the page's **unfloored** `(f*10001)/100` | 216 | 216 — see §5 |

Notes on things that could have gone wrong and didn't:

- **HMAC key encoding.** Node's `createHmac('sha256', str)` uses UTF-8 of the string;
  ours does `server_seed.encode("utf-8")`. Matches, including for a non-hex seed.
- **Mid-digest cursor.** The published loop resumes at `cursor − 32·⌊cursor/32⌋` and
  4-byte float chunking starts *from the cursor*, not from a digest boundary. Cursor 7
  and 100 both reproduce exactly, so the chunk phase is right.
- **`CARDS` order.** Published literal is rank-major with suits ♦♥♠♣ inside each rank;
  ours builds `[f"{suit}{rank}" for rank in RANKS for suit in SUITS]`. Index-for-index
  identical to my independent transcription for all 52 entries (♦2 → ♣A).
- **Limbo operation order.** `1e8 / (f*1e8) * houseEdge`, not `houseEdge / f`. Ours keeps
  the published order; node agrees on every float including the ULP-sensitive lattice
  points. `f == 0` → `inf` in both (JS `Infinity`).
- **Fisher-Yates is pop-order, not swap-order.** Node `splice` vs Python `pop` agree on
  all 9 tuples; the vectorized version agrees too (§3).

## 2. Cursor / round increments vs the doc table

`CURSOR_INCREMENTS` reproduces the published list exactly — dice/limbo/wheel/baccarat/
roulette/diamonds = 1; keno 2, plinko 2, diamond poker 2, mines 3, video poker 7;
hilo/blackjack 13 (the doc's reservation); slots `None` ("only utilised for bonus rounds").
More importantly the numbers are not decorative: I checked the **bytes the code actually
consumes** (`ceil(events·4/32)`) against the table for every game and they agree, and
`float_matrix(size, 104)` (the 13-digest reservation depth) is bit-equal to the scalar
path. Dragon Tower — round 3's headline defect — is now 9 floats / 2 digests, one float
per level, and both paths agree for all five difficulties. **That defect is closed.**

## 3. Bulk path vs scalar path

The task allows "KS test or exact match of discretized events, 1M+ samples". I did the
stronger one:

- **1,200,000 floats**, `BulkRng.floats()` vs a from-scratch Python transcription of the
  published pseudocode (no import of `rng.py` in the reference): **0 mismatches**,
  bit-exact. Every float lies exactly on the `k/2**32` lattice.
- Row-level equality with the scalar helpers on 400 bets each for dice, limbo, roulette,
  cards, gems, wheel(30), plinko rows 8/9/12/16, keno, mines(1/3/24), dragon tower
  (5 difficulties), scarab; 150 bets for video poker: **all equal**.
- **Chunk boundaries:** forcing `_CHUNK_FLOAT_BUDGET = 37` (many ragged chunks) leaves
  rows unchanged for `float_matrix`, `keno_hits`, `mines_positions`.
- **Parallel path:** forcing `_PARALLEL_MIN_DIGESTS = 10` so 4 processes fan out —
  byte-identical to `workers=1`.
- **Hostile inputs through the bulk path:** client seeds `'100%%win'`, `'%s%d'` (no
  format-string injection — `%` binds tighter than `+`, so the seed prefix is never a
  format target), `''`, `'a:b:c'`, 300 chars, non-ASCII; nonces `0, 7, −5, 2**53+3` —
  all bulk == scalar.
- **Vectorized Fisher-Yates stress:** 11,300 random rows across pools (25,24), (40,10),
  (52,52), (4,3), (2,2), with rows pinned to the adversarial floats `0.0`, `1−2⁻³²`,
  `0.5`, and alternating extremes: **0 mismatches** vs the scalar pop implementation.
- Nonce-type guard rejects `float`/`bool`/`str`/`np.float64` and accepts `np.int64`
  (a `7.0` nonce would render as `"7.0"` in Python but `"7"` in JS — silently forked
  stream; the guard is correct and worth keeping).

**One real bug found here** — see §4.

## 4. Defects found

### D1 (real, low reach): `int16` pool silently corrupts `draws_without_replacement` above 32767

`_fisher_yates_matrix` hardcodes `np.arange(pool_size, dtype=np.int16)`. The public,
documented method `draws_without_replacement(pool_size, draw_count, size)` promises
"distinct indices in `[0, pool_size)`" and guards only `draw_count > pool_size`:

```
BulkRng(...).draws_without_replacement(40000, 2, 3)
 -> [[ 15297  26229]
     [-32102  22657]     # negative indices; silently wrong, no exception
     [ 22790 -32502]]
```

No Stake game has a pool above 52, so no game method can reach it — but a generic helper
that returns negative "indices" without raising is a landmine for the game modules that
will be written on top. One-line fix: pick the dtype from `pool_size`
(`np.min_scalar_type(pool_size - 1)` or simply `np.int32`).

### D2 (design, in-scope games): no bulk path for multi-event card/gem bets

`EVENT_COUNTS` declares baccarat 6, diamonds 5, diamond poker 10, blue samurai 18/12, and
the scalar API implements all of them. `BulkRng` has **no method for any of them**, and
the names that look right are traps:

```
scalar baccarat_cards(nonce=900)  : [18, 30, 7, 51, 41, 13]   # 1 nonce, 6 cards
BulkRng.cards(6)                  : [18, 38, 12, 13, 12, 46]  # 6 nonces, 6 bets
nonces consumed by BulkRng.cards(6): (900, 906)
```

`BulkRng.cards()`/`gems()` model *one card per bet* — a bet shape no Stake game has.
`float_matrix(size, 6)` + `floor(f*52)` reproduces the coup exactly (verified), but that
pushes the event-budget decision back into every game module — precisely the drift that
produced round 3's Dragon Tower defect, and the module's own "this table is LIVE, every
BulkRng game method reads its event count from here" discipline is vacuous for these four
games because no bulk method exists to read it. Per `references/lobby.md`, **Blackjack and
Baccarat are in-scope lobby games** (Dice, Limbo, HiLo, Diamonds, Dragon Tower are not),
so this gap sits on the critical path and the well-covered games do not.

### D3 (API ambiguity, unfixed from earlier rounds): `cursor` means two things, and the
game helpers only expose the dangerous one

`byte_generator`/`generate_bytes`/`generate_floats` take `cursor` as a **byte offset**
(matching the published code) and offer `round_index=` as the unambiguous digest-index
escape hatch. But `keno_hits`, `mines_positions`, `video_poker_deck`, `card_draws`,
`baccarat_cards`, `diamonds_gems`, `diamond_poker_hands`, `dragon_tower_eggs`,
`scarab_spin` all take a bare positional `cursor` with no `round_index` and no warning.
A verifier who read the doc's *prose* ("cursor … increments by 1 each time 32 bytes are
consumed") and passes `cursor=1` gets bytes 1..32 of the **first** digest — silently wrong,
no error. Either accept `round_index` on these too, or reject non-zero non-multiple-of-32
cursors there.

### D4 (unowned, arguably out of scope): the crash hash-chain scheme still has no home

`core.md` explicitly excludes Crash/Slide from this scheme, so `rng.py` is defensible —
but `references/stake/crash.md` publishes a complete second scheme (10M-link SHA-256
chain, terminating hash, BTC block-584,500 salt, `HMAC_SHA256(key=gameHash, msg=blockHash)`
→ first 8 hex → crash point) and Crash is in-scope game #3 in `lobby.md`. Nothing in the
repo implements it. Flagged in round 3, still open; if a `crash_rng` piece owns it, fine.

### D5 (not a defect, verified): perf and memory claims are honest

Docstring claims ~0.43M digests/s serial and 1.0–1.7M parallel, peaks under 500 MB.
Measured on this container: **0.40M/s serial, 1.03M/s parallel**, peak RSS **406 MB** for
`keno_hits(1_000_000)` (10M floats) and for `video_poker_decks(150_000)`. No inflation.

## 5. The one deliberate divergence: dice

The page prints `const roll = (float * 10001) / 100;` with no floor; ours floors. The same
page's prose says "Range 00.00–100.00 → 10,001 outcomes", the general rule two sections
earlier is "multiply by the number of possible outcomes, **floor** to an index", and real
Stake dice results are two-decimal. Unfloored, `f = 0.7518987592775375` yields
`75.19739491534652`, which is not a value any dice game can display and does not partition
into 10,001 outcomes. Ours is right; the page has a typo, consistent with the four other
typos `core.md` already flags `[sic]` (`CARDS` for `DIRECTIONS`, `count1`, the unfloored
Wheel index, "curser"/"fullfilled"). I am scoring this as **ours favored**, not as a
mismatch — but it is the single blind-detectable cell, so it deserves the paragraph.

Empirically it is also the only reading that survives: 12M rolls produced exactly **10,001
distinct values**, mean 49.99949 (target 50.00000).

## 6. Empirical statistics — 12,000,000 rounds (+ 6.2M more for the FY games)

12M single-float bets, nonces 10,000,000–22,000,000, one nonce per bet, 11.7 s.

| statistic | measured | target | deviation |
|---|---|---|---|
| KS vs U(0,1), n = 2M | D = 5.010e-4, p = 0.697 | — | pass |
| roulette 37-pocket χ², df 36 | 49.11, p = 0.071 | — | pass |
| **roulette straight-up RTP** (36×) | 0.974304 | 0.972973 (36/37) | **+0.79 SE** |
| **dice "over 49.50" RTP** @ 1.9606× | 0.989935 | 0.990000 | **−0.23 SE** |
| dice win rate | 0.504916 | 0.504950 (5050/10001) | −0.23 SE |
| **limbo 2× cash-out RTP** | 0.990068 | 0.990000 | **+0.24 SE** |
| **limbo 10× cash-out RTP** | 0.988683 | 0.990000 | **−1.53 SE** |
| **limbo 100× cash-out RTP** | 0.989925 | 0.990000 | **−0.03 SE** |
| card index χ² (52), df 51 | 63.07, p = 0.120 | — | pass (worst cell z = 3.26) |
| keno square marginals χ² (2M rounds), df 39 | 33.21, p = 0.730 | 10/40 each | max z = 2.33 |
| keno draw-1 χ² vs exact lattice probs, df 39 | 47.82, p = 0.157 | — | pass |
| keno draw-2 χ² (uniform 1/40 under FY), df 39 | 41.75, p = 0.352 | — | pass |
| keno catch-count vs hypergeometric(40,10,10), df 8 | 8.69, p = 0.369 | — | pass |
| mines 3-mine tile marginals χ² (2M), df 24 | 14.02, p = 0.946 | 3/25 each | max z = 2.17 |
| **mines 1-mine single-reveal RTP** | 0.990093 | 0.990000 | **+0.65 SE** |
| plinko-16 bucket χ² vs Binomial(16, ½) (2M drops) | 16.50, p = 0.419 | — | pass |
| plinko per-row bias, max abs z over 16 rows | 1.65 | 0 | pass |
| plinko max abs row-row correlation | 0.00169 | 3 SE = 0.00212 | pass |
| video poker first-card χ² (200k), df 51 | 58.55, p = 0.218 | — | pass |
| video poker last-card χ², df 51 | 36.04, p = 0.944 | — | pass |

Structural invariants over the same runs: every keno row has 10 distinct squares in 1..40;
every mines row distinct; every video poker deck is a true permutation of 0..51; every
float on the `k/2**32` lattice; limbo `P(crash == 1.00) = 0.0199`, which is the correct
value for `max(⌊0.99/f·100⌋/100, 1)` (both the clamp and the 1.00–1.01 floor bucket), not
the naive 0.01.

Expected-probability caveat handled honestly: because 2³² is not divisible by 37, 52, 40 or
10001, the per-outcome probabilities are **not** exactly uniform. All χ² above use the
**exact lattice probabilities** `(⌈(i+1)·2³²/M⌉ − ⌈i·2³²/M⌉)/2³²`, not `1/M`, wherever the
mapping is a direct floor. The worst single cell anywhere is the 3.26 z on one of 52 card
indices; family-wise that is p ≈ 0.06 across 52 cells, and the block χ² is p = 0.12 — noise,
not bias, and it reproduces in the node implementation (same stream) so it cannot be
"our" bias.

Total sim cost: 12M + 2M keno + 2M mines + 2M plinko + 200k video poker ≈ 18.2M bets in
62.5 s wall clock; arrays chunked, peak RSS 406 MB.

## 7. Blind comparison

`blind.txt` renders 5 vectors × 12 field types as two unlabeled columns with independently
randomized left/right assignment per block. Result: **59 of 60 cell types are
character-identical** — bytes, float64 bit patterns, card names, gems, limbo, roulette,
keno, mines, video poker. Nothing in those cells can identify either column.

One cell type differs (dice, §5) and one is a formatting artifact of JSON vs Python
(`1` vs `1.0` for a clamped limbo point — numerically equal; `cmp.py` compares numerically
and passes). An expert asked "which is the imitation?" on the dice row would pick the
column printing `75.19739491534652`, because no dice game displays 14 significant figures —
i.e. the tell points at the **verbatim page transcription**, not at ours. Every other cell
is a coin flip.

## 8. Verdict

**Ours wins on the stated bar.** Everything the reference specifies reproduces exactly:
0 byte mismatches across 864 bytes and 9 input tuples, 0 bit-mismatches across 216 floats
and 1.2M bulk-path floats, correct pop-order Fisher-Yates, correct card/gem/pocket order,
correct published cursor table including the 13-digest reservation, correct SHA-256
commitment. 18.2M simulated rounds put every targeted RTP inside 1.6 SE (worst: limbo 10×
at −1.53 SE; every other headline RTP inside 0.8 SE), and the blind comparison is a coin
flip except for one cell that favors ours.

Round 3's headline defect (Dragon Tower reading `count` floats per level) is fixed and
verified from both directions.

### The one change that most closes the remaining distance

**Give `BulkRng` per-bet methods for the multi-event card/gem games — `baccarat_cards`,
`card_hands(cards_per_bet)` for Blackjack/Hilo, `diamonds_gems`, `diamond_poker_hands` —
each reading its budget from `EVENT_COUNTS` and consuming exactly one nonce per bet, and
rename or deprecate `cards()`/`gems()` (today they burn one nonce per card, a bet shape
Stake does not have).** Blackjack and Baccarat are in-scope lobby games with no vectorized
route today, so every game module built next must hand-roll `float_matrix` + `floor(f*52)`
and re-decide the event budget — exactly the drift that produced the round-3 defect. Fold
in the `int16` dtype fix (D1) while touching that file; it is one line.
