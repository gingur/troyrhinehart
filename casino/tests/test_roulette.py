"""Tests for the European single-zero Roulette engine.

Ground truth: references/stake/roulette.md (payouts, pocket mapping, colors)
and references/woo/roulette.md (per-bet SD figures and formula).
"""

from __future__ import annotations

import math
from fractions import Fraction

import numpy as np
import pytest

from spinquest_sim import rng as sq_rng
from spinquest_sim.games import roulette as rl
from spinquest_sim.games.roulette import Roulette
from spinquest_sim.rng import BulkRng

RTP_EXACT = Fraction(36, 37)


# ---------------------------------------------------------------------------
# Bet enumeration / layout
# ---------------------------------------------------------------------------

def test_bet_enumeration_counts():
    assert len(rl.all_splits()) == 60      # 24 horizontal + 33 vertical + 3 zero
    assert len(rl.all_streets()) == 12
    assert len(rl.zero_trios()) == 2
    assert len(rl.all_corners()) == 22
    assert len(rl.first_four()) == 4
    assert len(rl.all_lines()) == 11
    # Standard 157-bet European catalogue:
    # street bets = 12 rows + 2 zero trios; corner bets = 22 + first four.
    assert len(rl.all_bets()) == 37 + 60 + (12 + 2) + (22 + 1) + 11 + 3 + 3 + 6 == 157


def test_split_geometry():
    splits = set(rl.all_splits())
    assert {(0, 1), (0, 2), (0, 3)} <= splits          # zero splits
    assert (17, 20) in splits and (17, 18) in splits   # vertical + horizontal
    assert (3, 4) not in splits                        # row boundary
    assert (33, 36) in splits and (36, 37) not in splits
    for a, b in splits:
        assert (b - a == 3) or (b - a == 1 and a % 3 != 0) or a == 0


def test_streets_corners_lines_cover_expected_pockets():
    assert rl.all_streets()[0] == (1, 2, 3)
    assert rl.all_streets()[-1] == (34, 35, 36)
    assert rl.all_corners()[0] == (1, 2, 4, 5)
    assert rl.all_corners()[-1] == (32, 33, 35, 36)
    assert rl.all_lines()[0] == (1, 2, 3, 4, 5, 6)
    assert rl.all_lines()[-1] == (31, 32, 33, 34, 35, 36)
    for c in rl.all_corners():
        n = c[0]
        assert c == (n, n + 1, n + 3, n + 4) and n % 3 in (1, 2)


def test_dozens_columns():
    assert rl.dozen_pockets(1) == tuple(range(1, 13))
    assert rl.dozen_pockets(3) == tuple(range(25, 37))
    assert rl.column_pockets(1) == tuple(range(1, 37, 3))
    assert rl.column_pockets(3) == tuple(range(3, 37, 3))
    covered = set()
    for i in (1, 2, 3):
        covered |= set(rl.column_pockets(i))
    assert covered == set(range(1, 37))


def test_colors_match_reference():
    # Verbatim lists from references/stake/roulette.md
    ref_red = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
    ref_black = {2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35}
    assert rl.RED_NUMBERS == frozenset(ref_red)
    assert rl.BLACK_NUMBERS == frozenset(ref_black)
    assert rl.pocket_color(0) == "green"
    assert len(rl.RED_NUMBERS) == len(rl.BLACK_NUMBERS) == 18
    assert rl.RED_NUMBERS.isdisjoint(rl.BLACK_NUMBERS)


def test_zero_loses_every_outside_bet():
    """A pocket of 0 loses all bets that do not cover 0 (reference, sec. 5).

    Exactly 7 bets cover 0: straight 0, the 3 zero splits, the 2 zero trios
    and the first four.  Every other bet — every outside bet included — must
    NOT cover 0."""
    covering = []
    for bet_type, sel in rl.all_bets():
        eng = Roulette(bet_type, sel)
        covers_zero = (bet_type == "straight" and sel == 0) or (
            isinstance(sel, tuple) and 0 in sel
        )
        assert (0 in eng.covered) == covers_zero, (bet_type, sel)
        if 0 in eng.covered:
            covering.append((bet_type, sel))
    assert len(covering) == 7


