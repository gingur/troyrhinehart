# SpinQuest Playbook — pre-play briefing

Every number here comes from engines that reproduce Stake's published provably-fair math
payout-for-payout, validated within 3 SE of Wizard of Odds figures over 10M+ rounds
(see `STATUS.md` and `gauntlet/`). Full config-level table: `gauntlet/ranking_snapshot.csv`
(412 configs; regenerate with `spinquest_sim.selector.ranking()`).

**The one honest sentence:** every game has negative EV; expected loss = house edge x total
wagered, and grows with every round. Sizing and stops shape the distribution, never the sign.

## Game ranking (best configuration per game)

| # | Game | Best configuration | RTP | Cost per $100 bet | SD/unit |
|---|------|--------------------|-----|-------------------|---------|
| 1 | Video poker | 9/6 Jacks or Better, optimal holds | 99.54% | $0.46 | 4.42 |
| 2 | Blackjack | Basic strategy (S17, DAS, resplit 4, 3:2) | 99.49% | $0.51 | 1.15 |
| 3 | Plinko | High/11 rows (Medium/9 for low variance) | 99.16% | $0.84 | 4.13 |
| 4 | Keno | Low risk, 9 picks | 99.07% | $0.93 | 1.16 |
| 5 | Wheel | 10 segments, low | 99.00% | $1.00 | 0.50 |
| 5 | Mines | 1 mine, 1 pick | 99.00% | $1.00 | 0.20 |
| 5 | Crash | Auto-cashout 1.2x | 99.00% | $1.00 | 0.46 |
| 8 | Baccarat | Banker, always | 98.94% | $1.06 | 0.93 |
| 9 | Roulette | Single-zero, any bet | 97.30% | $2.70 | 1.00-5.84 |
| 10 | Slots | Published par sheet (Atkins) | 97.05% | $2.95 | 4.45 |
| X | Baccarat tie | Never | 85.64% | $14.36 | 2.64 |

Video poker and blackjack hold their rank only with correct play.

## Survival-optimal sizing (exact absorption math, sim-validated)

- **Goal: make it last** -> bet the table minimum. Keep bankroll/bet >= 200 units
  (low-variance picks) or >= 500 units (video poker, plinko-high, slots).
- **Goal: hit a target** -> bold play: few, big bets (Dubins-Savage). $200 -> $300 on
  roulette red: one $100 bet wins 64.9%; $5 grind 31.2%; $1 grind 0.45%.

## Stops (decided before the first bet)

- Stop-win where attainable (e.g. +$105 is reached in ~18% of 500-round $5 sessions on a
  $200 bankroll) — then actually stop.
- Stop-loss caps the worst tail; when playing bold toward a target, the stake IS the
  stop-loss. Never reload mid-session; never escalate after losses (martingale keeps the
  EV and worsens the worst case).

## Session budget

Expected cost = edge x bet x rounds. 200 x $1 rounds: blackjack ~$1.02, roulette ~$5.41,
baccarat tie ~$28.72.
