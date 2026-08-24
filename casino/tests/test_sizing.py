"""Tests for spinquest_sim.sizing — survival-optimal sizing for subfair games.

Layers:

(a) closed-form gambler's ruin vs exact Fraction arithmetic AND an
    independent numpy linear-system solution of the absorption equations;
(b) the BankrollChain convolution solver vs the closed form (even-money)
    and vs an independent pure-python Fraction-state DP (mines payouts);
(c) the goal-directed recommendations (bold/timid regimes, stop rules)
    including the honesty accounting;
(d) 1M+-session Monte Carlo through the REAL engines:
    - roulette even-money vs the closed form (must match within 3 SE),
    - mines vs the Markov/convolution solver (within 3 SE per checkpoint).

The Monte Carlo layers use fixed provably-fair seeds, so they are
deterministic: the 3-SE assertions are statistical statements about the
engine stream, checked once and then locked in by the fixed seed.
"""

import math
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from spinquest_sim import sizing as sz  # noqa: E402
from spinquest_sim.games.mines import Mines  # noqa: E402
from spinquest_sim.games.roulette import Roulette  # noqa: E402
from spinquest_sim.rng import BulkRng  # noqa: E402

SERVER = "3f9c2b7a1d5e8c4f6a0b9d2e7c1f5a8b3d6e0c9f2a5b8d1e4c7f0a3b6d9e2c5f"
CLIENT = "test-sizing-client"

P_RED = 18 / 37                      # roulette even-money win probability
P_RED_EXACT = Fraction(18, 37)


# ---------------------------------------------------------------------------
# independent re-derivations (deliberately NOT using the module's formulas)
# ---------------------------------------------------------------------------

def _solve_absorption(p: float, n: int) -> np.ndarray:
    """Reach probabilities h_1..h_{N-1} from the linear system
    h_i = p*h_{i+1} + q*h_{i-1}, h_0 = 0, h_N = 1 (numpy solve)."""
    q = 1.0 - p
    a = np.zeros((n - 1, n - 1))
    b = np.zeros(n - 1)
    for i in range(1, n):
        r = i - 1
        a[r, r] = 1.0
        if i + 1 < n:
            a[r, r + 1] = -p
        else:
            b[r] += p
        if i - 1 > 0:
            a[r, r - 1] = -q
    return np.linalg.solve(a, b)


def _solve_duration(p: float, n: int) -> np.ndarray:
    """Expected absorption times T_1..T_{N-1} from
    T_i = 1 + p*T_{i+1} + q*T_{i-1}, T_0 = T_N = 0 (numpy solve)."""
    q = 1.0 - p
    a = np.zeros((n - 1, n - 1))
    b = np.ones(n - 1)
    for i in range(1, n):
        r = i - 1
        a[r, r] = 1.0
        if i + 1 < n:
            a[r, r + 1] = -p
        if i - 1 > 0:
            a[r, r - 1] = -q
    return np.linalg.solve(a, b)


def _dp_survival(p_win: float, win_step: Fraction, start: Fraction,
                 bet: Fraction, n_rounds: int) -> list:
    """Pure-python DP over exact-Fraction bankroll states: flat bet while
    bankroll >= bet; win moves +win_step*bet? no — win_step is the NET move
    in money; lose moves -bet.  Returns P(alive after t), t = 1..N."""
    state = {start: 1.0}
    dead = 0.0
    out = []
    for _ in range(n_rounds):
        new: dict = {}
        for b, pr in state.items():
            up = b + win_step
            new[up] = new.get(up, 0.0) + pr * p_win
            dn = b - bet
            new[dn] = new.get(dn, 0.0) + pr * (1.0 - p_win)
        state = {}
        for b, pr in new.items():
            if b < bet:
                dead += pr
            else:
                state[b] = pr
        out.append(1.0 - dead)
    return out


# ---------------------------------------------------------------------------
# (a) closed form
# ---------------------------------------------------------------------------