# ---------------------------------------------------------------------------
# (a) analytics: payouts, RTP, variance
# ---------------------------------------------------------------------------

def test_published_payout_odds():
    """Payout-for-payout vs the Stake table (winnings odds / total return)."""
    expected = {
        "straight": (35, 36, 1),
        "split": (17, 18, 2),
        "street": (11, 12, 3),
        "corner": (8, 9, 4),
        "line": (5, 6, 6),
        "dozen": (2, 3, 12),
        "column": (2, 3, 12),
        "red": (1, 2, 18),
        "black": (1, 2, 18),
        "odd": (1, 2, 18),
        "even": (1, 2, 18),
        "low": (1, 2, 18),
        "high": (1, 2, 18),
    }
    assert set(expected) == set(rl.BET_TYPES)
    table = rl.full_payout_table()
    for bet_type, (odds, mult, cov) in expected.items():
        row = table[bet_type]
        assert row["payout_odds"] == f"{odds}:1"
        assert row["multiplier"] == mult
        assert row["coverage"] == cov
        assert row["win_probability"] == cov / 37


def test_every_bet_has_exact_uniform_rtp():
    for bet_type, sel in rl.all_bets():
        eng = Roulette(bet_type, sel)
        assert eng.rtp_exact == RTP_EXACT, (bet_type, sel)
        assert eng.multiplier_exact == Fraction(36, eng.coverage)
        assert math.isclose(eng.house_edge, 1 / 37, rel_tol=0, abs_tol=1e-15)
        assert math.isclose(eng.rtp, 0.972972972972973, abs_tol=1e-15)


def test_std_matches_woo_figures():
    """references/woo/roulette.md single-zero derived SDs: even money
    0.999635, single number 5.837800 (the latter is 5.8378 zero-padded —
    WoO's own formula sqrt((35^2+36)/37 - (1/37)^2) = 5.8378379...)."""
    even = Roulette("red")
    straight = Roulette("straight", 17)
    # Exact per WoO's stated formula
    assert math.isclose(
        even.std_per_unit, math.sqrt(1 - (1 / 37) ** 2), rel_tol=0, abs_tol=1e-12
    )
    assert math.isclose(
        straight.std_per_unit,
        math.sqrt((35**2 + 36) / 37 - (1 / 37) ** 2),
        rel_tol=0,
        abs_tol=1e-12,
    )
    # Printed figures to their reliable precision
    assert round(even.std_per_unit, 6) == 0.999635
    assert round(straight.std_per_unit, 4) == 5.8378


def test_variance_equals_binomial_formula():
    for bet_type, sel in [
        ("straight", 0), ("split", (0, 2)), ("street", (4, 5, 6)),
        ("corner", (14, 15, 17, 18)), ("line", (7, 8, 9, 10, 11, 12)),
        ("dozen", 2), ("column", 3), ("high", None),
    ]:
        eng = Roulette(bet_type, sel)
        m, p = eng.multiplier, eng.win_probability
        assert math.isclose(
            eng.variance_per_unit, m * m * p * (1 - p), rel_tol=1e-14
        )


def test_analytic_summary_contract():
    summary = Roulette("dozen", 2).analytic_summary()
    assert set(summary) == {"rtp", "house_edge", "std_per_unit", "config"}
    cfg = summary["config"]
    assert cfg["game"] == "roulette"
    assert cfg["wheel"] == "european_single_zero"
    assert cfg["covered"] == list(range(13, 25))
    assert cfg["payout_odds"] == "2:1"


# ---------------------------------------------------------------------------
# Bet validation
# ---------------------------------------------------------------------------

