# rng_polish — round 1 critique (independent, fresh-eyes)

Reviewer stance: harsh critic. I did **not** run or read `tests/test_rng.py` before
scoring, and I did not use the builder's `validate_rng_polish.py`. Ground truth is a
**fresh Node 22 execution of a from-scratch transcription of the JavaScript printed in
`references/stake/core.md`** (§1 `byteGenerator`, §2 `generateFloats`, §3 the card / gem /
Fisher-Yates mappings), written for this round without consulting `rng.py`. As a control I
also re-executed round 4's `ref.js` and confirmed it is byte-identical to the `ref.json`
that round 4 scored against, so the round-4 baseline is intact and the replay in §3 is a
true before/after.

Scope, as assigned: **only the delta** on top of the already-passed rng core —
(a) the new `BulkRng` per-bet card/gem methods, (b) the `draws_without_replacement`
pool-dtype fix, (c) no behavior change in the verified scalar path. No 10M-round
re-simulation of the core.

Artifacts (all re-runnable, prefix
`/tmp/claude-0/-home-user-troyrhinehart/b3ce270f-e608-55a6-8515-5735b66f4ebe/scratchpad/polish/`):

| file | what it does |
|---|---|
| `ref2.js` | independent published-JS transcription → per-**bet** vectors for baccarat / blackjack-hilo / diamonds / diamond poker + large-pool Fisher-Yates, 216 blocks |
| `d2case.js` | the documented baccarat nonce-900 case, isolated |
| `check_a.py` | 1,296 (seed, client, nonce) bets: bulk vs node, bulk vs scalar, scalar vs node, nonce accounting |
| `check_b.py` | `draws_without_replacement` overflow / dtype / distribution / memory |
| `check_c.py` | round-4 vectors replayed against the current `rng.py` |
| `check_stats.py` | 45.5M game events through the new methods, χ² vs exact lattice probabilities |
| `blind.py`, `blind.txt` | label-stripped side-by-side, randomized column assignment |

---

## 1. (a) New `BulkRng` per-bet card / gem methods

**216 blocks × 6 consecutive bets = 1,296 distinct (server seed, client seed, nonce)
tuples.** 6 server seeds (all-zero, all-`a`, all-`ff`, a mixed hex seed, `deadbeef`×8, a
byte-ramp) × 6 client seeds (`test`, empty, `spinquest`, `has:colons:in:it`,
`Ünïcøde:seed`, `100%%win`) × 6 nonce anchors (0, 1, 7, **900**, 12345, 999999).

| check | comparisons | mismatches |
|---|---|---|
| `BulkRng.baccarat_cards` vs node | 216 blocks | **0** |
| `BulkRng.baccarat_cards` vs scalar `baccarat_cards` | 1,296 bets | **0** |
| `BulkRng.card_hands(2 / 9 / 52 / 104)` vs node | 4 × 216 | **0** |
| `BulkRng.card_hands(9 / 104)` vs scalar `card_draws` | 2 × 1,296 | **0** |
| `BulkRng.diamonds_gems` vs node | 216 | **0** |
| `BulkRng.diamonds_gems` vs scalar (name-mapped) | 1,296 | **0** |
| `BulkRng.diamond_poker_hands` dealer / player vs node | 2 × 216 | **0** |
| `BulkRng.diamond_poker_hands` vs scalar (name-mapped) | 2 × 1,296 | **0** |
| `BulkRng.keno_hits` / `mines_positions(24)` vs node (these route through the *changed* `_fisher_yates_matrix`) | 2 × 216 | **0** |
| scalar `baccarat_cards` / `diamonds_gems` / `keno_hits` / `mines_positions` vs node (guards against a shared-bug tie) | 4 × 1,296 | **0** |
| **nonce accounting**: `nonce_next` and `last_nonce_range` after every method | 7 methods × 216 | **0 wrong** |

`CARDS` and `GEMS` index order were re-derived from the published literals and match
index-for-index.