class TestClosedForm:
    def test_fair_game_is_linear(self):
        for i, n in ((1, 2), (3, 6), (7, 10), (250, 1000)):
            assert sz.reach_probability_even_money(0.5, i, n) == pytest.approx(
                i / n, abs=1e-15
            )
            assert sz.expected_rounds_even_money(0.5, i, n) == i * (n - i)

    def test_boundaries(self):
        assert sz.reach_probability_even_money(P_RED, 0, 8) == 0.0
        assert sz.reach_probability_even_money(P_RED, 8, 8) == 1.0
        assert sz.ruin_probability_even_money(P_RED, 0, 8) == 1.0

    def test_reach_plus_ruin_is_one(self):
        for p in (0.3, P_RED, 0.5, 0.55):
            for i, n in ((1, 5), (4, 8), (10, 30)):
                r = sz.reach_probability_even_money(p, i, n)
                assert 0.0 <= r <= 1.0
                assert r + sz.ruin_probability_even_money(p, i, n) == \
                    pytest.approx(1.0, abs=1e-15)

    def test_matches_exact_fraction_arithmetic(self):
        for p_ex in (Fraction(2, 5), P_RED_EXACT, Fraction(49, 100),
                     Fraction(3, 5)):
            for i, n in ((1, 4), (3, 6), (10, 25), (40, 120)):
                exact = sz.reach_probability_even_money_exact(p_ex, i, n)
                got = sz.reach_probability_even_money(float(p_ex), i, n)
                assert got == pytest.approx(float(exact), rel=1e-9)

    def test_matches_independent_linear_solve(self):
        for p in (0.42, P_RED, 0.5, 0.58):
            n = 9
            h = _solve_absorption(p, n)
            t = _solve_duration(p, n)
            for i in range(1, n):
                assert sz.reach_probability_even_money(p, i, n) == \
                    pytest.approx(h[i - 1], abs=1e-10)
                assert sz.expected_rounds_even_money(p, i, n) == \
                    pytest.approx(t[i - 1], rel=1e-10)

    def test_log_space_branch_matches_exact(self):
        # N*ln(q/p) > 700 forces the overflow-safe branch; the exact
        # Fraction twin is still computable and must agree.
        p_ex = Fraction(49, 100)
        i, n = 100, 17600
        exact = float(sz.reach_probability_even_money_exact(p_ex, i, n))
        got = sz.reach_probability_even_money(float(p_ex), i, n)
        assert exact > 0.0            # ~1e-304: representable, not underflowed
        assert got == pytest.approx(exact, rel=1e-6)

    def test_huge_horizon_no_overflow(self):
        p = 0.49
        got = sz.reach_probability_even_money(p, 1000, 1_000_000)
        assert 0.0 <= got <= 1.0      # underflows to 0.0 rather than NaN/inf
        assert got == 0.0

    def test_monotone_in_start(self):
        vals = [sz.reach_probability_even_money(P_RED, i, 20)
                for i in range(21)]
        assert all(b > a for a, b in zip(vals, vals[1:]))

    def test_validation_errors(self):
        with pytest.raises(ValueError):
            sz.reach_probability_even_money(0.0, 1, 2)
        with pytest.raises(ValueError):
            sz.reach_probability_even_money(1.0, 1, 2)
        with pytest.raises(ValueError):
            sz.reach_probability_even_money(0.4, 5, 4)
        with pytest.raises(ValueError):
            sz.reach_probability_even_money(0.4, -1, 4)
        with pytest.raises(TypeError):
            sz.reach_probability_even_money(0.4, 1.5, 4)
        with pytest.raises(TypeError):
            sz.reach_probability_even_money(0.4, True, 4)

    def test_shorter_sessions_lose_less_in_expectation(self):
        # Honesty check baked into the math: expected loss is
        # edge * bet * E[T], and E[T] shrinks as the barriers close in.
        p = P_RED
        edge = 1 - 2 * p              # per-unit EV loss of an even-money bet
        loss_close = edge * sz.expected_rounds_even_money(p, 2, 4)
        loss_far = edge * sz.expected_rounds_even_money(p, 20, 40)
        assert 0 < loss_close < loss_far


