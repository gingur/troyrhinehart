"""Tests for spinquest_sim.rng.

Test vectors are derived INDEPENDENTLY from the published Stake spec
(references/stake/core.md) using python's hmac/hashlib and the verbatim
formulas — the reference helpers below intentionally do not touch
spinquest_sim.rng internals, and the hardcoded byte/float/draw vectors were
computed by standalone scripts (scratchpad derive_*.py) that never imported
the module under test.
"""

import hashlib
import hmac
import math

import numpy as np
import pytest

from spinquest_sim import rng

SERVER = "8f9e2b64c1a05d73e6f4a29b8c17d05e3a6b49f2c8d1e07a5b3f6c92d4e18a70"
CLIENT = "spinquest-client"
NONCE = 7


# ---------------------------------------------------------------------------
# Independent reference implementation, straight from the published spec text
# ---------------------------------------------------------------------------

def ref_bytes(server, client, nonce, cursor, n):
    """byteGenerator per the published JS: HMAC_SHA256(key=serverSeed,
    message=f"{clientSeed}:{nonce}:{currentRound}"), currentRound=cursor//32."""
    current_round = cursor // 32
    ccur = cursor - current_round * 32
    out = []
    while len(out) < n:
        digest = hmac.new(
            server.encode(),
            f"{client}:{nonce}:{current_round}".encode(),
            hashlib.sha256,
        ).digest()
        while ccur < 32 and len(out) < n:
            out.append(digest[ccur])
            ccur += 1
        ccur = 0
        current_round += 1
    return out


def ref_floats(server, client, nonce, cursor, count):
    b = ref_bytes(server, client, nonce, cursor, count * 4)
    return [
        sum(b[c * 4 + i] / 256 ** (i + 1) for i in range(4)) for c in range(count)
    ]


def ref_fisher_yates(floats, pool_size):
    pool = list(range(pool_size))
    return [pool.pop(math.floor(f * len(pool))) for f in floats]


def ref_limbo(f, house_edge=0.99):
    """Verbatim port of the published JS, in its exact operation order:
        const floatPoint = 1e8 / (float * 1e8) * houseEdge;
        const crashPoint = Math.floor(floatPoint * 100) / 100;
        const result = Math.max(crashPoint, 1);
    f == 0 divides by zero, which in JS yields Infinity."""
    if f == 0.0:
        return math.inf
    return max(math.floor(1e8 / (f * 1e8) * house_edge * 100) / 100, 1.0)


# ---------------------------------------------------------------------------
# Hardcoded vectors (derived by external scripts; see module docstring)
# ---------------------------------------------------------------------------

DIGEST_ROUND0_HEX = "54c7a69d538f2b25a3753a98e3138c04d7f5206cab193ca06d83f5f2c7c70bc1"
DIGEST_ROUND1_HEX = "a82090d4f473174afbc41c6e0d1cc7b0d5535fd0a97d47015abc1b91efb13822"
FIRST_40_BYTES = [
    84, 199, 166, 157, 83, 143, 43, 37, 163, 117, 58, 152, 227, 19, 140, 4,
    215, 245, 32, 108, 171, 25, 60, 160, 109, 131, 245, 242, 199, 199, 11, 193,
    168, 32, 144, 212, 244, 115, 23, 74,
]
BYTES_CURSOR35 = [212, 244, 115, 23, 74, 251, 196, 28, 110, 13, 28, 199]
FIRST_10_FLOATS = [
    0.33117142994888127, 0.32640332845039666, 0.6385075207799673,
    0.8870170125737786, 0.8435840858146548, 0.668353833258152,
    0.42779481085017323, 0.7803809496108443, 0.6567469136789441,
    0.954881148878485,
]
KENO_HITS = [14, 13, 27, 36, 34, 26, 17, 31, 25, 39]
MINES_ORDER = [8, 7, 16, 22, 20, 15, 10, 19, 14, 24, 23, 0, 17, 11, 4, 21,
               18, 5, 1, 13, 2, 3, 6, 12]
VP_DECK = [17, 16, 33, 46, 43, 34, 21, 40, 31, 50, 51, 2, 41, 29, 14, 47,
           49, 18, 1, 45, 7, 5, 8, 38, 28, 19, 37, 13, 15, 25, 27, 48, 20,
           11, 22, 24, 26, 4, 12, 0, 39, 10, 3, 23, 42, 44, 36, 30, 35, 6,
           32, 9]
SEED_COMMITMENT = "8c46c4afdd4b807c3b1714299e90175e973bcf303d0207f9af853836e35be9b1"

# New-game vectors (scratchpad/derive_vectors_r3.py — hmac/hashlib only):
BACCARAT_VECTOR = [17, 16, 33, 46, 43, 34]
DIAMONDS_VECTOR = ["yellow", "yellow", "cyan", "blue", "orange"]
DP_DEALER = ["yellow", "yellow", "cyan", "blue", "orange"]
DP_PLAYER = ["cyan", "yellow", "orange", "cyan", "blue"]
CARD_DRAWS8 = [17, 16, 33, 46, 43, 34, 22, 40]
# Dragon Tower vectors (scratchpad/derive_dragon_r4.py — hmac/hashlib only):
# 9 floats per bet, ONE per tower level; floor(float * size) draws the
# minority tile (skull for easy/medium -> eggs are the sorted complement;
# egg itself for hard/expert/master).
DRAGON_EASY = [[0, 2, 3], [0, 2, 3], [0, 1, 3], [0, 1, 2], [0, 1, 2],
               [0, 1, 3], [0, 2, 3], [0, 1, 2], [0, 1, 3]]
DRAGON_MEDIUM = [[1, 2], [1, 2], [0, 2], [0, 1], [0, 1], [0, 1], [0, 2],
                 [0, 1], [0, 2]]
