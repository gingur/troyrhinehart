# Crash — round 5 critic verdict (independent, fresh eyes)

**VERDICT: ours does NOT win.** The core math bar is immaculate and I could not
break it with any probe I invented. The gap that round 4 flagged is **not
closed** — it was renamed, not fixed. `fair_ordering: True` is still stamped on
a chain I rigged, in 12 seconds, through the public API, with no warning and no
error; and the new version of the exploit **survives out-of-band beacon
resolution**, which the round-4 version did not. The shipped test that claims to
prove the exploit is dead tests a strawman attacker.

Everything below is my own code. I did not run or trust the builder's tests
until the very end, and then only to check for regression.

---

## 1. Is the flagged gap closed? NO.

### 1.1 What round 4 asked for

> FIX: make `fair_ordering` require a verifier-resolvable EXTERNAL commitment —
> a structured `salt_source` naming a beacon and a **future index chosen before
> its value exists** — not a timestamp comparison; record a self-drawn salt as
> `fair_ordering: False`; and replace the STAKE_SALT special case with the
> general rule "no external commitment => not fair".

### 1.2 What was actually built

Half of it. `is_external_commitment()` checks that `salt_source` is a dict
naming `bitcoin`/`drand` with a positive integer index. That is the **shape** of
a commitment. Nothing checks the two things that make it a commitment:

| Required property | Enforced? | Evidence |
|---|---|---|
| the bound salt actually **equals** the named beacon's value | **NO** | any 64-hex string is accepted at any height |
| the named index is **in the future** relative to the commit | **NO** | `grep -n "future" crash.py` → 9 hits, **all in docstrings and comments, zero in code**; `{"beacon":"bitcoin","height":1}` is accepted |
| the value is even *structurally possible* for that beacon | **NO** | no difficulty/leading-zero check anywhere (`grep -c "leading\|zeros\|difficulty"` → 0) |
| the STAKE_SALT special case replaced by the general rule | **NO** | the special case is still there (`_reject_stake_salt_for_new_chain`), and it is still a single equality test |

Round 4's guard probe — *"any other real pre-existing block hash is ACCEPTED"* —
is verbatim still true. I re-ran it:

```
block1+beacon-height-1           fair_ordering=True  order=terminating_hash_first
genesis+beacon-height-1          fair_ordering=True  order=terminating_hash_first
random+beacon                    fair_ordering=True  order=terminating_hash_first
random+drand                     fair_ordering=True  order=terminating_hash_first
stake salt + beacon 584500       REFUSED
```

Exactly one hex string in the universe is blocked.

### 1.3 The exploit, relocated from salt → seed, and now verifier-proof

Round 4 ground the **salt** against a fixed seed. Round 4's fix made the salt
carry a label. So grind the **seed** against a salt that is a *genuine,
already-published beacon value*. Now the label is true, the beacon resolves, and
the rig survives a verifier who does the out-of-band check.

I used Bitcoin block **1**'s hash
(`00000000839a8e6886ab5951d76f411475428afc90947ee320161bbf18eb6048`, mined
2009-01-09 — published for 17 years, therefore fully known while the chain is
generated).

Grind (`scratchpad/grind_seed.py`, 4 cores, pure Python, no numpy):

```
candidates_tried=1,490,540  elapsed=12.3s  rate=120,710/s
WINNING_SEED=w3-310796
```

Then, entirely through the public API, with `warnings.simplefilter("error")` so
that **any** warning would have aborted the run:

```python
hc = HashChain(secret_seed="w3-310796", length=21)   # commitment exists here
print(hc.terminating_hash)                            # publish it
hc.bind_salt(BLOCK1, salt_source={"beacon": "bitcoin", "height": 1})
hc.crash_points(20)
```

Result — no warning, no error:

```
crash points: [1.5172, 1.1009, 1.0649, 1.2352, 1.5638, 1.4853, 1.5776, 1.3517,
               1.7867, 1.4138, 1.1633, 1.0398, 1.2051, 1.7640, 1.0989, 1.8060,
               1.3171, 1.6633, 1.4372, 1.1994]
max crash point: 1.805979965570859     all < 2.0: True
verify_game_hash steps for games 1..20: [1,2,3,...,20]      <- chain fully valid

{
  "terminating_hash": "8757b90898136aeb7604fc9cfddd30c27875d6fd6326d4588d32568b616bd3c4",
  "terminating_hash_committed_at": "2026-08-24T11:41:33.767970+00:00",
  "salt": "00000000839a8e6886ab5951d76f411475428afc90947ee320161bbf18eb6048",
  "salt_source": {"beacon": "bitcoin", "height": 1},
  "salt_bound_at": "2026-08-24T11:41:33.768030+00:00",
  "salt_revealed_at": null,
  "order": "terminating_hash_first",
  "fair_ordering": true
}
```