class TestKelly:
    def test_zero_for_all_project_engines(self):
        assert sz.kelly_fraction(Roulette("red")) == 0.0
        assert sz.kelly_fraction(Roulette("straight", 17)) == 0.0
        assert sz.kelly_fraction(Mines(3, 3)) == 0.0
        assert sz.kelly_fraction(Mines(24, 1)) == 0.0

    def test_positive_ev_two_outcome(self):
        # p=0.6, even money: f* = p - q/(m-1) = 0.2
        assert sz.kelly_fraction(
            {"win_probability": 0.6, "multiplier": 2}
        ) == pytest.approx(0.2)

    def test_positive_ev_multi_outcome_not_implemented(self):
        cfg = {"distribution": [(3, 0.3), (1.5, 0.3), (0, 0.4)]}
        with pytest.raises(NotImplementedError):
            sz.kelly_fraction(cfg)


# ---------------------------------------------------------------------------
# input normalization
# ---------------------------------------------------------------------------

class TestNormalizeGameConfig:
    def test_engine_exact_fractions(self):
        out = sz.normalize_game_config(Mines(3, 3))
        assert out == [
            (Fraction(0), 1 - Fraction(77, 115)),
            (Fraction(207, 140), Fraction(77, 115)),
        ]

    def test_dict_two_point(self):
        out = sz.normalize_game_config(
            {"win_probability": "18/37", "multiplier": 2}
        )
        assert out == [(Fraction(0), Fraction(19, 37)),
                       (Fraction(2), Fraction(18, 37))]

    def test_distribution_merges_and_rescales(self):
        out = sz.normalize_game_config(
            {"distribution": [(2, 0.25), (2, 0.25), (0, 0.5)]}
        )
        assert out == [(Fraction(0), Fraction(1, 2)),
                       (Fraction(2), Fraction(1, 2))]
        total = sum(p for _, p in out)
        assert total == 1

    def test_rejects_bad_inputs(self):
        with pytest.raises(ValueError):
            sz.normalize_game_config({"distribution": [(2, 0.6), (0, 0.6)]})
        with pytest.raises(ValueError):
            sz.normalize_game_config({"distribution": [(-1, 0.5), (0, 0.5)]})
        with pytest.raises(TypeError):
            sz.normalize_game_config(42)


# ---------------------------------------------------------------------------
# (b) BankrollChain
# ---------------------------------------------------------------------------

