# Roulette — critic round 5 (independent, fresh eyes)

Reviewed: `/home/user/troyrhinehart/casino/spinquest_sim/games/roulette.py`,
`/home/user/troyrhinehart/casino/scripts/validate_roulette.py`,
`/home/user/troyrhinehart/casino/tests/test_roulette.py`.
Ground truth: `references/stake/roulette.md`, `references/woo/roulette.md`.
All checks below are **my own code**, not the builder's tests. Probes live in
`/tmp/claude-0/-home-user-troyrhinehart/b3ce270f-e608-55a6-8515-5735b66f4ebe/scratchpad/`
(`probe_guard.py`, `probe_payout.py`, `probe_emp.py`, `probe_multi.py`, `probe_pf.py`, `probe_hang.py`).

**VERDICT: ours does NOT win.** Every number reproduces its source exactly, every empirical
check lands inside 3 SE, and the blind side-by-side is a coin flip that if anything favours
ours. But the bug class round 4 declared eliminated is **not** eliminated — it was patched at
one call site, not at the root — and the surviving instance returns a *false pass*.

---

## 1. Round-4 flagged gap: CLOSED

Reproduced the previous critic's probe (`probe_guard.py`, SIGALRM-fenced, 8 s budget/case):

| input to `Roulette.simulate` | result |
|---|---|
| `chunk_rounds=0` | `ValueError: chunk_rounds must be >= 1, got 0` |
| `chunk_rounds=-1` | `ValueError` |
| `chunk_rounds=-10**9` | `ValueError` |
| `chunk_rounds=0.5` | `ValueError` |
| `chunk_rounds=1` | returns; **bit-identical** to a single-chunk run |
| `n_rounds=0`, `n_rounds=-5` | `ValueError: n_rounds must be positive` |

The guard is at `roulette.py:502-509`, is covered by `test_simulate_rejects_nonpositive_chunk_rounds`
(parametrised 0/-1) plus a `chunk_rounds=1` boundary test, and is gated in the validator
(GATE 4, "simulate degenerate chunk guard"). Chunk-invariance independently confirmed:
`chunk_rounds` 7 vs 5000 over 5,000 spins gives identical `wins` and identical `pocket_counts`.
**Closed.**

## 2. Core bar re-verified

