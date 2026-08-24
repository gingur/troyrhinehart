# Gauntlet — Crash, Round 3 (independent critic, fresh eyes)

Piece: `spinquest_sim/games/crash.py`, `scripts/validate_crash.py`, `tests/test_crash.py`
Ground truth used: `references/stake/crash.md` (payout math), `references/woo/crash.md` (comparison only)
Date: 2026-08-24. Every number below comes from a script I wrote in this session. The builder's
tests were read for fudge-hunting, never used as evidence.

## Verdict

**ours does NOT win round 3.** The math is flawless — I could not dent it with exact-rational
arithmetic, a from-scratch RFC-2104 HMAC, 91M independent rounds, or seven distribution-level
tests. It loses on the same single non-numeric count round 1 named, and that count is **worse than
last round, not better: the code has not been touched since round 1 reviewed it**, and I have now
*demonstrated* the exploit round 1 only asserted.

> `spinquest_sim/games/crash.py` mtime = **2026-08-24 01:08:39**
> `gauntlet/crash/round1.md` mtime = **2026-08-24 03:56:25**
> `gauntlet/crash/round2.md` — **does not exist**
>
> Round 1's F1 ("biggest gap"), F2, F3, F4, F5, F6 are all still present, verbatim. Round 3 is
> reviewing a byte-identical artifact.

---

## 1. Independent recomputation of the reference math

`/tmp/.../indep_math.py` — nothing on the reference side imports engine helpers.

