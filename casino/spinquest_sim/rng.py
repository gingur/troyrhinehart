"""Stake-style provably-fair HMAC-SHA256 RNG.

Everything in this module — scalar and bulk — draws from ONE byte stream:
``HMAC_SHA256(key=serverSeed, message=f"{clientSeed}:{nonce}:{currentRound}")``,
a byte-exact Python port of Stake's published verifier code
(references/stake/core.md — Wayback snapshots of stake.com/provably-fair/*).

Two API surfaces, one RNG:

1. **Scalar path** (module-level functions): direct port of the published JS —
   byteGenerator, generateFloats (4 bytes -> ``sum(b_i / 256**(i+1))``), the
   per-game event mappings, and the SHA-256 seed-hash commitment.  Use it to
   verify any single bet.

2. **Bulk path** (:class:`BulkRng`): a *vectorized* implementation of the SAME
   provably-fair stream.  It builds HMAC digests for a contiguous nonce range
   (one bet per nonce, exactly like real play), folds each 4-byte group to the
   identical ``k / 2**32`` float, and applies the identical mapping arithmetic.
   Every simulated round is therefore individually verifiable: the class
   exposes ``server_seed`` / ``server_seed_hash`` / ``client_seed`` /
   ``nonce_start`` / ``nonce_next``, and row ``i`` of any bulk call is
   bit-for-bit reproducible with the scalar path at its recorded nonce.
   There is no statistical twin and no second RNG anywhere in this module.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import numbers
import os
import secrets
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

import numpy as np

__all__ = [
    "BYTES_PER_FLOAT",
    "BYTES_PER_DIGEST",
    "EVENTS_PER_DIGEST",
    "CARDS",
    "RANKS",
    "SUITS",
    "GEMS",
    "EVENT_COUNTS",
    "CURSOR_INCREMENTS",
    "DRAGON_TOWER_LEVEL_MAP",
    "DRAGON_TOWER_ROWS",
    "SCARAB_SPIN_REELS",
    "BLUE_SAMURAI_FLOATS_REGULAR",
    "BLUE_SAMURAI_FLOATS_SPECIAL",
    "digests_for_events",
    "hash_server_seed",
    "byte_generator",
    "generate_bytes",
    "generate_floats",
    "float_to_index",
    "fisher_yates_draws",
    "weighted_index",
    "card_index",
    "card_name",
    "cards_from_floats",
    "gem_index",
    "gems_from_floats",
    "dice_roll",
    "limbo_crash_point",
    "roulette_pocket",
    "wheel_index",
    "plinko_directions",
    "keno_hits",
    "mines_positions",
    "video_poker_deck",
    "card_draws",
    "baccarat_cards",
    "diamonds_gems",
    "diamond_poker_hands",
    "dragon_tower_eggs",
    "scarab_spin_stops",
    "scarab_spin",
    "blue_samurai_symbols",
    "BulkRng",
]

# ---------------------------------------------------------------------------
# Constants (from the published spec)
# ---------------------------------------------------------------------------

BYTES_PER_FLOAT = 4          # "4 bytes of data generate a single game result"
BYTES_PER_DIGEST = 32        # one HMAC-SHA256 digest
EVENTS_PER_DIGEST = 8        # 32 bytes = 8 results

RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
SUITS = ["♦", "♥", "♠", "♣"]  # diamonds, hearts, spades, clubs

# Index 0..51 : ♦2 ... ♣A — order within each rank: diamond, heart, spade, club.
CARDS: List[str] = [f"{suit}{rank}" for rank in RANKS for suit in SUITS]

# Diamonds / Diamond Poker — verbatim from the published game-events code:
#   // Index of 0 to 6 : green to blue
#   const GEMS = [ green, purple, yellow, red, cyan, orange, blue ];
GEMS: List[str] = ["green", "purple", "yellow", "red", "cyan", "orange", "blue"]

_KENO_POOL = 40      # 40-square board, 10 hits drawn without replacement
_KENO_DRAWS = 10
_MINES_TILES = 25    # 5x5 board; 24 mine-location events drawn without replacement
_MINES_EVENTS = 24
_DECK = 52
_BACCARAT_EVENTS = 6      # doc: "Baccarat only ever needs 6 game events"
_DIAMONDS_EVENTS = 5      # Diamonds: player's 5 gems
_DIAMOND_POKER_EVENTS = 10  # 5 dealer + 5 player

_DRAGON_TOWER_EVENTS = 9  # doc: "9 game events (one per tower level)"
_SCARAB_SPIN_EVENTS = 5   # doc: "5 game events per spin" (base spin)
_BLUE_SAMURAI_EVENTS = 18          # regular/bonus spin
_BLUE_SAMURAI_SPECIAL_EVENTS = 12  # special spin (outer 2 reels disabled)

# Floats (game events) a standard bet consumes, per the game-events page.
# This table is LIVE: the scalar per-game helpers and every BulkRng game
# method read their event counts from here — a game absent from this table
# has no float budget and no cursor increment, so keep it complete.
EVENT_COUNTS: Dict[str, int] = {
    "dice": 1,
    "limbo": 1,
    "wheel": 1,
    "roulette": 1,
    "diamonds": _DIAMONDS_EVENTS,
    "baccarat": _BACCARAT_EVENTS,
    "keno": _KENO_DRAWS,
    "plinko": 16,              # up to 16 pin rows -> up to 16 decisions
    "diamond_poker": _DIAMOND_POKER_EVENTS,
    "mines": _MINES_EVENTS,
    "video_poker": _DECK,
    "dragon_tower": _DRAGON_TOWER_EVENTS,
    "scarab_spin": _SCARAB_SPIN_EVENTS,
    "blue_samurai": _BLUE_SAMURAI_EVENTS,
    "blue_samurai_special": _BLUE_SAMURAI_SPECIAL_EVENTS,
}


def digests_for_events(event_count: int) -> int:
    """HMAC digests actually consumed by ``event_count`` 4-byte events:
    ``ceil(event_count * 4 / 32)``."""
    return -(-event_count * BYTES_PER_FLOAT // BYTES_PER_DIGEST)


# Incremental numbers (digest count, i.e. distinct ``currentRound`` values)
# per bet, as published.  Where the doc states an exact count for a
# fixed-length game, the value here is COMPUTED from EVENT_COUNTS via
# digests_for_events — a test asserts the computed values equal the doc's
# verbatim numbers (keno 2, plinko 2, diamond poker 2, mines 3, video
# poker 7), so this table cannot drift from the code that consumes bytes.
#
# Special cases taken verbatim from the doc rather than computed:
# - hilo/blackjack: "a curser of 13 to generate 52 possible game events".
#   13 digests reserve 104 floats — a RESERVATION for open-ended card draws,
#   not the per-hand consumption; actually drawing 52 cards reads
#   digests_for_events(52) == 7 digests.  Both numbers are real; 13 is the
#   published reservation, 7 is what a full 52-card draw touches.
# - slots: "The incremental number is only utilised for bonus rounds" —
#   variable, no fixed count, recorded as None.
CURSOR_INCREMENTS: Dict[str, Optional[int]] = {
    "dice": digests_for_events(EVENT_COUNTS["dice"]),            # 1
    "limbo": digests_for_events(EVENT_COUNTS["limbo"]),          # 1
    "wheel": digests_for_events(EVENT_COUNTS["wheel"]),          # 1
    "baccarat": digests_for_events(EVENT_COUNTS["baccarat"]),    # 1
    "roulette": digests_for_events(EVENT_COUNTS["roulette"]),    # 1
    "diamonds": digests_for_events(EVENT_COUNTS["diamonds"]),    # 1
    "keno": digests_for_events(EVENT_COUNTS["keno"]),            # 2
    "plinko": digests_for_events(EVENT_COUNTS["plinko"]),        # 2
    "diamond_poker": digests_for_events(EVENT_COUNTS["diamond_poker"]),  # 2
    "mines": digests_for_events(EVENT_COUNTS["mines"]),          # 3
    "video_poker": digests_for_events(EVENT_COUNTS["video_poker"]),      # 7
    "dragon_tower": digests_for_events(EVENT_COUNTS["dragon_tower"]),    # 2
    "scarab_spin": digests_for_events(EVENT_COUNTS["scarab_spin"]),      # 1
    "blue_samurai": digests_for_events(EVENT_COUNTS["blue_samurai"]),    # 3
    "blue_samurai_special": digests_for_events(
        EVENT_COUNTS["blue_samurai_special"]
    ),  # 2
    "hilo": 13,       # doc-verbatim reservation (see note above)
    "blackjack": 13,  # doc-verbatim reservation (see note above)
    "slots": None,    # doc: bonus rounds only; variable
}

# Dragon Tower — published verbatim (core.md §3), including Stake's own
# ``expert: { count1, size: 3 }`` typo, which can only mean count: 1:
#   const LEVEL_MAP = {
#     easy: { count: 3, size: 4 }, medium: { count: 2, size: 3 },
#     hard: { count: 1, size: 2 }, expert: { count1, size: 3 },  [sic]
#     master: { count: 1, size: 4 },
#   }
DRAGON_TOWER_LEVEL_MAP: Dict[str, Tuple[int, int]] = {
    "easy": (3, 4),
    "medium": (2, 3),
    "hard": (1, 2),
    "expert": (1, 3),  # [sic] published as "count1"; 1 is the only reading
    "master": (1, 4),
}
DRAGON_TOWER_ROWS = 9  # "9 game events (one per tower level)"

# The level map has min(count, size - count) == 1 for EVERY difficulty, so a
# single float per level determines the whole row: floor(float * size) draws
# the minority tile — the skull for easy/medium (eggs = the sorted
# complement), the egg itself for hard/expert/master.  That is what makes
# "9 game events (one per tower level)" possible, gives the "no duplicate
# eggs per row" guarantee for free, and is why the doc's worked example
# ``[0, 1, 3]`` is sorted (the complement of one skull always is).
assert all(
    min(c, s - c) == 1 for c, s in DRAGON_TOWER_LEVEL_MAP.values()
), "Dragon Tower one-float-per-level reading requires a minority of 1"

# Scarab Spin / Tome of Life: float x reel length = central stop position.
# "First 4 reels have 30 possible outcomes, last reel 41. 5 game events per
# spin; more during bonus rounds."
SCARAB_SPIN_REELS: Tuple[int, ...] = (30, 30, 30, 30, 41)

# Blue Samurai: 18 floats per regular/bonus spin, 12 per special spin (outer
# 2 reels disabled).  Symbols are chosen by weighted random sampling (fitness
# proportionate selection); Stake did NOT publish the weight tables, so only
# the selection primitive (weighted_index) and the float budgets are
# implementable from the reference.  (Aliases of the LIVE EVENT_COUNTS
# entries, kept for the public API.)
BLUE_SAMURAI_FLOATS_REGULAR = EVENT_COUNTS["blue_samurai"]
BLUE_SAMURAI_FLOATS_SPECIAL = EVENT_COUNTS["blue_samurai_special"]


# ---------------------------------------------------------------------------
# 1. Scalar provably-fair path (verified port of the published code)
# ---------------------------------------------------------------------------

def hash_server_seed(server_seed: str) -> str:
    """SHA-256 commitment of the (64-char hex string) server seed.

    Stake shows ``sha256(serverSeed)`` before betting; the seed itself is
    revealed on rotation.  The hash is over the ASCII/UTF-8 text of the seed
    string, not its hex-decoded bytes.
    """
    return hashlib.sha256(server_seed.encode("utf-8")).hexdigest()


def _check_nonce(nonce: object) -> int:
    """Validate and normalize a nonce to a plain int.

    Rejects bool/float/str: the JS template literal renders ``7.0`` as
    ``"7"`` and ``true`` as ``"true"``, while Python's f-string renders
    ``"7.0"``/``"True"`` — a silently forked byte stream for a verifier fed
    loosely-typed JSON.  Numpy integer types (np.int64 etc.) are accepted and
    converted with ``int()`` — they format identically and vectorized drivers
    iterate nonces out of numpy arrays.
    """
    if isinstance(nonce, (bool, np.bool_)) or not isinstance(nonce, numbers.Integral):
        raise TypeError(
            f"nonce must be an integer, got {type(nonce).__name__}: coercing "
            "float/bool/str nonces silently forks the byte stream"
        )
    return int(nonce)


def _resolve_cursor(cursor: int, round_index: Optional[int]) -> int:
    """Reconcile the two published meanings of "cursor".

    The published ``byteGenerator`` code treats ``cursor`` as a BYTE offset
    (``currentRound = Math.floor(cursor / 32)``); Stake's prose ("the cursor
    starts at 0 and increments by 1 each time 32 bytes are consumed") and the
    per-game increment table count DIGESTS.  A caller who read the prose and
    passes ``cursor=1`` expecting the second digest would silently get bytes
    1..32 of the FIRST digest.  Pass ``round_index=r`` to start at digest
    ``r`` (byte offset ``r * 32``) unambiguously.
    """
    if round_index is not None:
        if cursor != 0:
            raise ValueError(
                "pass either cursor (a BYTE offset) or round_index (a DIGEST "
                "index), not both"
            )
        return round_index * BYTES_PER_DIGEST
    return cursor


def byte_generator(
    server_seed: str,
    client_seed: str,
    nonce: int,
    cursor: int = 0,
    *,
    round_index: Optional[int] = None,
) -> Iterator[int]:
    """Infinite byte stream, port of Stake's published ``byteGenerator``.

    ``cursor`` is a BYTE offset into the stream (exactly as in the published
    code: ``currentRound = cursor // 32``); the digest index ``currentRound``
    is appended to the HMAC message ``f"{clientSeed}:{nonce}:{currentRound}"``.
    To address whole digests the way Stake's prose does ("cursor" = number of
    32-byte digests already consumed), pass ``round_index`` instead — see
    :func:`_resolve_cursor`.
    """
    nonce = _check_nonce(nonce)
    cursor = _resolve_cursor(cursor, round_index)
    current_round = cursor // BYTES_PER_DIGEST
    current_round_cursor = cursor - current_round * BYTES_PER_DIGEST
    key = server_seed.encode("utf-8")
    while True:
        digest = hmac.new(
            key,
            f"{client_seed}:{nonce}:{current_round}".encode("utf-8"),
            hashlib.sha256,
        ).digest()
        while current_round_cursor < BYTES_PER_DIGEST:
            yield digest[current_round_cursor]
            current_round_cursor += 1
        current_round_cursor = 0
        current_round += 1


def generate_bytes(
    server_seed: str,
    client_seed: str,
    nonce: int,
    cursor: int = 0,
    count: int = 32,
    *,
    round_index: Optional[int] = None,
) -> List[int]:
    """First ``count`` bytes of the stream starting at ``cursor`` (byte
    offset) or ``round_index`` (digest index)."""
    gen = byte_generator(server_seed, client_seed, nonce, cursor, round_index=round_index)
    return [next(gen) for _ in range(count)]


def generate_floats(
    server_seed: str,
    client_seed: str,
    nonce: int,
    cursor: int = 0,
    count: int = 1,
    *,
    round_index: Optional[int] = None,
) -> List[float]:
    """Port of Stake's ``generateFloats``: 4 bytes -> ``sum(b_i / 256**(i+1))``.

    Each float lies in [0, 1) with exact granularity ``1 / 2**32``.  (The
    4-term sum is exact in binary floating point, so the result equals the
    big-endian 32-bit integer of the 4 bytes divided by 2**32 — the identity
    the vectorized bulk path relies on.)
    """
    raw = generate_bytes(
        server_seed, client_seed, nonce, cursor, count * BYTES_PER_FLOAT,
        round_index=round_index,
    )
    out: List[float] = []
    for chunk_start in range(0, len(raw), BYTES_PER_FLOAT):
        value = 0.0
        for i in range(BYTES_PER_FLOAT):
            value += raw[chunk_start + i] / (256 ** (i + 1))
        out.append(value)
    return out


def float_to_index(value: float, outcome_count: int) -> int:
    """General rule: ``Math.floor(float * outcomes)`` -> index in [0, outcomes)."""
    return math.floor(value * outcome_count)


def fisher_yates_draws(floats: Sequence[float], pool: Sequence[int] | int) -> List[int]:
    """Partial Fisher-Yates: each float draws from the shrinking remaining pool.

    ``pool`` is either an explicit sequence of outcomes or an int N meaning
    ``range(N)``.  Float i is scaled by the remaining pool size (N, N-1, ...),
    the picked element is removed (list ``pop``, preserving order of the
    rest), so draws never repeat.  Used by Keno, Mines, Video Poker and
    Dragon Tower rows.
    """
    remaining = list(range(pool)) if isinstance(pool, int) else list(pool)
    if len(floats) > len(remaining):
        raise ValueError("more draws requested than pool elements")
    drawn: List[int] = []
    for f in floats:
        drawn.append(remaining.pop(math.floor(f * len(remaining))))
    return drawn


def weighted_index(value: float, weights: Sequence[float]) -> int:
    """Fitness-proportionate selection (Blue Samurai's dynamic reels).

    Scales ``value`` by the total weight and returns the first index whose
    cumulative weight exceeds it — the standard roulette-wheel/fitness-
    proportionate rule the game-events page names for Blue Samurai.  Stake
    did not publish the actual weight tables, so callers must supply them.
    """
    if not weights:
        raise ValueError("weights must be non-empty")
    total = 0.0
    for w in weights:
        if w < 0:
            raise ValueError("weights must be non-negative")
        total += w
    if total <= 0:
        raise ValueError("total weight must be positive")
    target = value * total
    cumulative = 0.0
    for i, w in enumerate(weights):
        cumulative += w
        if target < cumulative:
            return i
    return len(weights) - 1  # value ~ 1.0 with fp round-off


# --- per-game event mapping helpers ----------------------------------------

def card_index(value: float) -> int:
    """Independent card draw: ``Math.floor(float * 52)`` -> 0..51."""
    return math.floor(value * _DECK)


def card_name(index: int) -> str:
    """0..51 -> '♦2' ... '♣A' per the published CARDS table."""
    return CARDS[index]


def cards_from_floats(floats: Sequence[float]) -> List[int]:
    """Blackjack/Hilo/Baccarat: independent draws with replacement (unlimited decks)."""
    return [card_index(f) for f in floats]


def gem_index(value: float) -> int:
    """Diamonds / Diamond Poker: ``Math.floor(float * 7)`` -> 0..6 into GEMS
    (green, purple, yellow, red, cyan, orange, blue)."""
    return math.floor(value * 7)


def gems_from_floats(floats: Sequence[float]) -> List[str]:
    """Gem names for a sequence of floats — Diamonds uses 5 events, Diamond
    Poker 10 (first 5 dealer, second 5 player)."""
    return [GEMS[gem_index(f)] for f in floats]


def dice_roll(value: float) -> float:
    """Dice: 10,001 outcomes, 00.00-100.00: ``floor(float * 10001) / 100``.

    DELIBERATE divergence from the verbatim snippet, which reads
    ``(float * 10001) / 100`` without a floor: the same page's prose says
    "Range 00.00-100.00 -> 10,001 outcomes", which only holds if the event
    index is floored, the page's general translation rule is "multiply the
    float by the number of possible outcomes, floor to an index", and Dice
    results are displayed to exactly two decimals.  test_rng.py pins this
    choice so it cannot be "fixed" back to the unfloored snippet.
    """
    return math.floor(value * 10001) / 100


def limbo_crash_point(value: float, house_edge: float = 0.99) -> float:
    """Limbo crash point, byte-exact port of the published JS::

        const floatPoint = 1e8 / (float * 1e8) * houseEdge;
        const crashPoint = Math.floor(floatPoint * 100) / 100;
        const result = Math.max(crashPoint, 1);

    The operation order matters: ``1e8 / (value * 1e8) * houseEdge`` differs
    from ``houseEdge / value`` by an ULP for some lattice floats, which changes
    the floored cent (e.g. f = 0.005859375 -> 168.95, not 168.96).  For
    ``value == 0`` (probability 2**-32) the published code divides by zero,
    which in JS yields ``Infinity`` — we return ``math.inf`` to match
    (``Math.floor(Infinity * 100) / 100`` is still ``Infinity``).
    """
    if value == 0.0:
        return math.inf
    float_point = 1e8 / (value * 1e8) * house_edge
    return max(math.floor(float_point * 100) / 100, 1.0)


def roulette_pocket(value: float) -> int:
    """European roulette: ``Math.floor(float * 37)`` -> pocket 0..36."""
    return math.floor(value * 37)


def wheel_index(value: float, segments: int) -> int:
    """Wheel: ``Math.floor(float * segments)`` (published code omits the floor;
    the general rule floors the index)."""
    return math.floor(value * segments)


def plinko_directions(floats: Sequence[float]) -> List[int]:
    """Plinko: one direction per pin row; 0 = left, 1 = right."""
    return [math.floor(f * 2) for f in floats]


# --- seed-level per-game draws (one bet = one nonce, cursor from 0) ---------

def keno_hits(
    server_seed: str, client_seed: str, nonce: int, cursor: int = 0
) -> List[int]:
    """Keno: 10 hits from the 40-square board (squares numbered 1..40),
    Fisher-Yates without replacement; first float x 40."""
    floats = generate_floats(
        server_seed, client_seed, nonce, cursor, EVENT_COUNTS["keno"]
    )
    return [tile + 1 for tile in fisher_yates_draws(floats, _KENO_POOL)]


def mines_positions(
    server_seed: str,
    client_seed: str,
    nonce: int,
    mine_count: int = _MINES_EVENTS,
    cursor: int = 0,
) -> List[int]:
    """Mines: 24 mine-location events are always generated (pool of 25 tiles,
    left-to-right top-to-bottom, indices 0..24); the first ``mine_count`` are
    the mines for the chosen difficulty."""
    if not 1 <= mine_count <= _MINES_EVENTS:
        raise ValueError("mine_count must be in 1..24")
    floats = generate_floats(
        server_seed, client_seed, nonce, cursor, EVENT_COUNTS["mines"]
    )
    return fisher_yates_draws(floats, _MINES_TILES)[:mine_count]


def video_poker_deck(
    server_seed: str, client_seed: str, nonce: int, cursor: int = 0
) -> List[int]:
    """Video Poker: full 52-card deck order via Fisher-Yates (52, 51, ...)."""
    floats = generate_floats(
        server_seed, client_seed, nonce, cursor, EVENT_COUNTS["video_poker"]
    )
    return fisher_yates_draws(floats, _DECK)


def card_draws(
    server_seed: str, client_seed: str, nonce: int, count: int, cursor: int = 0
) -> List[int]:
    """Blackjack / Hilo: ``count`` independent card draws (unlimited decks,
    ``Math.floor(float * 52)`` each) from the bet's byte stream.  The stream
    is open-ended — the doc reserves a cursor of 13 digests (104 floats) for
    long hands; drawing reads only ``digests_for_events(count)`` digests."""
    floats = generate_floats(server_seed, client_seed, nonce, cursor, count)
    return cards_from_floats(floats)


def baccarat_cards(
    server_seed: str, client_seed: str, nonce: int, cursor: int = 0
) -> List[int]:
    """Baccarat: the 6 card events a game can ever need (doc: "Baccarat only
    ever needs 6 game events"), independent draws with replacement."""
    return card_draws(server_seed, client_seed, nonce, EVENT_COUNTS["baccarat"], cursor)


def diamonds_gems(
    server_seed: str, client_seed: str, nonce: int, cursor: int = 0
) -> List[str]:
    """Diamonds: the player's 5 gems (``Math.floor(float * 7)`` into GEMS)."""
    floats = generate_floats(
        server_seed, client_seed, nonce, cursor, EVENT_COUNTS["diamonds"]
    )
    return gems_from_floats(floats)


def diamond_poker_hands(
    server_seed: str, client_seed: str, nonce: int, cursor: int = 0
) -> Tuple[List[str], List[str]]:
    """Diamond Poker: 10 gem events — FIRST 5 to the DEALER, second 5 to the
    player (doc order).  Returns ``(dealer_gems, player_gems)``."""
    floats = generate_floats(
        server_seed, client_seed, nonce, cursor, EVENT_COUNTS["diamond_poker"]
    )
    names = gems_from_floats(floats)
    return names[:5], names[5:]


def _dragon_tower_row(value: float, count: int, size: int) -> List[int]:
    """One tower level from ONE float: ``floor(float * size)`` draws the
    minority tile (min(count, size - count) == 1 for every difficulty)."""
    idx = math.floor(value * size)
    if count == 1:
        return [idx]  # the drawn tile IS the egg
    # size - count == 1: the drawn tile is the skull; eggs = the complement,
    # which is always sorted — matching the doc's example [0, 1, 3].
    return [tile for tile in range(size) if tile != idx]


def dragon_tower_eggs(
    server_seed: str, client_seed: str, nonce: int, difficulty: str, cursor: int = 0
) -> List[List[int]]:
    """Dragon Tower: exactly 9 game events, ONE float per tower level
    (doc: "9 game events (one per tower level)" — 2 digests per bet).

    Per level the single float draws the minority tile via
    ``floor(float * size)`` (a 1-draw Fisher-Yates from the level's tile
    range): the skull for easy/medium — eggs are the sorted complement — or
    the egg itself for hard/expert/master.  Rows never contain duplicate
    eggs and multi-egg rows are ALWAYS sorted ascending, e.g. easy
    ``[0, 1, 3]`` = eggs on tiles 1, 2 and 4 (skull on tile 3).
    Levels consume floats sequentially from the bet's stream (level 0 first).
    """
    try:
        count, size = DRAGON_TOWER_LEVEL_MAP[difficulty]
    except KeyError:
        raise ValueError(
            f"difficulty must be one of {sorted(DRAGON_TOWER_LEVEL_MAP)}"
        ) from None
    floats = generate_floats(
        server_seed, client_seed, nonce, cursor, EVENT_COUNTS["dragon_tower"]
    )
    return [_dragon_tower_row(f, count, size) for f in floats]


def scarab_spin_stops(floats: Sequence[float]) -> List[int]:
    """Scarab Spin / Tome of Life: float x reel length -> each reel's central
    stop position.  Reels: 30, 30, 30, 30, 41 outcomes (5 events per spin)."""
    if len(floats) != len(SCARAB_SPIN_REELS):
        raise ValueError(f"scarab spin needs {len(SCARAB_SPIN_REELS)} floats")
    return [
        math.floor(f * reel) for f, reel in zip(floats, SCARAB_SPIN_REELS)
    ]


def scarab_spin(
    server_seed: str, client_seed: str, nonce: int, cursor: int = 0
) -> List[int]:
    """Seed-level Scarab Spin / Tome of Life base spin (5 reel stops)."""
    floats = generate_floats(
        server_seed, client_seed, nonce, cursor, EVENT_COUNTS["scarab_spin"]
    )
    return scarab_spin_stops(floats)


def blue_samurai_symbols(
    floats: Sequence[float], reel_weights: Sequence[Sequence[float]]
) -> List[int]:
    """Blue Samurai: one weighted (fitness-proportionate) symbol pick per
    float, moving down the reels left to right; ``reel_weights[i]`` is the
    weight table for the tile float ``i`` lands on (outer 2 reels use a
    different probability set than the inner 3 — tables NOT published by
    Stake, so the caller supplies them).  Regular/bonus spins use 18 floats,
    special spins 12 (outer reels disabled); a float assigned to a tile with
    a stuck samurai is discarded unused — implement that by omitting the
    tile's entry from both sequences.
    """
    if len(floats) != len(reel_weights):
        raise ValueError("need exactly one weight table per float")
    return [weighted_index(f, w) for f, w in zip(floats, reel_weights)]


# ---------------------------------------------------------------------------
# 2. Bulk path — the SAME provably-fair stream, vectorized
# ---------------------------------------------------------------------------

_TWO32 = float(1 << 32)
# Blocks needing at least this many digests are fanned out across worker
# processes (same digests, computed in parallel nonce sub-ranges — output is
# byte-identical to the serial path by construction).
_PARALLEL_MIN_DIGESTS = 400_000


def _digest_block(
    key: bytes, prefix: bytes, nonce0: int, count: int, n_digests: int
) -> bytes:
    """Serial HMAC digest block: bets nonce0..nonce0+count-1, rounds 0..n-1."""
    base = hmac.new(key, digestmod=hashlib.sha256)
    out = bytearray()
    for n in range(nonce0, nonce0 + count):
        mid = prefix + b"%d:" % n
        for r in range(n_digests):
            h = base.copy()
            h.update(mid + b"%d" % r)
            out += h.digest()
    return bytes(out)


def _digest_block_star(args: Tuple[bytes, bytes, int, int, int]) -> bytes:
    return _digest_block(*args)


# Per-chunk float64 budget for internal chunking (~64 MB of floats per chunk;
# peak whole-call memory measured via tracemalloc: keno_hits(1M) 378 MB,
# video_poker_decks(150k) 196 MB — see _fisher_yates_matrix docstring).
_CHUNK_FLOAT_BUDGET = 8_000_000
_PROGRESS_MIN_BETS = 2_000_000


class BulkRng:
    """Vectorized provably-fair stream — one bet per nonce, verifiable rows.

    NOT a statistical twin: this class evaluates the identical
    ``HMAC_SHA256(serverSeed, f"{clientSeed}:{nonce}:{round}")`` byte stream
    as the scalar path, folds each 4-byte group to the identical
    ``k / 2**32`` float, and applies the identical mapping arithmetic
    (including pop-order partial Fisher-Yates).  Row ``i`` of a call that
    started at nonce ``n0`` is bit-for-bit equal to the scalar helper at
    nonce ``n0 + i`` — so every simulated round carries a full
    ``(server_seed, client_seed, nonce)`` verification triple, and the
    published hash commitment (:attr:`server_seed_hash`) covers the whole
    campaign.

    Nonce accounting mirrors real play: every game method consumes one nonce
    per row (bet), starting at :attr:`nonce_next`; after the call
    :attr:`nonce_next` has advanced by ``size`` and
    :attr:`last_nonce_range` holds the half-open ``(start, stop)`` range the
    call used.

    Large calls are chunked internally (arrays stay well under 500 MB) and
    print progress for campaigns of 2M+ bets.

    Throughput (measured on this shared 4-core container): ~0.43M digests/s
    serial, ~1.0-1.7M digests/s with the default process fan-out — real play
    consumes one digest per one-float bet, so a 12M-round dice/limbo/roulette
    campaign takes ~8-18 s (serial: ~30 s).  Parallel and serial output are
    byte-identical; set ``workers=1`` to force the serial path.
    """

    def __init__(
        self,
        server_seed: Optional[str] = None,
        client_seed: str = "spinquest",
        nonce_start: int = 0,
        workers: Optional[int] = None,
    ) -> None:
        if server_seed is None:
            # Same form Stake generates: random 64-character hex string.
            server_seed = secrets.token_hex(32)
        self.server_seed = server_seed
        self.client_seed = client_seed
        self.nonce_start = _check_nonce(nonce_start)
        self.nonce_next = self.nonce_start
        self.last_nonce_range: Tuple[int, int] = (self.nonce_start, self.nonce_start)
        # workers: process count for large blocks (None = one per CPU;
        # 1 = always serial).  Parallel and serial output are byte-identical.
        self.workers = os.cpu_count() or 1 if workers is None else max(1, workers)
        self._key = server_seed.encode("utf-8")
        self._msg_prefix = client_seed.encode("utf-8") + b":"

    @property
    def server_seed_hash(self) -> str:
        """SHA-256 commitment of the server seed (publish before simulating)."""
        return hash_server_seed(self.server_seed)

    def verification_params(self) -> Dict[str, object]:
        """Everything needed to verify the campaign externally."""
        return {
            "server_seed": self.server_seed,
            "server_seed_hash": self.server_seed_hash,
            "client_seed": self.client_seed,
            "nonce_start": self.nonce_start,
            "nonce_next": self.nonce_next,
            "last_nonce_range": self.last_nonce_range,
        }

    def verify_floats(self, nonce: int, count: int) -> List[float]:
        """Scalar-path floats for one bet of this campaign — for spot checks."""
        return generate_floats(self.server_seed, self.client_seed, nonce, 0, count)

    # --- stream primitives --------------------------------------------------

    def _take_nonces(self, size: int) -> int:
        if size < 0:
            raise ValueError("size must be >= 0")
        start = self.nonce_next
        self.nonce_next = start + size
        self.last_nonce_range = (start, self.nonce_next)
        return start

    def _float_block(self, nonce0: int, size: int, floats_per_bet: int) -> np.ndarray:
        """(size, floats_per_bet) floats: bet b = nonce0+b, digests round 0..r-1.

        Bit-exact to the scalar path: HMAC-SHA256 digests are concatenated per
        bet and each big-endian 4-byte group is divided by 2**32 (equal to the
        published ``sum(b_i / 256**(i+1))`` — the 4-term sum is exact in
        float64).
        """
        n_digests = digests_for_events(floats_per_bet)
        if self.workers > 1 and size * n_digests >= _PARALLEL_MIN_DIGESTS:
            from concurrent.futures import ProcessPoolExecutor

            # Over-split (4 jobs per worker) so a slow worker cannot stall
            # the whole block; order is preserved by ex.map, so the joined
            # bytes are identical to the serial stream.
            step = max(1, -(-size // (self.workers * 4)))
            jobs = [
                (self._key, self._msg_prefix, nonce0 + off, min(step, size - off), n_digests)
                for off in range(0, size, step)
            ]
            with ProcessPoolExecutor(self.workers) as ex:
                out = b"".join(ex.map(_digest_block_star, jobs))
        else:
            out = _digest_block(self._key, self._msg_prefix, nonce0, size, n_digests)
        raw = np.frombuffer(out, dtype=np.uint8)
        raw = raw.reshape(size, n_digests * BYTES_PER_DIGEST)
        raw = np.ascontiguousarray(raw[:, : floats_per_bet * BYTES_PER_FLOAT])
        k = raw.view(">u4").astype(np.float64)
        return k / _TWO32

    def _chunks(self, size: int, floats_per_bet: int) -> Iterator[Tuple[int, int]]:
        """Yield (offset, chunk_size) keeping per-chunk arrays bounded, with
        progress output for large campaigns."""
        chunk = max(1, _CHUNK_FLOAT_BUDGET // max(1, floats_per_bet))
        show = size >= _PROGRESS_MIN_BETS and size > chunk
        done = 0
        while done < size:
            step = min(chunk, size - done)
            yield done, step
            done += step
            if show:
                print(f"BulkRng: {done:,}/{size:,} bets", flush=True)

    def floats(self, size: int) -> np.ndarray:
        """(size,) floats — one bet (nonce) per float, the single-event games'
        stream (dice/limbo/roulette/wheel/cards/gems all read float 0)."""
        return self.float_matrix(size, 1)[:, 0]

    def float_matrix(self, size: int, floats_per_bet: int) -> np.ndarray:
        """(size, floats_per_bet) floats — one bet per row, consuming ``size``
        nonces; row i is bit-equal to
        ``generate_floats(server, client, nonce0 + i, 0, floats_per_bet)``."""
        if floats_per_bet < 1:
            raise ValueError("floats_per_bet must be >= 1")
        nonce0 = self._take_nonces(size)
        out = np.empty((size, floats_per_bet), dtype=np.float64)
        for off, step in self._chunks(size, floats_per_bet):
            out[off:off + step] = self._float_block(nonce0 + off, step, floats_per_bet)
        return out

    def indices(self, outcome_count: int, size: int) -> np.ndarray:
        """floor(float * outcomes) for ``size`` bets (1 float each)."""
        return np.floor(self.floats(size) * outcome_count).astype(np.int64)

    @staticmethod
    def _fisher_yates_matrix(floats2d: np.ndarray, pool_size: int) -> np.ndarray:
        """Vectorized partial Fisher-Yates, identical to the scalar
        ``remaining.pop(floor(f * len(remaining)))`` (pop-order, NOT
        swap-order): draw j scales column j by (pool_size - j) and removal
        shifts later elements left, exactly like list.pop.

        Memory: measured (tracemalloc) whole-call peaks with the default
        chunking are 378 MB for ``keno_hits(1_000_000)`` and 196 MB for
        ``video_poker_decks(150_000)`` — under the 500 MB budget because
        every caller goes through :meth:`_chunks` (~8M floats per chunk).
        """
        size, draws = floats2d.shape
        if draws > pool_size:
            raise ValueError(
                f"cannot draw {draws} without replacement from a pool of {pool_size}"
            )
        pool = np.broadcast_to(
            np.arange(pool_size, dtype=np.int16), (size, pool_size)
        ).copy()
        out = np.empty((size, draws), dtype=np.int64)
        rows = np.arange(size)
        for j in range(draws):
            n_rem = pool_size - j
            idx = np.floor(floats2d[:, j] * n_rem).astype(np.int64)
            out[:, j] = pool[rows, idx]
            if n_rem > 1:
                active = pool[:, :n_rem]
                keep = np.arange(n_rem - 1)[None, :] < idx[:, None]
                pool[:, : n_rem - 1] = np.where(keep, active[:, :-1], active[:, 1:])
        return out

    def draws_without_replacement(
        self, pool_size: int, draw_count: int, size: int
    ) -> np.ndarray:
        """(size, draw_count) matrix of distinct indices in [0, pool_size),
        one bet per row, ``draw_count`` floats per bet, partial Fisher-Yates —
        row-identical to :func:`fisher_yates_draws` on the scalar floats.
        Raises ValueError if ``draw_count > pool_size`` (no silent
        truncation)."""
        if draw_count > pool_size:
            raise ValueError(
                f"cannot draw {draw_count} without replacement from a pool of {pool_size}"
            )
        nonce0 = self._take_nonces(size)
        out = np.empty((size, draw_count), dtype=np.int64)
        for off, step in self._chunks(size, draw_count):
            block = self._float_block(nonce0 + off, step, draw_count)
            out[off:off + step] = self._fisher_yates_matrix(block, pool_size)
        return out

    # --- per-game events (each row = one bet = one nonce) --------------------

    def cards(self, size: int) -> np.ndarray:
        return self.indices(_DECK, size)

    def gems(self, size: int) -> np.ndarray:
        return self.indices(len(GEMS), size)

    def dice_rolls(self, size: int) -> np.ndarray:
        return np.floor(self.floats(size) * 10001) / 100

    def limbo_crash_points(self, size: int, house_edge: float = 0.99) -> np.ndarray:
        """Same operation order as the scalar port: ``floor((1e8 / (f * 1e8)
        * houseEdge) * 100) / 100`` clamped to >= 1; ``f == 0`` yields ``inf``
        exactly as the published JS does."""
        f = self.floats(size)
        with np.errstate(divide="ignore"):
            float_point = 1e8 / (f * 1e8) * house_edge
        return np.maximum(np.floor(float_point * 100) / 100, 1.0)

    def roulette_pockets(self, size: int) -> np.ndarray:
        return self.indices(37, size)

    def wheel_indices(self, segments: int, size: int) -> np.ndarray:
        return self.indices(segments, size)

    def plinko_directions(self, rows: int, size: int) -> np.ndarray:
        """(size, rows) matrix of 0/1 directions; ``rows`` floats per bet."""
        if not 8 <= rows <= EVENT_COUNTS["plinko"]:
            raise ValueError("plinko rows must be in 8..16")
        return np.floor(self.float_matrix(size, rows) * 2).astype(np.int64)

    def keno_hits(self, size: int) -> np.ndarray:
        """(size, 10) matrix of squares in 1..40 (10 floats per bet)."""
        return (
            self.draws_without_replacement(_KENO_POOL, EVENT_COUNTS["keno"], size) + 1
        )

    def mines_positions(self, mine_count: int, size: int) -> np.ndarray:
        """(size, mine_count) tile indices in 0..24.  As in the doc (and the
        scalar helper), all 24 mine-location events are generated per bet and
        the first ``mine_count`` used."""
        if not 1 <= mine_count <= _MINES_EVENTS:
            raise ValueError("mine_count must be in 1..24")
        nonce0 = self._take_nonces(size)
        out = np.empty((size, mine_count), dtype=np.int64)
        for off, step in self._chunks(size, EVENT_COUNTS["mines"]):
            block = self._float_block(nonce0 + off, step, EVENT_COUNTS["mines"])
            out[off:off + step] = self._fisher_yates_matrix(block, _MINES_TILES)[
                :, :mine_count
            ]
        return out

    def dragon_tower_eggs(self, difficulty: str, size: int) -> np.ndarray:
        """(size, 9, count) egg positions — one bet per row, 9 floats per bet
        (one per tower level, 2 digests).  Level-identical to the scalar
        :func:`dragon_tower_eggs`: ``floor(float * level_size)`` draws the
        minority tile; multi-egg rows are the sorted complement."""
        try:
            count, level_size = DRAGON_TOWER_LEVEL_MAP[difficulty]
        except KeyError:
            raise ValueError(
                f"difficulty must be one of {sorted(DRAGON_TOWER_LEVEL_MAP)}"
            ) from None
        fm = self.float_matrix(size, EVENT_COUNTS["dragon_tower"])
        draws = np.floor(fm * level_size).astype(np.int64)  # (size, 9)
        if count == 1:
            return draws[:, :, None]
        # size - count == 1: complement lookup, rows sorted by construction
        comp = np.array(
            [[t for t in range(level_size) if t != d] for d in range(level_size)],
            dtype=np.int64,
        )
        return comp[draws]

    def scarab_spins(self, size: int) -> np.ndarray:
        """(size, 5) reel stops — one bet per row, 5 floats per bet;
        ``floor(float * reel_length)`` with reels (30, 30, 30, 30, 41)."""
        fm = self.float_matrix(size, EVENT_COUNTS["scarab_spin"])
        reels = np.asarray(SCARAB_SPIN_REELS, dtype=np.float64)
        return np.floor(fm * reels).astype(np.int64)

    def video_poker_decks(self, size: int, cards_needed: int = _DECK) -> np.ndarray:
        """(size, cards_needed) leading cards of Fisher-Yates-shuffled decks.
        As in the doc (and the scalar helper), all 52 deck events are
        generated per bet; ``cards_needed`` only selects returned columns and
        must be in 1..52."""
        if not 1 <= cards_needed <= _DECK:
            raise ValueError("cards_needed must be in 1..52")
        nonce0 = self._take_nonces(size)
        out = np.empty((size, cards_needed), dtype=np.int64)
        for off, step in self._chunks(size, EVENT_COUNTS["video_poker"]):
            block = self._float_block(nonce0 + off, step, EVENT_COUNTS["video_poker"])
            out[off:off + step] = self._fisher_yates_matrix(block, _DECK)[
                :, :cards_needed
            ]
        return out
