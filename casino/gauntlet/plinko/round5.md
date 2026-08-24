# Plinko — Round 5 critic report (independent, fresh eyes)

**Verdict: ours_wins = TRUE.** The round-4 gap is closed and independently
re-measured. Every payout number reproduces its published source exactly; the
only discrepancies in the blind panel are two *proven defects in the reference
page itself*, each confirmed by a second, independent route. 60,000,000 real
HMAC-SHA256 rounds run by me through the public API land inside 3 SE on my own
exact-rational statistics.

Nothing below is taken from the builder's tests. I wrote a from-scratch port of
Stake's published `byteGenerator` / `generateFloats` / `floor(float*2)` using
only `hmac` + `hashlib`, and re-parsed both reference `.md` files with my own
regexes rather than trusting any transcribed constant.

---

## 1. The flagged gap — reproduced and re-measured

Round 4's gap was threefold: (a) unchunked simulator, 2,541 MB peak RSS at 10M
drops; (b) the headline `simulate()` was a numpy-PCG64 binomial *surrogate*, so
270M of validate's advertised 300M rounds never touched the game's own RNG;
(c) off-contract naming (`PlinkoEngine`/`play`, missing result keys), plus two
secondary defects.

I re-ran the round-4 critic's exact probe: `/proc/self/status` RSS sampled at
50 ms for the duration of a 10M-round, 16-row campaign driven through the
**public** API (`Plinko(rows=16, risk="high").simulate(10_000_000, bulk=...)`).

| probe | round 4 | round 5 (mine) | budget |
|---|---|---|---|
| plinko 10M drops, 16 rows — peak RSS | **2,541 MB** | **368 MB** (VmHWM; 366 MB sampled) | 500 MB |
| sibling `Wheel.simulate(10M)` — peak RSS | 218 MB | 223 MB (VmHWM) | 500 MB |

**6.9x reduction, 74% of budget, gap closed.** The 368 MB is exactly the
predicted arithmetic for the shipped `chunk_rounds=1_000_000`: a 1M x 16
float64 matrix (128 MB) plus the `np.floor` temporary (128 MB) plus the
`astype(int64)` result (128 MB) = 384 MB, which is why the default is 1M and
not the 2M the round-4 note suggested — 2M x 16 would be 768 MB and *would*
blow the budget. That default is not a deviation from the suite contract, it is
the contract: the multi-float engines all sit at 1M (keno, mines, baccarat,
slots), single-float engines at 2M (wheel, crash, roulette), heaviest at 500k
(blackjack, video_poker). Plinko is in the right tier.

I also sampled the **whole process tree** (parent + the 4 forked digest
workers): plinko 884 MB, wheel 557 MB. The ~330–520 MB delta over each parent
is copy-on-write shared pages that RSS double-counts across forks; both
engines carry it, so it is a `BulkRng` fork artifact, not a plinko finding.

**(b) surrogate is gone.** `grep -n "default_rng\|PCG64\|binomial\|np.random"`
over `plinko.py`, `validate_plinko.py` and `test_plinko.py` returns only
prose occurrences of the word "binomial". Every simulated round now goes
through `BulkRng.plinko_directions`. I confirmed this end-to-end rather than by
grep: `simulate(500, chunk_rounds=97)`'s pocket histogram is *identical* to a
histogram I rebuilt by calling my own from-scratch scalar verifier at nonces
0..499, and 200 uniformly-random nonces out of a 3M-row bulk block all
reverify against my scalar port (0 failures).

**(c) contract aligned.** Class is `Plinko`, method is `play_round`, signature
is `simulate(n_rounds, bulk=None, chunk_rounds=1_000_000, progress=True)`, and
the result dict carries `n_rounds`, `analytic_rtp`, `analytic_std_per_unit`,
`se_rtp`, `z_score`, `within_3se`, `verification`. The progress line format
matches the siblings verbatim (`  plinko low/16: 1,000,000/2,500,000 drops
(253,188/s)` vs `  wheel 10/low: 2,000,000/5,000,000 spins (531,497/s)`).

**Secondary defects fixed.** `"int8"` no longer appears in the `simulate`
docstring. Every input I tried to smuggle past `play_round` is rejected:
empty `server_seed` (ValueError), negative nonce (ValueError), float nonce
(TypeError), bool nonce (TypeError), negative bet (ValueError). Also
`n_rounds=0`, `chunk_rounds=0`, `rows=17`, and calling `simulate` on a
`from_table` engine with rows outside 8..16 all raise.

---

## 2. Payout-for-payout parity vs the Stake reference