| # | Check | Method | Result |
|---|---|---|---|
| 1 | `int` extraction | HMAC-SHA256 rebuilt from RFC 2104 (`sha256(opad‖sha256(ipad‖msg))`, no `hmac` module), then `digest.hex()[0:8]` → `int(...,16)` exactly as `parseInt(hex.substr(0,8),16)`. 30,000 random game hashes. | **0 mismatches** |
| 2 | crash-point formula | `np.maximum(np.float64(1), (np.float64(2**32)/np.float64(i+1))*(np.float64(1)-np.float64(0.01)))`, compared **bit-for-bit** (`view(uint64)`) to the engine. 30,000 hashes + 5,021 adversarial ints (0, 1, 2³¹±1, 2³²−1, the whole bust boundary ±5) | **0 bit-mismatches** |
| 3 | `win_count(w)` | Exact-rational seed `⌊2³²·F(fl(0.99))/F(w)⌋` (`fractions.Fraction`), then a ±8 scan re-evaluating the **actual float64 formula** at `n−1` and `n`. 30 targets, 1+2⁻³⁰ … 1,000,000 | **0 differences**, every boundary confirmed |
| 4 | monotonicity (the bisection's premise) | 200,000 sorted random ints, `diff ≤ 0` everywhere | holds |
| 5 | instant bust | first busting int found independently = **4,252,017,623** → P = 42,949,673/2³² | engine **identical** |
| 6 | hash chain | own 2,001-hash chain (`sha256` over the ASCII hex of the previous hash); compared `build_hash_chain`, `HashChain` pop order, `verify_game_hash` step counts, and the private streamed walk (n=1,000) | identical; game *g* verifies in exactly *g* steps; unrelated hash → `None` |
| 7 | seed-pair float→int | `generate_floats` == `k/2³²` exactly, 400 nonces | exact |
| 8 | circularity break | `simulate_targets` win counts vs my own scalar recount of 5,000 crash points computed from `generate_floats` at nonce `n₀+i` | exact match at w = 1.5 / 2 / 10 |

**Total independent failures: 0.**

### Payout-for-payout vs the reference (30 targets, exact rational vs engine)

```
      target     indep_wc    engine_wc  diff       P(win)      0.99/w          RTP  |RTP-.99|   w/2^32
        1.01   4209918438   4209918438     0  0.9801980196 0.9801980198 0.9899999998   1.54e-10  2.35e-10
         1.5   2834678415   2834678415     0  0.6599999999 0.6600000000 0.9899999999   1.26e-10  3.49e-10
        1.98   2147483648   2147483648     0  0.5000000000 0.5000000000 0.9900000000   0.00e+00  4.61e-10
           2   2126008811   2126008811     0  0.4949999999 0.4950000000 0.9899999998   2.42e-10  4.66e-10
          10    425201762    425201762     0  0.0989999999 0.0990000000 0.9899999993   7.08e-10  2.33e-09
         100     42520176     42520176     0  0.0098999999 0.0099000000 0.9899999946   5.36e-09  2.33e-08
        1000      4252017      4252017     0  0.0009899999 0.0009900000 0.9899998549   1.45e-07  2.33e-07
       10000       425201       425201     0  0.0000989998 0.0000990000 0.9899982251   1.77e-06  2.33e-06
       99999        42520        42520     0  0.0000099000 0.0000099001 0.9899859969   1.40e-05  2.33e-05
       1e+06         4252         4252     0  0.0000009900 0.0000009900 0.9899958968   4.10e-06  2.33e-04
```

`max |engine_wc − indep_wc| = 0` over all 30 targets (including 1+2⁻³⁰, 1.000001, 999, 1001, 9999,
500000, 999999 — targets the shipped grid never touches). Worst `|RTP − 0.99| = 1.4003e-05` at
w = 99,999, against its bound `w/2³² = 2.33e-05`. **Every deviation is the 32-bit quantization of
Stake's own formula, and every one is below the bound.** An "RTP = 0.99 exactly" column would be
*less* faithful to the published code, not more.

---

## 2. Shipped gates, run by me

- `python scripts/validate_crash.py` (defaults: 10M bulk + 10M chain) → **OVERALL: PASS**, exit 0,
  ~57 s. Worst |z| = 0.999 (bulk), 1.352 (chain). Bulk 835k rounds/s, chain 231k rounds/s (the
  honest cost of 2 SHA-256 + 1 HMAC per round — a faked chain would be ~100× faster).
- `pytest tests/test_crash.py -q` → **57 passed** in 2.05 s.

---

## 3. My own empirical bar — 91,000,000 rounds, my own SE

All sims through the **public API** (`simulate_targets`, `simulate_chain_targets`, `HashChain`).
SE and z computed by me as `SE = √(p(1−p)/n)` from the **exact analytic** p; the engine's own
`z_score`/`se_rtp` were asserted equal to mine to <1e-7 (they are).

**Run A — 12,000,000 rounds, one shared stream, 10 targets** (9.0 s, 1.33M rounds/s):

```
       w       wins         p_hat       p_exact       my_SE    my_z        RTP   3SE(RTP)   ok
    1.01   11763062   0.980255167   0.980198020   4.022e-05  +1.421   0.990058   1.22e-04 PASS
     1.1   10799942   0.899995167   0.900000000   8.660e-05  -0.056   0.989995   2.86e-04 PASS
     1.5    7919389   0.659949083   0.660000000   1.367e-04  -0.372   0.989924   6.15e-04 PASS
       2    5940471   0.495039250   0.495000000   1.443e-04  +0.272   0.990078   8.66e-04 PASS
       3    3960077   0.330006417   0.330000000   1.357e-04  +0.047   0.990019   1.22e-03 PASS
       5    2376194   0.198016167   0.198000000   1.150e-04  +0.141   0.990081   1.73e-03 PASS
      10    1188629   0.099052417   0.099000000   8.622e-05  +0.608   0.990524   2.59e-03 PASS
      50     236535   0.019711250   0.019800000   4.022e-05  -2.207   0.985563   6.03e-03 PASS
     100     118022   0.009835167   0.009900000   2.858e-05  -2.268   0.983517   8.57e-03 PASS
    1000      11917   0.000993083   0.000990000   9.078e-06  +0.340   0.993083   2.72e-02 PASS
```
worst |z| = 2.268 (these are nested events on one stream, so the w=50/100 pair is one excursion).

**Run B — independent stream per target, 2M rounds each, 16,000,000 rounds total** (this is a test
neither the validator nor round 1 ran: the z's are genuinely independent, so `Σz²` is a valid
omnibus): z = +0.858, −0.645, +2.124, +0.826, +1.278, +0.402, +0.321, +2.136 →
**Σz² = 12.81, df = 8, p = 0.119.** Clean.

**Run C — extreme targets, 10,000,000 rounds:** w = 1+2⁻²⁰ z=+2.385, 1.005 z=+1.499,
10,000 z=−0.540, 100,000 z=**−2.915**, 1,000,000 z=−0.922. All inside 3 SE, but the w=100,000 cell
(70 observed vs 99.0 expected) has an *exact* binomial two-sided p = **0.0027** — the normal-approx
3-SE gate is generous at λ≈100. So I replicated it: **4 fresh seeds × 10M rounds at w = 10⁴/10⁵/10⁶**

```
POOLED w=10000   n=40,000,000 wins=3996 exp=3960.0 z=+0.572 exact p=0.5713
POOLED w=100000  n=40,000,000 wins= 394 exp= 396.0 z=-0.100 exact p=0.9466
POOLED w=1e+06   n=40,000,000 wins=  31 exp=  39.6 z=-1.367 exact p=0.1910
```
It does not replicate — the −2.9 was a fluctuation. **The extreme tail is clean at 40M rounds.**

**Run D — distribution-level GOF, 12,000,000 rounds** (the shipped validator does none of this):

| Test | statistic | p |
|---|---|---|
| χ² uniformity of the **high** 12 bits (`k>>20`), 4096 bins | 4141.5, df 4095 | 0.302 |
| χ² uniformity of the **low** 12 bits (`k&4095`), 4096 bins — *new; round 1 only binned high bits, which is what matters for the boundary at large w* | 4078.4, df 4095 | 0.570 |
| χ² over 41 multiplier bands vs exact `win_count` differences | 34.5, df 40 | 0.716 |
| lag-1 serial correlation of consecutive ints (**new**) | r = +0.000354 (z = +1.23) | — |
| instant bust rate | 119,957/12M = 0.00999642 vs exact 0.010000000009 | z = −0.125 |

Max multiplier observed: 17,145,232.35× (formula max 4,252,017,623.04×).

**Run E — chain mechanism, 1,000,000 rounds, wins recounted from crash points** via public
`HashChain.crash_points`, which breaks the engine's `int < win_count` shortcut:
w=1.5 → 659,816 (engine 659,816); w=2 → 494,676 (494,676); w=10 → 98,598 (98,598);
w=1000 → 933 (933). Exact; terminating hashes match.

**Run F — multi-chunk nonce accounting (new).** `simulate_targets(..., chunk_rounds=1000)` over
7,000 rounds from `nonce_start=37`: engine wins == my scalar recount from
`generate_floats(nonce 37+i)` at w=1.5 and w=2; reported `nonce_range = (37, 7037)`. No nonce reuse
or gap across chunk boundaries.

**Totals: 91,000,000 independent rounds through the public API; 0 gate failures; worst pooled |z| = 2.268.**

---

## 4. Blind comparison — labels stripped

### 4a. Numeric artifact

| target | Column A: P(win) / RTP | Column B: P(win) / RTP |
|---|---|---|
| 1.01 | 0.9801980198 / 0.990000000000 | 0.9801980196 / 0.989999999846 |
| 1.5 | 0.6600000000 / 0.990000000000 | 0.6599999999 / 0.989999999874 |
| 2 | 0.4950000000 / 0.990000000000 | 0.4949999999 / 0.989999999758 |
| 10 | 0.0990000000 / 0.990000000000 | 0.0989999999 / 0.989999999292 |
| 100 | 0.0099000000 / 0.990000000000 | 0.0098999999 / 0.989999994636 |
| 1 000 | 0.0009900000 / 0.990000000000 | 0.0009899999 / 0.989999854937 |
| 10 000 | 0.0000990000 / 0.990000000000 | 0.0000989998 / 0.989998225123 |
| 1 000 000 | 0.0000009900 / 0.990000000000 | 0.0000009900 / 0.989995896816 |
| P(bust) | 0.010000000000 | 0.010000000009 |
| SD @ w=10 | 2.9866201633 | 2.9866201624 |

**Coin flip, arguably favouring B.** A is the reference document's *derived* closed form (`0.99/w`,
which the reference itself labels "Derived properties (ours…)"); B is the engine. An expert who
actually reruns `Math.max(1,(2**32/(int+1))*(1-0.01))` over all 2³² ints gets **B**. B does not read
as the imitation — it reads as the one that was computed rather than idealized.