DRAGON_HARD = [[0], [0], [1], [1], [1], [1], [0], [1], [1]]
DRAGON_EXPERT = [[0], [0], [1], [2], [2], [2], [1], [2], [1]]
DRAGON_MASTER = [[1], [1], [2], [3], [3], [2], [1], [3], [2]]
# Second, unrelated seed tuple (guards against vectors tuned to one seed):
DRAGON2_SERVER = "0000000000000000000000000000000000000000000000000000000000000001"
DRAGON2_CLIENT = "dt-probe"
DRAGON2_NONCE = 123
DRAGON2_EASY = [[0, 2, 3], [0, 2, 3], [0, 2, 3], [0, 2, 3], [1, 2, 3],
                [0, 1, 2], [0, 1, 3], [0, 1, 2], [0, 2, 3]]
DRAGON2_MEDIUM = [[0, 2], [1, 2], [0, 2], [0, 2], [1, 2], [0, 1], [0, 2],
                  [0, 1], [0, 2]]
SCARAB_VECTOR = [9, 9, 19, 26, 34]

# Limbo adversarial vectors: lattice floats k/2**32 where the published order
# of operations (1e8/(f*1e8)*houseEdge) differs by one floored cent from the
# algebraically equal houseEdge/f, plus random lattice spots and the zero
# float.  Derived by scratchpad/derive_limbo_vectors.py, which never imports
# spinquest_sim.rng.
LIMBO_VECTORS = [
    (0, math.inf),               # published JS: 1e8 / 0 = Infinity
    (1, 4252017623.04),
    (2, 2126008811.52),
    (3, 1417339207.67),          # ULP-divergent vs the naive order
    (6, 708669603.83),           # ULP-divergent
    (9, 472446402.55),           # ULP-divergent
    (12, 354334801.91),          # ULP-divergent
    (18, 236223201.27),          # ULP-divergent
    (24, 177167400.95),          # ULP-divergent
    (36, 118111600.63),          # ULP-divergent
    (48, 88583700.47),           # ULP-divergent
    (25165824, 168.95),          # f = 0.005859375; naive order gives 168.96
    (2746317214, 1.54),
    (478163328, 8.89),
    (107420370, 39.58),
    (3184935164, 1.33),
    (1181241944, 3.59),
    (1051802513, 4.04),
    (2**32 - 1, 1.0),            # clamp: 0.99 / ~1 < 1
]


# ---------------------------------------------------------------------------
# Provably-fair scalar path
# ---------------------------------------------------------------------------

class TestSeedCommitment:
    def test_hardcoded_vector(self):
        assert rng.hash_server_seed(SERVER) == SEED_COMMITMENT

    def test_matches_hashlib(self):
        seed = "ab" * 32
        assert rng.hash_server_seed(seed) == hashlib.sha256(seed.encode()).hexdigest()


class TestByteGenerator:
    def test_first_digest_is_exact_hmac(self):
        got = bytes(rng.generate_bytes(SERVER, CLIENT, NONCE, cursor=0, count=32))
        assert got.hex() == DIGEST_ROUND0_HEX

    def test_round_increments_in_message(self):
        # bytes 32..63 must come from message "...:1"
        got = bytes(rng.generate_bytes(SERVER, CLIENT, NONCE, cursor=32, count=32))
        assert got.hex() == DIGEST_ROUND1_HEX

    def test_first_40_bytes_hardcoded(self):
        assert rng.generate_bytes(SERVER, CLIENT, NONCE, 0, 40) == FIRST_40_BYTES

    def test_cursor_mid_digest(self):
        # cursor=35 -> round 1, offset 3: equals stream[35:47]
        assert rng.generate_bytes(SERVER, CLIENT, NONCE, 35, 12) == BYTES_CURSOR35

    @pytest.mark.parametrize("cursor", [0, 1, 31, 32, 33, 63, 64, 100])
    def test_cursor_equals_offset_into_stream(self, cursor):
        stream = ref_bytes(SERVER, CLIENT, NONCE, 0, cursor + 20)
        assert rng.generate_bytes(SERVER, CLIENT, NONCE, cursor, 20) == stream[cursor:cursor + 20]

    def test_nonce_and_client_change_stream(self):
        base = rng.generate_bytes(SERVER, CLIENT, NONCE, 0, 32)
        assert rng.generate_bytes(SERVER, CLIENT, NONCE + 1, 0, 32) != base
        assert rng.generate_bytes(SERVER, "other-client", NONCE, 0, 32) != base


class TestCursorVsRoundIndex:
    """`cursor` is a BYTE offset in the published code, but Stake's prose
    counts DIGESTS.  round_index addresses digests unambiguously (F4)."""

    @pytest.mark.parametrize("r", [0, 1, 2, 6, 12])
    def test_round_index_is_digest_index(self, r):
        assert rng.generate_bytes(SERVER, CLIENT, NONCE, round_index=r, count=32) == \
            ref_bytes(SERVER, CLIENT, NONCE, r * 32, 32)

    def test_round_index_equals_cursor_times_32(self):
        assert rng.generate_floats(SERVER, CLIENT, NONCE, round_index=1, count=8) == \
            rng.generate_floats(SERVER, CLIENT, NONCE, cursor=32, count=8)

    def test_both_given_raises(self):
        with pytest.raises(ValueError):
            rng.generate_bytes(SERVER, CLIENT, NONCE, cursor=1, round_index=1)

    def test_cursor_one_is_not_second_digest(self):
        # The trap round_index exists to avoid: cursor=1 is byte 1 of digest 0.
        assert rng.generate_bytes(SERVER, CLIENT, NONCE, cursor=1, count=4) == \
            FIRST_40_BYTES[1:5]


