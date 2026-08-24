# rng_core — Gauntlet Round 1 (independent critic)

**Verdict: OURS DOES NOT WIN.** The core is genuinely excellent — byte-exact and
float-bit-exact against an independent Node reimplementation across every tuple I could
throw at it. It loses on one thing: `limbo_crash_point` evaluates the published
expression in a **different order of operations**, which changes the payout for
exactly **60 of the 2³² possible floats**, plus a hand-invented value for `float == 0`
where the published code yields `Infinity`.

Under the stated rule ("any byte/float mismatch = not winning") that is disqualifying,
and it is the one row of the blind table an expert uses to pick out the imitation.

---

## 1. Method — nothing was taken on trust

I did not import, read-for-truth, or run the builder's tests as evidence. I transcribed
Stake's verbatim JS from `references/stake/core.md` into a standalone Node 22 script
(`ref.js`) using Node's own `crypto.createHmac`/`createHash`, and treated its output as
ground truth. Python was then compared against it.

Artifacts (scratchpad):
`/tmp/claude-0/-home-user-troyrhinehart/b3ce270f-e608-55a6-8515-5735b66f4ebe/scratchpad/g1/`
— `ref.js` (verbatim JS), `cmp.py` (cross-language diff), `cursors.py` (increment table),
`formula.js` (5M sweep + adversarial set), `dist.py` (joint-law tests), `rtp.py` (10M RTP).

Test surface: **7 seed tuples × 16 cursors = 112 cases**. Tuples deliberately included
all-zero and all-`f` server seeds, an empty client seed, a client seed containing colons
(`"client:with:colons"` — a delimiter-injection trap), a 200-char client seed, a UTF-8
client seed (`ünïcødé-☃-seed`), nonce 0, and nonce 2147483647. Cursors included
mid-digest and multi-digest offsets: 0, 1, 3, 13, 31, 32, 33, 63, 64, 65, 96, 100, 255,
256, 1000, 4096.

---

## 2. What passes — and it passes hard

| Check | Result |
|---|---|
| `byte_generator` vs verbatim JS | **14,560 bytes exact** (112 cases × 130 bytes), 0 diffs |
| `generate_floats` vs verbatim JS | **5,824 floats exact as raw IEEE754 bit patterns** (112 × 52), 0 diffs |
| `hash_server_seed` | 7/7 exact |
| `CARDS` table order | exact match to the published `♦2…♣A` array (rank-major, suit order ♦♥♠♣) |
| Card index `floor(f*52)` | 1,344 exact |
| Keno (10-of-40 Fisher-Yates) | 112 exact |
| Mines (24 events, pool 25) | 112 exact |
| Video Poker (52-card FY) | 112 exact (full permutation) |
| Roulette / Plinko / Wheel (10,20,30,40,50) | 896 / 1,792 / 560 exact |
| Dice `floor(f*10001)/100` | 896 exact + 9 edge floats |
| Generic `fisher_yates_draws` (Dragon Tower easy 3-of-4) | 112 exact |

Floats were compared as **8-byte big-endian doubles**, not decimal strings, so no
printing precision could hide a mismatch.

**Cursor / increment table** — I instrumented `hmac.new` to count digests per game and
checked against the doc's list. All correct:

```
Dice/Limbo/Wheel/Roulette/Diamonds(5)/Baccarat(6ev)  doc 1  ours 1   rounds [0]
Keno / Plinko(16) / Diamond Poker(10)                doc 2  ours 2   rounds [0,1]
Mines (24 events)                                    doc 3  ours 3   rounds [0,1,2]
Video Poker (52) / Blackjack-Hilo (52 events)        doc 7  ours 7   rounds [0..6]
```

(My first pass flagged Dragon Tower as a mismatch; that was my own bad expectation —
9 events × 4 bytes = 36 bytes legitimately spans 2 digests. Retracted.)

Delimiter-injection trap passed: a client seed containing `:` produces the same stream in
both languages, because both build the message by plain interpolation. Good.

---

## 3. The disqualifying defect — limbo operation order

`rng.py:191`:

```python
crash_point = math.floor(house_edge / value * 100) / 100
```

The published code is:

```js
const floatPoint = 1e8 / (float * 1e8) * houseEdge;
const crashPoint = Math.floor(floatPoint * 100) / 100;
```

`(0.99/f)*100` and `((1e8/(f*1e8))*0.99)*100` are not the same double. They differ by an
ULP for some `f`, and when that ULP straddles an integer the floored cent differs.

**I scanned all 2³² lattice floats exhaustively** (numpy, 20M-value chunks, 229 s) after
first proving my numpy vectorization reproduces the Node output bit-for-bit on 5M values
(0 mismatches):

