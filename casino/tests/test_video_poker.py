"""Tests for spinquest_sim.games.video_poker.

Ground truth: references/stake/video_poker.md (paytable, provably-fair deal
mechanics, published 1% edge) and references/woo/video_poker.md (9/6 Jacks or
Better benchmark: 99.5439% optimal return, SD 4.417542, exact full-cycle
methodology).
"""

from __future__ import annotations

import math
import random
from fractions import Fraction

import numpy as np
import pytest

from spinquest_sim import rng as sq_rng
from spinquest_sim.rng import BulkRng
from spinquest_sim.games import video_poker as vp


# --------------------------------------------------------------------------
# Reference data (verbatim from references/stake/video_poker.md §6)
# --------------------------------------------------------------------------

STAKE_REFERENCE_PAYTABLE = {
    "Pair of Jacks or better": 1,
    "2 Pair": 2,
    "3 of a Kind": 3,
    "Straight": 4,
    "Flush": 6,
    "Full House": 9,
    "4 of a Kind": 22,
    "Straight Flush": 60,
    "Royal Flush": 800,
}

# references/woo/video_poker.md: 9/6 full pay, optimal strategy.
WOO_RTP_9_6 = 0.995439
WOO_SD_9_6 = 4.417542


def card(rank: str, suit: str) -> int:
    """'J','♦' -> Stake card index ((rank-2)*4 + suit; suits ♦♥♠♣)."""
    ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A"]
    suits = "dhsc"
    return ranks.index(rank) * 4 + suits.index(suit)


@pytest.fixture(scope="module")
def solutions():
    """Solve every paytable once for the whole module (single shared pass:
    the 8 WoO variants + Stake's table; 9/6 doubles as the benchmark)."""
    names = list(vp.WOO_VARIANT_PAYTABLES)
    tables = [vp.WOO_VARIANT_PAYTABLES[n] for n in names] + [vp.STAKE_PAYTABLE]
    sols = vp.solve_paytables(tables)
    variants = dict(zip(names, sols[:-1]))
    return {"benchmark": variants["9/6"], "stake": sols[-1],
            "variants": variants}


@pytest.fixture(scope="module")
def stake_game(solutions):
    return vp.VideoPoker()  # solutions cached at module level already


@pytest.fixture(scope="module")
def bench_game(solutions):
    return vp.VideoPoker(vp.BENCHMARK_9_6_PAYTABLE)


# --------------------------------------------------------------------------
# Paytable vs the Stake reference
# --------------------------------------------------------------------------

def test_paytable_matches_stake_reference_exactly():
    engine = {
        vp.CATEGORY_LABELS[name]: pays for name, pays in vp.STAKE_PAYTABLE.items()
    }
    assert engine == STAKE_REFERENCE_PAYTABLE


def test_benchmark_paytable_is_full_pay_9_6():
    assert vp.BENCHMARK_9_6_PAYTABLE["full_house"] == 9
    assert vp.BENCHMARK_9_6_PAYTABLE["flush"] == 6
    assert vp.BENCHMARK_9_6_PAYTABLE["royal_flush"] == 800
    assert vp.BENCHMARK_9_6_PAYTABLE["straight_flush"] == 50
    assert vp.BENCHMARK_9_6_PAYTABLE["four_of_a_kind"] == 25


def test_paytable_rejects_bad_entries():
    with pytest.raises(ValueError):
        vp.VideoPoker({"royal_flush": 800, "flushh": 6})
    with pytest.raises(ValueError):
        vp.VideoPoker({"royal_flush": -1})
    with pytest.raises(ValueError):
        vp.VideoPoker({"nothing": 1})