I regex-parsed the three "Playing Sizes" tables out of
`references/stake/plinko.md` and compared against the engine's own
`pockets` / `min(payouts)` / `max(payouts)`.

- **27/27 configs match on (destinations, min win, max win). 0 mismatches.**
- **27/27** payout arrays are exactly palindromic.
- **27/27** are monotone non-increasing edge→center with the minimum landing
  exactly on the centre pocket.
- Blog facts: 16/high edge = **1000x**, second-from-edge = **130x**,
  P(edge | 16 rows) = 1/65536 = **0.00152587890625%** (blog prints 0.0015%),
  global multiplier range across all 27 tables = **0.2x .. 1000x**.
- All three tables the references print in full match element-for-element:
  WoO 8/low `(5.6, 2.1, 1.1, 1, 0.5, ...)`, WoO 16/medium
  `(110, 41, 10, 5, 3, 1.5, 1, 0.5, 0.3, ...)`, and WoO's BetFury "Red"
  1000x table == our 16/high.
- Independent structural cross-check the builder does not run: Stake's blog
  claim that lower risk has *fewer* sub-1x pockets holds for all 9 row counts
  (low ≤ medium ≤ high loss-pocket counts, 9/9).

**Analytic exactness.** I recomputed RTP and per-drop SD from scratch in
`fractions.Fraction` over `C(rows,k)/2**rows`. Max |engine float64 − my exact|
across all 27 configs: **< 1e-15** on RTP, **< 1e-13** on SD. `paytable()`'s
return contributions sum to `rtp` and its probabilities sum to 1.0 with
**exactly zero** float error.

---

## 3. Blind comparison — labels stripped

I built the 27-row panel with the columns anonymised as X and Y (X = the
reference page's printed figures, Y = ours) and asked: which is the imitation?

```
cfg         X:dest|min|max   Y:dest|min|max   X:RTP%   Y:RTP%
low/8       9|0.5|5.6        9|0.5|5.6        98.91    98.98   <- differs
low/9       10|0.7|5.6       10|0.7|5.6       99.14    98.98   <- differs
...  (8 of 9 low rows differ; all 9 medium and all 9 high rows identical)
medium/16   17|0.3|110       17|0.3|110       98.99    98.99
high/16     17|0.2|1000      17|0.2|1000      98.98    98.98
```

Shape (destinations|min|max) is a **coin flip — 27/27 identical**, no tell.
The only signal is the low RTP column. An expert doing forensics on it would
convict **X**, not Y, on two independent grounds:

1. **X's low column is a row-for-row duplicate of X's own medium column**
   (98.91, 99.14, 98.91, 99.02, 98.99, 98.99, 98.99, 99.00, 98.99 — all 9
   identical). Low and medium are structurally different tables (8/low is
   `5.6, 2.1, 1.1, 1, 0.5`; 8/medium is `13, 3, 1.3, 0.7, 0.4`), so they cannot
   produce identical RTPs to 2 dp nine times over. This is a capture/transcribe
   defect.
2. **X contradicts itself.** The same page prints the 8-row low table verbatim;
   that table evaluates to **98.984375%**, which is *our* value — not the
   98.91% printed beside it. 98.90625% is exactly the medium/8 value. Where the
   reference publishes an actual low table, we match it exactly.

A third, unrelated defect on the same page corroborates that its transcription
is the weak link: its BetFury **Blue** table, reproduced verbatim, evaluates to
**97.501831%**, not the 97.88% printed next to it (its Green table does hit
97.88% — the two RTPs were duplicated the same way the low column was).

Where the reference is internally consistent, ours reproduces it to the last
printed digit, including figures the builder gets no credit for guessing:

| CryptoGames table | printed RTP / HE / SD | ours (via `Plinko.from_table`) |
|---|---|---|
| Green | 98.37% / 1.63% / **0.562711** | 98.37% / 1.63% / **0.562711** |
| Red | 98.16% / 1.84% / **0.517632** | 98.16% / 1.84% / **0.517632** |
| Blue | 98.48% / 1.52% / **0.464829** | 98.48% / 1.52% / **0.464829** |
| Yellow | 98.09% / 1.91% / **3.678698** | 98.09% / 1.91% / **3.678698** |

4/4 standard deviations reproduced to all six printed decimals through the
identical analytic formulas. WoO BGAMING grid: **medium 9/9 exact, high 9/9
exact** at the printed 2 dp.

**Blind module panel** (the round-4 complaint): I diffed plinko's public
surface against the passed siblings with names stripped. Same method set
(`analytic_summary`, `config`, `paytable`, `play_round`, `simulate`,
`summarize_counts`), same property set (`rtp`, `rtp_exact`, `house_edge`,
`std_per_unit`, `variance_exact`, `variance_per_unit`, `max_multiplier`),
same `__all__` shape, comparable size (460 LOC vs wheel 407 / keno 450).
Result-dict shape is identical to keno's (histogram + `total_payout`, no
`win_rate` — correct, since every plinko drop returns a multiplier and there
is no binary win). **No tell identifies ours as the imitation.**