```
EXHAUSTIVE all 2^32 floats: limbo mismatches = 60   p = 1.397e-08
```

Concrete, entirely reachable examples (ours → published):

| float | ours | published (Node) |
|---|---|---|
| `0.005859375` (k=25165824) | **168.96** | **168.95** |
| k=37748736 | 112.64 | 112.63 |
| k=50331648 | 84.48 | 84.47 |
| k=201326592 | 21.12 | 21.11 |
| k=3 | 1417339207.68 | 1417339207.67 |
| `0.0` | 4252017623.04 | `Infinity` |

`168.96` vs `168.95` is not a rounding curiosity — it is a payout a player would see on
Stake's own Calculation page and could not reproduce with this module. That is one bet in
~71.6 million; a busy verifier hits it.

The `float == 0` case (`rng.py:186-190`) is worse in kind than in frequency: the code
*knowingly* substitutes `2**-32` to dodge a division by zero, inventing a finite
4252017623.04 where the published algorithm returns `Infinity`. It is documented in a
comment, which makes it a deliberate deviation from spec rather than an oversight.

**The fix is one line and I verified it.** Replacing the expression with the published
order and letting `f == 0` return `math.inf`:

```
adversarial set (807 exact-boundary k): current impl 61 mismatches -> proposed fix 0
5,000,000 random lattice floats:        proposed fix 0 mismatches
```

The same change is needed in `BulkRng.limbo_crash_points` (`rng.py:286-289`), which
reproduces the identical reordering.

Note the builder's suite cannot catch this: `tests/test_rng.py` has **no independent
limbo reference at all** (`ref_bytes`/`ref_floats`/`ref_fisher_yates` exist; no
`ref_limbo`), and its only limbo assertions are one stream float and `0.999`. Its
"independent" claim does not extend to this formula.

---

## 4. Other findings (ranked)

**a) `GEMS` mapping is entirely absent.** The doc publishes
`GEMS = [green, purple, yellow, red, cyan, orange, blue]` with `floor(float*7)` for
Diamonds (5 events) and Diamond Poker (10 events, dealer-then-player). `rng.py` has no
`GEMS`, no `gem_index`, and the increment table correctly accounts for Diamond Poker's 2
increments but nothing maps the floats. Also missing: Dragon Tower `LEVEL_MAP`, the
Scarab/Tome reel lengths (30/30/30/30/41), and Blue Samurai's 18-float weighted sampling.
The generic primitives cover the mechanics, but a published index array is missing.

**b) Nonce type coercion silently forks the stream.** `f"{nonce}"` on a Python float or
bool does not match JS `${nonce}`:

```
nonce=7    -> [84, 199, 166, 157, ...]
nonce=7.0  -> [240, 176, 48, 48, ...]     different stream, no error
nonce=True -> different from nonce=1      (JS renders 'true')
nonce='7'  -> silently accepted, matches 7
```

For a module whose stated purpose is *verifying real bets*, a nonce arriving from
`json.loads` as `7.0` produces a confidently wrong answer with no warning. One
`int(nonce)` coercion or an `isinstance` guard closes it. (Nonces ≥ 1e21 would also
diverge — JS switches to exponential notation — but that is not reachable in practice.)

**c) Dice floor is an undocumented reading of the spec.** The doc's verbatim dice line is
`(float * 10001) / 100` with **no** floor, and unlike the Wheel case the doc does *not*
flag a missing floor for dice. Ours floors. **Ours is right** — without the floor the max
is 100.0099…, contradicting the doc's own "Range 00.00–100.00 → 10,001 outcomes" — but
the deviation carries no citation, while the equivalent Wheel deviation does
(`rng.py:200-203`). Add the one-line note.

**d) The cursor=13 ambiguity is unaddressed.** The doc contradicts itself: `byteGenerator`
treats cursor as a **byte offset** (`Math.floor(cursor / 32)`), while the prose says the
cursor "increments by 1 each time 32 bytes are consumed" (a **digest index**) and that
"Hilo and Blackjack use a cursor of 13". Under our (correct, code-faithful) semantics,
`cursor=13` means byte 13 and starts at round 0 — reproducing a real Stake blackjack hand
quoted at "cursor 13" would need `cursor=416`. The module ports the code faithfully, which
is the defensible choice, but exposes no per-game cursor constants and no note about the
conflict. `[a for a in dir(rng) if 'CURSOR' in a.upper()]` → `NONE`.

**e) Unverifiable shared assumption.** `hash_server_seed` hashes the UTF-8 *text* of the
hex seed, not its decoded bytes. My reference made the same choice, so this check is
circular — the doc does not disambiguate. Flagging it as residual risk, not a defect.

---

## 5. Statistics — passes decisively

