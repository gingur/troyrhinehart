"""Tests for spinquest_sim.session — hand-play session tracking.

Covers: bet recording, Decimal-exact money (no float cents drift), bankroll /
P&L / peak / max drawdown (dollar AND independent percent maxima), drawdown
episodes, absolute + percent stop-loss/stop-win latching (journalled), cash
deposits/withdrawals, per-game breakdown, JSON-serializable summary,
append-safe / reload-safe / tamper-evident JSONL persistence (including
torn-tail truncation), and the pandas DataFrame export.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from fractions import Fraction

import pandas as pd
import pytest

from spinquest_sim.session import CENT, BetRecord, MoneyError, Session


TS = "2026-08-24T12:00:00+00:00"


def ts(i: int) -> str:
    return f"2026-08-24T12:{i:02d}:00+00:00"


# ---------------------------------------------------------------------------
# recording basics
# ---------------------------------------------------------------------------

class TestRecordBet:
    def test_win_loss_push_ledger(self):
        s = Session("100.00")
        r1 = s.record_bet("blackjack", {"decks": 8}, "10.00", "2.5", ts(0))  # 3:2 win
        assert r1.payout == Decimal("25.00")
        assert r1.net == Decimal("15.00")
        assert s.bankroll == Decimal("115.00")

        r2 = s.record_bet("blackjack", {"decks": 8}, "10.00", 0, ts(1))     # loss
        assert r2.net == Decimal("-10.00")
        assert s.bankroll == Decimal("105.00")

        r3 = s.record_bet("blackjack", {"decks": 8}, "10.00", 1, ts(2))     # push
        assert r3.net == Decimal("0.00")
        assert s.bankroll == Decimal("105.00")
        assert s.pnl == Decimal("5.00")
        assert [r.seq for r in s.bets] == [1, 2, 3]

    def test_record_returns_immutable_record(self):
        s = Session(50)
        r = s.record_bet("keno", {}, 1, 0, TS)
        assert isinstance(r, BetRecord)
        with pytest.raises(AttributeError):
            r.stake = Decimal("999")  # frozen dataclass

    def test_config_is_deeply_immutable(self):
        s = Session(100)
        cfg = {"picks": [1, 2, 3]}
        r = s.record_bet("keno", cfg, 1, 0, TS)
        # mutating the caller's dict after the fact does not touch the record
        cfg["picks"].append(99)
        assert r.config["picks"] == [1, 2, 3]
        # mutating what the record hands out does not stick either
        view = r.config
        view["injected"] = True
        assert "injected" not in s.bets[0].config
        assert s.bets[0].config == {"picks": [1, 2, 3]}

    def test_config_canonicalized_at_record_time(self):
        # Non-string keys are canonicalized (JSON object keys are strings)
        # at record time, so memory and disk can never disagree.
        s = Session(100)
        r = s.record_bet("g", {1: "a"}, 1, 0, TS)
        assert r.config == {"1": "a"}
        assert r.config_json == '{"1":"a"}'

    def test_timestamp_datetime_normalized(self):
        s = Session(50)
        dt = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)
        r = s.record_bet("keno", {}, 1, 0, dt)
        assert r.timestamp == dt.isoformat()

    def test_timestamp_required_from_caller(self):
        s = Session(50)
        with pytest.raises(TypeError):
            s.record_bet("keno", {}, 1, 0, None)
        with pytest.raises(ValueError):
            s.record_bet("keno", {}, 1, 0, "")

    def test_timestamp_anomalies_flagged_not_blocked(self):
        s = Session(1000)
        s.record_bet("g", {}, 10, 0, ts(1))
        s.record_bet("g", {}, 10, 0, ts(0))                       # backwards
        s.record_bet("g", {}, 10, 0, "not a timestamp at all")    # unparseable
        assert len(s.bets) == 3                                   # never blocking
        assert s.timestamp_anomalies == 2
        assert s.summary()["timestamp_anomalies"] == 2

    def test_input_validation(self):
        s = Session(50)
        with pytest.raises(MoneyError):
            s.record_bet("keno", {}, 0, 1, TS)          # zero stake
        with pytest.raises(MoneyError):
            s.record_bet("keno", {}, -5, 1, TS)         # negative stake
        with pytest.raises(MoneyError):
            s.record_bet("keno", {}, "1.005", 1, TS)    # sub-cent stake
        with pytest.raises(MoneyError):
            s.record_bet("keno", {}, 1, -1, TS)         # negative multiplier
        with pytest.raises(MoneyError):
            s.record_bet("keno", {}, "nan", 1, TS)
        with pytest.raises(ValueError):
            s.record_bet("", {}, 1, 1, TS)              # empty game name
        with pytest.raises(ValueError):
            s.record_bet("keno", {"bad": object()}, 1, 1, TS)  # unserializable config
        # nothing was recorded by any failed call
        assert s.bets == [] and s.bankroll == Decimal("50.00")

    def test_huge_magnitudes_raise_money_error(self):
        # decimal.InvalidOperation must never escape the MoneyError contract.
        with pytest.raises(MoneyError):
            Session("1e30")
        s = Session(100, allow_negative_bankroll=True)
        with pytest.raises(MoneyError):
            s.record_bet("g", {}, 1e30, 0, TS)
        with pytest.raises(MoneyError):
            s.record_bet("g", {}, "1e30", 0, TS)
        with pytest.raises(MoneyError):
            s.record_bet("g", {}, "1.00", "1e30", TS)   # payout overflow
        assert s.bets == [] and s.bankroll == Decimal("100.00")

    def test_negative_zero_normalized(self):
        s = Session(100)
        r = s.record_bet("g", {}, "1.00", "-0.00", TS)  # -0 == 0: a plain loss
        assert str(r.payout) == "0.00"                  # never "-0.00"
        assert r.net == Decimal("-1.00")
        assert s.bankroll == Decimal("99.00")

    def test_stake_exceeding_bankroll_rejected_by_default(self):
        s = Session("20.00")
        with pytest.raises(MoneyError):
            s.record_bet("roulette", {}, "20.01", 2, TS)
        s2 = Session("20.00", allow_negative_bankroll=True)
        s2.record_bet("roulette", {}, "30.00", 0, TS)
        assert s2.bankroll == Decimal("-10.00")

    def test_starting_bankroll_validation(self):
        with pytest.raises(MoneyError):
            Session(0)
        with pytest.raises(MoneyError):
            Session(-10)
        with pytest.raises(MoneyError):
            Session("10.005")


# ---------------------------------------------------------------------------
# Decimal-safe money
# ---------------------------------------------------------------------------

class TestDecimalSafety:
    def test_no_float_cents_drift_over_many_bets(self):
        # 1000 bets of $0.10 at 1.1x -> each nets exactly +$0.01.
        # In float, 0.1 * 1.1 accumulates drift; in cents it is exact.
        s = Session("100.00")
        for i in range(1000):
            r = s.record_bet("slots", {}, "0.10", "1.1", ts(i % 60))
            assert r.net == Decimal("0.01")
        assert s.bankroll == Decimal("110.00")
        assert s.pnl == Decimal("10.00")

    def test_float_inputs_read_as_printed_value(self):
        s = Session(100.0)
        assert s.starting_bankroll == Decimal("100.00")
        r = s.record_bet("dice", {}, 0.1, 0.3, TS)  # 0.1 * 0.3 = 0.03 exactly
        assert r.payout == Decimal("0.03")
        assert r.net == Decimal("-0.07")

    def test_payout_quantized_half_up(self):
        s = Session(100)
        # 1.01 * 1.5 = 1.515 -> 1.52 (ROUND_HALF_UP)
        r = s.record_bet("crash", {}, "1.01", "1.5", TS)
        assert r.payout == Decimal("1.52")

    def test_all_money_fields_are_cent_decimals(self):
        s = Session(100)
        r = s.record_bet("wheel", {"risk": "low"}, "3.33", "1.2", TS)
        for value in (r.stake, r.payout, r.net, r.bankroll_after, s.bankroll,
                      s.pnl, s.peak_bankroll, s.max_drawdown):
            assert isinstance(value, Decimal)
            assert value == value.quantize(CENT)


# ---------------------------------------------------------------------------
# peak / drawdown
# ---------------------------------------------------------------------------

class TestPeakAndDrawdown:
    def test_peak_and_max_drawdown(self):
        s = Session("100.00")
        s.record_bet("g", {}, "10.00", 3, ts(0))   # +20 -> 120 (peak)
        s.record_bet("g", {}, "30.00", 0, ts(1))   # -30 -> 90
        s.record_bet("g", {}, "10.00", 0, ts(2))   # -10 -> 80  (dd 40 from 120)
        s.record_bet("g", {}, "10.00", 6, ts(3))   # +50 -> 130 (new peak)
        s.record_bet("g", {}, "20.00", 0, ts(4))   # -20 -> 110 (dd 20 < 40)
        assert s.peak_bankroll == Decimal("130.00")
        assert s.max_drawdown == Decimal("40.00")
        assert s.max_drawdown_pct == Fraction(1, 3)          # exact 40/120
        assert s.bankroll == Decimal("110.00")

    def test_max_drawdown_pct_decoupled_from_dollar_max(self):
        # The critic's counterexample: 100 -> 50 (50% dd), then 1000 -> 940
        # (a $60 dip, dollar-larger but only 6%).  The percent max must stay
        # at 50% while the dollar max moves to $60.
        s = Session("100.00", allow_negative_bankroll=True)
        s.record_bet("g", {}, "50.00", 0, ts(0))       # 100 -> 50
        assert s.max_drawdown == Decimal("50.00")
        assert s.max_drawdown_pct == Fraction(1, 2)
        s.record_bet("g", {}, "50.00", "20", ts(1))    # 50 -> 1000 (new peak)
        s.record_bet("g", {}, "60.00", 0, ts(2))       # 1000 -> 940
        assert s.max_drawdown == Decimal("60.00")      # dollar max updated
        assert s.max_drawdown_pct == Fraction(1, 2)    # percent max preserved
        # the two maxima come from different peaks, and both are exposed
        assert s.max_drawdown_peak == Decimal("1000.00")
        assert s.max_drawdown_pct_peak == Decimal("100.00")

    def test_max_drawdown_pct_is_monotone(self):
        s = Session("100.00", allow_negative_bankroll=True)
        seen = [s.max_drawdown_pct]
        moves = [("50.00", "0"), ("10.00", "10"), ("30.00", "0"),
                 ("5.00", "40"), ("100.00", "0"), ("20.00", "0")]
        for i, (stake, mult) in enumerate(moves):
            s.record_bet("g", {}, stake, mult, ts(i))
            seen.append(s.max_drawdown_pct)
        assert all(b >= a for a, b in zip(seen, seen[1:]))

    def test_no_drawdown_when_only_winning(self):
        s = Session(100)
        s.record_bet("g", {}, 10, 2, ts(0))
        s.record_bet("g", {}, 10, 2, ts(1))
        assert s.max_drawdown == Decimal("0.00")
        assert s.max_drawdown_pct == 0
        assert s.peak_bankroll == Decimal("120.00")
        assert s.max_drawdown_peak is None and s.max_drawdown_pct_peak is None

    def test_drawdown_episodes_and_summary_section(self):
        s = Session("100.00")
        s.record_bet("g", {}, "10.00", 3, ts(0))   # +20 -> 120 (peak, seq 1)
        s.record_bet("g", {}, "30.00", 0, ts(1))   # -30 -> 90
        s.record_bet("g", {}, "10.00", 0, ts(2))   # -10 -> 80 (trough, seq 3)
        s.record_bet("g", {}, "10.00", 6, ts(3))   # +50 -> 130 (recovery, seq 4)
        s.record_bet("g", {}, "20.00", 0, ts(4))   # -20 -> 110 (open episode)
        summ = s.summary()
        assert summ["max_drawdown"] == "40.00"
        assert summ["max_drawdown_pct"] == "33.33%"
        assert summ["max_drawdown_pct_value"] == pytest.approx(1 / 3)
        dd = summ["drawdown"]
        assert dd["max"]["from_peak"] == "120.00"
        assert dd["max"]["amount"] == "40.00"
        assert dd["max"]["start_seq"] == 1 and dd["max"]["start_at"] == ts(0)
        assert dd["max"]["trough_seq"] == 3 and dd["max"]["trough_at"] == ts(2)
        assert dd["max_pct"]["pct"] == "33.33%"
        worst = dd["worst"]
        assert worst[0]["from_peak"] == "120.00"
        assert worst[0]["trough"] == "80.00"
        assert worst[0]["drawdown"] == "40.00"
        assert worst[0]["drawdown_pct"] == "33.33%"
        assert worst[0]["recovered"] is True
        assert worst[0]["recovered_seq"] == 4 and worst[0]["recovered_at"] == ts(3)
        assert worst[0]["bets"] == 3
        assert worst[0]["days"] == pytest.approx(3 / 1440)   # 3 minutes
        # the still-open episode (130 -> 110) is closed at the last bet
        assert worst[1]["from_peak"] == "130.00"
        assert worst[1]["recovered"] is False
        assert worst[1]["recovered_seq"] == 5 and worst[1]["recovered_at"] == ts(4)
        assert dd["longest_bets"] == 3
        assert dd["count"] == 2
        json.dumps(summ)  # everything JSON-safe

    def test_open_episode_closed_at_last_observation(self):
        # The round-2 blocker: a drawdown still open at session end must be
        # measured peak -> last observation and fold into longest_*.
        s = Session("1000.00")
        s.record_bet("g", {}, "100.00", 0, "2026-03-01T12:00:00")   #  900
        s.record_bet("g", {}, "100.00", 3, "2026-03-03T12:00:00")   # 1100 peak
        s.record_bet("g", {}, "400.00", 0, "2026-03-04T12:00:00")   #  700
        for d in range(5, 31):
            s.record_bet("g", {}, "1.00", 1, f"2026-03-{d:02d}T12:00:00")
        summ = s.summary()
        dd = summ["drawdown"]
        # underwater from the 2026-03-03 peak to the last bet on 2026-03-30
        assert dd["longest_bets"] == 27
        assert dd["longest_days"] == pytest.approx(27.0)
        top = dd["worst"][0]
        assert top["recovered"] is False
        assert top["start_at"] == "2026-03-03T12:00:00"
        assert top["recovered_at"] == "2026-03-30T12:00:00"
        assert top["days"] == pytest.approx(27.0) and top["bets"] == 27
        # the headline never contradicts its own table
        table_max = max(e["days"] for e in dd["worst"] if e["days"] is not None)
        assert dd["longest_days"] >= table_max
        # Max DD Period End is readable straight off the summary
        assert dd["max_pct"]["recovered_at"] == "2026-03-30T12:00:00"
        assert dd["max_pct"]["recovered"] is False
        assert dd["max_pct"]["days"] == pytest.approx(27.0)

    def test_longest_updates_when_open_episode_recovers(self):
        s = Session("100.00")
        s.record_bet("g", {}, "10.00", 0, ts(0))     # dd starts (session peak)
        s.record_bet("g", {}, "10.00", 1, ts(1))     # push, still under
        assert s.longest_drawdown_bets == 2          # open episode counts
        s.record_bet("g", {}, "10.00", 3, ts(2))     # recovers
        assert s.longest_drawdown_bets == 3
        assert s.longest_drawdown_days == pytest.approx(2 / 1440)

    def test_session_start_episode_dates_from_first_bet(self):
        # An episode rooted at the opening peak has no peak bet; it dates
        # from started_at when given, else from the first bet's timestamp.
        s = Session("100.00")
        s.record_bet("g", {}, "10.00", 0, ts(1))
        s.record_bet("g", {}, "10.00", 3, ts(4))     # recovers
        e = s.drawdown_episodes()[0]
        assert e["start_seq"] == 0
        assert e["start_at"] == ts(1)
        assert e["days"] == pytest.approx(3 / 1440)
        s2 = Session("100.00", started_at=ts(0))
        s2.record_bet("g", {}, "10.00", 0, ts(1))
        e2 = s2.drawdown_episodes()[0]
        assert e2["start_at"] == ts(0)
        assert s2.summary()["started_at"] == ts(0)

    def test_average_drawdown_over_all_episodes(self):
        # ~200 alternating episodes: averages must cover ALL of them even
        # though the retained worst table is capped at 32.
        s = Session("1000000.00")
        for i in range(400):
            s.record_bet("g", {}, "100.00", 0 if i % 2 == 0 else "2.05", ts(i % 60))
        dd = s.summary()["drawdown"]
        assert dd["count"] == 200
        assert s.drawdown_episode_count == 200
        assert len(s.drawdown_episodes()) <= 33     # capped table
        assert dd["avg_pct"] is not None and dd["avg_pct_value"] > 0
        # every episode here spans exactly 2 bets (loss then win)
        assert dd["longest_bets"] == 2

    def test_max_dollar_episode_never_evicted(self):
        # A dollar-huge but percent-small episode among 60+ percent-deeper
        # ones must survive the 32-episode cap so the summary's
        # max_drawdown headline stays reconcilable with the episode table.
        s = Session("100.00", allow_negative_bankroll=True)
        for i in range(40):                             # 40 episodes of 50%
            s.record_bet("g", {}, "50.00", 0, ts(i % 60))
            s.record_bet("g", {}, "25.00", 3, ts(i % 60))   # +50: recovers
        s.record_bet("g", {}, "100.00", 10001, ts(0))   # equity ~1,000,200
        s.record_bet("g", {}, "100000.00", 0, ts(1))    # $100,000 dd (~10%)
        s.record_bet("g", {}, "50000.00", 3, ts(2))     # +100,000: recovers
        for i in range(20):                             # more 50%-deep trims
            s.record_bet("g", {}, "50.00", 0, ts(i % 60))
            s.record_bet("g", {}, "25.00", 3, ts(i % 60))
        summ = s.summary()
        assert summ["max_drawdown"] == "100000.00"
        tops = [e["drawdown"] for e in s.drawdown_episodes()]
        assert "100000.00" in tops
        assert summ["drawdown"]["max"]["recovered"] is True
        assert summ["drawdown"]["max"]["amount"] == "100000.00"


# ---------------------------------------------------------------------------
# stop triggers
# ---------------------------------------------------------------------------

class TestStops:
    def test_absolute_stop_loss_latches(self):
        s = Session(100, stop_loss=30)
        s.record_bet("g", {}, 20, 0, ts(0))            # pnl -20, no stop
        assert not s.stopped
        s.record_bet("g", {}, 10, 0, ts(1))            # pnl -30, exact threshold
        assert s.stopped and s.stop_reason == "stop_loss" and s.stop_seq == 2

    def test_absolute_stop_win_latches(self):
        s = Session(100, stop_win="50.00")
        s.record_bet("g", {}, 20, 2, ts(0))            # pnl +20
        assert not s.stopped
        s.record_bet("g", {}, 40, 2, ts(1))            # pnl +60 >= 50
        assert s.stopped and s.stop_reason == "stop_win" and s.stop_seq == 2

    def test_percent_stop_loss(self):
        s = Session(200, stop_loss_pct="0.25")         # stop at -50
        s.record_bet("g", {}, 49, 0, ts(0))
        assert not s.stopped
        s.record_bet("g", {}, 1, 0, ts(1))             # pnl -50
        assert s.stopped and s.stop_reason == "stop_loss_pct"

    def test_percent_stop_win(self):
        s = Session(200, stop_win_pct=0.5)             # stop at +100
        s.record_bet("g", {}, 50, 3, ts(0))            # pnl +100
        assert s.stopped and s.stop_reason == "stop_win_pct" and s.stop_seq == 1

    def test_first_trigger_wins_and_latch_is_sticky(self):
        s = Session(100, stop_loss=10, stop_win=10)
        s.record_bet("g", {}, 10, 0, ts(0))            # pnl -10 -> stop_loss
        assert s.stopped and s.stop_reason == "stop_loss" and s.stop_seq == 1
        # keeps recording, latch does not change even if stop_win later crossed
        s.record_bet("g", {}, 10, 4, ts(1))            # pnl +20
        assert s.stop_reason == "stop_loss" and s.stop_seq == 1
        assert len(s.bets) == 2

    def test_tighter_of_absolute_and_percent(self):
        s = Session(100, stop_loss=50, stop_loss_pct="0.20")   # pct is tighter (-20)
        s.record_bet("g", {}, 20, 0, ts(0))
        assert s.stopped and s.stop_reason == "stop_loss_pct"

    def test_no_stops_configured(self):
        s = Session(100)
        s.record_bet("g", {}, 99, 0, ts(0))
        assert not s.stopped and s.stop_reason is None and s.stop_seq is None

    def test_stop_config_validation(self):
        with pytest.raises(MoneyError):
            Session(100, stop_loss=0)
        with pytest.raises(MoneyError):
            Session(100, stop_win=-5)
        with pytest.raises(MoneyError):
            Session(100, stop_loss_pct="1.5")   # cannot lose >100%
        with pytest.raises(MoneyError):
            Session(100, stop_win_pct=0)
        Session(100, stop_win_pct=5)            # >100% win target is fine


# ---------------------------------------------------------------------------
# cash flows
# ---------------------------------------------------------------------------

class TestCashFlows:
    def test_deposit_and_withdrawal_ledger(self):
        s = Session("100.00")
        s.deposit("50.00", ts(0))
        assert s.bankroll == Decimal("150.00")
        assert s.total_deposited == Decimal("50.00")
        assert s.pnl == Decimal("0.00")                # cash is not winnings
        s.withdraw("30.00", ts(1))
        assert s.bankroll == Decimal("120.00")
        assert s.total_withdrawn == Decimal("30.00")
        assert s.pnl == Decimal("0.00")
        assert [c.kind for c in s.cash_flows] == ["deposit", "withdrawal"]

    def test_cash_validation(self):
        s = Session("100.00")
        with pytest.raises(MoneyError):
            s.deposit(0, TS)
        with pytest.raises(MoneyError):
            s.deposit("-5.00", TS)
        with pytest.raises(MoneyError):
            s.withdraw("100.01", TS)   # cannot overdraw by default
        assert s.bankroll == Decimal("100.00") and s.cash_flows == []

    def test_deposit_does_not_reset_stop_loss(self):
        s = Session(100, stop_loss=30)
        s.record_bet("g", {}, 20, 0, ts(0))    # pnl -20
        s.deposit(50, ts(1))                   # bankroll 130, pnl still -20 (seq 2)
        s.record_bet("g", {}, 10, 0, ts(2))    # pnl -30 -> latch (journal seq 3)
        assert s.stopped and s.stop_reason == "stop_loss" and s.stop_seq == 3

    def test_cash_is_drawdown_neutral(self):
        # Drawdown is measured on the equity curve (cash backed out), so a
        # withdrawal neither fabricates a drawdown nor inflates its percent.
        s = Session("100.00")
        s.record_bet("g", {}, "10.00", 3, ts(0))    # equity 120 (peak)
        s.withdraw("50.00", ts(1))                  # bankroll 70, equity still 120
        assert s.max_drawdown == Decimal("0.00")    # withdrawing is not a loss
        assert s.peak_bankroll == Decimal("120.00")
        s.record_bet("g", {}, "10.00", 0, ts(2))    # equity 120 -> 110
        assert s.max_drawdown == Decimal("10.00")
        assert s.max_drawdown_pct == Fraction(10, 120)

    def test_withdrawal_plus_push_cannot_inflate_percent(self):
        # The critic's hand audit: 1000 -> 900 (10% dd), withdraw 850, then a
        # PUSH.  No money was lost, so max_drawdown_pct must stay at 10%.
        s = Session("1000.00", allow_negative_bankroll=True)
        s.record_bet("g", {}, "100.00", 0, ts(0))
        assert s.max_drawdown_pct == Fraction(1, 10)
        s.withdraw("850.00", ts(1))
        s.record_bet("g", {}, "10.00", 1, ts(2))    # push
        assert s.max_drawdown_pct == Fraction(1, 10)
        assert s.summary()["max_drawdown_pct"] == "10.00%"

    def test_deposit_mid_episode_keeps_headline_reconcilable(self):
        # 1000 -> 500 (50%), deposit 1000, then recover: the headline percent
        # must appear in the worst-drawdowns table (equity semantics).
        s = Session("1000.00")
        s.record_bet("g", {}, "500.00", 0, ts(0))
        assert s.summary()["max_drawdown_pct"] == "50.00%"
        s.deposit("1000.00", ts(1))
        s.record_bet("g", {}, "500.00", 3, ts(2))   # equity 500 -> 1500, recovers
        summ = s.summary()
        assert summ["max_drawdown_pct"] == "50.00%"
        assert "50.00%" in [e["drawdown_pct"] for e in summ["drawdown"]["worst"]]

    def test_peak_stays_positive_after_overdraw_withdrawal(self):
        s = Session("100.00", allow_negative_bankroll=True)
        s.withdraw("500.00", ts(0))                 # bankroll -400, equity 100
        assert s.peak_bankroll == Decimal("100.00") # never <= 0
        s.record_bet("g", {}, "100.00", 0, ts(1))   # equity 100 -> 0
        assert s.max_drawdown == Decimal("100.00")
        assert s.max_drawdown_pct == Fraction(1)    # 100%, not a silent 0%

    def test_cash_records_share_the_event_journal(self):
        s = Session("1000.00")
        s.record_bet("g", {}, "100.00", 0, ts(0))
        s.deposit("50.00", ts(0))                   # duplicate timestamp
        s.record_bet("g", {}, "100.00", 0, ts(0))
        s.withdraw("50.00", ts(0))
        assert [b.seq for b in s.bets] == [1, 3]
        assert [c.seq for c in s.cash_flows] == [2, 4]
        assert [e.seq for e in s.events] == [1, 2, 3, 4]  # order recoverable

    def test_cash_persists_and_reloads(self, tmp_path):
        path = tmp_path / "cash.jsonl"
        s = Session("100.00", jsonl_path=path)
        s.record_bet("g", {}, "20.00", 0, ts(0))
        s.deposit("40.00", ts(1))
        s.record_bet("g", {}, "10.00", 2, ts(2))
        s.withdraw("15.00", ts(3))
        types = [json.loads(l)["type"] for l in path.read_text().splitlines()]
        assert types == ["session_start", "bet", "cash", "bet", "cash"]
        s2 = Session.load(path)
        assert s2.bankroll == s.bankroll == Decimal("115.00")
        assert s2.pnl == s.pnl == Decimal("-10.00")
        assert s2.total_deposited == Decimal("40.00")
        assert s2.total_withdrawn == Decimal("15.00")
        assert s2.summary() == s.summary()


# ---------------------------------------------------------------------------
# per-game breakdown + summary
# ---------------------------------------------------------------------------

class TestBreakdownAndSummary:
    def _played(self) -> Session:
        s = Session("500.00", stop_loss="250.00", stop_win_pct="0.5")
        s.record_bet("blackjack", {"decks": 8}, "25.00", "2", ts(0))
        s.record_bet("blackjack", {"decks": 8}, "25.00", "0", ts(1))
        s.record_bet("blackjack", {"decks": 8}, "25.00", "1", ts(2))
        s.record_bet("keno", {"spots": 5}, "1.00", "10", ts(3))
        s.record_bet("keno", {"spots": 5}, "1.00", "0", ts(4))
        return s

    def test_per_game_breakdown(self):
        s = self._played()
        bd = s.per_game_breakdown()
        assert set(bd) == {"blackjack", "keno"}
        bj = bd["blackjack"]
        assert bj == {
            "bets": 3, "wins": 1, "pushes": 1, "losses": 1,
            "total_staked": "75.00", "total_returned": "75.00", "net": "0.00",
        }
        kn = bd["keno"]
        assert kn["bets"] == 2 and kn["net"] == "8.00"
        assert kn["total_staked"] == "2.00" and kn["total_returned"] == "10.00"

    def test_summary_contents_and_json_round_trip(self):
        s = self._played()
        summ = s.summary()
        # JSON-serializable end to end
        assert json.loads(json.dumps(summ)) == summ
        assert summ["starting_bankroll"] == "500.00"
        assert summ["bankroll"] == "508.00"
        assert summ["pnl"] == "8.00"
        assert summ["total_bets"] == 5
        assert summ["total_staked"] == "77.00"
        assert summ["total_returned"] == "85.00"
        assert summ["peak_bankroll"] == "525.00"
        assert summ["max_drawdown"] == "25.00"        # 525 -> 500
        assert summ["max_drawdown_pct"] == "4.76%"    # 25/525, half-up
        assert summ["first_bet_at"] == ts(0)
        assert summ["last_bet_at"] == ts(4)
        assert summ["stopped"] is False
        assert summ["stops"]["stop_loss"] == "250.00"
        assert summ["stops"]["stop_win_pct"] == "0.5"
        assert summ["stops"]["stop_win"] is None
        assert summ["per_game"] == s.per_game_breakdown()

    def test_empty_session_summary(self):
        s = Session(100)
        summ = s.summary()
        assert summ["total_bets"] == 0
        assert summ["first_bet_at"] is None and summ["last_bet_at"] is None
        assert summ["pnl"] == "0.00"
        assert summ["max_drawdown_pct"] == "0.00%"
        assert summ["per_game"] == {}
        assert summ["drawdown"]["worst"] == []
        json.dumps(summ)


# ---------------------------------------------------------------------------
# JSONL persistence
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_file_layout(self, tmp_path):
        path = tmp_path / "sess.jsonl"
        s = Session("100.00", stop_loss="40.00", jsonl_path=path)
        s.record_bet("wheel", {"risk": "low", "segments": 10}, "5.00", "1.5", ts(0))
        s.record_bet("wheel", {"risk": "low", "segments": 10}, "5.00", "0", ts(1))
        lines = [json.loads(l) for l in path.read_text().splitlines()]
        assert [l["type"] for l in lines] == ["session_start", "bet", "bet"]
        assert lines[0]["starting_bankroll"] == "100.00"
        assert lines[0]["stop_loss"] == "40.00"
        assert lines[1]["seq"] == 1 and lines[1]["stake"] == "5.00"
        assert lines[1]["payout"] == "7.50" and lines[1]["bankroll_after"] == "102.50"
        assert lines[1]["session_id"] == s.session_id
        assert lines[2]["bankroll_after"] == "97.50"

    def test_reload_restores_identical_state(self, tmp_path):
        path = tmp_path / "sess.jsonl"
        s = Session("100.00", stop_loss=30, stop_win_pct="0.5", jsonl_path=path)
        s.record_bet("blackjack", {"decks": 8}, "10.00", "2.5", ts(0))
        s.record_bet("keno", {"spots": 3}, "2.00", "0", ts(1))
        s.record_bet("blackjack", {"decks": 8}, "40.00", "0", ts(2))  # pnl -27

        s2 = Session.load(path)
        assert s2.session_id == s.session_id
        assert s2.bankroll == s.bankroll == Decimal("73.00")
        assert s2.pnl == Decimal("-27.00")
        assert s2.peak_bankroll == s.peak_bankroll == Decimal("115.00")
        assert s2.max_drawdown == s.max_drawdown == Decimal("42.00")
        assert s2.max_drawdown_pct == s.max_drawdown_pct == Fraction(42, 115)
        assert s2.stopped == s.stopped is False
        assert s2.summary() == s.summary()
        assert len(s2.bets) == 3 and s2.bets == s.bets

    def test_reload_then_append_continues_same_file(self, tmp_path):
        path = tmp_path / "sess.jsonl"
        s = Session("100.00", stop_loss="50.00", jsonl_path=path)
        s.record_bet("g", {}, "20.00", 0, ts(0))
        del s

        s2 = Session.load(path)
        assert s2.bankroll == Decimal("80.00")
        s2.record_bet("g", {}, "30.00", 0, ts(1))      # pnl -50 -> stop latches
        assert s2.stopped and s2.stop_reason == "stop_loss" and s2.stop_seq == 2

        # no duplicated header; the resumed writer announces itself, then
        # both bets + the stop journal are on disk
        lines = [json.loads(l) for l in path.read_text().splitlines()]
        assert [l["type"] for l in lines] == [
            "session_start", "bet", "resume", "bet", "stop"]
        s3 = Session.load(path)
        assert s3.summary() == s2.summary()

    def test_reload_replays_stop_latch(self, tmp_path):
        path = tmp_path / "sess.jsonl"
        s = Session(100, stop_win=10, jsonl_path=path)
        s.record_bet("g", {}, 10, 2, ts(0))            # +10 -> latch
        assert s.stopped
        s2 = Session.load(path)
        assert s2.stopped and s2.stop_reason == "stop_win" and s2.stop_seq == 1

    def test_stop_latch_is_journalled(self, tmp_path):
        path = tmp_path / "sess.jsonl"
        s = Session(100, stop_loss=20, jsonl_path=path)
        s.record_bet("g", {}, 20, 0, ts(0))
        lines = [json.loads(l) for l in path.read_text().splitlines()]
        stop = lines[-1]
        assert stop == {
            "type": "stop", "session_id": s.session_id, "writer": s._writer,
            "reason": "stop_loss", "seq": 1, "timestamp": ts(0),
            "pnl": "-20.00", "bankroll": "80.00",
        }

    def test_header_stop_tamper_detected(self, tmp_path):
        # Loosening stop_loss in the header after a latch must not silently
        # un-stop the session: the journalled latch no longer matches the
        # replayed one, and load raises.
        path = tmp_path / "sess.jsonl"
        s = Session(100, stop_loss=20, jsonl_path=path)
        s.record_bet("g", {}, 20, 0, ts(0))
        assert s.stopped
        s.close()
        text = path.read_text().replace('"stop_loss":"20.00"', '"stop_loss":"90.00"')
        path.write_text(text)
        with pytest.raises(ValueError, match="stop record"):
            Session.load(path)

    def test_missing_stop_journal_is_healed_on_load(self, tmp_path):
        path = tmp_path / "sess.jsonl"
        s = Session(100, stop_loss=20, jsonl_path=path)
        s.record_bet("g", {}, 20, 0, ts(0))
        s.close()
        # simulate a crash that lost the stop line
        lines = path.read_text().splitlines()
        assert json.loads(lines[-1])["type"] == "stop"
        path.write_text("\n".join(lines[:-1]) + "\n")
        s2 = Session.load(path)
        assert s2.stopped and s2.stop_reason == "stop_loss"
        assert json.loads(path.read_text().splitlines()[-1])["type"] == "stop"
        Session.load(path)  # and the healed file loads cleanly again

    def test_torn_final_line_is_ignored(self, tmp_path):
        path = tmp_path / "sess.jsonl"
        s = Session(100, jsonl_path=path)
        s.record_bet("g", {}, 10, 2, ts(0))
        with open(path, "a", encoding="utf-8") as fh:
            fh.write('{"type": "bet", "seq": 2, "ga')   # crash mid-append
        s2 = Session.load(path)
        assert len(s2.bets) == 1 and s2.bankroll == Decimal("110.00")

    def test_torn_tail_resume_never_loses_a_bet(self, tmp_path):
        # The round-1 blocker: resume after a torn tail, keep playing, and
        # every committed bet must survive every subsequent reload.
        path = tmp_path / "torn.jsonl"
        s = Session(100, jsonl_path=path)
        s.record_bet("g", {}, 10, 2, ts(0))
        s.close()
        with open(path, "ab") as fh:
            fh.write(b'{"type":"bet","seq":2,"ga')      # crash mid-append
        s2 = Session.load(path)                          # truncates the torn tail
        assert len(s2.bets) == 1 and s2.bankroll == Decimal("110.00")
        s2.record_bet("g", {}, 10, 2, ts(1))             # keep playing
        # every line on disk is clean JSON now
        for line in path.read_text().splitlines():
            json.loads(line)
        s3 = Session.load(path)
        assert len(s3.bets) == 2 and s3.bankroll == Decimal("120.00")
        s3.record_bet("g", {}, 10, 2, ts(2))
        s4 = Session.load(path)
        assert len(s4.bets) == 3 and s4.bankroll == Decimal("130.00")

    def test_torn_tail_with_trailing_blank_line(self, tmp_path):
        path = tmp_path / "torn2.jsonl"
        s = Session(100, jsonl_path=path)
        s.record_bet("g", {}, 10, 2, ts(0))
        s.close()
        with open(path, "ab") as fh:
            fh.write(b'{"type":"bet","seq":2,"ga\n\n')  # torn + stray newlines
        s2 = Session.load(path)
        assert len(s2.bets) == 1 and s2.bankroll == Decimal("110.00")
        s2.record_bet("g", {}, 10, 2, ts(1))
        s3 = Session.load(path)
        assert len(s3.bets) == 2 and s3.bankroll == Decimal("120.00")

    def test_corruption_in_middle_raises(self, tmp_path):
        path = tmp_path / "sess.jsonl"
        s = Session(100, jsonl_path=path)
        s.record_bet("g", {}, 10, 2, ts(0))
        s.record_bet("g", {}, 10, 0, ts(1))
        s.close()
        lines = path.read_text().splitlines()
        lines[1] = "not json at all"
        path.write_text("\n".join(lines) + "\n")
        with pytest.raises(ValueError):
            Session.load(path)

    def test_tampered_fields_all_detected(self, tmp_path):
        # bankroll_after, payout, net and seq are each verified on replay.
        cases = [
            ('"bankroll_after":"110.00"', '"bankroll_after":"999.00"'),
            ('"payout":"20.00"', '"payout":"777.00"'),
            ('"net":"10.00"', '"net":"777.00"'),
            ('"seq":1,', '"seq":42,'),
        ]
        for i, (src, dst) in enumerate(cases):
            path = tmp_path / f"t{i}.jsonl"
            s = Session(100, jsonl_path=path)
            s.record_bet("g", {}, 10, 2, ts(0))
            s.close()
            text = path.read_text()
            assert src in text, src
            path.write_text(text.replace(src, dst, 1))
            with pytest.raises(ValueError, match="replay mismatch"):
                Session.load(path)

    def test_config_serialization_failure_mutates_nothing(self, tmp_path):
        # Config validation uses the exact persistence serializer: anything
        # unpersistable is rejected before any state (memory OR disk) changes,
        # and mixed-type keys are canonicalized instead of exploding at write
        # time after the bankroll already moved.
        path = tmp_path / "sess.jsonl"
        s = Session(100, jsonl_path=path)
        s.record_bet("g", {}, 10, 0, ts(0))
        with pytest.raises(ValueError, match="JSON-serializable"):
            s.record_bet("g", {"bad": object()}, 10, 0, ts(1))
        with pytest.raises(ValueError, match="JSON-serializable"):
            s.record_bet("g", {"nan": float("nan")}, 10, 0, ts(1))
        with pytest.raises(ValueError, match="JSON-serializable"):
            s.record_bet("g", {1: "a", "b": object()}, 10, 0, ts(1))
        assert len(s.bets) == 1 and s.bankroll == Decimal("90.00")
        lines = [json.loads(l) for l in path.read_text().splitlines()]
        assert [l["type"] for l in lines] == ["session_start", "bet"]
        assert "NaN" not in path.read_text()
        # a mixed-key config that IS serializable records cleanly end to end
        r = s.record_bet("g", {1: "a", "b": 2}, 10, 0, ts(2))
        assert r.config == {"1": "a", "b": 2}
        s2 = Session.load(path)          # memory and disk still agree
        assert s2.summary() == s.summary()

    def test_config_round_trips_identically(self, tmp_path):
        path = tmp_path / "cfg.jsonl"
        s = Session(100, jsonl_path=path)
        s.record_bet("g", {1: "int key", "t": (1, 2)}, 1, 0, ts(0))
        s.record_bet("g", {"nested": {"a": [1, {"b": 2}]}, "u": "é中文🎰"}, 1, 0, ts(1))
        s2 = Session.load(path)
        assert s2.bets == s.bets
        assert s2.bets[0].config == {"1": "int key", "t": [1, 2]}

    def test_tampered_bankroll_detected(self, tmp_path):
        path = tmp_path / "sess.jsonl"
        s = Session(100, jsonl_path=path)
        s.record_bet("g", {}, 10, 2, ts(0))
        s.close()
        text = path.read_text().replace('"bankroll_after":"110.00"',
                                        '"bankroll_after":"999.00"')
        assert '"999.00"' in text
        path.write_text(text)
        with pytest.raises(ValueError, match="replay mismatch"):
            Session.load(path)

    def test_multiple_headers_last_session_wins(self, tmp_path):
        path = tmp_path / "sess.jsonl"
        s1 = Session(100, jsonl_path=path)
        s1.record_bet("g", {}, 10, 0, ts(0))
        s2 = Session(250, jsonl_path=path)             # new session, same file
        s2.record_bet("g", {}, 50, 2, ts(1))
        loaded = Session.load(path)
        assert loaded.session_id == s2.session_id
        assert loaded.starting_bankroll == Decimal("250.00")
        assert loaded.bankroll == Decimal("300.00")
        assert len(loaded.bets) == 1

    def test_interleaved_sessions_do_not_brick_the_file(self, tmp_path):
        # Two live sessions appending to one file: load() follows the last
        # header and skips records tagged with the other session's id.
        path = tmp_path / "sess.jsonl"
        s1 = Session(100, jsonl_path=path)
        s1.record_bet("g", {}, 10, 0, ts(0))
        s2 = Session(250, jsonl_path=path)
        s2.record_bet("g", {}, 50, 2, ts(1))
        s1.record_bet("g", {}, 10, 0, ts(2))           # s1 keeps playing (seq 2)
        s2.record_bet("g", {}, 50, 0, ts(3))
        loaded = Session.load(path)
        assert loaded.session_id == s2.session_id
        assert len(loaded.bets) == 2
        assert loaded.bankroll == s2.bankroll == Decimal("250.00")

    def test_load_leaves_file_byte_identical(self, tmp_path):
        path = tmp_path / "sess.jsonl"
        s = Session(100, jsonl_path=path)
        s.record_bet("g", {}, 10, 2, ts(0))
        s.deposit(5, ts(1))
        s.close()
        before = path.read_bytes()
        Session.load(path).close()          # a bare load writes nothing
        assert path.read_bytes() == before
        loaded = Session.load(path)
        loaded.record_bet("g", {}, 5, 0, ts(2))
        loaded.close()
        after = path.read_bytes()
        assert after.startswith(before)     # append is a pure suffix
        types = [json.loads(l)["type"] for l in after.decode().splitlines()]
        assert types == ["session_start", "bet", "cash", "resume", "bet"]
        again = Session.load(path)
        assert again.summary() == loaded.summary()
        assert len(again.bets) == 2 and again.bankroll == Decimal("110.00")

    def test_stale_writer_after_resume_is_skipped_not_bricked(self, tmp_path):
        # Round-2 §4.2: two live handles with the same session_id used to
        # brick the file permanently.  Now the last resumer wins: the stale
        # handle's later records are skipped deterministically on load.
        path = tmp_path / "sess.jsonl"
        a = Session(100, jsonl_path=path)
        a.record_bet("g", {}, 10, 0, ts(0))
        b = Session.load(path)              # a is still open
        b.record_bet("g", {}, 10, 0, ts(1))
        a.record_bet("g", {}, 10, 2, ts(2))  # stale handle keeps writing
        a.close()
        b.close()
        loaded = Session.load(path)
        assert len(loaded.bets) == 2                    # a's post-resume bet dropped
        assert loaded.bankroll == Decimal("80.00")      # 100 - 10 - 10
        assert loaded.stale_records_skipped == 1
        # ...and the healed chain keeps loading cleanly
        loaded.record_bet("g", {}, 10, 2, ts(3))
        loaded.close()
        final = Session.load(path)
        assert final.bankroll == Decimal("90.00") and len(final.bets) == 3

    def test_diverged_resumed_writers_rejected(self, tmp_path):
        # Two sessions both resumed from the same point and both wrote:
        # their histories diverged and cannot be merged — load must say so.
        path = tmp_path / "sess.jsonl"
        s = Session(100, jsonl_path=path)
        s.record_bet("g", {}, 10, 0, ts(0))
        s.close()
        x = Session.load(path)
        y = Session.load(path)
        x.record_bet("g", {}, 10, 0, ts(1))
        y.record_bet("g", {}, 10, 2, ts(1))
        x.close()
        y.close()
        with pytest.raises(ValueError, match="diverged"):
            Session.load(path)

    def test_load_missing_header_raises(self, tmp_path):
        path = tmp_path / "bad.jsonl"
        path.write_text('{"type":"bet","seq":1}\n')
        with pytest.raises(ValueError, match="session_start"):
            Session.load(path)

    def test_context_manager_closes_handle(self, tmp_path):
        path = tmp_path / "sess.jsonl"
        with Session(100, jsonl_path=path) as s:
            s.record_bet("g", {}, 10, 2, ts(0))
        assert s._fh is None
        s.record_bet("g", {}, 10, 0, ts(1))    # reopens on demand
        assert Session.load(path).bankroll == Decimal("100.00")


# ---------------------------------------------------------------------------
# DataFrame export
# ---------------------------------------------------------------------------

class TestDataFrame:
    def test_dataframe_contents(self):
        s = Session("100.00")
        s.record_bet("blackjack", {"decks": 8}, "10.00", "2.5", ts(0))
        s.record_bet("keno", {"spots": 5}, "1.00", "0", ts(1))
        df = s.to_dataframe()
        assert isinstance(df, pd.DataFrame)
        assert list(df.columns) == [
            "seq", "type", "timestamp", "game", "kind", "config_json",
            "stake", "multiplier", "payout", "net", "bankroll_after",
        ]
        assert len(df) == 2
        assert df["seq"].tolist() == [1, 2]
        assert df["type"].tolist() == ["bet", "bet"]
        assert df["game"].tolist() == ["blackjack", "keno"]
        assert json.loads(df["config_json"].iloc[0]) == {"decks": 8}
        assert df["payout"].tolist() == [25.0, 0.0]
        assert df["bankroll_after"].tolist() == [115.0, 114.0]
        assert df["stake"].dtype == "float64" and df["seq"].dtype == "int64"

    def test_dataframe_foots_across_cash_flows(self):
        # The accountant's test: bankroll_after[i] == bankroll_after[i-1] +
        # net[i] on every row, cash movements included.
        s = Session("1000.00")
        s.record_bet("g", {}, "100.00", 0, ts(0))
        s.record_bet("g", {}, "100.00", 0, ts(1))
        s.deposit("500.00", ts(2))
        s.record_bet("g", {}, "100.00", 0, ts(3))
        s.withdraw("200.00", ts(4))
        s.record_bet("g", {}, "100.00", 2, ts(5))
        df = s.to_dataframe()
        assert len(df) == 6
        assert df["type"].tolist() == ["bet", "bet", "cash", "bet", "cash", "bet"]
        assert df["kind"].tolist()[2] == "deposit" and df["kind"].tolist()[4] == "withdrawal"
        prev = float(s.starting_bankroll)
        for _, row in df.iterrows():
            assert row["bankroll_after"] == pytest.approx(prev + row["net"])
            prev = row["bankroll_after"]
        # bets-only view still available
        bets_only = s.to_dataframe(include_cash=False)
        assert bets_only["type"].tolist() == ["bet"] * 4
        assert bets_only["net"].sum() == pytest.approx(float(s.pnl))

    def test_empty_dataframe_schema(self):
        df = Session(100).to_dataframe()
        assert len(df) == 0
        assert df["stake"].dtype == "float64"
        assert df["seq"].dtype == "int64"

    def test_dataframe_matches_ledger_totals(self):
        s = Session("1000.00")
        for i in range(200):
            s.record_bet("slots", {"n": i % 3}, "0.30", str(i % 5), ts(i % 60))
        df = s.to_dataframe()
        # float sums agree with the exact Decimal ledger to within rounding
        assert abs(df["net"].sum() - float(s.pnl)) < 1e-6
        assert df["bankroll_after"].iloc[-1] == pytest.approx(float(s.bankroll))