class TestFloats:
    def test_first_10_hardcoded(self):
        got = rng.generate_floats(SERVER, CLIENT, NONCE, 0, 10)
        assert got == FIRST_10_FLOATS  # exact: same fp operations

    def test_matches_reference_across_digest_boundary(self):
        # 20 floats = 80 bytes = 2.5 digests
        got = rng.generate_floats(SERVER, CLIENT, NONCE, 0, 20)
        assert got == ref_floats(SERVER, CLIENT, NONCE, 0, 20)

    def test_float_formula_from_known_bytes(self):
        b = FIRST_40_BYTES[:4]
        expected = b[0] / 256 + b[1] / 256**2 + b[2] / 256**3 + b[3] / 256**4
        assert rng.generate_floats(SERVER, CLIENT, NONCE, 0, 1)[0] == expected

    def test_four_term_sum_equals_bigendian_u32_over_2_32(self):
        # The identity the vectorized bulk path relies on, checked against
        # the published 4-term formula for every possible leading byte.
        for b0 in range(256):
            chunk = [b0, 173, 41, 255]
            s = sum(chunk[i] / 256 ** (i + 1) for i in range(4))
            k = (chunk[0] << 24) | (chunk[1] << 16) | (chunk[2] << 8) | chunk[3]
            assert s == k / 2**32

    def test_range_and_granularity(self):
        floats = rng.generate_floats(SERVER, "x", 0, 0, 64)
        for f in floats:
            assert 0.0 <= f < 1.0
            assert (f * 2**32) == int(f * 2**32)  # exact multiple of 2**-32


class TestEventMapping:
    def test_float_to_index_floors(self):
        assert rng.float_to_index(0.999999, 52) == 51
        assert rng.float_to_index(0.0, 52) == 0
        assert rng.float_to_index(51.5 / 52, 52) == 51

    def test_card_helpers(self):
        f0 = FIRST_10_FLOATS[0]
        assert rng.card_index(f0) == 17
        assert len(rng.CARDS) == 52
        assert rng.CARDS[0] == "♦2"
        assert rng.CARDS[51] == "♣A"
        assert rng.CARDS[35] == "♣10"  # ranks 2..A, suits ♦♥♠♣ within rank
        assert rng.card_name(17) == rng.CARDS[17]
        assert rng.cards_from_floats(FIRST_10_FLOATS) == [
            math.floor(f * 52) for f in FIRST_10_FLOATS
        ]

    def test_scalar_events_from_first_float(self):
        f0 = FIRST_10_FLOATS[0]
        assert rng.dice_roll(f0) == 33.12
        assert rng.limbo_crash_point(f0) == 2.98
        assert rng.roulette_pocket(f0) == 12
        assert rng.wheel_index(f0, 50) == 16
        assert rng.plinko_directions(FIRST_10_FLOATS[:8]) == [0, 0, 1, 1, 1, 1, 0, 1]

    def test_dice_bounds(self):
        assert rng.dice_roll(0.0) == 0.0
        assert rng.dice_roll(1 - 2**-32) == 100.0

    def test_dice_floor_is_deliberate_divergence_from_verbatim_snippet(self):
        """F9: the published snippet reads `(float * 10001) / 100` with no
        floor, but the page's prose demands 10,001 discrete outcomes
        (00.00-100.00 in cents) and its general rule floors every index.
        This test pins the floored form so nobody "fixes" it back."""
        f = FIRST_10_FLOATS[0]
        unfloored_verbatim = (f * 10001) / 100
        assert rng.dice_roll(f) == math.floor(f * 10001) / 100
        assert rng.dice_roll(f) != unfloored_verbatim  # they genuinely differ
        # every result lands exactly on a cent
        for g in FIRST_10_FLOATS:
            r = rng.dice_roll(g)
            assert r == round(r, 2)

    def test_limbo_clamps_to_one(self):
        assert rng.limbo_crash_point(0.999) == 1.0  # 0.99/0.999 < 1


class TestLimbo:
    """Independent checks of the published crash-point formula, including the
    ULP-sensitive operation order and the Infinity edge case."""

    @pytest.mark.parametrize("k,expected", LIMBO_VECTORS)
    def test_hardcoded_lattice_vectors(self, k, expected):
        assert rng.limbo_crash_point(k / 2**32) == expected

    def test_zero_float_is_infinity(self):
        assert rng.limbo_crash_point(0.0) == math.inf

    def test_operation_order_matches_published_js(self):
        # ULP case: the naive houseEdge/f order gets the cent wrong here.
        assert rng.limbo_crash_point(0.005859375) == 168.95
        naive = math.floor(0.99 / 0.005859375 * 100) / 100
        assert naive == 168.96  # proves the orders genuinely diverge

    def test_matches_reference_on_random_lattice(self):
        ks = np.random.default_rng(20240823).integers(0, 2**32, 200_000, dtype=np.uint64)
        for k in ks[:5000]:  # scalar spot check
            f = float(k) / 2**32
            assert rng.limbo_crash_point(f) == ref_limbo(f)

    def test_matches_reference_from_stream_floats(self):
        for i, f in enumerate(ref_floats(SERVER, CLIENT, NONCE, 0, 64)):
            assert rng.limbo_crash_point(f) == ref_limbo(f), i

    def test_house_edge_parameter(self):
        f = 0.5
        assert rng.limbo_crash_point(f, 0.99) == ref_limbo(f, 0.99)
        assert rng.limbo_crash_point(f, 1.0) == ref_limbo(f, 1.0) == 2.0