### 4b. Provable-fairness artifact — ours still gives itself away

| | Artifact X | Artifact Y |
|---|---|---|
| published terminating hash | `78a9757d…e56752`, published **2019-07-08** | `6599d236…5b3e44bf`, generated **2026-08-24** |
| salt (client seed) | block 584,500 hash, mined **2019-07-21** | block 584,500 hash, mined **2019-07-21** |
| chain length | 10,000,001 | 10,000,001 |
| commitment ordering | salt was **unknowable** when the chain was committed | salt was public **7 years before** the chain existed |
| can the operator choose the outcome sequence? | no | **yes — demonstrated below** |

Y is ours, verbatim from the `verification` dict in this run's `CRASH_VALIDATION_JSON`. Any
provable-fairness reviewer picks Y as the imitation on sight, and the last row is why.

**I demonstrated the exploit** (round 1 only asserted it). Grinding candidate secret seeds against
the *already-public* 2019 salt, in pure Python, single core:

```
grind: 126,472 candidate secret seeds in 11s (11,856/s), K=18
best: first 18 played rounds ALL crash below 2.0x (honest chance = 4.56e-06)
  published terminating hash: f54a60dbef7ff4341eae829013861f42f85820909b7af50928922ccb6a9239de
  first 10 crash points: [1.46, 1.12, 1.79, 1.05, 1.85, 1.09, 1.76, 1.65, 1.0, 1.13]
```

