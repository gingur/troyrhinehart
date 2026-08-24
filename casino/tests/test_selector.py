"""Tests for spinquest_sim.selector — the odds-ranked game selector.

The heavy analytic build (two video-poker paytable solves + exact
Atkins slots enumeration, ~30-40 s) runs once per process via the
selector's lru_cache; every test after the first ranking() call is
cheap.

The reference figures asserted here are the published Wizard-of-Odds /
Stake figures snapshotted in references/woo/*.md (video_poker.md:
"Full-pay 9/6 Jacks or Better: 99.54% return"; baccarat.md: "Banker
98.94%, Player 98.76%, Tie 85.64%"; blackjack.py carries WoO's
infinite-deck house edge 0.00511734).  The selector itself never
hardcodes them — it pulls everything live from the engines — so these
tests are the cross-check that the live figures match the ground truth.
"""

import math

import numpy as np
import pandas as pd
import pytest

from spinquest_sim import selector
from spinquest_sim.games import blackjack as bj_mod


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def df():
    return selector.ranking()  # defaults: bankroll=100, bet=1, rounds=200


# ---------------------------------------------------------------------------
# configuration grid
# ---------------------------------------------------------------------------

def test_enumerates_all_ten_games():
    cfgs = selector.enumerate_configs()
    games = {c.game for c in cfgs}
    assert games == {
        "plinko", "mines", "keno", "wheel", "blackjack", "baccarat",
        "roulette", "video_poker", "crash", "slots",
    }


def test_config_counts():
    cfgs = selector.enumerate_configs()
    counts = {}
    for c in cfgs:
        counts[c.game] = counts.get(c.game, 0) + 1
    assert counts["plinko"] == 9 * 3          # rows 8..16 x 3 risks
    assert counts["mines"] == 300             # sum_{m=1}^{24} (25 - m)
    assert counts["keno"] == 10 * 4           # picks 1..10 x 4 risks
    assert counts["wheel"] == 5 * 3           # 5 segment counts x 3 risks
    assert counts["blackjack"] == 1
    assert counts["baccarat"] == 3
    assert counts["roulette"] == 13           # all European bet types
    assert counts["video_poker"] == 2         # 9/6 JoB + Stake paytable
    assert counts["crash"] == len(selector.CRASH_TARGETS)
    assert counts["slots"] == 1               # Atkins only (validated model)
    assert len(cfgs) == sum(counts.values())


def test_config_labels_unique_within_game():
    cfgs = selector.enumerate_configs()
    keys = [(c.game, c.label) for c in cfgs]
    assert len(keys) == len(set(keys))


def test_scarab_excluded():
    # Scarab Spin's reconstruction is a documented strict=False xfail
    # (RTP > 1); it must not appear in the ranking.
    cfgs = selector.enumerate_configs()
    slots_labels = [c.label for c in cfgs if c.game == "slots"]
    assert len(slots_labels) == 1
    assert "atkins" in slots_labels[0].lower()
    assert not any("scarab" in lbl.lower() for lbl in slots_labels)


def test_factories_build_cheap_engines():
    # Spot-check that factories produce live engine objects exposing the
    # analytic API (cheap games only — no VP/slots solve here).
    by_key = {(c.game, c.label): c for c in selector.enumerate_configs()}
    eng = by_key[("mines", "3 mines, 5 picks")].build()
    assert 0 < eng.rtp < 1 and eng.std_per_unit > 0
    eng = by_key[("wheel", "10 segments, low")].build()
    assert eng.rtp == pytest.approx(0.99)


# ---------------------------------------------------------------------------
# ranking table shape and ordering
# ---------------------------------------------------------------------------

def test_ranking_shape_and_columns(df):
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == [
        "rank", "game", "config", "rtp", "house_edge", "std_per_unit",
        "variance_per_unit", "survival_prob",
    ]
    assert len(df) == len(selector.enumerate_configs())
    assert list(df["rank"]) == list(range(1, len(df) + 1))
    assert not df.isna().any().any()


def test_ranking_sorted_by_rtp_desc(df):
    rtps = df["rtp"].to_numpy()
    assert (np.diff(rtps) <= 1e-15).all()


