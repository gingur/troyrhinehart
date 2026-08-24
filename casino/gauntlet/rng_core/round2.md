# rng_core — Gauntlet Round 2 (independent critic, fresh eyes)

**Verdict: OURS DOES NOT WIN — but for the first time the reason is not a wrong number.**

Round 1's disqualifying defect (limbo operation order) is **genuinely fixed**: I swept
**21,499,700 lattice floats** against a fresh Node transcription of the published formula
and found **zero** mismatches, on a test I proved has teeth (the old operation order fails
180 of the same floats). Every byte, every float bit-pattern, and every published game
mapping now reproduces the reference **exactly**. The 12M-round empirical stats land
inside 3 SE of targets I computed by **exhaustively enumerating all 2³² floats**. The
blind comparison is a true coin flip — 405 of 405 cells identical.

It loses on **completeness and architecture**, not arithmetic. The single thing that gives
ours away as the imitation: **every simulated round this project will ever produce comes
out of a PCG64 twin, not out of the provably-fair stream** — and I measured that the real
stream is fast enough to have made the twin unnecessary (12M rounds in 6 seconds).

---

## 1. Method — nothing taken on trust

I did not read, run, or believe the builder's tests as evidence. I transcribed Stake's
verbatim JS from `references/stake/core.md` into a standalone Node 22 script using Node's
own `crypto.createHmac`/`createHash`, inlined lodash's `chunk`, and treated **that** as
ground truth. I then wrote my own vectorized provably-fair stream (≈20 lines, independent
of `rng.py`'s bulk path) to cross-check distributions and RTP.

Scratchpad artifacts:
`/tmp/claude-0/-home-user-troyrhinehart/b3ce270f-e608-55a6-8515-5735b66f4ebe/scratchpad/g2/`
— `ref.js` (verbatim JS oracle), `cmp.py` (cross-language diff), `limbo.js`/`limbo_cmp.py`
(21.5M-float sweep), `cursors.py` (increment-table audit + digest instrumentation),
`dist.py` (PF-vs-bulk G-tests), `rtp.py` (2³² exhaustive enumeration + 12M rounds),
`blind.txt` (unlabeled side-by-side).

Test surface: **9 seed tuples × 24 cursors = 216 cases**, deliberately adversarial —
all-zero and all-`f` server seeds, an empty client seed, a client seed made only of
delimiters (`":::"`), one containing colons (`"client:with:colons"` — a delimiter-injection
trap), a 190-char client seed, a UTF-8 client seed (`ünïcødé-☃-seed-é中文`), a client seed
with a literal tab, a server-seed key longer than SHA-256's 64-byte block (forces HMAC key
pre-hashing), an 8-char server seed, nonce 0, and nonce 1000000007. Cursors covered
mid-digest, digest-boundary and far offsets: 0,1,2,3,7,15,31,32,33,35,63,64,65,96,127,128,
129,200,255,256,1000,4095,4096,100000.

---

## 2. What passes — and it passes at full strength

Floats were compared as **8-byte big-endian IEEE754 bit patterns**, never as decimal
strings, so no printing precision can hide a mismatch.

| Check | Scale | Result |
|---|---|---|
| `byte_generator` vs verbatim JS | 216 × 208 = **44,928 bytes** | **0 diffs** |
| `generate_floats` vs verbatim JS | 216 × 52 = **11,232 floats, bit-exact** | **0 diffs** |
| `hash_server_seed` (SHA-256 commitment) | 216 | 0 diffs |
| `CARDS` order + `card_index` | 216 × 52 | 0 diffs — `♦2…♣A`, rank-major, suits ♦♥♠♣ |
| `GEMS` order + `gem_index` | 216 × 10 | 0 diffs — green,purple,yellow,red,cyan,orange,blue |
| Roulette (37) / Plinko (2) / Wheel (10,20,30,40,50) | 2,592 / 3,456 / 6,480 | 0 diffs |
| Dice `floor(f*10001)/100` | 2,592 | 0 diffs |
| **Limbo, full formula sweep** | **21,499,700 floats** | **0 diffs** |
| Keno 10-of-40 Fisher-Yates | 216 full draws | 0 diffs |
| Mines 24-event FY (pool 25) | 216 full draws | 0 diffs |
| Video Poker 52-card FY | 216 full permutations | 0 diffs |
| Dragon Tower rows via `fisher_yates_draws` (3-of-4, 2-of-3, 1-of-2, 1-of-4) | 864 | 0 diffs |

