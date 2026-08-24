# Plinko — Gauntlet Round 1 (independent critic)

**Verdict: DOES NOT YET WIN.** Payout grid and statistics are clean; three named
defects keep it from being blind-indistinguishable from the reference.

Reviewed: `/home/user/troyrhinehart/casino/spinquest_sim/games/plinko.py`,
`/home/user/troyrhinehart/casino/scripts/validate_plinko.py`,
`/home/user/troyrhinehart/casino/tests/test_plinko.py`.
Ground truth: `references/stake/plinko.md`, `references/woo/plinko.md` only.

---

## 1. What I did (nothing reused from the builder)

| Check | Method |
|---|---|
| Analytic RTP, all 27 configs | Paytables re-typed by hand from the engine source into a throwaway script; RTP recomputed with `fractions.Fraction` (exact rationals, no float64), compared to the WoO BGAMING grid and the Stake dest/min/max tables. |
| Payout-for-payout vs Stake | 27 × (destinations, min win, max win) + the two verbatim WoO full tables + BetFury-Red 16-row table + blog facts (1000x, 130x, 0.0015%, 0.2x–1000x range). |
| Provably-fair path | A **from-scratch** re-implementation of Stake's published `byteGenerator` / `generateFloats` / `floor(float*2)` (hmac+hashlib only, zero `spinquest_sim` imports), cross-checked against `PlinkoEngine.play` for 1,620 rounds spanning all 27 configs. |
| Empirical | **60,000,000 rounds** through the engine's public `simulate_provably_fair` (real HMAC-SHA256 stream), 10M each on high/16, medium/16, low/8, high/8, medium/14, low/15. My own SE, my own z, my own chi-square. |
| Extra | Per-row direction bias over 2M × 16 real-stream rows (a test the builder never runs). |
| Builder's own script | `scripts/validate_plinko.py` executed: **PASS**, 270M rounds, worst \|z\|=2.15, 18.6 s. |

## 2. Analytic recomputation (exact rationals)

Medium and High: **18/18 match the printed WoO figure exactly at 2 dp.**

```
medium/8  98.906250%  vs 98.91    high/8   99.062500% vs 99.06
medium/9  99.140625%  vs 99.14    high/11  99.160156% vs 99.16
medium/16 98.988342%  vs 98.99    high/16  98.976440% vs 98.98   ... all 18 OK
```

Low: **8 of 9 do NOT reproduce the printed WoO Low column.**

```
low/8  98.9844% vs 98.91 (+0.074)   low/13 98.9990% vs 98.99 (+0.009)
low/9  98.9844% vs 99.14 (-0.156)   low/14 99.0002% vs 98.99 (+0.010)
low/10 99.0039% vs 98.91 (+0.094)   low/15 99.0009% vs 99.00 (  OK  )
low/11 99.0039% vs 99.02 (-0.016)   low/16 98.9987% vs 98.99 (+0.009)
low/12 98.9795% vs 98.99 (-0.011)
```

**I independently confirmed this is a reference defect, not an engine defect.**
Two proofs, both internal to `references/woo/plinko.md`:

1. The page's own verbatim low/8 pay table `5.6, 2.1, 1.1, 1, 0.5, …` evaluates
   to **98.984375%**, contradicting the **98.91%** its own Low column prints for
   low/8. The captured Low column is a row-for-row duplicate of the Medium column.
2. The same page's BetFury **Blue** table evaluates to **97.5018%**, not the
   **97.88%** it prints beside it — a second, unrelated table/RTP inconsistency
   in the same capture.

So the builder's "duplicated column" call is correct and provable. But
`validate_plinko.py` replaces the failing exact check with a 98.91–99.16 *band*
check that essentially any plausible low table would pass — the escape hatch is
wider than the evidence requires. low/8 is the only low config with a full-table
anchor; the other eight are pinned by three numbers each.

## 3. Payout grid vs Stake — clean

All 27 configs: destinations = rows+1, min win, max win exact. Tables symmetric,
max at the edges, min at/near center. Blog facts reproduce: 16/high edge = 1000x,
second-from-edge = 130x, P(edge, 16 rows) = 1/65536 = 0.0015%, global range
0.2x–1000x. `_full_table` even/odd mirroring is correct (odd pocket count shares
one center value; even repeats the innermost half value). No hardcoded empirical
results anywhere; the sims genuinely drive `self.payouts`.

## 4. Empirical — passes, on my own numbers

60M rounds on the **real provably-fair stream** via the public API:

```
cfg              n      emp_rtp   analytic     my_SE   my_z    chi2  df       p
high/16   10,000,000   0.990391   0.989764  2.08e-03  +0.30   11.77  16  0.7599
medium/16 10,000,000   0.989886   0.989883  4.64e-04  +0.01   25.13  16  0.0675
low/8     10,000,000   0.989888   0.989844  1.76e-04  +0.25    7.22   8  0.5127
high/8    10,000,000   0.990043   0.990625  8.44e-04  -0.69   13.08   8  0.1090
medium/14 10,000,000   0.990916   0.989941  4.31e-04  +2.26   15.95  14  0.3162
low/15    10,000,000   0.990014   0.990009  1.30e-04  +0.04   14.17  15  0.5126
```