# --------------------------------------------------------------------------
# Hand evaluator
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "cards,expect",
    [
        ([card(r, "d") for r in "TJQKA"], "royal_flush"),
        ([card(r, "c") for r in "A2345"], "straight_flush"),  # wheel SF
        ([card(r, "h") for r in "56789"], "straight_flush"),
        ([card("T", "d"), card("J", "h"), card("Q", "s"), card("K", "c"),
          card("A", "d")], "straight"),  # broadway, mixed suits
        ([card("A", "d"), card("2", "h"), card("3", "s"), card("4", "c"),
          card("5", "d")], "straight"),  # wheel, mixed suits
        ([card("9", "d"), card("9", "h"), card("9", "s"), card("9", "c"),
          card("3", "d")], "four_of_a_kind"),
        ([card("9", "d"), card("9", "h"), card("9", "s"), card("3", "c"),
          card("3", "d")], "full_house"),
        ([card("2", "s"), card("5", "s"), card("9", "s"), card("J", "s"),
          card("K", "s")], "flush"),
        ([card("7", "d"), card("7", "h"), card("7", "s"), card("K", "c"),
          card("3", "d")], "three_of_a_kind"),
        ([card("7", "d"), card("7", "h"), card("K", "s"), card("K", "c"),
          card("3", "d")], "two_pair"),
        ([card("J", "d"), card("J", "h"), card("2", "s"), card("7", "c"),
          card("9", "d")], "jacks_or_better"),
        ([card("A", "d"), card("A", "h"), card("2", "s"), card("7", "c"),
          card("9", "d")], "jacks_or_better"),
        ([card("T", "d"), card("T", "h"), card("2", "s"), card("7", "c"),
          card("9", "d")], "nothing"),  # tens do NOT pay
        ([card("A", "d"), card("K", "h"), card("2", "s"), card("7", "c"),
          card("9", "d")], "nothing"),
        # A-high but not a straight (A,2,3,4,6)
        ([card("A", "d"), card("2", "h"), card("3", "s"), card("4", "c"),
          card("6", "d")], "nothing"),
        # K-Q-J-T-9 straight (touching the royal window but 9-high min rank)
        ([card("9", "d"), card("T", "h"), card("J", "s"), card("Q", "c"),
          card("K", "d")], "straight"),
        ([card("9", "s"), card("T", "s"), card("J", "s"), card("Q", "s"),
          card("K", "s")], "straight_flush"),  # K-high SF, not royal
    ],
)
def test_evaluator_known_hands(cards, expect):
    assert vp.evaluate_hand(cards) == expect
    # order-agnostic
    shuffled = list(cards)
    random.Random(0).shuffle(shuffled)
    assert vp.evaluate_hand(shuffled) == expect


def test_five_card_category_counts_are_the_known_combinatorics():
    tabs = vp._get_tables()
    counts = np.bincount(tabs["cat"], minlength=vp.N_CAT)
    assert counts.tolist() == [
        2_062_860, 337_920, 123_552, 54_912, 10_200, 5_108, 3_744, 624, 36, 4
    ]
    assert counts.sum() == vp.N_HANDS


def test_colex_rank_is_a_bijection_over_all_hands():
    tabs = vp._get_tables()
    ranks = vp.hand_colex_rank(tabs["hands"].astype(np.int64))
    assert ranks.min() == 0 and ranks.max() == vp.N_HANDS - 1
    seen = np.zeros(vp.N_HANDS, dtype=bool)
    seen[ranks] = True
    assert seen.all()


# --------------------------------------------------------------------------
# Exact hold EV: inclusion-exclusion tables vs independent brute force
# --------------------------------------------------------------------------

def test_hold_ev_exact_matches_bruteforce():
    rnd = random.Random(42)
    masks = [31, 30, 27, 24, 21, 16, 5, 1, 0]
    for i, mask in enumerate(masks):
        dealt = rnd.sample(range(52), 5)
        pt = vp.STAKE_PAYTABLE if i % 2 else vp.BENCHMARK_9_6_PAYTABLE
        exact = vp.hold_ev_exact(dealt, mask, pt)
        brute = vp.hold_ev_bruteforce(dealt, mask, pt)
        assert exact == brute, (dealt, mask)


def test_hold_all_five_ev_is_the_hand_payout():
    dealt = [card(r, "d") for r in "TJQKA"]
    assert vp.hold_ev_exact(dealt, 31, vp.STAKE_PAYTABLE) == 800


def test_optimal_table_agrees_with_direct_argmax(solutions):
    """The vectorized table must equal a per-hand scalar argmax over all 32
    holds (exact fractions, ties to the lowest mask)."""
    rnd = random.Random(2024)
    for sol, pt in (
        (solutions["benchmark"], vp.BENCHMARK_9_6_PAYTABLE),
        (solutions["stake"], vp.STAKE_PAYTABLE),
    ):
        for _ in range(12):
            dealt = sorted(rnd.sample(range(52), 5))
            evs = [vp.hold_ev_exact(dealt, m, pt) for m in range(32)]
            best = max(range(32), key=lambda m: (evs[m], -m))
            table_mask = int(sol.pattern_table[int(vp.hand_colex_rank(np.array(dealt))[0])])
            assert evs[table_mask] == evs[best]
            assert table_mask == min(m for m in range(32) if evs[m] == evs[best])


# --------------------------------------------------------------------------
# Headline analytic numbers vs the references
# --------------------------------------------------------------------------

