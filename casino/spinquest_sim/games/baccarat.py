"""Stake-style Baccarat (punto banco) — Banker / Player / Tie.

Rules & payouts (references/stake/baccarat.md — Stake's published pages,
verbatim):

* Card values: 10/J/Q/K = 0, Ace = 1, 2-9 = pip value; hand total mod 10.
* Player hand: natural 8/9 stands both hands; stands on 6-7; draws on 0-5.
* Banker hand (after a player third card), by banker two-card total:
  0-2 always draws; 3 draws unless the player's third card is 8; 4 draws on
  player third card 2-7; 5 draws on 4-7; 6 draws on 6-7; 7 stands.
  When the player STANDS (6-7, no natural), the banker draws on 0-5 and
  stands on 6-7 (standard punto banco; Stake's rows 3-6 are phrased for the
  player-third-card case only).
* Payouts (total returned per 1 unit): Player 1:1 -> 2.00, Banker 0.95:1
  -> 1.95 (5% commission), Tie 8:1 -> 9.00.  Player/Banker bets PUSH when
  the hands tie.

Shoe models:

* ``decks=8`` (default) — standard 8-deck punto banco: each round deals up
  to 6 cards WITHOUT replacement from a freshly shuffled 416-card shoe.
  This is the configuration the Wizard of Odds analyzes
  (references/woo/baccarat.md): house edges 1.06% Banker / 1.24% Player /
  14.36% Tie, SDs 0.93 / 0.95 / 2.64, win probabilities 45.86 / 44.62 /
  9.52%.
* ``decks=None`` — Stake's published on-chain mechanism: "we utilise an
  unlimited amount of decks", each card an INDEPENDENT draw
  ``floor(float * 52)`` with replacement (references/stake/baccarat.md §3).
  Matches WoO's "Infinite" row: 1.064% / 1.228% / 14.117%.

Provably-fair mechanics: one round = one nonce = 6 game events = 24 bytes =
ONE HMAC-SHA256 digest (cursor stays 0; Stake lists Baccarat among "games
with only 1 incremental number").  Stake does not publish the assignment
order of the 6 events to seats; this module uses physical shoe order —
event 0 Player card 1, event 1 Banker card 1, event 2 Player card 2,
event 3 Banker card 2, event 4 the FIRST third card needed (player's if the
player draws, else banker's), event 5 the second third card (banker's when
both draw).  Unused events are still generated, exactly as published ("we
only ever need 6 game events generated").  For ``decks=8`` the 6 floats
drive a partial Fisher-Yates draw from the 416-card pool (pool index mod 52
= the published CARDS identity); for ``decks=None`` each float maps
independently via ``floor(float * 52)``.  Both the scalar path and the
vectorized :class:`~spinquest_sim.rng.BulkRng` path are the critic-verified
RNG core — this module adds no randomness of its own, and every simulated
round is bit-for-bit reproducible from ``(server_seed, client_seed,
nonce)``.

Analytics are EXACT: full enumeration of every value sequence with integer
falling-factorial weights (finite shoe) or fixed weights (infinite deck),
reduced to :class:`fractions.Fraction` probabilities — the same
combinatorial method the Wizard of Odds names ("exact combinatorial
analysis ... no simulation needed").

Pair side bets (rank-level analytics): the Wizard's house-edge table
carries a fifth column, "Pair bets (11:1)" — a side bet that a hand's
FIRST TWO cards share a RANK (references/woo/baccarat.md: 10.36% at 8
decks / 11.25% at 6 / 29.41% at 1 / 7.69% infinite; 8-deck RTP 89.64%).
Rank identity lives one level below baccarat values (10/J/Q/K are four
distinct ranks that all count 0), so this module exposes it explicitly:
``CARD_RANKS`` (published card index // 4), exact
:func:`pair_probability` = (4D-1)/(52D-1) for a D-deck shoe (1/13
infinite), :func:`pair_house_edge` at the published 11:1 odds, and a
rank-granular empirical path (:func:`deal_cards` / :func:`simulate_pairs`)
that verifies the dealt CARD INDICES — not just their baccarat values —
against those exact rank-level figures.
"""

from __future__ import annotations

import math
import time
from fractions import Fraction
from functools import lru_cache
from typing import Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from spinquest_sim import rng as sq_rng
from spinquest_sim.rng import BulkRng

__all__ = [
    "BET_TYPES",
    "PAIR_BET_TYPES",
    "PAYOUT_ODDS",
    "MULTIPLIERS",
    "PAIR_PAYOUT_ODDS",
    "PAIR_MULTIPLIER",
    "EVENTS_PER_ROUND",
    "CARD_VALUES",
    "CARD_RANKS",
    "BANKER_DRAW_TABLE",
    "card_value",
    "card_rank",
    "banker_draws",
    "settle_values",
    "outcome_probabilities",
    "pair_probability",
    "pair_rtp",
    "pair_house_edge",
    "pair_std_per_unit",
    "pair_summary",
    "total_grid",
    "full_payout_table",
    "deal_cards",
    "deal_rounds",
    "simulate_all_bets",
    "simulate_pairs",
    "Baccarat",
]

