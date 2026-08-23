# Wizard of Odds — Keno (key: keno)

Captured: 2026-08-23

## Stake-specific coverage: NONE

**The Wizard of Odds has no page analyzing Stake's Keno original** (the 40-number,
pick-1-to-10, draw-10 game with Classic/Low/Medium/High risk pay tables). Checked
2026-08-23: `wizardofodds.com/games/keno-stake/` returns 404, and site searches for
Stake keno analysis surface only Stake *casino reviews* (which name Keno among the
Originals but publish no math). Stake's own claim of ~99% RTP / 1% house edge for its
Keno comes from stake.com, not from the Wizard, and is NOT independently verified here.

The closest authoritative equivalent the Wizard publishes is his **40-Ball Keno**
analysis (Gamesys "40-Number Instant Keno"), which shares Stake Keno's core structure:
40 numbers, 10 balls drawn, player picks a subset. Pay tables differ from Stake's, so
its RTPs are indicative of the format, not of Stake's game.

## Closest equivalent: 40-Ball Keno (Gamesys)

Source: https://wizardofodds.com/games/keno/40-ball/

Rules: player picks 3–10 numbers from 1–40; the game draws 10.

### Return (RTP) per number of picks

| Picks | Return |
|-------|--------|
| 3     | 97.47% |
| 4     | 96.48% |
| 5     | 96.15% |
| 6     | 96.63% |
| 7     | 95.66% |
| 8     | 97.48% |
| 9     | 96.87% |
| 10    | 97.90% (best) |

Range: 95.66% (pick 7) to 97.90% (pick 10). "The greatest return is for the pick-10
at 97.90%."

### Pay table (pays per catch, for-one)

- Pick 3: 2→5, 3→24
- Pick 4: 2→2, 3→10, 4→62
- Pick 5: 2→1, 3→5, 4→25, 5→125
- Pick 6: 2→1, 3→2, 4→10, 5→50, 6→1000
- Pick 7: 3→2, 4→8, 5→25, 6→250, 7→1000
- Pick 8: 3→1, 4→4, 5→8, 6→250, 7→1000, 8→5000
- Pick 9: 3→1, 4→2, 5→12, 6→25, 7→500, 8→2500, 9→10000
- Pick 10: 4→2, 5→8, 6→25, 7→250, 8→1250, 9→10000, 10→20000

(All unlisted catch counts pay 0.)

No standard deviation / variance figures are published on the 40-ball page.

## Classic 80-number keno (Wizard's main coverage)

Main page: https://wizardofodds.com/games/keno/

Survey-style return figures (no per-pick breakdown on the main page):

- Live keno, Las Vegas 2001 survey: returns 65%–80% (house edge 20–35%)
- Live keno, Laughlin 2012 survey: returns 50%–74%
- Video keno, San Diego 2008 survey: returns 84%–95%

Spot Keno page: https://wizardofodds.com/games/keno/spot-keno/
Seven common video-keno pay tables analyzed, picks 1–10. Return ranges by pay table:

- Pay Table 1: 84.25%–86.43%
- Pay Table 2: 83.25%–86.72%
- Pay Table 3: 75% (pick 1) – 90.19%
- Pay Table 4: 84.18%–90.85%
- Pay Table 5: 75%–92.67%
- Pay Table 6: ~92.6%–92.9% (picks 2–10)
- Pay Table 7: 75%–94.99%

Keno Odds appendix: https://wizardofodds.com/games/keno/appendix/3/
Full probability tables (combinations, probability, return contribution) for catching
x of y picks, picks 1–15, standard 80-number / 20-draw keno (payoffs referenced to the
Atlantic City Tropicana).

## Standard deviation / variance (what the Wizard publishes)

1. **House Edge of Casino Games Compared**
   https://wizardofodds.com/gambling/house-edge/
   Keno row: house edge **25%–29%**, standard deviation **1.30–46.04** (per unit bet).
   The huge SD range reflects pick count and pay table: few picks with small flat pays
   sit near the low end; many picks with jackpot-heavy tables (10,000x-style top pays)
   drive SD toward the high end. No footnote elaborates further on the page.

2. **Variance in Multi-Card Keno**
   https://wizardofodds.com/games/keno/multi-card-variance/
   Explicit variance/SD math for video keno (4–20 card play). Reference pay tables:
   - Pick 6: 3-4-68-1500 → single-card variance **305.33**, SD **17.47** (per unit)
   - Pick 9: 1-6-44-300-4700-10000
   - Pick 10: 5-23-132-1000-4500-10000

   Multi-card example (pick 6, 3 numbers common across 4 cards):

   | Cards | Total variance | Var/card | Total SD | SD/card |
   |-------|----------------|----------|----------|---------|
   | 1     | 305.33         | 305.33   | 17.47    | 17.47   |
   | 2     | 623.80         | 311.90   | 24.98    | 17.66   |
   | 3     | 955.39         | 318.46   | 30.91    | 17.85   |
   | 4     | 1,300.12       | 325.03   | 36.06    | 18.03   |

   Covariance formula for n correlated cards: `Total variance = n*Var(x) + n*(n-1)*Cov(x,y)`.
   Sharing numbers across cards increases variance (positive covariance).
   Worked example: 10,000 games of 4-card keno at $1/card → expected loss $3,696.35,
   SD $3,605.72, 95% CI −$10,763.44 to +$3,370.73
   (total variance = 40,000 × 325.0308343 ≈ $13,001,233).

## Methodology notes

- All keno returns are exact combinatorial calculations: for each pick count the
  Wizard tabulates combinations, probability, and return contribution for every catch
  count and sums them. The underlying distribution is hypergeometric — for an
  80-number/20-draw game, P(catch c of p picks) = C(p,c)·C(80−p,20−c)/C(80,20); for
  the 40-ball game, C(p,c)·C(40−p,10−c)/C(40,10). (Formula paraphrased from his
  combinations-based tables; the appendix presents tables rather than the formula
  inline.)
- Variance per card is computed from the pay table's squared deviations; multi-card
  play adds pairwise covariance terms, which depend on how many numbers the cards
  share.
- Survey pages (Las Vegas / Laughlin / video keno) report empirically collected casino
  pay tables and their computed returns, not simulation.
- The Wizard also offers keno calculators for arbitrary pay tables
  (https://wizardofodds.com/games/keno/calculator/).

## Source URLs

- https://wizardofodds.com/games/keno/ — main keno page (rules, surveys)
- https://wizardofodds.com/games/keno/40-ball/ — 40-ball keno (closest to Stake's format)
- https://wizardofodds.com/games/keno/spot-keno/ — per-pick pay table analyses
- https://wizardofodds.com/games/keno/appendix/3/ — full odds tables, picks 1–15
- https://wizardofodds.com/games/keno/multi-card-variance/ — variance / SD / covariance
- https://wizardofodds.com/gambling/house-edge/ — keno HE 25–29%, SD 1.30–46.04
