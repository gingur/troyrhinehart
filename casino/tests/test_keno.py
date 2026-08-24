"""Tests for the Keno engine (references/stake/keno.md + references/woo/keno.md)."""

import math
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spinquest_sim import rng as sq_rng  # noqa: E402
from spinquest_sim.games.keno import (  # noqa: E402
    DRAW_COUNT,
    MAX_PICKS,
    MIN_PICKS,
    PAYTABLES,
    POOL_SIZE,
    RISKS,
    Keno,
    full_rtp_table,
    hit_probability,
    hit_probability_exact,
    paytable,
    paytable_exact,
    rtp,
    rtp_exact,
    std_per_unit,
    variance_exact,
)
from spinquest_sim.rng import BulkRng  # noqa: E402

SEED = "d8b8a4b26181b23342f2b40a1ba64c39c0a173d0f9bf798c8bba9c4c3b7a2e01"
CLIENT = "keno-test-client"

# references/stake/keno.md §6 "RTP verification" — the reference table,
# percentages as published (2 decimals).
STAKE_RTP_PCT = {
    "classic": {1: 99.00, 2: 99.04, 3: 99.02, 4: 98.96, 5: 98.99,
                6: 98.97, 7: 98.98, 8: 99.02, 9: 98.98, 10: 99.04},
    "low": {1: 98.75, 2: 98.85, 3: 98.87, 4: 98.92, 5: 98.90,
            6: 99.01, 7: 98.94, 8: 99.00, 9: 99.07, 10: 98.76},
    "medium": {1: 98.75, 2: 98.65, 3: 98.99, 4: 98.78, 5: 98.94,
               6: 98.83, 7: 98.96, 8: 98.92, 9: 98.94, 10: 98.97},
    "high": {1: 99.00, 2: 98.65, 3: 98.99, 4: 98.91, 5: 98.89,
             6: 99.00, 7: 98.96, 8: 98.96, 9: 98.96, 10: 99.01},
}


class TestPaytables:
    def test_shapes(self):
        for risk in RISKS:
            assert set(PAYTABLES[risk]) == set(range(1, 11))
            for picks in range(1, 11):
                assert len(PAYTABLES[risk][picks]) == picks + 1

    def test_published_spot_checks(self):
        # references/stake/keno.md §6, payout-for-payout spot checks.
        assert paytable("classic", 1) == [0.0, 3.96]
        assert paytable("classic", 10)[10] == 100.0
        assert paytable("classic", 7)[2] == 0.47
        assert paytable("low", 1) == [0.7, 1.85]       # pays 0.7x on 0 hits
        assert paytable("medium", 1) == [0.4, 2.75]    # pays 0.4x on 0 hits
        assert paytable("low", 9)[9] == 1000.0
        assert paytable("medium", 5)[5] == 390.0
        assert paytable("high", 2) == [0.0, 0.0, 17.1]
        assert paytable("high", 10) == [0.0, 0.0, 0.0, 0.0, 3.5, 8.0, 13.0,
                                        63.0, 500.0, 800.0, 1000.0]

    def test_published_prose_consistency(self):
        # Stake blog: Classic max 100x; Low/Medium/High 10-of-10 max 1000x;
        # "the lower the risk setting the less tiles you need to hit on to
        # receive a payout" -> the first paying hit count is monotone
        # non-decreasing Low -> Medium -> High for every pick count.
        assert max(paytable("classic", 10)) == 100.0
        for risk in ("low", "medium", "high"):
            assert paytable(risk, 10)[10] == 1000.0
        for picks in range(1, 11):
            thresholds = [
                min(k for k, pay in enumerate(paytable(risk, picks)) if pay > 0)
                for risk in ("low", "medium", "high")
            ]
            assert thresholds == sorted(thresholds), (picks, thresholds)

    def test_exact_fractions(self):
        # String-sourced Fractions are exact (0.47 is not a binary float).
        assert paytable_exact("classic", 7)[2] == Fraction(47, 100)
        assert paytable_exact("low", 1)[0] == Fraction(7, 10)


