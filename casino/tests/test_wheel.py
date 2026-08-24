"""Tests for the Stake Originals Wheel engine.

Ground truth: references/stake/wheel.md (verbatim PAYOUTS arrays, the
floor(float * segments) mapping, published max-win table, 99% RTP / 1% edge at
every setting).  references/woo/wheel.md documents that WoO has no page for
this game, so the analytic target is Stake's published table evaluated with
the WoO prob-x-pay methodology (SD computed from the pay tables directly).
"""

from __future__ import annotations

import math
from fractions import Fraction

import numpy as np
import pytest

from spinquest_sim import rng as sq_rng
from spinquest_sim.games import wheel as wh
from spinquest_sim.games.wheel import Wheel
from spinquest_sim.rng import BulkRng

SEED = "8a1f4e7d0c3b6a9582e1f4c7d0a3b695f70b1435a4b8e2f6d3c0a9184e7d2c5b"
CLIENT = "spinquest-wheel-tests"


# ---------------------------------------------------------------------------
# Payout arrays vs the published reference
# ---------------------------------------------------------------------------

def test_config_enumeration():
    assert wh.SEGMENT_COUNTS == (10, 20, 30, 40, 50)
    assert wh.RISKS == ("low", "medium", "high")
    assert len(wh.all_configs()) == 15


@pytest.mark.parametrize("segments", wh.SEGMENT_COUNTS)
@pytest.mark.parametrize("risk", wh.RISKS)
def test_array_lengths(segments, risk):
    assert len(wh.PAYOUTS[segments][risk]) == segments


def test_payouts_10_verbatim():
    """The full 10-segment arrays, verbatim from the reference (section 3)."""
    assert wh.PAYOUTS[10]["low"] == (1.5, 1.2, 1.2, 1.2, 0, 1.2, 1.2, 1.2, 1.2, 0)
    assert wh.PAYOUTS[10]["medium"] == (0, 1.9, 0, 1.5, 0, 2, 0, 1.5, 0, 3)
    assert wh.PAYOUTS[10]["high"] == (0, 0, 0, 0, 0, 0, 0, 0, 0, 9.9)


