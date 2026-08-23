# Wizard of Odds — Roulette (key: roulette)

Captured: 2026-08-23

## Stake-specific page?

**No.** Unlike Mines, Plinko, Crash, Dice, Limbo, Keno, Wheel, and Hilo, the Wizard of
Odds has **no Stake Originals page for roulette** (no `/games/roulette-stake/` or
equivalent; confirmed by site search). Stake's "Roulette" Original is a standard
**European single-zero wheel**, which the Wizard's classic roulette analysis covers
directly. The figures below are his classic-page numbers; the single-zero column is the
one that applies to Stake's implementation.

## House edge / RTP by wheel configuration

General formula the Wizard gives: **house edge = z / (36 + z)**, where z = number of
zeroes on the wheel.

| Configuration | House edge | RTP | Notes |
|---|---|---|---|
| Single-zero (European / Stake Originals) | **2.70%** (1/37) | **97.30%** | Applies to ALL bets |
| Double-zero (American) | **5.26%** (2/38) | **94.74%** | All bets except one (below) |
| Double-zero, First Five bet (0-00-1-2-3, pays 6:1) | **7.89%** | 92.11% | The only bet with a different edge on a 38-slot wheel |
| Triple-zero | **7.69%** (1/13) | 92.31% | Every bet |
| Quadruple-zero | **10%** (4/40) | 90.00% | Every bet |
| Double-zero + Atlantic City rules (even-money bets, half back on 0/00) | **2.63%** | 97.37% | Even-money bets only |
| Single-zero + la partage / French rule (half back on zero, even-money bets) | **1.35%** | 98.65% | Wizard's imprisonment EV tables land at approx. -1.35% to -1.37%, "comparable to losing half the bet" |

## Bet-by-bet table (double-zero wheel)

All bets 5.26% house edge except First Five.

| Bet | Pays | Probability of win |
|---|---|---|
| Red / Black / Odd / Even / 1-18 / 19-36 | 1:1 | 47.37% |
| Dozens / Columns | 2:1 | 31.58% |
| Six line | 5:1 | 15.79% |
| Corner | 8:1 | 10.53% |
| Street | 11:1 | 7.89% |
| Split | 17:1 | 5.26% |
| Single number | 35:1 | 2.63% |
| First Five (0-00-1-2-3) | 6:1 | 13.16% (edge 7.89%) |

On a single-zero wheel the same payouts apply with 37 slots, giving 2.70% on every bet
(there is no First Five bet).

## Standard deviation / variance

The Wizard's house-edge comparison table lists roulette's SD with a footnote:
**"standard deviation depends on bet made"** — there is no single SD for the game.
Published per-unit ($1 bet, one spin) figures, double-zero wheel (Ask The Wizard #65):

| Bet (double-zero) | SD per unit wagered |
|---|---|
| Any even-money bet | **0.998614** |
| Single number | **5.762617** |

These follow from the standard discrete-distribution calculation
(SD = sqrt(E[X^2] - EV^2); e.g. even money: sqrt(1 - (2/38)^2) = 0.998614;
single number: sqrt((35^2 + 37)/38 - (2/38)^2) = 5.762617).

Derived by the same method for the **single-zero (Stake) wheel** (not explicitly
printed by the Wizard, but exactly his formula):

| Bet (single-zero) | SD per unit wagered (derived) |
|---|---|
| Any even-money bet | 0.999635 |
| Single number | 5.837800 |

Session scaling (Wizard's methodology, house-edge page): "The standard deviation of the
final result over n bets is the product of the standard deviation for one bet and the
square root of the number of initial bets made in the session."

Worked binomial example (Ask The Wizard, roulette general): tracking one dozen over
3,000 double-zero spins — variance = 3000 * (12/38) * (1 - 12/38) = 648.20,
SD = sqrt(648.20) = 25.46 occurrences.

## Methodology notes

- All figures are **exact combinatorial probabilities** from wheel composition (37, 38,
  39, or 40 equally likely slots) — no simulation needed.
- Every standard bet on a given wheel returns the same EV (e.g. -2/38 per unit on
  double-zero); bet choice changes only volatility, not expected return.
- For session-level "probability of finishing ahead" questions he applies a **normal
  approximation** using the per-bet SD scaled by sqrt(n); he notes even-money bets give
  a sharp bell curve (results cluster near expected loss) while single-number bets give
  a wide one.
- Imprisonment/en-prison variants analyzed with full outcome trees (single vs. infinite
  imprisonment): win approx. 48.65%, push 1.31-1.33%, EV approx. -1.35% to -1.37% on
  even-money bets.

## Sources

- https://wizardofodds.com/games/roulette/ (hub page)
- https://wizardofodds.com/games/roulette/basics/ (house edges by variant, bet tables, imprisonment analysis)
- https://wizardofodds.com/gambling/house-edge/ (comparison table; SD footnote and session-scaling formula)
- https://wizardofodds.com/ask-the-wizard/65/ (per-bet standard deviations, double-zero)
- https://wizardofodds.com/ask-the-wizard/roulette/general/ (binomial variance worked example)
