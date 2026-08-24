# Plinko — Gauntlet Round 4 (independent critic, fresh eyes)

**Verdict: DOES NOT YET WIN.** The math is now airtight — every number the
references publish reproduces exactly, and 90,000,000 of my own rounds on the
real provably-fair stream land inside 3 SE with room to spare. What still gives
it away is the **simulator surface**: plinko's provably-fair campaign is
unchunked (2.5 GB peak at 10M drops vs 218 MB for its sibling games), its
headline `simulate()` is not the game's own RNG path, and its class/method/result
contract is the only one in the suite that does not match the other nine games.

Reviewed: `/home/user/troyrhinehart/casino/spinquest_sim/games/plinko.py`,
`/home/user/troyrhinehart/casino/scripts/validate_plinko.py`,
`/home/user/troyrhinehart/casino/tests/test_plinko.py`,
`/home/user/troyrhinehart/casino/spinquest_sim/rng.py` (bulk plinko path only).
Ground truth: `references/stake/plinko.md`, `references/woo/plinko.md` only.
Nothing from the builder's own scripts was reused as evidence.

---

## 1. What I actually ran

| Check | Method | Result |
|---|---|---|
| Analytic RTP + SD, 27 configs | Full pocket arrays **typed independently** by me, RTP/SD recomputed with `fractions.Fraction` (exact rationals, zero float64), then compared to the engine | 27/27 tables identical to the engine; max \|float64 − exact\| = **8.9e-16** |
| Stake payout-for-payout | dest / min win / max win **re-parsed from `references/stake/plinko.md`** by my own regex, 27 configs, + the blog facts | 27/27 exact, 0 mismatches |
| WoO RTP grid | exact rational RTP vs the re-parsed BGAMING grid | medium 9/9 exact, high 9/9 exact, low 8/9 differ (**reference defect**, §3) |
| WoO SD/RTP cross-tables | 4 CryptoGames + 3 BetFury through `from_table`, my own exact-rational SD | 4/4 SDs exact to 6 dp, 6/7 RTPs exact, 1 reference defect |
| Provably-fair path | **From-scratch** port of Stake's published `byteGenerator`/`generateFloats`/`floor(float*2)` (hmac+hashlib only, zero `spinquest_sim` imports), 1,620 rounds across all 27 configs + bulk spot rows | **0 mismatches** on floats, directions, pocket, path, multiplier, payout, seed hash |
| Empirical | **90,000,000 drops** through the public `simulate_provably_fair` (real HMAC-SHA256 stream), 10M each on 9 configs; my own SE, my own z, my own χ² | worst \|z\| = **1.36**, all χ² p ∈ [0.12, 0.92] |
| Row-level RNG | per-row right-fraction over 2M × 16 real-stream rows, + 240 pairwise row correlations | max \|z\| = 2.34; max \|corr\| = 0.00239 (3.4 SE, expected for max-of-240) |
| Builder's script | `scripts/validate_plinko.py`, run by me end to end | **PASS**, 148/148 checks, 270M fast + 30M provably-fair rounds, 107.9 s |
| Test suite | `pytest tests/test_plinko.py` | 182 passed, 0.43 s |
| Memory | RSS-sampled `simulate_provably_fair(10M, rows=16)` vs `Wheel.simulate(10M)` | **2,541 MB vs 218 MB** (§5, D1) |

## 2. Payout grid — clean, payout-for-payout

All 27 configs reproduce every number Stake publishes: destinations = rows+1,
min win, max win, exact, no rounding slack. Blog facts reproduce: 16/high edge
= 1000×, second-from-edge = 130×, P(edge, 16 rows) = 1/65536 = 0.0015 %, global
grid range exactly 0.2×–1000×. The three full-table anchors the references do
publish (WoO 8/low, WoO 16/medium, BetFury-Red = Stake 16/high) match verbatim.