class TestBankrollChain:
    def test_even_money_absorption_matches_closed_form(self):
        eng = Roulette("red")
        for i, n in ((3, 6), (5, 10), (4, 12)):
            chain = sz.BankrollChain(i, 1, eng, target=n)
            assert chain.exact_lattice and chain.lattice_denominator == 1
            res = chain.absorption()
            assert res["p_target"] == pytest.approx(
                sz.reach_probability_even_money(P_RED, i, n), abs=1e-10
            )
            assert res["p_ruin"] == pytest.approx(
                sz.ruin_probability_even_money(P_RED, i, n), abs=1e-10
            )
            assert res["expected_rounds"] == pytest.approx(
                sz.expected_rounds_even_money(P_RED, i, n), rel=1e-9
            )
            assert res["p_target"] + res["p_ruin"] + res["residual"] == \
                pytest.approx(1.0, abs=1e-12)

    def test_bet_size_scales_out_of_the_lattice(self):
        # Same problem stated in dollars: bankroll 50, bet 10, target 100
        # is the units problem (5 -> 10).
        chain = sz.BankrollChain(50, 10, Roulette("red"), target=100)
        assert chain.absorption()["p_target"] == pytest.approx(
            sz.reach_probability_even_money(P_RED, 5, 10), abs=1e-10
        )

    def test_mines_exact_lattice_detected(self):
        chain = sz.BankrollChain(3, 1, Mines(3, 3))
        # net win step 67/140 -> exact common denominator 140
        assert chain.exact_lattice
        assert chain.lattice_denominator == 140
        assert chain.max_step_rounding_error == 0.0

    def test_mines_survival_matches_independent_dp(self):
        eng = Mines(3, 3)
        chain = sz.BankrollChain(3, 1, eng)
        got = chain.survival_curve(6)
        want = _dp_survival(
            float(Fraction(77, 115)), Fraction(67, 140),
            Fraction(3), Fraction(1), 6,
        )
        np.testing.assert_allclose(got, want, atol=1e-12)

    def test_run_conserves_probability_each_round(self):
        chain = sz.BankrollChain(4, 1, Mines(3, 3), target=7)
        res = chain.run(12)
        total = res["alive"] + res["ruined"] + res["reached"]
        np.testing.assert_allclose(total, 1.0, atol=1e-12)
        assert res["p_alive"] + res["p_ruined"] + res["p_reached"] == \
            pytest.approx(1.0, abs=1e-12)
        # terminal alive distribution foots with p_alive
        assert res["probs"].sum() == pytest.approx(res["p_alive"], abs=1e-12)
        assert np.all(res["grid"] >= 1.0)          # alive means >= bet
        assert np.all(res["grid"] < 7.0)           # below target

    def test_survival_curve_monotone_nonincreasing(self):
        curve = sz.survival_curve(5, 1, Roulette("red"), 40)
        assert np.all(np.diff(curve) <= 1e-15)
        assert 0.0 < curve[-1] < 1.0

    def test_survival_ordered_by_bet_size(self):
        curves = sz.survival_curves(12, [1, 2, 3, 4], Roulette("red"), 30)
        b1, b2, b3, b4 = (curves[float(b)] for b in (1, 2, 3, 4))
        assert np.all(b1 >= b2 - 1e-15)
        assert np.all(b2 >= b3 - 1e-15)
        assert np.all(b3 >= b4 - 1e-15)
        # strictly better somewhere, not vacuously equal
        assert b1[-1] > b4[-1]

    def test_rounding_fallback_close_to_exact(self):
        # Float inputs with 1e16 denominators force the rounding grid; the
        # result must stay close to the exact-lattice chain.
        eng = Mines(3, 3)
        approx_cfg = {
            "win_probability": float(eng.win_probability_exact),
            "multiplier": float(eng.multiplier_exact),
        }
        chain = sz.BankrollChain(3, 1, approx_cfg)
        assert not chain.exact_lattice
        assert chain.max_step_rounding_error > 0.0
        exact = sz.BankrollChain(3, 1, eng).survival_curve(6)
        got = chain.survival_curve(6)
        np.testing.assert_allclose(got, exact, atol=0.01)

    def test_validation(self):
        eng = Roulette("red")
        with pytest.raises(ValueError):
            sz.BankrollChain(0.5, 1, eng)          # cannot place one bet
        with pytest.raises(ValueError):
            sz.BankrollChain(5, 0, eng)
        with pytest.raises(ValueError):
            sz.BankrollChain(5, 1, eng, target=5)  # target must exceed bank
        with pytest.raises(ValueError):
            sz.BankrollChain(5, 1, eng).absorption()   # needs target
        with pytest.raises(ValueError):
            sz.BankrollChain(5, 1, eng, target=10).survival_curve(5)
        with pytest.raises(ValueError):
            sz.BankrollChain(5, 1, eng).run(0)
        with pytest.raises(TypeError):
            sz.BankrollChain(5, 1, eng).run(2.5)


# ---------------------------------------------------------------------------
# (c) survival_optimal_bet — bold vs timid regimes
# ---------------------------------------------------------------------------