class TestHypergeometric:
    def test_probabilities_sum_to_one_exactly(self):
        for picks in range(1, 11):
            total = sum(hit_probability_exact(picks, k) for k in range(picks + 1))
            assert total == 1

    def test_matches_scipy(self):
        from scipy.stats import hypergeom
        for picks in range(1, 11):
            for k in range(picks + 1):
                ref = hypergeom.pmf(k, POOL_SIZE, picks, DRAW_COUNT)
                assert hit_probability(picks, k) == pytest.approx(ref, abs=1e-14)

    def test_known_value(self):
        # P(1 hit | 1 pick) = 10/40 = 1/4.
        assert hit_probability_exact(1, 1) == Fraction(1, 4)
        # P(10 hits | 10 picks) = 1 / C(40,10).
        assert hit_probability_exact(10, 10) == Fraction(1, math.comb(40, 10))

    def test_bad_hits_raise(self):
        with pytest.raises(ValueError):
            hit_probability_exact(3, 4)
        with pytest.raises(ValueError):
            hit_probability_exact(3, -1)


class TestRtp:
    def test_all_40_configs_match_stake_reference(self):
        # Analytic hypergeometric RTP reproduces Stake's published table,
        # config-for-config, at its printed 2-decimal precision.
        for risk in RISKS:
            for picks in range(1, 11):
                pct = float(rtp_exact(risk, picks) * 100)
                assert abs(pct - STAKE_RTP_PCT[risk][picks]) <= 0.005 + 1e-9, (
                    risk, picks, pct)

    def test_rtp_close_to_stated_99(self):
        for risk in RISKS:
            for picks in range(1, 11):
                assert 0.986 <= rtp(risk, picks) <= 0.991

    def test_classic_pick1_exact(self):
        # 3.96 * 1/4 = 0.99 exactly.
        assert rtp_exact("classic", 1) == Fraction(99, 100)

    def test_full_rtp_table_shape(self):
        table = full_rtp_table()
        assert set(table) == set(RISKS)
        for risk in RISKS:
            assert set(table[risk]) == set(range(1, 11))

    def test_variance_matches_direct_enumeration(self):
        for risk in ("classic", "high"):
            for picks in (1, 5, 10):
                pays = paytable(risk, picks)
                probs = [hit_probability(picks, k) for k in range(picks + 1)]
                mean = sum(p * w for p, w in zip(probs, pays))
                var = sum(p * w * w for p, w in zip(probs, pays)) - mean**2
                assert float(variance_exact(risk, picks)) == pytest.approx(
                    var, rel=1e-12)
                assert std_per_unit(risk, picks) == pytest.approx(
                    math.sqrt(var), rel=1e-12)


class TestConfig:
    @pytest.mark.parametrize("picks,risk", [
        (0, "classic"), (11, "classic"), (-1, "low"),
    ])
    def test_invalid_picks_raise(self, picks, risk):
        with pytest.raises(ValueError):
            Keno(picks, risk)

    def test_invalid_risk_raises(self):
        with pytest.raises(ValueError):
            Keno(5, "extreme")
        with pytest.raises(TypeError):
            Keno(5, 3)

    def test_non_int_picks_raise(self):
        with pytest.raises(TypeError):
            Keno(2.5, "classic")
        with pytest.raises(TypeError):
            Keno(True, "classic")

    def test_risk_case_insensitive(self):
        assert Keno(5, "Classic").risk == "classic"

    def test_result_dict_contract(self):
        game = Keno(6, "medium")
        res = game.analytic_summary()
        assert set(res) == {"rtp", "house_edge", "std_per_unit", "config"}
        assert res["rtp"] == pytest.approx(rtp("medium", 6))
        assert res["house_edge"] == pytest.approx(1 - rtp("medium", 6))
        cfg = res["config"]
        assert cfg["game"] == "keno"
        assert cfg["pool_size"] == 40
        assert cfg["draw_count"] == 10
        assert cfg["picks"] == 6
        assert cfg["risk"] == "medium"
        assert cfg["paytable"] == paytable("medium", 6)