**Eleven seconds of Python** bought a chain that is fully "provably fair" — every round verifies
against the published terminating hash and against Bitcoin block 584,500 — and on which every
player auto-cashing at 2× loses 18 rounds in a row. A real operator at ~2M hashes/s in C rigs 28–30
rounds. This voids exactly the one sentence the reference gives as the design's purpose:
*"a future bitcoin block as a client seed so players can be certain that we did not pick one in the
house's favor."* The module presents `STAKE_SALT` as a neutral default constant and says nothing
about the ordering requirement.

---

## 5. Fudge hunt

- **Hardcoded empirical results:** none. `grep -nE "[0-9]+\.[0-9]{3,}"` over `crash.py` returns
  **nothing** — there is not a single multi-decimal literal in the module. The only constants are
  `2**32`, `1 - 0.01`, `0.01`, `1_000_000`, `10_000_000`, and the 2019 hash/salt, and every one of
  them is re-parsed out of `references/stake/crash.md` by `check_spec_parity()` and asserted equal.
- **Sim not using the engine:** false alarm, twice over. Bulk really pulls `BulkRng.floats` (I
  reproduced 5,000 rounds *and* a 7-chunk run scalar-for-scalar from `generate_floats`); chain
  really walks SHA-256 (231k rounds/s, and my own chain reproduces the streamed ints exactly).
- **Circular win counting:** `simulate_chain_targets` counts `ints < win_count_exact`, so that path
  cannot falsify the analytic threshold. I broke it two ways (exact boundary re-evaluation at
  `n−1`/`n` for 30 targets; 1M-round crash-point recount through public `HashChain`). Equivalent.
  Still a methodological weakness of the shipped gate, not a defect.
- **Vacuous check:** the empirical `std_per_unit` is `w·√(p̂(1−p̂))`, algebraically determined by the
  win rate — comparing it to `analytic_std_per_unit` adds zero information over the z-test.
- **Dead code:** `_crash_points_from_ints` is defined and **never called anywhere** in the repo
  (`grep` hits only its own definition). `win_count`'s `return 0` / `return TWO32` branches are
  unreachable for `1 < w ≤ 1e6`.
- **Edge cases:** target ≤ 1, > 1e6, inf, nan rejected; `1+2⁻⁵²` accepted; `n_rounds ≤ 0` rejected;
  chain exhaustion raises; `build_hash_chain` rejects `len < 2` and `len > 2,000,000`;
  `crash_point_from_int` range-checked; `crash_point_from_float` rejects 1.0. All confirmed.
- **Memory:** bulk 2M-float64 chunks (~16 MB × 3 live); chain 10M = one int64 array + reversed copy
  ≈ 160 MB peak. Under the 500 MB rule.
- **WoO handling: correct.** `references/woo/crash.md` is JetX (97% / 3% edge / tick mechanism with
  a 3% runway crash) and is printed as a labelled comparison whose `pass` depends only on the shared
  *shape* (`P = RTP/w`, flat edge) and the Wizard's own 3× worked example — never on 97% matching.
  The 2 pp gap is stated as expected. This is the right call and it is documented in three places.

---

## 6. Findings, ranked