def test_ranking_internal_consistency(df):
    assert np.allclose(df["rtp"] + df["house_edge"], 1.0, atol=1e-12)
    assert np.allclose(
        df["variance_per_unit"], df["std_per_unit"] ** 2, rtol=1e-12
    )
    assert ((df["survival_prob"] >= 0) & (df["survival_prob"] <= 1)).all()
    assert (df["rtp"] > 0).all() and (df["rtp"] < 1.0).all()
    assert "normal" in df.attrs["survival_metric"]  # labeled approximation


def test_survival_column_matches_function(df):
    p = df.attrs["survival_params"]
    row = df[(df["game"] == "baccarat") & (df["config"] == "tie")].iloc[0]
    expect = selector.survival_probability(
        row["rtp"], row["std_per_unit"], p["bankroll"], p["bet"], p["rounds"]
    )
    assert row["survival_prob"] == pytest.approx(expect, abs=1e-12)


# ---------------------------------------------------------------------------
# sanity of the top of the table against references/woo figures
# ---------------------------------------------------------------------------

def test_top_of_table_is_96_jacks_or_better(df):
    top = df.iloc[0]
    assert top["game"] == "video_poker"
    assert top["config"] == "9/6 Jacks or Better"
    # references/woo/video_poker.md: "Full-pay 9/6 Jacks or Better:
    # 99.54% return" — half-ULP of the printed 2-dp percentage.
    assert abs(top["rtp"] - 0.9954) <= 5.0e-5


def test_blackjack_near_woo_995(df):
    row = df[df["game"] == "blackjack"].iloc[0]
    # references/woo/blackjack figures: house edge ~0.5% under basic
    # strategy; engine ships WoO's infinite-deck 0.00511734 benchmark.
    assert abs(row["rtp"] - 0.995) < 1.0e-3
    assert abs(row["house_edge"] - bj_mod.WOO_INFINITE_DECK_HOUSE_EDGE) < 2e-4
    # Blackjack ranks second, right under 9/6 JoB.
    assert row["rank"] == 2


def test_baccarat_matches_woo(df):
    # references/woo/baccarat.md: "Banker 98.94%, Player 98.76%, Tie
    # 85.64%" (8-deck).  1e-4 covers rounding of the printed 2-dp
    # percentages.
    rows = df[df["game"] == "baccarat"].set_index("config")
    assert abs(rows.loc["banker", "rtp"] - 0.9894) < 1.0e-4
    assert abs(rows.loc["player", "rtp"] - 0.9876) < 1.0e-4
    assert abs(rows.loc["tie", "rtp"] - 0.8564) < 1.0e-4
    # Banker beats player beats tie; tie is the worst bet on the board.
    assert rows.loc["banker", "rtp"] > rows.loc["player", "rtp"]
    assert rows.loc["tie", "rtp"] == df["rtp"].min()


def test_video_poker_beats_blackjack_beats_banker(df):
    r = {g: df[df["game"] == g]["rtp"].max()
         for g in ("video_poker", "blackjack", "baccarat")}
    assert r["video_poker"] > r["blackjack"] > r["baccarat"]


def test_roulette_uniform_european_edge(df):
    # Every European bet returns exactly 36/37 (references/woo/roulette).
    rows = df[df["game"] == "roulette"]
    assert len(rows) == 13
    assert np.allclose(rows["rtp"], 36.0 / 37.0, atol=1e-12)
    # ... but variance spans the bet types: straight is the wildest.
    assert rows.loc[rows["std_per_unit"].idxmax(), "config"] == "straight 17"


def test_mines_wheel_flat_99(df):
    assert np.allclose(df[df["game"] == "mines"]["rtp"], 0.99, atol=1e-12)
    assert np.allclose(df[df["game"] == "wheel"]["rtp"], 0.99, atol=1e-12)


def test_crash_rtp_just_under_99(df):
    rows = df[df["game"] == "crash"]
    assert len(rows) == len(selector.CRASH_TARGETS)
    # Published 1% edge, minus the engine's exact 2^-32 quantization.
    assert (rows["rtp"] <= 0.99).all()
    assert (rows["rtp"] > 0.9899).all()


