# Wizard of Odds — Baccarat

Captured: 2026-08-23

## Stake-specific page?

**No.** Unlike Mines, Plinko, Crash, Dice, Limbo, Keno, Wheel, and Hilo, the Wizard of Odds
has **no Stake-Originals-specific baccarat page** (`wizardofodds.com/games/baccarat-stake/`
returns 404, and site searches surface no such page). Baccarat on Stake is the standard
punto banco game, so the Wizard's classic baccarat analysis below is the authoritative
equivalent and applies directly (Stake's baccarat uses standard 8-deck punto banco rules
with 0.95-to-1 Banker payout).

## House edge by bet and deck count

House edge = ratio of average loss to initial bet, **ties included** in the calculation
(the Wizard explicitly counts unresolved/tie hands, unlike some sources).

| Decks | Banker | Player | Tie (8:1) | Pair bets (11:1) |
|-------|--------|--------|-----------|------------------|
| 8 (standard) | **1.06%** | **1.24%** | **14.36%** | 10.36% |
| 6 | 1.06% | 1.24% | 14.44% | 11.25% |
| 1 | 1.01% | 1.29% | 15.75% | 29.41% |
| Infinite | 1.064% | 1.228% | 14.117% | 7.69% |

Equivalent RTP (8-deck): Banker **98.94%**, Player **98.76%**, Tie **85.64%**,
Pair bets 89.64%.

Note: many other sources quote house edge excluding ties (bet only resolved hands),
which yields ~1.17% Banker / ~1.36% Player; the Wizard's headline figures include ties.

## Win probabilities (8-deck)

- Banker wins: 45.86%
- Player wins: 44.62%
- Tie: 9.52%

## Standard deviation

Published on the Wizard's House Edge master table (per unit initially bet):

| Bet | Standard deviation |
|-----|--------------------|
| Banker | **0.93** |
| Player | **0.95** |
| Tie | **2.64** |

The Wizard defines standard deviation as "a measure of how volatile your bankroll will
be playing a given game" — ~68.26% of session results fall within one SD of expectation.

## Methodology notes

- Figures derive from **exact combinatorial analysis** of all possible hand outcomes for
  the given shoe composition, applying the fixed punto banco third-card drawing rules;
  no simulation needed.
- Banker bet assumes the standard **5% commission** on Banker wins (pays 0.95:1).
- Tie pays 8:1; Pair bets pay 11:1 (some casinos pay 9:1 on Tie, cutting its house edge
  to ~4.84% — not the standard configuration).
- House edge counts ties as resolved pushes (average loss / initial bet including ties).
- Baccarat Appendix 1 publishes the full probability distribution of every final
  Player/Banker total combination for an 8-deck shoe (combination counts and
  probabilities), the underlying data for the house-edge figures.
- Further appendices cover effects of card removal (card counting), mid-hand win
  probabilities, streaks, side bets, and commission-free variants.

## Sources

- https://wizardofodds.com/games/baccarat/ — main baccarat guide (calculator, appendix index)
- https://wizardofodds.com/games/baccarat/basics/ — house edge tables per deck count, probabilities, rules
- https://wizardofodds.com/gambling/house-edge/ — house edge + standard deviation master table, definitions
- https://wizardofodds.com/games/baccarat/appendix/1/ — full 8-deck outcome probability tables
- https://wizardofodds.com/games/baccarat/calculator/ — odds calculator for arbitrary shoe compositions