class TestPlayRound:
    def test_draw_comes_from_verified_scalar_rng(self):
        game = Keno(10, "classic")
        for nonce in range(5):
            res = game.play_round(SEED, CLIENT, nonce)
            assert res["drawn"] == sq_rng.keno_hits(SEED, CLIENT, nonce)
            assert len(res["drawn"]) == 10
            assert len(set(res["drawn"])) == 10
            assert all(1 <= n <= 40 for n in res["drawn"])

    def test_outcome_consistent_with_draw(self):
        game = Keno(7, "high")
        for nonce in range(50):
            res = game.play_round(SEED, CLIENT, nonce)
            expect_hits = sorted(set(res["selection"]) & set(res["drawn"]))
            assert res["hits"] == expect_hits
            assert res["n_hits"] == len(expect_hits)
            assert res["payout"] == paytable("high", 7)[res["n_hits"]]
            assert res["profit"] == pytest.approx(res["payout"] - 1.0)
            assert res["win"] == (res["payout"] > 1.0)

    def test_win_profit_semantics_on_sub_unit_payouts(self):
        # 7 of the 40 configs have paytable cells paying in (0, 1]: those
        # rounds return money but are NOT wins (profit <= 0).  Force each
        # case deterministically by choosing the selection from the actual
        # draw, then assert the bet-record fields.
        cases = [
            # (risk, picks, hits_to_force, expected payout, expected win)
            ("low", 1, 0, 0.7, False),        # 0.7x consolation -> loss
            ("medium", 1, 0, 0.4, False),     # 0.4x consolation -> loss
            ("classic", 4, 1, 0.8, False),    # 0.80x -> net -0.20
            ("classic", 5, 1, 0.25, False),   # 0.25x -> net -0.75
            ("classic", 7, 2, 0.47, False),   # 0.47x -> net -0.53
            ("classic", 6, 2, 1.0, False),    # exactly 1.00x is a push, not a win
            ("classic", 3, 1, 1.0, False),    # 1.00x push
            ("low", 1, 1, 1.85, True),        # actual win
            ("classic", 2, 1, 1.9, True),     # actual win
        ]
        drawn = sq_rng.keno_hits(SEED, CLIENT, 0)
        not_drawn = [n for n in range(1, POOL_SIZE + 1) if n not in drawn]
        for risk, picks, force_hits, exp_pay, exp_win in cases:
            sel = drawn[:force_hits] + not_drawn[: picks - force_hits]
            res = Keno(picks, risk).play_round(SEED, CLIENT, 0, selection=sel)
            assert res["n_hits"] == force_hits, (risk, picks)
            assert res["payout"] == pytest.approx(exp_pay), (risk, picks)
            assert res["profit"] == pytest.approx(exp_pay - 1.0), (risk, picks)
            assert res["win"] is exp_win, (risk, picks)

    def test_zero_payout_round_is_loss_with_full_profit(self):
        drawn = sq_rng.keno_hits(SEED, CLIENT, 0)
        miss = [n for n in range(1, POOL_SIZE + 1) if n not in drawn][:10]
        res = Keno(10, "high").play_round(SEED, CLIENT, 0, selection=miss)
        assert res["n_hits"] == 0
        assert res["payout"] == 0.0
        assert res["profit"] == -1.0
        assert res["win"] is False

    def test_default_selection_is_prefix(self):
        res = Keno(4, "low").play_round(SEED, CLIENT, 0)
        assert res["selection"] == [1, 2, 3, 4]

    def test_custom_selection(self):
        sel = [40, 13, 7, 22, 31]
        res = Keno(5, "medium").play_round(SEED, CLIENT, 3, selection=sel)
        assert res["selection"] == sel
        assert res["hits"] == sorted(set(sel) & set(res["drawn"]))

    def test_bad_selection_raises(self):
        game = Keno(3, "classic")
        with pytest.raises(ValueError):
            game.play_round(SEED, CLIENT, 0, selection=[1, 2])        # too few
        with pytest.raises(ValueError):
            game.play_round(SEED, CLIENT, 0, selection=[1, 1, 2])     # dupes
        with pytest.raises(ValueError):
            game.play_round(SEED, CLIENT, 0, selection=[0, 1, 2])     # out of range
        with pytest.raises(ValueError):
            game.play_round(SEED, CLIENT, 0, selection=[1, 2, 41])    # out of range