Honest chance of 20 consecutive sub-2.0x rounds: `(1 − 0.49499999987892807)^20 =
1.1637e-06`, i.e. 1 in 859,355. A player auto-cashing at 2.0x loses **20/20
rounds, −20.0 units against an EV of −0.2** — a 100% house edge over the window
the operator controls, certified `fair_ordering: true`.

**Why this is worse than round 4's version.** Round 4's ground salt was a random
token; a verifier who actually resolved the named beacon would find a mismatch
and catch it. Here the salt genuinely **is** block 1's hash. The verifier
resolves `bitcoin/height=1`, gets a byte-identical match, and the rig passes.
The only surviving signal is that block 1 is from 2009 — a fact the engine never
asks for (`salt_revealed_at` is `null`, and it is optional) and never checks.
Supplying an honest `revealed_at=2009` *is* refused, which is precisely why an
attacker omits it.

### 1.4 Round 4's literal probe still gets stamped `True`

For completeness I also reran round 4's exact attack (fixed seed, grind the
salt) and simply attached a beacon label instead of a confession:

```
salt-grind: tries=1,379,356 elapsed=12.0s
  crash points all <2.0: True   max: 1.8824
  ENGINE STAMP -> order: terminating_hash_first  fair_ordering: True
```

So the engine's certification behaviour on round 4's own probe is **unchanged**.

### 1.5 The shipped anti-grind gate is a strawman

`tests/test_crash.py::test_ground_salt_attack_is_not_certified_fair` and
`validate_crash.py` check `ground_salt_rig_not_certified_fair` both do this:

```python
hc.bind_salt(rigged, salt_source=f"ground in {tries} tries")
assert hc.fair_ordering is False
```

The attacker is required to **label the salt with a confession**. Change that one
string literal to `{"beacon": "drand", "round": 3366570}` and both gates flip to
`fair_ordering: True` (§1.4). The gate proves only that a cooperative attacker is
not certified. It is not evidence the gap is closed, and it should not have been
presented as such.

### 1.6 What the fix *did* close (credit where due)

- `simulate_chain_targets` default two-phase path → `fair_ordering: False`,
  `order: operator_drawn_after_commitment` (was `True` in round 4). Confirmed.
- `simulate_chain_targets(salt=..., salt_source=<beacon>)` → warns +
  `fair_ordering: False`. Confirmed.
- `simulate_chain_targets(salt=None, salt_source=<beacon>)` → raises. Confirmed.
- Free-text / malformed `salt_source` → not certified. Confirmed.

The *simulator* paths are now honest. The hole is exactly `HashChain.bind_salt`
— the one path the module docstring points to as **"the real protocol"**.

---

## 2. Blind side-by-side (labels stripped)

I took the two "certified-fair" commitment records and stripped every label.
Cell B is not a construct of mine — it is copied verbatim out of the **shipped
validator's own `CRASH_VALIDATION_JSON` PASS artifact**
(`commitment_ordering.external_beacon_commitment_record`).

> **Cell A**
> Commitment `78a9757d3be42b74a3f70239078ad9317125fe9ee630d5bdada46de963e56752`
> published in a public thread, 2019-07-08 06:51 UTC. Salt named in advance
> only as *"a future bitcoin block"*. Salt later resolved to block **584,500**:
> `0000000000000000001b34dc6a1e86083f95500b096231436e9b25cbdd0075c4`, mined
> 2019-07-21. Gap: **13 days**. Anyone can fetch block 584,500 and compare.

> **Cell B**
> Commitment `1ddc9fd7f5c19aa6378ee16a56784df958c0b4e41438ad756dc76fc91be088bf`
> at 2026-08-24T11:45:44.470294Z. Salt
> `6a9f9bd23957e0df34d471a2f278b1500c34cb1f1dd2c84c7a6dcdac1ea6e139` bound at
> 2026-08-24T11:45:44.470402Z. `salt_source: {"beacon":"bitcoin","height":1000000}`.
> `salt_revealed_at: 2026-08-24T11:45:45.470294Z`. `fair_ordering: true`.

An expert picks B as the imitation in seconds, on **three independent tells in
one cell**:

1. **The salt cannot be a Bitcoin block hash at all.** A block hash must be
   below the difficulty target. Cell A's hash has **18 leading zeros**. Cell B's
   salt has **0**. It is arithmetically impossible for any block, at any height,
   ever. The record certifies itself fair while naming a beacon whose value it
   contradicts on inspection.
