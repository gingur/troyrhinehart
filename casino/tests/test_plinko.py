"""Tests for spinquest_sim.games.plinko against references/stake/plinko.md
and references/woo/plinko.md (the only ground truth)."""

import math

import numpy as np
import pytest

from spinquest_sim import rng as sq_rng
from spinquest_sim.games.plinko import (
    MAX_ROWS,
    MIN_ROWS,
    PAYTABLES,
    PlinkoEngine,
    RISKS,
    pascal_probabilities,
)

# ---------------------------------------------------------------------------
# Verbatim reference data
# ---------------------------------------------------------------------------

# Stake "Playing Sizes" tables (references/stake/plinko.md section 4):
# (risk, rows) -> (# of destinations, min win, max win)
STAKE_PLAYING_SIZES = {
    ("low", 8): (9, 0.5, 5.6),
    ("low", 9): (10, 0.7, 5.6),
    ("low", 10): (11, 0.5, 8.9),
    ("low", 11): (12, 0.7, 8.4),
    ("low", 12): (13, 0.5, 10),
    ("low", 13): (14, 0.7, 8.1),
    ("low", 14): (15, 0.5, 7.1),
    ("low", 15): (16, 0.7, 15),
    ("low", 16): (17, 0.5, 16),
    ("medium", 8): (9, 0.4, 13),
    ("medium", 9): (10, 0.5, 18),
    ("medium", 10): (11, 0.4, 22),
    ("medium", 11): (12, 0.5, 24),
    ("medium", 12): (13, 0.3, 33),
    ("medium", 13): (14, 0.4, 43),
    ("medium", 14): (15, 0.2, 58),
    ("medium", 15): (16, 0.3, 88),
    ("medium", 16): (17, 0.3, 110),
    ("high", 8): (9, 0.2, 29),
    ("high", 9): (10, 0.2, 43),
    ("high", 10): (11, 0.2, 76),
    ("high", 11): (12, 0.2, 120),
    ("high", 12): (13, 0.2, 170),
    ("high", 13): (14, 0.2, 260),
    ("high", 14): (15, 0.2, 420),
    ("high", 15): (16, 0.2, 620),
    ("high", 16): (17, 0.2, 1000),
}

# WoO full-table anchors (references/woo/plinko.md)
WOO_LOW_8 = [5.6, 2.1, 1.1, 1, 0.5, 1, 1.1, 2.1, 5.6]
WOO_MEDIUM_16 = [110, 41, 10, 5, 3, 1.5, 1, 0.5, 0.3,
                 0.5, 1, 1.5, 3, 5, 10, 41, 110]
# BetFury "Red" on the WoO page is the 1000x Stake/BGAMING 16-high table.
WOO_BETFURY_RED_16 = [1000, 130, 26, 9, 4, 2, 0.2, 0.2, 0.2,
                      0.2, 0.2, 2, 4, 9, 26, 130, 1000]

# WoO CryptoGames tables (16 rows, 17 positions) with the page's published
# RTP (%) and per-drop standard deviation (6 decimals) — the only SD figures
# the reference publishes anywhere.
WOO_CRYPTOGAMES = {
    # name: (payout table, published RTP %, published SD)
    "green": ([10, 8, 6, 3, 2, 1.3, 1, 0.8, 0.5, 0.8, 1, 1.3, 2, 3, 6, 8, 10],
              98.37, 0.562711),
    "red": ([20, 7, 5, 3, 2, 1.1, 1, 0.6, 1, 0.6, 1, 1.1, 2, 3, 5, 7, 20],
            98.16, 0.517632),
    "blue": ([50, 8, 3, 2, 1.4, 1.2, 1.1, 1, 0.4, 1, 1.1, 1.2, 1.4, 2, 3, 8, 50],
             98.48, 0.464829),
    "yellow": ([650, 30, 7, 3, 1.5, 1.2, 1, 0.7, 0.7, 0.7, 1, 1.2, 1.5, 3, 7,
                30, 650],
               98.09, 3.678698),
}

# WoO BetFury tables (16 rows) with the page's published RTP (%).
WOO_BETFURY = {
    "blue": ([16, 5, 2, 1.3, 1.2, 0.2, 1.1, 1.1, 1, 1.1, 1.1, 0.2, 1.2, 1.3,
              2, 5, 16],
             97.88),
    "green": ([110, 41, 10, 5, 2.8, 1.5, 1, 0.5, 0.3, 0.5, 1, 1.5, 2.8, 5, 10,
               41, 110],
              97.88),
    "red": ([1000, 130, 26, 9, 4, 2, 0.2, 0.2, 0.2, 0.2, 0.2, 2, 4, 9, 26,
             130, 1000],
            98.98),
}