def test_benchmark_9_6_rtp_and_sd_match_wizard_of_odds(solutions):
    sol = solutions["benchmark"]
    assert abs(float(sol.ev) - WOO_RTP_9_6) < 1e-6
    assert abs(sol.std - WOO_SD_9_6) < 1e-5
    # displayed precision in the reference
    assert round(float(sol.ev) * 100, 4) == 99.5439
    assert round(sol.std, 2) == 4.42


def test_stake_optimal_rtp_is_the_ceiling_below_published_99pct(solutions):
    """Exact optimal play on Stake's 800/60/22/9/6/4/3/2/1 table is the
    CEILING at 98.9445% (edge 1.0555%): the published 'Edge: 1.00%' is
    unattainable under any strategy; only the integer-rounded '99% RTP'
    page title is consistent with the ceiling."""
    ev = solutions["stake"].ev
    assert ev == Fraction(410892309848, 415275635775)
    rtp = float(ev)
    assert rtp < 0.99                      # published 99% is above the ceiling
    assert round(rtp * 100) == 99          # ...but rounds to it at integer precision
    assert round((1 - rtp) * 100, 4) == 1.0555


def test_woo_variant_returns_match_published(solutions):
    """All 8 WoO Jacks-or-Better pay-table variants reproduce the published
    optimal-strategy returns at the reference's displayed precision."""
    for name, sol in solutions["variants"].items():
        published = vp.WOO_VARIANT_RETURNS_PCT[name]
        assert round(float(sol.ev) * 100, 2) == published, name


def test_multihand_appendix3_sd(solutions):
    """WoO Appendix 3: per-hand n-play SD = sqrt(v + (n-1)c), c the exact
    shared-deal covariance Var(E[X|deal]) from the per-deal EV moments."""
    bench = solutions["benchmark"]
    published = {1: 4.42, 3: 4.84, 5: 5.23, 10: 6.10, 50: 10.76, 100: 14.64}
    for n, ref in published.items():
        assert round(bench.n_play_std(n), 2) == ref, n
    c = float(bench.hold_ev_variance)
    assert abs(c - 1.966389) < 1e-5
    assert 0 < bench.hold_ev_variance < bench.variance
    assert bench.n_play_std(1) == bench.std
    with pytest.raises(ValueError):
        bench.n_play_variance(0)


def test_hold_ev_moment_identities(solutions):
    """The per-deal optimal-EV mean must equal the aggregate return exactly,
    for every solved paytable (links the two solver accumulations)."""
    all_sols = list(solutions["variants"].values()) + [solutions["stake"]]
    for sol in all_sols:
        mean = Fraction(sol.hold_ev_sum_scaled, vp.COMBINATIONS_DENOMINATOR)
        assert mean == sol.ev
        assert 0 <= sol.hold_ev_variance <= sol.variance


def test_return_table_combinations_column(bench_game):
    """9/6 return table: the exact Combinations column (denominator
    L * C(52,5) = 19,933,230,517,200) must match the Wizard's published
    integers digit-for-digit, and the return column must sum to the RTP."""
    expected = {
        "royal_flush": 493_512_264,
        "straight_flush": 2_178_883_296,
        "four_of_a_kind": 47_093_167_764,
        "full_house": 229_475_482_596,
        "flush": 219_554_786_160,
        "straight": 223_837_565_784,
        "three_of_a_kind": 1_484_003_070_324,
        "two_pair": 2_576_946_164_148,
        "jacks_or_better": 4_277_372_890_968,
        "nothing": 10_872_274_993_896,
    }
    assert vp.COMBINATIONS_DENOMINATOR == 19_933_230_517_200
    rows = bench_game.return_table()
    assert [r["category"] for r in rows] == list(reversed(vp.CATEGORIES))
    assert {r["category"]: r["combinations"] for r in rows} == expected
    assert sum(r["combinations"] for r in rows) == vp.COMBINATIONS_DENOMINATOR
    assert sum(r["probability_exact"] for r in rows) == 1
    assert sum(r["return_exact"] for r in rows) == bench_game.rtp_exact
    for r in rows:
        assert r["return_exact"] == r["probability_exact"] * r["pays"]


def test_category_probs_exact_consistency(solutions):
    for name in ("benchmark", "stake"):
        sol = solutions[name]
        assert sum(sol.category_probs) == 1
        ev = sum(p * pay for p, pay in zip(sol.category_probs, sol.paytable_key))
        assert ev == sol.ev
        assert all(p >= 0 for p in sol.category_probs)
        # every category is reachable under optimal play
        assert all(p > 0 for p in sol.category_probs)