**Adversarial cases that could have broken it and did not:** HMAC key longer than the
64-byte block; UTF-8 client seeds (both languages encode UTF-8); colon-only and
colon-containing client seeds (the `${clientSeed}:${nonce}:${round}` delimiter-injection
trap); negative cursor (Python's floor division `-1 // 32 == -1` matches JS
`Math.floor(-1/32)`, so `cursor=-1` yields round −1 / roundCursor 31 in both). Resume at
every byte offset 0..399 reproduces the contiguous stream exactly.

### Limbo — the round-1 defect is dead

`ref.js` computed `1e8 / (f*1e8) * 0.99 → floor(·*100)/100 → max(·,1)` over
9,499,700 systematically chosen floats (all k < 300,000; all k in the top 200,000; and the
three floats straddling every `0.99·100·2³²/c` cent boundary for c up to 3M) plus
12,000,000 xorshift-random floats from three seeds.

```
sweep total          21,499,700 floats
ours mismatches               0
naive order (0.99/f) 180 mismatches   <- proves the test has teeth
scalar rng.limbo_crash_point  9,529 spot-checks, 0 mismatches
f == 0               ours inf ; JS Infinity  (match)
```

### Cursor / increment behaviour — measured, not assumed

I monkeypatched `hmac.new` and counted digests actually consumed per bet:

```
dice/limbo/roulette/wheel (1 float)   doc 1   measured 1
diamonds (5 gems)                     doc 1   measured 1
baccarat (6 events)                   doc 1   measured 1
keno (10 of 40)                       doc 2   measured 2
plinko (16 rows)                      doc 2   measured 2
diamond_poker (10 gems)               doc 2   measured 2
mines (24 events)                     doc 3   measured 3
video_poker (52 events)               doc 7   measured 7
blackjack/hilo (52 card events)       doc 13  measured 7   <-- see F2
dragon tower (9 events)               doc —   measured 2
```

### Statistics — targets computed exactly, not assumed

I enumerated **all 4,294,967,296 lattice floats** (316 s, chunked at 20M) to get exact
targets rather than textbook approximations:

```
limbo   1.5x  P=0.6600000001  RTP=0.9900000002
limbo   2.0x  P=0.4950000001  RTP=0.9900000002
limbo    10x  P=0.0990000002  RTP=0.9900000016
limbo   100x  P=0.0099000002  RTP=0.9900000179
limbo  1000x  P=0.0009900001  RTP=0.9900000878
dice over 50.49  P=0.4950504948  RTP @ 0.99/p = 0.9900000000
roulette pocket 0  P=0.0270270272  straight-up RTP = 0.9729729798
```

The published 1% house edge is reproduced to **9 decimal places** off the real byte stream.
Then **12,000,000 rounds on the actual provably-fair stream** (one float per bet,
nonce 0..12M, generated in **6 seconds**):

```
stat                          empirical       target        3*SE        z
limbo RTP @ 1.5x             0.99029813    0.99000000  0.00061537   +1.45  OK
limbo RTP @ 2.0x             0.99020067    0.99000000  0.00086598   +0.70  OK
limbo RTP @ 10x              0.99116333    0.99000002  0.00258649   +1.35  OK
limbo RTP @ 100x             0.98556667    0.99000002  0.00857408   -1.55  OK
limbo RTP @ 1000x            0.98308333    0.99000009  0.02723536   -0.76  OK
dice RTP (over 50.49)        0.98980920    0.99000000  0.00086589   -0.66  OK
roulette straight-up RTP     0.97036500    0.97297298  0.00505572   -1.55  OK
float mean                   0.49987213    0.50000000  0.00025000   -1.53  OK
float variance               0.08330501    0.08333333  0.00006455   -1.32  OK

roulette 37-pocket chi2=40.23 df=36 p=0.2885
card 52-index    chi2=57.96 df=51 p=0.2340
```

Max |z| = **1.55**. All nine inside 3 SE.

### Bulk path is distribution-identical (17 G-tests, 4M events each)

Two-sample G-tests, my independent PF stream vs `BulkRng`:

```
roulette(37) p=0.167   card(52) p=0.574   gem(7) p=0.409   plinko(2) p=0.746
wheel 10/20/30/40/50   p=0.201/0.166/0.117/0.220/0.518
dice index (10001)     G=9742.24 df=10000 p=0.967
raw float, 256 bins    p=0.103
KS 2-sample (500k/500k) D=0.001832 p=0.371
KS bulk vs U(0,1)      D=0.000970 p=0.734     KS PF vs U(0,1) D=0.001248 p=0.417

without-replacement (300k bets each):
keno marginal p=0.905 | 1st draw p=0.464 | 10th draw p=0.789 | hits-on-10-pick p=0.046
mines(3) marginal p=0.874 | 1st mine p=0.207
video poker 5-card marginal p=0.280 | rank marginal p=0.112
P(pair+) in 5 cards: PF 0.493090, bulk 0.493613, exact 0.492918 (z=+0.19 / +0.76)
```

