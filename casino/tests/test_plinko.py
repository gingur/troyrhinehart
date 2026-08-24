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
    Plinko,
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
    return [Plinko(rows=rows, risk=risk) for risk, rows in ALL_CONFIGS]


# ---------------------------------------------------------------------------
# Paytable grid vs the Stake reference (all 27 configs)
# ---------------------------------------------------------------------------

def test_grid_has_all_27_configs():
    assert set(PAYTABLES) == set(STAKE_PLAYING_SIZES)
    assert len(PAYTABLES) == 27


@pytest.mark.parametrize("risk,rows", ALL_CONFIGS)
def test_destinations_min_max_match_stake_tables(risk, rows):
    eng = Plinko(rows=rows, risk=risk)
    destinations, min_win, max_win = STAKE_PLAYING_SIZES[(risk, rows)]
    assert eng.pockets == destinations == rows + 1
    assert len(eng.payouts) == destinations
    assert float(eng.payouts.min()) == pytest.approx(min_win, abs=0)
    assert float(eng.payouts.max()) == pytest.approx(max_win, abs=0)
    assert eng.max_multiplier == max_win


@pytest.mark.parametrize("risk,rows", ALL_CONFIGS)
def test_tables_symmetric_edge_max_center_min_region(risk, rows):
    eng = Plinko(rows=rows, risk=risk)
    p = eng.payouts
    assert np.array_equal(p, p[::-1]), "pay table must be symmetric"
    # max at the edges, min at/near the center
    assert p[0] == p.max()
    center = rows // 2
    assert p.min() in (p[center], p[center + (rows % 2)])


def test_woo_full_table_anchors():
    assert Plinko(8, "low").payouts.tolist() == pytest.approx(WOO_LOW_8)
    assert Plinko(16, "medium").payouts.tolist() == pytest.approx(WOO_MEDIUM_16)
    assert Plinko(16, "high").payouts.tolist() == pytest.approx(
        WOO_BETFURY_RED_16)


def test_stake_blog_facts_16_high():
    p = Plinko(16, "high").payouts
    assert p[0] == p[16] == 1000       # "max payout of 1000x"
    assert p[1] == p[15] == 130        # "second to last pins ... 130x"
    # global multiplier range across the whole grid: 0.2x to 1000x
    all_vals = np.concatenate([Plinko(r, k).payouts
                               for k, r in ALL_CONFIGS])
    assert all_vals.min() == 0.2 and all_vals.max() == 1000


# ---------------------------------------------------------------------------
# Probabilities: exact binomial, and equal to Stake's shipped JS helper
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rows", range(MIN_ROWS, MAX_ROWS + 1))
def test_probabilities_binomial_and_match_stake_client_helper(rows):
    eng = Plinko(rows, "medium")
    exact = np.array([math.comb(rows, k) for k in range(rows + 1)],
                     dtype=np.float64) / 2 ** rows
    assert np.array_equal(eng.probabilities, exact)
    assert eng.probabilities.sum() == pytest.approx(1.0, abs=1e-15)
    # Stake's client-side Pascal helper (ported verbatim) agrees
    assert pascal_probabilities(rows) == pytest.approx(exact, abs=1e-15)


def test_edge_probability_16_rows_blog_fact():
    # Stake blog: "0.0015% chance of landing the biggest win" on 16 rows
    p_edge = Plinko(16, "high").probabilities[0]
    assert p_edge == 1 / 65536
    assert round(100 * p_edge, 4) == 0.0015


# ---------------------------------------------------------------------------
# Analytic RTP / variance vs WoO
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("risk,rows", ALL_CONFIGS)
def test_rtp_in_published_band(risk, rows):
    # WoO: "Range across all 27 configurations: 98.91%-99.16% RTP"
    rtp = Plinko(rows, risk).rtp
    assert 0.9891 - 5e-5 <= rtp <= 0.9916 + 5e-5


@pytest.mark.parametrize("risk,rows", sorted(WOO_RTP))
def test_rtp_matches_woo_grid_exactly(risk, rows):
    rtp_pct = round(100 * Plinko(rows, risk).rtp, 2)
    assert rtp_pct == pytest.approx(WOO_RTP[(risk, rows)], abs=1e-9)


@pytest.mark.parametrize("risk,rows", ALL_CONFIGS)
def test_variance_consistency(risk, rows):
    eng = Plinko(rows, risk)
    p, m = eng.probabilities, eng.payouts
    mean = float(p @ m)
    var = float(p @ (m - mean) ** 2)  # independent float64 formulation
    assert eng.rtp == pytest.approx(mean, rel=1e-12)
    assert eng.variance_per_unit == pytest.approx(var, rel=1e-12)
    assert eng.variance_per_unit == pytest.approx(float(eng.variance_exact),
                                                 rel=0)
    assert eng.std_per_unit == pytest.approx(math.sqrt(var), rel=1e-12)
    assert eng.house_edge == pytest.approx(1 - mean, abs=1e-12)
    assert float(eng.rtp_exact) == eng.rtp


