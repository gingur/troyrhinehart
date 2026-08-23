# Stake.com — Crash (Stake Original): Published Provably-Fair Math & Rules

Captured 2026-08-23 from Stake's own published material. stake.com direct access was
geo-blocked (HTTP 403), so content was captured from Web Archive snapshots of stake.com
pages and from Stake's official BitcoinTalk seeding-event thread, which is the document
stake.com/provably-fair/game-events itself links to as the authoritative math for Crash.

## Sources (Stake's own published material)

| Content | URL | Via |
|---|---|---|
| Provably Fair — Game Events (Crash section links to seeding thread) | https://stake.com/provably-fair/game-events | https://web.archive.org/web/20240916020208/https://stake.com/provably-fair/game-events |
| Crash Seeding Event (exact math, posted by Stake admin "Stunna", 2019-07-08) | https://bitcointalk.org/index.php?topic=5162888.0 | fetched live |
| Crash game page (rules, house edge, max multiplier) | https://stake.com/casino/games/crash | https://web.archive.org/web/20250108002647/https://stake.com/casino/games/crash |

## How Crash differs from other Stake Originals (per Stake)

Unlike Stake's seed-pair games (Dice, Limbo, Plinko, etc., which use server seed +
client seed + nonce), Crash is a **multiplayer** game: every round is the same for all
active players. It therefore uses a **salted hash-chain** provable-fairness model.
Stake's Provably Fair "Game Events" page says, in full, for Crash:

> **Crash**
> See the [BitcoinTalk seeding thread](https://bitcointalk.org/index.php?topic=5162888.0)
> to learn about how we utilise the salt hash based provable fairness modal for this
> particular game.

## Event-generation math (from Stake's seeding event thread)

Posted by **Stunna** (Stake admin) on **July 08, 2019, 06:51:19 AM**, thread
"Stake.com Crash Seeding Event" (bitcointalk topic 5162888):

1. **Hash chain:** "To prove our fairness we have generated a chain of **10,000,000
   SHA256 hashes** where each hash is the hash of the hexadecimal representation of the
   previous hash."

   - **Terminating (published) hash of the chain:**
     `78a9757d3be42b74a3f70239078ad9317125fe9ee630d5bdada46de963e56752`
   - Games are played by popping hashes off the chain in reverse order; any game hash
     can be verified as belonging to the chain by repeatedly SHA256-hashing it until
     the published terminating hash is reached.

2. **Public salt (client seed):** "a future bitcoin block as a client seed so players
   can be certain that we did not pick one in the house's favor."

   - **Chosen block: Bitcoin block 584,500** (mined July 21, 2019, i.e. after the
     chain's terminating hash was published)
   - **Block hash (the salt used for every game):**
     `0000000000000000001b34dc6a1e86083f95500b096231436e9b25cbdd0075c4`

3. **Crash-point formula** (verbatim code from the thread):

```javascript
const gameHash = hashChain.pop()
const hmac = createHmac('sha256', gameHash);
hmac.update(blockHash);
const hex = hmac.digest('hex').substr(0, 8);
const int = parseInt(hex, 16);
const crashpoint = Math.max(1, (2 ** 32 / (int + 1)) * (1 - 0.01))
```

Stake's accompanying note: "0.01 will result in **1% house edge** with a lowest
crashpoint of 1".

In words: for each round, the next hash is popped off the pre-committed chain and used
as the HMAC-SHA256 **key**; the Bitcoin block 584,500 hash is the HMAC **message**.
The first 8 hex characters (32 bits) of the HMAC digest are parsed as an unsigned
integer `int` ∈ [0, 2³²−1], and the round's crash point is
`max(1, (2³² / (int + 1)) × 0.99)`.

## Payout table

Crash has **no discrete payout table**. The payout is continuous and player-chosen:

| Outcome | Payout |
|---|---|
| Player cashes out at multiplier `m` (manually or via "Cashout At") before the round crashes — i.e. `m` ≤ crash point | `bet × m` |
| Round crashes below the player's cashout value | 0 (bet lost) |

| Published game parameter | Value |
|---|---|
| House edge (shown on game page: "Edge:") | **1.00%** |
| Minimum crash point | **1** (formula consolidates all lower values to 1) |
| Maximum cashout value | **1,000,000×** ("a maximum cashout value of 1,000,000x" — game page) |
| Round cadence | New betting window every 5 seconds after a round ends |
| Mode | Multiplayer — every round identical for all active players; live leaderboard |

## Rules (from stake.com/casino/games/crash, verbatim key passages)

> "Crash is a simple game of chance where the player picks the cashout amount for a
> betting round as an icon representing a rocket flies through a grid. The cashout
> amount climbs until the rocket 'crashes' and as long as the player's cashout amount
> is lower than the crash value, the player can win a payout."

> "every 5 seconds after a round of Crash is played, players can make their bets on
> what their cashout value will be for the upcoming round. This is the amount that
> that player will cashout before the rocket 'crashes'. If the player hits the cashout
> value during a round, they receive a payout based on that cashout amount. However,
> if the rocket crashes at a value lower than their cashout bet, the player loses the
> bet for that round."

> "it is a real-time multiplayer game … Every round is the same for all active players
> playing Crash at that specific time - with a live leader board showcasing each
> player's bets for that round."

> "With the live community playing this game of chance, provably fair gameplay and a
> maximum cashout value of 1,000,000x …"

Betting options (game page): Manual Bet (bet amount + Cashout At; Profit on Win shown)
and Auto Bet (number of bets, increase/reset on win/loss, stop on profit/loss).
Hotkeys: `s` double bet, `a` halve bet, `d` zero bet, `spacebar` bet, `q` cancel/cashout.

## Derived properties (ours, implied directly by Stake's formula — not quoted text)

- `int` is uniform on [0, 2³²−1], so P(crash point ≥ m) = 0.99 / m (for 1 < m ≤ raw max),
  giving expected return `m × P(win at m) = 0.99` at any target — the stated 1% edge.
- Instant bust (crash point exactly 1.00) occurs when `(2³²/(int+1)) × 0.99 ≤ 1`,
  i.e. with probability ≈ 1%.
- RTP = 99% for any cashout target (house edge 1%, as published).
