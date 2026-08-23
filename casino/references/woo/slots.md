# Wizard of Odds — Slots (representative published-RTP model)

Captured: 2026-08-23. Key: `slots`.

## Stake-specific page?

**No.** The Wizard of Odds has Stake-Originals-specific pages for Mines, Plinko, Crash,
Dice, Limbo, Keno, Wheel, and Hilo, but **no Stake-specific slots analysis** — slots on
Stake are third-party studio games (Pragmatic Play, Hacksaw, etc.), not a Stake Original,
and each title has its own studio-published RTP. The Wizard's Stake casino reviews
mention the slots lobby but publish no math for it.

The closest authoritative equivalents are the Wizard's **slot machine deconstructions
and appendices**, where he publishes full par-sheet math (RTP and standard deviation)
for specific representative machines. Those are captured below. His **Atkins Diet
deconstruction** is the canonical fully-published model (he publishes the complete par
sheet); **Cleopatra** (IGT) is his most representative mainstream video slot, with
per-configuration standard deviations.

## Headline figures

| Model | RTP | House edge | Standard deviation | Source |
|---|---|---|---|---|
| Atkins Diet (full par sheet, 5-reel video slot) | **97.046%** | 2.954% | not published on that page | /games/slots/atkins-diet/ |
| Cleopatra (IGT video slot, 20 lines) | **95.025%** | 4.975% | **5.18** (20 lines) to **13.45** (1 line), relative SD | /games/slots/cleopatra/ |
| Red White & Blue (IGT 3-reel) | 86.58% (1–2 coins) / **87.47%** (3 coins) | 12.53% (3 coins) | **9.03** (1–2 coins), **10.80** (3 coins) | /games/slots/appendix/6/ |
| Double Strike (empirical, 3,976 recorded spins) | 96.62% (1 coin) / **96.73%** (2 coins) | 3.27% | **8.54** (max coins) | /games/slots/appendix/1/ |
| Generic slot machines (house-edge master table) | 85%–98% | **2%–15%** | **8.74** | /gambling/house-edge/ |
| Hypothetical 3-reel teaching example | 94.545% | 5.455% | none given | /games/slots/appendix/2/ |

## Atkins Diet — the Wizard's fully-published par-sheet model

- Total return **97.046%** ("for every dollar the player bets, he can expect to get
  back 97¢").
- Return breakdown: line pays **63.460%**, scatter pay **6.976%**, bonus (free-spin)
  feature **26.610%**.
- 5 reels × 32 positions each → **32^5 = 33,554,432** equally likely outcomes.
- Hit frequency **5.45%** per line.
- Bonus: 3+ scatters (probability **0.011185**) trigger 10 free spins with all wins
  tripled; retriggers give an expected **11.259335** spins per bonus and expected bonus
  win of **23.791632** × bet.
- Method: exact enumeration — "a program with five nested loops that tallied the total
  for each win for each possible combination" of all 33.55M outcomes.

## Cleopatra (IGT) — standard deviation per configuration

- Total return **95.025%**; breakdown: line pays 52.047%, scatter pays 17.508%,
  free spins 25.470%.
- Hit frequency: 11.36% (1 line) to 35.88% (20 lines).
- **Relative standard deviation: 13.45 betting 1 line down to 5.18 betting all
  20 lines** — the Wizard distinguishes *total* SD (per credit, betting one credit per
  line) from *relative* SD (total SD ÷ total amount bet); betting more lines lowers
  relative volatility.
- SD obtained from **20 simulations of 100 million spins each**; return obtained by
  exact combinatorial analysis over 30^4 × 41 ≈ 33.21M outcomes, with reel strips
  documented from the live game.

## Land-casino payback context (actual returns by denomination)

Clark County, NV average slot win (house edge), 2012, from the Wizard's main slots page:

| Denomination | House edge | Denomination | House edge |
|---|---|---|---|
| $0.01 | 10.77% | $5.00 | 5.51% |
| $0.05 | 5.96% | $25.00 | 3.97% |
| $0.25 | 5.74% | $100.00 | 4.73% |
| $1.00 | 5.64% | Megabucks | 12.89% |
| Multi-denom | 5.32% | **All slots** | **6.58%** |

- "The house edge on penny video slots is usually set from 6% to 15%." Higher
  denominations generally return more.
- Nevada regulation floor: theoretical return ≥ 75%; even tight airport machines pay
  ~85%+.

## Standard deviation — what the Wizard publishes

- His house-edge master table lists slot machines at house edge **2%–15%** with
  **SD 8.74**, with the explicit caveat: "Slot machine standard deviation based on just
  one machine. While this can vary, the standard deviation on slot machines are very
  high" — the highest SD of any game class on his table (vs ~1.15 blackjack, ~4.4
  9/6 Jacks video poker).