def test_analytic_summary_standard_keys(bench_game):
    s = bench_game.analytic_summary()
    for key in ("rtp", "house_edge", "std_per_unit", "config"):
        assert key in s
    assert s["config"]["game"] == "video_poker"
    assert abs(s["rtp"] + s["house_edge"] - 1.0) < 1e-12


# --------------------------------------------------------------------------
# Known strategy decisions (classic Jacks-or-Better discriminators)
# --------------------------------------------------------------------------

def test_strategy_dealt_royal_holds_all(bench_game):
    dealt = [card(r, "h") for r in "TJQKA"]
    assert bench_game.optimal_hold_mask_sorted(dealt) == 0b11111


def test_strategy_pat_straight_flush_is_kept(bench_game, stake_game):
    # ♥9 ♥T ♥J ♥Q ♥K is a K-high STRAIGHT FLUSH (50x/60x) — never broken.
    dealt = [card(r, "h") for r in "9TJQK"]
    for game in (bench_game, stake_game):
        assert game.optimal_hold_mask_sorted(dealt) == 0b11111


def test_strategy_breaks_pat_flush_for_four_to_royal(bench_game, stake_game):
    # ♥8 ♥T ♥J ♥Q ♥K: made flush (pays 6) but holding TJQK chases the royal
    # (EV = (800 + 7*6 + 6*4 + 9*1)/47 = 875/47 ~ 18.6 on the 9/6 table).
    dealt = [card(r, "h") for r in "8TJQK"]
    for game in (bench_game, stake_game):
        assert game.optimal_hold_mask_sorted(dealt) == 0b11110


def test_strategy_low_pair_over_open_ended_straight_draw(bench_game):
    # 6♦ 6♥ 7♠ 8♦ 9♣ -> hold the pair of sixes (sorted positions 0,1).
    dealt = [card("6", "d"), card("6", "h"), card("7", "s"),
             card("8", "d"), card("9", "c")]
    assert bench_game.optimal_hold_mask_sorted(dealt) == 0b00011


def test_strategy_four_flush_over_low_pair(bench_game):
    # ♦5 ♥5 ♦8 ♦J ♦K -> hold the four diamonds, not the pair of fives.
    dealt = [card("5", "d"), card("5", "h"), card("8", "d"),
             card("J", "d"), card("K", "d")]
    # sorted: ♦5(12) ♥5(13) ♦8(24) ♦J(36) ♦K(44) -> hold positions 0,2,3,4
    assert bench_game.optimal_hold_mask_sorted(dealt) == 0b11101


def test_strategy_lookups_reject_bad_deals(bench_game):
    """A 4-card deal must raise, not silently return a 5-bit mask/flag list
    (optimal_hold_mask_sorted([0,1,2,3]) used to return 15)."""
    for bad in ([0, 1, 2, 3], [0, 1, 2, 3, 4, 5], [0, 1, 2, 3, 3],
                [0, 1, 2, 3, 52], [-1, 1, 2, 3, 4], []):
        with pytest.raises(ValueError):
            bench_game.optimal_hold_mask_sorted(bad)
        with pytest.raises(ValueError):
            bench_game.optimal_holds(bad)


def test_hand_colex_rank_rejects_non_5_card_rows():
    with pytest.raises(ValueError):
        vp.hand_colex_rank(np.array([0, 1, 2, 3]))
    with pytest.raises(ValueError):
        vp.hand_colex_rank(np.array([[0, 1, 2, 3, 4, 5]]))
    with pytest.raises(ValueError):
        vp.hand_colex_rank(np.array([0, 1, 2, 3, 52]))


def test_optimal_holds_maps_back_to_deal_order(bench_game):
    dealt = [card("K", "d"), card("5", "h"), card("5", "d"),
             card("8", "d"), card("J", "d")]  # scrambled four-flush hand
    holds = bench_game.optimal_holds(dealt)
    held_cards = {c for c, h in zip(dealt, holds) if h}
    assert held_cards == {card("5", "d"), card("8", "d"),
                          card("J", "d"), card("K", "d")}


# --------------------------------------------------------------------------
# Provably-fair single round
# --------------------------------------------------------------------------

SERVER = "9f" * 32
CLIENT = "vp-test-client"


