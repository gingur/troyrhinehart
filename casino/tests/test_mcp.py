"""Tests for mcp_server.server — every tool driven through an in-process
MCP client (the official SDK's memory transport: a real client session
speaking the protocol to the real FastMCP server object, no subprocess).

Costs: the first ``list_games`` call builds the selector's analytic table
(~30-40 s, two video-poker solves + the exact Atkins enumeration) and the
first video_poker tool call solves its paytable (~15 s).  Both are cached
process-wide, so the rest of the file is cheap.
"""

import json
import math
import os
from fractions import Fraction
from pathlib import Path

import anyio
import pytest

from mcp.shared.memory import create_connected_server_and_client_session

from mcp_server import server as srv
from spinquest_sim import rng as sq_rng


# ---------------------------------------------------------------------------
# harness
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True, scope="module")
def sq_home(tmp_path_factory):
    """Point $SPINQUEST_HOME at a temp dir for the whole module (the server
    reads it at call time), and start from an empty session registry."""
    home = tmp_path_factory.mktemp("spinquest_home")
    old = os.environ.get("SPINQUEST_HOME")
    os.environ["SPINQUEST_HOME"] = str(home)
    srv._SESSIONS.clear()
    yield home
    if old is None:
        os.environ.pop("SPINQUEST_HOME", None)
    else:
        os.environ["SPINQUEST_HOME"] = old


def run(async_fn):
    """Run ``async_fn(client)`` against an in-process client session."""
    async def main():
        async with create_connected_server_and_client_session(srv.mcp) as client:
            return await async_fn(client)
    return anyio.run(main)


def payload(result):
    """Unwrap a successful CallToolResult into the tool's dict payload."""
    assert not result.isError, f"tool error: {result.content}"
    if result.structuredContent is not None:
        sc = result.structuredContent
        return sc.get("result", sc)
    return json.loads(result.content[0].text)


def error_text(result):
    assert result.isError, "expected a tool error"
    return result.content[0].text


async def call(client, name, args=None):
    return payload(await client.call_tool(name, args or {}))


async def call_err(client, name, args=None):
    return error_text(await client.call_tool(name, args or {}))


ALL_TOOLS = {
    "list_games", "game_odds", "simulate", "optimal_sizing",
    "session_start", "session_record_bet", "session_status", "session_end",
    "strategy_report", "verify_bet",
}


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------

def test_all_tools_registered():
    async def go(client):
        listed = await client.list_tools()
        names = {t.name for t in listed.tools}
        assert names == ALL_TOOLS
        for t in listed.tools:
            assert t.description, f"{t.name} has no description"
    run(go)


# ---------------------------------------------------------------------------
# game_odds
# ---------------------------------------------------------------------------

def test_game_odds_exact_figures():
    async def go(client):
        red = await call(client, "game_odds",
                         {"game": "roulette", "config": {"bet_type": "red"}})
        assert math.isclose(red["rtp"], 36 / 37, rel_tol=0, abs_tol=1e-12)
        assert math.isclose(red["house_edge"], 1 / 37, abs_tol=1e-12)
        assert red["config"]["bet_type"] == "red"
        assert red["std_per_unit"] > 0

        wheel = await call(client, "game_odds",
                           {"game": "wheel",
                            "config": {"segments": 10, "risk": "low"}})
        assert math.isclose(wheel["rtp"], 0.99, abs_tol=1e-12)

        # engine config() output round-trips as a config
        again = await call(client, "game_odds",
                           {"game": "roulette", "config": red["config"]})
        assert again["rtp"] == red["rtp"]
    run(go)


def test_game_odds_errors_are_mcp_errors():
    async def go(client):
        msg = await call_err(client, "game_odds", {"game": "hyperdice"})
        assert "unknown game" in msg
        msg = await call_err(client, "game_odds",
                             {"game": "keno", "config": {"picks": 99}})
        assert "picks" in msg
        msg = await call_err(client, "game_odds", {"game": "roulette"})
        assert "bet_type" in msg
        # config/game mismatch is refused, not silently reinterpreted
        msg = await call_err(client, "game_odds",
                             {"game": "keno",
                              "config": {"game": "wheel", "picks": 3}})
        assert "wheel" in msg and "keno" in msg
    run(go)


# ---------------------------------------------------------------------------
# list_games (selector-ranked; the expensive analytic build happens here)
# ---------------------------------------------------------------------------