Worst \|z\| = **2.26** (bound 3.0); worst chi-square p = 0.068. Per-row
right-fraction over 2M × 16 real rows: max \|z\| = 2.47. `emp_rtp` recomputed by
me from `pocket_counts @ payouts`, agreeing with the engine's own to 1e-12.
Builder's script separately: 270M rounds, worst \|z\| = 2.15.

Float64 `rtp()` vs exact rational: max error **1.1e-16** across all 27 configs.

## 5. Defects found

### D1 — `simulate(chunk<=0)` hangs forever (reproduced)
`PlinkoEngine.simulate` validates `n_rounds` but not `chunk`. With `chunk=0`,
`step = min(0, …) = 0`, `done` never advances, and the loop spins forever
printing `plinko simulate[low/8]: 0/10`. I generated a **512 KB** log in 120 s
before killing it. A public parameter that turns into an unkillable spin loop is
not something the reference implementation would ship. Fix: `if chunk < 1: raise`.

### D2 — the SD path is validated against nothing (biggest gap)
`std_per_unit()` / `variance()` are the engine's only outputs beyond RTP, and
**not one published number is used to check them.** The reference hands over four
exact figures — CryptoGames Green/Red/Blue/Yellow SDs. I verified by hand that
the engine's formula reproduces all four to six decimals *and* their four RTPs:

```
CG Green  98.3701% (pub 98.37)  SD 0.562711 (pub 0.562711)  MATCH
CG Red    98.1561% (pub 98.16)  SD 0.517632 (pub 0.517632)  MATCH
CG Blue   98.4814% (pub 98.48)  SD 0.464829 (pub 0.464829)  MATCH
CG Yellow 98.0899% (pub 98.09)  SD 3.678698 (pub 3.678698)  MATCH
BF Green  97.8775% (pub 97.88)                              MATCH
BF Red    98.9764% (pub 98.98)                              MATCH
BF Blue   97.5018% (pub 97.88)                              REFERENCE DEFECT
```

The engine cannot be pointed at any of these: `PAYTABLES` is a closed 27-key dict
and `PlinkoEngine.__init__` takes no custom pocket array. Eleven independently
checkable published numbers sit unused, and the eleventh (BetFury Blue) would
have surfaced the second reference inconsistency automatically.

### D3 — headline empirical run is on a surrogate, not the engine's path
`validate_plinko.py` step 5 ("10,000,000 drops × 27 configs") calls `simulate()`,
which draws `Binomial(rows, 0.5)` from numpy PCG64 and never touches
`floor(float*2)`. Only **1** config × **1M** rounds runs on the real HMAC stream.
Distributionally identical, so not a correctness fudge — but the advertised
"10M+ through the engine" bar is met by a shortcut. (I closed this gap myself:
60M real-stream rounds, above.) Related: `simulate`'s docstring claims "chunks of
`chunk` **int8** draws"; `gen.binomial` returns int64, so the default 20M chunk is
160 MB, not 20 MB — still inside the 500 MB budget, but the doc is wrong.

### D4 — blind tells (cosmetic but real)
`config()["payouts"]` renders as `[110.0, 41.0, 10.0, 5.0, 3.0, 1.5, …]`. The
published table is `110, 41, 10, 5, 3, 1.5, …`. Side by side that trailing `.0`
alone identifies which column was machine-emitted.

### D5 — unguarded inputs
`play(..., bet=-5)` returns `payout = -5.0`; negative nonces are accepted.
Cosmetic next to D1–D2, but the reference API rejects both.

## 6. Blind comparison

Panel 1 (27 rows × dest/min/max/RTP, columns unlabeled): 19/27 identical; the 8
differing cells are all in Low. An expert **can** tell the columns apart — but
the giveaway is that column A's Low column is a verbatim duplicate of its own
Medium column, which marks A as the flawed transcription. This panel favors ours.

Panel 2 (full pay tables): identical values, but one column prints `1.0` where the
other prints `1` — a formatting tell (D4).

Panel 3 (blog facts): indistinguishable.

Panel 4 (published SDs `0.562711 / 0.517632 / 0.464829 / 3.678698`): column A has
four numbers; column B has *no way to produce them*. This panel gives ours away
immediately as the less complete artifact.

**Blind result: not a coin flip.** Panels 2 and 4 identify ours.

## 7. Verdict

- Payout match: **PASS** — every number the references publish reproduces exactly.
- Statistics: **PASS** — 60M own rounds on the real provably-fair path, worst
  \|z\| = 2.26 < 3, chi-square clean, per-row bias clean.
- Blind: **FAIL** — D4 (float rendering) and D2/Panel 4 (unreachable published SDs).
- Robustness: **FAIL** — D1 hangs.

**ours_wins = false.**

**Single biggest gap:** the variance/SD surface is validated against zero
published numbers. Open `PlinkoEngine` to an arbitrary pocket table (e.g.
`PlinkoEngine.from_table(payouts)`), then assert in `validate_plinko.py` and
`tests/test_plinko.py` the four CryptoGames SDs (0.562711, 0.517632, 0.464829,
3.678698) and RTPs (98.37/98.16/98.48/98.09) plus the three BetFury RTPs — the
only hard, independently checkable statistical figures the references publish,
and the one thing the artifact currently cannot even attempt.