2. **The named index is in the past, not the future.** Block 1,000,000 was mined
   2019-09-18; the commitment is dated 2026. A "future block" that predates the
   commitment by seven years is not a commitment. The record even asserts
   `salt_revealed_at` = 2026 for it.
3. **108.2 microseconds** between commitment and salt binding, versus 13 days.
   Nothing external can be revealed in 108 µs.

Not a coin flip. This is the single cell that loses the blind, and it loses it
worse than in round 4: round 4's tell was *"the salt came from
`secrets.token_hex`"*; round 5's tell is *"the salt is asserted to be a Bitcoin
block hash that visibly is not one, at a height that visibly is not in the
future, and the engine printed `fair_ordering: true` anyway."* Round 4 was a
missing check. Round 5 is a **false claim in the PASS artifact.**

### Cheapest honest fixes (all offline, no network)

- For `beacon == "bitcoin"`: reject a salt that is not 64 lowercase hex with
  ≥ 8 leading zeros. Two lines. Kills the Cell-B artifact and every random-token
  bind outright.
- Make `revealed_at` **mandatory** whenever `fair_ordering` would be `True`, and
  require `revealed_at > committed_at`. Two lines. Forces the attacker to state
  a falsifiable timestamp instead of `null`, and kills the block-1 seed grind
  (block 1's real time is 2009; a lie is now checkable against the named height).
- Stop asserting a boolean the engine cannot verify. Rename the field
  `fair_ordering_claimed`, or gate the `True` behind an explicit
  `hc.verify_salt_against_beacon(resolved_value, resolved_time)` that a verifier
  calls with data fetched out-of-band. The engine may record a claim; it must
  not certify it.

---

## 3. Core bar re-verification (all independent; engine code not trusted)

### 3.1 Payout-for-payout parity vs the Stake reference — **exact, 0 mismatches**

`scratchpad/parity.py`. HMAC re-implemented from RFC 2104 on top of raw
`hashlib.sha256` (ipad/opad by hand); the crash formula re-typed from
`references/stake/crash.md`; win counts recomputed by my own bisection and
checked with `fractions.Fraction`; every constant re-parsed out of the reference
markdown by regex.

```
PASS  terminating hash == reference
PASS  salt == reference (block 584,500)
PASS  chain length == 10,000,000
PASS  max cashout == 1,000,000x
PASS  house edge == 1.00%
PASS  EDGE_MULTIPLIER is verbatim (1-0.01)          [struct.pack '<d' identical to 0.99]
PASS  formula line present verbatim in ref
PASS  crash_int_from_hash vs scratch RFC-2104 HMAC (20,000 pairs)   mismatches=0
PASS  crash_point_from_int bit-identical (20,110 ints)              diffs=0
PASS  win_count == independent rational bisection (24 targets)      diffs=0
PASS  win_count boundary tight (crash(wc-1)>=w>crash(wc))           bad=0
PASS  |RTP-0.99| <= w/2^32 at every target      worst excess over bound = 0.000e+00
PASS  instant bust P matches independent bisection  P=0.010000000009313226
PASS  instant bust ~ 1%                             |P-0.01|=9.313e-12
PASS  bust boundary int == 4,252,017,623
PASS  crash_point_from_float == formula on recovered int (3,000 floats)
PASS  payout = target iff crash_point >= target else 0

PARITY RESULT: ALL PASS
```

The int probe set includes 0, 1, 2, 2^31±1, 2^32−1, the 101 ints straddling the
instant-bust boundary, and 20,000 random ints; comparison is on the raw IEEE-754
bit pattern, not `==`. Targets span `1+2^-30` to `1,000,000`. The `1e-5`-scale
RTP deviations are the 32-bit quantization inherent in Stake's own published
float64 code, and every one sits inside its `w/2^32` bound with zero excess.

No fudge factors: `grep -nE "[0-9]+\.[0-9]{3,}" crash.py` returns nothing.
WoO handling is correct — JetX's 97%/3% is printed as a labelled comparison
table and never used as a target, exactly as `references/woo/crash.md` requires.

### 3.2 Empirical, ≥10M rounds through the public API — **within 3 SE**

`scratchpad/empirical.py`. SEs computed from **my own** exact analytic `p`
(rational bisection), not the engine's; I additionally assert the engine's
`analytic_win_probability` equals mine to the bit at every target.

**A) 12,000,000 rounds, 13 targets, `simulate_targets` (public API), 9.8 s**

