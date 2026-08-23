# Wizard of Odds — Plinko

**Source:** https://wizardofodds.com/games/plinko/
**Captured:** 2026-08-23

## Coverage note

The Wizard of Odds has a dedicated Plinko analysis page. It does **not** analyze
Stake's Plinko by name; it analyzes three implementations: **CryptoGames Casino**,
**BGAMING**, and **BetFury Casino**. The BGAMING analysis (selectable 8–16 rows,
low/medium/high risk, RTP ~99%) is structurally identical to Stake Originals
Plinko — e.g. the BGAMING 16-row medium-risk pay table
(110, 41, 10, 5, 3, 1.5, 1, 0.5, 0.3, mirrored) is the same one Stake uses — so
treat the BGAMING section as the closest authoritative equivalent for Stake.

## Game mechanics (per the Wizard)

A ball drops down a triangular Galton Board of pegs. "At each row, the ball will
hit a peg and may either go left or right, each with a 50% chance." With 16 rows
there are 2^16 = 65,536 equally likely paths mapping to 17 landing positions —
i.e. position k has probability C(16,k)/65,536 (binomial). The Wizard computes
return as sum over positions of probability × multiplier; house edge = 1 − return.

## CryptoGames Casino (16 rows, 17 positions, 4 pay tables)

| Pay table | RTP    | House edge | Standard deviation |
|-----------|--------|------------|--------------------|
| Green     | 98.37% | 1.63%      | 0.562711           |
| Red       | 98.16% | 1.84%      | 0.517632           |
| Blue      | 98.48% | 1.52%      | 0.464829           |
| Yellow    | 98.09% | 1.91%      | 3.678698           |

Standard deviations are per unit bet, per drop. Yellow (top multiplier 650x) is
by far the most volatile.

Pay tables (positions 0–16, symmetric):

- Green:  10, 8, 6, 3, 2, 1.3, 1, 0.8, 0.5, 0.8, 1, 1.3, 2, 3, 6, 8, 10
- Red:    20, 7, 5, 3, 2, 1.1, 1, 0.6, 1, 0.6, 1, 1.1, 2, 3, 5, 7, 20
- Blue:   50, 8, 3, 2, 1.4, 1.2, 1.1, 1, 0.4, 1, 1.1, 1.2, 1.4, 2, 3, 8, 50
- Yellow: 650, 30, 7, 3, 1.5, 1.2, 1, 0.7, 0.7, 0.7, 1, 1.2, 1.5, 3, 7, 30, 650

Fairness: CryptoGames is provably fair (SHA512 hashing of server + client seeds).

## BGAMING (Stake-equivalent: 8–16 rows × low/medium/high risk)

RTP by rows and risk (headline: everything clusters tightly around 99%):

| Rows | Low    | Medium | High   |
|------|--------|--------|--------|
| 8    | 98.91% | 98.91% | 99.06% |
| 9    | 99.14% | 99.14% | 99.06% |
| 10   | 98.91% | 98.91% | 99.06% |
| 11   | 99.02% | 99.02% | 99.16% |
| 12   | 98.99% | 98.99% | 99.12% |
| 13   | 98.99% | 98.99% | 99.09% |
| 14   | 98.99% | 98.99% | 98.98% |
| 15   | 99.00% | 99.00% | 99.03% |
| 16   | 98.99% | 98.99% | 98.98% |

Range across all 27 configurations: 98.91%–99.16% RTP (house edge 0.84%–1.09%).
The Wizard notes returns are approximately equal across risk levels; risk changes
volatility, not expected return.

Example pay tables:
- 8 rows, low risk: 5.6, 2.1, 1.1, 1, 0.5, 1, 1.1, 2.1, 5.6
- 16 rows, medium risk: 110, 41, 10, 5, 3, 1.5, 1, 0.5, 0.3, 0.5, 1, 1.5, 3, 5, 10, 41, 110

**Standard deviation:** the Wizard does NOT publish SD figures for the BGAMING
configurations — only per-position combinations/probability/return tables and
the RTP summary. (SDs are published only for the CryptoGames variant, above.)

## BetFury Casino (16 rows, 3 pay tables)

| Pay table | RTP    | House edge |
|-----------|--------|------------|
| Blue      | 97.88% | 2.12%      |
| Green     | 97.88% | 2.12%      |
| Red       | 98.98% | 1.02%      |

Pay tables (17 positions):
- Blue:  16, 5, 2, 1.3, 1.2, 0.2, 1.1, 1.1, 1, 1.1, 1.1, 0.2, 1.2, 1.3, 2, 5, 16
- Green: 110, 41, 10, 5, 2.8, 1.5, 1, 0.5, 0.3, 0.5, 1, 1.5, 2.8, 5, 10, 41, 110
- Red:   1000, 130, 26, 9, 4, 2, 0.2, 0.2, 0.2, 0.2, 0.2, 2, 4, 9, 26, 130, 1000

No standard deviations published for BetFury. Top multiplier on the page: 1000x
(BetFury Red).

## Methodology notes

- Outcome model: pure binomial — each peg is an independent 50/50 left/right;
  16 rows → random number 0–65,535 mapped to a bucket by path count.
- Return = Σ (binomial probability × multiplier); the Wizard shows per-position
  tables (combinations, probability, return contribution) for each configuration.
- Standard deviations (where given) are per-drop, per unit wagered, derived from
  the same discrete distribution.
- No separate mathematical appendix; all math is on the main page.

## Source URLs

- Main analysis: https://wizardofodds.com/games/plinko/
- Stake.us casino review (mentions Plinko, no math): https://wizardofodds.com/online-casinos/reviews/stakeus-casino/