# WoO BGAMING RTP grid (percent, 2 decimals). The Low column on the captured
# page duplicates the Medium column row-for-row (a transcription artifact —
# see validate_plinko.py), so exact-match assertions cover medium and high.
WOO_RTP = {
    ("medium", 8): 98.91, ("medium", 9): 99.14, ("medium", 10): 98.91,
    ("medium", 11): 99.02, ("medium", 12): 98.99, ("medium", 13): 98.99,
    ("medium", 14): 98.99, ("medium", 15): 99.00, ("medium", 16): 98.99,
    ("high", 8): 99.06, ("high", 9): 99.06, ("high", 10): 99.06,
    ("high", 11): 99.16, ("high", 12): 99.12, ("high", 13): 99.09,
    ("high", 14): 98.98, ("high", 15): 99.03, ("high", 16): 98.98,
}

ALL_CONFIGS = [(risk, rows) for risk in RISKS
               for rows in range(MIN_ROWS, MAX_ROWS + 1)]


def engines():
    return [PlinkoEngine(rows=rows, risk=risk) for risk, rows in ALL_CONFIGS]


# ---------------------------------------------------------------------------
# Paytable grid vs the Stake reference (all 27 configs)
# ---------------------------------------------------------------------------

def test_grid_has_all_27_configs():
    assert set(PAYTABLES) == set(STAKE_PLAYING_SIZES)
    assert len(PAYTABLES) == 27


@pytest.mark.parametrize("risk,rows", ALL_CONFIGS)
def test_destinations_min_max_match_stake_tables(risk, rows):
    eng = PlinkoEngine(rows=rows, risk=risk)
    destinations, min_win, max_win = STAKE_PLAYING_SIZES[(risk, rows)]
    assert eng.pockets == destinations == rows + 1
    assert len(eng.payouts) == destinations
    assert float(eng.payouts.min()) == pytest.approx(min_win, abs=0)
    assert float(eng.payouts.max()) == pytest.approx(max_win, abs=0)


@pytest.mark.parametrize("risk,rows", ALL_CONFIGS)
def test_tables_symmetric_edge_max_center_min_region(risk, rows):
    eng = PlinkoEngine(rows=rows, risk=risk)
    p = eng.payouts
    assert np.array_equal(p, p[::-1]), "pay table must be symmetric"
    # max at the edges, min at/near the center
    assert p[0] == p.max()
    center = rows // 2
    assert p.min() in (p[center], p[center + (rows % 2)])


def test_woo_full_table_anchors():
    assert PlinkoEngine(8, "low").payouts.tolist() == pytest.approx(WOO_LOW_8)
    assert PlinkoEngine(16, "medium").payouts.tolist() == pytest.approx(WOO_MEDIUM_16)
    assert PlinkoEngine(16, "high").payouts.tolist() == pytest.approx(
        WOO_BETFURY_RED_16)


def test_stake_blog_facts_16_high():
    p = PlinkoEngine(16, "high").payouts
    assert p[0] == p[16] == 1000       # "max payout of 1000x"
    assert p[1] == p[15] == 130        # "second to last pins ... 130x"
    # global multiplier range across the whole grid: 0.2x to 1000x
    all_vals = np.concatenate([PlinkoEngine(r, k).payouts
                               for k, r in ALL_CONFIGS])
    assert all_vals.min() == 0.2 and all_vals.max() == 1000


# ---------------------------------------------------------------------------
# Probabilities: exact binomial, and equal to Stake's shipped JS helper
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rows", range(MIN_ROWS, MAX_ROWS + 1))
def test_probabilities_binomial_and_match_stake_client_helper(rows):
    eng = PlinkoEngine(rows, "medium")
    exact = np.array([math.comb(rows, k) for k in range(rows + 1)],
                     dtype=np.float64) / 2 ** rows
    assert np.array_equal(eng.probabilities, exact)
    assert eng.probabilities.sum() == pytest.approx(1.0, abs=1e-15)
    # Stake's client-side Pascal helper (ported verbatim) agrees
    assert pascal_probabilities(rows) == pytest.approx(exact, abs=1e-15)