- Per-machine published SDs: Red White & Blue **9.03 / 10.80** (1–2 / 3 coins),
  Double Strike **8.54**, Cleopatra **5.18–13.45** depending on lines bet.
- He defines SD as "a measure of how volatile your bankroll will be playing a given
  game"; SD of the mean over n spins = SD per bet ÷ √n; ~68.26% of session results fall
  within one SD of expectation.

## Methodology notes

- **RNG + weighted reel mapping**: "The outcome of every bet is ultimately determined
  by random numbers. The game will choose one random number for each reel, map that
  number onto a position on the reel, stop the reel in the appointed place, and score
  whatever the outcome is. ... The outcome is predestined the moment you press the
  button; the rest is just for show." Symbol counts per reel are chosen to hit a target
  return; on stepper slots the physical reel positions are weighted (unequal
  probabilities), on video slots each stop is typically equally likely.
- **Return calculation** (appendix 2): enumerate all reel combinations (e.g. 64^3 =
  262,144 for a 3-reel with 64 virtual stops), compute each pay combination's
  probability, and take the dot product with the pay table → example return 94.545%.
- **Sources of par data**: manufacturer par sheets where obtainable (Atkins Diet,
  Vamos a Las Vegas, Australian Reels, 21 Bell, Fruit Machine), machine-posted
  weightings (Red White & Blue, Netherlands), empirical reel reconstruction from
  recorded play (Double Strike, 3,976 spins), and reel-strip documentation plus
  large-scale simulation (Cleopatra and the rest of the "Deconstructing" series).
- Unlike his table-game pages, slot RTP is **machine/title-specific and usually hidden
  from the player**; his representative models exist to show how any given published
  RTP decomposes and how volatile the games are.
- Relevance to online "slots" lobbies (incl. Stake): online studios publish per-title
  RTP (commonly ~94%–97%, matching the Atkins Diet / Cleopatra band); the Wizard's
  models are the authoritative public examples of the underlying math.

## Source URLs

- https://wizardofodds.com/games/slots/atkins-diet/ — Deconstructing the Atkins Diet slot (full par sheet, RTP 97.046%)
- https://wizardofodds.com/games/slots/cleopatra/ — Deconstructing Cleopatra (RTP 95.025%, SD 5.18–13.45 by lines)
- https://wizardofodds.com/games/slot-machines/ — main slots page (how they work, Nevada paybacks, methodology)
- https://wizardofodds.com/games/slots/appendix/1/ — Appendix 1: Double Strike empirical analysis (return 96.73%, SD 8.54)
- https://wizardofodds.com/games/slots/appendix/2/ — Appendix 2: how to calculate a slot's return (94.545% example)
- https://wizardofodds.com/games/slots/appendix/6/ — Appendix 6: Red White & Blue analysis (SD 9.03 / 10.80)
- https://wizardofodds.com/gambling/house-edge/ — house-edge master table (slots 2%–15%, SD 8.74)
- https://wizardofodds.com/online-casinos/reviews/stake-casino/ — Stake review (no slots math; confirms no Stake-specific slots analysis)