class TestNonceTypes:
    """JS coerces nonce via template literal ('7.0' -> '7', true -> 'true');
    Python would render '7.0'/'True' and silently fork the stream.  The port
    refuses non-integer nonces but accepts numpy integers (F7)."""

    def test_float_nonce_rejected(self):
        with pytest.raises(TypeError):
            rng.generate_bytes(SERVER, CLIENT, 7.0, 0, 4)

    def test_bool_nonce_rejected(self):
        with pytest.raises(TypeError):
            rng.generate_bytes(SERVER, CLIENT, True, 0, 4)

    def test_numpy_bool_rejected(self):
        with pytest.raises(TypeError):
            rng.generate_bytes(SERVER, CLIENT, np.bool_(True), 0, 4)

    def test_str_nonce_rejected(self):
        with pytest.raises(TypeError):
            rng.generate_floats(SERVER, CLIENT, "7", 0, 1)

    def test_int_nonce_accepted(self):
        assert len(rng.generate_bytes(SERVER, CLIENT, 7, 0, 4)) == 4

    @pytest.mark.parametrize("np_type", [np.int64, np.int32, np.uint64, np.uint32])
    def test_numpy_integer_nonce_accepted_and_identical(self, np_type):
        assert rng.generate_bytes(SERVER, CLIENT, np_type(7), 0, 8) == \
            ref_bytes(SERVER, CLIENT, 7, 0, 8)

    def test_bulk_nonce_start_numpy_integer(self):
        b = rng.BulkRng(SERVER, CLIENT, nonce_start=np.int64(5))
        assert b.nonce_start == 5 and isinstance(b.nonce_start, int)


class TestGemsAndCursorTable:
    def test_gems_published_order(self):
        assert rng.GEMS == ["green", "purple", "yellow", "red", "cyan", "orange", "blue"]

    def test_gem_index_floors_by_seven(self):
        assert rng.gem_index(0.0) == 0
        assert rng.gem_index(1 - 2**-32) == 6
        f0 = FIRST_10_FLOATS[0]
        assert rng.gem_index(f0) == math.floor(f0 * 7)

    def test_gems_from_floats(self):
        names = rng.gems_from_floats(FIRST_10_FLOATS)
        assert names == [rng.GEMS[math.floor(f * 7)] for f in FIRST_10_FLOATS]

    def test_cursor_increments_match_doc_table_verbatim(self):
        """The doc's table (slots included) plus the game-events-page games
        the round-3 review found missing: dragon_tower (9 events -> 2
        digests), scarab_spin (5 -> 1), blue_samurai (18 -> 3 regular,
        12 -> 2 special)."""
        expected = {"dice": 1, "limbo": 1, "wheel": 1, "baccarat": 1,
                    "roulette": 1, "diamonds": 1, "keno": 2, "plinko": 2,
                    "diamond_poker": 2, "mines": 3, "video_poker": 7,
                    "dragon_tower": 2, "scarab_spin": 1,
                    "blue_samurai": 3, "blue_samurai_special": 2,
                    "hilo": 13, "blackjack": 13, "slots": None}
        assert rng.CURSOR_INCREMENTS == expected

    def test_event_counts_cover_all_fixed_length_games(self):
        """Round 3's root cause: dragon_tower/scarab_spin/blue_samurai were
        absent from BOTH tables, so the LIVE-table safeguard never covered
        them.  Every fixed-length game on the game-events page must appear."""
        expected = {"dice": 1, "limbo": 1, "wheel": 1, "roulette": 1,
                    "diamonds": 5, "baccarat": 6, "keno": 10, "plinko": 16,
                    "diamond_poker": 10, "mines": 24, "video_poker": 52,
                    "dragon_tower": 9, "scarab_spin": 5,
                    "blue_samurai": 18, "blue_samurai_special": 12}
        assert rng.EVENT_COUNTS == expected
        # aliases stay tied to the LIVE table
        assert rng.BLUE_SAMURAI_FLOATS_REGULAR == rng.EVENT_COUNTS["blue_samurai"]
        assert rng.BLUE_SAMURAI_FLOATS_SPECIAL == \
            rng.EVENT_COUNTS["blue_samurai_special"]
        assert len(rng.SCARAB_SPIN_REELS) == rng.EVENT_COUNTS["scarab_spin"]
        assert rng.DRAGON_TOWER_ROWS == rng.EVENT_COUNTS["dragon_tower"]

    def test_cursor_increments_computed_from_live_event_counts(self):
        """For fixed-length games the table values are DERIVED from the same
        EVENT_COUNTS the code consumes — the table cannot drift (F2)."""
        for game, events in rng.EVENT_COUNTS.items():
            assert rng.CURSOR_INCREMENTS[game] == rng.digests_for_events(events), game

    def test_blackjack_reservation_vs_actual_consumption(self):
        """Doc reserves 13 digests for hilo/blackjack; a full 52-card draw
        actually reads ceil(52*4/32) = 7 — both facts, stated and tested."""
        assert rng.CURSOR_INCREMENTS["blackjack"] == 13
        assert rng.digests_for_events(52) == 7
        assert rng.digests_for_events(52) <= rng.CURSOR_INCREMENTS["blackjack"]
        # 13 digests hold 104 floats — enough for the 52 possible events
        assert rng.CURSOR_INCREMENTS["hilo"] * 8 >= 52

    def test_digests_for_events(self):
        assert [rng.digests_for_events(n) for n in (1, 8, 9, 10, 16, 24, 52)] == \
            [1, 1, 2, 2, 2, 3, 7]

    def test_fisher_yates_matches_reference(self):
        floats = ref_floats(SERVER, CLIENT, NONCE, 0, 24)
        assert rng.fisher_yates_draws(floats, 25) == ref_fisher_yates(floats, 25)

    def test_fisher_yates_no_duplicates_and_range(self):
        floats = ref_floats(SERVER, "fy", 3, 0, 52)
        draws = rng.fisher_yates_draws(floats, 52)
        assert sorted(draws) == list(range(52))

    def test_fisher_yates_overdraw_raises(self):
        with pytest.raises(ValueError):
            rng.fisher_yates_draws([0.1, 0.2, 0.3], 2)

    def test_keno_hardcoded(self):
        assert rng.keno_hits(SERVER, CLIENT, NONCE) == KENO_HITS
        assert all(1 <= h <= 40 for h in KENO_HITS)
        assert len(set(KENO_HITS)) == 10

    def test_mines_hardcoded_and_truncation(self):
        assert rng.mines_positions(SERVER, CLIENT, NONCE, 24) == MINES_ORDER
        assert rng.mines_positions(SERVER, CLIENT, NONCE, 3) == MINES_ORDER[:3]
        assert sorted(MINES_ORDER) == sorted(set(MINES_ORDER))
        assert all(0 <= m <= 24 for m in MINES_ORDER)
        with pytest.raises(ValueError):
            rng.mines_positions(SERVER, CLIENT, NONCE, 25)

    def test_video_poker_hardcoded(self):
        deck = rng.video_poker_deck(SERVER, CLIENT, NONCE)
        assert deck == VP_DECK
        assert sorted(deck) == list(range(52))