EVENTS_PER_ROUND = sq_rng.EVENT_COUNTS["baccarat"]      # 6, published
assert EVENTS_PER_ROUND == 6

BET_TYPES: Tuple[str, ...] = ("player", "banker", "tie")

# Published winnings odds (references/stake/baccarat.md §5) — exact.
PAYOUT_ODDS: Dict[str, Fraction] = {
    "player": Fraction(1),            # 1:1
    "banker": Fraction(19, 20),       # 0.95:1 (even money less 5% commission)
    "tie": Fraction(8),               # 8:1
}
# Total returned per 1 unit staked on a WIN (stake + winnings).
MULTIPLIERS: Dict[str, Fraction] = {b: o + 1 for b, o in PAYOUT_ODDS.items()}

# Pair side bets (references/woo/baccarat.md, house-edge table column
# "Pair bets (11:1)"): the FIRST TWO cards of a hand share a rank.  Player
# pair rides on the player's initial two cards, banker pair on the
# banker's; the two bets are exactly symmetric by exchangeability.
PAIR_BET_TYPES: Tuple[str, ...] = ("player_pair", "banker_pair")
PAIR_PAYOUT_ODDS: Fraction = Fraction(11)                 # published 11:1
PAIR_MULTIPLIER: Fraction = PAIR_PAYOUT_ODDS + 1          # 12.00 returned

_DECK = 52
_RANKS = 13
_VALUES = 10  # baccarat card values 0..9