class TestSurvivalOptimalBet:
    def test_reach_target_prefers_bold_even_money(self):
        res = sz.survival_optimal_bet(
            10, Roulette("red"), "reach_target", target=20,
            bet_grid=[1, 2, 5, 10],
        )
        assert res["regime"] == "bold"
        table = res["flat_bet_table"]
        probs = [row["p_reach_target"] for row in table]
        # P(reach) strictly increases with flat bet size (subfair even money)
        assert all(b > a for a, b in zip(probs, probs[1:]))
        assert res["best_flat_bet"] == 10.0
        # bold play: min(bankroll, target - bankroll) = 10
        assert res["recommended_bet"] == 10.0
        # one bold even-money bet is a single spin: P = 18/37 exactly
        assert table[-1]["p_reach_target"] == pytest.approx(P_RED, abs=1e-10)
        # bigger bets pay the edge over fewer expected rounds
        rounds = [row["expected_rounds"] for row in table]
        assert all(a > b for a, b in zip(rounds, rounds[1:]))
        losses = [row["expected_loss"] for row in table]
        assert all(a > b for a, b in zip(losses, losses[1:]))
        assert all(loss > 0 for loss in losses)    # negative EV, always

    def test_reach_target_bold_stake_general_multiplier(self):
        # Mines(3,3) wins pay 207/140: reach +2 profit in one win with a
        # stake of 2/(67/140) = 280/67.
        res = sz.survival_optimal_bet(
            10, Mines(3, 3), "reach_target", target=12, bet_grid=[1, 2, 5],
        )
        assert res["recommended_bet"] == pytest.approx(float(Fraction(280, 67)))

    def test_reach_target_respects_max_bet(self):
        res = sz.survival_optimal_bet(
            10, Roulette("red"), "reach_target", target=20,
            bet_grid=[1, 2], max_bet=2,
        )
        assert res["recommended_bet"] == 2.0

    def test_survive_rounds_prefers_timid(self):
        res = sz.survival_optimal_bet(
            10, Roulette("red"), "survive_rounds", n_rounds=50,
            bet_grid=[1, 2, 5], min_bet=1,
        )
        assert res["regime"] == "timid"
        assert res["recommended_bet"] == 1.0
        probs = [row["p_survive"] for row in res["flat_bet_table"]]
        assert all(a > b for a, b in zip(probs, probs[1:]))
        assert res["p_survive_at_recommended"] == max(probs)

    def test_honesty_accounting(self):
        res = sz.survival_optimal_bet(
            10, Roulette("red"), "survive_rounds", n_rounds=20, bet_grid=[1],
        )
        assert res["house_edge"] == pytest.approx(1 / 37)
        assert res["ev_per_unit_staked"] < 0
        assert res["kelly_fraction"] == 0.0
        assert "cannot change the sign" in res["note"]
        for row in res["flat_bet_table"]:
            assert row["expected_loss"] > 0

    def test_errors(self):
        eng = Roulette("red")
        with pytest.raises(ValueError):
            sz.survival_optimal_bet(10, eng, "reach_target")     # no target
        with pytest.raises(ValueError):
            sz.survival_optimal_bet(10, eng, "survive_rounds")   # no n_rounds
        with pytest.raises(ValueError):
            sz.survival_optimal_bet(10, eng, "get_rich_quick", target=20)
        with pytest.raises(ValueError):
            sz.survival_optimal_bet(10, eng, "reach_target", target=5)
        with pytest.raises(ValueError):
            sz.survival_optimal_bet(
                10, eng, "reach_target", target=20, bet_grid=[100]
            )


# ---------------------------------------------------------------------------
# (c') stop recommendations
# ---------------------------------------------------------------------------