Both streams verified to live on the `k/2³²` lattice. And a stronger test than any of the
above: I **forced the identical 2,002,004 floats** (including k = 0…1999 and both extremes)
through the scalar and bulk mapping code and required bitwise equality —
`cards`, `dice_rolls`, `limbo_crash_points`, `roulette_pockets`, `wheel_indices`(×5),
`plinko_directions` all came back **IDENTICAL**. The bulk path is not a re-derivation that
drifted; it is the same arithmetic.

### Blind comparison — a genuine coin flip

`blind.txt` renders 27 cases × 15 fields with the columns unlabeled and their order
randomised per block. **405 of 405 cells are value-identical.** (Two cells differ as
*strings* only: JS `Math.max(x,1)` serialises the integer literal `1`, Python `1.0` —
same value.) There is no cell an expert could use to assign the labels. On output,
ours is indistinguishable from the reference.

---

## 3. Where it loses

### F1 — BIGGEST GAP: the bulk path is not the reference RNG, and it did not need to be

`BulkRng` is `numpy.random.Generator(PCG64)`. It shares no byte stream with the
provably-fair path, so **no simulated round can be verified against a (server seed, client
seed, nonce) triple** — no seed pair, no nonce, no hash commitment is attached to any of
the millions of rounds the harness will produce. Provable fairness is the entire reason
the reference document exists, and 100% of this project's simulation output falls outside
it.

The usual justification is speed. I measured it and the justification does not hold:

```
my vectorized PF stream (HMAC-SHA256, nonce-parallel)  1.50 M floats/s
12,000,000 real provably-fair rounds                   6 seconds
BulkRng PCG64                                          105x faster
```

A 10M-round campaign costs **6 seconds** on the real stream. The 105× buys nothing anyone
needs, and it costs: (a) verifiability, (b) the two divergences below (F6, and the
modulo-bias mismatch — the PF path's `floor(f*N)` is non-uniform by up to 1.2e-8 for a
52-pool, the argsort twin is not; statistically irrelevant, conceptually a second RNG).

**The single change that most closes the distance:** replace `BulkRng`'s PCG64 backend
with the vectorized HMAC-SHA256 stream (build digests for a contiguous nonce range, view
as `uint8`, fold 4 bytes to `k/2³²`), keep the identical mapping methods, and expose
`(server_seed, client_seed, nonce0)` on the class. Every simulated round then becomes
individually verifiable, the twin/lattice/bias divergences vanish by construction, and the
class stops being a second RNG that merely resembles the first. This is roughly the 20-line
function in my `dist.py:pf_floats`.

### F2 — the increment table diverges from the doc's own list, and nothing enforces it