@pytest.mark.parametrize("segments", wh.SEGMENT_COUNTS)
def test_low_is_repeating_block(segments):
    """Low risk is the same 10-segment block at every size (reference
    structural note): 1x1.50, 7x1.20, 2x0.00 per 10 segments."""
    block = (1.5, 1.2, 1.2, 1.2, 0, 1.2, 1.2, 1.2, 1.2, 0)
    assert wh.PAYOUTS[segments]["low"] == block * (segments // 10)
    pt = Wheel(segments, "low").paytable_exact()
    assert pt[Fraction("1.5")] == Fraction(1, 10)
    assert pt[Fraction("1.2")] == Fraction(7, 10)
    assert pt[Fraction(0)] == Fraction(2, 10)


@pytest.mark.parametrize("segments", wh.SEGMENT_COUNTS)
def test_high_single_paying_segment(segments):
    """High risk pays only the LAST index, worth segments * 0.99 exactly."""
    arr = wh.PAYOUTS[segments]["high"]
    assert all(m == 0 for m in arr[:-1])
    assert Fraction(str(arr[-1])) == Fraction(99, 100) * segments
    eng = Wheel(segments, "high")
    assert eng.win_probability_exact == Fraction(1, segments)


@pytest.mark.parametrize("segments", (20, 30, 40, 50))
def test_medium_alternates(segments):
    """At 20/30/40/50 segments every odd medium index pays 0 (reference
    structural note); at 10 segments every even index is 0."""
    arr = wh.PAYOUTS[segments]["medium"]
    assert all(arr[i] == 0 for i in range(1, segments, 2))
    assert all(arr[i] > 0 for i in range(0, segments, 2))


def test_medium_10_alternates_even_zero():
    arr = wh.PAYOUTS[10]["medium"]
    assert all(arr[i] == 0 for i in range(0, 10, 2))
    assert all(arr[i] > 0 for i in range(1, 10, 2))


def test_published_max_win_table():
    """Stake's published Symbols & Information max-win table (section 5)."""
    expected = {
        (10, "low"): 1.5, (20, "low"): 1.5, (30, "low"): 1.5,
        (40, "low"): 1.5, (50, "low"): 1.5,
        (10, "medium"): 3.0, (20, "medium"): 3.0, (30, "medium"): 4.0,
        (40, "medium"): 3.0, (50, "medium"): 5.0,
        (10, "high"): 9.9, (20, "high"): 19.8, (30, "high"): 29.7,
        (40, "high"): 39.6, (50, "high"): 49.5,
    }
    for (n, r), mx in expected.items():
        assert Wheel(n, r).max_multiplier == mx, (n, r)


def test_medium_spot_values():
    """Distinctive single-segment values from the section-4 tables."""
    assert wh.PAYOUTS[10]["medium"][1] == 1.9
    assert wh.PAYOUTS[20]["medium"][12] == 1.8
    assert wh.PAYOUTS[30]["medium"][22] == 1.7
    assert wh.PAYOUTS[30]["medium"][24] == 4
    assert wh.PAYOUTS[40]["medium"][26] == 1.6
    assert wh.PAYOUTS[50]["medium"][42] == 5


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("segments,risk", wh.all_configs())
def test_exact_rtp_099(segments, risk):
    eng = Wheel(segments, risk)
    assert eng.rtp_exact == Fraction(99, 100)
    assert eng.rtp == 0.99
    assert abs(eng.house_edge - 0.01) < 1e-15


@pytest.mark.parametrize("segments,risk", wh.all_configs())
def test_paytable_probabilities_sum_to_one(segments, risk):
    eng = Wheel(segments, risk)
    pt = eng.paytable_exact()
    assert sum(pt.values()) == 1
    assert sum(m * p for m, p in pt.items()) == Fraction(99, 100)
    # float paytable mirrors the exact one
    assert abs(sum(eng.paytable().values()) - 1.0) < 1e-12


@pytest.mark.parametrize("segments", wh.SEGMENT_COUNTS)
def test_high_risk_sd_closed_form(segments):
    """High risk: X = 0.99*n w.p. 1/n else 0 ->
    Var = 0.99^2 * (n - 1)  ->  SD = 0.99 * sqrt(n - 1)."""
    eng = Wheel(segments, "high")
    assert eng.variance_exact == Fraction(99, 100) ** 2 * (segments - 1)
    assert abs(eng.std_per_unit - 0.99 * math.sqrt(segments - 1)) < 1e-12


def test_low_risk_sd_closed_form():
    """Low risk (any size, same 10-block): E[X^2] = (1.5^2 + 7*1.2^2)/10."""
    ex2 = Fraction(1, 10) * Fraction(3, 2) ** 2 + Fraction(7, 10) * Fraction(6, 5) ** 2
    var = ex2 - Fraction(99, 100) ** 2
    for n in wh.SEGMENT_COUNTS:
        eng = Wheel(n, "low")
        assert eng.variance_exact == var
        assert abs(eng.std_per_unit - math.sqrt(float(var))) < 1e-12


def test_variance_ordering():
    """Risk name orders volatility at every segments setting."""
    for n in wh.SEGMENT_COUNTS:
        lo, me, hi = (Wheel(n, r).std_per_unit for r in wh.RISKS)
        assert lo < me < hi


def test_analytic_summary_contract():
    s = Wheel(30, "medium").analytic_summary()
    assert set(s) == {"rtp", "house_edge", "std_per_unit", "config"}
    assert s["rtp"] == 0.99
    assert s["config"]["game"] == "wheel"
    assert s["config"]["segments"] == 30
    assert s["config"]["risk"] == "medium"
    table = wh.full_analytic_table()
    assert len(table) == 15 and all(v["rtp"] == 0.99 for v in table.values())


def test_invalid_config_rejected():
    with pytest.raises(ValueError):
        Wheel(15, "low")
    with pytest.raises(ValueError):
        Wheel(10, "extreme")


# ---------------------------------------------------------------------------
# Provably-fair single round (scalar path)
# ---------------------------------------------------------------------------

def test_play_round_matches_scalar_rng():
    eng = Wheel(50, "medium")
    for nonce in range(20):
        r = eng.play_round(SEED, CLIENT, nonce)
        f = sq_rng.generate_floats(SEED, CLIENT, nonce, 0, 1)[0]
        assert r["float"] == f
        assert r["segment"] == math.floor(f * 50)
        assert r["multiplier"] == wh.PAYOUTS[50]["medium"][r["segment"]]
        assert r["payout"] == r["multiplier"]
        assert r["win"] == (r["multiplier"] > 0)
        assert r["verification"] == {
            "server_seed": SEED, "client_seed": CLIENT, "nonce": nonce,
        }


def test_index_mapping_edges():
    assert sq_rng.wheel_index(0.0, 50) == 0
    assert sq_rng.wheel_index(1 - 2**-32, 50) == 49
    assert sq_rng.wheel_index(0.5, 10) == 5
    # boundary: float exactly at a segment edge belongs to the upper segment
    assert sq_rng.wheel_index(0.1, 10) == 1


# ---------------------------------------------------------------------------
# Vectorized path vs scalar path
# ---------------------------------------------------------------------------

def test_bulk_matches_scalar():
    n = 200
    bulk = BulkRng(SEED, CLIENT, nonce_start=0, workers=1)
    idx = bulk.wheel_indices(30, n)
    eng = Wheel(30, "high")
    pay = eng.payouts_for_segments(idx)
    for i in range(n):
        r = eng.play_round(SEED, CLIENT, i)
        assert idx[i] == r["segment"]
        assert pay[i] == r["multiplier"]


def test_payouts_for_floats_matches_indices():
    bulk = BulkRng(SEED, CLIENT, nonce_start=0, workers=1)
    floats = bulk.floats(500)
    for n, r in wh.all_configs():
        eng = Wheel(n, r)
        idx = np.floor(floats * n).astype(np.int64)
        assert np.array_equal(
            eng.payouts_for_floats(floats), eng.payouts_for_segments(idx)
        )


# ---------------------------------------------------------------------------
# Simulation (small deterministic campaigns; the 10M gate lives in
# scripts/validate_wheel.py)
# ---------------------------------------------------------------------------

def test_simulate_contract_and_3se():
    n = 200_000
    eng = Wheel(20, "medium")
    bulk = BulkRng(SEED, CLIENT, nonce_start=0, workers=1)
    res = eng.simulate(n, bulk=bulk, progress=False)
    for key in ("rtp", "house_edge", "std_per_unit", "config"):
        assert key in res
    assert res["n_rounds"] == n
    assert int(res["segment_counts"].sum()) == n
    assert res["analytic_rtp"] == 0.99
    assert abs(res["z_score"]) <= 3.0 and res["within_3se"]
    assert abs(res["rtp"] + res["house_edge"] - 1.0) < 1e-12
    assert res["verification"]["nonce_range"] == (0, n)
    assert res["verification"]["server_seed_hash"] == sq_rng.hash_server_seed(SEED)
    # empirical SD near analytic
    assert abs(res["std_per_unit"] - eng.std_per_unit) < 0.05


def test_simulate_nonce_accounting_and_chunking():
    eng = Wheel(10, "low")
    bulk = BulkRng(SEED, CLIENT, nonce_start=100, workers=1)
    res = eng.simulate(5_000, bulk=bulk, chunk_rounds=1_024, progress=False)
    assert res["verification"]["nonce_range"] == (100, 5_100)
    assert bulk.nonce_next == 5_100
    # chunked result identical to unchunked (same seed/nonces)
    bulk2 = BulkRng(SEED, CLIENT, nonce_start=100, workers=1)
    res2 = eng.simulate(5_000, bulk=bulk2, chunk_rounds=5_000, progress=False)
    assert np.array_equal(res["segment_counts"], res2["segment_counts"])
    assert res["rtp"] == res2["rtp"]


def test_summarize_counts_exact_when_counts_uniform():
    """Feeding perfectly uniform counts must reproduce the analytics exactly."""
    for n, r in wh.all_configs():
        eng = Wheel(n, r)
        res = eng.summarize_counts(np.full(n, 1000, dtype=np.int64))
        assert abs(res["rtp"] - 0.99) < 1e-12
        assert abs(res["std_per_unit"] - eng.std_per_unit) < 1e-9
        assert abs(res["z_score"]) < 1e-6


def test_summarize_counts_validates_shape():
    eng = Wheel(10, "low")
    with pytest.raises(ValueError):
        eng.summarize_counts(np.zeros(20, dtype=np.int64))
    with pytest.raises(ValueError):
        eng.summarize_counts(np.zeros(10, dtype=np.int64))
    with pytest.raises(ValueError):
        eng.simulate(0)
