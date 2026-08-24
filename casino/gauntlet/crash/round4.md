# Gauntlet — Crash, Round 4 (independent critic, fresh eyes)

Piece: `spinquest_sim/games/crash.py`, `scripts/validate_crash.py`, `tests/test_crash.py`
Ground truth: `references/stake/crash.md` (payout math), `references/woo/crash.md` (comparison only)
Date: 2026-08-24.

Every number below comes from a script I wrote in this session
(`/tmp/.../scratchpad/{indep_math,indep_sim,probe_order,probe_edges,seed_shop,tail}.py`).
The builder's tests were read only for fudge-hunting, never used as evidence.
**235,400,000 rounds simulated by me through the engine's public API**, plus the
20,000,000 the shipped validator runs.

---

## Verdict

**ours does NOT win round 4.**

| Gate | Result |
|---|---|
| Payout / probability parity with the reference | **PASS** — exact, 33/33 targets, 0 differences vs exact-rational recomputation |
| Empirical stats within 3 SE over 10M+ rounds | **PASS** — 235.4M rounds, worst \|z\| = 2.10, every GOF test clean |
| Blind comparison a coin flip or favouring ours | **FAIL** — the provable-fairness artifact still identifies ours on sight |

The math is finished and I could not dent it. What loses the blind is the *same cell* rounds 1
and 3 lost on — and round 4's fix, while real, hardened the wrong half of it. **The fix moved the
grindable free variable from the secret seed to the salt, made grinding ~2× cheaper than round 3's
exploit, and now stamps the rigged result `fair_ordering: True`.**

---

## 0. What actually changed since round 3

| Round 3 finding | Status |
|---|---|
| **F1** fresh chain bound by default to Stake's public 2019 salt | **fixed** (`CommitmentOrderError`, two-phase protocol, `commitment` record) — but see §5 |
| **F2** validator: 1 seed/mechanism, no distribution-level test | **unfixed** (`DEFAULT_TARGETS`, seeds, gate contents byte-identical) |
| **F3** `DEFAULT_TARGETS` stops at 1000× while the table runs to 1e6 | **unfixed** |
| **F4** no public vectorized crash-point generator | **unfixed** (`_crash_points_from_ints` was deleted rather than promoted) |
| **F5** full-float crash points, no 2-decimal display | **unfixed** |
| **F6** `build_hash_chain` capped at 2,000,000 | **unfixed** |

`crash.py` mtime 2026-08-24 07:19:48, `validate_crash.py` 07:18:15 — both after round 3
(06:34:26). The diff is the commitment-ordering work and nothing else.

---

## 1. Independent recomputation of the reference math

Nothing on my reference side imports engine helpers. HMAC-SHA256 rebuilt from RFC 2104
(`sha256(opad‖sha256(ipad‖msg))`, no `hmac` module); `win_count` seeded from exact rationals
(`fractions.Fraction`) and confirmed by re-evaluating the **actual float64 formula** at `n−1`/`n`.

| # | Check | Method | Result |
|---|---|---|---|
| 1 | `int` extraction | from-scratch RFC 2104 HMAC → `digest.hex()[0:8]` → `int(...,16)`, 20,000 random (hash, salt) pairs | **0 mismatches** |
| 2 | crash formula | bit-for-bit (`struct.pack('<d')`) vs engine, 20,110 ints incl. 0, 1, 2³¹±1, 2³²−1 and the whole bust boundary ±50 | **0 bit-mismatches** |
| 3 | instant bust | first busting int found independently = **4,252,017,623** → P = 42,949,673/2³² = 0.010000000009313226 | engine **identical** |
| 4 | `win_count` | exact-rational seed + ±10 scan of the real float64 formula, **33 targets** from 1+2⁻³⁰ to 1,000,000 | **0 differences** |
| 5 | monotonicity (bisection premise) | 300,000 sorted random ints | holds everywhere |
| 6 | hash chain | own 2,001-hash chain (SHA-256 over the ASCII hex) vs `build_hash_chain`, pop order, `verify_game_hash` | identical; game *g* verifies in exactly *g* steps; unrelated hash → `None` |
| 7 | seed-pair float→int | `generate_floats` == `k/2³²` and `int(f·2³²)==k` exactly, 300 nonces | exact |