class TestRecommendStops:
    def test_reach_target_stops(self):
        res = sz.recommend_stops(
            10, 1, Roulette("red"), "reach_target", target=15,
        )
        assert res["stop_win"] == 5.0              # the target itself
        assert res["stop_loss"] == 10.0            # commit the whole bankroll
        tradeoff = res["stop_loss_tradeoff"]
        probs = [row["p_reach_target"] for row in tradeoff]
        # a tighter stop-loss strictly costs reach probability
        assert all(b > a for a, b in zip(probs, probs[1:]))
        # full-commitment row equals the closed form for units (10 -> 15)
        assert tradeoff[-1]["stop_loss"] == 10.0
        assert tradeoff[-1]["p_reach_target"] == pytest.approx(
            sz.reach_probability_even_money(P_RED, 10, 15), abs=1e-10
        )

    def test_survive_rounds_stop_loss_is_alpha_quantile(self):
        alpha = 0.10
        res = sz.recommend_stops(
            20, 1, Roulette("red"), "survive_rounds", n_rounds=50,
            stop_loss_alpha=alpha,
        )
        assert res["p_stop_loss_hit"] <= alpha
        # every smaller candidate loss cap busts too often
        for row in res["stop_loss_table"]:
            if row["stop_loss"] < res["stop_loss"]:
                assert row["p_hit_within_n"] > alpha
        # first-passage identity: hitting a loss cap of L is ruin of the
        # chain started at L
        chain = sz.BankrollChain(res["stop_loss"], 1, Roulette("red"))
        assert 1.0 - chain.run(50)["p_alive"] == pytest.approx(
            res["p_stop_loss_hit"], abs=1e-12
        )

    def test_survive_rounds_stop_win_is_attainable(self):
        floor = 0.25
        res = sz.recommend_stops(
            20, 1, Roulette("red"), "survive_rounds", n_rounds=50,
            stop_win_prob_floor=floor,
        )
        assert res["p_stop_win_hit"] >= floor
        # the win stop is a real first-passage probability of the chain
        chain = sz.BankrollChain(
            20, 1, Roulette("red"), target=20 + res["stop_win"]
        )
        assert chain.run(50)["p_reached"] == pytest.approx(
            res["p_stop_win_hit"], abs=1e-12
        )

    def test_honest_note_present(self):
        res = sz.recommend_stops(
            10, 1, Roulette("red"), "reach_target", target=15,
        )
        assert "cannot create positive EV" in res["note"]

    def test_errors(self):
        with pytest.raises(ValueError):
            sz.recommend_stops(10, 1, Roulette("red"), "reach_target")
        with pytest.raises(ValueError):
            sz.recommend_stops(10, 1, Roulette("red"), "survive_rounds")
        with pytest.raises(ValueError):
            sz.recommend_stops(10, 20, Roulette("red"), "survive_rounds",
                               n_rounds=5)


# ---------------------------------------------------------------------------
# (d) 1M+-session Monte Carlo through the REAL engines
# ---------------------------------------------------------------------------

N_SESSIONS = 1_000_000


class TestValidationRouletteClosedForm:
    """1M sessions of flat even-money roulette through the real engine
    (BulkRng pockets settled by Roulette.payouts_for_pockets) vs the exact
    gambler's-ruin closed form: |p_hat - p| must be within 3 SE."""

    START_UNITS = 3
    TARGET_UNITS = 6

    def test_engine_sessions_match_closed_form_within_3_se(self):
        eng = Roulette("red")
        # the closed form's p is the engine's own exact win probability
        assert eng.win_probability_exact == P_RED_EXACT
        p_reach = sz.reach_probability_even_money(
            float(eng.win_probability_exact), self.START_UNITS,
            self.TARGET_UNITS,
        )
        e_rounds = sz.expected_rounds_even_money(
            float(eng.win_probability_exact), self.START_UNITS,
            self.TARGET_UNITS,
        )

        # scalar cross-check: the vectorized settle path used below
        # (payouts_for_pockets) agrees with the engine's play_round
        spot_bulk = BulkRng(SERVER, CLIENT, nonce_start=1)
        spot_pockets = spot_bulk.roulette_pockets(20)
        spot_mults = eng.payouts_for_pockets(spot_pockets)
        for i in range(20):
            scalar = eng.play_round(SERVER, CLIENT, 1 + i)
            assert scalar["pocket"] == int(spot_pockets[i])
            assert scalar["payout"] == float(spot_mults[i])

        rng = BulkRng(SERVER, CLIENT, nonce_start=1)
        reached = 0
        total_rounds = 0
        # sequential first-passage: draw pockets only for still-active
        # sessions, settle through the engine, absorb at 0 and target
        active = np.full(N_SESSIONS, self.START_UNITS, dtype=np.int64)
        while active.size:
            pk = rng.roulette_pockets(active.size)
            mult = eng.payouts_for_pockets(pk)     # 2.0 win / 0.0 lose
            active = active + np.where(mult == 2.0, 1, -1)
            total_rounds += active.size
            reached += int(np.count_nonzero(active >= self.TARGET_UNITS))
            active = active[(active > 0) & (active < self.TARGET_UNITS)]

        p_hat = reached / N_SESSIONS
        se = math.sqrt(p_reach * (1.0 - p_reach) / N_SESSIONS)
        assert abs(p_hat - p_reach) <= 3.0 * se, (
            f"p_hat={p_hat} vs closed form {p_reach} "
            f"(z={(p_hat - p_reach) / se:.2f})"
        )
        # mean session length vs the closed-form expected duration (loose
        # 2% band — dozens of SEs wide, but a real cross-check of E[T])
        mean_rounds = total_rounds / N_SESSIONS
        assert mean_rounds == pytest.approx(e_rounds, rel=0.02)
        # and the Markov solver agrees with the same closed form exactly
        chain = sz.BankrollChain(
            self.START_UNITS, 1, eng, target=self.TARGET_UNITS
        )
        assert chain.absorption()["p_target"] == pytest.approx(
            p_reach, abs=1e-10
        )