Structural properties I checked that the builder does **not** test: every one of
the 27 tables is monotone non-increasing from edge to centre, and every minimum
sits exactly at the centre pocket. Both hold, 27/27 — a typo in any half-table
would have broken one of them. `_full_table`'s odd/even mirroring is correct.

No hardcoded empirical results anywhere. Both simulators genuinely index
`self.payouts`; `_summarize`'s `rtp` recomputed by me from
`pocket_counts @ payouts` agrees with the engine's to 1e-12 on every run.

## 3. The Low column is a reference defect — independently re-confirmed

Exact-rational RTP, low risk:

```
low/8  98.984375 % vs printed 98.91    low/13 98.999023 % vs 98.99
low/9  98.984375 % vs printed 99.14    low/14 99.000244 % vs 98.99
low/10 99.003906 % vs printed 98.91    low/15 99.000854 % vs 99.00  (only match)
low/11 99.003906 % vs printed 99.02    low/16 98.998718 % vs 98.99
low/12 98.979492 % vs printed 98.99
```

I re-derived the proof rather than taking round 1's word for it:

1. `grid[("low", r)] == grid[("medium", r)]` for **all 9 rows** — the captured
   Low column is a row-for-row duplicate of the Medium column.
2. The page's own verbatim low/8 table `5.6, 2.1, 1.1, 1, 0.5, …` evaluates to
   **98.984375 %**, not the 98.91 % printed beside it — and 98.91 % is exactly
   what the *medium*/8 table evaluates to. So Medium is the intact column and
   Low was overwritten, not the other way round.