### The documented baccarat nonce-900 case

Round 4's D2 headline, re-derived from Node, not from `rng.py`:

```
seed 4d6a5e…5c4d, client "bac", nonce 900
node  generateFloats(count=6) -> floor(f*52)   : [18, 30, 7, 51, 41, 13]
scalar baccarat_cards(...,900)                 : [18, 30, 7, 51, 41, 13]
BulkRng.baccarat_cards(1)[0]                   : [18, 30, 7, 51, 41, 13]   nonces (900, 901)
card names                                     : ♠6 ♠9 ♣3 ♣A ♥Q ♥5
legacy BulkRng.cards(6)                        : [18, 38, 12, 13, 12, 46]  nonces (900, 906)
node one-nonce-per-card shape                  : [18, 38, 12, 13, 12, 46]
```

The coup now comes from **one nonce**, and 8 consecutive coups (nonces 900–907) are
element-identical to the Node stream. `cards()` / `gems()` still exist but now emit
`DeprecationWarning` and are documented as the trap they are; nothing in `spinquest_sim/`,
`scripts/` or `tests/` calls them, so the deprecation breaks nothing.

**Hostile probes on the delta, all clean:**

- `_CHUNK_FLOAT_BUDGET = 13` (deliberately ragged chunks): `baccarat_cards`,
  `diamonds_gems`, `diamond_poker_hands`, `card_hands(104)` all byte-identical to the
  default budget.
- `_PARALLEL_MIN_DIGESTS = 5`, `workers=4` (forced process fan-out): identical to serial.
- `card_hands(n)` for n ∈ {1, 7, 8, 9, 32, 52, 104, 105, 200} — spanning 1, 2, 4, 7, 13,
  14 and 25 digests, i.e. crossing the digest boundary at every awkward place — every row
  equals scalar `card_draws`, and every call consumes exactly `size` nonces.
- `card_hands(0 / -1, …)` and negative `size` raise `ValueError` rather than returning
  something plausible.
- Digest budgets: `digests_for_events` gives 6→1, 5→1, 10→2, 52→7, 104→13, matching the
  published cursor table, and `float_matrix(1, 104)` is bit-equal to
  `generate_floats(..., 104)` — the 13-digest hilo/blackjack reservation is addressable
  from the bulk path.

**Verdict on (a): pass, without qualification.**

## 2. (b) `draws_without_replacement` — overflow fixed, but the fix's own safety claim is false

### Correctness: fixed

```
BulkRng(...).draws_without_replacement(40000, 2, 3)
 -> [[2590, 33904], [32229, 23017], [5441, 13296]]     dtype int64, no negatives
```

Row-identity against the Node Fisher-Yates at **12 pool/draw shapes** — pools 1, 2, 3,
256, 257, 32767, **32768**, 40000, 65535-crossing 65536, 70000, 100000 (96 rows total):
**0 mismatches**, every row in `[0, pool)`, every row distinct. Independently, 400 rows at
pool 40000 draws 4 match the scalar `fisher_yates_draws` exactly. The dtype ladder is
right at every boundary: pool 256 → `uint8`, 257 → `uint16`, 65536 → `uint16`,
70000 → `uint32`. All Stake game pools (25, 40, 52) land on `uint8`, which is *half* the
old `int16` footprint, and their outputs are unchanged (§1). A `float` `pool_size` raises
`TypeError` rather than silently picking `float16`, so that adjacent hazard is unreachable.

Distribution at a post-`int16` pool — 200,000 rows × 3 draws from a pool of 40,000,
bucketed into 40 equal ranges and scored against the **exact `k/2**32` lattice
probabilities**, not `1/M`:

| statistic | value |
|---|---|
| column 0 χ²(39) | 35.23, p = 0.643, max \|z\| = 1.95 |
| column 1 χ²(39) | 19.42, p = 0.996, max \|z\| = 1.43 |
| rows with a repeat, or index outside `[0, 40000)` | 0 |

