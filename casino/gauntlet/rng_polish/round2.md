# rng_polish — round 2 critique (independent, fresh-eyes)

Reviewer stance: harsh critic. I did not read or run `tests/test_rng.py` before scoring,
did not use the builder's `validate_rng_polish.py` / `validate_r5.py`, and did not reuse
round 1's or round 4's artifacts. Ground truth for this round is a **from-scratch Node 22
transcription of the JavaScript printed in `references/stake/core.md`**, written for this
round without opening `rng.py` (§1 `byteGenerator`, §2 `generateFloats`, §3 the
`CARDS` / `GEMS` / Fisher-Yates mappings). The only edits to the printed code are the
three the page forces: `function` → `function*` (the body yields), `createHmac` from
`node:crypto`, and a 4-line local replacing lodash `_.chunk`.

Scope, as assigned — **only the delta** on the passed rng core: (a) the `BulkRng` per-bet
card/gem methods, (b) `draws_without_replacement` overflow, (c) no movement in the
verified scalar path. No 10M-round re-simulation of the core was required; I ran one
anyway on the delta's own methods because the verdict rules ask for it.

Artifacts (all re-runnable, prefix
`/tmp/claude-0/-home-user-troyrhinehart/b3ce270f-e608-55a6-8515-5735b66f4ebe/scratchpad/p2/`):

| file | what it does |
|---|---|
| `ref.js` → `ref.json` | independent published-JS transcription → 343 per-bet blocks, 9 scalar vectors, 108 large-pool Fisher-Yates vectors |
| `check.py` | 231,743 comparisons: bulk vs node, bulk vs scalar, scalar vs node, nonce accounting, ragged chunking, forced parallel |
| `fuzz.py` | 400 random (seed, client, nonce) trials × 22 bulk methods, 17,515 row comparisons |
| `boundary.py` | rows straddling the REAL chunk boundaries at default budgets, incl. the new pool-cell boundary |
| `mem.py` | peak-RSS / throughput sweep across pool sizes 40 → 200,000,000 |
| `edge.py` | degenerate args, nonce leakage on error paths, warning visibility, dtype ladder |
| `stats.py`, `big.py`, `replicate.py` | 43.8M bets / 115.5M+ game events, χ² vs exact lattice probabilities |
| `blind.py`, `blind.txt`, `blind_key.txt` | label-stripped side-by-side, randomized column assignment, key kept in a separate file |

---

## 1. (a) `BulkRng` per-bet card / gem methods

**343 blocks** = 7 server seeds × 7 client seeds × 7 nonces, each expanded to 6
consecutive bets in the multi-bet pass. Server seeds: all-zero, all-`f`, a mixed hex seed,
`4d6a5e…5c4d`, `deadbeef`×8, `0123456789abcdef`×4, and a **non-hex** seed
(`not-a-hex-seed-at-all`, to pin the UTF-8 HMAC key encoding). Client seeds: `test`,
empty, `spinquest`, `has:colons:in:it` (collides with the message delimiter),
`Ünïcøde:seed`, `100%%win` (format-string bait), `bac`. Nonces: 0, 1, 7, **900**, 12345,
999999, 2³¹+5.

| check | comparisons | mismatches |
|---|---|---|
| `BulkRng.baccarat_cards` vs node | 2,058 | **0** |
| `BulkRng.card_hands(2 / 9 / 52 / 104)` vs node | 54,880 | **0** |
| `BulkRng.diamonds_gems` (indices **and** `names=True`) vs node | 3,430 | **0** |
| `BulkRng.diamond_poker_hands` dealer/player, indices and names vs node | 6,860 | **0** |
| `BulkRng.keno_hits` / `mines_positions(24)` / `video_poker_decks` vs node (these route through the **changed** `_fisher_yates_matrix`) | 29,498 | **0** |
| scalar `baccarat_cards` / `card_draws` / `diamonds_gems` / `diamond_poker_hands` / `keno_hits` / `mines_positions` / `video_poker_deck` vs node (guards against a shared-bug tie) | 70,463 | **0** |
| bulk row *i* vs scalar helper at nonce *n₀+i*, 6-bet runs | 41,160 | **0** |
| **nonce accounting** — `nonce_next` and `last_nonce_range` after every method | 2,745 | **0 wrong** |
| `card_hands(n)` at every awkward digest boundary, n ∈ {1,2,7,8,9,16,17,32,51,52,53,63,64,65,104,105,200,257} | 288 | **0** |
| ragged chunking (`_CHUNK_FLOAT_BUDGET=13`, `_POOL_CELL_BUDGET=61`) | 7 methods | **0** |
| forced process fan-out (`_PARALLEL_MIN_DIGESTS=5`, `workers=4`) | 4 methods | **0** |
| rows straddling real default-budget chunk boundaries (baccarat 1,333,333 / card_hands 888,888 / diamonds 1,600,000 / keno 800,000 / mines 333,333 / vp 153,846) | 78 rows | **0** |
| 400-trial randomized fuzz, all 22 bulk methods vs scalar (hostile seeds incl. emoji, control chars, 200-char and non-hex seeds; nonces to 2⁵³−3) | 17,515 | **0** |