class TestValidationMinesMarkovSolver:
    """1M mines sessions through the real engine stream (BulkRng mine
    positions settled with the engine's own prefix-picks rule and exact
    multiplier) vs the BankrollChain convolution solver on the exact
    67/140 lattice: survival at every checkpoint within 3 SE."""

    MINES = 3
    PICKS = 3
    START = 3            # bankroll, in bets
    N_ROUNDS = 6

    def test_engine_sessions_match_markov_solver_within_3_se(self):
        eng = Mines(self.MINES, self.PICKS)
        # exact lattice: win step (m-1) = 67/140 of the bet
        win_step = (eng.multiplier_exact - 1) * 140
        assert win_step == 67

        # scalar cross-check: the vectorized settle rule used below is the
        # engine's own (prefix picks 0..k-1), bit-equal to play_round
        spot_bulk = BulkRng(SERVER, CLIENT, nonce_start=1)
        pos50 = spot_bulk.mines_positions(self.MINES, 50)
        vec_win = ~np.any(pos50 < self.PICKS, axis=1)
        for i in range(50):
            scalar = eng.play_round(SERVER, CLIENT, 1 + i)
            assert scalar["win"] == bool(vec_win[i])

        chain = sz.BankrollChain(self.START, 1, eng)
        assert chain.exact_lattice and chain.lattice_denominator == 140
        expected = chain.survival_curve(self.N_ROUNDS)

        rng = BulkRng(SERVER, CLIENT, nonce_start=1000)
        # bankroll in exact 1/140 units of the bet: no float drift at the
        # ruin threshold
        bank = np.full(N_SESSIONS, self.START * 140, dtype=np.int64)
        alive = np.ones(N_SESSIONS, dtype=bool)
        survival_hat = np.empty(self.N_ROUNDS)
        wins = rounds = 0
        for t in range(self.N_ROUNDS):
            idx = np.flatnonzero(alive)
            pos = rng.mines_positions(self.MINES, idx.size)
            lost = np.any(pos < self.PICKS, axis=1)   # engine settle rule
            bank[idx] += np.where(lost, -140, 67)
            wins += int(idx.size - np.count_nonzero(lost))
            rounds += idx.size
            dead = bank[idx] < 140                    # cannot place next bet
            alive[idx[dead]] = False
            survival_hat[t] = np.count_nonzero(alive) / N_SESSIONS

        # per-round win rate vs the engine's exact analytic probability
        p_win = float(eng.win_probability_exact)
        se_win = math.sqrt(p_win * (1 - p_win) / rounds)
        assert abs(wins / rounds - p_win) <= 3.0 * se_win

        # survival at every checkpoint within 3 SE of the Markov solver
        for t in range(self.N_ROUNDS):
            s = expected[t]
            if s in (0.0, 1.0):
                assert survival_hat[t] == s
                continue
            se = math.sqrt(s * (1.0 - s) / N_SESSIONS)
            assert abs(survival_hat[t] - s) <= 3.0 * se, (
                f"round {t + 1}: sim {survival_hat[t]} vs solver {s} "
                f"(z={(survival_hat[t] - s) / se:.2f})"
            )