def test_keno_and_plinko_bands(df):
    keno = df[df["game"] == "keno"]["rtp"]
    plinko = df[df["game"] == "plinko"]["rtp"]
    # Stake originals sit in a tight band around the published 99%.
    assert keno.between(0.94, 1.0 - 1e-9).all()
    assert plinko.between(0.98, 1.0 - 1e-9).all()


def test_atkins_slots_rtp(df):
    row = df[df["game"] == "slots"].iloc[0]
    # WoO Atkins Diet par sheet: 97.05% enumerated exactly by the engine.
    assert abs(row["rtp"] - 0.9705) < 1.0e-3


# ---------------------------------------------------------------------------
# survival metric
# ---------------------------------------------------------------------------

def test_survival_monotone_in_bankroll():
    ps = [selector.survival_probability(0.97, 2.0, B, 1.0, 500)
          for B in (5, 20, 80, 320)]
    assert all(a < b for a, b in zip(ps, ps[1:]))
    assert 0.0 < ps[0] < ps[-1] <= 1.0


def test_survival_monotone_in_rounds():
    ps = [selector.survival_probability(0.97, 2.0, 20.0, 1.0, n)
          for n in (50, 200, 1000, 5000)]
    assert all(a > b for a, b in zip(ps, ps[1:]))


def test_survival_edge_hurts():
    fair = selector.survival_probability(1.0, 1.0, 30.0, 1.0, 1000)
    bad = selector.survival_probability(0.85, 1.0, 30.0, 1.0, 1000)
    assert fair > bad


def test_survival_degenerate_cases():
    assert selector.survival_probability(0.99, 1.0, 0.0, 1.0, 100) == 0.0
    # Deterministic loss of 1% per round: broke by round 100 from B=1.
    assert selector.survival_probability(0.99, 0.0, 1.0, 1.0, 100) == 0.0
    assert selector.survival_probability(0.99, 0.0, 100.0, 1.0, 100) == 1.0
    with pytest.raises(ValueError):
        selector.survival_probability(0.99, 1.0, 100.0, 0.0, 100)
    with pytest.raises(ValueError):
        selector.survival_probability(0.99, 1.0, 100.0, 1.0, 0)
    # Strong negative drift must not overflow (log-space reflection term).
    p = selector.survival_probability(0.5, 0.1, 1000.0, 1.0, 10000)
    assert 0.0 <= p <= 1.0


def test_survival_matches_normal_walk_monte_carlo():
    """The labeled approximation must agree with a Monte-Carlo random
    walk with NORMAL increments (that is exactly the distribution the
    approximation assumes; the game-specific error is the normality of
    payouts, documented in the module docstring)."""
    rtp, std, bankroll, bet, rounds = 0.97, 2.0, 20.0, 1.0, 200
    analytic = selector.survival_probability(rtp, std, bankroll, bet, rounds)
    rng = np.random.default_rng(20260824)
    n_paths = 60_000
    steps = rng.normal((rtp - 1.0) * bet, std * bet, size=(n_paths, rounds))
    ruined = (bankroll + np.cumsum(steps, axis=1)).min(axis=1) <= 0.0
    empirical = 1.0 - ruined.mean()
    # MC s.e. ~0.002; discrete walks slightly overshoot the continuous
    # barrier, so allow a modest one-sided-ish margin.
    assert abs(analytic - empirical) < 0.03
    assert 0.0 < analytic < 1.0


# ---------------------------------------------------------------------------
# markdown rendering
# ---------------------------------------------------------------------------

def test_to_markdown(df):
    md = selector.to_markdown(df, top=10)
    assert isinstance(md, str)
    lines = [ln for ln in md.splitlines() if ln.startswith("|")]
    assert len(lines) == 12  # header + separator + 10 rows
    assert "video_poker" in lines[2]        # top-ranked row
    assert "9/6 Jacks or Better" in lines[2]
    assert "99.5439%" in lines[2]
    assert "normal" in md                   # survival metric labeled
    # Default path builds its own ranking (cached, so cheap).
    md_full = selector.to_markdown()
    assert md_full.count("\n") > len(selector.enumerate_configs())
