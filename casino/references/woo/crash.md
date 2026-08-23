# Wizard of Odds — Crash (key: crash)

Captured: 2026-08-23

## Coverage status

- The Wizard of Odds HAS a page analyzing crash games: https://wizardofodds.com/games/crash/ ("Crash Games - What Are They?").
- There is NO Stake-specific Crash analysis page. `https://wizardofodds.com/games/crash-stake/` returns HTTP 404 (checked 2026-08-23), unlike his Stake-specific pages for dice (`/games/dice-stake/`), mines, plinko, etc.
- His former JetX page (`https://wizardofodds.com/games/jetx/`) now says only: "My content on JetX has been moved to my page on Crash" — i.e. the general crash page is the canonical analysis.
- The general crash page is his closest authoritative equivalent for Stake's Crash. Note that his numbers are based on SmartSoft Gaming's JetX (97% return); Stake advertises a different RTP for its own Crash original (99%, 1% house edge, per Stake's published game info — NOT a Wizard of Odds figure). The Wizard's Stake Casino review mentions Crash as a provably-fair Stake Original but publishes no independent numeric analysis of it.

## House edge / RTP (as published by the Wizard)

Game analyzed: JetX by SmartSoft Gaming (also notes DraftKings' "DK Rocket" variant, with no separate RTP given).

- Return (RTP): **97%** — "The return of this game is reported to be 97%."
- House edge: **3%**.
- Win probability for a winning goal of `w` times the bet: **P(win) = 0.97 / w**.
  - Example given: goal 3x → P(win) = 0.97/3 ≈ 32.33%.
- Because P(win) × payout = (0.97/w) × w = 0.97 for every target, the 97% return holds regardless of the cash-out multiplier chosen. Crash has a flat house edge across all configurations (unlike keno/mines/plinko where edge varies by setting).
- Selectable winning goal range: **1.01x to 1000x** the bet.

## Standard deviation / variance

- **The Wizard publishes no standard deviation or variance figures for crash** (confirmed on the /games/crash/ page; no return table, no SD column).
- (Our derivation, NOT from the Wizard, for reference: with auto-cashout at w and p = 0.97/w, per-unit-bet variance = p·w² − (p·w)² = 0.97·w − 0.9409, i.e. SD ≈ sqrt(0.97·w − 0.9409). SD grows roughly with sqrt(w): ~1.03 at w=2, ~3.0 at w=10, ~9.8 at w=100.)

## Methodology / mechanics notes (Wizard's description of JetX)

- Betting window lasts "about 5.6 seconds" before the ship launches.
- The spaceship starts at altitude (multiplier) 1. "About every 1/7 of a second one of two things will happen: With about a 99% chance, the multiplier will increase by about 1%. With about a 1% chance, the spaceship will explode." (~400 calculations per minute.)
- How the flat 97% is achieved (per the operator's math the Wizard relays): "there is a 3% chance the spaceship never gets off the ground and crashes on the runway"; after takeoff, each tick has 99% chance the multiplier grows by 1/99 of its previous value and 1% chance of explosion. The +1/99 growth exactly offsets the 1% survival tax, so expected value is preserved tick-to-tick and only the 3% instant-crash creates the house edge.
- Player may place one or two simultaneous bets with different multiplier targets; the "pilot" ejects automatically at the target, paying bet × target.
- Worked example on the page: two simultaneous bets (5 GEL @ 8x and 2 GEL @ 3x); both auto-cashed before the ship exploded at 11.52x.
- "Rocket Man!" anecdote: while testing, the Wizard observed a game reach a multiplier of **12540.26x**.
- No provably-fair verification walkthrough is given on this page (contrast with his Stake dice/mines pages); Stake's Crash provable fairness is only mentioned in passing in his Stake Casino review.

## Source URLs

- https://wizardofodds.com/games/crash/ — main analysis (JetX-based), last updated Aug 2026 era; author Michael Shackleford.
- https://wizardofodds.com/games/jetx/ — redirect stub pointing to the crash page.
- https://wizardofodds.com/games/crash-stake/ — 404, no Stake-specific page exists.
- https://wizardofodds.com/software/spribe/ — Spribe (Aviator) casino/software page, crash-adjacent.
- https://wizardofodds.com/online-casinos/reviews/stake-casino/ — Stake review; mentions Crash among provably-fair Stake Originals, no numeric analysis.
- https://wizardofodds.com/article/largest-bitcoin-online-casino/ — Stake history article; crash-game lineage (MoneyPot 2014 by Eric Springer → BustaBit; Stake et al. launched Crash 2018–2020).