def test_invalid_bets_rejected():
    with pytest.raises(ValueError):
        Roulette("five_number")            # American-only bet
    with pytest.raises(ValueError):
        Roulette("basket")
    with pytest.raises(ValueError):
        Roulette("straight", 37)
    with pytest.raises(TypeError):
        Roulette("straight", None)
    with pytest.raises(TypeError):
        Roulette("straight", True)
    with pytest.raises(ValueError):
        Roulette("split", (1, 5))          # not adjacent
    with pytest.raises(ValueError):
        Roulette("split", (3, 4))          # row boundary
    with pytest.raises(ValueError):
        Roulette("street", (2, 3, 4))      # not a mat row
    with pytest.raises(ValueError):
        Roulette("corner", (3, 4, 6, 7))   # crosses row boundary
    with pytest.raises(ValueError):
        Roulette("line", (4, 5, 6, 7, 8, 10))
    with pytest.raises(ValueError):
        Roulette("dozen", 0)
    with pytest.raises(ValueError):
        Roulette("column", 4)
    with pytest.raises(TypeError):
        Roulette("red", 5)                 # even-money takes no selection
    with pytest.raises(TypeError):
        Roulette("split", 17)


def test_selection_order_normalized():
    assert Roulette("split", (20, 17)).selection == (17, 20)
    assert Roulette("corner", (5, 1, 4, 2)).selection == (1, 2, 4, 5)


def test_zero_trios_and_first_four():
    """The mat is coherent about zero adjacency: having the zero splits, the
    zero trios (street payout) and first four (corner payout) are legal too."""
    for trio in ((0, 1, 2), (0, 2, 3)):
        eng = Roulette("street", trio)
        assert eng.coverage == 3
        assert eng.multiplier == 12.0 and eng.payout_odds == 11
        assert eng.rtp_exact == RTP_EXACT
    ff = Roulette("corner", (0, 1, 2, 3))
    assert ff.coverage == 4
    assert ff.multiplier == 9.0 and ff.payout_odds == 8
    assert ff.rtp_exact == RTP_EXACT
    # Shapes that do NOT follow from the zero adjacency stay illegal.
    with pytest.raises(ValueError):
        Roulette("street", (0, 1, 3))      # not a trio (1 and 3 not adjacent via 0's corner)
    with pytest.raises(ValueError):
        Roulette("street", (0, 3, 4))
    with pytest.raises(ValueError):
        Roulette("corner", (0, 1, 2, 4))
    with pytest.raises(ValueError):
        Roulette("split", (0, 4))          # 0 borders only the first row


# ---------------------------------------------------------------------------
# (b) provably-fair single round
# ---------------------------------------------------------------------------

_SRV = "a" * 64
_CLIENT = "clientseed"


def test_play_round_known_vector():
    """Pinned vector: serverSeed 'a'*64, clientSeed 'clientseed', nonce 1
    -> float 0.4767664363607764 -> pocket 17 (black)."""
    res = Roulette("straight", 17).play_round(_SRV, _CLIENT, 1)
    assert res["pocket"] == 17
    assert res["color"] == "black"
    assert res["win"] is True
    assert res["payout"] == 36.0
    assert math.isclose(res["float"], 0.4767664363607764, rel_tol=0, abs_tol=1e-15)
    # First five nonces pinned (deterministic replay of the verifier)
    pockets = [
        Roulette("red").play_round(_SRV, _CLIENT, n)["pocket"] for n in range(5)
    ]
    assert pockets == [21, 17, 2, 0, 5]


def test_play_round_matches_scalar_rng_path():
    for nonce in range(20):
        res = Roulette("black").play_round(_SRV, _CLIENT, nonce)
        f = sq_rng.generate_floats(_SRV, _CLIENT, nonce, 0, 1)[0]
        assert res["pocket"] == sq_rng.roulette_pocket(f)
        assert res["win"] == (res["pocket"] in rl.BLACK_NUMBERS)
        assert res["payout"] == (2.0 if res["win"] else 0.0)
        assert res["verification"]["nonce"] == nonce