def test_list_games_ranked_by_rtp():
    async def go(client):
        out = await call(client, "list_games")
        assert out["count"] == 412        # the selector's full config grid
        rows = out["games"]
        assert len(rows) == 412
        games = {r["game"] for r in rows}
        assert games == {"plinko", "mines", "keno", "wheel", "blackjack",
                         "baccarat", "roulette", "video_poker", "crash",
                         "slots"}
        rtps = [r["rtp"] for r in rows]
        assert rtps == sorted(rtps, reverse=True)
        assert [r["rank"] for r in rows[:3]] == [1, 2, 3]
        # full-pay 9/6 Jacks or Better tops the board (99.54%)
        assert rows[0]["game"] == "video_poker"
        assert math.isclose(rows[0]["rtp"], 0.99543904, abs_tol=5e-7)
        for r in rows:
            assert 0.0 <= r["survival_prob"] <= 1.0
            assert math.isclose(r["house_edge"], 1 - r["rtp"], abs_tol=1e-12)
        assert "surviving 200 flat bets" in out["survival_metric"]

        top = await call(client, "list_games", {"top": 5})
        assert top["shown"] == 5 and top["count"] == 412
        assert top["games"] == rows[:5]
    run(go)


# ---------------------------------------------------------------------------
# simulate
# ---------------------------------------------------------------------------

def test_simulate_deterministic_and_verifiable():
    async def go(client):
        args = {"game": "roulette", "n_rounds": 20_000,
                "config": {"bet_type": "red"}, "seed": 42}
        a = await call(client, "simulate", args)
        b = await call(client, "simulate", args)
        assert a["rtp"] == b["rtp"]
        assert a["rng"]["server_seed"] == b["rng"]["server_seed"]
        assert a["n_rounds"] == 20_000
        assert abs(a["z_score"]) < 6.0
        assert math.isclose(a["analytic_rtp"], 36 / 37, abs_tol=1e-12)
        # the disclosed seed commitment is the sha256 of the server seed
        assert (sq_rng.hash_server_seed(a["rng"]["server_seed"])
                == a["rng"]["server_seed_hash"])

        # a row of the campaign is verifiable through verify_bet
        row = await call(client, "verify_bet", {
            "game": "roulette",
            "server_seed": a["rng"]["server_seed"],
            "client_seed": a["rng"]["client_seed"],
            "nonce": 0,
            "config": {"bet_type": "red"},
        })
        assert row["server_seed_hash"] == a["rng"]["server_seed_hash"]
    run(go)


def test_simulate_round_cap_and_validation():
    async def go(client):
        msg = await call_err(client, "simulate",
                             {"game": "roulette", "n_rounds": 10_000_001,
                              "config": {"bet_type": "red"}})
        assert "10,000,000" in msg
        msg = await call_err(client, "simulate",
                             {"game": "roulette", "n_rounds": 0,
                              "config": {"bet_type": "red"}})
        assert "n_rounds" in msg
    run(go)


def test_simulate_multi_float_game():
    async def go(client):
        out = await call(client, "simulate",
                         {"game": "keno", "n_rounds": 10_000,
                          "config": {"picks": 3, "risk": "classic"},
                          "seed": "keno-test"})
        assert out["n_rounds"] == 10_000
        assert sum(out["hit_histogram"]) == 10_000
        assert 0.5 < out["rtp"] < 1.5
    run(go)


# ---------------------------------------------------------------------------
# optimal_sizing
# ---------------------------------------------------------------------------

def test_optimal_sizing_reach_target_bold():
    async def go(client):
        out = await call(client, "optimal_sizing", {
            "bankroll": 100.0, "game": "roulette", "goal": "reach_target",
            "config": {"bet_type": "red"}, "target": 150.0,
            "bet_grid": [1.0, 5.0, 25.0],
        })
        assert out["regime"] == "bold"
        # even-money win (m=2): bold stake = target - bankroll = 50
        assert math.isclose(out["recommended_bet"], 50.0, abs_tol=1e-9)
        assert out["house_edge"] > 0 and out["ev_per_unit_staked"] < 0
        assert out["kelly_fraction"] == 0.0
        table = out["flat_bet_table"]
        assert [r["bet"] for r in table] == [1.0, 5.0, 25.0]
        # even-money: P(reach) increases with flat bet size
        p = [r["p_reach_target"] for r in table]
        assert p == sorted(p)
        assert out["config"]["bet_type"] == "red"
    run(go)


def test_optimal_sizing_survive_rounds_timid():
    async def go(client):
        out = await call(client, "optimal_sizing", {
            "bankroll": 100.0, "game": "wheel", "goal": "survive_rounds",
            "config": {"segments": 10, "risk": "low"}, "n_rounds": 50,
            "bet_grid": [1.0, 10.0, 50.0],
        })
        assert out["regime"] == "timid"
        assert out["recommended_bet"] == 1.0
        p = [r["p_survive"] for r in out["flat_bet_table"]]
        assert p == sorted(p, reverse=True)   # survival nonincreasing in bet
    run(go)


