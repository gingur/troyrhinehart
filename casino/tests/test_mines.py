"""Tests for spinquest_sim.games.mines against the published references."""

import importlib.util
import math
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from spinquest_sim import rng as sq_rng  # noqa: E402
from spinquest_sim.games import mines as mines_mod  # noqa: E402
from spinquest_sim.games.mines import (  # noqa: E402
    GRID_TILES,
    Mines,
    display_multiplier,
    full_payout_table,
    multiplier,
    multiplier_exact,
    win_probability,
    win_probability_exact,
)
from spinquest_sim.rng import BulkRng  # noqa: E402


def _load_validator():
    spec = importlib.util.spec_from_file_location(
        "validate_mines", _ROOT / "scripts" / "validate_mines.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


VAL = _load_validator()

SERVER = "d8e1c9a55b3f4e2a90c17d6b8f0a3c5e7d9b1f2a4c6e8d0b3f5a7c9e1d2b4f6a"
CLIENT = "test-mines-client"


# ---------------------------------------------------------------------------
# (a) analytics vs Stake's published table
# ---------------------------------------------------------------------------

class TestStakeTable:
    def test_all_300_cells_match_reference(self):
        ref = VAL.parse_stake_table()
        assert len(ref) == 300
        for (m, k), ref_val in ref.items():
            ours = multiplier(m, k)
            assert abs(ours - ref_val) <= VAL.DISPLAY_TOL, (m, k, ours, ref_val)

    def test_published_spot_checks(self):
        # Verbatim spot checks from references/stake/mines.md section 7.
        assert display_multiplier(1, 1) == 1.03
        assert display_multiplier(24, 1) == 24.75
        assert display_multiplier(1, 24) == 24.75
        assert display_multiplier(3, 22) == 2277.00
        # Formula anchors.
        assert multiplier_exact(1, 1) == Fraction(99, 100) * Fraction(25, 24)
        assert multiplier_exact(24, 1) == Fraction(99, 4)

    def test_full_table_shape(self):
        table = full_payout_table()
        assert sum(len(row) for row in table.values()) == 300
        for m, row in table.items():
            assert set(row) == set(range(1, GRID_TILES - m + 1))

    def test_rtp_exactly_099_everywhere(self):
        for m in range(1, 25):
            for k in range(1, 25 - m + 1):
                rtp = multiplier_exact(m, k) * win_probability_exact(m, k)
                assert rtp == Fraction(99, 100)
                game = Mines(m, k)
                assert game.rtp == pytest.approx(0.99, abs=1e-15)
                assert game.house_edge == pytest.approx(0.01, abs=1e-15)

    def test_symmetry_in_mines_and_picks(self):
        # C(25,k)/C(25-m,k) is symmetric in (m, k).
        assert multiplier_exact(9, 15) == multiplier_exact(15, 9)
        assert multiplier_exact(7, 17) == multiplier_exact(17, 7)


class TestWooMethodology:
    def test_probabilities_match_woo_published_column(self):
        rows = VAL.parse_woo_table()
        assert len(rows) == 300
        for r in rows:
            p = win_probability(int(r["mines"]), int(r["picks"]))
            assert abs(p - r["prob"]) <= 5e-7, r

    def test_prob_times_pay_on_stake_table_is_099(self):
        # WoO's enumeration applied to Stake's table.
        for m, k in [(1, 1), (2, 5), (3, 22), (10, 10), (24, 1), (16, 9)]:
            assert multiplier(m, k) * win_probability(m, k) == pytest.approx(
                0.99, abs=1e-12
            )

    def test_woo_table_is_a_different_95_paytable(self):
        rows = VAL.parse_woo_table()
        # WoO: "In cases of 2 to 24 mines, the expected return is always
        # close to 95%" (1-mine rows are his documented exception, and two
        # rows are known typos with return > 1).
        # pays x EXACT P(win): his printed prob column is 6dp-rounded and
        # useless for tiny-probability rows.
        clean = [
            r["pays"] * win_probability(int(r["mines"]), int(r["picks"]))
            for r in rows
            if r["ret"] <= 1.0 and r["mines"] >= 2
        ]
        mean_ret = sum(clean) / len(clean)
        assert 0.93 < mean_ret < 0.96          # WoO/BetFury ~95%
        assert abs(mean_ret - 0.99) > 0.03      # demonstrably NOT Stake's table
        for r in rows:
            if r["mines"] >= 2 and r["ret"] <= 1.0:
                ret = r["pays"] * win_probability(int(r["mines"]), int(r["picks"]))
                assert 0.94 < ret < 0.96, r


# ---------------------------------------------------------------------------
# config validation / variance
# ---------------------------------------------------------------------------

class TestConfig:
    @pytest.mark.parametrize("m,k", [(0, 1), (25, 1), (1, 0), (1, 25), (3, 23), (24, 2)])
    def test_invalid_configs_raise(self, m, k):
        with pytest.raises(ValueError):
            Mines(m, k)

    def test_variance_matches_bernoulli_formula(self):
        game = Mines(5, 5)
        p = game.win_probability
        mult = game.multiplier
        assert game.variance_per_unit == pytest.approx(
            mult * mult * p - (mult * p) ** 2, rel=1e-12
        )
        assert game.std_per_unit == pytest.approx(
            math.sqrt(game.variance_per_unit), rel=1e-12
        )

    def test_result_dict_contract(self):
        game = Mines(3, 3)
        for res in (game.analytic_summary(), game.simulate(500, progress=False)):
            for key in ("rtp", "house_edge", "std_per_unit", "config"):
                assert key in res
            assert res["config"]["game"] == "mines"
            assert res["config"]["mines"] == 3
            assert res["config"]["picks"] == 3


# ---------------------------------------------------------------------------
# (b) provably-fair single round
# ---------------------------------------------------------------------------

class TestPlayRound:
    def test_mine_positions_come_from_verified_scalar_rng(self):
        game = Mines(4, 3)
        res = game.play_round(SERVER, CLIENT, nonce=7)
        assert res["mine_positions"] == sq_rng.mines_positions(SERVER, CLIENT, 7, 4)
        assert res["verification"] == {
            "server_seed": SERVER,
            "client_seed": CLIENT,
            "nonce": 7,
        }

    def test_outcome_consistent_with_mine_set(self):
        game = Mines(6, 4)
        saw_win = saw_loss = False
        for nonce in range(200):
            res = game.play_round(SERVER, CLIENT, nonce)
            mine_set = set(sq_rng.mines_positions(SERVER, CLIENT, nonce, 6))
            expected_win = not (mine_set & set(range(4)))
            assert res["win"] is expected_win
            if res["win"]:
                saw_win = True
                assert res["payout"] == pytest.approx(multiplier(6, 4))
                assert res["revealed"] == [0, 1, 2, 3]
                assert len(res["multiplier_path"]) == 4
                assert res["multiplier_path"][-1] == pytest.approx(multiplier(6, 4))
                assert res["hit_mine"] is None
            else:
                saw_loss = True
                assert res["payout"] == 0.0
                assert res["hit_mine"] in mine_set
                assert res["hit_mine"] not in res["revealed"]
        assert saw_win and saw_loss

    def test_custom_pick_order(self):
        game = Mines(3, 2)
        res = game.play_round(SERVER, CLIENT, 11, picks=[24, 12])
        mine_set = set(sq_rng.mines_positions(SERVER, CLIENT, 11, 3))
        assert res["win"] is not bool(mine_set & {24, 12})

    def test_bad_picks_raise(self):
        game = Mines(3, 3)
        with pytest.raises(ValueError):
            game.play_round(SERVER, CLIENT, 0, picks=[0, 1])       # too few
        with pytest.raises(ValueError):
            game.play_round(SERVER, CLIENT, 0, picks=[0, 0, 1])    # dupes
        with pytest.raises(ValueError):
            game.play_round(SERVER, CLIENT, 0, picks=[0, 1, 25])   # off-board


# ---------------------------------------------------------------------------
# (c) vectorized simulator
# ---------------------------------------------------------------------------

class TestValidatorHardening:
    """The validation script's own gates and failure modes (round-3 gap)."""

    @staticmethod
    def _run_main(capsys, argv):
        rc = VAL.main(argv)
        out = capsys.readouterr().out
        line = next(
            ln for ln in out.splitlines()
            if ln.startswith("MINES_VALIDATION_JSON:")
        )
        import json as _json
        return rc, _json.loads(line.split(":", 1)[1]), out

    def test_all_gates_pass_end_to_end_with_real_sim(self, capsys):
        # Full script including a real (small, deterministic-seed) empirical
        # run — every gate, sim included, is genuinely exercised.
        rc, summary, out = self._run_main(
            capsys, ["--rounds", "40000", "--configs", "3:3,24:1"]
        )
        assert rc == 0
        assert summary["overall_pass"] is True
        assert summary["empirical_skipped"] is False
        assert summary["empirical"]["meets_10m_bar"] is False  # smoke run
        assert len(summary["empirical"]["configs"]) == 2
        for cfg in summary["empirical"]["configs"]:
            assert cfg["n_rounds"] == 40000
            assert cfg["within_3se"] is True
        for gate in (
            "stake_table_300_cells",
            "published_spot_checks",
            "exact_rtp_identity",
            "scalar_bulk_bitmatch",
            "woo_methodology",
            "empirical_within_3se",
        ):
            assert summary["gates"][gate] is True, gate
        assert "below the 10M bar" in out  # smoke run is flagged, not hidden

    def test_skip_sim_is_flagged_not_silent(self, capsys):
        rc, summary, out = self._run_main(capsys, ["--skip-sim"])
        assert rc == 0
        assert summary["overall_pass"] is True
        assert summary["empirical_skipped"] is True
        assert "analytic gates only" in out

    def test_spot_check_gate(self):
        res = VAL.check_spot_checks()
        assert res["pass"] and len(res["checks"]) == 4

    def test_exact_rtp_identity_gate(self):
        res = VAL.check_exact_rtp_identity()
        assert res["pass"] and res["cells_checked"] == 300
        assert res["exact_failures"] == []

    def test_scalar_bulk_bitmatch_gate(self):
        res = VAL.check_scalar_bulk_bitmatch(n_rounds=200)
        assert res["pass"]
        for cfg in res["configs"]:
            assert cfg["position_mismatches"] == 0
            assert cfg["outcome_mismatches"] == 0

    def test_parser_rejects_tampered_table(self, tmp_path):
        # Drop one cell from a copied reference: structural check must fire.
        text = (VAL.STAKE_MD).read_text()
        tampered = text.replace("| 24 | 24.75x |", "| 24 | — |", 1)
        assert tampered != text
        bad = tmp_path / "mines.md"
        bad.write_text(tampered)
        with pytest.raises(VAL.ValidationError):
            VAL.parse_stake_table(bad)

    def test_parser_rejects_missing_file(self, tmp_path):
        with pytest.raises(VAL.ValidationError):
            VAL.parse_stake_table(tmp_path / "nope.md")
        with pytest.raises(VAL.ValidationError):
            VAL.parse_woo_table(tmp_path / "nope.md")

    def test_parser_rejects_garbage_cell(self, tmp_path):
        bad = tmp_path / "mines.md"
        bad.write_text(
            "| Gems picked | 1 mine |\n|---|---|\n| 1 | banana |\n"
        )
        with pytest.raises(VAL.ValidationError):
            VAL.parse_stake_table(bad)

    def test_config_arg_validation(self):
        assert VAL._parse_configs("3:3, 24:1") == [(3, 3), (24, 1)]
        with pytest.raises(SystemExit):
            VAL._parse_configs("3-3")
        with pytest.raises(ValueError):
            VAL._parse_configs("25:1")   # invalid mines count
        with pytest.raises(SystemExit):
            VAL._parse_configs("")


class TestSimulator:
    def test_bulk_simulation_bit_matches_scalar_rounds(self):
        n = 1000
        game = Mines(5, 4)
        bulk = BulkRng(server_seed=SERVER, client_seed=CLIENT, nonce_start=0)
        res = game.simulate(n, bulk=bulk, progress=False)
        assert res["verification"]["nonce_range"] == (0, n)
        scalar_wins = sum(
            game.play_round(SERVER, CLIENT, nonce)["win"] for nonce in range(n)
        )
        assert res["wins"] == scalar_wins
        assert res["rtp"] == pytest.approx(scalar_wins / n * game.multiplier)

    def test_custom_picks_match_scalar(self):
        n = 400
        picks = [24, 0, 12]
        game = Mines(8, 3)
        bulk = BulkRng(server_seed=SERVER, client_seed=CLIENT, nonce_start=0)
        res = game.simulate(n, bulk=bulk, picks=picks, progress=False)
        scalar_wins = sum(
            game.play_round(SERVER, CLIENT, nonce, picks=picks)["win"]
            for nonce in range(n)
        )
        assert res["wins"] == scalar_wins

    def test_empirical_rtp_within_5se_at_200k(self):
        game = Mines(3, 3)
        bulk = BulkRng(server_seed=SERVER, client_seed=CLIENT, nonce_start=0)
        res = game.simulate(200_000, bulk=bulk, progress=False)
        assert abs(res["z_score"]) < 5.0
        assert res["analytic_rtp"] == pytest.approx(0.99)

    def test_chunking_is_seamless(self):
        game = Mines(2, 2)
        one = game.simulate(
            300,
            bulk=BulkRng(server_seed=SERVER, client_seed=CLIENT),
            chunk_rounds=1_000_000,
            progress=False,
        )
        many = game.simulate(
            300,
            bulk=BulkRng(server_seed=SERVER, client_seed=CLIENT),
            chunk_rounds=64,
            progress=False,
        )
        assert one["wins"] == many["wins"]
