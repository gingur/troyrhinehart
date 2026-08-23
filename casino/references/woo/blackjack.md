# Wizard of Odds — Blackjack

Captured: 2026-08-23. Key: `blackjack`.

## Stake-specific page?

**No.** Unlike Mines, Plinko, Crash, Dice, Limbo, Keno, Wheel, and Hilo, the Wizard of
Odds has **no Stake-Originals-specific Blackjack page** (`wizardofodds.com/games/blackjack-stake/`
returns 404 as of the capture date). The closest authoritative equivalents are his classic
blackjack pages, in particular the **infinite-deck expected-return analysis** (Stake
Originals Blackjack deals from a continuously reshuffled shoe, which infinite-deck math
approximates) plus his house-edge/variance appendices. Those are captured below.

## Headline house edge / RTP

| Configuration | House edge | RTP | Source |
|---|---|---|---|
| Liberal Vegas Strip rules (6 decks, S17, DOA, DAS, resplit aces, late surrender), basic strategy | **0.28%** | 99.72% | /gambling/house-edge/ |
| Infinite deck, S17, DAS, split to 3 hands (aces once, one card), no surrender — optimal strategy | **0.511734%** (player EV −0.511734%) | 99.488% | /games/blackjack/expected-return-infinite-deck/ |
| Six-deck benchmark (S17, no DAS, no surrender, no resplit aces), basic strategy, cut-card game | **0.573%** | 99.427% | /games/blackjack/variance/ |

RTP here is per initial bet (house edge defined as ratio of average loss to the initial
bet). Actual house edge varies with the exact rule set; the Wizard's
[house edge calculator](https://wizardofodds.com/games/blackjack/calculator/) gives the
edge for virtually any rule combination under basic strategy. Poor play raises it
substantially (e.g. "never bust" strategy ≈ 3.91%, "mimic the dealer" ≈ 5.48%).

## Standard deviation / variance

From the house-edge comparison page and the "Variance in Blackjack" appendix
(figures per initial/unit bet):

| Configuration | Variance | Std. dev. | Notes |
|---|---|---|---|
| Blackjack, Liberal Vegas rules (headline) | ~1.32 | **1.15** | /gambling/house-edge/ |
| Liberal Strip rules, 6 decks, 1 hand | 1.303 | **1.142** | /games/blackjack/variance/ |
| Liberal Strip rules, 2 simultaneous hands | 3.565 per round; 1.782 per hand | 1.335 per hand | includes covariance between hands |
| Liberal Strip rules, 3 simultaneous hands | 6.785 per round; 2.262 per hand | 1.504 per hand | |
| 6-deck benchmark (S17, no DAS, no surrender, no RSA) | 1.295 (covariance 0.478) | ~1.138 | validated vs. Stanford Wong's 1.28 / 0.47 |

Rule effects on variance (vs. benchmark): stand on soft 17 −0.00838; double after split
+0.03753; surrender −0.03629; resplit aces +0.00207.

Total variance for n simultaneous hands: `n·v + n·(n−1)·c` where v = single-hand
variance and c = covariance between hands. A commonly cited round-number SD for
blackjack elsewhere on the site is ~1.17.

## Methodology notes

- **Basic strategy assumed** throughout; house edge = mean loss / initial wager. SD
  measures bankroll volatility per unit initial bet (~68.26% of session results fall
  within 1 SD).
- **Variance figures** come from simulations of roughly 10 billion hands under basic
  strategy in **cut-card games** (the cut-card effect slightly worsens the player return
  versus a fixed number of rounds).
- **Infinite-deck analysis** is exact combinatorial: expected-return tables for every
  decision (stand/hit/double/split) by player total vs. dealer upcard; optimal play picks
  the max-EV action. Strategy differs from 4-deck play only in hitting soft 13 vs 5 and
  soft 15 vs 4 (dealer stands soft 17). A spreadsheet version allows infinite resplits;
  published tables cap resplits at three (aces excluded).
- The Wizard distinguishes total-dependent from composition-dependent strategy; his
  calculator and rule-variation tables quantify each rule's effect on the edge.

## Source URLs

- https://wizardofodds.com/games/blackjack/ (main guide)
- https://wizardofodds.com/gambling/house-edge/ (house edge 0.28%, SD 1.15, definitions)
- https://wizardofodds.com/games/blackjack/variance/ (variance/covariance appendix)
- https://wizardofodds.com/games/blackjack/expected-return-infinite-deck/ (infinite deck, EV −0.511734%)
- https://wizardofodds.com/games/blackjack/calculator/ (house edge calculator, any rule set)
- https://wizardofodds.com/games/blackjack/basics/ (basics; cost of bad strategies)
- https://wizardofodds.com/games/blackjack/strategy/calculator/ (basic strategy calculator)