class TestNewGameMappings:
    """The six mappings core.md publishes that round 2 flagged as missing (F3)."""

    def test_card_draws_hardcoded(self):
        assert rng.card_draws(SERVER, CLIENT, NONCE, 8) == CARD_DRAWS8

    def test_card_draws_matches_reference_any_count(self):
        for count in (1, 2, 6, 13, 52):
            expected = [math.floor(f * 52)
                        for f in ref_floats(SERVER, CLIENT, NONCE, 0, count)]
            assert rng.card_draws(SERVER, CLIENT, NONCE, count) == expected

    def test_baccarat_six_events(self):
        assert rng.baccarat_cards(SERVER, CLIENT, NONCE) == BACCARAT_VECTOR
        assert len(BACCARAT_VECTOR) == 6  # doc: "only ever needs 6 game events"

    def test_diamonds_five_gems(self):
        assert rng.diamonds_gems(SERVER, CLIENT, NONCE) == DIAMONDS_VECTOR
        assert len(DIAMONDS_VECTOR) == 5

    def test_diamond_poker_dealer_first(self):
        dealer, player = rng.diamond_poker_hands(SERVER, CLIENT, NONCE)
        assert dealer == DP_DEALER  # FIRST 5 events -> dealer (doc order)
        assert player == DP_PLAYER
        # dealer hand == the Diamonds 5-gem draw for the same bet (same stream)
        assert dealer == DIAMONDS_VECTOR

    def test_dragon_tower_level_map_published_values(self):
        assert rng.DRAGON_TOWER_LEVEL_MAP == {
            "easy": (3, 4), "medium": (2, 3), "hard": (1, 2),
            "expert": (1, 3),  # published as "count1" [sic]
            "master": (1, 4),
        }
        assert rng.DRAGON_TOWER_ROWS == 9

    @pytest.mark.parametrize("difficulty,expected", [
        ("easy", DRAGON_EASY), ("medium", DRAGON_MEDIUM), ("hard", DRAGON_HARD),
        ("expert", DRAGON_EXPERT), ("master", DRAGON_MASTER),
    ])
    def test_dragon_tower_hardcoded(self, difficulty, expected):
        assert rng.dragon_tower_eggs(SERVER, CLIENT, NONCE, difficulty) == expected

    @pytest.mark.parametrize("difficulty,expected", [
        ("easy", DRAGON2_EASY), ("medium", DRAGON2_MEDIUM),
    ])
    def test_dragon_tower_hardcoded_second_seed(self, difficulty, expected):
        got = rng.dragon_tower_eggs(
            DRAGON2_SERVER, DRAGON2_CLIENT, DRAGON2_NONCE, difficulty
        )
        assert got == expected

    def test_dragon_tower_matches_reference_all_difficulties(self):
        """9 game events per bet, ONE float per tower level (core.md L393).
        min(count, size - count) == 1 for every difficulty, so the single
        float draws the minority tile: floor(f * size) is the skull for
        easy/medium (eggs = sorted complement) or the egg itself for
        hard/expert/master."""
        floats = ref_floats(SERVER, CLIENT, NONCE, 0, 9)  # exactly 9 events
        for difficulty, (count, size) in rng.DRAGON_TOWER_LEVEL_MAP.items():
            assert min(count, size - count) == 1
            expected = []
            for f in floats:
                idx = math.floor(f * size)
                if count == 1:
                    expected.append([idx])
                else:
                    expected.append([t for t in range(size) if t != idx])
            got = rng.dragon_tower_eggs(SERVER, CLIENT, NONCE, difficulty)
            assert got == expected
            assert len(got) == 9
            for row in got:
                assert len(row) == len(set(row)) == count  # no duplicate eggs
                assert all(0 <= egg < size for egg in row)

    def test_dragon_tower_consumes_exactly_nine_floats_two_digests(self):
        """The identifying probe from round 3: a real Stake verifier reads 9
        floats (2 digests) per Dragon Tower bet at EVERY difficulty.  Feeding
        a stream whose 3rd digest differs must not change any row."""
        assert rng.EVENT_COUNTS["dragon_tower"] == 9
        assert rng.CURSOR_INCREMENTS["dragon_tower"] == 2
        assert rng.digests_for_events(9) == 2
        # single-draw Fisher-Yates == floor(f * size): the one-float row rule
        # is the doc's own Fisher-Yates primitive with one draw
        for f in ref_floats(SERVER, CLIENT, NONCE, 0, 9):
            for size in (2, 3, 4):
                assert ref_fisher_yates([f], size) == [math.floor(f * size)]

    def test_dragon_tower_rows_always_sorted(self):
        """Reference rows are 100% sorted (complement of one skull), not the
        1/6 chance rate of an order-preserving 3-draw — the tell that
        outed round 3's implementation."""
        for nonce in range(40):
            for difficulty in rng.DRAGON_TOWER_LEVEL_MAP:
                rows = rng.dragon_tower_eggs(SERVER, CLIENT, nonce, difficulty)
                assert all(row == sorted(row) for row in rows)

    def test_dragon_tower_easy_skull_is_drawn_tile(self):
        """Easy: the missing tile (skull) is exactly floor(f * 4), per level."""
        floats = ref_floats(SERVER, CLIENT, NONCE, 0, 9)
        rows = rng.dragon_tower_eggs(SERVER, CLIENT, NONCE, "easy")
        for f, row in zip(floats, rows):
            skull = (set(range(4)) - set(row)).pop()
            assert skull == math.floor(f * 4)

    def test_dragon_tower_bad_difficulty(self):
        with pytest.raises(ValueError):
            rng.dragon_tower_eggs(SERVER, CLIENT, NONCE, "nightmare")

    def test_scarab_reels_and_hardcoded_spin(self):
        assert rng.SCARAB_SPIN_REELS == (30, 30, 30, 30, 41)
        assert rng.scarab_spin(SERVER, CLIENT, NONCE) == SCARAB_VECTOR
        for stop, reel in zip(SCARAB_VECTOR, rng.SCARAB_SPIN_REELS):
            assert 0 <= stop < reel

    def test_scarab_stops_matches_reference(self):
        floats = ref_floats(SERVER, CLIENT, NONCE, 0, 5)
        assert rng.scarab_spin_stops(floats) == [
            math.floor(f * r) for f, r in zip(floats, (30, 30, 30, 30, 41))
        ]
        with pytest.raises(ValueError):
            rng.scarab_spin_stops(floats[:4])

    def test_weighted_index_fitness_proportionate(self):
        # weights [1, 1, 2]: boundaries at 0.25 and 0.5 of total mass
        assert rng.weighted_index(0.0, [1, 1, 2]) == 0
        assert rng.weighted_index(0.2499, [1, 1, 2]) == 0
        assert rng.weighted_index(0.25, [1, 1, 2]) == 1   # strict >
        assert rng.weighted_index(0.4999, [1, 1, 2]) == 1
        assert rng.weighted_index(0.5, [1, 1, 2]) == 2
        assert rng.weighted_index(1 - 2**-32, [1, 1, 2]) == 2
        # zero-weight symbols are never selected
        assert rng.weighted_index(0.0, [0, 5]) == 1

    def test_weighted_index_matches_cumsum_reference(self):
        weights = [3.5, 0.0, 1.25, 7.0, 0.5, 2.75]
        total = sum(weights)
        cum = np.cumsum(weights)
        for f in ref_floats(SERVER, CLIENT, NONCE, 0, 64):
            expected = int(np.searchsorted(cum, f * total, side="right"))
            assert rng.weighted_index(f, weights) == min(expected, len(weights) - 1)

    def test_weighted_index_validation(self):
        with pytest.raises(ValueError):
            rng.weighted_index(0.5, [])
        with pytest.raises(ValueError):
            rng.weighted_index(0.5, [1, -1])
        with pytest.raises(ValueError):
            rng.weighted_index(0.5, [0, 0])

    def test_blue_samurai_symbols_and_budgets(self):
        assert rng.BLUE_SAMURAI_FLOATS_REGULAR == 18
        assert rng.BLUE_SAMURAI_FLOATS_SPECIAL == 12
        floats = ref_floats(SERVER, CLIENT, NONCE, 0, 18)
        tables = [[1, 2, 3]] * 18
        got = rng.blue_samurai_symbols(floats, tables)
        assert got == [rng.weighted_index(f, [1, 2, 3]) for f in floats]
        with pytest.raises(ValueError):
            rng.blue_samurai_symbols(floats, tables[:-1])


