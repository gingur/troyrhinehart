"""Tests for spinquest_sim.games.crash against the published references."""

import hashlib
import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from spinquest_sim import rng as sq_rng  # noqa: E402
from spinquest_sim.games import crash as crash_mod  # noqa: E402
from spinquest_sim.games.crash import (  # noqa: E402
    EDGE_MULTIPLIER,
    HOUSE_EDGE,
    MAX_CASHOUT,
    STAKE_CHAIN_LENGTH,
    STAKE_SALT,
    STAKE_TERMINATING_HASH,
    TWO32,
    Crash,
    HashChain,
    analytic_table,
    build_hash_chain,
    crash_int_from_hash,
    crash_point_from_float,
    crash_point_from_hash,
    crash_point_from_int,
    instant_bust_probability,
    next_chain_hash,
    simulate_chain_targets,
    simulate_targets,
    verify_game_hash,
    win_count,
    win_probability,
    win_probability_ideal,
)
from spinquest_sim.rng import BulkRng  # noqa: E402


def _load_validator():
    spec = importlib.util.spec_from_file_location(
        "validate_crash", _ROOT / "scripts" / "validate_crash.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


VAL = _load_validator()

SERVER = "a3f1c8d92b6e4a7f5c0d9b8e1f2a3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b"
CLIENT = "test-crash-client"
TARGETS = [1.01, 1.5, 2.0, 3.0, 5.0, 10.0, 100.0, 1000.0]


# ---------------------------------------------------------------------------
# Published constants and formula (references/stake/crash.md)
# ---------------------------------------------------------------------------

class TestPublishedConstants:
    def test_constants_match_reference_document(self):
        ref = VAL.parse_stake_reference()
        assert ref["terminating_hash"] == STAKE_TERMINATING_HASH
        assert ref["salt"] == STAKE_SALT
        assert ref["chain_length"] == STAKE_CHAIN_LENGTH
        assert ref["house_edge"] == HOUSE_EDGE
        assert ref["max_cashout"] == MAX_CASHOUT
        assert ref["formula_found"]

    def test_edge_multiplier_verbatim(self):
        # verbatim (1 - 0.01); in float64 this equals the literal 0.99 exactly
        assert EDGE_MULTIPLIER == 0.99
        assert EDGE_MULTIPLIER == 1 - 0.01


class TestFormula:
    def test_extreme_ints(self):
        # int = 2^32 - 1: (2^32 / 2^32) * 0.99 = 0.99 -> Math.max -> 1
        assert crash_point_from_int(TWO32 - 1) == 1.0
        # int = 0: raw max multiplier
        assert crash_point_from_int(0) == (2 ** 32 / 1) * (1 - 0.01)
        assert crash_point_from_int(0) > MAX_CASHOUT

    def test_matches_verbatim_js_expression(self):
        for k in [0, 1, 2, 99, 12345, 123456789, 2**31, TWO32 - 2, TWO32 - 1]:
            expected = max(1, (2 ** 32 / (k + 1)) * (1 - 0.01))
            assert crash_point_from_int(k) == expected

    def test_weakly_decreasing(self):
        ks = np.linspace(0, TWO32 - 1, 10001).astype(np.int64)
        vals = [crash_point_from_int(int(k)) for k in ks]
        assert all(a >= b for a, b in zip(vals, vals[1:]))

    def test_rejects_out_of_range_int(self):
        with pytest.raises(ValueError):
            crash_point_from_int(-1)
        with pytest.raises(ValueError):
            crash_point_from_int(TWO32)

    def test_hmac_against_independent_construction(self):
        # Manual HMAC-SHA256 (ipad/opad from first principles) — independent
        # of the hmac module used by the implementation.
        game_hash = hashlib.sha256(b"test vector").hexdigest()
        key = game_hash.encode()  # 64 bytes -> padded to block size 64
        assert len(key) == 64
        ipad = bytes(b ^ 0x36 for b in key)
        opad = bytes(b ^ 0x5C for b in key)
        inner = hashlib.sha256(ipad + STAKE_SALT.encode()).digest()
        digest = hashlib.sha256(opad + inner).digest()
        expected_int = int(digest.hex()[:8], 16)  # parseInt(hex.substr(0,8), 16)
        assert crash_int_from_hash(game_hash) == expected_int
        assert crash_point_from_hash(game_hash) == crash_point_from_int(expected_int)

    def test_parseint_equals_first_four_bytes(self):
        game_hash = "ab" * 32
        digest_hex = __import__("hmac").new(
            game_hash.encode(), STAKE_SALT.encode(), hashlib.sha256
        ).hexdigest()
        assert crash_int_from_hash(game_hash) == int(digest_hex[:8], 16)


# ---------------------------------------------------------------------------
# Hash chain mechanics
# ---------------------------------------------------------------------------

class TestHashChain:
    def test_chain_construction(self):
        chain = build_hash_chain("secret", 50)
        assert len(chain) == 50
        assert chain[0] == hashlib.sha256(b"secret").hexdigest()
        for prev, nxt in zip(chain, chain[1:]):
            assert nxt == hashlib.sha256(prev.encode()).hexdigest()
            assert nxt == next_chain_hash(prev)

    def test_verify_game_hash_steps(self):
        chain = build_hash_chain("secret", 50)
        terminating = chain[-1]
        # game g (1-indexed, newest-first) is chain[-1 - g]; verifies in g steps
        for g in [1, 2, 5, 49]:
            assert verify_game_hash(chain[-1 - g], terminating, 100) == g
        assert verify_game_hash("00" * 32, terminating, 20) is None

    def test_hashchain_play_order_and_exhaustion(self):
        hc = HashChain("secret", length=6)
        chain = build_hash_chain("secret", 6)
        assert hc.terminating_hash == chain[-1]
        assert hc.games_remaining == 5
        popped = [hc.pop_hash() for _ in range(5)]
        assert [g for g, _ in popped] == [1, 2, 3, 4, 5]
        assert [h for _, h in popped] == chain[-2::-1]  # newest first, no term.
        with pytest.raises(RuntimeError):
            hc.pop_hash()

    def test_crash_points_match_scalar(self):
        hc = HashChain("secret", length=20)
        pts = hc.crash_points(10)
        chain = build_hash_chain("secret", 20)
        expected = [crash_point_from_hash(h, STAKE_SALT) for h in chain[-2:-12:-1]]
        assert pts == expected

    def test_stream_matches_hashchain_bitwise(self):
        n = 500
        ints, terminating = crash_mod._stream_chain_ints(
            "stream-secret", n, STAKE_SALT, progress=False
        )
        chain = build_hash_chain("stream-secret", n + 1)
        assert terminating == chain[-1]
        expected = [crash_int_from_hash(h, STAKE_SALT) for h in chain[-2::-1]]
        assert ints.tolist() == expected

    def test_build_chain_guards(self):
        with pytest.raises(ValueError):
            build_hash_chain("s", 1)
        with pytest.raises(ValueError):
            build_hash_chain("s", 5_000_000)


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

class TestAnalytics:
    @pytest.mark.parametrize("w", TARGETS + [1.23, 33.33, 250.0, 1e6])
    def test_win_count_boundary_is_exact(self, w):
        n = win_count(w)
        assert 0 < n < TWO32
        # bisection boundary: crash(n-1) >= w > crash(n)
        assert crash_point_from_int(n - 1) >= w
        assert crash_point_from_int(n) < w

    @pytest.mark.parametrize("w", TARGETS)
    def test_win_probability_close_to_ideal(self, w):
        p, ideal = win_probability(w), win_probability_ideal(w)
        # quantization: |p - 0.99/w| <= ~2/2^32
        assert abs(p - ideal) <= 2.5 / TWO32
        assert ideal == 0.99 / w

    @pytest.mark.parametrize("w", TARGETS + [1e6])
    def test_rtp_within_quantization_bound_of_099(self, w):
        game = Crash(w)
        assert abs(game.rtp - 0.99) <= game.rtp_quantization_bound + 1e-12
        assert game.rtp == w * game.win_probability
        assert game.house_edge == 1.0 - game.rtp

    def test_instant_bust_near_one_percent(self):
        p = instant_bust_probability()
        assert abs(p - 0.01) < 1e-4

    def test_variance_matches_closed_form(self):
        for w in TARGETS:
            game = Crash(w)
            p = game.win_probability
            assert game.variance_per_unit == pytest.approx(
                w * w * p - (w * p) ** 2, rel=1e-12
            )
            # ideal closed form sqrt(0.99 w - 0.9801), quantization-close
            assert game.std_per_unit == pytest.approx(
                game.std_per_unit_ideal, rel=1e-3
            )

    def test_target_validation(self):
        for bad in [1.0, 0.5, 0.0, -2.0, 1_000_000.01, float("inf"), float("nan")]:
            with pytest.raises(ValueError):
                Crash(bad)
        Crash(1.01)
        Crash(MAX_CASHOUT)

    def test_analytic_table_and_summary_shape(self):
        rows = analytic_table([2.0, 10.0])
        assert [r["target"] for r in rows] == [2.0, 10.0]
        summary = Crash(2.0).analytic_summary()
        assert set(summary) == {"rtp", "house_edge", "std_per_unit", "config"}
        assert summary["config"]["game"] == "crash"


# ---------------------------------------------------------------------------
# Provably-fair single rounds
# ---------------------------------------------------------------------------

class TestPlayRounds:
    def test_play_round_chain(self):
        hc = HashChain("secret", length=30)
        game = Crash(2.0)
        for _ in range(10):
            _, game_hash = hc.pop_hash()
            res = game.play_round(game_hash)
            assert res["crash_point"] == crash_point_from_hash(game_hash)
            assert res["win"] == (res["crash_point"] >= 2.0)
            assert res["payout"] == (2.0 if res["win"] else 0.0)
            assert res["verification"]["mechanism"] == "hash_chain"
            assert verify_game_hash(
                res["verification"]["game_hash"], hc.terminating_hash, 30
            ) is not None

    def test_play_round_seedpair_matches_stream_float(self):
        game = Crash(2.0)
        for nonce in range(8):
            res = game.play_round_seedpair(SERVER, CLIENT, nonce)
            f = sq_rng.generate_floats(SERVER, CLIENT, nonce, 0, 1)[0]
            assert res["crash_point"] == crash_point_from_float(f)
            assert res["event_int"] == int(f * 2 ** 32)
            assert res["win"] == (res["crash_point"] >= 2.0)

    def test_float_to_int_recovery_is_exact(self):
        # lattice floats k/2^32 recover k exactly
        for k in [0, 1, 255, 65535, 2**31 - 1, TWO32 - 1]:
            f = k / TWO32
            assert int(f * float(TWO32)) == k
            assert crash_point_from_float(f) == crash_point_from_int(k)
        with pytest.raises(ValueError):
            crash_point_from_float(1.0)


# ---------------------------------------------------------------------------
# Vectorized simulators
# ---------------------------------------------------------------------------

class TestSimulate:
    def test_bulk_rows_match_scalar_seedpair(self):
        n = 64
        bulk = BulkRng(server_seed=SERVER, client_seed=CLIENT, nonce_start=0)
        k = bulk.floats(n) * float(TWO32)
        crash_vec = np.maximum(1.0, (float(TWO32) / (k + 1.0)) * EDGE_MULTIPLIER)
        game = Crash(2.0)
        for i in range(n):
            res = game.play_round_seedpair(SERVER, CLIENT, i)
            assert res["crash_point"] == crash_vec[i]

    def test_simulate_bulk_statistics(self):
        game = Crash(2.0)
        bulk = BulkRng(server_seed=SERVER, client_seed=CLIENT, nonce_start=0)
        res = game.simulate(400_000, bulk=bulk, progress=False)
        for key in ("rtp", "house_edge", "std_per_unit", "config"):
            assert key in res
        assert res["n_rounds"] == 400_000
        assert res["wins"] == round(res["win_rate"] * 400_000)
        assert abs(res["z_score"]) <= 4.0  # deterministic seed; sanity bar
        assert res["rtp"] == res["win_rate"] * 2.0
        assert res["verification"]["mechanism"] == "seed_pair_bulk"
        assert res["verification"]["nonce_range"] == (0, 400_000)

    def test_simulate_targets_shares_stream(self):
        bulk1 = BulkRng(server_seed=SERVER, client_seed=CLIENT, nonce_start=0)
        multi = simulate_targets([1.5, 2.0, 10.0], 200_000, bulk=bulk1,
                                 progress=False)
        assert multi["n_rounds"] == 200_000
        bulk2 = BulkRng(server_seed=SERVER, client_seed=CLIENT, nonce_start=0)
        single = Crash(2.0).simulate(200_000, bulk=bulk2, progress=False)
        row = next(r for r in multi["targets"] if r["config"]["target"] == 2.0)
        assert row["wins"] == single["wins"]

    def test_simulate_chain_bit_matches_hashchain(self):
        n = 2_000
        seed = "chain-sim-secret"
        res = simulate_chain_targets([2.0], n, secret_seed=seed, progress=False)
        hc = HashChain(seed, length=n + 1)
        assert res["verification"]["terminating_hash"] == hc.terminating_hash
        wins_scalar = sum(1 for p in hc.crash_points(n) if p >= 2.0)
        assert res["targets"][0]["wins"] == wins_scalar

    def test_simulate_chain_statistics(self):
        game = Crash(1.5)
        res = game.simulate_chain(150_000, secret_seed="stats-secret",
                                  progress=False)
        assert abs(res["z_score"]) <= 4.0
        assert res["verification"]["mechanism"] == "hash_chain"
        assert res["verification"]["chain_length"] == 150_001

    def test_int_domain_threshold_equals_float_comparison(self):
        # chain sim counts wins as int < win_count; must equal crash >= w
        rng = np.random.default_rng(7)
        ks = rng.integers(0, TWO32, size=50_000)
        crash = np.maximum(1.0, (float(TWO32) / (ks + 1.0)) * EDGE_MULTIPLIER)
        for w in [1.01, 2.0, 10.0, 1000.0]:
            assert int(np.count_nonzero(crash >= w)) == int(
                np.count_nonzero(ks < win_count(w))
            )

    def test_rejects_bad_round_counts(self):
        with pytest.raises(ValueError):
            simulate_targets([2.0], 0)
        with pytest.raises(ValueError):
            simulate_chain_targets([2.0], -5)