class TestSimulator:
    def test_bulk_simulation_bit_matches_scalar_rounds(self):
        n = 2_000
        game = Keno(8, "medium")
        bulk = BulkRng(server_seed=SEED, client_seed=CLIENT, nonce_start=100)
        res = game.simulate(n, bulk=bulk, chunk_rounds=700, progress=False)
        hist = np.zeros(9, dtype=np.int64)
        total = 0.0
        for nonce in range(100, 100 + n):
            r = game.play_round(SEED, CLIENT, nonce)
            hist[r["n_hits"]] += 1
            total += r["payout"]
        assert res["hit_histogram"] == hist.tolist()
        assert res["total_payout"] == pytest.approx(total, rel=1e-12)
        assert res["verification"]["nonce_range"] == (100, 100 + n)

    def test_custom_selection_matches_scalar(self):
        n = 1_000
        sel = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29]
        game = Keno(10, "high")
        bulk = BulkRng(server_seed=SEED, client_seed=CLIENT, nonce_start=0)
        res = game.simulate(n, bulk=bulk, selection=sel, progress=False)
        hist = np.zeros(11, dtype=np.int64)
        for nonce in range(n):
            hist[game.play_round(SEED, CLIENT, nonce, selection=sel)["n_hits"]] += 1
        assert res["hit_histogram"] == hist.tolist()

    def test_chunking_is_seamless(self):
        n = 5_000
        game = Keno(5, "low")
        res_a = game.simulate(
            n, bulk=BulkRng(SEED, CLIENT, nonce_start=0), chunk_rounds=999,
            progress=False)
        res_b = game.simulate(
            n, bulk=BulkRng(SEED, CLIENT, nonce_start=0), chunk_rounds=n,
            progress=False)
        assert res_a["hit_histogram"] == res_b["hit_histogram"]
        assert res_a["rtp"] == res_b["rtp"]

    def test_empirical_rtp_within_5se_at_200k(self):
        # Low-variance config keeps this quick test tight and reliable.
        game = Keno(2, "classic")
        res = game.simulate(
            200_000, bulk=BulkRng(SEED, CLIENT, nonce_start=0), progress=False)
        assert abs(res["z_score"]) < 5.0
        assert res["analytic_rtp"] == pytest.approx(rtp("classic", 2))

    def test_simulate_result_contract(self):
        res = Keno(3, "classic").simulate(
            10_000, bulk=BulkRng(SEED, CLIENT), progress=False)
        for key in ("rtp", "house_edge", "std_per_unit", "config", "n_rounds",
                    "hit_histogram", "z_score", "within_3se", "se_rtp",
                    "rounds_per_sec", "verification"):
            assert key in res
        assert sum(res["hit_histogram"]) == 10_000
        assert res["config"]["risk"] == "classic"

    def test_bad_rounds_raise(self):
        with pytest.raises(ValueError):
            Keno(3, "classic").simulate(0)

    def test_bad_chunk_rounds_raise(self):
        # chunk_rounds=0 used to loop forever silently; both 0 and negative
        # values must raise immediately.
        game = Keno(3, "classic")
        with pytest.raises(ValueError):
            game.simulate(100, bulk=BulkRng(SEED, CLIENT), chunk_rounds=0)
        with pytest.raises(ValueError):
            game.simulate(100, bulk=BulkRng(SEED, CLIENT), chunk_rounds=-5)