# ---------------------------------------------------------------------------
# from_table: the WoO CryptoGames / BetFury published RTP + SD figures
# (the 11 independently checkable numbers on the reference page)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(WOO_CRYPTOGAMES))
def test_cryptogames_published_rtp_and_sd(name):
    table, rtp_pct, sd = WOO_CRYPTOGAMES[name]
    eng = Plinko.from_table(table, label=f"cryptogames-{name}")
    assert eng.rows == 16 and eng.pockets == 17
    # published RTP, exact at the printed 2 decimals
    assert round(100 * eng.rtp, 2) == pytest.approx(rtp_pct, abs=1e-9)
    # published per-drop SD, exact at the printed 6 decimals
    assert round(eng.std_per_unit, 6) == pytest.approx(sd, abs=1e-9)


@pytest.mark.parametrize("name", ["green", "red"])
def test_betfury_published_rtp(name):
    table, rtp_pct = WOO_BETFURY[name]
    eng = Plinko.from_table(table, label=f"betfury-{name}")
    assert round(100 * eng.rtp, 2) == pytest.approx(rtp_pct, abs=1e-9)


def test_betfury_blue_reference_self_inconsistency():
    # The WoO page prints 97.88% beside its BetFury Blue table, but the
    # table it prints evaluates to 97.501831...% — a defect in the
    # reference page itself (its Blue row duplicates Green's RTP).  Pin
    # what the printed table actually evaluates to, and that it does NOT
    # reproduce the printed RTP.
    table, printed_rtp = WOO_BETFURY["blue"]
    eng = Plinko.from_table(table, label="betfury-blue")
    assert round(100 * eng.rtp, 4) == pytest.approx(97.5018, abs=1e-9)
    assert round(100 * eng.rtp, 2) != printed_rtp


def test_betfury_red_is_stake_high_16():
    # Same table => identical analytic surface through both constructors.
    grid = Plinko(16, "high")
    custom = Plinko.from_table(WOO_BETFURY["red"][0], label="betfury-red")
    assert custom.payouts.tolist() == grid.payouts.tolist()
    assert custom.rtp == grid.rtp
    assert custom.rtp_exact == grid.rtp_exact
    assert custom.variance_exact == grid.variance_exact
    assert custom.std_per_unit == grid.std_per_unit
    assert round(100 * custom.rtp, 2) == 98.98  # WoO BetFury Red RTP


def test_from_table_grid_equivalence_all_27():
    for risk, rows in ALL_CONFIGS:
        grid = Plinko(rows, risk)
        custom = Plinko.from_table(grid.payouts, label=risk)
        assert custom.rows == rows
        assert np.array_equal(custom.payouts, grid.payouts)
        assert custom.rtp == grid.rtp
        assert custom.std_per_unit == grid.std_per_unit


def test_from_table_play_and_sim_work():
    table, _, _ = WOO_CRYPTOGAMES["yellow"]
    eng = Plinko.from_table(table, label="cryptogames-yellow")
    res = eng.play_round(SERVER, CLIENT, nonce=5)
    assert res["multiplier"] == table[res["pocket"]]
    sim = eng.simulate(
        500, bulk=sq_rng.BulkRng(server_seed=SERVER, client_seed=CLIENT),
        progress=False)
    assert sim["n_rounds"] == 500


def test_from_table_outside_8_16_rows_analytic_only():
    eng = Plinko.from_table([2.0, 1.0, 2.0], label="tiny")  # 2 rows
    assert eng.rtp == pytest.approx(1.5)
    with pytest.raises(ValueError):
        eng.simulate(100)  # the provably-fair stream covers 8..16 rows


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
        Plinko.from_table(bad)


def test_from_table_copies_input():
    src = np.array([2.0, 1.0, 2.0])
    eng = Plinko.from_table(src)
    src[0] = 99.0
    assert eng.payouts[0] == 2.0
    with pytest.raises(ValueError):
        eng.payouts[0] = 1.0  # read-only


def test_analytic_summary_contract():
    res = Plinko(16, "high").analytic_summary()
    assert set(res) == {"rtp", "house_edge", "std_per_unit", "config"}
    assert res["config"]["game"] == "plinko"
    assert res["config"]["risk"] == "high"
    assert res["config"]["rows"] == 16
    assert res["config"]["pockets"] == 17
    assert res["config"]["payouts"] == Plinko(16, "high").payouts.tolist()
    assert res["rtp"] + res["house_edge"] == pytest.approx(1.0)