**Bulk path is distribution-identical.** `BulkRng.floats` draws `integers(0, 2**32)/2**32`;
the provably-fair float is exactly `(b0·2²⁴+b1·2¹⁶+b2·2⁸+b3)/2³²` — the same lattice,
exactly representable in a double. I confirmed both are exact multiples of 2⁻³² and that
the bulk limbo/dice formulas reproduce the Node values on 1M identical floats (0 diffs).

I attacked the **joint** law, since the builder's tests only check marginals — an
argsort-based sampler can pass marginal tests with a wrong joint distribution:

| Test | Result |
|---|---|
| KS 2-sample, PF floats vs Bulk floats (2M each) | D=0.000953, **p=0.323** |
| HMAC byte uniformity, 4M bytes, χ²(255) | 252.6, **p=0.531** |
| Fisher-Yates **full joint** law, pool 5 draw 3 (60 ordered outcomes), 3M each | PF p=0.607, Bulk p=0.324, **PF-vs-Bulk contingency p=0.635** |
| Keno hit-count vs Hypergeometric(40,10,10), 2M | χ²=9.00, df=8, **p=0.343** |
| Keno per-position uniformity ×10 | p ∈ [0.025, 0.887] |
| Mines pair independence, 600 ordered-pair cells | worst 3.13 SE (expected max ≈3.2), diagonal = 0 |
| Exact discretization law of `floor(k/2³²·M)` for M=37,52,7,10001, 20M each | matches; deviation from uniform is ≤2.1e-10, undetectable below n≈10²⁰ — structurally guaranteed by construction |

**RTP, 200M+ rounds.** My first 10M-round run showed limbo RTP positive at all five
cashouts on both paths and a dice mean at **−3.06 SE**, which looked like a real bias. It
is not — the cashout statistics are nested (win@100x ⊂ win@10x ⊂ …) and dice/limbo share
one float stream, so a single stream's small-float excess moves everything together. I ran
independent replicates: **12 × 10M bulk + 6 × 10M PF = 180M rounds**.

```
combined z   bulk dice +0.31   bulk P(limbo>=2) +0.13   bulk mean_float +0.31
             PF   dice +0.21   PF   P(limbo>=2) -0.04
             |z| > 3 in any of 12 bulk replicates: 0
```

Single 10M-round RTPs against doc-derived targets (all within 3 SE):

```
PF   limbo @2x    RTP=0.990691  target 0.990000  +2.18 SE
PF   roulette     RTP=0.975420  target 0.972973  +1.33 SE
Bulk wheel 10/low RTP=0.989859  target 0.990000  -0.89 SE
Bulk wheel 10/med RTP=0.989806  target 0.990000  -0.58 SE
Bulk wheel 50/med RTP=0.989880  target 0.990000  -0.33 SE
Bulk wheel 50/high RTP=0.991866 target 0.990000  +0.85 SE
```

(All five published wheel tables sum to 0.99× their segment count — the 1% edge — and the
sim reproduces that.) PF-vs-Bulk head-to-head win counts at five cashouts: |z| ≤ 1.27.

**stats_pass: true.**

---

## 6. Blind comparison

Two unlabeled columns, same inputs. Thirteen of seventeen rows are indistinguishable —
identical bytes, identical float bit patterns, identical keno/mines/video-poker/roulette/
wheel/plinko/dice draws, identical seed commitment. (One row differed only because my
harness printed suits as `♥` vs `H`; the indices matched. Not a defect.)

Then:

```
limbo f=0.005859375     A: 168.96             B: 168.95          <== DIFFERS
limbo f=3·2^-32         A: 1417339207.68      B: 1417339207.67   <== DIFFERS
limbo f=0               A: 4252017623.04      B: Infinity        <== DIFFERS
gem(float)              A: AttributeError     B: yellow          <== DIFFERS
```

An expert picks column A as the imitation without hesitation. `4252017623.04` where the
algorithm says `Infinity` is a fingerprint of a hand-patched edge case, and a missing
`GEMS` table is a fingerprint of partial coverage. **The blind comparison favors the
reference.**

---

## 7. Biggest remaining gap

**Reproduce the published limbo expression in its published order, and let `float == 0`
return `Infinity`.** Replace `math.floor(house_edge / value * 100) / 100` with
`math.floor((1e8 / (value * 1e8) * house_edge) * 100) / 100`, drop the `2**-32`
substitution in favour of `math.inf`, and mirror both in
`BulkRng.limbo_crash_points`. Verified: this takes the mismatch count from 61 to **0** on
the 807-value adversarial boundary set and holds at 0 across 5,000,000 random lattice
floats.

Everything else here is a note, a guard, or a missing seven-element array. This is the
only place the module computes a *different published payout* than Stake does.