def test_edge_probability_16_rows_blog_fact():
    # Stake blog: "0.0015% chance of landing the biggest win" on 16 rows
    p_edge = PlinkoEngine(16, "high").probabilities[0]
    assert p_edge == 1 / 65536
    assert round(100 * p_edge, 4) == 0.0015


# ---------------------------------------------------------------------------
# Analytic RTP / variance vs WoO
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("risk,rows", ALL_CONFIGS)
def test_rtp_in_published_band(risk, rows):
    # WoO: "Range across all 27 configurations: 98.91%-99.16% RTP"
    rtp = PlinkoEngine(rows, risk).rtp()
    assert 0.9891 - 5e-5 <= rtp <= 0.9916 + 5e-5


@pytest.mark.parametrize("risk,rows", sorted(WOO_RTP))
def test_rtp_matches_woo_grid_exactly(risk, rows):
    rtp_pct = round(100 * PlinkoEngine(rows, risk).rtp(), 2)
    assert rtp_pct == pytest.approx(WOO_RTP[(risk, rows)], abs=1e-9)


@pytest.mark.parametrize("risk,rows", ALL_CONFIGS)
def test_variance_consistency(risk, rows):
    eng = PlinkoEngine(rows, risk)
    p, m = eng.probabilities, eng.payouts
    mean = float(p @ m)
    var = float(p @ (m - mean) ** 2)  # independent formulation
    assert eng.variance() == pytest.approx(var, rel=1e-12)
    assert eng.std_per_unit() == pytest.approx(math.sqrt(var), rel=1e-12)
    assert eng.house_edge() == pytest.approx(1 - mean, abs=1e-15)


# ---------------------------------------------------------------------------
# from_table: the WoO CryptoGames / BetFury published RTP + SD figures
# (the 11 independently checkable numbers on the reference page)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(WOO_CRYPTOGAMES))
def test_cryptogames_published_rtp_and_sd(name):
    table, rtp_pct, sd = WOO_CRYPTOGAMES[name]
    eng = PlinkoEngine.from_table(table, label=f"cryptogames-{name}")
    assert eng.rows == 16 and eng.pockets == 17
    # published RTP, exact at the printed 2 decimals
    assert round(100 * eng.rtp(), 2) == pytest.approx(rtp_pct, abs=1e-9)
    # published per-drop SD, exact at the printed 6 decimals
    assert round(eng.std_per_unit(), 6) == pytest.approx(sd, abs=1e-9)


@pytest.mark.parametrize("name", ["green", "red"])
def test_betfury_published_rtp(name):
    table, rtp_pct = WOO_BETFURY[name]
    eng = PlinkoEngine.from_table(table, label=f"betfury-{name}")
    assert round(100 * eng.rtp(), 2) == pytest.approx(rtp_pct, abs=1e-9)


def test_betfury_blue_reference_self_inconsistency():
    # The WoO page prints 97.88% beside its BetFury Blue table, but the
    # table it prints evaluates to 97.501831...% — a defect in the
    # reference page itself (its Blue row duplicates Green's RTP).  Pin
    # what the printed table actually evaluates to, and that it does NOT
    # reproduce the printed RTP.
    table, printed_rtp = WOO_BETFURY["blue"]
    eng = PlinkoEngine.from_table(table, label="betfury-blue")
    assert round(100 * eng.rtp(), 4) == pytest.approx(97.5018, abs=1e-9)
    assert round(100 * eng.rtp(), 2) != printed_rtp


def test_betfury_red_is_stake_high_16():
    # Same table => identical analytic surface through both constructors.
    grid = PlinkoEngine(16, "high")
    custom = PlinkoEngine.from_table(WOO_BETFURY["red"][0], label="betfury-red")
    assert custom.payouts.tolist() == grid.payouts.tolist()
    assert custom.rtp() == grid.rtp()
    assert custom.variance() == grid.variance()
    assert custom.std_per_unit() == grid.std_per_unit()
    assert round(100 * custom.rtp(), 2) == 98.98  # WoO BetFury Red RTP


def test_from_table_grid_equivalence_all_27():
    for risk, rows in ALL_CONFIGS:
        grid = PlinkoEngine(rows, risk)
        custom = PlinkoEngine.from_table(grid.payouts, label=risk)
        assert custom.rows == rows
        assert np.array_equal(custom.payouts, grid.payouts)
        assert custom.rtp() == grid.rtp()
        assert custom.std_per_unit() == grid.std_per_unit()