# ---------------------------------------------------------------------------
# Bulk path — vectorized provably-fair stream (F1)
# ---------------------------------------------------------------------------

BULK_CLIENT = "bulk-client"


class TestBulkIsProvablyFair:
    """Every BulkRng row must be bit-for-bit reproducible from its
    (server_seed, client_seed, nonce) triple via the INDEPENDENT reference
    implementation — the property round 2 said the whole module was missing."""

    def test_exposes_verification_identity(self):
        b = rng.BulkRng(SERVER, BULK_CLIENT, nonce_start=100)
        assert b.server_seed == SERVER
        assert b.client_seed == BULK_CLIENT
        assert b.nonce_start == 100
        assert b.server_seed_hash == hashlib.sha256(SERVER.encode()).hexdigest()
        p = b.verification_params()
        assert p["server_seed"] == SERVER and p["nonce_start"] == 100

    def test_default_server_seed_is_64_hex_and_committed(self):
        b = rng.BulkRng()
        assert len(b.server_seed) == 64
        int(b.server_seed, 16)  # valid hex
        assert b.server_seed_hash == hashlib.sha256(b.server_seed.encode()).hexdigest()

    def test_floats_bitexact_vs_independent_reference(self):
        b = rng.BulkRng(SERVER, BULK_CLIENT, nonce_start=0)
        got = b.floats(200)
        for i in range(200):
            assert got[i] == ref_floats(SERVER, BULK_CLIENT, i, 0, 1)[0], i

    def test_float_matrix_bitexact_vs_independent_reference(self):
        b = rng.BulkRng(SERVER, BULK_CLIENT, nonce_start=1000)
        got = b.float_matrix(40, 24)  # 3 digests per bet
        for i in range(40):
            assert got[i].tolist() == ref_floats(SERVER, BULK_CLIENT, 1000 + i, 0, 24), i

    def test_nonce_accounting_one_bet_per_row(self):
        b = rng.BulkRng(SERVER, BULK_CLIENT, nonce_start=50)
        b.floats(10)
        assert b.last_nonce_range == (50, 60)
        b.keno_hits(5)
        assert b.last_nonce_range == (60, 65)
        assert b.nonce_next == 65
        # the next call's rows verify at nonces 65, 66, ...
        rolls = b.dice_rolls(3)
        for i in range(3):
            f = ref_floats(SERVER, BULK_CLIENT, 65 + i, 0, 1)[0]
            assert rolls[i] == math.floor(f * 10001) / 100

    def test_every_game_row_verifies_against_reference(self):
        b = rng.BulkRng(SERVER, BULK_CLIENT, nonce_start=0)
        n = 30

        cards = b.cards(n)
        for i, n0 in [(i, b.last_nonce_range[0]) for i in range(n)]:
            f = ref_floats(SERVER, BULK_CLIENT, n0 + i, 0, 1)[0]
            assert cards[i] == math.floor(f * 52)

        gems = b.gems(n); n0 = b.last_nonce_range[0]
        rolls = None
        for i in range(n):
            f = ref_floats(SERVER, BULK_CLIENT, n0 + i, 0, 1)[0]
            assert gems[i] == math.floor(f * 7)

        rolls = b.dice_rolls(n); n0 = b.last_nonce_range[0]
        for i in range(n):
            f = ref_floats(SERVER, BULK_CLIENT, n0 + i, 0, 1)[0]
            assert rolls[i] == math.floor(f * 10001) / 100

        crash = b.limbo_crash_points(n); n0 = b.last_nonce_range[0]
        for i in range(n):
            f = ref_floats(SERVER, BULK_CLIENT, n0 + i, 0, 1)[0]
            assert crash[i] == ref_limbo(f)

        pockets = b.roulette_pockets(n); n0 = b.last_nonce_range[0]
        for i in range(n):
            f = ref_floats(SERVER, BULK_CLIENT, n0 + i, 0, 1)[0]
            assert pockets[i] == math.floor(f * 37)

        for segments in (10, 20, 30, 40, 50):
            w = b.wheel_indices(segments, 10); n0 = b.last_nonce_range[0]
            for i in range(10):
                f = ref_floats(SERVER, BULK_CLIENT, n0 + i, 0, 1)[0]
                assert w[i] == math.floor(f * segments)

        plinko = b.plinko_directions(16, n); n0 = b.last_nonce_range[0]
        for i in range(n):
            fs = ref_floats(SERVER, BULK_CLIENT, n0 + i, 0, 16)
            assert plinko[i].tolist() == [math.floor(f * 2) for f in fs]

        keno = b.keno_hits(n); n0 = b.last_nonce_range[0]
        for i in range(n):
            fs = ref_floats(SERVER, BULK_CLIENT, n0 + i, 0, 10)
            assert keno[i].tolist() == [t + 1 for t in ref_fisher_yates(fs, 40)]

        mines = b.mines_positions(3, n); n0 = b.last_nonce_range[0]
        for i in range(n):
            fs = ref_floats(SERVER, BULK_CLIENT, n0 + i, 0, 24)
            assert mines[i].tolist() == ref_fisher_yates(fs, 25)[:3]

        decks = b.video_poker_decks(n); n0 = b.last_nonce_range[0]
        for i in range(n):
            fs = ref_floats(SERVER, BULK_CLIENT, n0 + i, 0, 52)
            assert decks[i].tolist() == ref_fisher_yates(fs, 52)

        for difficulty, (count, sz) in rng.DRAGON_TOWER_LEVEL_MAP.items():
            towers = b.dragon_tower_eggs(difficulty, 10)
            n0 = b.last_nonce_range[0]
            assert towers.shape == (10, 9, count)
            for i in range(10):
                fs = ref_floats(SERVER, BULK_CLIENT, n0 + i, 0, 9)
                expected = []
                for f in fs:
                    idx = math.floor(f * sz)
                    expected.append(
                        [idx] if count == 1
                        else [t for t in range(sz) if t != idx]
                    )
                assert towers[i].tolist() == expected

        spins = b.scarab_spins(n); n0 = b.last_nonce_range[0]
        for i in range(n):
            fs = ref_floats(SERVER, BULK_CLIENT, n0 + i, 0, 5)
            assert spins[i].tolist() == [
                math.floor(f * r) for f, r in zip(fs, (30, 30, 30, 30, 41))
            ]

    def test_bulk_dragon_tower_matches_scalar_helper(self):
        b = rng.BulkRng(SERVER, BULK_CLIENT, nonce_start=500)
        towers = b.dragon_tower_eggs("easy", 25)
        for i in range(25):
            scalar = rng.dragon_tower_eggs(SERVER, BULK_CLIENT, 500 + i, "easy")
            assert towers[i].tolist() == scalar

    def test_bulk_dragon_tower_bad_difficulty_consumes_no_nonces(self):
        b = rng.BulkRng(SERVER, BULK_CLIENT)
        with pytest.raises(ValueError):
            b.dragon_tower_eggs("nightmare", 5)
        assert b.nonce_next == b.nonce_start

    def test_verify_floats_helper_matches_bulk_row(self):
        b = rng.BulkRng(SERVER, BULK_CLIENT, nonce_start=7)
        m = b.float_matrix(5, 10)
        assert m[2].tolist() == b.verify_floats(9, 10)

    def test_chunked_output_identical_to_unchunked(self, monkeypatch):
        b1 = rng.BulkRng(SERVER, BULK_CLIENT)
        big = b1.float_matrix(101, 10)
        monkeypatch.setattr(rng, "_CHUNK_FLOAT_BUDGET", 70)  # forces 7-row chunks
        b2 = rng.BulkRng(SERVER, BULK_CLIENT)
        assert np.array_equal(b2.float_matrix(101, 10), big)
        # and for the Fisher-Yates games
        b3 = rng.BulkRng(SERVER, BULK_CLIENT)
        k3 = b3.keno_hits(31)
        monkeypatch.setattr(rng, "_CHUNK_FLOAT_BUDGET", 8_000_000)
        b4 = rng.BulkRng(SERVER, BULK_CLIENT)
        assert np.array_equal(b4.keno_hits(31), k3)

    def test_parallel_workers_byte_identical(self, monkeypatch):
        monkeypatch.setattr(rng, "_PARALLEL_MIN_DIGESTS", 100)
        a = rng.BulkRng(SERVER, BULK_CLIENT, 0, workers=3).float_matrix(1000, 2)
        c = rng.BulkRng(SERVER, BULK_CLIENT, 0, workers=1).float_matrix(1000, 2)
        assert np.array_equal(a, c)
        # and the parallel rows still verify against the independent reference
        assert a[977].tolist() == ref_floats(SERVER, BULK_CLIENT, 977, 0, 2)

    def test_float_lattice_and_range(self):
        f = rng.BulkRng(SERVER, BULK_CLIENT).floats(10_000)
        assert np.all((f >= 0) & (f < 1))
        scaled = f * 2**32
        assert np.array_equal(scaled, np.floor(scaled))  # exact k / 2**32

    def test_reproducible_from_same_seeds(self):
        a = rng.BulkRng(SERVER, BULK_CLIENT, 0).floats(100)
        c = rng.BulkRng(SERVER, BULK_CLIENT, 0).floats(100)
        assert np.array_equal(a, c)
        d = rng.BulkRng(SERVER, "other", 0).floats(100)
        assert not np.array_equal(a, d)