def test_play_round_settles_all_bet_types_consistently():
    for nonce in range(15):
        pocket = Roulette("red").play_round(_SRV, _CLIENT, nonce)["pocket"]
        for bet_type, sel in rl.all_bets():
            eng = Roulette(bet_type, sel)
            res = eng.play_round(_SRV, _CLIENT, nonce)
            assert res["pocket"] == pocket
            expected = eng.multiplier if pocket in eng.covered else 0.0
            assert res["payout"] == expected, (bet_type, sel, pocket)


# ---------------------------------------------------------------------------
# (c) vectorized simulator
# ---------------------------------------------------------------------------

def test_bulk_pockets_match_scalar_path():
    bulk = BulkRng(_SRV, _CLIENT, nonce_start=0, workers=1)
    pockets = bulk.roulette_pockets(200)
    for i in range(200):
        f = sq_rng.generate_floats(_SRV, _CLIENT, i, 0, 1)[0]
        assert pockets[i] == sq_rng.roulette_pocket(f)


def test_payouts_for_pockets():
    eng = Roulette("dozen", 1)
    pockets = np.array([0, 1, 12, 13, 36])
    np.testing.assert_allclose(
        eng.payouts_for_pockets(pockets), [0.0, 3.0, 3.0, 0.0, 0.0]
    )


def test_payouts_for_pockets_rejects_out_of_range():
    """No silent wraparound: -1 must NOT settle as pocket 36 (numpy fancy
    indexing would happily wrap it), and >= 37 / non-integer dtypes raise."""
    eng = Roulette("red")
    with pytest.raises(ValueError):
        eng.payouts_for_pockets(np.array([-1]))
    with pytest.raises(ValueError):
        eng.payouts_for_pockets(np.array([0, 5, -3, 12]))
    with pytest.raises(ValueError):
        eng.payouts_for_pockets(np.array([37]))
    with pytest.raises(TypeError):
        eng.payouts_for_pockets(np.array([1.5]))
    # Empty input is fine (settles to an empty payout array)
    assert eng.payouts_for_pockets(np.array([], dtype=np.int64)).size == 0


def test_settle_bets_multi_bet_basket():
    """Shared-spin settlement of a simultaneous basket (multi-bet API)."""
    basket = [Roulette("red"), Roulette("straight", 0), Roulette("dozen", 1)]
    pockets = np.array([0, 1, 13, 36])
    # pocket 0: straight-0 pays 36; pocket 1: red 2 + dozen1 3 = 5;
    # pocket 13: nothing; pocket 36: red 2.
    np.testing.assert_allclose(
        rl.settle_bets(pockets, basket), [36.0, 5.0, 0.0, 2.0]
    )
    with pytest.raises(ValueError):
        rl.settle_bets(pockets, [])
    with pytest.raises(ValueError):
        rl.settle_bets(np.array([-1]), basket)
    # Basket EV is still 36/37 per unit staked: settle the basket over the
    # full wheel (each pocket once) — total payout is 36 * n_bets exactly.
    wheel = np.arange(37)
    assert rl.settle_bets(wheel, basket).sum() == 36.0 * len(basket)


def test_basket_analytics_single_bet_matches_per_bet_analytics():
    for bt, sel in [("red", None), ("straight", 0), ("dozen", 2),
                    ("corner", (0, 1, 2, 3))]:
        eng = Roulette(bt, sel)
        ana = rl.basket_analytics([eng])
        assert ana["rtp_exact"] == RTP_EXACT
        assert ana["ev_exact"] == (
            eng.multiplier_exact * eng.win_probability_exact
        )
        assert math.isclose(ana["variance"], eng.variance_per_unit,
                            rel_tol=1e-14)
        assert math.isclose(ana["std"], eng.std_per_unit, rel_tol=1e-14)


