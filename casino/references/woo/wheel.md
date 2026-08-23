# Wizard of Odds — Wheel

Captured: 2026-08-23. Key: `wheel`.

## Stake-specific page?

**No.** As of the capture date, the Wizard of Odds has **no page analyzing the Stake
Originals "Wheel" game** (the multiplier wheel with Low/Medium/High risk and
10/20/30/40/50 segments). Checked:

- `wizardofodds.com/games/wheel/` — **404**
- `wizardofodds.com/games/wheel-stake/` — **404**
- `wizardofodds.com/games/wheel-cryptocurrency/` — **404**
- Site search for wheel pages under `/games/` surfaces only: Wheel by TvBet,
  Wheel by BetGames, Wheel of Fortune, Big Six, Money Wheel, Wheel of Dice.
- His Stake Casino review (`/online-casinos/reviews/stake-casino/`) mentions Stake
  Originals exist but gives **no RTP/house-edge math for Wheel** or any other original.
- His TonySpins review lists an original called "Wheel" but provides no analysis.

So there is **no Wizard-published per-risk/per-segment RTP table for this game**.
Stake's own published figure for Wheel is 99% RTP (1% house edge) at every
risk/segment setting, max payout 49.5x (50 segments, High risk) — but that figure is
Stake's, not the Wizard's; he has not independently verified it.

The closest authoritative equivalents he does publish are captured below.

## Closest equivalent 1 — Wheel by TvBet

Source: https://wizardofodds.com/games/wheel-tvbet/

Live vertical wheel with **38 stops**, numbered/colored like double-zero roulette.
All wins are **"for one"** (payout includes/replaces the stake). Zero and double-zero
lose all outside-style bets.

| Bet | Pays (for one) | Return | House edge |
|---|---|---|---|
| Specific number | 36 | 0.947368 | 5.26% |
| Specific column | 12 | 0.947368 | 5.26% |
| Group of 12 (dozen) | 3.008 | 0.949895 | 5.01% |
| Color / Odd-Even / Low-High / Over-Under 18.5 | 2.006 | 0.950211 | 4.98% |
| Under 14.5 / Over 22.5 | 2.579 | ~0.947–0.950 | ~5% |
| Over 14.5 / Under 22.5 | 1.641 | ~0.947–0.950 | ~5% |
| Under 9.5 / Over 27.5 | 4.011 | ~0.947–0.950 | ~5% |
| Over 9.5 / Under 27.5 | 1.337 | ~0.947–0.950 | ~5% |

All returns fall between 94.74% and 95.02%. No standard deviation published on this page.

## Closest equivalent 2 — Wheel (BetGames) / Wheel of Fortune

Sources: https://wizardofodds.com/games/wheel-betgames/ ,
https://wizardofodds.com/games/wheel-of-fortune/

Vertical wheel with **19 stops**: numbers 1–18 (6 red, 6 black, 6 grey, each color
split evenly odd/even) plus a trophy. All wins are "for one."

| Bet | Pays (for one) | Winning stops |
|---|---|---|
| Specific number or trophy | 18 | 1 |
| Range 1–6 / 7–12 / 13–18 | 3 | 6 |
| Under 9.5 / Over 9.5 | 2 | 9 |
| Color (grey/red/black) | 3 | 6 |
| Odd / Even | 2 | 9 |
| Color + odd/even combo | 6 | 3 |

**Every bet returns 18/19 = 94.74%** (house edge **5.26%**, same as double-zero
roulette). No standard deviation published on the game page.

## Closest equivalent 3 — Big Six & Money Wheel (with standard deviations)

Sources: https://wizardofodds.com/gambling/house-edge/ ,
https://wizardofodds.com/games/big-six/ , https://wizardofodds.com/games/money-wheel/

Big Six (classic 54-stop casino money wheel) — the only wheel game on the Wizard's
master house-edge table, which is also the only place he publishes **standard
deviations** for a wheel game (per unit bet):

| Bet | House edge | Standard deviation |
|---|---|---|
| $1 | 11.11% | **0.99** |
| $2 | 16.67% | **1.34** |
| $5 | 22.22% | **2.02** |
| $10 | 18.52% | **2.88** |
| $20 | 22.22% | **3.97** |
| Joker/Logo (45:1) | 24.07% | **5.35** |

Money Wheel (56-stop Big Six variant with multiplier stops): house edge by bet —
$1: 6.12%, $2: 6.25%, $5: 10.71%, $10: 5.61% (best), $20: 9.44%, $40: 11.35%.
No SD published.

## Context — the 99% crypto-original benchmark

Source: https://wizardofodds.com/games/dice-cryptocurrency/

For provably-fair crypto originals (the family Stake Wheel belongs to), the Wizard
documents the standard ~1% house edge design: e.g. crypto Dice pays 2-for-1 on a
49.50%-probability win → **99.0% RTP**; adjustable variants at 99.5% / 98.5%. This is
the same design target Stake states for Wheel (99% RTP at all settings). His crypto
pages (Plinko, Mines/minesweeper-cryptocurrency, Dice) consistently find returns in
the 95–99.5% band for these originals.

## Methodology notes (Wizard's definitions)

- **House edge** = ratio of average loss to the initial bet.
- **Standard deviation** = "a measure of how volatile your bankroll will be playing a
  given game"; ~68% of session results fall within one SD of expectation.
- Wheel games: returns computed exactly from stop counts × pay table (all wins
  quoted "for one" on the TvBet/BetGames pages).
- Crypto originals: he verifies provable fairness via the SHA-512 server/client seed
  scheme and recommends salting the client seed; he publishes a PHP verification
  script on the crypto Dice page.

## Note for our model (not WoO data)

Stake's Wheel (Low/Medium/High risk; 10/20/30/40/50 segments) is stated by Stake to
return **99.0%** in every configuration; only the variance changes with risk/segments
(max multiplier 49.5x at 50 segments High risk; High risk is winner-take-nothing on
most segments). No Wizard-published SD exists for it; per-configuration SD must be
computed from Stake's pay tables directly.

## Source URLs

- https://wizardofodds.com/games/wheel-tvbet/
- https://wizardofodds.com/games/wheel-betgames/
- https://wizardofodds.com/games/wheel-of-fortune/
- https://wizardofodds.com/games/big-six/
- https://wizardofodds.com/games/money-wheel/
- https://wizardofodds.com/gambling/house-edge/
- https://wizardofodds.com/games/dice-cryptocurrency/
- https://wizardofodds.com/online-casinos/reviews/stake-casino/