def test_optimal_sizing_honest_refusals():
    async def go(client):
        msg = await call_err(client, "optimal_sizing", {
            "bankroll": 100.0, "game": "blackjack",
            "goal": "survive_rounds", "n_rounds": 10,
        })
        assert "blackjack" in msg
        msg = await call_err(client, "optimal_sizing", {
            "bankroll": 100.0, "game": "slots",
            "goal": "survive_rounds", "n_rounds": 10,
        })
        assert "slots" in msg
        msg = await call_err(client, "optimal_sizing", {
            "bankroll": 100.0, "game": "roulette",
            "config": {"bet_type": "red"}, "goal": "get_rich",
        })
        assert "goal" in msg
    run(go)


# ---------------------------------------------------------------------------
# sessions + strategy report
# ---------------------------------------------------------------------------

def test_session_lifecycle_and_report(sq_home):
    async def go(client):
        start = await call(client, "session_start",
                           {"starting_bankroll": 200.0, "stop_loss": 30.0})
        sid = start["session_id"]
        assert start["bankroll"] == "200.00"
        assert Path(start["jsonl_path"]).exists()
        assert str(sq_home) in start["jsonl_path"]

        rl_cfg = {"game": "roulette", "bet_type": "red"}
        b1 = await call(client, "session_record_bet", {
            "session_id": sid, "game": "roulette", "stake": 10.0,
            "multiplier": 2.0, "config": rl_cfg,
            "timestamp": "2026-08-24T10:00:00+00:00",
        })
        assert b1["bankroll"] == "210.00" and b1["pnl"] == "10.00"
        assert not b1["stopped"]

        b2 = await call(client, "session_record_bet", {
            "session_id": sid, "game": "roulette", "stake": 25.0,
            "multiplier": 0.0, "config": rl_cfg,
            "timestamp": "2026-08-24T10:01:00+00:00",
        })
        assert b2["bankroll"] == "185.00" and b2["pnl"] == "-15.00"

        b3 = await call(client, "session_record_bet", {
            "session_id": sid, "game": "roulette", "stake": 20.0,
            "multiplier": 0.0, "config": rl_cfg,
            "timestamp": "2026-08-24T10:02:00+00:00",
        })
        # cumulative P&L -35 crosses the 30 stop-loss: advisory latch
        assert b3["stopped"] and b3["stop_reason"] == "stop_loss"
        assert b3["stop_seq"] == 3

        status = await call(client, "session_status", {"session_id": sid})
        assert status["total_bets"] == 3
        assert status["bankroll"] == "165.00"
        assert status["pnl"] == "-35.00"
        assert status["per_game"]["roulette"]["bets"] == 3
        assert status["max_drawdown"] == "45.00"   # peak 210 -> trough 165
        assert status["stopped"] is True

        rep = await call(client, "strategy_report", {"session_id": sid})
        path = Path(rep["report_path"])
        assert path.exists() and path.suffix == ".html"
        assert str(sq_home) in rep["report_path"]
        html = path.read_text()
        assert len(html) > 10_000 and "<html" in html.lower()
        # exact analytics were attached for the single-config game
        assert rep["analytics_games"] == ["roulette"]

        end = await call(client, "session_end", {"session_id": sid})
        assert end["ended"] is True and end["bankroll"] == "165.00"

        # ledger survives session_end: status reloads it from disk
        again = await call(client, "session_status", {"session_id": sid})
        assert again["total_bets"] == 3 and again["pnl"] == "-35.00"
        return sid
    run(go)


def test_session_errors_are_mcp_errors():
    async def go(client):
        msg = await call_err(client, "session_status",
                             {"session_id": "no-such-session"})
        assert "unknown session_id" in msg
        msg = await call_err(client, "session_status",
                             {"session_id": "../../etc/passwd"})
        assert "invalid session_id" in msg

        start = await call(client, "session_start", {"starting_bankroll": 10.0})
        sid = start["session_id"]
        # stake exceeding the bankroll is rejected by the ledger
        msg = await call_err(client, "session_record_bet", {
            "session_id": sid, "game": "roulette", "stake": 100.0,
            "multiplier": 0.0,
        })
        assert "exceeds bankroll" in msg
        # sub-cent stake is rejected (exact-cent ledger)
        msg = await call_err(client, "session_record_bet", {
            "session_id": sid, "game": "roulette", "stake": 0.001,
            "multiplier": 0.0,
        })
        assert "exact cent" in msg
        # a report needs at least one recorded bet
        msg = await call_err(client, "strategy_report", {"session_id": sid})
        assert "no recorded bets" in msg
        await call(client, "session_end", {"session_id": sid})
    run(go)