**One nonce per bet is real, not asserted.** Every method's `last_nonce_range` is exactly
`(n₀, n₀+size)`; `card_hands(104, 1)` — 13 digests — still consumes **one** nonce.

### The documented nonce-900 case, re-derived from Node

```
seed …9c2e9c2e   client ''   nonce 900
node  generateFloats(count=6) -> floor(f*52)  : [2, 10, 24, 6, 46, 2]
scalar baccarat_cards(..., 900)               : [2, 10, 24, 6, 46, 2]
BulkRng.baccarat_cards(1)[0]                  : [2, 10, 24, 6, 46, 2]   nonces (900, 901)
card names                                    : ♠2 ♠4 ♦8 ♠3 ♠K ♠2
```

Nonce 900 appears in 49 of the 343 blocks (every seed × client combination) and every one
matches, on both paths, with the coup coming from a single nonce. The legacy
`cards(6)` one-nonce-per-card shape is still reproducible and still different — verified
against node in `fuzz.py` — which is the point of the deprecation.

**Verdict on (a): pass, without qualification.**

## 2. (b) `draws_without_replacement` — overflow gone, and this time the memory bound is real

```
BulkRng('0'*64,'d1',0).draws_without_replacement(40000, 2, 3)
 -> [[15232, 5583], [18365, 20414], [10908, 8193]]   dtype int64
```

Row-identity against the Node Fisher-Yates at **18 pool/draw shapes** — pools 1, 2, 3,
255, 256, 257, 32766, **32767**, **32768**, 32769, 40000, 65535, **65536**, 65537, 70000,
100000, 200000 (108 rows): **0 mismatches**, every index in `[0, pool)`, every row
distinct. 1,020 further multi-row rows at pools 32768 / 40000 / 70000 / 100000 match the
scalar `fisher_yates_draws` exactly. The dtype ladder is right at every boundary
(256→uint8, 257→uint16, 65536→uint16, 65537→uint32). Adversarial floats pinned to `0.0`,
`1−2⁻³²`, `2⁻³²`, `0.5` across 15 pool sizes: 295 rows, **0 mismatches**.

Distribution at a post-`int16` pool — 60,000 rows × 3 draws from a pool of 40,000,
bucketed into 40 ranges, scored against the **exact `k/2³²` lattice probabilities**:

| column | χ²(39) | p | max \|z\| |
|---|---|---|---|
| 0 | 22.01 | 0.987 | 1.73 |
| 1 | 36.24 | 0.597 | 2.56 |
| 2 | 32.89 | 0.744 | 1.99 |

Rows with a repeat or an index outside `[0, 40000)`: **0**.

### Round 1's D1 is genuinely fixed

Round 1 failed the piece because the `int16` fix traded a wrong-answer bug for an
unbounded-memory bug: `draws_without_replacement(40000, 2, 200_000)` thrashed the
container for 82 s with no result. Measured now, on the same 16 GB / 4-core box:

| call | round 1 | round 2 |
|---|---|---|
| `dwr(40000, 2, 20_000)` | 3.87 GB | **269 MB** |
| `dwr(40000, 2, 200_000)` | thrashed, no result | **272 MB, 36.9 s** |
| `keno_hits(1_000_000)` | 378 MB | 260 MB |
| `video_poker_decks(150_000)` | 196 MB | 234 MB |

And the fix costs the real games nothing: chunk rows for pools 25 / 40 / 52 are still
`8M // floats_per_bet` (333,333 / 800,000 / 153,846) — the pool bound never binds, so
`keno_hits`, `mines_positions` and `video_poker_decks` are byte-identical to round 4.
I checked their chunk arithmetic directly rather than taking the comment's word for it.