def test_play_round_deterministic_and_verifiable(stake_game):
    r1 = stake_game.play_round(SERVER, CLIENT, 3)
    r2 = stake_game.play_round(SERVER, CLIENT, 3)
    assert r1["dealt"] == r2["dealt"] and r1["final"] == r2["final"]
    deck = sq_rng.video_poker_deck(SERVER, CLIENT, 3)
    assert r1["dealt"] == deck[:5]
    # replacements come from the same pre-committed permutation, in order
    n_disc = sum(not h for h in r1["holds"])
    expected_repl = deck[5:5 + n_disc]
    got_repl = [c for c, h in zip(r1["final"], r1["holds"]) if not h]
    assert got_repl == expected_repl
    assert r1["verification"]["server_seed_hash"] == sq_rng.hash_server_seed(SERVER)
    assert r1["payout"] == r1["payout_multiplier"] * r1["bet"]


def test_play_round_hold_all_keeps_deal(stake_game):
    r = stake_game.play_round(SERVER, CLIENT, 11, holds=[True] * 5)
    assert r["final"] == r["dealt"]
    assert r["category"] == vp.evaluate_hand(r["dealt"])


def test_play_round_discard_all_draws_next_five(stake_game):
    r = stake_game.play_round(SERVER, CLIENT, 12, holds=[False] * 5)
    deck = sq_rng.video_poker_deck(SERVER, CLIENT, 12)
    assert r["final"] == deck[5:10]


def test_play_round_optimal_matches_pattern_table(stake_game):
    for nonce in range(5):
        r = stake_game.play_round(SERVER, CLIENT, nonce)
        mask = stake_game.optimal_hold_mask_sorted(r["dealt"])
        sorted_dealt = sorted(r["dealt"])
        held_sorted = {sorted_dealt[i] for i in range(5) if (mask >> i) & 1}
        held_play = {c for c, h in zip(r["dealt"], r["holds"]) if h}
        assert held_sorted == held_play


def test_play_round_validates_inputs(stake_game):
    with pytest.raises(ValueError):
        stake_game.play_round(SERVER, CLIENT, 0, bet=0)
    with pytest.raises(ValueError):
        stake_game.play_round(SERVER, CLIENT, 0, holds=[True] * 4)


# --------------------------------------------------------------------------
# Vectorized simulator
# --------------------------------------------------------------------------

def test_simulate_bit_for_bit_matches_scalar_rounds(stake_game):
    """Every simulated row must equal the scalar provably-fair round at the
    same nonce (same deck, same optimal hold, same payout)."""
    n = 40
    bulk = BulkRng(server_seed=SERVER, client_seed=CLIENT, nonce_start=100)
    sim = stake_game.simulate(n, bulk=bulk, progress=False)
    scalar_total = 0.0
    for nonce in range(100, 100 + n):
        scalar_total += stake_game.play_round(SERVER, CLIENT, nonce)["payout"]
    assert sim["rtp"] * n == pytest.approx(scalar_total, abs=1e-9)
    assert sim["verification"]["nonce_range"] == (100, 100 + n)


def test_simulate_within_se(stake_game):
    sim = stake_game.simulate(
        250_000,
        bulk=BulkRng(server_seed="ab" * 32, client_seed="vp-se", nonce_start=0),
        progress=False,
    )
    assert abs(sim["z_score"]) < 4.0
    assert sum(sim["category_counts"].values()) == 250_000
    for key in ("rtp", "house_edge", "std_per_unit", "config"):
        assert key in sim
    assert sim["config"]["game"] == "video_poker"
    # Empirical SD is dominated by royal-flush noise (800x at p~2.5e-5: only
    # ~6 royals expected in 250k rounds, carrying ~80% of the variance), so
    # only a wide sanity band is meaningful at this sample size.
    assert 1.5 < sim["std_per_unit"] < 8.0


def test_simulate_rejects_bad_rounds(stake_game):
    with pytest.raises(ValueError):
        stake_game.simulate(0)


def test_solution_cache_roundtrip(tmp_path, solutions):
    """The v2 cache must round-trip the per-deal EV moment sums (the square
    sum exceeds int64 and is stored as a string)."""
    sol = solutions["benchmark"]
    vp._store_cached(str(tmp_path), sol.paytable_key, sol)
    loaded = vp._load_cached(str(tmp_path), sol.paytable_key)
    assert loaded is not None
    assert loaded.ev == sol.ev
    assert loaded.hold_ev_sum_scaled == sol.hold_ev_sum_scaled
    assert loaded.hold_ev_sq_sum_scaled == sol.hold_ev_sq_sum_scaled
    assert loaded.hold_ev_variance == sol.hold_ev_variance
    assert np.array_equal(loaded.pattern_table, sol.pattern_table)