class TestBulkValidation:
    def test_draws_without_replacement_overdraw_raises(self):
        b = rng.BulkRng(SERVER, BULK_CLIENT)
        with pytest.raises(ValueError):
            b.draws_without_replacement(pool_size=5, draw_count=9, size=3)

    def test_video_poker_cards_needed_out_of_range(self):
        b = rng.BulkRng(SERVER, BULK_CLIENT)
        with pytest.raises(ValueError):
            b.video_poker_decks(size=3, cards_needed=60)
        with pytest.raises(ValueError):
            b.video_poker_decks(size=3, cards_needed=0)

    def test_mine_count_validation(self):
        with pytest.raises(ValueError):
            rng.BulkRng(SERVER, BULK_CLIENT).mines_positions(0, 5)
        with pytest.raises(ValueError):
            rng.BulkRng(SERVER, BULK_CLIENT).mines_positions(25, 5)

    def test_plinko_rows_validation(self):
        b = rng.BulkRng(SERVER, BULK_CLIENT)
        with pytest.raises(ValueError):
            b.plinko_directions(17, 5)
        with pytest.raises(ValueError):
            b.plinko_directions(7, 5)

    def test_failed_validation_consumes_no_nonces(self):
        b = rng.BulkRng(SERVER, BULK_CLIENT)
        with pytest.raises(ValueError):
            b.draws_without_replacement(5, 9, 3)
        assert b.nonce_next == b.nonce_start

    def test_video_poker_prefix_property(self):
        """cards_needed only slices columns of the full 52-event shuffle."""
        b1 = rng.BulkRng(SERVER, BULK_CLIENT)
        full = b1.video_poker_decks(10, 52)
        b2 = rng.BulkRng(SERVER, BULK_CLIENT)
        assert np.array_equal(b2.video_poker_decks(10, 5), full[:, :5])

    def test_draws_matrix_uniqueness(self):
        d = rng.BulkRng(SERVER, BULK_CLIENT).draws_without_replacement(40, 10, 300)
        assert d.shape == (300, 10)
        for row in d:
            assert len(set(row.tolist())) == 10
            assert row.min() >= 0 and row.max() < 40