`CURSOR_INCREMENTS` holds 13 entries against the doc's 14. **`slots` is missing** — Stake's
verbatim "Games with more than 1 incremental number" list has eight entries (Hilo, Keno,
Mines, Plinko, Blackjack, Video Poker, Diamond Poker, **Slots** — "The incremental number
is only utilised for bonus rounds"); ours has seven. This is a direct miss on the check
"cursor/round increments per game against the doc's table".

Worse, the table is **dead code** — `grep` finds no reader of `CURSOR_INCREMENTS` anywhere
outside `__all__` and the tests. And the module's own behaviour contradicts it: the entry
says `blackjack: 13`, but drawing 52 blackjack card events measurably consumes **7**
digests. Either 13 is a per-bet cursor *reservation* (in which case the module should
advance the cursor by 13 and expose that), or it is a digest count (in which case nothing
honours it). Right now it is an unverified comment in dict form.

### F3 — published mappings in this very document with no implementation

`core.md` §3 publishes these and `rng.py` implements none of them:

- **Dragon Tower `LEVEL_MAP`** (easy 3/4, medium 2/3, hard 1/2, expert `count1`[sic]/3,
  master 1/4) — published *verbatim*, 9 events per game, and `rng.py`'s own
  `fisher_yates_draws` docstring name-checks Dragon Tower without providing the map.
- **Scarab Spin / Tome of Life** reels (4 × 30 outcomes, last reel 41, 5 floats/spin).
- **Blue Samurai** weighted (fitness-proportionate) reels, 18 floats regular / 12 special,
  stuck-samurai floats discarded unused.
- **Diamond Poker** 5-dealer + 5-player split; **Diamonds** 5-gem draw.
- Seed-level card draw for **Baccarat / Blackjack / Hilo** — note the API asymmetry:
  Keno/Mines/Video Poker take `(server, client, nonce, cursor)`, everything else takes
  bare floats.

### F4 — `cursor` means two different things and the API does not guard it

The published `byteGenerator` treats `cursor` as a **byte offset**
(`currentRound = floor(cursor/32)`); `rng.py` correctly follows the code. But Stake's prose
— in `core.md` and repeated verbatim in `blackjack.md:40` — says the cursor "starts as 0
and gets increased by 1 every time the 32 bytes are returned", i.e. a **digest index**, and
`CURSOR_INCREMENTS` itself uses that second meaning. A verifier operator who reads Stake's
docs and passes `cursor=1` expecting the second digest silently gets bytes 1..32 of the
*first* digest instead. No error, no warning, wrong stream. Rename to `cursor_bytes` or add
an explicit `round=` keyword.

### F5 — bulk without-replacement silently truncates where the scalar path raises

```
BulkRng.draws_without_replacement(pool_size=5, draw_count=9, size=3) -> shape (3, 5)
BulkRng.video_poker_decks(size=3, cards_needed=60)                   -> shape (3, 52)
rng.fisher_yates_draws([0.1]*9, 5)                                   -> ValueError
```

The `[:, :draw_count]` slice quietly returns fewer columns than asked. A caller that
reshapes or indexes by a fixed width gets silently wrong results. The scalar path validates;
the bulk path must too.

### F6 — the class docstring's headline claim is false for three of its methods

> "floats are drawn as `k / 2**32` to match the 4-byte granularity exactly"

True for `cards`/`dice_rolls`/`limbo_crash_points`/`roulette_pockets`/`wheel_indices`/
`plinko_directions`. **False** for `keno_hits`/`mines_positions`/`video_poker_decks`: they
bypass `self.floats()` entirely and call `generator.random()`, whose lattice is 2⁻⁵³. I
verified this directly. Statistically harmless; as documentation it is wrong.

### F7 — a numpy integer nonce is rejected

The strict `isinstance(nonce, int)` guard (a good idea against JS/Python template-literal
divergence) also rejects every numpy integer type:

```
np.int64(7) / np.int32(7) / np.uint64(7)  ->  TypeError
```

Any vectorized driver that iterates nonces out of a numpy array will hit this. Accept
`numbers.Integral` (or `np.integer`) and convert with `int()`, keeping the bool/float/str
rejection.

### F8 — memory guidance understates peak by 2.25×

`draws_without_replacement`'s docstring says "Memory ~ size * pool_size * 8 bytes … chunk
`size` so that stays under ~500MB". Measured peak for `keno_hits(1_000_000)`: **720 MB**
against a claimed 320 MB (the `random` array, argsort's workspace, and the int64 output all
coexist). A caller who follows the docstring and picks a chunk size for 500 MB will
allocate over 1 GB.

### F9 — the one place ours deviates from the verbatim JS (and I think ours is right)

`dice_roll` applies a floor the published snippet does not:

```js
const roll = (float * 10001) / 100;        // core.md, verbatim
```
```python
return math.floor(value * 10001) / 100     # rng.py
```

All 216 cases fail against the literal snippet and pass against the floored form. I judge
ours correct — the same page's prose says "Range 00.00–100.00 → **10,001 outcomes**", which
only holds if the index is floored, and the general rule ("multiply by the number of
possible outcomes, floor to an index") is applied with `Math.floor` in every other game's
snippet. But this is an *interpretation*, the references contain **no worked test vector
anywhere** to settle it (I grepped all of `references/`), and there is no test asserting the
divergence is deliberate. Add one, with the reasoning, so a future editor cannot "fix" it
back.

---

## 4. Scorecard

| Gate | Result |
|---|---|
| Byte-for-byte vs verbatim JS | **PASS** — 44,928 bytes, 0 diffs |
| Float-for-float (IEEE754 bits) | **PASS** — 11,232 floats, 0 diffs |
| Limbo formula | **PASS** — 21,499,700 floats, 0 diffs (round-1 defect fixed) |
| Card index order / Fisher-Yates / seed hash | **PASS** |
| Cursor increments vs doc table | **FAIL** — `slots` missing; table dead; blackjack 13≠7 measured |
| Bulk path distribution-identical | **PASS** — 17 G-tests + KS, min p=0.046; mappings bitwise identical |
| 10M+ round stats within 3 SE | **PASS** — 12M rounds, max \|z\| = 1.55 |
| Blind comparison | **COIN FLIP** — 405/405 cells identical |
| Coverage of the reference document | **FAIL** — 6 published mappings unimplemented |

Builder's own suite: 75 passed. It is green and it did not catch F1–F8.

**ours_wins = false.** Not on arithmetic — on F1.