def test_basket_analytics_matches_full_wheel_brute_force():
    """Exact Fraction moments == brute-force numpy moments of settle_bets
    over the full wheel (each pocket exactly once, uniform)."""
    basket = [Roulette("red"), Roulette("straight", 0), Roulette("dozen", 1),
              Roulette("split", (0, 2)), Roulette("corner", (25, 26, 28, 29)),
              Roulette("line", (13, 14, 15, 16, 17, 18)),
              Roulette("column", 2)]
    ana = rl.basket_analytics(basket)
    wheel = rl.settle_bets(np.arange(37), basket)
    # per-pocket totals agree pointwise with the settlement path
    np.testing.assert_allclose(
        np.array([float(t) for t in ana["pocket_totals_exact"]]), wheel
    )
    assert math.isclose(ana["ev"], wheel.mean(), rel_tol=1e-12)
    assert math.isclose(ana["variance"], wheel.var(), rel_tol=1e-12)
    assert math.isclose(
        ana["mu4"], float(((wheel - wheel.mean()) ** 4).mean()), rel_tol=1e-12
    )
    assert ana["rtp_exact"] == RTP_EXACT
    assert ana["ev_exact"] == Fraction(36, 37) * len(basket)


def test_basket_analytics_covariance_is_real():
    """Overlap moves basket variance away from the sum of per-bet variances
    (same EV either way) — the analytic counterpart genuinely models
    covariance, it is not a per-bet restatement."""
    sum_var = 2 * Roulette("red").variance_per_unit
    overlapping = rl.basket_analytics([Roulette("red"), Roulette("high")])
    disjoint = rl.basket_analytics([Roulette("red"), Roulette("black")])
    assert overlapping["ev_exact"] == disjoint["ev_exact"] == Fraction(72, 37)
    assert overlapping["variance"] > sum_var   # positive covariance
    assert disjoint["variance"] < sum_var      # negative covariance
    # red+black exact: T = 2 unless pocket 0 -> Var = 4*(36/37) - (72/37)^2
    assert disjoint["variance_exact"] == (
        Fraction(4 * 36, 37) - Fraction(72, 37) ** 2
    )


def test_basket_analytics_rejects_empty():
    with pytest.raises(ValueError):
        rl.basket_analytics([])


def test_simulate_contract_and_reproducibility():
    n = 100_000
    res = Roulette("red").simulate(
        n, bulk=BulkRng(_SRV, _CLIENT, workers=1), progress=False
    )
    for key in (
        "rtp", "house_edge", "std_per_unit", "config", "n_rounds", "wins",
        "win_rate", "analytic_rtp", "analytic_std_per_unit", "se_rtp",
        "z_score", "within_3se", "rounds_per_sec", "verification",
    ):
        assert key in res
    assert res["n_rounds"] == n
    assert res["verification"]["nonce_range"] == (0, n)
    assert res["verification"]["server_seed_hash"] == sq_rng.hash_server_seed(_SRV)
    assert int(res["pocket_counts"].sum()) == n
    # Deterministic replay: same seeds -> identical result
    res2 = Roulette("red").simulate(
        n, bulk=BulkRng(_SRV, _CLIENT, workers=1), progress=False
    )
    assert res2["wins"] == res["wins"]
    # Sanity: within 5 SE of analytic on this fixed stream (measured ~ -0.6 SE)
    assert abs(res["z_score"]) < 5.0
    # Cross-check the counted wins against the analytic settle of the pockets
    assert math.isclose(res["rtp"], res["win_rate"] * 2.0, rel_tol=1e-12)