3. Second, independent inconsistency in the same capture: the BetFury **Blue**
   table evaluates to **97.501831 %**, not the 97.88 % printed next to it (which
   is BetFury Green's value). Two duplicated-cell defects on one page.

The engine is right and the reference is wrong. But be honest about what that
costs: **8 of 9 low configs now have no exact RTP anchor at all** — they are
held only to the page's 98.91–99.16 % band, a 25-bp window that essentially any
plausible table passes. Combined with §4, only 3 of 27 configs have their full
pocket array verifiable against the references; the other 24 are pinned by
three numbers each (dest/min/max) plus an RTP that, for low risk, is a band.
That is a limit of the reference material, not a defect the builder introduced —
but it means "validated payout-for-payout" in the module docstring oversells.

## 4. Provably-fair path — bit-exact

My independent port of the published JS agreed with `PlinkoEngine.play` on all
1,620 rounds (27 configs × 60 nonces × 7 fields each). Verified separately that
a 16-row drop really does span two HMAC digests (rounds 0 and 1 of
`{clientSeed}:{nonce}:{round}`), matching Stake's published
"Plinko (2 increments per game)". Bulk rows 0/1/17/999/4999 are bit-identical to
the scalar reference. `plinko_directions` is literally `floor(f*2)` — no fudge.

## 5. Defects

### D1 — provably-fair simulator is unchunked: 2.5 GB at 10M drops (biggest)

`simulate_provably_fair` passes `n_rounds` straight into
`bulk.plinko_directions(rows, n_rounds)`. `BulkRng._chunks` bounds only the
*digest* work; `float_matrix` still allocates the full `(n, rows)` float64
output, which is then floored to another float array and cast to another int64
array. Measured peak RSS, sampled every 50 ms:

```
plinko.simulate_provably_fair(5,000,000, rows=16)  ->  1,320 MB
plinko.simulate_provably_fair(10,000,000, rows=16) ->  2,541 MB
wheel.simulate(10,000,000)                         ->    218 MB   (sibling game)
```

That is **5× over the project's stated <500 MB-per-chunk budget**, and
`scripts/validate_plinko.py` trips it twice per run (medium/16 and high/16 at
10M each). Every sibling game — Keno, Mines, Wheel, Roulette — takes
`chunk_rounds`, loops, and accumulates a `bincount` histogram, and each says so
in its docstring ("chunked so per-chunk arrays stay well under 500 MB"). Plinko
needs nothing but a per-pocket histogram, so the fix is mechanical; the current
code is the only one in the suite that materialises the whole campaign. A user
asking for 100M drops needs 25 GB.

### D2 — the headline `simulate()` is not the game's RNG path, and the suite contract is broken

`PlinkoEngine.simulate()` draws `np.random.default_rng().binomial(rows, 0.5)`.
It never touches `floor(float*2)` or the HMAC stream. In every other game in
this codebase `simulate()` **is** the provably-fair campaign (`bulk: BulkRng`,
`chunk_rounds`, `progress`), and the fast surrogate does not exist. So
`validate_plinko.py`'s advertised 270,000,000 rounds are 270M rounds of numpy's
PCG64, with only 30M on the real stream. Distributionally identical, so not a
correctness fudge — but it is not what the same word means anywhere else in the
suite. The divergence is not limited to that one method:

| | 9 sibling games | plinko |
|---|---|---|
| class name | `Keno`, `Mines`, `Wheel`, `Roulette`, … | `PlinkoEngine` |
| single round | `play_round(...)` | `play(...)` |
| `simulate()` | provably-fair BulkRng campaign, chunked | numpy PCG64 surrogate, and a *second* method for the real stream |
| result keys | `n_rounds`, `analytic_std_per_unit`, `se_rtp`, `z_score`, `within_3se` | `rounds`, `rtp_standard_error`, `rtp_z`, no `within_3se` |
| `rtp` / `std_per_unit` | attributes | methods |

Strip the filenames off the ten game modules and hand them to an expert: plinko
is picked out immediately as the module written by a different hand.

### D3 — round-1 doc bug still unfixed after three rounds

`simulate`'s docstring: *"works in chunks of `chunk` int8 draws (<500 MB)"*.
`gen.binomial` returns **int64**; the default 20M chunk is 160 MB, not 20 MB.
Flagged in round 1 (D3), still verbatim in the source at line 331.

### D4 — unguarded provably-fair inputs

```
play(server_seed="", client_seed="c", nonce=0)      -> OK, returns a full result
play(server_seed="a"*64, client_seed="c", nonce=-1) -> OK, pocket=2, path="..."
```

Stake's published spec is a 64-character hex server seed and a nonce that
"increments as every new bet is made" — both start at a bet, so neither an empty
seed nor a negative nonce is a reachable state on the reference. Round 1 flagged
the negative nonce (D5); the bet guard was added, the nonce guard was not. Low
severity, but a verifier that accepts `serverSeed=""` is not the reference.

### D5 — nothing else

`chunk<=0` no longer hangs (round-1 D1 fixed, regression-tested).
`config()["payouts"]` renders `110, 41, 10, 5, 3, 1.5` not `110.0, …` (round-1
D4 fixed). `from_table` exists and the four CryptoGames SDs are asserted
(round-1 D2 fixed — I re-derived all four with exact rationals and they match to
the printed sixth decimal). `bet` is validated. `payouts` is read-only and
copied. `simulate` seed-deterministic. Bad rows/risk/table rejected.

## 6. Empirical — passes on my numbers, not the builder's

90,000,000 drops on the **real HMAC-SHA256 stream** via the public API, 9 configs
× 10M, distinct 64-hex server seed each, my own exact-rational μ and σ:

```
cfg            n            emp_rtp     exact_rtp    my_SE     my_z    chi2  df      p
high/16     10,000,000     0.988320     0.989764   2.076e-03  -0.70   10.354  16  0.8475
medium/16   10,000,000     0.989548     0.989883   4.640e-04  -0.72   13.860  16  0.6092
low/8       10,000,000     0.989740     0.989844   1.765e-04  -0.59   12.188   8  0.1430
high/8      10,000,000     0.990647     0.990625   8.445e-04  +0.03    3.190   8  0.9219
medium/14   10,000,000     0.989354     0.989941   4.308e-04  -1.36   12.911  14  0.5336
low/15      10,000,000     0.989908     0.990009   1.297e-04  -0.77   21.493  15  0.1218
high/11     10,000,000     0.991438     0.991602   1.305e-03  -0.13   10.671  11  0.4712
low/12      10,000,000     0.989667     0.989795   1.227e-04  -1.04    9.166  12  0.6887
medium/9    10,000,000     0.991406*    0.991406   4.050e-04  -0.46    5.041   9  0.8307
```

Worst \|z\| = **1.36** (bound 3.0). Every pocket histogram passes χ² against the
exact binomial. Per-row right-fraction over 2M × 16 real rows: max \|z\| = 2.34.
Builder's own script, run by me: PASS, 148/148, worst \|z\| = 2.15 (fast) /
1.26 (provably fair). Runtime 252.6 s for my 90M; 107.9 s for validate.
(*emp 0.991218; exact 0.991406 — z as printed.)

**Statistics: PASS.**

## 7. Blind comparison

**Panel A — 27-config RTP grid, columns unlabelled.** 19/27 cells identical; the
8 differing cells are all in Low. Column A's Low column is a byte-for-byte
duplicate of its own Medium column, and A's own printed low/8 pay table does not
evaluate to A's own low/8 RTP. An expert *can* tell the columns apart, and picks
A as the flawed transcription. **Favours ours.**

**Panel B — full pay tables (the 3 the references print) + blog facts.**
Indistinguishable. Formatting tell from round 1 is gone.

**Panel C — CryptoGames RTP + SD (0.562711 / 0.517632 / 0.464829 / 3.678698).**
Both columns produce all four to six decimals, plus the BetFury RTPs and the
Blue self-inconsistency. Indistinguishable. Round-1 Panel 4 is closed.

**Panel D — the artifact itself, ten unlabelled game modules.** Plinko is picked
out on sight: it is the only class suffixed `Engine`, the only one whose round
method is `play` not `play_round`, the only one whose `simulate()` is a
non-provably-fair surrogate, the only one with a second `simulate_*` method, the
only one with `rounds`/`rtp_z` instead of `n_rounds`/`z_score`/`within_3se`, and
the only one that allocates 2.5 GB where its siblings allocate 0.2 GB for the
same 10M rounds. **Gives ours away immediately.**

**Blind result: not a coin flip.** Panels A–C are a wash or favour ours; Panel D
identifies ours as the bolted-on piece.

## 8. Verdict

- Payout match: **PASS** — 27/27 configs, every published number exact; the two
  numbers that disagree are provable reference-internal defects (WoO Low column,
  BetFury Blue), both re-confirmed by me from first principles.
- Statistics: **PASS** — 90M own rounds on the real provably-fair path, worst
  \|z\| = 1.36 < 3, χ² clean, per-row bias clean, float64 vs exact ≤ 8.9e-16.
- Blind: **FAIL** — Panel D (D1/D2).
- Resource discipline: **FAIL** — 2,541 MB peak at 10M drops, 5× the project's
  stated <500 MB budget; `validate_plinko.py` itself trips it twice per run.

**ours_wins = false.**

**Single biggest gap:** replace `simulate_provably_fair` + surrogate `simulate`
with the suite's standard contract — one
`simulate(n_rounds, bulk=None, chunk_rounds=2_000_000, progress=True)` that
loops `bulk.plinko_directions(rows, step)` in chunks and accumulates a
`np.bincount` pocket histogram (exactly the Keno/Mines/Wheel pattern), renaming
the class to `Plinko`, the round method to `play_round`, and the result keys to
`n_rounds` / `analytic_std_per_unit` / `se_rtp` / `z_score` / `within_3se`.
That one change drops 10M-round peak memory from 2,541 MB to ~200 MB, puts the
validation script's headline rounds back on the game's own RNG, and removes
every tell in Panel D — the only panel that still identifies ours as the
imitation.