### D1 (real, in the changed code): the chunker ignores `pool_size`, so the "safe for any pool size" comment is false

`_fisher_yates_matrix` materializes a `(size, pool_size)` pool matrix and then, per draw,
builds a `(size, n_rem)` boolean mask plus two `(size, n_rem)` slices for the `np.where`.
Working set is therefore **O(size × pool_size)**. But `draws_without_replacement` chunks
via `self._chunks(size, draw_count)`, whose budget is `_CHUNK_FLOAT_BUDGET // draw_count`
— `draw_count` is the *float* count, and `pool_size` never enters. For `pool_size = 40000,
draw_count = 2` the chunk is `8_000_000 // 2 = 4,000,000` rows, i.e. a 160 GB pool matrix
before any temporaries.

Measured on this container (16 GB):

| call | pool matrix | max RSS |
|---|---|---|
| `draws_without_replacement(40000, 2, 200)` | 16 MB | 68 MB |
| `draws_without_replacement(40000, 2, 1_000)` | 80 MB | 243 MB |
| `draws_without_replacement(40000, 2, 5_000)` | 400 MB | **1.01 GB** |
| `draws_without_replacement(40000, 2, 20_000)` | 1.6 GB | **3.87 GB** |
| `draws_without_replacement(40000, 2, 60_000)` | 4.8 GB | **11.5 GB**, 48 s |
| `draws_without_replacement(40000, 2, 200_000)` | 16 GB | thrashed, 82 s of ~100 % system time, no result |

The RSS is ~2.4× the pool matrix because of the `keep` mask and the two `np.where`
operands. It also runs at ~4,200 rows/s at that pool size (200,000 rows took 48 s even
when hand-chunked to 2,000 rows per call), versus millions/s for the pool-40 games.

Why this is in scope rather than a pre-existing gripe: the delta's own comment asserts
the opposite.

```python
# No Stake game exceeds a pool of 52, so the game methods stay on
# uint8 (same memory as before); the generic helper is now safe for
# any pool size.
```

It is safe for any pool size *in the answers it returns* and unusable above a pool of a
few thousand *for any realistic `size`*. Round 4 accepted D1 as a landmine specifically
because a generic public helper should not mislead the game modules built on top of it;
this replaces "returns negative indices" with "silently allocates 160 GB", and stamps a
safety claim on it. It also breaks the class docstring's promise —
"Large calls are chunked internally (arrays stay well under 500 MB)" — and the project's
own `<500 MB` chunking rule, both of which now hold only for `pool_size ≤ ~50`.

Fix is small and local: budget the chunk on pool *cells*, not floats, e.g.

```python
chunk = max(1, min(_CHUNK_FLOAT_BUDGET // draw_count,
                   _POOL_CELL_BUDGET // max(1, pool_size)))
```

with `_POOL_CELL_BUDGET ≈ 5e7` (≈ 100 MB of `uint16` pool + temporaries), threaded into
`_chunks` as an extra bound. `keno_hits`, `mines_positions` and `video_poker_decks` would
be untouched at pools 40 / 25 / 52.