| target | wins | p̂ | p exact | RTP | my z |
|---|---|---|---|---|---|
| 1.01 | 11,762,226 | 0.98018550 | 0.98019802 | 0.98999 | −0.311 |
| 1.10 | 10,801,338 | 0.90011150 | 0.90000000 | 0.99012 | +1.287 |
| 1.50 | 7,923,202 | 0.66026683 | 0.66000000 | 0.99040 | +1.951 |
| 2.00 | 5,942,979 | 0.49524825 | 0.49500000 | 0.99050 | +1.720 |
| 3.00 | 3,960,960 | 0.33008000 | 0.33000000 | 0.99024 | +0.589 |
| 5.00 | 2,376,687 | 0.19805725 | 0.19800000 | 0.99029 | +0.498 |
| 10.00 | 1,187,865 | 0.09898875 | 0.09900000 | 0.98989 | −0.130 |
| 20.00 | 593,130 | 0.04942750 | 0.04950000 | 0.98855 | −1.158 |
| 50.00 | 236,709 | 0.01972575 | 0.01980000 | 0.98629 | −1.846 |
| 100 | 118,495 | 0.00987458 | 0.00990000 | 0.98746 | −0.889 |
| 1,000 | 11,854 | 0.00098783 | 0.00099000 | 0.98783 | −0.239 |
| 10,000 | 1,177 | 0.00009808 | 0.00009900 | 0.98083 | −0.319 |
| 100,000 | 125 | 0.00001042 | 0.00000990 | 1.04167 | +0.569 |

Worst |z| = **1.951**.

**B) Circularity break** — I recounted the same 12M rounds from raw
`BulkRng.floats`, recovering the int and applying my own re-typed formula:
`diffs vs engine = [0,0,0,0,0,0,0,0,0,0,0,0,0]`.

**C) 10,000,000 rounds of Stake's ACTUAL salted-hash-chain mechanism**
(`simulate_chain_targets`, 52.3 s, 191k rounds/s):
z = +1.030 / +0.169 / +0.495 / +0.617 / +1.508 / −0.741 / +0.835 at
w = 1.01/1.5/2/5/10/100/1000. Worst |z| = **1.508**. The run's commitment
record correctly reports `fair_ordering: false`.

**Overall worst |z| across 22M rounds = 1.951 (bar 3.0).**

### 3.3 No regression in the shipped gates

- `pytest tests/test_crash.py` → **75 passed in 2.11 s** (up from 69).
- `python scripts/validate_crash.py` → **OVERALL: PASS, exit 0** (bulk 10M in
  8.1 s @ 1.23M/s; chain 10M in 44.5 s @ 225k/s).

Both pass. Both also pass *while emitting the Cell-B artifact of §2*, which is
the point: the gates do not test the property that matters.

Total compute for this review: ~4 minutes.

---

## 4. Single biggest remaining gap

**`HashChain.bind_salt` still certifies `fair_ordering: True` on a chain I
rigged, and the new beacon rule made the rig verifier-proof instead of killing
it.** `is_external_commitment` validates the *shape* of a beacon claim and never
the *content*: the salt is never compared to the named beacon's value, the index
is never required to be in the future (`"future"` appears 9 times in crash.py —
zero of them in executable code), and no structural sanity check exists (the
shipped validator's own certified-fair record binds a salt with **0 leading
zeros** while calling it Bitcoin block 1,000,000, which is impossible, and dates
a 2019 block as revealed in 2026). Grinding the **seed** against an
already-published beacon value — Bitcoin block 1 — bought me, in **12.3 s of
4-core pure Python**, a fully chain-verifiable 20-round window in which every
round busts below 2.0x (honest chance 1.16e-06; player −20/20 units at a 2.0x
auto-cashout), stamped `order: terminating_hash_first, fair_ordering: true`,
with **no warning and no error**, and — unlike round 4's exploit — a salt that
*matches* the beacon it names, so an out-of-band verifier confirms it. The
builder's own anti-grind gate misses this because it forces the attacker to
label the ground salt `f"ground in {tries} tries"`; swap that literal for
`{"beacon":"drand","round":3366570}` and the gate flips to `True`. Minimum fix:
require ≥ 8 leading zeros for `beacon == "bitcoin"`, make `revealed_at`
mandatory and `> committed_at` for any `fair_ordering: True`, and either rename
the field `fair_ordering_claimed` or gate the boolean behind an explicit
`verify_salt_against_beacon(resolved_value, resolved_time)` the verifier calls
with out-of-band data. The core math is untouched by all of this and is
flawless — 0 payout mismatches against a from-scratch RFC-2104 HMAC over 20,000
pairs and a re-typed formula over 20,110 ints, worst |z| = 1.951 over 22M
public-API rounds.