# Baccarat value of each published card index 0..51 (rank = index // 4,
# ranks 2..9 -> pip, 10/J/Q/K -> 0, A -> 1).
CARD_VALUES = np.array(
    [(r + 2 if r <= 7 else (0 if r <= 11 else 1)) for r in range(13)],
    dtype=np.int64,
)[np.arange(_DECK) // 4]

# Rank (0..12 = ranks 2..A) of each published card index — the published
# CARDS layout groups the 4 suits of each rank contiguously, so rank is
# exactly index // 4.  This is FINER than baccarat value: ranks 8..11
# (10/J/Q/K) all collapse to value 0, but stay distinct here — pair bets
# and the rank-level shoe checks live at this granularity.
CARD_RANKS = np.arange(_DECK, dtype=np.int64) // 4
CARD_RANKS.setflags(write=False)
assert all(int(np.sum(CARD_RANKS == r)) == 4 for r in range(_RANKS))

# Cards of each value in ONE deck: value 0 <- {10, J, Q, K} (16 cards),
# values 1..9 <- 4 cards each.
_VALUE_COUNTS_PER_DECK = (16, 4, 4, 4, 4, 4, 4, 4, 4, 4)

# Sanity: per-deck value composition derived from CARD_VALUES must match.
assert tuple(int(c) for c in np.bincount(CARD_VALUES, minlength=_VALUES)) == _VALUE_COUNTS_PER_DECK

# BANKER_DRAW_TABLE[banker_two_card_total][player_third_card_value] -> bool,
# the published third-card table (only consulted when the player drew):
#   0-2: draws always; 3: unless third card is 8; 4: on 2-7; 5: on 4-7;
#   6: on 6-7; 7: stands.  Rows 8-9 are unreachable (naturals stand first).
BANKER_DRAW_TABLE = np.zeros((_VALUES, _VALUES), dtype=bool)
BANKER_DRAW_TABLE[0:3, :] = True
BANKER_DRAW_TABLE[3, :] = True
BANKER_DRAW_TABLE[3, 8] = False
BANKER_DRAW_TABLE[4, 2:8] = True
BANKER_DRAW_TABLE[5, 4:8] = True
BANKER_DRAW_TABLE[6, 6:8] = True
BANKER_DRAW_TABLE.setflags(write=False)


def card_value(card_index: int) -> int:
    """Baccarat value (0..9) of a published card index 0..51."""
    if not 0 <= card_index < _DECK:
        raise ValueError(f"card index must be in 0..51, got {card_index}")
    return int(CARD_VALUES[card_index])


def card_rank(card_index: int) -> int:
    """Rank (0..12, ranks 2..A) of a published card index 0..51."""
    if not 0 <= card_index < _DECK:
        raise ValueError(f"card index must be in 0..51, got {card_index}")
    return card_index // 4


def banker_draws(banker_total: int, player_third_value: Optional[int]) -> bool:
    """Does the banker draw a third card?  ``player_third_value`` is None
    when the player stood (banker then draws on 0-5), else the player's
    third-card value 0..9 (published table).  Naturals must be handled by
    the caller — this is the post-natural decision only."""
    if not 0 <= banker_total <= 7:
        raise ValueError("banker total must be 0..7 here (naturals stand)")
    if player_third_value is None:
        return banker_total <= 5
    if not 0 <= player_third_value <= 9:
        raise ValueError("player third-card value must be 0..9")
    return bool(BANKER_DRAW_TABLE[banker_total, player_third_value])


def settle_values(values: Sequence[int]) -> Dict[str, object]:
    """Resolve one round from the 6 event VALUES in dealt order
    (P1, B1, P2, B2, first-third-card, second-third-card).

    Returns player/banker card-count and totals, the outcome
    ('player' / 'banker' / 'tie'), and how many of the 6 events were used.
    The scalar reference implementation — the vectorized simulator is
    tested element-for-element against this function.
    """
    if len(values) != EVENTS_PER_ROUND:
        raise ValueError(f"need exactly {EVENTS_PER_ROUND} event values")
    v = [int(x) for x in values]
    if any(not 0 <= x <= 9 for x in v):
        raise ValueError("card values must be in 0..9")
    player = [v[0], v[2]]
    banker = [v[1], v[3]]
    pt = (player[0] + player[1]) % 10
    bt = (banker[0] + banker[1]) % 10
    used = 4
    natural = pt >= 8 or bt >= 8
    if not natural:
        if pt <= 5:                                    # player draws
            p3 = v[used]
            player.append(p3)
            used += 1
            if banker_draws(bt, p3):
                banker.append(v[used])
                used += 1
        else:                                          # player stands on 6-7
            if banker_draws(bt, None):
                banker.append(v[used])
                used += 1
    pt = sum(player) % 10
    bt = sum(banker) % 10
    outcome = "tie" if pt == bt else ("player" if pt > bt else "banker")
    return {
        "player_values": player,
        "banker_values": banker,
        "player_total": pt,
        "banker_total": bt,
        "natural": natural,
        "outcome": outcome,
        "events_used": used,
    }


# ---------------------------------------------------------------------------
# (a) exact analytics — full enumeration, integer weights, Fractions
# ---------------------------------------------------------------------------

def _shoe_params(decks: Optional[int]) -> Tuple[Tuple[int, ...], Optional[int]]:
    """(per-value counts, total cards) — total is None for infinite decks."""
    if decks is None:
        return _VALUE_COUNTS_PER_DECK, None
    if not isinstance(decks, int) or isinstance(decks, bool) or decks < 1:
        raise ValueError("decks must be a positive int or None (infinite)")
    return tuple(c * decks for c in _VALUE_COUNTS_PER_DECK), _DECK * decks


@lru_cache(maxsize=None)
def _enumerate(decks: Optional[int]) -> Tuple[Tuple[Tuple[int, ...], ...], int]:
    """Exact enumeration of every deal.

    Returns ``(grid, denominator)`` where ``grid[pt][bt]`` is the integer
    weight of the final (player_total, banker_total) pair and
    ``denominator`` normalizes it: the falling factorial
    ``total * (total-1) * ... * (total-5)`` for a finite shoe (every
    sequence weight is padded with the remaining falling factors so all
    share one denominator), or ``52**6`` for the infinite deck.

    Drawing depletion follows dealt order; by exchangeability the joint
    law of the totals is order-independent, so this matches the simulator
    regardless of seat-assignment convention.
    """
    counts, total = _shoe_params(decks)
    finite = total is not None
    grid = [[0] * _VALUES for _ in range(_VALUES)]

    if finite:
        denom = 1
        for k in range(EVENTS_PER_ROUND):
            denom *= total - k

        def pad(weight: int, used: int) -> int:
            for k in range(used, EVENTS_PER_ROUND):
                weight *= total - k
            return weight
    else:
        denom = _DECK ** EVENTS_PER_ROUND

        def pad(weight: int, used: int) -> int:
            return weight * _DECK ** (EVENTS_PER_ROUND - used)

    def cnt(value: int, drawn: Sequence[int]) -> int:
        return counts[value] - drawn.count(value) if finite else counts[value]

    table = BANKER_DRAW_TABLE
    for p1 in range(_VALUES):
        w1 = cnt(p1, ())
        for b1 in range(_VALUES):
            w2 = w1 * cnt(b1, (p1,))
            for p2 in range(_VALUES):
                w3 = w2 * cnt(p2, (p1, b1))
                for b2 in range(_VALUES):
                    w4 = w3 * cnt(b2, (p1, b1, p2))
                    if w4 == 0:
                        continue
                    pt = (p1 + p2) % 10
                    bt = (b1 + b2) % 10
                    drawn4 = (p1, b1, p2, b2)
                    if pt >= 8 or bt >= 8:             # natural — both stand
                        grid[pt][bt] += pad(w4, 4)
                    elif pt >= 6:                      # player stands
                        if bt >= 6:                    # banker stands too
                            grid[pt][bt] += pad(w4, 4)
                        else:                          # banker draws on 0-5
                            for b3 in range(_VALUES):
                                w5 = w4 * cnt(b3, drawn4)
                                if w5:
                                    grid[pt][(bt + b3) % 10] += pad(w5, 5)
                    else:                              # player draws
                        for p3 in range(_VALUES):
                            w5 = w4 * cnt(p3, drawn4)
                            if w5 == 0:
                                continue
                            npt = (pt + p3) % 10
                            if table[bt, p3]:          # banker draws
                                drawn5 = drawn4 + (p3,)
                                for b3 in range(_VALUES):
                                    w6 = w5 * cnt(b3, drawn5)
                                    if w6:
                                        grid[npt][(bt + b3) % 10] += pad(w6, 6)
                            else:                      # banker stands
                                grid[npt][bt] += pad(w5, 5)
    assert sum(map(sum, grid)) == denom  # total probability is exactly 1
    return tuple(tuple(row) for row in grid), denom


def total_grid(decks: Optional[int] = 8) -> Tuple[np.ndarray, int]:
    """(10, 10) integer-weight grid of final (player_total, banker_total)
    pairs and its common denominator — WoO 'Appendix 1'-style exact data."""
    grid, denom = _enumerate(decks)
    return np.array(grid, dtype=object), denom


@lru_cache(maxsize=None)
def outcome_probabilities(decks: Optional[int] = 8) -> Dict[str, Fraction]:
    """Exact P(player win), P(banker win), P(tie) for the configured shoe."""
    grid, denom = _enumerate(decks)
    p = b = t = 0
    for pt in range(_VALUES):
        for bt in range(_VALUES):
            w = grid[pt][bt]
            if pt > bt:
                p += w
            elif bt > pt:
                b += w
            else:
                t += w
    return {
        "player": Fraction(p, denom),
        "banker": Fraction(b, denom),
        "tie": Fraction(t, denom),
    }


def pair_probability(decks: Optional[int] = 8) -> Fraction:
    """Exact P(a hand's first two cards share a rank) — a rank-level
    quantity (10/J/Q/K are distinct ranks despite all being value 0).

    Finite D-deck shoe: after any first card, 4D-1 of the remaining
    52D-1 cards match its rank -> (4D-1)/(52D-1); by exchangeability of
    the without-replacement draw this applies identically to the Player
    pair (dealt cards 1 & 3) and the Banker pair (cards 2 & 4).
    Infinite decks (Stake's published mechanism, independent
    ``floor(float * 52)`` draws): 4/52 = 1/13.
    """
    _shoe_params(decks)  # validates
    if decks is None:
        return Fraction(1, 13)
    return Fraction(4 * decks - 1, 52 * decks - 1)


def pair_rtp(decks: Optional[int] = 8) -> Fraction:
    """Exact RTP of a pair side bet at the published 11:1 odds — 12 * p.
    WoO 8-deck: 372/415 = 89.64%."""
    return PAIR_MULTIPLIER * pair_probability(decks)


def pair_house_edge(decks: Optional[int] = 8) -> Fraction:
    """Exact pair-bet house edge: 1 - 12 * (4D-1)/(52D-1).  Reproduces
    WoO's published column: 10.36% (8 decks), 11.25% (6), 29.41% (1),
    7.69% (infinite)."""
    return 1 - pair_rtp(decks)


def pair_std_per_unit(decks: Optional[int] = 8) -> float:
    """Per-unit SD of the pair-bet net result (+11 on a pair, -1
    otherwise): sqrt(144 p (1-p))."""
    p = pair_probability(decks)
    return math.sqrt(float(144 * p * (1 - p)))


def pair_summary(decks: Optional[int] = 8, bet: str = "player_pair") -> Dict[str, object]:
    """Standard analytic result dict for one pair side bet (both pair bets
    are exactly symmetric)."""
    if bet not in PAIR_BET_TYPES:
        raise ValueError(f"unknown pair bet {bet!r}; must be one of {PAIR_BET_TYPES}")
    p = pair_probability(decks)
    return {
        "rtp": float(pair_rtp(decks)),
        "house_edge": float(pair_house_edge(decks)),
        "std_per_unit": pair_std_per_unit(decks),
        "payout_odds": f"{float(PAIR_PAYOUT_ODDS):g}:1",
        "multiplier": float(PAIR_MULTIPLIER),
        "win_probability": float(p),
        "push_probability": 0.0,
        "config": {
            "game": "baccarat",
            "variant": "punto_banco",
            "decks": decks if decks is not None else "infinite",
            "bet_type": bet,
            "payout_odds": f"{float(PAIR_PAYOUT_ODDS):g}:1",
            "multiplier": float(PAIR_MULTIPLIER),
            "rank_based": True,
            "events_per_round": EVENTS_PER_ROUND,
            "win_probability": float(p),
            "push_probability": 0.0,
        },
    }


def full_payout_table(decks: Optional[int] = 8) -> Dict[str, Dict[str, object]]:
    """Per bet: published odds, multiplier, exact probabilities, RTP, house
    edge, per-unit SD — all analytic.  Covers the three main bets (Stake's
    published spots) AND the two 11:1 pair side bets from WoO's table, so
    every column of the published house-edge table is reproducible."""
    table = {
        bet: Baccarat(bet, decks=decks).analytic_summary() | {
            "payout_odds": f"{float(PAYOUT_ODDS[bet]):g}:1",
            "multiplier": float(MULTIPLIERS[bet]),
            "win_probability": Baccarat(bet, decks=decks).win_probability,
            "push_probability": Baccarat(bet, decks=decks).push_probability,
        }
        for bet in BET_TYPES
    }
    for bet in PAIR_BET_TYPES:
        table[bet] = pair_summary(decks, bet)
    return table


# ---------------------------------------------------------------------------
# card drawing (shared by scalar play and the vectorized simulator)
# ---------------------------------------------------------------------------

def _cards_scalar(floats: Sequence[float], decks: Optional[int]) -> List[int]:
    """6 card indices (0..51) from 6 floats.  Infinite deck: independent
    ``floor(float * 52)`` (Stake verbatim).  Finite shoe: partial
    Fisher-Yates over the ``52 * decks`` pool (pool id mod 52 = card)."""
    if len(floats) != EVENTS_PER_ROUND:
        raise ValueError(f"need exactly {EVENTS_PER_ROUND} floats")
    if decks is None:
        return sq_rng.cards_from_floats(floats)
    _, total = _shoe_params(decks)
    return [i % _DECK for i in sq_rng.fisher_yates_draws(floats, total)]


def _cards_matrix(floats2d: np.ndarray, decks: Optional[int]) -> np.ndarray:
    """(n, 6) card indices 0..51 from a (n, 6) float matrix — row-identical
    to :func:`_cards_scalar`.

    Finite shoe: draw j maps ``floor(float * (total - j))`` — the position
    among the remaining (always ascending) pool — to the j-th smallest
    undrawn pool id by insertion-order rank correction, which is exactly
    the pop-order partial Fisher-Yates of the scalar path without ever
    materializing per-row pools (memory stays O(n * 6)).
    """
    if floats2d.ndim != 2 or floats2d.shape[1] != EVENTS_PER_ROUND:
        raise ValueError(f"need an (n, {EVENTS_PER_ROUND}) float matrix")
    if decks is None:
        return np.floor(floats2d * _DECK).astype(np.int64)
    _, total = _shoe_params(decks)
    n = floats2d.shape[0]
    ids = np.empty((n, EVENTS_PER_ROUND), dtype=np.int64)
    for j in range(EVENTS_PER_ROUND):
        actual = np.floor(floats2d[:, j] * (total - j)).astype(np.int64)
        if j:
            prev = np.sort(ids[:, :j], axis=1)
            for k in range(j):        # ascending: shift past each drawn id
                actual += prev[:, k] <= actual
        ids[:, j] = actual
    return ids % _DECK


def _settle_matrix(values: np.ndarray) -> np.ndarray:
    """Vectorized :func:`settle_values`: (n, 6) event VALUES in dealt order
    -> outcome codes (0 = player win, 1 = banker win, 2 = tie)."""
    v = values
    pt2 = (v[:, 0] + v[:, 2]) % 10
    bt2 = (v[:, 1] + v[:, 3]) % 10
    natural = (pt2 >= 8) | (bt2 >= 8)
    player_draws = ~natural & (pt2 <= 5)
    # event 4 = player's 3rd card when the player draws, else banker's 3rd
    p3 = v[:, 4]
    b_draws = ~natural & np.where(
        player_draws, BANKER_DRAW_TABLE[bt2, p3], bt2 <= 5
    )
    b3 = np.where(player_draws, v[:, 5], v[:, 4])
    pt = (pt2 + np.where(player_draws, p3, 0)) % 10
    bt = (bt2 + np.where(b_draws, b3, 0)) % 10
    return np.where(pt == bt, 2, np.where(pt > bt, 0, 1)).astype(np.int64)


_OUTCOME_NAMES = ("player", "banker", "tie")


def deal_cards(
    rng: BulkRng, n_rounds: int, decks: Optional[int] = 8
) -> np.ndarray:
    """Deal ``n_rounds`` provably-fair rounds (one nonce each, 6 events
    each) and return the (n, 6) CARD INDICES 0..51 in dealt order — full
    rank identity (index // 4), not just baccarat values.  Row i is
    bit-for-bit the ``cards`` list of :meth:`Baccarat.play_round` at nonce
    ``start + i`` where ``start`` is ``rng.nonce_next`` before the call."""
    if n_rounds <= 0:
        raise ValueError("n_rounds must be positive")
    if decks is None:
        # Stake's published unlimited-deck mechanism: use BulkRng's own
        # per-bet baccarat method — it reads the 6-event budget from
        # EVENT_COUNTS['baccarat'] and consumes ONE nonce per coup, so this
        # module cannot drift from the RNG core's event accounting.
        return rng.baccarat_cards(n_rounds)
    floats = rng.float_matrix(n_rounds, EVENTS_PER_ROUND)
    return _cards_matrix(floats, decks)


def deal_rounds(
    rng: BulkRng, n_rounds: int, decks: Optional[int] = 8
) -> np.ndarray:
    """Deal ``n_rounds`` provably-fair rounds (one nonce each, 6 events
    each) and return outcome codes (0 player / 1 banker / 2 tie).  Row i is
    bit-for-bit reproducible with :meth:`Baccarat.play_round` at nonce
    ``start + i`` where ``start`` is ``rng.nonce_next`` before the call."""
    return _settle_matrix(CARD_VALUES[deal_cards(rng, n_rounds, decks)])


# ---------------------------------------------------------------------------
# engine
# ---------------------------------------------------------------------------

class Baccarat:
    """Baccarat engine for ONE bet of one unit (player / banker / tie).

    Standard engine contract:

    (a) exact analytic paytable / probability / RTP / variance,
    (b) provably-fair single-round play on the scalar RNG path,
    (c) a vectorized :class:`BulkRng` simulator for 10M+ rounds,
    (d) the standard result dict {rtp, house_edge, std_per_unit, config}.

    ``decks=8`` (default) is the standard punto banco shoe; ``decks=None``
    is Stake's published unlimited-deck mechanism (module docstring).
    """

    def __init__(self, bet_type: str, decks: Optional[int] = 8) -> None:
        if bet_type not in BET_TYPES:
            raise ValueError(
                f"unknown bet type {bet_type!r}; must be one of {BET_TYPES}"
            )
        _shoe_params(decks)  # validates
        self.bet_type = bet_type
        self.decks = decks
        self.payout_odds = PAYOUT_ODDS[bet_type]
        self._mult_exact = MULTIPLIERS[bet_type]
        probs = outcome_probabilities(decks)
        self._p_win = probs[bet_type]
        if bet_type == "tie":
            self._p_push = Fraction(0)
        else:
            self._p_push = probs["tie"]
        self._p_lose = 1 - self._p_win - self._p_push

    # ---- (a) analytics — exact rationals, floats at the edge -------------

    @property
    def multiplier_exact(self) -> Fraction:
        """Total return per unit on a win (odds + 1)."""
        return self._mult_exact

    @property
    def multiplier(self) -> float:
        return float(self._mult_exact)

    @property
    def win_probability_exact(self) -> Fraction:
        return self._p_win

    @property
    def win_probability(self) -> float:
        return float(self._p_win)

    @property
    def push_probability_exact(self) -> Fraction:
        return self._p_push

    @property
    def push_probability(self) -> float:
        return float(self._p_push)

    @property
    def lose_probability(self) -> float:
        return float(self._p_lose)

    @property
    def rtp_exact(self) -> Fraction:
        """Expected total return per unit: M * P(win) + 1 * P(push).
        Ties count as resolved pushes — the WoO house-edge convention."""
        return self._mult_exact * self._p_win + self._p_push

    @property
    def rtp(self) -> float:
        return float(self.rtp_exact)

    @property
    def house_edge_exact(self) -> Fraction:
        return 1 - self.rtp_exact

    @property
    def house_edge(self) -> float:
        return float(self.house_edge_exact)

    @property
    def variance_per_unit(self) -> float:
        """Variance of the NET result per unit staked (odds on win, 0 on
        push, -1 on loss) — the WoO per-unit SD convention."""
        o = self.payout_odds
        ev = o * self._p_win - self._p_lose
        var = o * o * self._p_win + self._p_lose - ev * ev
        return float(var)

    @property
    def std_per_unit(self) -> float:
        return math.sqrt(self.variance_per_unit)

    def config(self) -> Dict[str, object]:
        return {
            "game": "baccarat",
            "variant": "punto_banco",
            "decks": self.decks if self.decks is not None else "infinite",
            "bet_type": self.bet_type,
            "payout_odds": f"{float(self.payout_odds):g}:1",
            "multiplier": self.multiplier,
            "tie_pushes_player_banker": True,
            "events_per_round": EVENTS_PER_ROUND,
            "win_probability": self.win_probability,
            "push_probability": self.push_probability,
        }

    def analytic_summary(self) -> Dict[str, object]:
        """Standard result dict, analytic (no simulation)."""
        return {
            "rtp": self.rtp,
            "house_edge": self.house_edge,
            "std_per_unit": self.std_per_unit,
            "config": self.config(),
        }

    # ---- (b) provably-fair single round ----------------------------------

    def play_round(
        self, server_seed: str, client_seed: str, nonce: int
    ) -> Dict[str, object]:
        """Play one verifiable round: 6 floats from cursor 0 (one digest,
        matching the published '1 incremental number'), mapped to cards per
        the configured shoe model, settled with the published drawing
        rules; the returned dict carries everything needed to re-verify."""
        floats = sq_rng.generate_floats(
            server_seed, client_seed, nonce, 0, EVENTS_PER_ROUND
        )
        cards = _cards_scalar(floats, self.decks)
        res = settle_values([card_value(c) for c in cards])
        outcome = res["outcome"]
        win = outcome == self.bet_type
        push = self.bet_type != "tie" and outcome == "tie"
        payout = self.multiplier if win else (1.0 if push else 0.0)
        n_p = len(res["player_values"])
        n_b = len(res["banker_values"])
        # reconstruct seat assignment from dealt order (module docstring)
        player_cards = [cards[0], cards[2]] + ([cards[4]] if n_p == 3 else [])
        banker_cards = [cards[1], cards[3]]
        if n_b == 3:
            banker_cards.append(cards[4 if n_p == 2 else 5])
        return {
            "cards": cards,
            "card_names": [sq_rng.card_name(c) for c in cards],
            "player_cards": [sq_rng.card_name(c) for c in player_cards],
            "banker_cards": [sq_rng.card_name(c) for c in banker_cards],
            "player_total": res["player_total"],
            "banker_total": res["banker_total"],
            # 11:1 pair side bets: first two cards of the hand share a RANK
            # (index // 4) — finer than value: e.g. ♦K + ♥K is a pair,
            # ♦K + ♦10 is not, though both hands total 0.
            "player_pair": cards[0] // 4 == cards[2] // 4,
            "banker_pair": cards[1] // 4 == cards[3] // 4,
            "natural": res["natural"],
            "events_used": res["events_used"],
            "outcome": outcome,
            "win": win,
            "push": push,
            "payout": payout,
            "floats": floats,
            "config": self.config(),
            "verification": {
                "server_seed": server_seed,
                "client_seed": client_seed,
                "nonce": nonce,
            },
        }

    # ---- (c) vectorized simulator ----------------------------------------

    def payouts_for_outcomes(self, outcomes: np.ndarray) -> np.ndarray:
        """Settle this bet against outcome codes (0/1/2) — total return per
        unit; shared-round evaluation across the three bets."""
        table = np.zeros(3, dtype=np.float64)
        table[_OUTCOME_NAMES.index(self.bet_type)] = self.multiplier
        if self.bet_type != "tie":
            table[2] = 1.0                              # push
        return table[outcomes]

    def simulate(
        self,
        n_rounds: int,
        bulk: Optional[BulkRng] = None,
        chunk_rounds: int = 1_000_000,
        progress: bool = True,
    ) -> Dict[str, object]:
        """Simulate ``n_rounds`` provably-fair rounds (one nonce per round)
        on the vectorized :class:`BulkRng` stream; standard result dict."""
        res = simulate_all_bets(
            n_rounds,
            decks=self.decks,
            bulk=bulk,
            chunk_rounds=chunk_rounds,
            progress=progress,
            bets=(self.bet_type,),
        )
        out = res["bets"][self.bet_type]
        out["outcome_counts"] = res["outcome_counts"]
        out["elapsed_s"] = res["elapsed_s"]
        out["rounds_per_sec"] = res["rounds_per_sec"]
        out["verification"] = res["verification"]
        return out


def simulate_all_bets(
    n_rounds: int,
    decks: Optional[int] = 8,
    bulk: Optional[BulkRng] = None,
    chunk_rounds: int = 1_000_000,
    progress: bool = True,
    bets: Sequence[str] = BET_TYPES,
) -> Dict[str, object]:
    """Simulate one shared campaign of ``n_rounds`` rounds and settle every
    requested bet against the SAME rounds (as at a real table).  Chunked so
    per-chunk arrays stay small (1M rounds -> ~150 MB peak); each chunk is
    one contiguous nonce range of the provably-fair stream."""
    if n_rounds <= 0:
        raise ValueError("n_rounds must be positive")
    for b in bets:
        if b not in BET_TYPES:
            raise ValueError(f"unknown bet type {b!r}")
    rng = bulk if bulk is not None else BulkRng()
    nonce_first = rng.nonce_next
    counts = np.zeros(3, dtype=np.int64)
    done = 0
    t0 = time.perf_counter()
    while done < n_rounds:
        step = min(chunk_rounds, n_rounds - done)
        outcomes = deal_rounds(rng, step, decks)
        counts += np.bincount(outcomes, minlength=3)
        done += step
        if progress and n_rounds > chunk_rounds:
            rate = done / (time.perf_counter() - t0)
            print(
                f"  baccarat({'inf' if decks is None else decks} decks): "
                f"{done:,}/{n_rounds:,} rounds ({rate:,.0f}/s)",
                flush=True,
            )
    elapsed = time.perf_counter() - t0

    per_bet: Dict[str, Dict[str, object]] = {}
    for bet in bets:
        eng = Baccarat(bet, decks=decks)
        i_win = _OUTCOME_NAMES.index(bet)
        wins = int(counts[i_win])
        pushes = int(counts[2]) if bet != "tie" else 0
        rtp_emp = (wins * eng.multiplier + pushes) / n_rounds
        se = eng.std_per_unit / math.sqrt(n_rounds)
        z = (rtp_emp - eng.rtp) / se if se > 0 else 0.0
        # empirical per-unit SD of the net result
        p_w, p_p = wins / n_rounds, pushes / n_rounds
        o = float(eng.payout_odds)
        m2 = o * o * p_w + (1.0 - p_w - p_p)
        mean = o * p_w - (1.0 - p_w - p_p)
        per_bet[bet] = {
            "rtp": rtp_emp,
            "house_edge": 1.0 - rtp_emp,
            "std_per_unit": math.sqrt(max(m2 - mean * mean, 0.0)),
            "config": eng.config(),
            "n_rounds": n_rounds,
            "wins": wins,
            "pushes": pushes,
            "win_rate": p_w,
            "analytic_rtp": eng.rtp,
            "analytic_house_edge": eng.house_edge,
            "analytic_win_probability": eng.win_probability,
            "analytic_std_per_unit": eng.std_per_unit,
            "se_rtp": se,
            "z_score": z,
            "within_3se": abs(z) <= 3.0,
        }
    return {
        "n_rounds": n_rounds,
        "decks": decks if decks is not None else "infinite",
        "outcome_counts": {
            name: int(counts[i]) for i, name in enumerate(_OUTCOME_NAMES)
        },
        "bets": per_bet,
        "elapsed_s": elapsed,
        "rounds_per_sec": n_rounds / elapsed if elapsed > 0 else float("inf"),
        "pass": all(r["within_3se"] for r in per_bet.values()),
        "verification": {
            "server_seed_hash": rng.server_seed_hash,
            "client_seed": rng.client_seed,
            "nonce_range": (nonce_first, rng.nonce_next),
        },
    }


def simulate_pairs(
    n_rounds: int,
    decks: Optional[int] = 8,
    bulk: Optional[BulkRng] = None,
    chunk_rounds: int = 1_000_000,
    progress: bool = True,
) -> Dict[str, object]:
    """RANK-granular empirical campaign: deal ``n_rounds`` provably-fair
    rounds and check the dealt CARD INDICES (not just their baccarat
    values) against the exact rank-level analytics.

    Measures (a) both 11:1 pair side bets — empirical win frequency and
    RTP vs the exact :func:`pair_probability` / :func:`pair_rtp`, with
    z-scores against the exact binomial SE — and (b) rank uniformity: a
    13-bin count of card index // 4 for EACH of the 6 dealt positions
    (every position is marginally uniform over ranks for both shoe
    models), reported as per-position chi-squared statistics (df 12) and
    the worst per-cell z.  Same seeds/nonces as :func:`simulate_all_bets`
    deal the identical cards, so this audits the very shoe the main bets
    settle on — at a granularity the value-level enumeration cannot see.
    """
    if n_rounds <= 0:
        raise ValueError("n_rounds must be positive")
    rng = bulk if bulk is not None else BulkRng()
    nonce_first = rng.nonce_next
    p_pairs = 0
    b_pairs = 0
    rank_counts = np.zeros((EVENTS_PER_ROUND, _RANKS), dtype=np.int64)
    done = 0
    t0 = time.perf_counter()
    while done < n_rounds:
        step = min(chunk_rounds, n_rounds - done)
        cards = deal_cards(rng, step, decks)
        ranks = cards // 4
        p_pairs += int(np.sum(ranks[:, 0] == ranks[:, 2]))
        b_pairs += int(np.sum(ranks[:, 1] == ranks[:, 3]))
        for j in range(EVENTS_PER_ROUND):
            rank_counts[j] += np.bincount(ranks[:, j], minlength=_RANKS)
        done += step
        if progress and n_rounds > chunk_rounds:
            rate = done / (time.perf_counter() - t0)
            print(
                f"  baccarat pairs/ranks ({'inf' if decks is None else decks}"
                f" decks): {done:,}/{n_rounds:,} rounds ({rate:,.0f}/s)",
                flush=True,
            )
    elapsed = time.perf_counter() - t0

    p_exact = pair_probability(decks)
    pf = float(p_exact)
    se_p = math.sqrt(pf * (1.0 - pf) / n_rounds)          # binomial SE
    rtp_exact = float(pair_rtp(decks))
    bets: Dict[str, Dict[str, object]] = {}
    for bet, hits in (("player_pair", p_pairs), ("banker_pair", b_pairs)):
        freq = hits / n_rounds
        z = (freq - pf) / se_p if se_p > 0 else 0.0
        bets[bet] = {
            "rtp": float(PAIR_MULTIPLIER) * freq,
            "house_edge": 1.0 - float(PAIR_MULTIPLIER) * freq,
            "std_per_unit": math.sqrt(max(144.0 * freq * (1.0 - freq), 0.0)),
            "config": pair_summary(decks, bet)["config"],
            "n_rounds": n_rounds,
            "wins": hits,
            "win_rate": freq,
            "analytic_win_probability": pf,
            "analytic_rtp": rtp_exact,
            "analytic_house_edge": 1.0 - rtp_exact,
            "analytic_std_per_unit": pair_std_per_unit(decks),
            "se_win_rate": se_p,
            "z_score": z,
            "within_3se": abs(z) <= 3.0,
        }

    # rank uniformity per dealt position: expected n/13 per cell
    expected = n_rounds / _RANKS
    dev = rank_counts - expected
    chi2 = (dev * dev / expected).sum(axis=1)             # (6,) each df 12
    se_cell = math.sqrt(n_rounds * (1 / _RANKS) * (1 - 1 / _RANKS))
    max_cell_z = float(np.max(np.abs(dev)) / se_cell)
    return {
        "n_rounds": n_rounds,
        "decks": decks if decks is not None else "infinite",
        "bets": bets,
        "rank_counts": rank_counts.tolist(),
        "rank_chi2_per_position": [float(x) for x in chi2],
        "rank_chi2_df": _RANKS - 1,
        "max_rank_cell_z": max_cell_z,
        "elapsed_s": elapsed,
        "rounds_per_sec": n_rounds / elapsed if elapsed > 0 else float("inf"),
        "pass": all(r["within_3se"] for r in bets.values()),
        "verification": {
            "server_seed_hash": rng.server_seed_hash,
            "client_seed": rng.client_seed,
            "nonce_range": (nonce_first, rng.nonce_next),
        },
    }