### Payout-for-payout vs the reference (extract; 33 targets checked, 0 differences)

```
      target     indep_wc    engine_wc  diff       P(win)       0.99/w          RTP  |RTP-.99|    w/2^32
        1.01   4209918438   4209918438     0  0.9801980196 0.9801980198 0.9899999998  1.54e-10  2.35e-10
         1.5   2834678415   2834678415     0  0.6599999999 0.6600000000 0.9899999999  1.26e-10  3.49e-10
        1.98   2147483648   2147483648     0  0.5000000000 0.5000000000 0.9900000000  0.00e+00  4.61e-10
           2   2126008811   2126008811     0  0.4949999999 0.4950000000 0.9899999998  2.42e-10  4.66e-10
          10    425201762    425201762     0  0.0989999999 0.0990000000 0.9899999993  7.08e-10  2.33e-09
         100     42520176     42520176     0  0.0098999999 0.0099000000 0.9899999946  5.36e-09  2.33e-08
        1000      4252017      4252017     0  0.0009899999 0.0009900000 0.9899998549  1.45e-07  2.33e-07
       10000       425201       425201     0  0.0000989998 0.0000990000 0.9899982251  1.77e-06  2.33e-06
       99999        42520        42520     0  0.0000099000 0.0000099001 0.9899859969  1.40e-05  2.33e-05
       1e+06         4252         4252     0  0.0000009900 0.0000009900 0.9899958968  4.10e-06  2.33e-04
```

Worst `|RTP − 0.99| = 1.4003e-05` at w = 99,999, against its bound `w/2³² = 2.33e-05`.
Every deviation is the 32-bit quantization of **Stake's own published code**, and every one is
under the bound. A hard-coded "RTP = 0.99 exactly" column would be *less* faithful.

Boundary exactness spot-checked: at each of w = 1.01 / 2 / 10 / 1000 / 1e6, `crash(wc−1) ≥ w`
and `crash(wc) < w`. The `ints < win_count` shortcut the chain simulator uses is therefore
exactly equivalent to `crash_point >= target` — verified again empirically in §3 Run E.

---

## 2. Shipped gates, run by me

- `python scripts/validate_crash.py` (defaults: 10M bulk + 10M chain) → **OVERALL: PASS**, exit 0.
  Bulk 616k rounds/s (16.2 s), chain 226k rounds/s (44.3 s — the honest cost of 2 SHA-256 +
  1 HMAC per round; a faked chain would be ~100× faster). Worst \|z\|: 0.999 bulk, 1.916 chain.
- `pytest tests/test_crash.py -q` → **69 passed** in 2.34 s.

---

## 3. My own empirical bar — my own SE, my own z

`SE = √(p(1−p)/n)` from the **exact analytic** p (recomputed by me), never from engine fields.
I additionally asserted the engine's own `z_score` equals mine to <1e-6 at all 13 targets (it does).

**Run A — 12,000,000 rounds, one shared stream, 13 targets** (19.3 s, 621k rounds/s).
Worst \|z\| = **1.485** (w = 1e6). All 13 PASS; exact binomial two-sided p ≥ 0.14 everywhere,
so the normal 3-SE gate is not doing the work in the tail.