def test_paytable_rows_woo_style():
    eng = Plinko(8, "low")
    table = eng.paytable()
    assert len(table) == 9
    assert [r["combinations"] for r in table] == [1, 8, 28, 56, 70, 56, 28, 8, 1]
    assert sum(r["return"] for r in table) == pytest.approx(eng.rtp)


# ---------------------------------------------------------------------------
# Provably-fair play (spinquest_sim.rng)
# ---------------------------------------------------------------------------

SERVER = "a" * 64
CLIENT = "test-client-seed"


def test_play_round_matches_scalar_rng_path():
    eng = Plinko(16, "medium")
    res = eng.play_round(SERVER, CLIENT, nonce=7)
    floats = sq_rng.generate_floats(SERVER, CLIENT, 7, 0, 16)
    assert res["floats"] == floats
    assert res["directions"] == [math.floor(f * 2) for f in floats]
    assert res["pocket"] == sum(res["directions"])
    assert res["multiplier"] == eng.payouts[res["pocket"]]
    assert res["payout"] == res["multiplier"]  # bet defaults to 1
    assert res["server_seed_hash"] == sq_rng.hash_server_seed(SERVER)
    assert len(res["path"]) == 16
    assert res["path"].count("R") == res["pocket"]


def test_play_round_deterministic_and_nonce_sensitive():
    eng = Plinko(12, "high")
    a = eng.play_round(SERVER, CLIENT, nonce=1)
    b = eng.play_round(SERVER, CLIENT, nonce=1)
    assert a == b
    outcomes = {eng.play_round(SERVER, CLIENT, n)["path"] for n in range(50)}
    assert len(outcomes) > 40  # different nonces give different paths


def test_play_round_consumes_two_hmac_rounds_for_rows_over_8():
    # rows > 8 spans 2 digests ("Plinko (2 increments per game ...)"):
    # floats 8..15 must come from HMAC round 1, i.e. byte cursor 32.
    floats16 = sq_rng.generate_floats(SERVER, CLIENT, 3, 0, 16)
    round1 = sq_rng.generate_floats(SERVER, CLIENT, 3, 0, 8, round_index=1)
    assert floats16[8:] == round1
    assert sq_rng.digests_for_events(16) == 2
    assert sq_rng.digests_for_events(8) == 1


def test_play_round_scaled_bet():
    eng = Plinko(8, "low")
    res = eng.play_round(SERVER, CLIENT, nonce=0, bet=2.5)
    assert res["payout"] == pytest.approx(2.5 * res["multiplier"])


@pytest.mark.parametrize("bad_bet", [-5, -0.01, float("nan"),
                                     float("inf"), float("-inf")])
def test_play_round_rejects_bad_bets(bad_bet):
    eng = Plinko(8, "low")
    with pytest.raises(ValueError):
        eng.play_round(SERVER, CLIENT, nonce=0, bet=bad_bet)


def test_play_round_zero_bet_allowed():
    res = Plinko(8, "low").play_round(SERVER, CLIENT, nonce=0, bet=0)
    assert res["bet"] == 0.0 and res["payout"] == 0.0


@pytest.mark.parametrize("bad_seed", ["", None, 123])
def test_play_round_rejects_empty_or_nonstring_server_seed(bad_seed):
    # Stake's spec is a 64-char hex server seed; "" is not a reachable state.
    with pytest.raises(ValueError):
        Plinko(8, "low").play_round(bad_seed, CLIENT, nonce=0)


@pytest.mark.parametrize("bad_nonce", [-1, -100])
def test_play_round_rejects_negative_nonce(bad_nonce):
    # the nonce counts bets made, so it starts at a bet and is never negative
    with pytest.raises(ValueError):
        Plinko(8, "low").play_round(SERVER, CLIENT, nonce=bad_nonce)


@pytest.mark.parametrize("bad_nonce", [1.5, True, "7"])
def test_play_round_rejects_nonint_nonce(bad_nonce):
    with pytest.raises(TypeError):
        Plinko(8, "low").play_round(SERVER, CLIENT, nonce=bad_nonce)


def test_config_payouts_render_like_published_tables():
    # published tables print 110, 41, 10 ... not 110.0, 41.0, 10.0
    cfg = Plinko(16, "medium").config()
    assert cfg["payouts"] == [110, 41, 10, 5, 3, 1.5, 1, 0.5, 0.3,
                              0.5, 1, 1.5, 3, 5, 10, 41, 110]
    types = [type(x) for x in cfg["payouts"]]
    assert types[:5] == [int, int, int, int, int]
    assert isinstance(cfg["payouts"][5], float)  # 1.5 stays a float


@pytest.mark.parametrize("bad", [dict(rows=7), dict(rows=17), dict(rows=8.0),
                                 dict(rows=True)])