# ---------------------------------------------------------------------------
# verify_bet
# ---------------------------------------------------------------------------

VERIFY_CASES = [
    ("roulette", {"bet_type": "straight", "selection": 17}),
    ("roulette", {"bet_type": "split", "selection": [17, 20]}),
    ("wheel", {"segments": 20, "risk": "medium"}),
    ("keno", {"picks": 5, "risk": "high", "selection": [1, 5, 9, 22, 40]}),
    ("mines", {"mines": 5, "picks": 3, "reveal": [0, 12, 24]}),
    ("plinko", {"rows": 16, "risk": "high"}),
    ("baccarat", {"bet_type": "tie"}),
    ("crash", {"target": 3.5}),
    ("blackjack", {}),
    ("slots", {}),
    ("video_poker", {"paytable": "stake",
                     "holds": [True, True, False, False, False]}),
]


def test_verify_bet_all_games_deterministic():
    server_seed, client_seed, nonce = "d" * 64, "spinquest-test", 7

    async def go(client):
        for game, cfg in VERIFY_CASES:
            args = {"game": game, "server_seed": server_seed,
                    "client_seed": client_seed, "nonce": nonce, "config": cfg}
            a = await call(client, "verify_bet", args)
            b = await call(client, "verify_bet", args)
            assert a == b, f"{game}: verify_bet is not deterministic"
            assert a["game"] == game
            assert a["server_seed_hash"] == sq_rng.hash_server_seed(server_seed)
            assert "payout" in a or "net" in a, f"{game}: no outcome in {a.keys()}"
        return True
    run(go)


def test_verify_bet_matches_scalar_rng():
    """The tool's outcome must equal an independent scalar-RNG replay."""
    server_seed, client_seed, nonce = "a" * 64, "check", 123

    async def go(client):
        # roulette: pocket = floor(float * 37)
        r = await call(client, "verify_bet", {
            "game": "roulette", "server_seed": server_seed,
            "client_seed": client_seed, "nonce": nonce,
            "config": {"bet_type": "red"},
        })
        f = sq_rng.generate_floats(server_seed, client_seed, nonce, 0, 1)[0]
        assert r["pocket"] == sq_rng.roulette_pocket(f)

        # keno: the ten drawn squares
        k = await call(client, "verify_bet", {
            "game": "keno", "server_seed": server_seed,
            "client_seed": client_seed, "nonce": nonce,
            "config": {"picks": 3, "risk": "classic"},
        })
        drawn = sq_rng.keno_hits(server_seed, client_seed, nonce)
        assert list(drawn) == list(k["drawn"])

        # mines: the mine positions
        m = await call(client, "verify_bet", {
            "game": "mines", "server_seed": server_seed,
            "client_seed": client_seed, "nonce": nonce,
            "config": {"mines": 4, "picks": 2},
        })
        assert m["mine_positions"] == sq_rng.mines_positions(
            server_seed, client_seed, nonce, 4)
    run(go)


def test_verify_bet_validation():
    async def go(client):
        msg = await call_err(client, "verify_bet", {
            "game": "roulette", "server_seed": "s", "client_seed": "c",
            "nonce": -1, "config": {"bet_type": "red"},
        })
        assert "nonce" in msg
    run(go)


# ---------------------------------------------------------------------------
# JSON hygiene of the sanitizer
# ---------------------------------------------------------------------------

def test_jsonify_handles_engine_types():
    import numpy as np
    from decimal import Decimal
    out = srv._jsonify({
        "a": np.int64(3), "b": np.float64(0.5), "c": Fraction(1, 3),
        "d": Decimal("1.50"), "e": (1, 2), "f": np.array([1.0, 2.0]),
        "g": float("nan"), "h": float("inf"), "i": {1: "x"},
        "j": frozenset({2, 1}),
    })
    json.dumps(out)  # strict-JSON serializable
    assert out["a"] == 3 and out["b"] == 0.5
    assert abs(out["c"] - 1 / 3) < 1e-12
    assert out["d"] == "1.50"
    assert out["e"] == [1, 2] and out["f"] == [1.0, 2.0]
    assert out["g"] is None and out["h"] is None
    assert out["i"] == {"1": "x"}
    assert out["j"] == [1, 2]
