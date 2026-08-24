"""Tests for the Baccarat (punto banco) engine.

Ground truth: references/stake/baccarat.md (payouts, drawing rules, card
mapping, 6-events-per-round provably-fair mechanics) and
references/woo/baccarat.md (8-deck and infinite-deck house edges, win
probabilities, and per-unit SDs).
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from spinquest_sim import rng as sq_rng
from spinquest_sim.games import baccarat as bc
from spinquest_sim.games.baccarat import Baccarat
from spinquest_sim.rng import BulkRng

SS = hashlib.sha256(b"test_baccarat server seed").hexdigest()
CS = "test-baccarat"


# ---------------------------------------------------------------------------
# card values & payouts (references/stake/baccarat.md sec. 4-5)
# ---------------------------------------------------------------------------

def test_card_values_follow_published_mapping():
    # 10/J/Q/K worth zero, aces worth one, 2-9 pip value (verbatim rules),
    # over the published CARDS index (rank = index // 4, ranks 2..A).
    for idx in range(52):
        rank = sq_rng.CARDS[idx][1:]
        if rank in ("10", "J", "Q", "K"):
            expect = 0
        elif rank == "A":
            expect = 1
        else:
            expect = int(rank)
        assert bc.card_value(idx) == expect, sq_rng.CARDS[idx]
    # per-deck composition: 16 zero-value cards, 4 of each value 1..9
    assert list(np.bincount(bc.CARD_VALUES, minlength=10)) == [16] + [4] * 9


def test_published_payout_table():
    # Player 1:1 -> 2.00, Banker 0.95:1 -> 1.95, Tie 8:1 -> 9.00 (verbatim)
    assert bc.PAYOUT_ODDS["player"] == 1
    assert bc.PAYOUT_ODDS["banker"] == Fraction(19, 20)
    assert bc.PAYOUT_ODDS["tie"] == 8
    assert float(bc.MULTIPLIERS["player"]) == 2.00
    assert float(bc.MULTIPLIERS["banker"]) == 1.95
    assert float(bc.MULTIPLIERS["tie"]) == 9.00


def test_events_per_round_is_published_six_one_digest():
    assert bc.EVENTS_PER_ROUND == 6
    assert sq_rng.EVENT_COUNTS["baccarat"] == 6
    # "only 1 incremental number": 6 events * 4 bytes fit one 32-byte digest
    assert sq_rng.CURSOR_INCREMENTS["baccarat"] == 1


# ---------------------------------------------------------------------------
# drawing rules (references/stake/baccarat.md sec. 4, verbatim table)
# ---------------------------------------------------------------------------

def test_banker_draw_table_matches_published_rows():
    t = bc.BANKER_DRAW_TABLE
    # 0/1/2: "Bank draws in all instances" (naturals handled before)
    assert t[0:3].all()
    # 3: "draws if the player's third card is 0-7 or 9; stands when 8"
    assert [bool(t[3, v]) for v in range(10)] == [
        True, True, True, True, True, True, True, True, False, True
    ]
    # 4: "draws if the player's third card is 2-7"
    assert [v for v in range(10) if t[4, v]] == [2, 3, 4, 5, 6, 7]
    # 5: "draws if the player's third card is 4-7"
    assert [v for v in range(10) if t[5, v]] == [4, 5, 6, 7]
    # 6: "draws if the player's third card is 6-7"
    assert [v for v in range(10) if t[6, v]] == [6, 7]
    # 7: "Bank stands."
    assert not t[7].any() and not t[8].any() and not t[9].any()


def test_banker_draws_when_player_stands():
    # player stood on 6-7: banker draws 0-5, stands 6-7 (standard punto banco)
    for bt in range(8):
        assert bc.banker_draws(bt, None) == (bt <= 5)
    with pytest.raises(ValueError):
        bc.banker_draws(8, None)   # naturals must be handled by the caller


@pytest.mark.parametrize(
    "values,p_total,b_total,used,outcome",
    [
        # natural 9 vs 7: both stand at 4 cards
        ((4, 3, 5, 4), 9, 7, 4, "player"),
        # natural 8 (banker): player 0-5 does NOT draw against a natural
        ((2, 4, 3, 4), 5, 8, 4, "banker"),
        # both naturals equal -> tie
        ((4, 5, 4, 3), 8, 8, 4, "tie"),
        # player stands on 6, banker 5 draws (player stood -> banker 0-5 draws)
        ((2, 2, 4, 3, 9), 6, 4, 5, "player"),
        # player stands on 7, banker 6 stands -> 4 cards
        ((3, 3, 4, 3), 7, 6, 4, "player"),
        # player draws (0-5); banker 3 stands on player third card 8
        ((1, 2, 3, 1, 8), 2, 3, 5, "banker"),
        # player draws; banker 3 draws on player third card 9
        ((1, 2, 3, 1, 9, 5), 3, 8, 6, "banker"),
        # player draws; banker 4 stands on player third card 1
        ((1, 3, 3, 1, 1), 5, 4, 5, "player"),
        # player draws; banker 6 draws only on player third 6-7
        ((1, 2, 3, 4, 6, 3), 0, 9, 6, "banker"),
        # player draws; banker 6 stands on player third 5
        ((1, 2, 3, 4, 5), 9, 6, 5, "player"),
        # banker 7 always stands after a player draw
        ((1, 3, 3, 4, 9, 0), 3, 7, 5, "banker"),
        # player 0 draws, banker 0 draws -> full 6 cards, modulo-10 totals
        ((0, 0, 0, 0, 7, 7), 7, 7, 6, "tie"),
    ],
)
def test_settle_values_rule_branches(values, p_total, b_total, used, outcome):
    padded = tuple(values) + (0,) * (6 - len(values))
    res = bc.settle_values(padded)
    assert res["player_total"] == p_total
    assert res["banker_total"] == b_total
    assert res["events_used"] == used
    assert res["outcome"] == outcome


def test_settle_matrix_matches_scalar_settle():
    rs = np.random.default_rng(20260824)
    values = rs.integers(0, 10, size=(50_000, 6))
    vec = bc._settle_matrix(values)
    names = ("player", "banker", "tie")
    for i in range(0, 50_000, 7):   # dense spot-check of every 7th row
        assert names[vec[i]] == bc.settle_values(values[i])["outcome"]
    # and full agreement on a smaller exhaustive block
    for i in range(2_000):
        assert names[vec[i]] == bc.settle_values(values[i])["outcome"]


# ---------------------------------------------------------------------------
# exact analytics vs the Wizard of Odds published figures
# ---------------------------------------------------------------------------

def test_probabilities_sum_to_one_exactly():
    for decks in (8, 6, 1, None):
        probs = bc.outcome_probabilities(decks)
        assert sum(probs.values()) == 1


def test_8deck_win_probabilities_match_woo():
    # WoO: Banker 45.86%, Player 44.62%, Tie 9.52% (rounded to 2 dp)
    p = bc.outcome_probabilities(8)
    assert round(100 * float(p["banker"]), 2) == 45.86
    assert round(100 * float(p["player"]), 2) == 44.62
    assert round(100 * float(p["tie"]), 2) == 9.52


def test_8deck_house_edges_match_woo():
    # WoO 8-deck: Banker 1.06%, Player 1.24%, Tie 14.36%
    assert round(100 * Baccarat("banker", 8).house_edge, 2) == 1.06
    assert round(100 * Baccarat("player", 8).house_edge, 2) == 1.24
    assert round(100 * Baccarat("tie", 8).house_edge, 2) == 14.36
    # equivalent RTPs: 98.94 / 98.76 / 85.64
    assert round(100 * Baccarat("banker", 8).rtp, 2) == 98.94
    assert round(100 * Baccarat("player", 8).rtp, 2) == 98.76
    assert round(100 * Baccarat("tie", 8).rtp, 2) == 85.64


def test_other_deck_counts_match_woo_table():
    # WoO: 6 decks 1.06 / 1.24 / 14.44; 1 deck 1.01 / 1.29 / 15.75
    assert round(100 * Baccarat("banker", 6).house_edge, 2) == 1.06
    assert round(100 * Baccarat("player", 6).house_edge, 2) == 1.24
    assert round(100 * Baccarat("tie", 6).house_edge, 2) == 14.44
    assert round(100 * Baccarat("banker", 1).house_edge, 2) == 1.01
    assert round(100 * Baccarat("player", 1).house_edge, 2) == 1.29
    assert round(100 * Baccarat("tie", 1).house_edge, 2) == 15.75


def test_infinite_deck_matches_woo_and_is_stakes_mechanism():
    # WoO "Infinite" row: 1.064% / 1.228% / 14.117%
    assert round(100 * Baccarat("banker", None).house_edge, 3) == 1.064
    assert round(100 * Baccarat("player", None).house_edge, 3) == 1.228
    assert round(100 * Baccarat("tie", None).house_edge, 3) == 14.117


def test_8deck_std_per_unit_matches_woo():
    # WoO per-unit SDs: Banker 0.93, Player 0.95, Tie 2.64
    assert round(Baccarat("banker", 8).std_per_unit, 2) == 0.93
    assert round(Baccarat("player", 8).std_per_unit, 2) == 0.95
    assert round(Baccarat("tie", 8).std_per_unit, 2) == 2.64


def test_rtp_identity_and_push_accounting():
    for decks in (8, None):
        probs = bc.outcome_probabilities(decks)
        for bet in bc.BET_TYPES:
            eng = Baccarat(bet, decks)
            if bet == "tie":
                assert eng.push_probability == 0
                assert eng.rtp_exact == 9 * probs["tie"]
            else:
                assert eng.push_probability_exact == probs["tie"]
                assert eng.rtp_exact == (
                    bc.MULTIPLIERS[bet] * probs[bet] + probs["tie"]
                )
            assert eng.house_edge_exact == 1 - eng.rtp_exact
            assert 0 < eng.win_probability < 1


def test_house_edge_excluding_ties_matches_woo_note():
    # WoO note: "many other sources quote house edge excluding ties ...
    # which yields ~1.17% Banker / ~1.36% Player" (8 decks)
    assert round(100 * float(bc.house_edge_excluding_ties("banker", 8)), 2) == 1.17
    assert round(100 * float(bc.house_edge_excluding_ties("player", 8)), 2) == 1.36
    # exact identity for every published shoe: edge / (1 - P(tie)), and the
    # excluding-ties edge is strictly larger (the tie pushes it hid shrink
    # the denominator)
    for decks in (8, 6, 1, None):
        pt = bc.outcome_probabilities(decks)["tie"]
        for bet in ("player", "banker"):
            eng = Baccarat(bet, decks)
            excl = bc.house_edge_excluding_ties(bet, decks)
            assert isinstance(excl, Fraction)
            assert excl == eng.house_edge_exact / (1 - pt)
            assert excl > eng.house_edge_exact
    # only player/banker have the convention (tie never pushes)
    for bad in ("tie", "dragon", "player_pair"):
        with pytest.raises(ValueError):
            bc.house_edge_excluding_ties(bad, 8)
    with pytest.raises(ValueError):
        bc.house_edge_excluding_ties("player", 0)


def test_tie_bet_9to1_variant_matches_woo_note():
    # WoO note: "some casinos pay 9:1 on Tie, cutting its house edge to
    # ~4.84%" — reachable via the tie_odds constructor parameter
    eng9 = Baccarat("tie", 8, tie_odds=Fraction(9))
    assert eng9.payout_odds == Fraction(9)
    assert eng9.multiplier == 10.0
    pt = bc.outcome_probabilities(8)["tie"]
    assert eng9.rtp_exact == 10 * pt                     # exact machinery
    assert eng9.house_edge_exact == 1 - 10 * pt
    assert round(100 * eng9.house_edge, 2) == 4.84
    # variance/SD follow the new odds — no desync between odds & analytics:
    # net result is +9 w.p. p, -1 w.p. 1-p, so var = (9+1)^2 p (1-p)
    assert eng9.variance_per_unit == pytest.approx(float(100 * pt * (1 - pt)))
    assert eng9.variance_per_unit > Baccarat("tie", 8).variance_per_unit
    assert eng9.config()["payout_odds"] == "9:1"
    assert eng9.config()["tie_odds"] == "9:1"
    # default stays the published 8:1
    d = Baccarat("tie", 8)
    assert d.payout_odds == Fraction(8) and d.tie_odds == Fraction(8)
    assert d.config()["tie_odds"] == "8:1"
    # tie_odds never changes player/banker (a tie pushes them regardless)
    for bet in ("player", "banker"):
        a = Baccarat(bet, 8)
        b = Baccarat(bet, 8, tie_odds=Fraction(9))
        assert a.house_edge_exact == b.house_edge_exact
        assert a.payout_odds == b.payout_odds
        assert b.payouts_for_outcomes(np.array([2]))[0] == 1.0
    # settlement table honors the variant odds
    assert list(eng9.payouts_for_outcomes(np.array([0, 1, 2]))) == [0.0, 0.0, 10.0]
    # bad tie odds rejected
    for bad in (0, -1, Fraction(0), True, 8.0, "9"):
        with pytest.raises(ValueError):
            Baccarat("tie", 8, tie_odds=bad)


def test_tie_9to1_simulation_settles_at_variant_odds():
    n = 200_000
    res = bc.simulate_all_bets(
        n, decks=8, bulk=BulkRng(SS, CS, 0), progress=False,
        bets=("tie",), tie_odds=Fraction(9),
    )
    r = res["bets"]["tie"]
    assert r["config"]["payout_odds"] == "9:1"
    assert r["analytic_house_edge"] == pytest.approx(
        float(1 - 10 * bc.outcome_probabilities(8)["tie"])
    )
    assert r["rtp"] == pytest.approx(10 * r["wins"] / n)
    assert r["within_3se"], r["z_score"]
    # identical rounds, only the tie settle changes: same wins as 8:1 run
    res8 = bc.simulate_all_bets(
        n, decks=8, bulk=BulkRng(SS, CS, 0), progress=False, bets=("tie",),
    )
    assert res8["bets"]["tie"]["wins"] == r["wins"]
    # invalid tie_odds rejected before any simulation work
    with pytest.raises(ValueError):
        bc.simulate_all_bets(10, tie_odds=0)
    # per-bet engine path carries its tie_odds into simulate()
    single = Baccarat("tie", 8, tie_odds=Fraction(9)).simulate(
        50_000, bulk=BulkRng(SS, CS, 0), progress=False
    )
    assert single["config"]["payout_odds"] == "9:1"
    assert single["within_3se"]


# ---------------------------------------------------------------------------
# Stake's headline "1.10% overall / 98.90% RTP" — exact portfolio math
# (references/stake/baccarat.md sec. 6)
# ---------------------------------------------------------------------------

def test_portfolio_house_edge_is_exact_blend():
    # weight 1 on a single bet reduces exactly to that bet's edge
    for decks in (8, None):
        for bet in bc.BET_TYPES:
            assert bc.portfolio_house_edge({bet: 1}, decks) == (
                Baccarat(bet, decks).house_edge_exact
            )
        for bet in bc.PAIR_BET_TYPES:
            assert bc.portfolio_house_edge({bet: 1}, decks) == (
                bc.pair_house_edge(decks)
            )
    # exact linearity: a 50/50 banker/player mix is the exact midpoint
    eb = Baccarat("banker", 8).house_edge_exact
    ep = Baccarat("player", 8).house_edge_exact
    half = Fraction(1, 2)
    assert bc.portfolio_house_edge({"banker": half, "player": half}, 8) == (
        (eb + ep) / 2
    )
    # zero-weight entries are inert
    assert bc.portfolio_house_edge(
        {"banker": half, "player": half, "tie": 0}, 8
    ) == (eb + ep) / 2
    # tie_odds flows through to the tie bet's edge in the blend
    assert bc.portfolio_house_edge({"tie": 1}, 8, tie_odds=Fraction(9)) == (
        Baccarat("tie", 8, tie_odds=Fraction(9)).house_edge_exact
    )


def test_implied_banker_weight_exact_inverse_round_trip():
    eb = Baccarat("banker", 8).house_edge_exact
    ep = Baccarat("player", 8).house_edge_exact
    # endpoints: banker-only and player-only portfolios
    assert bc.implied_banker_weight(eb, 8) == 1
    assert bc.implied_banker_weight(ep, 8) == 0
    # interior targets round-trip EXACTLY through the blend (Fractions)
    for target in ((eb + ep) / 2, (3 * eb + ep) / 4, Fraction(11, 1000)):
        w = bc.implied_banker_weight(target, 8)
        assert 0 <= w <= 1
        assert bc.portfolio_house_edge(
            {"banker": w, "player": 1 - w}, 8
        ) == target


def test_stake_overall_headline_is_derived_portfolio_figure():
    # published constants (sec. 6): 1.10% overall edge <=> 98.90% RTP
    assert bc.STAKE_OVERALL_HOUSE_EDGE == Fraction("1.10") / 100
    assert bc.STAKE_OVERALL_RTP == Fraction("98.90") / 100
    assert bc.STAKE_OVERALL_HOUSE_EDGE + bc.STAKE_OVERALL_RTP == 1
    # 1.10% is NOT any single bet's edge — it is a genuine mix ...
    for bet in bc.BET_TYPES:
        assert Baccarat(bet, 8).house_edge_exact != bc.STAKE_OVERALL_HOUSE_EDGE
    # ... and the unique zero-tie mix is ~76.24% banker / 23.76% player
    w = bc.implied_banker_weight(bc.STAKE_OVERALL_HOUSE_EDGE, 8)
    assert round(100 * float(w), 2) == 76.24
    assert round(100 * float(1 - w), 2) == 23.76
    assert bc.portfolio_house_edge({"banker": w, "player": 1 - w}, 8) == (
        bc.STAKE_OVERALL_HOUSE_EDGE
    )


def test_overall_summary_block_reports_range_weights_and_assumption():
    ov = bc.overall_house_edge_summary(8)
    eb = Baccarat("banker", 8).house_edge_exact
    ep = Baccarat("player", 8).house_edge_exact
    assert ov["published_house_edge_exact"] == bc.STAKE_OVERALL_HOUSE_EDGE
    assert ov["published_rtp_exact"] == bc.STAKE_OVERALL_RTP
    assert ov["published_house_edge"] == pytest.approx(0.011)
    assert ov["published_rtp"] == pytest.approx(0.989)
    rng_blk = ov["achievable_house_edge_range"]
    assert rng_blk["min_exact"] == eb and rng_blk["max_exact"] == ep
    assert rng_blk["min_bet"] == "banker" and rng_blk["max_bet"] == "player"
    assert ov["within_achievable_range"] is True
    assert ov["reproduces_published_exactly"] is True
    we = ov["implied_weights_exact"]
    assert we["banker"] + we["player"] == 1 and we["tie"] == 0
    assert we["banker"] == bc.implied_banker_weight(
        bc.STAKE_OVERALL_HOUSE_EDGE, 8
    )
    # the zero-tie assumption is NAMED and quantified
    assert "tie" in ov["assumption"]
    assert 0 < ov["max_tie_weight_for_target"] < 0.01
    # other shoe models: 1.10% stays inside their banker/player ranges too
    for decks in (6, 1, None):
        o = bc.overall_house_edge_summary(decks)
        assert o["within_achievable_range"] is True
        assert o["reproduces_published_exactly"] is True
    # a target outside the achievable range is reported, never fabricated
    o = bc.overall_house_edge_summary(8, target=Fraction(1, 2))
    assert o["within_achievable_range"] is False
    assert o["implied_weights"] is None
    assert o["reproduces_published_exactly"] is False


def test_portfolio_and_inverse_reject_bad_inputs():
    good = {"banker": Fraction(1, 2), "player": Fraction(1, 2)}
    with pytest.raises(ValueError):
        bc.portfolio_house_edge({})                       # empty
    with pytest.raises(ValueError):
        bc.portfolio_house_edge(42)                       # not a mapping
    with pytest.raises(ValueError):
        bc.portfolio_house_edge({"dragon": 1})            # unknown bet
    with pytest.raises(ValueError):
        bc.portfolio_house_edge({"banker": 2})            # sum != 1
    with pytest.raises(ValueError):
        bc.portfolio_house_edge({"banker": Fraction(1, 2)})
    with pytest.raises(ValueError):
        bc.portfolio_house_edge({"banker": -1, "player": 2})   # negative
    with pytest.raises(ValueError):
        bc.portfolio_house_edge({"banker": 0.5, "player": 0.5})  # float
    with pytest.raises(ValueError):
        bc.portfolio_house_edge({"banker": True})         # bool
    with pytest.raises(ValueError):
        bc.portfolio_house_edge(good, decks=0)            # bad shoe
    with pytest.raises(ValueError):
        bc.portfolio_house_edge(good, tie_odds=0)         # bad tie odds
    with pytest.raises(ValueError):
        bc.implied_banker_weight(0.011)                   # float target
    with pytest.raises(ValueError):
        bc.implied_banker_weight(True)                    # bool target
    with pytest.raises(ValueError):
        bc.implied_banker_weight(Fraction(1, 100))        # below banker edge
    with pytest.raises(ValueError):
        bc.implied_banker_weight(Fraction(1, 2))          # above player edge
    with pytest.raises(ValueError):
        bc.implied_banker_weight(Fraction(11, 1000), decks=0)
    with pytest.raises(ValueError):
        bc.overall_house_edge_summary(8, target=0.011)    # float target


def test_engine_attributes_and_tables_are_tamper_proof():
    # payout_odds / tie_odds are read-only: mutating them cannot desync
    # the analytics fixed at construction
    eng = Baccarat("tie", 8)
    with pytest.raises(AttributeError):
        eng.payout_odds = Fraction(9)
    with pytest.raises(AttributeError):
        eng.tie_odds = Fraction(9)
    # module lookup tables are frozen (CARD_VALUES included)
    for arr in (bc.CARD_VALUES, bc.CARD_RANKS):
        with pytest.raises(ValueError):
            arr[0] = 1
    with pytest.raises(ValueError):
        bc.BANKER_DRAW_TABLE[0, 0] = False


def test_config_names_shoe_mechanism():
    assert Baccarat("player", 8).config()["shoe_mechanism"] == (
        "fisher_yates_without_replacement"
    )
    assert Baccarat("player", None).config()["shoe_mechanism"] == (
        "independent_floor_52"
    )
    assert bc.pair_summary(None, "player_pair")["config"]["shoe_mechanism"] == (
        "independent_floor_52"
    )


def test_total_grid_is_exact_and_consistent():
    grid, denom = bc.total_grid(8)
    assert grid.shape == (10, 10)
    assert int(grid.sum()) == denom
    # a natural-9 player total against banker 9 exists (tie cell nonzero)
    assert grid[9][9] > 0
    # denominator is the 6-card falling factorial of the 416-card shoe
    expect = 1
    for k in range(6):
        expect *= 416 - k
    assert denom == expect


def test_full_payout_table_structure():
    table = bc.full_payout_table(8)
    # main bets, the two 11:1 pair side bets (WoO's fifth column), AND the
    # "overall" block for Stake's headline blended figure
    assert set(table) == set(bc.BET_TYPES) | set(bc.PAIR_BET_TYPES) | {"overall"}
    for bet in bc.BET_TYPES + bc.PAIR_BET_TYPES:
        row = table[bet]
        assert set(row) >= {
            "rtp", "house_edge", "std_per_unit", "config",
            "payout_odds", "multiplier", "win_probability",
        }
        assert row["config"]["game"] == "baccarat"
    # every bet row's config shares ONE key set (a consumer reading e.g.
    # row["config"]["tie_odds"] must not crash on pair rows or vice versa)
    key_sets = {
        frozenset(table[bet]["config"])
        for bet in bc.BET_TYPES + bc.PAIR_BET_TYPES
    }
    assert len(key_sets) == 1
    for bet in bc.PAIR_BET_TYPES:
        assert table[bet]["payout_odds"] == "11:1"
        assert table[bet]["multiplier"] == 12.0
        assert table[bet]["config"]["rank_based"] is True
        assert table[bet]["config"]["tie_odds"] == "8:1"
    for bet in bc.BET_TYPES:
        assert table[bet]["config"]["rank_based"] is False
    # derived WoO-note figures are surfaced (no unreachable published cell)
    for bet in ("player", "banker"):
        assert table[bet]["house_edge_excluding_ties"] == pytest.approx(
            float(bc.house_edge_excluding_ties(bet, 8))
        )
    assert table["tie"]["house_edge_9to1"] == pytest.approx(
        Baccarat("tie", 8, tie_odds=Fraction(9)).house_edge
    )
    assert "house_edge_excluding_ties" not in table["tie"]
    # the overall block is the module-level summary, verbatim
    assert table["overall"] == bc.overall_house_edge_summary(8)


# ---------------------------------------------------------------------------
# pair side bets (11:1) — rank-level analytics (references/woo/baccarat.md)
# ---------------------------------------------------------------------------

def test_card_ranks_follow_published_layout():
    # published CARDS layout: 4 suits of each rank contiguous, ranks 2..A
    for idx in range(52):
        assert bc.card_rank(idx) == idx // 4
        assert bc.CARD_RANKS[idx] == idx // 4
    assert list(np.bincount(bc.CARD_RANKS, minlength=13)) == [4] * 13
    # ranks are FINER than values: 10/J/Q/K distinct ranks, same value 0
    assert len({bc.card_rank(i) for i in (32, 36, 40, 44)}) == 4
    assert len({bc.card_value(i) for i in (32, 36, 40, 44)}) == 1
    with pytest.raises(ValueError):
        bc.card_rank(52)
    with pytest.raises(ValueError):
        bc.card_rank(-1)


def test_pair_probability_exact_fractions():
    # finite D-deck shoe: (4D-1)/(52D-1); infinite: 1/13
    assert bc.pair_probability(8) == Fraction(31, 415)
    assert bc.pair_probability(6) == Fraction(23, 311)
    assert bc.pair_probability(1) == Fraction(1, 17)
    assert bc.pair_probability(None) == Fraction(1, 13)
    for decks in (0, -1, True, 2.5):
        with pytest.raises(ValueError):
            bc.pair_probability(decks)


def test_pair_house_edges_match_woo_all_deck_counts():
    # WoO pair column: 10.36% (8) / 11.25% (6) / 29.41% (1) / 7.69% (inf)
    assert round(100 * float(bc.pair_house_edge(8)), 2) == 10.36
    assert round(100 * float(bc.pair_house_edge(6)), 2) == 11.25
    assert round(100 * float(bc.pair_house_edge(1)), 2) == 29.41
    assert round(100 * float(bc.pair_house_edge(None)), 2) == 7.69
    # WoO 8-deck pair RTP 89.64%; identities hold exactly
    assert round(100 * float(bc.pair_rtp(8)), 2) == 89.64
    for decks in (8, 6, 1, None):
        p = bc.pair_probability(decks)
        assert bc.pair_rtp(decks) == 12 * p
        assert bc.pair_house_edge(decks) == 1 - 12 * p
        assert bc.pair_std_per_unit(decks) == pytest.approx(
            math.sqrt(float(144 * p * (1 - p)))
        )


def test_pair_payout_published_odds():
    assert bc.PAIR_PAYOUT_ODDS == Fraction(11)
    assert float(bc.PAIR_MULTIPLIER) == 12.0
    with pytest.raises(ValueError):
        bc.pair_summary(8, "dragon_pair")
    s = bc.pair_summary(None, "banker_pair")
    assert s["config"]["decks"] == "infinite"
    assert s["win_probability"] == pytest.approx(1 / 13)


def test_play_round_pair_flags_recompute_from_cards():
    n_pairs = 0
    for decks in (8, None):
        eng = Baccarat("player", decks)
        for nonce in range(150):
            r = eng.play_round(SS, CS, nonce)
            c = r["cards"]
            assert r["player_pair"] == (c[0] // 4 == c[2] // 4)
            assert r["banker_pair"] == (c[1] // 4 == c[3] // 4)
            n_pairs += r["player_pair"] + r["banker_pair"]
    assert n_pairs > 0    # ~1/13 per hand: 300 hands virtually surely hit


def test_deal_cards_bit_identical_to_play_round():
    for decks in (8, None):
        rng = BulkRng(SS, CS, nonce_start=500)
        cards = bc.deal_cards(rng, 60, decks)
        eng = Baccarat("tie", decks)
        for i in range(60):
            assert list(cards[i]) == eng.play_round(SS, CS, 500 + i)["cards"]
        assert rng.last_nonce_range == (500, 560)
    with pytest.raises(ValueError):
        bc.deal_cards(BulkRng(SS, CS, 0), 0, 8)


def test_simulate_pairs_tracks_exact_rank_analytics():
    n = 300_000
    for decks in (8, None):
        res = bc.simulate_pairs(n, decks=decks, bulk=BulkRng(SS, CS, 0),
                                progress=False)
        p = float(bc.pair_probability(decks))
        se = math.sqrt(p * (1 - p) / n)
        for bet in bc.PAIR_BET_TYPES:
            r = res["bets"][bet]
            assert abs(r["win_rate"] - p) < 4 * se, (decks, bet, r["z_score"])
            assert r["rtp"] == pytest.approx(12 * r["win_rate"])
            assert r["analytic_house_edge"] == pytest.approx(
                float(bc.pair_house_edge(decks))
            )
        # rank uniformity: 13-bin chi2 per dealt position, df 12 — mean 12,
        # generous ceiling (p ~ 2e-5) that a uniform shoe essentially
        # never trips at a fixed seed
        assert len(res["rank_chi2_per_position"]) == 6
        assert all(x < 45.0 for x in res["rank_chi2_per_position"]), res[
            "rank_chi2_per_position"
        ]
        counts = np.array(res["rank_counts"])
        assert counts.shape == (6, 13)
        assert (counts.sum(axis=1) == n).all()
        assert res["pass"] and res["n_rounds"] == n
    with pytest.raises(ValueError):
        bc.simulate_pairs(0)


def test_invalid_configs_rejected():
    with pytest.raises(ValueError):
        Baccarat("dragon", 8)
    with pytest.raises(ValueError):
        Baccarat("player", 0)
    with pytest.raises(ValueError):
        Baccarat("player", True)   # bool is not a deck count
    with pytest.raises(ValueError):
        bc.settle_values([1, 2, 3])
    with pytest.raises(ValueError):
        bc.card_value(52)


# ---------------------------------------------------------------------------
# provably-fair single round (scalar path)
# ---------------------------------------------------------------------------

def test_play_round_uses_published_card_mapping_infinite():
    """decks=None must reproduce Stake verbatim: floor(float * 52) per event."""
    eng = Baccarat("player", decks=None)
    for nonce in range(50):
        r = eng.play_round(SS, CS, nonce)
        floats = sq_rng.generate_floats(SS, CS, nonce, 0, 6)
        assert r["floats"] == floats
        assert r["cards"] == [math.floor(f * 52) for f in floats]
        assert r["cards"] == sq_rng.baccarat_cards(SS, CS, nonce)


def test_play_round_finite_shoe_never_repeats_a_physical_card():
    eng = Baccarat("banker", decks=8)
    for nonce in range(80):
        floats = sq_rng.generate_floats(SS, CS, nonce, 0, 6)
        ids = sq_rng.fisher_yates_draws(floats, 416)
        assert len(set(ids)) == 6                       # without replacement
        r = eng.play_round(SS, CS, nonce)
        assert r["cards"] == [i % 52 for i in ids]


def test_play_round_settlement_and_payout():
    codes = {"player": 0, "banker": 1, "tie": 2}
    for decks in (8, None):
        engines = {b: Baccarat(b, decks) for b in bc.BET_TYPES}
        for nonce in range(120):
            results = {b: e.play_round(SS, CS, nonce) for b, e in engines.items()}
            outcome = results["player"]["outcome"]
            assert len({r["outcome"] for r in results.values()}) == 1
            for b, r in results.items():
                if b == outcome:
                    assert r["win"] and not r["push"]
                    assert r["payout"] == float(bc.MULTIPLIERS[b])
                elif outcome == "tie":
                    assert r["push"] and not r["win"] and r["payout"] == 1.0
                else:
                    assert not r["win"] and not r["push"] and r["payout"] == 0.0
                # dealt cards partition into the two hands
                assert sorted(r["player_cards"] + r["banker_cards"]) == sorted(
                    [sq_rng.card_name(c) for c in r["cards"][: r["events_used"]]]
                )
                assert 2 <= len(r["player_cards"]) <= 3
                assert 2 <= len(r["banker_cards"]) <= 3
                # totals recompute from the hand cards
                pv = sum(bc.card_value(sq_rng.CARDS.index(c)) for c in r["player_cards"])
                bv = sum(bc.card_value(sq_rng.CARDS.index(c)) for c in r["banker_cards"])
                assert pv % 10 == r["player_total"]
                assert bv % 10 == r["banker_total"]
                assert r["verification"] == {
                    "server_seed": SS, "client_seed": CS, "nonce": nonce,
                }


def test_play_round_result_dict_contract():
    r = Baccarat("tie", 8).play_round(SS, CS, 0)
    for key in (
        "cards", "card_names", "player_cards", "banker_cards", "player_total",
        "banker_total", "outcome", "win", "push", "payout", "config",
        "verification", "events_used", "natural",
    ):
        assert key in r


# ---------------------------------------------------------------------------
# vectorized simulator: bit-identical to scalar play, standard result dict
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("decks", [8, None])
def test_bulk_deal_bit_identical_to_scalar_play(decks):
    n = 400
    rng = BulkRng(SS, CS, nonce_start=1000)
    outcomes = bc.deal_rounds(rng, n, decks)
    eng = Baccarat("player", decks)
    codes = {"player": 0, "banker": 1, "tie": 2}
    for i in range(n):
        assert codes[eng.play_round(SS, CS, 1000 + i)["outcome"]] == outcomes[i]
    assert rng.last_nonce_range == (1000, 1000 + n)     # one nonce per round


def test_cards_matrix_matches_scalar_fisher_yates():
    rng = BulkRng(SS, CS, 0)
    floats = rng.float_matrix(300, 6)
    cards = bc._cards_matrix(floats, 8)
    for i in range(300):
        expect = [x % 52 for x in sq_rng.fisher_yates_draws(list(floats[i]), 416)]
        assert list(cards[i]) == expect


def test_simulate_standard_result_dict_and_edges():
    n = 400_000
    res = bc.simulate_all_bets(
        n, decks=8, bulk=BulkRng(SS, CS, 0), progress=False
    )
    assert res["n_rounds"] == n
    assert sum(res["outcome_counts"].values()) == n
    for bet in bc.BET_TYPES:
        r = res["bets"][bet]
        for key in ("rtp", "house_edge", "std_per_unit", "config"):
            assert key in r
        assert r["within_3se"], (bet, r["z_score"])
        assert abs(r["std_per_unit"] - r["analytic_std_per_unit"]) < 0.05
        assert r["config"]["bet_type"] == bet
    # per-bet Baccarat.simulate agrees with the shared-campaign settle
    single = Baccarat("banker", 8).simulate(
        50_000, bulk=BulkRng(SS, CS, 0), progress=False
    )
    assert single["n_rounds"] == 50_000
    assert single["within_3se"]
    assert "verification" in single and "rtp" in single


def test_simulate_rejects_bad_args():
    with pytest.raises(ValueError):
        bc.simulate_all_bets(0)
    with pytest.raises(ValueError):
        bc.simulate_all_bets(10, bets=("player", "lucky6"))


def test_payouts_for_outcomes_lookup():
    outcomes = np.array([0, 1, 2, 0, 2])
    assert list(Baccarat("player", 8).payouts_for_outcomes(outcomes)) == [
        2.0, 0.0, 1.0, 2.0, 1.0
    ]
    assert list(Baccarat("banker", 8).payouts_for_outcomes(outcomes)) == [
        0.0, 1.95, 1.0, 0.0, 1.0
    ]
    assert list(Baccarat("tie", 8).payouts_for_outcomes(outcomes)) == [
        0.0, 0.0, 9.0, 0.0, 9.0
    ]


# ---------------------------------------------------------------------------
# validation-script hardening: machine-readable summary must survive
# argument errors and internal crashes (gauntlet round-4 gap)
# ---------------------------------------------------------------------------

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "validate_baccarat.py"


def _run_validator(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True, text=True, timeout=300,
        cwd=str(_SCRIPT.parent.parent),
    )


def _json_line(stdout: str) -> dict:
    lines = [l for l in stdout.splitlines()
             if l.startswith("BACCARAT_VALIDATION_JSON: ")]
    assert len(lines) == 1, "exactly one machine-readable summary line"
    return json.loads(lines[0].split(": ", 1)[1])


def test_validator_analytic_gates_pass_and_emit_json():
    # --skip-sim runs gates 1-2 (payout-for-payout + WoO analytics) fast
    proc = _run_validator("--skip-sim")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    j = _json_line(proc.stdout)
    assert j["pass"] is True and j["failed"] == []
    assert j["checks_passed"] == j["checks_total"] >= 50
    assert j["game"] == "baccarat" and j["empirical"] is None
    a = j["analytic"]
    assert round(100 * a["banker"]["house_edge"], 2) == 1.06
    assert round(100 * a["player"]["house_edge"], 2) == 1.24
    assert round(100 * a["tie"]["house_edge"], 2) == 14.36
    assert round(100 * a["player_pair"]["house_edge"], 2) == 10.36
    # derived WoO-note figures reach the machine-readable summary too
    assert round(100 * a["banker"]["house_edge_excluding_ties"], 2) == 1.17
    assert round(100 * a["player"]["house_edge_excluding_ties"], 2) == 1.36
    assert round(100 * a["tie"]["house_edge_9to1"], 2) == 4.84
    # Stake's headline blended figure — derived, exact, in the summary
    ov = a["overall"]
    assert round(100 * ov["published_house_edge"], 2) == 1.10
    assert round(100 * ov["published_rtp"], 2) == 98.90
    assert round(100 * ov["implied_weights"]["banker"], 2) == 76.24
    assert round(100 * ov["implied_weights"]["player"], 2) == 23.76
    assert ov["implied_weights"]["tie"] == 0.0
    assert ov["reproduces_published_exactly"] is True
    lo, hi = ov["achievable_house_edge_range"]
    assert round(100 * lo, 4) == 1.0579 and round(100 * hi, 4) == 1.2351


def test_validator_small_sim_reports_empirical_block():
    proc = _run_validator("--rounds", "60000")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    j = _json_line(proc.stdout)
    assert j["pass"] is True
    emp = j["empirical"]
    assert emp["n_rounds"] == 60000
    assert set(emp["bets"]) == set(bc.BET_TYPES)
    assert all(emp["bets"][b]["within_3se"] for b in bc.BET_TYPES)
    assert set(emp["pair_bets"]) == set(bc.PAIR_BET_TYPES)
    assert emp["verification"]["nonce_range"] == [0, 60000]


def test_validator_rejects_bad_arguments():
    for args in (("--rounds", "0"), ("--seed", "nothex"), ("--client", "")):
        proc = _run_validator(*args)
        assert proc.returncode == 2, args           # argparse usage error
        assert "error:" in proc.stderr


def test_validator_crash_still_emits_failing_json(tmp_path):
    """A broken reference file must yield exit 1 + a pass:false JSON line,
    never a bare traceback with no machine-readable verdict."""
    code = (
        "import sys, importlib.util, pathlib\n"
        f"spec = importlib.util.spec_from_file_location('vb', {str(_SCRIPT)!r})\n"
        "vb = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(vb)\n"
        "vb.STAKE_MD = pathlib.Path('/nonexistent/baccarat.md')\n"
        "sys.argv = ['validate_baccarat.py', '--skip-sim']\n"
        "sys.exit(vb.main())\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                          text=True, timeout=120)
    assert proc.returncode == 1
    j = _json_line(proc.stdout)
    assert j["pass"] is False
    assert any("without exceptions" in name for name in j["failed"])
    assert any("check-count floor" in name for name in j["failed"])


def test_empirical_outcome_frequencies_track_exact_probabilities():
    """200k rounds per shoe model: each outcome frequency within 4 SE of its
    own exact probability (binomial SE)."""
    n = 200_000
    for decks in (8, None):
        res = bc.simulate_all_bets(
            n, decks=decks, bulk=BulkRng(SS, CS, 0), progress=False
        )
        probs = bc.outcome_probabilities(decks)
        for i, name in enumerate(("player", "banker", "tie")):
            p = float(probs[name])
            se = math.sqrt(p * (1 - p) / n)
            emp = res["outcome_counts"][name] / n
            assert abs(emp - p) < 4 * se, (decks, name, emp, p)
