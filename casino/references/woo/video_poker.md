# Wizard of Odds — Video Poker (key: video_poker)

Captured: 2026-08-23

## Stake-specific coverage

The Wizard has **no Stake Originals-specific video poker analysis page** (unlike Mines,
Plinko, Crash, Dice, Limbo, Keno, Wheel, HiLo). His Stake casino review confirms video
poker at Stake comes from third-party providers (Microgaming, NetEnt, Play'n GO,
Pragmatic Play, Red Rake), not the Originals line. Per-title returns he lists for Stake:

**Microgaming at Stake** (returns as listed in the Wizard's Stake review):

| Game | Return |
|---|---|
| All Aces | 99.92% |
| Jacks or Better | 99.54% |
| All American | 99.38% |
| Aces & Faces | 99.26% |
| Double Bonus | 99.16% |
| Bonus Deuces Wild | 99.15% |
| Tens or Better | 99.14% |
| Aces & Eights | 99.09% |
| Deuces & Joker | 99.07% |
| Double Double Bonus | 98.98% |
| Joker Poker (kings or better) | 98.60% |
| Bonus Poker Deluxe | 98.49% |
| Double Joker | 98.10% |
| Deuces Wild | 96.77% |
| Louisiana Double | 93.45% |

**NetEnt at Stake:** Jacks or Better 99.56%, All American 98.11%, Deuces Wild 97.97%.
Other providers (Play'n GO, Pragmatic, Red Rake) range 94.97%–99.77%.

The authoritative analysis therefore comes from the Wizard's classic video poker pages,
captured below.

## Headline figures — Jacks or Better (the benchmark game)

- **Full-pay 9/6 Jacks or Better: 99.54% return (0.46% house edge) with optimal
  strategy, standard deviation 4.42 per hand** (more precisely 4.417542).
- Return assumes max-coin bet (royal pays 800:1); all figures are per-unit-wagered
  under computer-perfect play.

### Jacks or Better pay-table variants (return with optimal strategy)

| Pay table (FH/Flush) | Return |
|---|---|
| 9/6 "full pay" | 99.54% |
| 9/5 | 98.45% |
| 8/6 | 98.39% |
| 8/5 | 97.30% |
| 7/5 | 96.15% |
| 6/5 | 95.00% |
| NetEnt 40-20-9-6-5 | 99.56% |
| Gtech 20/7/5 | 94.97% |

The Wizard also notes the practical strategy gap: e.g., using conventional 8/5 strategy
returns 99.68% on some tables where optimal returns 100.08% (Ask the Wizard, probability
section) — i.e., simplified strategies cost only a few hundredths of a percent.

## Standard deviation / variance

Per-hand SD for single-play, optimal strategy (from the JoB table page and Appendix 3):

| Game (full pay) | SD (1 play) |
|---|---|
| Jacks or Better 9/6 | 4.42 |
| Bonus Poker 8/5 | 4.57 |
| Deuces Wild 25-15-10-4-4-3 | 5.07 |
| Double Bonus 9/7/5 | 5.34 |
| Bonus Deuces Wild 9-4-4-3 | 5.72 |
| Double Double Bonus 9/6 | 6.48 |

### Multihand (n-play) standard deviation per hand — Appendix 3

Formula: total variance for n-play = n·v + n·(n−1)·c, where v = variance of one hand
and c = covariance between any two hands (hands share the same dealt 5 cards, so they
are positively correlated).

| Plays | JoB 9/6 | Bonus 8/5 | Dbl Bonus 9/7/5 | DDB 9/6 | Deuces Wild | Bonus Deuces |
|---|---|---|---|---|---|---|
| 1 | 4.42 | 4.57 | 5.34 | 6.48 | 5.07 | 5.72 |
| 3 | 4.84 | 5.01 | 5.94 | 7.18 | 5.63 | 6.35 |
| 5 | 5.23 | 5.42 | 6.48 | 7.82 | 6.15 | 6.92 |
| 10 | 6.10 | 6.32 | 7.66 | 9.23 | 7.27 | 8.18 |
| 50 | 10.76 | 11.17 | 13.88 | 16.66 | 13.19 | 14.80 |
| 100 | 14.64 | 15.19 | 18.98 | 22.76 | 18.03 | 20.24 |

(SD "per hand" — total bet SD divided by number of plays; grows with plays because of
the shared-deal covariance.)

## Methodology notes (Wizard's video poker methodology page)

- Exhaustive combinatorial analysis: all C(52,5) = 2,598,960 starting hands × all 32
  hold/discard subsets, choosing the maximum-EV hold for each hand; aggregate = game
  return. No simulation — results are exact.
- Suit-equivalence reduction collapses the 2,598,960 hands to 134,459 structural hand
  classes, each weighted by the number of real hands it represents.
- Pre-computed scoring arrays (all complete hands scored once; indexed arrays for each
  number of discards, evaluated with inclusion-exclusion) avoid looping over the
  1,533,939 possible replacement draws — cutting run time from hours to ~3 seconds.
- Variance for n-play uses the covariance formula above (Appendix 3); Appendix 1 covers
  bankroll size vs. risk of ruin.

## Sources

- Jacks or Better pay tables & returns: https://wizardofodds.com/games/video-poker/tables/jacks-or-better/
- Main video poker guide: https://wizardofodds.com/games/video-poker/
- Methodology: https://wizardofodds.com/games/video-poker/methodology/
- Appendix 3 (multihand standard deviation): https://wizardofodds.com/games/video-poker/appendix/3/
- Appendix 1 (bankroll vs. risk of ruin): https://wizardofodds.com/games/video-poker/appendix/1/
- Stake casino review (per-provider video poker returns): https://wizardofodds.com/online-casinos/reviews/stake-casino/
- Ask the Wizard — video poker probability: https://wizardofodds.com/ask-the-wizard/video-poker/probability/
