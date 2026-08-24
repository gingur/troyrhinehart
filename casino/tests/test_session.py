"""Tests for spinquest_sim.session — hand-play session tracking.

Covers: bet recording, Decimal-exact money (no float cents drift), bankroll /
P&L / peak / max drawdown, absolute + percent stop-loss/stop-win latching,
per-game breakdown, JSON-serializable summary, append-safe / reload-safe JSONL
persistence, and the pandas DataFrame export.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

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
        assert s.max_drawdown_pct == Decimal("40") / Decimal("120")
        assert s.bankroll == Decimal("110.00")

    def test_no_drawdown_when_only_winning(self):
        s = Session(100)
        s.record_bet("g", {}, 10, 2, ts(0))
        s.record_bet("g", {}, 10, 2, ts(1))
        assert s.max_drawdown == Decimal("0.00")
        assert s.max_drawdown_pct == 0
        assert s.peak_bankroll == Decimal("120.00")


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
        assert summ["per_game"] == {}
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
        assert lines[2]["bankroll_after"] == "97.50"

    def test_reload_restores_identical_state(self, tmp_path):
        path = tmp_path / "sess.jsonl"
        s = Session("100.00", stop_loss=30, stop_win_pct="0.5", jsonl_path=path)
        s.record_bet("blackjack", {"decks": 8}, "10.00", "2.5", ts(0))
        s.record_bet("keno", {"spots": 3}, "2.00", "0", ts(1))
        s.record_bet("blackjack", {"decks": 8}, "40.00", "0", ts(2))  # pnl -29

        s2 = Session.load(path)
        assert s2.session_id == s.session_id
        assert s2.bankroll == s.bankroll == Decimal("73.00")
        assert s2.pnl == Decimal("-27.00")
        assert s2.peak_bankroll == s.peak_bankroll == Decimal("115.00")
        assert s2.max_drawdown == s.max_drawdown == Decimal("42.00")
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

        # no duplicated header, both bets on disk, and a third load agrees
        lines = [json.loads(l) for l in path.read_text().splitlines()]
        assert [l["type"] for l in lines] == ["session_start", "bet", "bet"]
        s3 = Session.load(path)
        assert s3.summary() == s2.summary()

    def test_reload_replays_stop_latch(self, tmp_path):
        path = tmp_path / "sess.jsonl"
        s = Session(100, stop_win=10, jsonl_path=path)
        s.record_bet("g", {}, 10, 2, ts(0))            # +10 -> latch
        assert s.stopped
        s2 = Session.load(path)
        assert s2.stopped and s2.stop_reason == "stop_win" and s2.stop_seq == 1

    def test_torn_final_line_is_ignored(self, tmp_path):
        path = tmp_path / "sess.jsonl"
        s = Session(100, jsonl_path=path)
        s.record_bet("g", {}, 10, 2, ts(0))
        with open(path, "a", encoding="utf-8") as fh:
            fh.write('{"type": "bet", "seq": 2, "ga')   # crash mid-append
        s2 = Session.load(path)
        assert len(s2.bets) == 1 and s2.bankroll == Decimal("110.00")

    def test_corruption_in_middle_raises(self, tmp_path):
        path = tmp_path / "sess.jsonl"
        s = Session(100, jsonl_path=path)
        s.record_bet("g", {}, 10, 2, ts(0))
        s.record_bet("g", {}, 10, 0, ts(1))
        lines = path.read_text().splitlines()
        lines[1] = "not json at all"
        path.write_text("\n".join(lines) + "\n")
        with pytest.raises(ValueError):
            Session.load(path)

    def test_tampered_bankroll_detected(self, tmp_path):
        path = tmp_path / "sess.jsonl"
        s = Session(100, jsonl_path=path)
        s.record_bet("g", {}, 10, 2, ts(0))
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

    def test_load_missing_header_raises(self, tmp_path):
        path = tmp_path / "bad.jsonl"
        path.write_text('{"type":"bet","seq":1}\n')
        with pytest.raises(ValueError, match="session_start"):
            Session.load(path)


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
            "seq", "timestamp", "game", "config_json",
            "stake", "multiplier", "payout", "net", "bankroll_after",
        ]
        assert len(df) == 2
        assert df["seq"].tolist() == [1, 2]
        assert df["game"].tolist() == ["blackjack", "keno"]
        assert json.loads(df["config_json"].iloc[0]) == {"decks": 8}
        assert df["payout"].tolist() == [25.0, 0.0]
        assert df["bankroll_after"].tolist() == [115.0, 114.0]
        assert df["stake"].dtype == "float64" and df["seq"].dtype == "int64"

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