def test_simulate_chunking_matches_single_call():
    a = Roulette("straight", 7).simulate(
        50_000, bulk=BulkRng(_SRV, _CLIENT, workers=1),
        chunk_rounds=7_777, progress=False,
    )
    b = Roulette("straight", 7).simulate(
        50_000, bulk=BulkRng(_SRV, _CLIENT, workers=1), progress=False
    )
    assert a["wins"] == b["wins"]
    np.testing.assert_array_equal(a["pocket_counts"], b["pocket_counts"])


def test_simulate_rejects_bad_rounds():
    with pytest.raises(ValueError):
        Roulette("red").simulate(0)
    with pytest.raises(ValueError):
        Roulette("red").simulate(-1)


@pytest.mark.parametrize(
    "bad",
    [float("inf"), float("nan"), 2.5, 1e6, np.float64(10.0), True, "1000",
     None],
)
def test_simulate_rejects_non_integral_n_rounds(bad):
    """Root guard for the round-4 bug class: n_rounds=inf passes an `<= 0`
    guard (inf <= 0 is False) and `while done < n_rounds` never terminates;
    n_rounds=nan makes every comparison False, so the loop body never runs
    and simulate would RETURN a normal-looking dict (wins=0, within_3se=True)
    for a campaign that never happened.  json.loads parses bare Infinity/NaN
    by default, so JSON/MCP callers inherit both.  Every non-Integral (and
    bool) must raise TypeError up front."""
    with pytest.raises(TypeError, match="n_rounds"):
        Roulette("red").simulate(
            bad, bulk=BulkRng(_SRV, _CLIENT, workers=1), progress=False
        )


@pytest.mark.parametrize(
    "bad", [float("inf"), float("nan"), 0.5, 2.0, np.float32(4.0), True]
)
def test_simulate_rejects_non_integral_chunk_rounds(bad):
    # Same root guard on the other loop counter: a float chunk_rounds used
    # to die with a raw numpy "an integer is required" deep inside BulkRng
    # (and inf/nan would corrupt the chunking arithmetic silently).
    with pytest.raises(TypeError, match="chunk_rounds"):
        Roulette("red").simulate(
            1000, bulk=BulkRng(_SRV, _CLIENT, workers=1),
            chunk_rounds=bad, progress=False,
        )


def test_simulate_accepts_numpy_integers():
    # numpy integers ARE numbers.Integral and must keep working.
    res = Roulette("red").simulate(
        np.int64(500), bulk=BulkRng(_SRV, _CLIENT, workers=1),
        chunk_rounds=np.int32(128), progress=False,
    )
    assert res["n_rounds"] == 500
    assert int(res["pocket_counts"].sum()) == 500
    ref = Roulette("red").simulate(
        500, bulk=BulkRng(_SRV, _CLIENT, workers=1), progress=False
    )
    assert res["wins"] == ref["wins"]


@pytest.mark.parametrize("bad_chunk", [0, -1, -5])
def test_simulate_rejects_nonpositive_chunk_rounds(bad_chunk):
    # chunk_rounds=0 used to make step = min(0, remaining) = 0 and loop
    # forever with no error or output; negative values only raised
    # incidentally from deeper in the RNG.  Both must raise up front.
    with pytest.raises(ValueError, match="chunk_rounds"):
        Roulette("red").simulate(
            1000, bulk=BulkRng(_SRV, _CLIENT, workers=1),
            chunk_rounds=bad_chunk, progress=False,
        )


def test_simulate_chunk_rounds_one_terminates_and_matches():
    # Boundary just above the guard: chunk_rounds=1 must terminate and
    # replay the exact same stream as one default-sized chunk.
    a = Roulette("red").simulate(
        50, bulk=BulkRng(_SRV, _CLIENT, workers=1),
        chunk_rounds=1, progress=False,
    )
    b = Roulette("red").simulate(
        50, bulk=BulkRng(_SRV, _CLIENT, workers=1), progress=False
    )
    assert a["wins"] == b["wins"]
    np.testing.assert_array_equal(a["pocket_counts"], b["pocket_counts"])
