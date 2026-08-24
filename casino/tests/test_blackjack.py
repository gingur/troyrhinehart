"""Tests for the Stake-style Blackjack engine (infinite deck).

Ground truth: references/stake/blackjack.md (unlimited decks, floor(f*52)
card mapping over the published CARDS index, payouts 1:1 / 3:2 / insurance
2:1, cursor-of-13 reservation) and references/woo/blackjack.md
(infinite-deck S17/DAS, resplit non-aces to 4 hands, expected return
-0.511734%, per-unit SD ~1.15).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pytest

from spinquest_sim import rng as sq_rng
from spinquest_sim.games import blackjack as bj_mod
from spinquest_sim.games.blackjack import (
    CARD_VALUES,
    INSURANCE_PAYS,
    P_VALUE,
    WOO_INFINITE_DECK_HOUSE_EDGE,
    Blackjack,
    hand_value,
)
from spinquest_sim.rng import BulkRng

SS = hashlib.sha256(b"test_blackjack server seed").hexdigest()
CS = "test-blackjack"


@pytest.fixture(scope="module")
def game() -> Blackjack:
    return Blackjack()


# ---------------------------------------------------------------------------
# card mapping (references/stake/blackjack.md sec. 3)
# ---------------------------------------------------------------------------

def test_card_values_follow_published_index():
    # Published CARDS table is rank-major (2..A, suits diamond/heart/spade/
    # club within each rank); blackjack values: 2-9 pip, 10/J/Q/K ten,
    # ace eleven (demoted to one by the hand logic as needed).
    for idx in range(52):
        rank = sq_rng.CARDS[idx][1:]
        if rank in ("10", "J", "Q", "K"):
            expect = 10
        elif rank == "A":
            expect = 11
        else:
            expect = int(rank)
        assert int(CARD_VALUES[idx]) == expect, sq_rng.CARDS[idx]
    # Composition: 4 cards each of 2..9 and ace, 16 ten-valued.
    counts = np.bincount(CARD_VALUES, minlength=12)
    assert list(counts[2:10]) == [4] * 8
    assert counts[10] == 16 and counts[11] == 4
    # Infinite deck probabilities used by the analytics.
    assert P_VALUE[10] == pytest.approx(4 / 13)
    for v in range(2, 10):
        assert P_VALUE[v] == pytest.approx(1 / 13)
    assert P_VALUE[11] == pytest.approx(1 / 13)


def test_cursor_reservation_is_published_thirteen():
    # "a curser of 13 to generate 52 possible game events" (sec. 3).
    assert sq_rng.CURSOR_INCREMENTS["blackjack"] == 13


def test_hand_value_ace_handling():
    # index 48 = diamond A, 32 = diamond 10, 0 = diamond 2, 16 = diamond 6
    assert hand_value([48, 32]) == (21, True)     # natural
    assert hand_value([48, 48]) == (12, True)     # A,A = soft 12
    assert hand_value([48, 16]) == (17, True)     # soft 17
    assert hand_value([48, 16, 32]) == (17, False)  # ace demoted
    assert hand_value([32, 32, 0]) == (22, False)   # hard bust


# ---------------------------------------------------------------------------
# published payouts (references/stake/blackjack.md sec. 4)
# ---------------------------------------------------------------------------

def test_published_payouts(game: Blackjack):
    # standard win 1:1 -> total 2.00; blackjack 3:2 -> total 2.50
    assert game.config()["standard_win_pays"] == 1.0
    assert game.bj_payout == 1.5
    # insurance pays 2:1 -> 3x the insurance stake; EV = 2*(4/13) - 9/13
    assert INSURANCE_PAYS == 2.0
    assert Blackjack.insurance_ev() == pytest.approx(-1 / 13)
    # basic strategy never takes insurance (negative EV side bet)
    assert game.config()["insurance_taken"] is False


def test_blackjack_probability(game: Blackjack):
    # P(natural) = 2 * (1/13) * (4/13) = 8/169 per hand, infinite deck.
    assert game._p_player_bj == pytest.approx(8 / 169)
    # P(win WITH blackjack) = P(player natural) * P(no dealer natural)
    p_dbj = sum(P_VALUE[u] * game._p_dealer_bj[u] for u in P_VALUE)
    expect = (8 / 169) * (1 - p_dbj)
    assert game.outcome_probabilities()["blackjack_win"] == pytest.approx(expect)


# ---------------------------------------------------------------------------
# analytics vs the WoO infinite-deck reference (references/woo/blackjack.md)
# ---------------------------------------------------------------------------

def test_analytic_house_edge_matches_woo(game: Blackjack):
    # WoO exact infinite-deck figure for S17 / DAS / resplit non-aces to
    # 4 hands / aces once / no surrender: 0.511734% (published to 6
    # significant figures).  The engine's exact analytics must reproduce
    # it to better than half the last published digit (measured residual
    # -3.6e-9).
    assert abs(game.house_edge - WOO_INFINITE_DECK_HOUSE_EDGE) < 5e-7
    assert game.rtp == pytest.approx(1.0 - game.house_edge)
    assert 0.994 < game.rtp < 0.996


def test_analytic_std_close_to_woo(game: Blackjack):
    # WoO publishes ~1.15 (headline) / 1.142 (liberal 6-deck) per unit.
    assert abs(game.std_per_unit - 1.15) < 0.02
    assert game.variance_per_unit == pytest.approx(game.std_per_unit**2)


def test_payout_distribution_is_a_distribution(game: Blackjack):
    dist = game.payout_distribution()
    assert sum(dist.values()) == pytest.approx(1.0, abs=1e-12)
    assert all(p > 0 for p in dist.values())
    # every support point on the half-unit lattice within [-8, +8]
    for x in dist:
        assert abs(2 * x - round(2 * x)) < 1e-12 and -8 <= x <= 8
    # mean of the distribution IS the EV (cross-checked in _build too)
    mean = sum(x * p for x, p in dist.items())
    assert mean == pytest.approx(game.ev, abs=1e-12)
    # blackjack pay 1.5 present
    assert dist[1.5] > 0.04
    # a real 4-hand game has support BEYOND +-6 (3-resplit rounds with
    # doubles): tiny but strictly positive, including the +-8 extremes
    p_tail = sum(p for x, p in dist.items() if abs(x) > 6)
    assert 0.0 < p_tail < 1e-4
    assert dist.get(8.0, 0.0) > 0.0 and dist.get(-8.0, 0.0) > 0.0
    probs = game.outcome_probabilities()
    assert probs["win"] + probs["push"] + probs["loss"] == pytest.approx(1.0)
    assert 0.42 < probs["win"] < 0.45
    assert 0.46 < probs["loss"] < 0.50
    assert 0.07 < probs["push"] < 0.10


def test_analytic_summary_contract(game: Blackjack):
    s = game.analytic_summary()
    assert set(s) == {"rtp", "house_edge", "std_per_unit", "config"}
    assert s["rtp"] == game.rtp
    cfg = s["config"]
    assert cfg["game"] == "blackjack"
    assert cfg["decks"] == "infinite"
    assert cfg["dealer_soft_17"] == "stand"
    assert cfg["das"] is True and cfg["max_hands"] == 4
    assert cfg["blackjack_pays"] == 1.5


# ---------------------------------------------------------------------------
# derived basic strategy = classic infinite-deck S17/DAS chart
# ---------------------------------------------------------------------------

def test_strategy_splits(game: Blackjack):
    ups = range(2, 12)
    # always split aces and eights; never split fives or tens
    assert all(game.SPLIT[11, u] for u in ups)
    assert all(game.SPLIT[8, u] for u in ups)
    assert not game.SPLIT[5, 2:12].any()
    assert not game.SPLIT[10, 2:12].any()
    # nines: split vs 2-6 and 8-9, stand vs 7/10/A
    for u in ups:
        assert bool(game.SPLIT[9, u]) == (u in (2, 3, 4, 5, 6, 8, 9))
    # twos/threes/sevens vs 2-7 (DAS chart)
    for r in (2, 3, 7):
        for u in ups:
            assert bool(game.SPLIT[r, u]) == (u <= 7), (r, u)
    # sixes vs 2-6, fours vs 5-6 (DAS)
    for u in ups:
        assert bool(game.SPLIT[6, u]) == (u <= 6)
        assert bool(game.SPLIT[4, u]) == (u in (5, 6))


def test_strategy_hard_doubles(game: Blackjack):
    # 11 doubles vs 2-10 (S17: not vs ace); 10 vs 2-9; 9 vs 3-6
    for u in range(2, 12):
        assert bool(game.DBL_HARD[11, u]) == (u <= 10)
        assert bool(game.DBL_HARD[10, u]) == (u <= 9)
        assert bool(game.DBL_HARD[9, u]) == (3 <= u <= 6)
        assert not game.DBL_HARD[8, u]


def test_strategy_hard_hit_stand(game: Blackjack):
    for u in range(2, 12):
        assert game.HIT_HARD[8, u]           # always hit 8 or less
        assert not game.HIT_HARD[17, u]      # always stand hard 17+
        assert not game.HIT_HARD[20, u]
        # 12 stands only vs 4-6; 13-16 stand vs 2-6, hit vs 7+
        assert bool(game.HIT_HARD[12, u]) == (u not in (4, 5, 6))
        for t in (13, 14, 15, 16):
            assert bool(game.HIT_HARD[t, u]) == (u >= 7), (t, u)


def test_strategy_soft_totals_with_infinite_deck_quirks(game: Blackjack):
    for u in range(2, 12):
        # soft 19+ stand (S17 chart; no soft-19-v-6 double at S17)
        assert not game.HIT_SOFT[19, u] and not game.DBL_SOFT[19, u]
        assert not game.HIT_SOFT[20, u]
        # soft 18: double 3-6, stand 2/7/8, hit 9/10/A
        assert bool(game.DBL_SOFT[18, u]) == (3 <= u <= 6)
        assert bool(game.HIT_SOFT[18, u]) == (u >= 9)
        # soft 17 doubles vs 3-6; soft 16/15 vs 4-6; soft 14/13 vs 5-6...
        assert bool(game.DBL_SOFT[17, u]) == (3 <= u <= 6)
        assert bool(game.DBL_SOFT[16, u]) == (4 <= u <= 6)
        # ... EXCEPT the two published infinite-deck deviations:
        # hit soft 13 vs 5 and soft 15 vs 4 (4-deck chart doubles there).
        assert bool(game.DBL_SOFT[15, u]) == (u in (5, 6))
        assert bool(game.DBL_SOFT[14, u]) == (u in (5, 6))
        assert bool(game.DBL_SOFT[13, u]) == (u == 6)
    assert game.HIT_SOFT[13, 5] and not game.DBL_SOFT[13, 5]
    assert game.HIT_SOFT[15, 4] and not game.DBL_SOFT[15, 4]
    # soft totals below 18 always hit when not doubling
    for t in range(12, 18):
        for u in range(2, 12):
            assert game.HIT_SOFT[t, u]


# ---------------------------------------------------------------------------
# rule variants move the edge the right way
# ---------------------------------------------------------------------------

def test_rule_variants():
    s17 = Blackjack()
    h17 = Blackjack(dealer_hits_soft_17=True)
    # H17 costs the player ~0.22% at infinite deck
    assert 0.0015 < h17.house_edge - s17.house_edge < 0.0030
    # blackjack paying 1:1 instead of 3:2 costs exactly 0.5 * P(BJ win)
    even = Blackjack(bj_payout=1.0)
    delta = even.house_edge - s17.house_edge
    assert delta == pytest.approx(
        0.5 * s17.outcome_probabilities()["blackjack_win"], abs=1e-12
    )
    # removing DAS and tightening the resplit cap all cost the player,
    # monotonically: 4 hands (default) < 3 hands < 2 hands
    assert Blackjack(das=False).house_edge > s17.house_edge
    m3, m2 = Blackjack(max_hands=3), Blackjack(max_hands=2)
    assert s17.house_edge < m3.house_edge < m2.house_edge
    # the resplit cap matters: M=3 misses WoO's figure by ~9e-5
    assert m3.house_edge - WOO_INFINITE_DECK_HOUSE_EDGE > 5e-5
    with pytest.raises(ValueError):
        Blackjack(max_hands=5)
    with pytest.raises(ValueError):
        Blackjack(bj_payout=1.4)


# ---------------------------------------------------------------------------
# (b) provably-fair scalar rounds
# ---------------------------------------------------------------------------

def test_play_round_deterministic_and_verifiable(game: Blackjack):
    r1 = game.play_round(SS, CS, 7)
    r2 = game.play_round(SS, CS, 7)
    assert r1 == r2
    assert r1["verification"] == {
        "server_seed": SS,
        "client_seed": CS,
        "nonce": 7,
    }
    # the card stream IS the published card_draws stream for this nonce
    n = len(r1["cards"])
    assert r1["cards"] == sq_rng.card_draws(SS, CS, 7, n)
    assert r1["card_names"] == [sq_rng.CARDS[i] for i in r1["cards"]]


def test_play_round_invariants(game: Blackjack):
    seen_split = seen_double = seen_bj = seen_dbj = seen_allbust = False
    for nonce in range(1, 401):
        r = game.play_round(SS, CS, nonce)
        net = r["net"]
        assert abs(2 * net - round(2 * net)) < 1e-12  # half-unit lattice
        assert -8 <= net <= 8
        wagers = [h["wager"] for h in r["hands"]]
        assert r["total_bet"] == sum(wagers)
        assert r["total_returned"] == pytest.approx(r["total_bet"] + net)
        assert 1 <= len(r["hands"]) <= 4
        up, hole = CARD_VALUES[r["cards"][1]], CARD_VALUES[r["cards"][3]]
        if r["player_blackjack"] or r["dealer_blackjack"]:
            # resolved on the first four cards only
            assert len(r["cards"]) == 4
            if r["player_blackjack"] and r["dealer_blackjack"]:
                assert net == 0.0
            elif r["player_blackjack"]:
                assert net == game.bj_payout
                seen_bj = True
            else:
                assert net == -1.0
                seen_dbj = True
            continue
        if all(h["bust"] for h in r["hands"]):
            # dealer never draws into an already-lost round
            t0, s0 = 0, False
            from spinquest_sim.games.blackjack import _add
            t0, s0 = _add(int(up), up == 11, int(hole))
            assert r["dealer_total"] == t0
            assert net == -sum(wagers)
            seen_allbust = True
        else:
            assert r["dealer_total"] >= 17
        for h in r["hands"]:
            assert h["bust"] == (h["total"] > 21)
            assert h["wager"] in (1, 2)
        if len(r["hands"]) > 1:
            seen_split = True
        if any(h["wager"] == 2 for h in r["hands"]):
            seen_double = True
    assert seen_split and seen_double and seen_bj and seen_dbj and seen_allbust


def test_play_round_four_hand_rounds_happen(game: Blackjack):
    # A real 3-resplit game produces 4-hand rounds (P ~ 5.4e-4).  On this
    # deterministic stream the first is at nonce 510; count them over the
    # first 5000 nonces and check the vectorized path agrees bit for bit.
    r = game.play_round(SS, CS, 510)
    assert len(r["hands"]) == 4
    assert r["total_bet"] == sum(h["wager"] for h in r["hands"]) >= 4
    n = 5000
    counts = {1: 0, 2: 0, 3: 0, 4: 0}
    nets = []
    for nonce in range(1, n + 1):
        rr = game.play_round(SS, CS, nonce)
        counts[len(rr["hands"])] += 1
        nets.append(rr["net"])
    assert counts[4] >= 1  # measured: 2 in the first 5000 nonces
    res = game.simulate(
        n, bulk=BulkRng(SS, CS, nonce_start=1, workers=1),
        progress=False, keep_payouts=True,
    )
    assert np.array_equal(np.asarray(nets), res["payouts"])


def test_simulated_tail_beyond_six_units(game: Blackjack):
    # |net| > 6 rounds (4 hands with doubles) exist: analytic P ~ 1.13e-5,
    # and this deterministic 1M-round stream contains 12 of them
    # (including one +8).  A hard-capped +-6 engine would show zero.
    res = game.simulate(
        1_000_000, bulk=BulkRng(SS, CS, nonce_start=1), progress=False
    )
    hist = np.asarray(res["payout_hist"], dtype=np.int64)
    lat = np.asarray(res["payout_lattice"])
    assert lat[0] == -8.0 and lat[-1] == 8.0 and hist.size == 33
    tail = int(hist[np.abs(lat) > 6].sum())
    assert tail > 0
    p_tail = float(game.payout_dist[np.abs(lat) > 6].sum())
    # Poisson-consistent with the exact analytic tail probability
    assert abs(tail - 1_000_000 * p_tail) < 5 * math.sqrt(1_000_000 * p_tail)


def test_play_round_dealer_stands_soft_17():
    s17, h17 = Blackjack(), Blackjack(dealer_hits_soft_17=True)
    # find rounds where the dealer's final differs between the rules
    diff = 0
    for nonce in range(1, 500):
        a, b = s17.play_round(SS, CS, nonce), h17.play_round(SS, CS, nonce)
        if a["dealer_total"] != b["dealer_total"]:
            diff += 1
    assert diff > 0  # H17 actually changes dealer play on this stream


# ---------------------------------------------------------------------------
# (c) vectorized simulator == scalar path, per nonce, bit for bit
# ---------------------------------------------------------------------------

def test_vectorized_matches_scalar_per_nonce(game: Blackjack):
    n = 5000
    bulk = BulkRng(SS, CS, nonce_start=1, workers=1)
    res = game.simulate(n, bulk=bulk, progress=False, keep_payouts=True)
    nets = res["payouts"]
    assert nets.shape == (n,)
    for i in range(n):
        assert nets[i] == game.play_round(SS, CS, 1 + i)["net"], i
    assert res["verification"]["nonce_range"] == (1, 1 + n)
    assert res["verification"]["server_seed_hash"] == sq_rng.hash_server_seed(SS)


def test_overflow_fallback_is_exact(game: Blackjack):
    # A 6-float budget starves thousands of rounds; every one must be
    # replayed scalar and produce the identical payout stream.
    n = 20_000
    lo = game.simulate(
        n, bulk=BulkRng(SS, CS, nonce_start=1, workers=1),
        progress=False, float_budget=6, keep_payouts=True,
    )
    hi = game.simulate(
        n, bulk=BulkRng(SS, CS, nonce_start=1, workers=1),
        progress=False, float_budget=24, keep_payouts=True,
    )
    assert lo["overflow_rounds"] > 1000
    assert hi["overflow_rounds"] == 0
    assert np.array_equal(lo["payouts"], hi["payouts"])


def test_simulate_result_contract_and_statistics(game: Blackjack):
    n = 200_000
    res = game.simulate(
        n, bulk=BulkRng(SS, CS, nonce_start=1, workers=1), progress=False
    )
    for key in (
        "rtp", "house_edge", "std_per_unit", "config", "n_rounds",
        "mean_net", "analytic_rtp", "analytic_house_edge",
        "analytic_std_per_unit", "se_rtp", "z_score", "within_3se",
        "payout_hist", "payout_lattice", "rounds_per_sec", "verification",
    ):
        assert key in res, key
    assert res["n_rounds"] == n
    assert res["rtp"] == pytest.approx(1.0 - res["house_edge"])
    hist = np.asarray(res["payout_hist"], dtype=np.float64)
    lat = np.asarray(res["payout_lattice"])
    assert hist.sum() == n
    assert float(hist @ lat) / n == pytest.approx(res["mean_net"], abs=1e-12)
    # deterministic fixed-seed campaign: statistical agreement with the
    # exact analytics (z at 4 SE; empirical bin probs near exact ones)
    assert abs(res["z_score"]) < 4.0
    assert res["se_rtp"] == pytest.approx(game.std_per_unit / math.sqrt(n))
    np.testing.assert_allclose(hist / n, game.payout_dist, atol=6e-3)
    assert abs(res["std_per_unit"] - game.std_per_unit) < 0.01


# ---------------------------------------------------------------------------
# hardened validation-script contract (scripts/validate_blackjack.py)
# ---------------------------------------------------------------------------

def _load_validator():
    path = Path(__file__).resolve().parent.parent / "scripts" / \
        "validate_blackjack.py"
    spec = importlib.util.spec_from_file_location("validate_blackjack", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def validator():
    return _load_validator()


def _json_summary(out: str) -> dict:
    lines = [l for l in out.splitlines()
             if l.startswith("BLACKJACK_VALIDATION_JSON: ")]
    assert len(lines) == 1, "JSON summary line must be emitted exactly once"
    return json.loads(lines[0].split(": ", 1)[1])


def test_validator_skip_sim_passes(validator, capsys):
    rc = validator.main(["--skip-sim"])
    summary = _json_summary(capsys.readouterr().out)
    assert rc == 0
    assert summary["all_pass"] is True
    assert summary["game"] == "blackjack"
    names = [c["check"] for c in summary["checks"]]
    assert len(names) == 9 and all(c["pass"] for c in summary["checks"])
    # payout-for-payout rows all present
    assert any("standard win 1:1" in n for n in names)
    assert any("blackjack 3:2" in n for n in names)
    assert any("insurance 2:1" in n for n in names)
    assert any("CARDS index table" in n for n in names)


def test_validator_small_campaign_fails_without_waiver(validator, capsys):
    rc = validator.main(["--rounds", "20000"])
    summary = _json_summary(capsys.readouterr().out)
    assert rc == 1 and summary["all_pass"] is False
    bad = [c for c in summary["checks"] if not c["pass"]]
    assert len(bad) == 1 and "campaign size" in bad[0]["check"]


def test_validator_small_campaign_with_waiver(validator, capsys):
    rc = validator.main(["--rounds", "20000", "--allow-small"])
    summary = _json_summary(capsys.readouterr().out)
    assert rc == 0 and summary["all_pass"] is True
    # the waived bar is NOT recorded as a passing gate
    assert not any("campaign size" in c["check"] for c in summary["checks"])
    assert summary["simulation"]["n_rounds"] == 20000


def test_validator_emits_json_and_exit_2_on_crash(validator, capsys,
                                                  monkeypatch):
    monkeypatch.setattr(validator, "STAKE_MD",
                        Path("/nonexistent/blackjack.md"))
    rc = validator.main(["--skip-sim"])
    summary = _json_summary(capsys.readouterr().out)
    assert rc == 2
    assert summary["all_pass"] is False and "error" in summary


def test_validator_rejects_bad_cli(validator):
    for argv in (["--rounds", "0"], ["--seed", "nothex"],
                 ["--seed", "ab" * 31], ["--client", ""]):
        with pytest.raises(SystemExit):
            validator.main(argv + ["--skip-sim"])


def test_validator_parsers_are_sanity_bounded(validator):
    stake_text = (Path(__file__).resolve().parent.parent / "references" /
                  "stake" / "blackjack.md").read_text(encoding="utf-8")
    woo_text = (Path(__file__).resolve().parent.parent / "references" /
                "woo" / "blackjack.md").read_text(encoding="utf-8")
    # clean parses succeed and reproduce the published figures
    stake = validator.parse_stake_reference(stake_text)
    woo = validator.parse_woo_reference(woo_text)
    assert stake["bj_odds"] == (3, 2) and stake["ins_odds"] == (2, 1)
    assert stake["stake_edge"] == pytest.approx(0.0057)
    assert woo["infinite_deck_edge"] == pytest.approx(0.00511734)
    assert woo["headline_sd"] == pytest.approx(1.15)
    # corrupted figures are rejected, not gated against
    with pytest.raises(validator.ReferenceParseError):
        validator.parse_stake_reference(
            stake_text.replace('"Edge: 0.57%"', '"Edge: 57%"'))
    with pytest.raises(validator.ReferenceParseError):
        validator.parse_stake_reference(stake_text.replace("| 51 | ♣A |", ""))
    with pytest.raises(validator.ReferenceParseError):
        validator.parse_woo_reference(
            woo_text.replace("**0.511734%** (player EV",
                             "**51.1734%** (player EV"))
    with pytest.raises(validator.ReferenceParseError):
        validator.parse_woo_reference(woo_text.replace("(player EV", "(XX"))