def test_bad_rows_rejected(bad):
    with pytest.raises((ValueError, TypeError)):
        Plinko(risk="low", **bad)


def test_bad_risk_rejected():
    with pytest.raises(ValueError):
        Plinko(8, "extreme")


# ---------------------------------------------------------------------------
# Vectorized simulator (provably-fair BulkRng campaign)
# ---------------------------------------------------------------------------

def _bulk(nonce_start=0, workers=1):
    return sq_rng.BulkRng(server_seed=SERVER, client_seed=CLIENT,
                          nonce_start=nonce_start, workers=workers)


def test_simulate_rows_match_scalar_play_round():
    eng = Plinko(10, "high")
    sim = eng.simulate(200, bulk=_bulk(nonce_start=100), progress=False)
    assert sim["n_rounds"] == 200
    assert sim["verification"]["nonce_range"] == (100, 300)
    assert sim["verification"]["server_seed_hash"] == \
        sq_rng.hash_server_seed(SERVER)
    # replay every round through the scalar provably-fair path
    counts = np.zeros(11, dtype=np.int64)
    for nonce in range(100, 300):
        counts[eng.play_round(SERVER, CLIENT, nonce)["pocket"]] += 1
    assert counts.tolist() == sim["pocket_counts"]


def test_simulate_result_contract():
    sim = Plinko(9, "low").simulate(1000, bulk=_bulk(), progress=False)
    assert set(sim) >= {"rtp", "house_edge", "std_per_unit", "config",
                        "n_rounds", "pocket_counts", "analytic_rtp",
                        "analytic_std_per_unit", "se_rtp", "z_score",
                        "within_3se", "elapsed_s", "rounds_per_sec",
                        "verification"}
    assert sim["n_rounds"] == 1000 == sum(sim["pocket_counts"])
    assert sim["config"]["game"] == "plinko"
    assert sim["rtp"] + sim["house_edge"] == pytest.approx(1.0)
    assert sim["se_rtp"] == pytest.approx(
        sim["analytic_std_per_unit"] / math.sqrt(1000))
    assert sim["within_3se"] == (abs(sim["z_score"]) <= 3.0)


def test_simulate_statistics():
    eng = Plinko(16, "medium")
    sim = eng.simulate(300_000, bulk=_bulk(workers=None), progress=False)
    assert sim["n_rounds"] == 300_000
    # fixed seeds => deterministic, no flake; hold to 4 SE
    assert abs(sim["z_score"]) < 4
    # empirical pocket frequencies close to binomial
    freq = np.asarray(sim["pocket_counts"]) / 300_000
    assert np.abs(freq - eng.probabilities).max() < 4e-3
    assert sim["std_per_unit"] == pytest.approx(eng.std_per_unit, rel=0.05)


def test_simulate_seed_deterministic_and_chunk_invariant():
    eng = Plinko(9, "low")
    a = eng.simulate(10_001, bulk=_bulk(), progress=False)
    b = eng.simulate(10_001, bulk=_bulk(), progress=False)
    # same seeds/nonces -> identical campaign
    assert a["pocket_counts"] == b["pocket_counts"]
    # chunk size never changes results, only peak memory
    c = eng.simulate(10_001, bulk=_bulk(), chunk_rounds=997, progress=False)
    assert c["pocket_counts"] == a["pocket_counts"]
    assert c["n_rounds"] == 10_001


def test_simulate_shares_one_stream_across_risks():
    # pockets depend only on rows, so risks settle the same direction stream
    counts = np.asarray(
        Plinko(12, "low").simulate(2000, bulk=_bulk(), progress=False)
        ["pocket_counts"])
    for risk in ("medium", "high"):
        eng = Plinko(12, risk)
        out = eng.summarize_counts(counts)
        assert out["n_rounds"] == 2000
        assert out["rtp"] == pytest.approx(
            float(counts @ eng.payouts) / 2000, rel=1e-12)
        assert out["analytic_rtp"] == eng.rtp


def test_summarize_counts_rejects_bad_counts():
    eng = Plinko(8, "low")
    with pytest.raises(ValueError):
        eng.summarize_counts(np.zeros(8, dtype=np.int64))   # wrong shape
    with pytest.raises(ValueError):
        eng.summarize_counts(np.zeros(9, dtype=np.int64))   # zero rounds


def test_simulate_rejects_zero_rounds():
    with pytest.raises(ValueError):
        Plinko(8, "low").simulate(0)


@pytest.mark.parametrize("bad_chunk", [0, -1, -1_000_000])
def test_simulate_rejects_nonpositive_chunk_rounds(bad_chunk):
    # regression: chunk<=0 must not make the while-loop spin forever
    with pytest.raises(ValueError):
        Plinko(8, "low").simulate(1000, bulk=_bulk(), chunk_rounds=bad_chunk)