**F1 (biggest gap; unchanged from round 1, now demonstrated). A fresh chain is bound by default to
Stake's already-public 2019 salt, inverting the commitment order the reference names as the point —
and I rigged 18 consecutive sub-2× rounds in 11 seconds to prove it.**
`HashChain.__init__(salt=STAKE_SALT)` and `simulate_chain_targets(salt=STAKE_SALT)` pair a chain
generated *now* with Bitcoin block 584,500 (mined 2019-07-21). Fix: keep `STAKE_SALT` **only** for
replaying/verifying Stake's own 2019 chain; make `salt` a **required** argument whenever a new chain
is generated; record the ordering in the `verification` dict (`terminating_hash` committed at t₀,
salt from a block after t₀) and raise/warn when a caller pairs a fresh chain with a salt that
predates it. ~20 lines, and it is the only thing standing between this piece and a blind win.

**F2. The shipped validator's empirical gate is thinner than the engine deserves.** 7 marginal tail
probabilities, **one** fixed seed per mechanism, no distribution-level test at all. Every GOF test I
added passes comfortably (§3 Run D) — so this is an evidence gap, not an engine gap — but the
validator is the artifact that stands for "we validated this". It should carry the multiplier-band
χ², the low-bit χ², the empirical instant-bust z, and a multi-seed sweep. ~30 lines. *Unfixed since
round 1.*

**F3. `DEFAULT_TARGETS` stops at 1000× while the analytic table runs to 1,000,000×** — exactly the
regime where quantization becomes visible. I ran 40M rounds at 10⁴/10⁵/10⁶ and all pass, so extend
the grid; it costs nothing and closes the "conveniently avoided regime" objection. *Unfixed since
round 1.*

**F4. No public vectorized crash-point generator.** `simulate_targets` builds the crash-point array
and discards it; the only public sequence source is `HashChain.crash_points`, O(n) Python and capped
at 2M. Anything downstream (multiplier histogram, two simultaneous bets as the WoO reference
describes, manual cashout, laddering) must re-derive the formula. `crash_points(n, bulk=…) ->
np.ndarray` fixes it — and `_crash_points_from_ints` is already sitting there unused, waiting to be
that function. *Unfixed since round 1.*

**F5 (nit). Crash points are emitted at full float precision** (`3.3712893041231235`) where a real
Stake history is 2-decimal. The reference is silent on display rounding and it is provably
payout-neutral for 2-decimal targets (`⌊100·c⌋/100 ≥ w ⟺ c ≥ w`), so I am not scoring it — but a
side-by-side *round history* would be given away instantly by it, and the engine also accepts
non-2-decimal targets (1.000001×) that the real game does not offer. One line of documentation, or a
2-decimal `display_crash_point` helper.

**F6 (nit).** `build_hash_chain` cannot build the published 10,000,000-hash chain
(`_MAX_STORED_CHAIN = 2,000,000`), so random access to a Stake-scale game hash is unavailable; only
the streaming aggregate path reaches that size. `_crash_points_from_ints` is dead code.

**F7 (project-level, not crash's fault).** `harness.py`, `selector.py`, `report.py`,
`games/__init__.py` and `mcp_server/` are one-line stubs — no game, crash included, is wired into
the harness the README advertises. Noting it so it is not mistaken for a crash-specific gap.

---

## 7. Bottom line

On numbers this piece is finished, and round 3 hardened that conclusion rather than softening it:
bit-exact against a from-scratch RFC-2104 reimplementation; `win_count` exact against rational
arithmetic at 30 targets from 1+2⁻³⁰ to 10⁶; worst |RTP − 0.99| = 1.4e-05 and always under the 32-bit
bound; 91M rounds inside 3 SE with an independent-stream omnibus p = 0.119; high-bit χ² p = 0.302,
low-bit χ² p = 0.570, band χ² p = 0.716, lag-1 z = +1.23; extreme-tail outlier chased down to 40M
rounds and shown not to replicate; zero hardcoded empirical values in the module.

It loses the blind on the same cell as last round — **a 2026 chain committed to a 2019 salt** — and
this round that cell stopped being a theoretical objection: 11 seconds of grinding produced a
"provably fair" chain on which 18 straight rounds bust below 2×. Nothing else in the piece is close
to this. Fix the salt commitment ordering and crash wins round 4.