**Verdict on (b): the assigned check ("no longer overflow, no negative indices,
distribution correct") passes. The method is nonetheless not fit for the use its own
comment now advertises.**

### D2 (minor, API): same method name, different return type across the two paths

```
scalar diamonds_gems(...)        -> ['green', 'blue', 'green', 'red', 'red']   (names)
BulkRng.diamonds_gems(1)         -> [[0 6 0 3 3]]                              (indices)
scalar diamond_poker_hands(...)  -> (names, names)
BulkRng.diamond_poker_hands(1)   -> (index array, index array)
```

`baccarat_cards` and `card_hands` are consistent (indices on both sides); the two gem
methods are not. Both are documented, and both are correct — but the whole point of this
delta was to remove same-name/different-shape traps from `BulkRng`, and it left two
behind. Either return indices from the scalar helpers (with a `gems_from_floats`-style
name mapper for display) or hand back names on both sides.

### D3 (real, and the reason the delta does not yet pay for itself): nothing uses the new methods

The methods exist; no caller adopted them.

- `spinquest_sim/games/baccarat.py:404` — `floats = rng.float_matrix(n_rounds, EVENTS_PER_ROUND)`
  then `np.floor(floats2d * _DECK)` at line 361.
- `spinquest_sim/games/blackjack.py:910` — `fm = rng.float_matrix(step, float_budget)`
  then `np.floor(fm * _DECK)`, with `float_budget` a local parameter guarded only by
  `if float_budget < 6`, i.e. re-deciding the event budget outside `EVENT_COUNTS`.

Round 4's D2 asked for these methods *because* every game module was hand-rolling
`float_matrix` + `floor(f*52)` and re-deciding its own float budget — the drift that
produced round 3's Dragon Tower defect. Adding the method without wiring the two in-scope
lobby games onto it leaves that drift exactly where it was; `EVENT_COUNTS` is still not
the single source of truth for blackjack. (Arguably a `baccarat` / `blackjack` piece owns
the change, but the delta's stated purpose is unfulfilled until it happens.)

## 3. (c) The verified scalar path did not change

Round 4's nine (serverSeed, clientSeed, nonce, cursor) vectors — including mid-digest
cursor 7, unaligned cursor 100, cursor 416 (the 13-digest reservation), empty client seed,
a client seed containing `:`, a non-ASCII client seed and nonce 999,999 — replayed against
the **current** `rng.py`, with the Node reference regenerated live:

| check | comparisons | mismatches |
|---|---|---|
| `generate_bytes`, 96 bytes/vector | 9 vectors / 864 bytes | **0** |
| `generate_floats`, compared as **float64 bit patterns** | 9 × 24 | **0** |
| card names (52-entry published order) | 9 × 24 | **0** |
| gem names | 9 × 24 | **0** |
| limbo crash points (published operation order) | 9 × 24 | **0** |
| roulette pockets, plinko directions | 2 × 9 × 24 | **0** |
| dice (floored — the §5 deliberate divergence, unchanged) | 9 × 24 | **0** |
| `keno_hits`, `mines_positions(24)`, `video_poker_deck`, VP card names | 4 × 9 | **0** |
| `hash_server_seed` vs node `createHash` | 3 | **0** |
| **TOTAL** | | **0** |

Published tables are byte-identical to round 4: `CURSOR_INCREMENTS` (dice/limbo/wheel/
baccarat/roulette/diamonds 1; keno 2, plinko 2, diamond poker 2, mines 3, video poker 7,
dragon tower 2, scarab 1, blue samurai 3/2; **hilo/blackjack 13**; slots `None`),
`EVENT_COUNTS`, `DRAGON_TOWER_LEVEL_MAP`, `SCARAB_SPIN_REELS`. `digests_for_events` still
yields 1/1/2/2/3/7/13 for 1/6/10/16/24/52/104. The builder's own suite runs clean
(150 passed in 2.7 s) — reported for completeness, not relied on.

**Verdict on (c): pass. Nothing in the verified path moved.**

## 4. Empirical statistics on the new methods

45,500,000 game events over 6,500,000 bets/nonces, 11 s wall clock, peak RSS 380 MB,
χ² against **exact `k/2**32` lattice probabilities** (2³² is divisible by neither 52 nor 7,
so `1/M` would be the wrong null):

| statistic | measured |
|---|---|
| `baccarat_cards`, 2,000,000 coups = 12M card events; card index χ²(51) | 55.10, p = 0.322, max \|z\| = 2.88 |
| … per coup position 0–5, χ²(51) each | 56.07 / 59.54 / 57.90 / 59.53 / 47.87 / 50.43 — p from 0.19 to 0.60 |
| card 0 × card 1 independence within a coup, χ²(2601) | 2561.5, p = 0.706 |
| `card_hands(9)`, 1,500,000 bets = 13.5M events; card index χ²(51) | 53.71, p = 0.371, max \|z\| = 2.92 |
| `diamonds_gems`, 2,000,000 bets = 10M gem events; χ²(6) | 21.46, p = 0.0015, max \|z\| = 3.05 — **see below** |
| … per position 0–4, χ²(6) | p = 0.289 / 0.799 / 0.011 / 0.301 / 0.227 |
| `diamond_poker_hands`, 1,000,000 bets; dealer χ²(6) / player χ²(6) | 1.42 (p = 0.965) / 3.46 (p = 0.749) |
| nonces consumed vs bets, all four methods | exactly 1:1 |

The one flag above 3 SE is the pooled gem χ² on a single seed. It is noise and I confirmed
it rather than waving it off: on the same seed at 40M events it decays to χ²(6) = 12.50,
p = 0.052, max \|z\| = 2.56 (a real bias grows in z, it does not shrink), and on two other
seeds at 10M events each it is p = 0.869 and p = 0.520. It also **cannot** be "our" bias:
the bulk gem stream is bit-identical to the Node transcription over all 1,296 bets in §1,
so any distributional quirk belongs to HMAC-SHA256, not to this module.

## 5. Blind comparison

`blind.txt` renders 6 blocks × 9 field types × 3 bets as two unlabeled columns with
independently randomized left/right assignment per block — baccarat coups (indices and
card names), 9-card blackjack hands, the tail of a 104-card hilo reservation, diamonds gem
names, diamond poker dealer/player halves, keno, mines, and large-pool
`draws_without_replacement` at pools 40,000 and 100,000.

**Rows where LEFT ≠ RIGHT: 0**, out of ~165 rendered cells. There is no dice column in
this delta, so the single blind-detectable cell from round 4 does not even appear. An
expert asked "which column is the imitation?" has nothing to go on: it is a pure coin
flip, and the key at the bottom of `blind.txt` is the only way to tell.

## 6. Verdict

On **reference fidelity the delta is flawless**. Every claim I was asked to test holds:
the four new per-bet card/gem methods are row-wise identical to both the scalar API and an
independent Node execution of Stake's published code across 1,296 (seed, nonce) tuples,
including the documented baccarat nonce-900 coup, at exactly one nonce per bet, under
ragged chunking and forced parallel fan-out; the `int16` overflow is genuinely gone with
correct distributions up to a pool of 100,000; and not one bit of the round-4-verified
scalar path moved. The blind comparison is a coin flip with zero differing cells.

I am still scoring this **not a win**, because a check I ran on the delta's own code
fails: `draws_without_replacement` swapped a wrong-answer bug for an unbounded-memory bug
and shipped a comment asserting it is "safe for any pool size", when the same call that
motivated the fix OOMs the container at `size = 200_000` and blows the module's own
documented 500 MB budget by 20× at `size = 20_000`. A public helper that misstates its own
safety envelope is the same class of landmine round 4 flagged, moved one step down the
call stack. Secondary: two gem methods still return different types on the scalar and bulk
paths, and neither in-scope lobby game (baccarat, blackjack) was wired onto the new
methods, so the event-budget drift these methods were built to prevent is still live in
`blackjack.py:910`.

### The one change that most closes the remaining distance

**Make `draws_without_replacement`'s chunking a function of `pool_size`, not just
`draw_count`** — bound the per-chunk pool matrix (`size × pool_size` cells, plus ~1.4×
for the `np.where` temporaries) to a fixed cell budget of roughly 5 × 10⁷, take the
minimum of that and the existing float budget, and delete or correct the
"safe for any pool size" comment. That restores the class's own "arrays stay well under
500 MB" guarantee for the generic helper, leaves keno / mines / video poker byte-identical
(pools of 40 / 25 / 52 never bind), and is the only place in this delta where the shipped
code does something a reader of it would not predict.