def test_from_table_play_and_sims_work():
    table, _, _ = WOO_CRYPTOGAMES["yellow"]
    eng = PlinkoEngine.from_table(table, label="cryptogames-yellow")
    res = eng.play(SERVER, CLIENT, nonce=5)
    assert res["multiplier"] == table[res["pocket"]]
    sim = eng.simulate(200_000, seed=7)
    assert sim["rounds"] == 200_000
    pf = eng.simulate_provably_fair(
        500, server_seed=SERVER, client_seed=CLIENT)
    assert pf["rounds"] == 500


@pytest.mark.parametrize("bad", [
    [],                       # empty
    [1.0],                    # single pocket (rows = 0)
    [[1.0, 2.0]],             # wrong ndim
    [1.0, -0.5, 1.0],         # negative multiplier
    [1.0, float("nan"), 1.0], # non-finite
    [1.0, float("inf"), 1.0],
])
def test_from_table_rejects_bad_tables(bad):
    with pytest.raises(ValueError):
        PlinkoEngine.from_table(bad)


def test_from_table_copies_input():
    src = np.array([2.0, 1.0, 2.0])
    eng = PlinkoEngine.from_table(src)
    src[0] = 99.0
    assert eng.payouts[0] == 2.0
    with pytest.raises(ValueError):
        eng.payouts[0] = 1.0  # read-only


def test_result_dict_contract():
    res = PlinkoEngine(16, "high").result()
    assert set(res) == {"rtp", "house_edge", "std_per_unit", "config"}
    assert res["config"]["game"] == "plinko"
    assert res["config"]["risk"] == "high"
    assert res["config"]["rows"] == 16
    assert res["config"]["pockets"] == 17
    assert res["config"]["payouts"] == PlinkoEngine(16, "high").payouts.tolist()
    assert res["rtp"] + res["house_edge"] == pytest.approx(1.0)


def test_paytable_rows_woo_style():
    eng = PlinkoEngine(8, "low")
    table = eng.paytable()
    assert len(table) == 9
    assert [r["combinations"] for r in table] == [1, 8, 28, 56, 70, 56, 28, 8, 1]
    assert sum(r["return"] for r in table) == pytest.approx(eng.rtp())


# ---------------------------------------------------------------------------
# Provably-fair play (spinquest_sim.rng)
# ---------------------------------------------------------------------------

SERVER = "a" * 64
CLIENT = "test-client-seed"


def test_play_matches_scalar_rng_path():
    eng = PlinkoEngine(16, "medium")
    res = eng.play(SERVER, CLIENT, nonce=7)
    floats = sq_rng.generate_floats(SERVER, CLIENT, 7, 0, 16)
    assert res["floats"] == floats
    assert res["directions"] == [math.floor(f * 2) for f in floats]
    assert res["pocket"] == sum(res["directions"])
    assert res["multiplier"] == eng.payouts[res["pocket"]]
    assert res["payout"] == res["multiplier"]  # bet defaults to 1
    assert res["server_seed_hash"] == sq_rng.hash_server_seed(SERVER)
    assert len(res["path"]) == 16
    assert res["path"].count("R") == res["pocket"]


def test_play_deterministic_and_nonce_sensitive():
    eng = PlinkoEngine(12, "high")
    a = eng.play(SERVER, CLIENT, nonce=1)
    b = eng.play(SERVER, CLIENT, nonce=1)
    assert a == b
    outcomes = {eng.play(SERVER, CLIENT, n)["path"] for n in range(50)}
    assert len(outcomes) > 40  # different nonces give different paths


def test_play_consumes_two_hmac_rounds_for_rows_over_8():
    # rows > 8 spans 2 digests ("Plinko (2 increments per game ...)"):
    # floats 8..15 must come from HMAC round 1, i.e. byte cursor 32.
    floats16 = sq_rng.generate_floats(SERVER, CLIENT, 3, 0, 16)
    round1 = sq_rng.generate_floats(SERVER, CLIENT, 3, 0, 8, round_index=1)
    assert floats16[8:] == round1
    assert sq_rng.digests_for_events(16) == 2
    assert sq_rng.digests_for_events(8) == 1


def test_play_scaled_bet():
    eng = PlinkoEngine(8, "low")
    res = eng.play(SERVER, CLIENT, nonce=0, bet=2.5)
    assert res["payout"] == pytest.approx(2.5 * res["multiplier"])