class TestBulkDistributions:
    """Sanity-level distribution checks (bit-exactness above is the real
    guarantee; these catch gross wiring mistakes cheaply)."""

    def test_float_mean_and_variance(self):
        f = rng.BulkRng(SERVER, "dist-check", 0).floats(200_000)
        assert abs(f.mean() - 0.5) < 0.005
        assert abs(f.var() - 1 / 12) < 0.002

    def test_roulette_uniformity_chi2(self):
        from scipy import stats
        n = 111_000
        pockets = rng.BulkRng(SERVER, "dist-check", 0).roulette_pockets(n)
        counts = np.bincount(pockets, minlength=37)
        chi2 = ((counts - n / 37) ** 2 / (n / 37)).sum()
        assert stats.chi2.sf(chi2, 36) > 1e-6

    def test_mines_marginal_inclusion_probability(self):
        m = rng.BulkRng(SERVER, "dist-check", 0).mines_positions(3, 40_000)
        incl = np.bincount(m.ravel(), minlength=25) / 40_000
        assert np.allclose(incl, 3 / 25, atol=0.01)

    def test_limbo_law(self):
        l = rng.BulkRng(SERVER, "dist-check", 0).limbo_crash_points(100_000)
        assert l.min() >= 1.0
        # P(crash >= 2) = P(float <= 0.99/2) ~ 0.495
        assert abs((l >= 2).mean() - 0.495) < 0.01

    def test_bulk_zero_float_yields_inf(self):
        class ZeroFirst(rng.BulkRng):
            def floats(self, size):
                out = super().floats(size)
                out[0] = 0.0
                out[1] = 3 / 2**32  # a known ULP-divergent lattice float
                return out

        pts = ZeroFirst(SERVER, BULK_CLIENT).limbo_crash_points(16)
        assert pts[0] == math.inf
        assert pts[1] == 1417339207.67