**Run B — independent stream per target, 2M each, 8 targets** (valid omnibus, uncorrelated z's):
`Σz² = 6.46, df = 8, p = 0.595`.

**Run C — circularity break, 12,000,000 rounds.** I rebuilt crash points **myself** from
`BulkRng.floats` with my own formula and counted my own wins, then ran `simulate_targets` on the
identical stream:

```
engine wins − my independent recount, per target: [0,0,0,0,0,0,0,0,0,0,0,0,0]
```

Distribution-level tests on the same 12M rounds (the shipped validator does **none** of these):

| Test | statistic | p |
|---|---|---|
| χ² uniformity, high 12 bits (`k>>20`), 4096 bins | 4035.9, df 4095 | 0.742 |
| χ² uniformity, low 12 bits (`k&4095`), 4096 bins | 4025.6, df 4095 | 0.778 |
| χ² over 18 multiplier bands vs exact `win_count` differences | 12.72, df 17 | 0.755 |
| lag-1 serial correlation of `k/2³²` | r = +0.000036 (z = +0.12) | — |
| instant-bust rate 120,587/12M = 0.010048917 vs exact 0.010000000009 | z = +1.703 | — |

Max multiplier observed 20,541,147.94× (formula max 4,252,017,623.04×).

**Run E — chain mechanism, 200,000 rounds, recounted from public `HashChain.crash_points`**
(breaks the engine's `int < win_count` shortcut): 132,261 / 99,315 / 19,987 / 1,946 at
w = 1.5 / 2 / 10 / 100 — **identical** to `simulate_chain_targets`; terminating hashes match.

**Run F — deep tail, 96,000,000 rounds, 8 independent seeds** — the regime the shipped
validator never simulates (its grid stops at 1000×):

```
  w=10000    wins=  9,540  expected=  9504.0  z=+0.369  exact binom p=0.712  RTP=0.993750
  w=100000   wins=    931  expected=   950.4  z=-0.629  exact binom p=0.548  RTP=0.969792
  w=1e+06    wins=     97  expected=    95.0  z=+0.201  exact binom p=0.837  RTP=1.010417
```

All within 3 SE, and round 3's transient −2.9 at w = 100,000 does not replicate at 96M rounds.

**Run G — nonce accounting across chunk boundaries** (`chunk_rounds=997`, 7000 rounds from
nonce 37): engine wins `[4603, 3441]` == my scalar recount from `generate_floats(37+i)`;
reported `nonce_range = (37, 7037)`. No reuse, no gap.

---

## 4. Fudge hunt

- **Hardcoded empirical results: none.** `grep -nE "[0-9]+\.[0-9]{3,}"` over `crash.py` returns
  nothing. The only constants are `2**32`, `1 - 0.01`, `0.01`, `1_000_000`, `10_000_000` and the
  2019 hash/salt — and all are re-parsed out of `references/stake/crash.md` by
  `check_spec_parity()` and asserted equal. Tests contain no hardcoded probability literals either.
- **Sim not using the engine: false alarm.** Bulk genuinely pulls `BulkRng.floats` (12M-round
  scalar-equivalent recount, §3 Run C, plus a 7-chunk nonce audit); chain genuinely walks SHA-256
  at 226k rounds/s.
- **Was the validator's single fixed seed cherry-picked? NO.** I re-ran its exact 7-target grid
  with **6 different server seeds × 10,000,000 rounds** and **3 different chain secrets ×
  5,000,000 rounds**:

  ```
  bulk  v1..v6 worst |z| = 0.999, 2.004, 1.389, 1.309, 1.290, 0.750   → all PASS
  chain v1..v3 worst |z| = 1.528, 1.414, 2.095                        → all PASS
  ```

  Per-seed cluster means (the 7 z's inside one seed are nested events on one stream and are
  strongly correlated, so only the 6 cluster means are independent):
  `+0.271, −0.782, +0.592, +0.544, +0.357, +0.392` → t = +1.101, **p = 0.321**. Clean. The
  shipped seed is not special. (A naive KS of all 42 correlated z's against N(0,1) gives
  p = 0.0015 — that statistic is invalid here, and I am reporting it only so it is not
  mistaken later for a defect.)
- **Vacuous check (still there):** the empirical `std_per_unit` is `w·√(p̂(1−p̂))`, algebraically
  determined by the win rate — comparing it to `analytic_std_per_unit` adds nothing over the z-test.
- **Edge cases:** target ≤ 1, ≥ 1e6+ε, ±inf, nan rejected; `1+2⁻⁵²` accepted; `crash_point_from_int`
  range-checked; `crash_point_from_float(1.0)` rejected, `(0.0)` → 4,252,017,623.04; `n_rounds ≤ 0`
  rejected; chain exhaustion raises; `build_hash_chain` rejects len < 2 and > 2,000,000. All confirmed.
  (Nit: `simulate_targets(targets=[], ...)` silently burns nonces and returns an empty row list.)
- **Max-cashout cap:** crash points above 1,000,000× do occur (P = 9.9e-07) but `Crash(w)` never
  pays more than `w` and `w ≤ 1e6` is enforced, so the published cap holds by construction.
- **WoO handling: correct.** JetX (97% / 3% / tick mechanism) is printed as a labelled comparison
  whose `pass` depends only on the shared shape (`P = RTP/w`, flat edge) and the Wizard's own 3×
  worked example — never on 97% matching. The ~2 pp gap is stated as expected in three places.

---

## 5. Blind comparison — labels stripped

### 5a. Numeric payout / probability artifact

| target | Column A: P(win) / RTP | Column B: P(win) / RTP |
|---|---|---|
| 1.01 | 0.9801980198 / 0.990000000000 | 0.9801980196 / 0.989999999846 |
| 2 | 0.4950000000 / 0.990000000000 | 0.4949999999 / 0.989999999758 |
| 10 | 0.0990000000 / 0.990000000000 | 0.0989999999 / 0.989999999292 |
| 1 000 | 0.0009900000 / 0.990000000000 | 0.0009899999 / 0.989999854937 |
| 100 000 | 0.0000099000 / 0.990000000000 | 0.0000099000 / 0.989995896816 |
| P(bust) | 0.010000000000 | 0.010000000009 |

**Coin flip, arguably favouring B.** A is the reference document's *derived* closed form (which the
reference itself labels "Derived properties (ours…)"); B is the engine. An expert who actually
reruns `Math.max(1,(2**32/(int+1))*(1-0.01))` over all 2³² ints gets **B**. B reads as the one
that was computed rather than idealized. **Ours wins this artifact.**

### 5b. Provable-fairness artifact — ours still gives itself away

Both rows below are verbatim: X from `references/stake/crash.md`, Y from the
`CRASH_VALIDATION_JSON` / `[order]` line of the run I did in §2.

| | Artifact X | Artifact Y |
|---|---|---|
| terminating hash | `78a9757d…e56752` | `c9364469cb89c60f…` |
| published | 2019-07-08, public forum thread | 2026-08-24T08:02:23.**380307**Z, in-process |
| salt | Bitcoin block **584,500** — block *number* named in advance, value unknowable | `d61c702e2d2aea53…` |
| salt bound | 2019-07-21 (block mined **13 days later**) | 2026-08-24T08:02:23.**380337**Z — **30 microseconds later** |
| salt source | an uncontrollable public blockchain | `"drawn after terminating-hash commitment"` (`secrets.token_hex(32)`, same process) |
| third party can independently look up the salt? | yes | **no** |
| engine's own verdict | — | `fair_ordering: True` |

Y is ours. **Any provable-fairness reviewer picks Y as the imitation on the "30 µs" cell alone.**
A salt bound 30 microseconds after the commitment did not come from a future block; it came from
the same function call.

### 5c. I rigged the "fair" chain in 5.3 seconds

The round-3 fix committed the chain first — but the chain's game hashes **do not depend on the
salt**, so once the chain is committed the salt is a free variable and grinding it costs *one HMAC
per candidate per round* instead of a full chain walk. That is **cheaper** than the attack round 3
demonstrated:

```
committed terminating hash: d36b99c1c56f870221570e84abc34e35925abb0af3160f4424d5114dfd9801c1
GRIND: found after 516,701 candidate salts in 5.3s (96,878 salts/s, pure Python, 1 core)
  honest chance of 20 straight sub-2x rounds = 1.164e-06
  winning salt: fd727075e29da7bd938b79f1f60a49b2a71355fa0ef97f79a46c7f378c7ca41d
  first 20 crash points: [1.81, 1.01, 1.69, 1.04, 1.35, 1.23, 1.11, 1.67, 1.25, 1.0,
                          1.99, 1.51, 1.07, 1.06, 1.11, 1.66, 1.06, 1.0, 1.18, 1.26]

ENGINE VERDICT ON THE RIGGED CHAIN:
  order         = terminating_hash_first
  fair_ordering = True
  wins at 2x over first 20 rounds = 0
```

(Round 3 needed 11 s for 18 rounds; this needs 5.3 s for 20. A C implementation at ~2M/s rigs
30+ rounds.) Over that window a player auto-cashing at 2× faces a **99% house edge instead of 1%**.

And it does not even need `bind_salt`: the **default** "honest two-phase" entry point self-draws
the salt, so simply calling it again is a re-roll —

```
re-rolling simulate_chain_targets([2.0], 12, secret_seed=SEED) 2,568 times (0.3s)
yields 12/12 player losses at 2x, stamped fair_ordering=True, order='terminating_hash_first'
```

**Guard probes.** The blocklist is a single equality test against `STAKE_SALT`; everything else
is accepted, and `revealed_at` is an unverified operator-supplied number:

```
bind_salt(no revealed_at attestation)                : ACCEPTED  -> fair_ordering True
bind_salt(revealed_at == committed_at exactly)       : ACCEPTED  -> fair_ordering True
bind_salt(STAKE_SALT.upper())                        : ACCEPTED
bind_salt("0x" + STAKE_SALT)                         : ACCEPTED
bind_salt(some other real 2019 bitcoin block hash)   : ACCEPTED
HashChain(salt=<pre-existing>)                       : warning only, suppressible with -W ignore
```

The module's own comment states the criterion correctly — *"salt from an uncontrollable source
second — is the entire guarantee"* — but `fair_ordering` only tests **timestamp order**, which is
necessary and nowhere near sufficient. The flag claims a property the code does not check.

### 5d. Round-history artifact — a second, cheaper tell

| Column A | Column B |
|---|---|
| `1.06x 1.14x 10.41x 5.71x 2.62x 3.48x 5.27x 1.09x 1.27x 2.62x 1.00x 1.08x` | `1.0657339040203118x 1.1458031444116803x 10.416489716603229x 5.719696974346783x 2.625360704459204x 3.4813997683324733x 5.27379636052282x 1.0921658000001366x 1.27442141632336x 2.6298166974642982x 1.0x 1.0890093194044974x` |

B is ours. Instant identification. Payout-neutral for 2-decimal targets
(`⌊100c⌋/100 ≥ w ⟺ c ≥ w`) and the reference is silent on display rounding, so it does not touch
the math gates — but it is a blind tell for one line of code.

---

## 6. Findings, ranked

**F1 (biggest gap). `fair_ordering: True` is asserted for a salt the operator drew itself —
the engine certifies as fair a chain I rigged in 5.3 seconds.** The round-3 fix hardened
commitment *ordering* but left the salt's *provenance* unchecked, which simply relocated the grind
(seed → salt) and made it cheaper, because game hashes are salt-independent once the chain is
committed. Fix, ~10–15 lines, no network needed:
1. `fair_ordering` must require a **verifier-resolvable external commitment** — a structured
   `salt_source` naming a beacon and a future index (`{"beacon":"bitcoin","height":N}`,
   `{"beacon":"drand","round":R}`) chosen *before* its value exists — not a timestamp comparison.
2. A self-drawn `secrets.token_hex` salt must record
   `order: "operator_drawn_after_commitment", fair_ordering: False` and say in one sentence that
   it is a reproducible-simulation convenience, not the published guarantee.
3. Drop the `salt == STAKE_SALT` special case for a general rule: no external commitment ⇒ not fair.
   (Keep the `STAKE_SALT` refusal as a special-cased *hint*, not as the mechanism.)

That single change turns blind cell 5b from a giveaway into an honest "reproducible-simulation
mode" label, which an expert reads as candour rather than imitation.

**F2. The shipped validator's empirical gate is still thinner than the engine deserves.**
7 marginal tail probabilities, **one** fixed seed per mechanism, no distribution-level test, no
empirical instant-bust z. I ran the missing tests (§3 Run C) and the missing seed sweep (§4) and
**every one passes comfortably** — so this is an evidence gap, not an engine gap. But the validator
is the artifact that stands for "we validated this". Add the band χ², the low-bit χ², the
instant-bust z and a 3-seed sweep: ~30 lines. *Unfixed since round 1.*

**F3. `DEFAULT_TARGETS` stops at 1000× while `PAYTABLE_TARGETS` runs to 1,000,000×.** I ran 96M
rounds at 10⁴/10⁵/10⁶ and all pass (z = +0.37/−0.63/+0.20), so extend the empirical grid; it costs
nothing and closes the "conveniently avoided regime" objection. *Unfixed since round 1.*

**F4. No public vectorized crash-point generator.** `simulate_targets` builds the crash-point array
and discards it; the only public sequence source is `HashChain.crash_points`, O(n) Python and capped
at 2M. Anything downstream (multiplier histogram, the two-simultaneous-bets pattern the WoO
reference describes, manual cashout, laddering) must re-derive the formula. Round 3 asked for this;
round 4 *deleted* the dead `_crash_points_from_ints` instead of promoting it to
`crash_points(n, bulk=…) -> np.ndarray`. *Unfixed.*

**F5 (nit). Crash points emitted at full float precision** where a real Stake history is 2-decimal
(§5d). One `display_crash_point` helper. The engine also accepts targets the real game does not
offer (`1.000001×`). *Unfixed.*

**F6 (nit).** `build_hash_chain` cannot build the published 10,000,000-hash chain
(`_MAX_STORED_CHAIN = 2,000,000`); only the streaming aggregate path reaches Stake scale, so random
access to a Stake-scale game hash is unavailable. *Unfixed.*

**F7 (project-level, not crash's fault).** `harness.py`, `selector.py`, `report.py`,
`games/__init__.py`, `mcp_server/` are stubs — no game is wired into the harness the README
advertises.

---

## 7. Bottom line

On numbers this piece is done, and round 4 hardened that further rather than softening it:
bit-exact against a from-scratch RFC-2104 HMAC; `win_count` exact against rational arithmetic at
33 targets from 1+2⁻³⁰ to 10⁶ with **zero** differences; worst |RTP − 0.99| = 1.4e-05 and always
under the 32-bit bound; **235.4M rounds** inside 3 SE with worst |z| = 2.10, an independent-stream
omnibus p = 0.595, high-bit χ² p = 0.742, low-bit χ² p = 0.778, band χ² p = 0.755, lag-1 z = +0.12;
the deep tail clean at 96M rounds; the validator's seed shown **not** cherry-picked over 6 alternates
(p = 0.321); zero hardcoded empirical values anywhere in the module.

It loses the blind on one artifact, for the third round running: **a salt bound 30 microseconds
after the commitment, drawn by the operator's own process, and stamped `fair_ordering: True`.**
Round 3's fix was real but half-length — it checked *when* the salt arrived and never *where from*,
which relocated the grind rather than closing it, and I rigged 20 straight sub-2× rounds in
5.3 seconds that the engine certifies as fairly ordered. Make `fair_ordering` mean "bound to an
externally verifiable beacon commitment", label the self-drawn salt honestly, and crash wins.