**Verdict on (b): pass. The assigned check and round 1's follow-on both hold.**

### D1 (residual, unreachable): the budget counts *cells*, not *bytes*, and floors at one row

`_POOL_CELL_BUDGET = 50_000_000` bounds `rows × pool_size` in **elements**, and
`_chunks` clamps to `max(1, …)`. Two consequences the docstrings deny:

- The pool dtype scales the budget's byte cost: 50M cells is 50 MB at `uint8` but 200 MB
  at `uint32`, before the `np.where` temporaries.
- Above `pool_size = 50M` the chunk floors at one row and the pool matrix grows without
  further bound.

| call | pool matrix | peak RSS |
|---|---|---|
| `dwr(100_000, 5, 20_000)` | 200 MB (uint32) | **461 MB** |
| `dwr(1_000_000, 3, 2_000)` | 200 MB | **467 MB** |
| `dwr(60_000_000, 2, 4)` | 240 MB | **831 MB** |
| `dwr(200_000_000, 2, 2)` | 800 MB (4× the stated cap) | **2,701 MB** |

Against the class docstring, verbatim: *"so per-chunk arrays stay well under 500 MB for
any `size` AND any `pool_size`"*, and `_fisher_yates_matrix`'s *"the pool matrix is then
capped at `_POOL_CELL_BUDGET` (~50M) cells per chunk regardless of pool size."* Both
absolutes are false; 461 MB is not "well under 500 MB" and 200M cells is not "capped at
50M". The one-line fix is to make the budget a byte budget and to say "up to
`_POOL_CELL_BUDGET`", not "any":
`chunk = min(chunk, _POOL_BYTE_BUDGET // (pool_size * np.min_scalar_type(pool_size-1).itemsize))`.

I am **not** failing the piece on this, and I want to be explicit about why, because it is
the same sentence I failed round 1 on. Round 1's version cost a caller their container at
`size = 200_000` with a pool of 40,000 — a shape a generic helper plausibly sees. Round 2's
version requires a pool of **two hundred million**, at which point the caller has asked for
an 800 MB array by arithmetic, not by surprise. The cliff moved four orders of magnitude
past anything reachable; what is left is an overstated adjective, not a landmine.

### D2 (minor, hygiene): the deprecation warning is invisible to exactly the callers it targets

```
called from __main__            : DeprecationWarning: BulkRng.cards() burns one nonce per card…
called from a library module    : (NOTHING)   cards(3) = [2, 25, 24]
```

Python's default filter ignores `DeprecationWarning` unless it fires in `__main__`. The
trap round 4 named — `cards()`/`gems()` consuming one nonce per event — is therefore still
completely silent for a game module, which is the only caller that would ever hit it.
`FutureWarning` (or deleting the two methods, since round 1 confirmed and I re-confirmed
that nothing in `spinquest_sim/`, `scripts/` or `tests/` calls them outside their own
tests) closes it.

### D3 (cosmetic)

- `dwr(40_000, 2, 2_000_000)` emits **1,600** `BulkRng: n/2,000,000 bets` lines, because
  the progress trigger is `size > chunk` and the pool bound shrank the chunk to 1,250.
- `draw_count = -1` escapes as numpy's `ValueError: negative dimensions are not allowed`
  rather than a guard; `pool_size = 0, draw_count = 0` silently consumes `size` nonces and
  returns a `(size, 0)` array.
- The pool bound shrinks large-pool chunks below `_PARALLEL_MIN_DIGESTS`, so the process
  fan-out never engages for them. Irrelevant in practice (those calls are dominated by the
  Fisher-Yates matrix, not by HMAC) and **no in-scope game is affected** — keno, mines,
  video poker and baccarat all still cross the parallel threshold.

**No error path leaks a nonce.** `nonce_next` is unchanged after every one of
`draw_count > pool_size`, `size < 0`, `n_cards < 1`, `mine_count = 99`,
`cards_needed = 53`, a bad dragon-tower difficulty, and `plinko rows = 7`.

## 3. (c) The verified scalar path did not move

Nine `(serverSeed, clientSeed, nonce, cursor)` vectors of the round-4 class — mid-digest
cursor 7, unaligned cursor 32 and 64, cursor 100, **cursor 416** (the 13-digest
hilo/blackjack reservation), empty client seed, a client seed containing `:`, a non-ASCII
client seed, a non-hex server seed, nonce 999,999 — replayed against the **current**
`rng.py` with the Node reference regenerated live:

| check | comparisons | mismatches |
|---|---|---|
| `generate_bytes`, 96 bytes/vector | 864 | **0** |
| `generate_floats` compared as **float64 bit patterns**, not decimals | 216 | **0** |
| card names (52-entry published order) | 216 | **0** |
| gem names | 216 | **0** |
| limbo crash points (published operation order) | 216 | **0** |
| roulette pockets / plinko directions | 432 | **0** |
| dice, floored (the round-4 §5 deliberate divergence, unchanged) | 216 | **0** |
| `keno_hits` / `mines_positions(24)` / `video_poker_deck` | 774 | **0** |
| `hash_server_seed` vs node `createHash` | 9 | **0** |
| `CURSOR_INCREMENTS` / `EVENT_COUNTS` / `digests_for_events` vs the published tables | 40 | **0** |

The 400-trial fuzz additionally re-derives `dice_rolls`, `limbo_crash_points`,
`roulette_pockets`, `wheel_indices`, `plinko_directions`, `scarab_spins`,
`dragon_tower_eggs` (all 5 difficulties) and `floats` bulk-vs-scalar — **0 mismatches** —
so the regression guard covers the whole module, not only the delta's neighbourhood.
`CURSOR_INCREMENTS` is byte-identical to round 4 including the doc-verbatim
hilo/blackjack 13 and `slots: None`.

Reported for completeness, not relied on: the builder's `tests/test_rng.py` runs clean
(159 passed in 5.2 s).

**Verdict on (c): pass. Nothing in the verified path moved.**

## 4. Round 1's other two findings

