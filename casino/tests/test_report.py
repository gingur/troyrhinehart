"""Tests for spinquest_sim.report: every headline number in the demo report
is recomputed independently from the session ledger, plus unit tests of the
metric definitions on hand-built sessions with hand-computed answers."""

import importlib.util
import math
import os
import re
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spinquest_sim import sizing  # noqa: E402
from spinquest_sim.report import (  # noqa: E402
    compute_metrics,
    generate_report,
    ruin_probability_diffusion,
)
from spinquest_sim.session import Session  # noqa: E402


def _load_demo():
    path = os.path.join(os.path.dirname(__file__), "..", "scripts",
                        "demo_report.py")
    spec = importlib.util.spec_from_file_location("demo_report", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _norm_cdf(x):
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


# ---------------------------------------------------------------------------
# hand-built session with hand-computed answers
# ---------------------------------------------------------------------------

@pytest.fixture()
def tiny():
    """4 bets, every metric computable by hand."""
    s = Session("100.00", started_at="2026-01-01T20:00:00")
    ts = ["2026-01-01T20:00:05", "2026-01-01T20:00:10",
          "2026-01-01T20:00:20", "2026-01-01T20:00:35"]
    s.record_bet("A", {"k": 1}, "10.00", "2", ts[0])     # win  +10
    s.record_bet("A", {"k": 1}, "10.00", "0", ts[1])     # loss -10
    s.record_bet("B", None, "5.00", "1", ts[2])          # push   0
    s.record_bet("B", None, "5.00", "0.5", ts[3])        # loss -2.50
    analytics = {
        "A": {"rtp": 0.95, "variance_per_unit": 1.0},
        "B": {"rtp": 0.98, "std_per_unit": 2.0},
    }
    return s, analytics


class TestTinySession:
    def test_bankroll_and_wagering(self, tiny):
        s, an = tiny
        m = compute_metrics(s, an)
        assert m["bankroll"]["starting"] == 100.0
        assert m["bankroll"]["pnl"] == pytest.approx(-2.50)
        assert m["bankroll"]["final"] == pytest.approx(97.50)
        assert m["wagering"]["handle"] == pytest.approx(30.0)
        assert m["wagering"]["total_returned"] == pytest.approx(27.50)
        assert m["wagering"]["n_bets"] == 4
        assert m["wagering"]["avg_stake"] == pytest.approx(7.50)
        assert m["performance"]["realized_rtp"] == pytest.approx(27.5 / 30)

    def test_expectation_decomposition_by_hand(self, tiny):
        s, an = tiny
        m = compute_metrics(s, an)
        p = m["performance"]
        # E[pnl] = 2*10*(0.95-1) + 2*5*(0.98-1) = -1.0 - 0.2 = -1.2
        assert p["expected_pnl"] == pytest.approx(-1.2)
        assert p["expected_loss"] == pytest.approx(1.2)
        # SD = sqrt(2*10^2*1.0 + 2*5^2*4.0) = sqrt(400) = 20
        assert p["sd_pnl"] == pytest.approx(20.0)
        assert p["luck_dollars"] == pytest.approx(-2.5 - (-1.2))
        assert p["luck_z"] == pytest.approx(-1.3 / 20.0)
        assert p["luck_p_two_sided"] == pytest.approx(
            2 * _norm_cdf(-abs(-1.3 / 20.0)))
        # stake-weighted expected RTP = 1 + (-1.2)/30
        assert p["expected_rtp"] == pytest.approx(1 - 1.2 / 30)
        assert p["expected_edge"] == pytest.approx(1.2 / 30)
        assert p["rtp_se"] == pytest.approx(20.0 / 30.0)
        assert p["full_coverage"] is True
        assert p["coverage_handle_frac"] == 1.0

    def test_distribution_by_hand(self, tiny):
        s, an = tiny
        d = compute_metrics(s, an)["distribution"]
        assert d["n_wins"] == 1 and d["n_pushes"] == 1 and d["n_losses"] == 2
        assert d["win_rate"] == pytest.approx(0.25)
        assert d["avg_win"] == pytest.approx(10.0)
        assert d["avg_loss"] == pytest.approx(-6.25)
        assert d["payoff_ratio"] == pytest.approx(10.0 / 6.25)
        assert d["profit_factor"] == pytest.approx(10.0 / 12.5)
        assert d["best_bet_net"] == pytest.approx(10.0)
        assert d["best_bet_game"] == "A"
        assert d["worst_bet_net"] == pytest.approx(-10.0)
        assert d["max_multiplier_hit"] == pytest.approx(2.0)
        nets = np.array([10.0, -10.0, 0.0, -2.5])
        assert d["std_net_per_bet"] == pytest.approx(float(nets.std()))
        assert d["var95"] == pytest.approx(float(np.percentile(nets, 5)))
        assert d["cvar95"] == pytest.approx(
            float(nets[nets <= np.percentile(nets, 5)].mean()))
        # order: win, loss, push, loss -> streaks of 1
        assert d["max_consecutive_wins"] == 1
        assert d["max_consecutive_losses"] == 1

    def test_per_game_attribution_by_hand(self, tiny):
        s, an = tiny
        rows = {r["game"]: r for r in compute_metrics(s, an)["per_game"]}
        a, b = rows["A"], rows["B"]
        assert a["bets"] == 2 and b["bets"] == 2
        assert a["handle"] == pytest.approx(20.0)
        assert a["net"] == pytest.approx(0.0)
        assert a["expected_net"] == pytest.approx(-1.0)
        assert a["edge_paid"] == pytest.approx(1.0)
        assert a["luck"] == pytest.approx(1.0)
        assert a["sd"] == pytest.approx(math.sqrt(200.0))
        assert a["z"] == pytest.approx(1.0 / math.sqrt(200.0))
        assert b["net"] == pytest.approx(-2.5)
        assert b["expected_net"] == pytest.approx(-0.2)
        assert b["realized_rtp"] == pytest.approx(7.5 / 10.0)
        assert a["share_of_handle"] + b["share_of_handle"] == pytest.approx(1.0)

    def test_pacing(self, tiny):
        s, an = tiny
        pac = compute_metrics(s, an)["pacing"]
        assert pac["duration_seconds"] == pytest.approx(30.0)
        assert pac["avg_seconds_between_bets"] == pytest.approx(10.0)
        assert pac["bets_per_hour"] == pytest.approx(4 / (30 / 3600))

    def test_partial_coverage(self, tiny):
        s, an = tiny
        m = compute_metrics(s, {"A": an["A"]})
        p = m["performance"]
        assert p["full_coverage"] is False
        assert p["coverage_bets_frac"] == pytest.approx(0.5)
        assert p["coverage_handle_frac"] == pytest.approx(20.0 / 30.0)
        assert p["expected_pnl"] == pytest.approx(-1.0)   # A only
        assert p["covered_handle"] == pytest.approx(20.0)
        rows = {r["game"]: r for r in m["per_game"]}
        assert rows["B"]["expected_net"] is None
        # expectation overlays are dropped from the plots (no luck figure)
        html = generate_report(s, {"A": an["A"]})
        assert 'alt="luck"' not in html
        assert 'alt="bankroll"' in html

    def test_no_analytics(self, tiny):
        s, _ = tiny
        m = compute_metrics(s)
        assert m["performance"]["expected_rtp"] is None
        assert m["performance"]["luck_z"] is None
        html = generate_report(s)
        assert "data:image/png;base64," in html


class TestStreaks:
    def test_push_breaks_both(self):
        s = Session("100.00")
        mults = ["2", "2", "0", "0", "0", "1", "2"]
        for i, mu in enumerate(mults):
            s.record_bet("g", None, "1.00", mu, f"2026-01-01T00:00:{i:02d}")
        d = compute_metrics(s)["distribution"]
        assert d["max_consecutive_wins"] == 2
        assert d["max_consecutive_losses"] == 3


class TestErrors:
    def test_empty_session_raises(self):
        with pytest.raises(ValueError):
            compute_metrics(Session("100.00"))

    def test_bad_analytics_raises(self):
        s = Session("100.00")
        s.record_bet("g", None, "1.00", "2", "2026-01-01T00:00:00")
        with pytest.raises(ValueError):
            compute_metrics(s, {"g": {"house_edge": 0.02}})  # no rtp
        with pytest.raises(ValueError):
            compute_metrics(s, {"g": {"rtp": 0.98}})  # no variance/std


class TestRuinProbability:
    def test_bounds_and_monotonicity(self):
        args = dict(bankroll=100.0, bet=5.0, edge=0.02, var_per_unit=1.0)
        ps = [ruin_probability_diffusion(n_bets=n, **args)
              for n in (10, 100, 1000, 10000, 100000)]
        assert all(0.0 <= p <= 1.0 for p in ps)
        assert ps == sorted(ps)                     # monotone in horizon
        # more edge -> more ruin
        p_hi = ruin_probability_diffusion(100.0, 5.0, 0.05, 1.0, 1000)
        assert p_hi >= ps[2]
        # negative drift forever -> certain ruin
        assert ruin_probability_diffusion(100.0, 5.0, 0.02, 1.0, 10**9) > 0.999

    def test_degenerate_cases(self):
        assert ruin_probability_diffusion(0.0, 1.0, 0.01, 1.0, 10) == 1.0
        assert ruin_probability_diffusion(100.0, 1.0, 0.01, 1.0, 0) == 0.0
        # zero variance: ruin iff drift covers the bankroll
        assert ruin_probability_diffusion(10.0, 1.0, 0.1, 0.0, 99) == 0.0
        assert ruin_probability_diffusion(10.0, 1.0, 0.1, 0.0, 100) == 1.0

    def test_against_exact_markov_chain(self):
        """Fair even-money coin: diffusion vs the exact BankrollChain."""
        cfg = {"distribution": [(0, "1/2"), (2, "1/2")]}
        chain = sizing.BankrollChain(10, 1, cfg)
        exact = 1.0 - float(chain.run(100)["p_alive"])
        approx = ruin_probability_diffusion(10.0, 1.0, 0.0, 1.0, 100)
        assert approx == pytest.approx(exact, abs=0.05)

    def test_deep_tail_is_finite(self):
        # would overflow exp() without the log-space branch
        p = ruin_probability_diffusion(1_000_000.0, 1.0, 0.01, 1.0, 100)
        assert p == 0.0 or (0.0 < p < 1e-100)


class TestStops:
    def test_stop_latch_and_violation(self):
        s = Session("100.00", stop_loss="20.00", allow_negative_bankroll=True)
        for i in range(3):                        # -30 by bet 3
            s.record_bet("g", None, "10.00", "0", f"2026-01-01T00:00:0{i}")
        assert s.stopped and s.stop_reason == "stop_loss"
        # keeps betting after the stop: 2 violations
        s.record_bet("g", None, "5.00", "2", "2026-01-01T00:00:03")
        s.record_bet("g", None, "5.00", "0", "2026-01-01T00:00:04")
        st = compute_metrics(s)["stops"]
        assert st["stopped"] is True
        assert st["stop_reason"] == "stop_loss"
        assert st["stop_seq"] == 2                # pnl hits -20 on bet 2
        assert st["adhered"] is False
        assert st["bets_after_stop"] == 3
        assert st["handle_after_stop"] == pytest.approx(20.0)
        assert st["net_after_stop"] == pytest.approx(-10.0)
        assert st["pnl_at_stop"] == pytest.approx(-20.0)

    def test_adhered_when_no_bets_after(self):
        s = Session("100.00", stop_win="10.00")
        s.record_bet("g", None, "10.00", "2", "2026-01-01T00:00:00")
        st = compute_metrics(s)["stops"]
        assert st["stopped"] and st["adhered"] is True
        assert st["bets_after_stop"] == 0

    def test_not_stopped_distances(self):
        s = Session("100.00", stop_loss="50.00", stop_win="50.00")
        s.record_bet("g", None, "10.00", "2", "2026-01-01T00:00:00")  # +10
        st = compute_metrics(s)["stops"]
        assert st["stopped"] is False and st["adhered"] is True
        assert st["distance_to_stops"]["stop_loss"] == pytest.approx(60.0)
        assert st["distance_to_stops"]["stop_win"] == pytest.approx(40.0)


# ---------------------------------------------------------------------------
# the demo session: every headline number recomputed from the ledger
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def demo():
    mod = _load_demo()
    session, analytics = mod.build_demo_session()
    metrics = compute_metrics(session, analytics)
    return mod, session, analytics, metrics


class TestDemoHeadlines:
    def test_ledger_totals(self, demo):
        _, s, _, m = demo
        stakes = [float(b.stake) for b in s.bets]
        payouts = [float(b.payout) for b in s.bets]
        nets = [float(b.net) for b in s.bets]
        assert m["wagering"]["n_bets"] == len(s.bets) == 2000
        assert m["wagering"]["handle"] == pytest.approx(sum(stakes))
        assert m["wagering"]["total_returned"] == pytest.approx(sum(payouts))
        assert m["bankroll"]["pnl"] == pytest.approx(sum(nets))
        assert m["bankroll"]["pnl"] == pytest.approx(float(s.pnl))
        assert m["bankroll"]["final"] == pytest.approx(
            m["bankroll"]["starting"] + m["bankroll"]["pnl"])
        assert m["performance"]["realized_rtp"] == pytest.approx(
            sum(payouts) / sum(stakes))
        assert m["performance"]["realized_edge"] == pytest.approx(
            1 - sum(payouts) / sum(stakes))

    def test_expectation_recomputed_from_engines(self, demo):
        _, s, analytics, m = demo
        exp = sd2 = 0.0
        for b in s.bets:
            eng = analytics[b.game]
            st = float(b.stake)
            exp += st * (eng.rtp - 1.0)
            sd2 += st * st * eng.variance_per_unit
        p = m["performance"]
        assert p["full_coverage"] is True
        assert p["expected_pnl"] == pytest.approx(exp)
        assert p["sd_pnl"] == pytest.approx(math.sqrt(sd2))
        assert p["luck_dollars"] == pytest.approx(float(s.pnl) - exp)
        assert p["luck_z"] == pytest.approx(
            (float(s.pnl) - exp) / math.sqrt(sd2))
        handle = sum(float(b.stake) for b in s.bets)
        assert p["expected_rtp"] == pytest.approx(1.0 + exp / handle)
        assert p["expected_edge"] == pytest.approx(-exp / handle)
        assert p["luck_p_two_sided"] == pytest.approx(
            2 * _norm_cdf(-abs(p["luck_z"])))

    def test_per_game_reconciles_to_totals(self, demo):
        _, s, analytics, m = demo
        rows = m["per_game"]
        assert sum(r["bets"] for r in rows) == 2000
        assert sum(r["handle"] for r in rows) == pytest.approx(
            m["wagering"]["handle"])
        assert sum(r["net"] for r in rows) == pytest.approx(
            m["bankroll"]["pnl"])
        assert sum(r["expected_net"] for r in rows) == pytest.approx(
            m["performance"]["expected_pnl"])
        assert sum(r["luck"] for r in rows) == pytest.approx(
            m["performance"]["luck_dollars"])
        # spot recompute one game end-to-end
        g = rows[0]["game"]
        gb = [b for b in s.bets if b.game == g]
        assert rows[0]["bets"] == len(gb)
        assert rows[0]["handle"] == pytest.approx(
            sum(float(b.stake) for b in gb))
        assert rows[0]["realized_rtp"] == pytest.approx(
            sum(float(b.payout) for b in gb)
            / sum(float(b.stake) for b in gb))
        assert rows[0]["analytic_rtp"] == pytest.approx(analytics[g].rtp)
        gsd = math.sqrt(sum(
            float(b.stake) ** 2 * analytics[g].variance_per_unit for b in gb))
        assert rows[0]["sd"] == pytest.approx(gsd)
        assert rows[0]["z"] == pytest.approx(rows[0]["luck"] / gsd)

    def test_drawdown_recomputed_from_equity_curve(self, demo):
        _, s, _, m = demo
        nets = np.array([float(b.net) for b in s.bets])
        equity = float(s.starting_bankroll) + np.cumsum(nets)
        peak = np.maximum.accumulate(
            np.maximum(equity, float(s.starting_bankroll)))
        dd = m["drawdown"]
        assert dd["max_dd"] == pytest.approx(float((peak - equity).max()))
        assert dd["max_dd"] == pytest.approx(float(s.max_drawdown))
        assert dd["max_dd_pct"] == pytest.approx(
            float(((peak - equity) / peak).max()))
        assert dd["max_dd_pct"] == pytest.approx(float(s.max_drawdown_pct))
        assert m["bankroll"]["peak"] == pytest.approx(float(peak.max()))
        assert dd["ulcer_index"] == pytest.approx(
            math.sqrt(float((((peak - equity) / peak) ** 2).mean())))
        assert dd["current_dd"] == pytest.approx(float(peak[-1] - equity[-1]))
        assert len(dd["worst"]) <= 10
        # worst table headline reconciles with the max-% figure
        worst_pct = max(ep["drawdown_pct_value"] for ep in dd["worst"])
        assert worst_pct == pytest.approx(dd["max_dd_pct"])

    def test_distribution_recomputed(self, demo):
        _, s, _, m = demo
        nets = np.array([float(b.net) for b in s.bets])
        stakes = np.array([float(b.stake) for b in s.bets])
        payouts = np.array([float(b.payout) for b in s.bets])
        d = m["distribution"]
        assert d["win_rate"] == pytest.approx(float((payouts > stakes).mean()))
        assert d["push_rate"] == pytest.approx(
            float((payouts == stakes).mean()))
        assert d["avg_win"] == pytest.approx(float(nets[nets > 0].mean()))
        assert d["avg_loss"] == pytest.approx(float(nets[nets < 0].mean()))
        assert d["profit_factor"] == pytest.approx(
            float(nets[nets > 0].sum() / -nets[nets < 0].sum()))
        assert d["var95"] == pytest.approx(float(np.percentile(nets, 5)))
        assert d["cvar95"] == pytest.approx(
            float(nets[nets <= np.percentile(nets, 5)].mean()))
        assert d["best_bet_net"] == pytest.approx(float(nets.max()))
        assert d["worst_bet_net"] == pytest.approx(float(nets.min()))
        assert d["std_net_per_bet"] == pytest.approx(float(nets.std()))
        # skew / excess kurtosis: population moments
        c = nets - nets.mean()
        m2 = float((c ** 2).mean())
        assert d["skew"] == pytest.approx(float((c ** 3).mean()) / m2 ** 1.5)
        assert d["kurtosis_excess"] == pytest.approx(
            float((c ** 4).mean()) / m2 ** 2 - 3.0)

    def test_stop_audit_recomputed(self, demo):
        _, s, _, m = demo
        st = m["stops"]
        assert st["stopped"] == s.stopped
        if s.stopped:
            after = [b for b in s.bets if b.seq > s.stop_seq]
            assert st["bets_after_stop"] == len(after)
            assert st["handle_after_stop"] == pytest.approx(
                sum(float(b.stake) for b in after))
            assert st["net_after_stop"] == pytest.approx(
                sum(float(b.net) for b in after))
            assert st["adhered"] == (not after)
            # the latch really is the FIRST crossing of a stop threshold
            run = 0.0
            first = None
            for b in s.bets:
                run += float(b.net)
                if first is None and (run <= -float(s.stop_loss)
                                      or run >= float(s.stop_win)):
                    first = b.seq
                    break
            assert first == s.stop_seq

    def test_risk_of_ruin_block(self, demo):
        _, s, analytics, m = demo
        ror = m["risk_of_ruin"]
        stakes = np.array([float(b.stake) for b in s.bets])
        edges = np.array([1.0 - analytics[b.game].rtp for b in s.bets])
        variances = np.array(
            [analytics[b.game].variance_per_unit for b in s.bets])
        assert ror["avg_stake"] == pytest.approx(float(stakes.mean()))
        assert ror["blended_edge"] == pytest.approx(
            float((stakes * edges).sum() / stakes.sum()))
        assert ror["blended_var_per_unit"] == pytest.approx(
            float((stakes ** 2 * variances).sum() / (stakes ** 2).sum()))
        ps = [h["p_ruin"] for h in ror["horizons"]]
        assert all(0.0 <= p <= 1.0 for p in ps)
        assert ps == sorted(ps)
        assert ror["horizons"][1]["p_ruin"] == pytest.approx(
            ruin_probability_diffusion(
                ror["current_bankroll"], ror["avg_stake"],
                ror["blended_edge"], ror["blended_var_per_unit"], 1000))

    def test_pacing_recomputed(self, demo):
        from datetime import datetime
        _, s, _, m = demo
        t0 = datetime.fromisoformat(s.bets[0].timestamp)
        t1 = datetime.fromisoformat(s.bets[-1].timestamp)
        dur = (t1 - t0).total_seconds()
        assert m["pacing"]["duration_seconds"] == pytest.approx(dur)
        assert m["pacing"]["bets_per_hour"] == pytest.approx(
            2000 / (dur / 3600))

    def test_demo_is_deterministic(self):
        mod = _load_demo()
        s1, _ = mod.build_demo_session(n_bets=60)
        s2, _ = mod.build_demo_session(n_bets=60)
        assert [str(b.net) for b in s1.bets] == [str(b.net) for b in s2.bets]
        assert s1.pnl == s2.pnl


@pytest.fixture(scope="module")
def rendered(demo, tmp_path_factory):
    mod, s, analytics, m = demo
    out = tmp_path_factory.mktemp("report") / "demo.html"
    html = generate_report(
        s, analytics, mod.build_sizing(),
        title="SpinQuest Strategy Report — Demo Session",
        output_path=str(out),
    )
    return html, out, m


class TestDemoHtml:
    def test_written_and_self_contained(self, rendered):
        html, out, _ = rendered
        assert out.read_text(encoding="utf-8") == html
        assert html.count("data:image/png;base64,") >= 6
        # no external fetches of any kind
        assert not re.search(r'(?:src|href)\s*=\s*["\']https?://', html)
        assert "<script" not in html.lower()

    def test_headline_numbers_appear_verbatim(self, rendered):
        from spinquest_sim.report import _money, _num, _pct
        html, _, m = rendered
        assert _money(m["bankroll"]["pnl"], signed=True) in html
        assert _pct(m["performance"]["realized_rtp"]) in html
        assert _pct(m["performance"]["expected_rtp"]) in html
        assert _num(m["performance"]["luck_z"]) in html
        assert _pct(m["drawdown"]["max_dd_pct"]) in html
        assert _money(m["drawdown"]["max_dd"]) in html
        assert _money(m["wagering"]["handle"]) in html
        assert _money(m["performance"]["luck_dollars"], signed=True) in html
        assert f"{m['wagering']['n_bets']:,} bets" in html
        for row in m["per_game"]:
            assert row["game"] in html

    def test_all_seven_figures_present(self, rendered):
        html, _, _ = rendered
        for key in ("bankroll", "underwater", "luck", "rolling_rtp",
                    "attribution", "net_hist", "ruin"):
            assert f'alt="{key}"' in html

    def test_stop_and_sizing_sections(self, rendered):
        html, _, m = rendered
        assert "Stop-loss / stop-win adherence" in html
        assert "Sizing" in html
        if m["stops"]["stopped"] and not m["stops"]["adhered"]:
            assert "violated" in html
        # the checked-in demo artifact target directory exists
        assert os.path.isdir(os.path.join(
            os.path.dirname(__file__), "..", "gauntlet", "report"))