### 2a. Payout-for-payout parity vs Stake (`probe_payout.py`)
I hand-transcribed section 5 of `references/stake/roulette.md` into my own literal table
(no reuse of the builder's parser) and compared 13 bet types × 5 quantities:

```
worst |engine - reference| = 0.0     (odds, total-return multiplier, coverage, P(win), RTP)
```

All 13 exact as `Fraction`: `multiplier_exact == Fraction(36, coverage)`,
`win_probability_exact == Fraction(coverage, 37)`, `rtp_exact == Fraction(36, 37)` — not
float-close, *equal*. Colors match the reference lists verbatim, partition 1..36, disjoint,
0 green and excluded from red/black/odd/even/low/high. 1/37 = 2.702703% → rounds to the
published 2.70%; 36/37 = 97.297297% → 97.30%. Five-number bet (6:1) correctly absent.

157-bet catalogue: my own independent enumeration of splits (60) and corners (22) matches the
engine set-for-set; every one of the 157 has exact RTP 36/37 and multiplier 36/coverage; all
157 selections distinct; settling each bet over the full wheel returns **exactly 36.0**
(min = max = 36.0).

### 2b. WoO SD (`probe_payout.py`)
Recomputed from first principles (`sqrt(M²p(1-p))`, M = 36/c, p = c/(36+z)):

| | WoO printed | my derivation | engine |
|---|---|---|---|
| double-zero even money | 0.998614 | 0.998614 | — |
| double-zero straight | 5.762617 | 5.762617 | — |
| single-zero even money | 0.999635 | 0.999635 | 0.999634703 |
| single-zero straight | 5.837800 | **5.837837838** | **5.837837838** |

Max \|engine − mine\| over all 13 types = 8.9e-16. The single divergent cell is the WoO file's
own *derived* straight-up figure; it contradicts the formula printed two lines above it
(216/37 = 5.8378378) while its two *published* double-zero figures are 6dp-exact. **The engine
is right and the reference cell is a rounding slip** — the engine reports the discrepancy
rather than rounding to hide it.

### 2c. RNG / provably-fair path (`probe_pf.py`)
I re-implemented Stake's published `byteGenerator` / `generateFloats` / `POCKETS[floor(f*37)]`
from scratch out of the reference markdown and diffed:

- pinned vector `serverSeed='a'*64, clientSeed='clientseed', nonce=1` → float
  `0.4767664363607764` → pocket 17 — identical mine vs engine.
- 2,000 nonces on a fresh random 64-hex seed: **0 mismatches** bulk vs my independent port.
- parallel `BulkRng` output identical to `workers=1`.
- `play_round` pocket == my port; nonce accounting contiguous (1 nonce/spin, `nonce_range`
  width == n_rounds).

Mapping exactness: swept every pocket boundary `k = ceil(p·2³²/37) ± 2` plus `k = 2³²−1` and
compared `floor(k/2³² · 37)` (scalar and vectorized) against exact integer `floor(37k/2³²)` —
**0 mismatches**. Lattice: 2³² mod 37 = 7, so 7 pockets carry 116,080,198 points and 30 carry
116,080,197; exact per-type lattice RTP deviates from 36/37 by at most 1.6e-9 (≈ 1e-6 SE at
10M) — matching the module docstring's disclosure.

### 2d. Empirical, public API only, 5 independent fresh random seeds (50M spins)

`probe_emp.py` (10M) and `probe_multi.py` (3 × 10M) settle through the **public**
`payouts_for_pockets` / `settle_bets`; the builder's validator was also run once on
`--fresh-seed` (10M).

| run | 13 types outside 3 SE | worst \|z\| | 157-bet Sidak (4.298) | pocket χ²(36) |
|---|---|---|---|---|
| mine, seed a892a0… | 0/13 | 2.24 | 0/157 | 37.6 |
| mine, seed e80e1e… | 0/13 | 1.76 | 0/157 | 45.3 |
| mine, seed 4a4138… | 0/13 | 1.27 | 0/157 | 29.8 |
| mine, seed b1c1dd… | 0/13 | 1.82 | 0/157 | 25.8 |
| builder validator, fresh fc7be5… | 0/13 | 1.92 | 0/157 | 44.3 |

99.99% χ²(36) quantile = 76.36. 39 per-type z-scores across my 3-seed sweep: mean −0.034,
sd 0.875, max \|z\| 1.82 — no drift, no under-dispersion.

Pooled 30M spins (my seeds): straight z = −0.29, red z = +0.50, dozen z = +0.24, line z = −0.76;
pocket-0 frequency 0.0270133 vs 1/37 = 0.0270270; χ²(36) = 37.6.

Independence: lag-1 transition χ²(1296) = 1272.6, z = −0.46 at 10M.

`Roulette.simulate(10_000_000)` through the public path: rtp 0.9720216, z = −0.52,
`within_3se=True`, 14.0 s, **peak RSS 218 MB** (children 83 MB) — inside the 500 MB budget.

### 2e. Round-4 runner-up (variance evidence) — I supplied it myself; it holds
Round 4 noted the piece has no genuine variance evidence because per-bet "empirical SD" is
algebraically `multiplier·sqrt(p̂(1-p̂))`. I built the missing counterpart: exact basket EV,
variance and 4th central moment over the 37 pockets (`Fraction` arithmetic), then simulated
through `settle_bets`.

- 7-bet overlapping basket, 10M spins: mean 6.812655 vs exact 252/37 = 6.810811 (z = +0.65);
  **variance 80.129349 vs exact 80.099343 (z = +0.31)**.
- 10-bet basket (one of every type), 30M spins: mean 9.729172 vs exact 360/37 = 9.729730
  (z = −0.21); **variance 206.17175 vs exact 206.19722 (z = −0.19)**.
- Per-seed basket z: mean +0.25/−0.47/−0.15, variance +0.35/−0.63/−0.04.

So the piece's variance behaviour is correct. What is still missing is that the *piece* cannot
produce this evidence: `roulette.py` exposes no analytic basket EV/variance, and
`validate_roulette.py` never calls `settle_bets` at all (GATE 5 uses `payouts_for_pockets`
and `bincount`). Round 4's runner-up is unchanged, but it is a coverage gap, not a
correctness gap — hence it is not my headline.

---

## 3. Blind side-by-side

Panels stripped of labels, one column the reference bar, one column the engine:

| cell | panel X | panel Y |
|---|---|---|
| wheel | 37 pockets 0–36, one green zero | 37 pockets 0–36, one green zero |
| edge / RTP | 2.70% / 97.30% | 2.702703% / 97.297297% (rounds to X) |
| 10 payout rows | 35/17/11/8/5/2/2/1/1/1 : 1 | identical, plus exact `Fraction` multipliers |
| coverage & P(win) | 1,2,3,4,6,12,12,18…/37 | identical |
| red/black lists | 18 + 18 | identical, verbatim |
| five-number bet | present in prose, excluded as double-zero-only | excluded, same reason quoted |
| RNG | `POCKETS[floor(float*37)]`, cursor 0, 1 float | byte-exact, pinned vector reproduced |
| straight-up SD | 5.837800 | 5.8378378 |
| catalogue | 10 named bet families | 157 individual bets incl. 2 zero trios + first four |

Two cells differ. Neither identifies an imitation:
- the SD cell — panel Y is the value panel X's *own* formula produces (216/37); panel X is the
  one that slipped a digit;
- the catalogue cell — panel Y is a superset. Trio (0-1-2, 0-2-3, 11:1 on 3 pockets) and first
  four (0-1-2-3, 8:1 on 4 pockets) are standard single-zero-mat bets that inherit the exact
  36/coverage identity, so they add no house-edge distortion; the reference's list is simply a
  marketing guide, not an exhaustive mat. Worth noting: these 3 bets are the only content in
  the engine **not** attested by either reference file — they are extrapolated (and honestly
  documented as such in the module docstring). An expert could flag them as unsourced, but not
  as *wrong*.

Call: coin flip, mildly favouring the engine. **No tell.**

---

## 4. THE GAP — the round-4 bug class is not actually closed

`Roulette.simulate` was patched at one call site instead of at the root. Two degenerate inputs
on the same code path — the *identical* failure mode round 4 named "the last survivor" — are
still live (`probe_hang.py`, reproduced deterministically):

```
n_rounds=inf : still running after 45 s, no exception, no output -> unbounded loop
n_rounds=nan : RETURNED rtp=nan wins=0 n_rounds=nan within_3se=True nonce_range=(0, 0)
               pocket_counts.sum()=0
```

Root cause, all three lines in one method:

```python
if n_rounds <= 0:          raise ValueError(...)   # False for inf AND for nan
if chunk_rounds < 1:       raise ValueError(...)   # guarded (round-4 fix)
while done < n_rounds:     ...                     # never terminates for inf; never runs for nan
```

- `n_rounds=float('inf')` → `inf <= 0` is False, so it passes the guard, and `done < inf` is
  always true: an unbounded loop with no error and no output, exactly the round-4 signature.
  With `progress=True` it instead prints progress lines forever.
- `n_rounds=float('nan')` is worse than a hang: every comparison with nan is False, so the
  loop body never executes and the method **returns a normal-looking result dict reporting
  `within_3se: True`** from a campaign that consumed 0 nonces and settled 0 spins. A caller
  gating on `result["within_3se"]` gets a green light from a simulation that never ran.

This is not hypothetical plumbing: `json.loads` parses bare `Infinity`/`NaN` by default, so any
JSON/MCP-shaped caller (this repo ships an `mcp_server` package) forwarding a round count into
`simulate` inherits both. Note the CLI is safe — `validate_roulette.py` coerces `--rounds`
through `_positive_int` — which is precisely why the library-level hole survived another round.

Fix is the same shape as the round-4 fix, applied at the root rather than the site:

```python
if not isinstance(n_rounds, numbers.Integral) or isinstance(n_rounds, bool):
    raise TypeError(f"n_rounds must be an integer, got {n_rounds!r}")
if not isinstance(chunk_rounds, numbers.Integral) or isinstance(chunk_rounds, bool):
    raise TypeError(f"chunk_rounds must be an integer, got {chunk_rounds!r}")
```

(`chunk_rounds=True` currently dies with a raw numpy `TypeError: an integer is required` from
deep inside `BulkRng`, so the same coercion tidies that too.)

**Runner-up:** round 4's own runner-up is unchanged — `settle_bets` still has no analytic
basket EV/variance counterpart in `roulette.py` and is still never simulated by
`validate_roulette.py`, so the piece cannot generate the variance evidence I had to build by
hand in §2e (even though the numbers, once built, check out at z = −0.19 over 30M spins).

**Cosmetic, not gating:** `settle_bets` raises a raw `AttributeError: 'str' object has no
attribute '_mask'` for a non-`Roulette` element rather than a typed error, and
`Roulette('split', (1, 2, 1))` silently accepts a duplicate-bearing selection.

---

## 5. Scoreboard

| check | result |
|---|---|
| round-4 flagged gap (`chunk_rounds=0`) | **CLOSED** |
| payout parity vs Stake, 13 types × 5 quantities | **0.0** worst diff, exact rationals |
| 157-bet catalogue exactness + full-wheel settle | **PASS** (all exactly 36.0) |
| WoO SD, all 13 types | **PASS** (8.9e-16; ref's 5.837800 cell is the error) |
| provably-fair byte-exactness vs my own port | **PASS** (0/2000 mismatches) |
| float→pocket boundary sweep | **PASS** (0 mismatches) |
| 10M+ empirical, 5 fresh seeds, public API | **PASS** (0/13 and 0/157 outside, all runs) |
| basket EV **and** variance, 30M, `settle_bets` | **PASS** (z = −0.21 / −0.19) |
| memory (10M `simulate`) | **PASS** (218 MB peak) |
| blind side-by-side | **coin flip / favours ours** |
| degenerate-input robustness of `simulate` | **FAIL** — `inf` hangs, `nan` returns `within_3se: True` |