- **D3 (nothing used the new methods) is closed.** `games/baccarat.py:409` now calls
  `rng.baccarat_cards(n_rounds)` on the unlimited-deck path, and `games/blackjack.py:914`
  calls `rng.card_hands(float_budget, step)`. Blackjack's `_DEFAULT_FLOAT_BUDGET = 24` is
  still a locally chosen number rather than an `EVENT_COUNTS` entry — but that is correct
  here: the doc gives Blackjack no fixed event count ("Unlimited to cover required amount
  of cards"), and any round exceeding the budget is replayed exactly on the scalar path,
  so the budget is a performance knob, not a correctness one.
- **D2 (scalar returns names, bulk returns indices) is addressed** by the `names=True`
  keyword on `diamonds_gems` / `diamond_poker_hands`; both forms verified against node.
  The defaults still differ between the two paths, which I would still rather see
  unified, but it is now documented and both branches are exercised.

## 5. Empirical statistics on the delta's methods

**21,000,000 bets / 115,500,000 game events** in the headline campaign (30 s wall,
peak RSS 384 MB), χ² against **exact `k/2³²` lattice probabilities** — 2³² is divisible by
neither 52 nor 7, so `1/M` would be the wrong null:

| statistic | measured |
|---|---|
| `baccarat_cards`, 10,500,000 coups = 63M card events; pooled card index χ²(51) | 53.99, p = 0.361, max \|z\| = 2.33 |
| … per coup position 0–5, χ²(51) each | p = 0.181 / 0.095 / 0.348 / 0.930 / 0.623 / 0.467 |
| `diamonds_gems`, 10,500,000 bets = 52.5M gem events; χ²(6) | 6.42, p = 0.378, max \|z\| = 1.55 |
| nonces consumed vs bets | exactly 1:1 (`last_nonce_range` = (9,000,000, 10,500,000) on the final chunk) |

A second 6,760,000-bet / 47,680,000-event campaign on a different seed covered the rest of
the delta: `card_hands(9)` χ²(51) = 68.97 (p = 0.048), `diamond_poker_hands` dealer
χ²(6) = 11.80 (p = 0.067) / player 10.57 (p = 0.103), `baccarat` card0×card1 independence
χ²(2601) = 2731 (p = 0.037), `dwr(40000, 3)` columns p = 0.987 / 0.597 / 0.744. Sixteen
tests with a minimum p of 0.037 is exactly what uniform p-values look like
(P(min p < 0.037 across 16) ≈ 0.45).

**The one cell above 3 SE, chased rather than waved off.** Baccarat coup position 4 threw
max \|z\| = 3.47 on one seed. Across 6 positions × 52 cells = 312 cells, E[max \|z\|] ≈ 3.2,
so this is where the maximum is expected to sit. I confirmed it anyway:

| run | coups | χ²(51) | p | max \|z\| |
|---|---|---|---|---|
| original seed | 2,000,000 | 59.69 | 0.189 | 3.47 (cell 15) |
| original seed, 4× the data | 8,000,000 | 59.15 | 0.202 | **3.29** (cell 15) |
| independent seed 1 | 2,000,000 | 43.90 | 0.749 | 2.95 (cell 4) |
| independent seed 2 | 2,000,000 | 51.10 | 0.470 | 2.33 (cell 36) |
| independent seed 3 | 2,000,000 | 56.04 | 0.291 | 2.18 (cell 51) |

A real bias would have taken cell 15 from 3.47 to ≈ 6.9 on 4× the data; it went **down**,
and it does not reproduce on any other seed. Decisively: the bulk stream is **bit-identical
to the Node transcription over all 343 blocks and 400 fuzz trials**, so any distributional
quirk belongs to HMAC-SHA256, not to this module — it is not "our" bias, by construction.

Total simulation across all campaigns: ≈ 43.8M bets / 180M+ game events, arrays chunked,
peak RSS never above 500 MB on any campaign path.

## 6. Blind comparison

`blind.txt` renders **10 blocks × 78 cells** as two unlabeled columns with independently
randomized left/right assignment per block; the key lives in a separate `blind_key.txt`
that is not shown beside the table. Blocks: 6 per-bet card/gem blocks (baccarat coup as
indices *and* card names, 9-card blackjack hand, the tail of a 104-float hilo reservation,
diamonds gem names, diamond poker dealer/player, keno, mines, video poker), 3 large-pool
`draws_without_replacement` blocks at pools 40,000 / 100,000 / 200,000, and one scalar-path
block (raw bytes at cursor 416, float64 **bit patterns**, limbo crash points).

**Cells where A ≠ B: 0 of 78.** Not "equal to displayed precision" — the float column is
compared as raw IEEE-754 hex, so a single-ULP difference would show. There is no dice
column in this delta, so round 4's one blind-detectable cell does not even appear. An
expert asked "which column is the imitation?" has literally nothing to go on; the key is
the only way to tell. Coin flip.

## 7. Verdict

**Ours wins.** All three assigned checks pass without qualification:

- **(a)** the per-bet card/gem methods are row-identical to both an independent Node
  execution of Stake's published code and to the scalar API across 343 seed/client/nonce
  blocks and 400 randomized fuzz trials — 249,000+ comparisons, **0 mismatches** — at
  exactly one nonce per bet, under ragged chunking, forced 4-process fan-out, and at every
  real chunk boundary; the documented nonce-900 coup reproduces on all 49 seed×client
  combinations that carry it.
- **(b)** the `int16` overflow is gone (correct up to a pool of 200,000, right dtype at
  every boundary, distributions on the exact lattice), and — the reason round 1 failed —
  the memory blow-up its fix introduced is genuinely bounded: the exact call that thrashed
  the container now peaks at **272 MB** and finishes in 37 s, with the real game pools
  (25/40/52) provably untouched.
- **(c)** not one bit of the round-4-verified scalar path moved, across bytes, float64 bit
  patterns, every game mapping, the published cursor/event tables, and the SHA-256
  commitment.

21M bets / 115.5M events put every block-level χ² inside its expected range with the single
3-SE-plus cell demonstrated to be non-replicating HMAC noise, and the blind comparison is
0 differing cells out of 78 — a pure coin flip with no tell in either direction.

### The one change that most closes the remaining distance

Non-blocking, but it is the only place left where the shipped code does something a reader
of it would not predict: **make `_POOL_CELL_BUDGET` a byte budget rather than a cell budget
and drop the two absolutes from the docstrings.** Multiply the divisor by the pool dtype's
`itemsize` so 50M `uint32` cells stop costing 4× what 50M `uint8` cells cost, and change
"stay well under 500 MB for any `size` AND any `pool_size`" / "capped … regardless of pool
size" to name the actual envelope (`pool_size` up to `_POOL_CELL_BUDGET`; above that the
chunk floors at one row and the pool matrix is `pool_size` cells). Measured today: 461 MB
at pool 10⁵, 467 MB at pool 10⁶, 831 MB at pool 6×10⁷, 2.70 GB at pool 2×10⁸. It is a
two-line change, it is unreachable by any in-scope lobby game, and it would retire the last
sentence in this module that its own code does not honor. Fold in `FutureWarning` for
`cards()`/`gems()` while touching the file — the current `DeprecationWarning` is invisible
to every caller except `__main__`.