# ---------------------------------------------------------------------------
# Hardened validation script (scripts/validate_keno.py): the script must
# ALWAYS return a machine-readable verdict — including when a gate crashes —
# and its reference parsers must recover the full published tables (no
# vacuous passes on format drift).
# ---------------------------------------------------------------------------

def _load_validate_keno():
    import importlib.util
    path = Path(__file__).resolve().parent.parent / "scripts" / "validate_keno.py"
    spec = importlib.util.spec_from_file_location("validate_keno_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestValidationScript:
    def test_reference_parsers_recover_full_tables(self):
        vk = _load_validate_keno()
        tables = vk.parse_stake_paytables()
        assert set(tables) == set(RISKS)
        for risk in RISKS:
            assert set(tables[risk]) == set(range(1, 11))
            for picks in range(1, 11):
                assert len(tables[risk][picks]) == picks + 1
        rtp_ref = vk.parse_stake_rtp_table()
        assert all(len(rtp_ref[r]) == 10 for r in RISKS)
        pays, rets = vk.parse_woo_40ball()
        assert set(rets) == set(range(3, 11))
        assert set(pays) >= set(range(3, 11))
        # WoO spot values from references/woo/keno.md.
        assert pays[10][10] == 20000.0
        assert rets[10] == 97.90

    def test_analytic_gates_pass(self):
        vk = _load_validate_keno()
        assert vk.check_stake_paytables()["pass"] is True
        assert vk.check_stake_rtp()["pass"] is True
        assert vk.check_woo_methodology()["pass"] is True

    def test_provably_fair_gate_bit_matches_scalar(self):
        vk = _load_validate_keno()
        res = vk.check_provably_fair(n_rounds=64)
        assert res["pass"] is True
        assert res["draw_mismatches"] == 0
        assert res["payout_mismatches"] == 0
        assert res["shape_and_uniqueness_ok"] is True

    def test_guarded_gate_converts_crash_to_failing_verdict(self):
        vk = _load_validate_keno()
        def boom():
            raise RuntimeError("injected failure")
        res = vk._guarded("test", boom)
        assert res["pass"] is False
        assert res["crashed"] is True
        assert "injected failure" in res["error"]

    def test_configs_arg_validation(self):
        vk = _load_validate_keno()
        assert vk.parse_configs_arg("classic:1,high:10") == [
            ("classic", 1), ("high", 10)]
        assert vk.parse_configs_arg("Classic:5") == [("classic", 5)]
        for bad in ("turbo:5", "classic:0", "classic:11", "classic", "", "high:x"):
            with pytest.raises(SystemExit):
                vk.parse_configs_arg(bad)

    def test_crashed_gate_still_emits_json_verdict(self, capsys):
        import json
        vk = _load_validate_keno()
        vk.check_stake_paytables = lambda: (_ for _ in ()).throw(
            RuntimeError("injected"))
        rc = vk.main(["--skip-sim"])
        out = capsys.readouterr().out
        line = [l for l in out.splitlines()
                if l.startswith("KENO_VALIDATION_JSON:")]
        assert len(line) == 1
        summary = json.loads(line[0].split(": ", 1)[1])
        assert rc == 1
        assert summary["overall_pass"] is False
        assert summary["stake_paytables"]["crashed"] is True

    def test_end_to_end_skip_sim(self, capsys):
        import json
        vk = _load_validate_keno()
        rc = vk.main(["--skip-sim"])
        out = capsys.readouterr().out
        line = [l for l in out.splitlines()
                if l.startswith("KENO_VALIDATION_JSON:")][0]
        summary = json.loads(line.split(": ", 1)[1])
        assert rc == 0
        assert summary["overall_pass"] is True
        assert summary["stake_paytables"]["n_mismatches"] == 0
        assert summary["stake_rtp"]["pass"] is True
        assert summary["woo_40ball"]["pass"] is True
        assert summary["provably_fair"]["pass"] is True
        assert summary["meets_10m_bar"] is False  # sim skipped