---

## 4. Provably-fair verification (my own port, zero project imports)

| probe | result |
|---|---|
| `play_round` vs my hmac/hashlib port — 27 configs x 60 nonces x 7 fields | **11,340 comparisons, 0 mismatches** |
| 16-row drop spans HMAC rounds 0 and 1 (Stake: "2 increments per game") | confirmed |
| bulk vs scalar, rows {8,11,16} x sizes {1,2,17,999,5001} | **0 mismatches** |
| `simulate(500)` histogram vs my scalar replay of nonces 0..499 | identical |
| serial (`workers=1`) vs parallel (`workers=8`) | identical counts |
| `chunk_rounds` 13 vs 97 vs 500 vs default | identical counts |
| 200 uniformly-random nonces out of a 3M-row block | **0 failures** |

---

## 5. Empirical — 60,000,000 real HMAC rounds, my statistics

Every round on the real provably-fair stream via the public `simulate()`.
`mu`, `sigma` and `SE = sigma/sqrt(N)` are **mine**, recomputed in exact
rational arithmetic; empirical RTP is **mine**, summed as `Fraction` over the
returned histogram. I confirmed the engine's own reported `rtp` /
`analytic_rtp` / `se_rtp` / `z_score` agree with mine in every case.

10M drops per row count, each direction stream settled against all three risk
tables:

| rows | low | medium | high | chi2 (df=rows) p |
|---|---|---|---|---|
| 8 | z = −0.484 | −0.228 | −0.071 | 0.322 |
| 12 | +0.038 | +0.389 | +0.145 | 0.864 |
| 16 | +2.659 | +2.562 | +1.475 | 0.387 |

The rows=16 line is one correlated draw (all three risks share the same
histogram), so I ran three *further* independent 10M campaigns at medium/16
with different server seeds: z = **−0.704 / +0.264 / +0.609**, mean z **+0.056**.
Seed luck, not drift.

**Worst |z| over my 60M rounds: 2.659 — inside the 3.0 bound.**

Row-level structure, 3,000,000 x 16 real decisions:

- per-row right-fraction: max |z| = **1.772** (16 rows)
- max |off-diagonal row correlation| = **0.00170** vs 1σ = 5.77e-04 — that is
  2.95σ for a max over 240 cells, where the expected max of 240 standard
  normals is ≈2.9. Exactly right.
- Wald–Wolfowitz runs test on the flattened 48,000,000-bit stream: z = **+0.376**
- throughput: 407k–1.06M drops/s depending on row count

**Builder's own artefacts (cross-check only, not trusted as evidence):**
`pytest tests/test_plinko.py` 193 passed in 1.58 s; `scripts/validate_plinko.py`
**RESULT|PASS**, 149/149 checks, 90,000,000 provably-fair rounds, worst |z| 1.89,
self-reported peak RSS 396 MB, 273.6 s. Its numbers are consistent with mine.

---

## 6. Biggest remaining gap

**Plinko is the only multi-config grid engine in the suite with no
module-level whole-grid renderer.** It exports exactly one module-level
function (`pascal_probabilities`), the thinnest surface of all ten engines.
Every other config-grid engine ships one: wheel `full_analytic_table` /
`all_configs`, keno `full_rtp_table`, mines and roulette and baccarat
`full_payout_table`, crash `analytic_table`. Plinko has the *largest* grid of
any of them (27 risk x rows configs, 9–17 pockets each) and is the one engine
where a caller most obviously wants `full_payout_table()` /
`all_configs()` — and instead has to loop the constructor and expand
`PAYTABLES` half-tables by hand. It is the one surface asymmetry an expert
could still point at in the module panel; it is cosmetic (no number is wrong,
nothing is unverifiable because of it), which is why it does not sink the
verdict.

*Context, not a gap to fix:* 8 of the 9 low-risk interior tables have no
reference anchor of any kind — the references publish no per-pocket grid for
them (Stake serves it at runtime via `PlinkoPayouts`, per its own documented
completeness caveat), and the WoO RTP column that would pin them is the proven
duplicate. Their RTPs do all sit inside WoO's stated 98.91–99.16 band, the one
low table WoO does print matches ours exactly, and the loss-pocket ordering
matches Stake's blog. This is the ceiling of the available ground truth, not
something the builder can close.