@pytest.mark.parametrize("bad_bet", [-5, -0.01, float("nan"),
                                     float("inf"), float("-inf")])
def test_play_rejects_bad_bets(bad_bet):
    eng = PlinkoEngine(8, "low")
    with pytest.raises(ValueError):
        eng.play(SERVER, CLIENT, nonce=0, bet=bad_bet)


def test_play_zero_bet_allowed():
    res = PlinkoEngine(8, "low").play(SERVER, CLIENT, nonce=0, bet=0)
    assert res["bet"] == 0.0 and res["payout"] == 0.0


def test_config_payouts_render_like_published_tables():
    # published tables print 110, 41, 10 ... not 110.0, 41.0, 10.0
    cfg = PlinkoEngine(16, "medium").config()
    assert cfg["payouts"] == [110, 41, 10, 5, 3, 1.5, 1, 0.5, 0.3,
                              0.5, 1, 1.5, 3, 5, 10, 41, 110]
    types = [type(x) for x in cfg["payouts"]]
    assert types[:5] == [int, int, int, int, int]
    assert isinstance(cfg["payouts"][5], float)  # 1.5 stays a float


@pytest.mark.parametrize("bad", [dict(rows=7), dict(rows=17), dict(rows=8.0),
                                 dict(rows=True)])
def test_bad_rows_rejected(bad):
    with pytest.raises((ValueError, TypeError)):
        PlinkoEngine(risk="low", **bad)


def test_bad_risk_rejected():
    with pytest.raises(ValueError):
        PlinkoEngine(8, "extreme")


# ---------------------------------------------------------------------------
# Simulators
# ---------------------------------------------------------------------------

def test_provably_fair_sim_rows_match_scalar_play():
    eng = PlinkoEngine(10, "high")
    bulk = sq_rng.BulkRng(server_seed=SERVER, client_seed=CLIENT,
                          nonce_start=100, workers=1)
    sim = eng.simulate_provably_fair(200, bulk=bulk)
    assert sim["rounds"] == 200
    assert sim["verification"]["last_nonce_range"] == (100, 300)
    # replay every round through the scalar provably-fair path
    counts = np.zeros(11, dtype=np.int64)
    for nonce in range(100, 300):
        counts[eng.play(SERVER, CLIENT, nonce)["pocket"]] += 1
    assert counts.tolist() == sim["pocket_counts"]


def test_fast_sim_statistics():
    eng = PlinkoEngine(16, "medium")
    sim = eng.simulate(2_000_000, seed=1234)
    assert sim["rounds"] == 2_000_000
    assert sum(sim["pocket_counts"]) == 2_000_000
    assert set(sim) >= {"rtp", "house_edge", "std_per_unit", "config",
                        "analytic_rtp", "rtp_standard_error", "rtp_z"}
    # within 4 SE of analytic (fixed seed => deterministic, no flake)
    assert abs(sim["rtp_z"]) < 4
    # empirical pocket frequencies close to binomial
    freq = np.asarray(sim["pocket_counts"]) / 2e6
    assert np.abs(freq - eng.probabilities).max() < 5e-4
    assert sim["std_per_unit"] == pytest.approx(eng.std_per_unit(), rel=0.05)


def test_fast_sim_seed_determinism():
    eng = PlinkoEngine(9, "low")
    a = eng.simulate(100_000, seed=42)
    b = eng.simulate(100_000, seed=42)
    assert a["pocket_counts"] == b["pocket_counts"]


def test_sim_rejects_zero_rounds():
    eng = PlinkoEngine(8, "low")
    with pytest.raises(ValueError):
        eng.simulate(0)
    with pytest.raises(ValueError):
        eng.simulate_provably_fair(0)


@pytest.mark.parametrize("bad_chunk", [0, -1, -1_000_000])
def test_sim_rejects_nonpositive_chunk(bad_chunk):
    # regression: chunk<=0 used to make the while-loop spin forever
    eng = PlinkoEngine(8, "low")
    with pytest.raises(ValueError):
        eng.simulate(1000, seed=1, chunk=bad_chunk)


def test_sim_small_chunk_terminates_and_is_exact():
    eng = PlinkoEngine(8, "low")
    sim = eng.simulate(10_001, seed=3, chunk=1000)
    assert sim["rounds"] == 10_001
    assert sum(sim["pocket_counts"]) == 10_001
