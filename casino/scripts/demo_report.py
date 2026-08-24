"""Demo strategy report: a realistic simulated 2000-bet session (seeded).

Plays a seeded evening session across eight provably-fair engine
configurations — every outcome comes from the real engines'
``play_round`` scalar verification paths on a fixed seed pair, one nonce
per bet — records it in a :class:`spinquest_sim.session.Session`, computes
survival-optimal sizing/stop recommendations, and writes the full HTML
tear sheet to ``gauntlet/report/demo_report.html``.

Run:  python3 scripts/demo_report.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Callable, Dict, Tuple

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spinquest_sim import sizing  # noqa: E402
from spinquest_sim.games.baccarat import Baccarat  # noqa: E402
from spinquest_sim.games.crash import Crash  # noqa: E402
from spinquest_sim.games.keno import Keno  # noqa: E402
from spinquest_sim.games.mines import Mines  # noqa: E402
from spinquest_sim.games.plinko import Plinko  # noqa: E402
from spinquest_sim.games.roulette import Roulette  # noqa: E402
from spinquest_sim.games.wheel import Wheel  # noqa: E402
from spinquest_sim.report import generate_report  # noqa: E402
from spinquest_sim.session import Session  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(HERE, "..", "gauntlet", "report", "demo_report.html")

SERVER_SEED = "d6a3b5a2c8f4e9b1704a5c3d2e8f6a1b9c0d4e7f2a8b5c1d6e3f9a0b7c4d2e81"
CLIENT_SEED = "spinquest-demo-session"
SEED = 20260827          # numpy seed for game mix / timing (chosen so the
                         # demo session trips its stop-loss mid-session and
                         # keeps playing — the adherence audit has a story)
N_BETS = 2000
STARTING_BANKROLL = "2000.00"
STOP_LOSS = "500.00"     # advisory: quit if down $500
STOP_WIN = "800.00"      # advisory: quit if up $800


def build_engines() -> Dict[str, Tuple[Any, Callable[[Any, int], float], str]]:
    """{game name: (engine, multiplier_fn(engine, nonce), stake)}.

    Every multiplier is the engine's total-return ("for one") payout per
    unit staked, straight from its provably-fair ``play_round`` path.
    """
    def std(engine, nonce):
        return engine.play_round(SERVER_SEED, CLIENT_SEED, nonce)["payout"]

    def crash_mult(engine, nonce):
        return engine.play_round_seedpair(
            SERVER_SEED, CLIENT_SEED, nonce)["payout"]

    def plinko_mult(engine, nonce):
        return engine.play_round(
            SERVER_SEED, CLIENT_SEED, nonce)["multiplier"]

    return {
        "roulette:red": (Roulette("red"), std, "10.00"),
        "roulette:straight-17": (Roulette("straight", 17), std, "2.00"),
        "baccarat:banker": (Baccarat("banker"), std, "10.00"),
        "crash:2.00x": (Crash(2.0), crash_mult, "5.00"),
        "plinko:12-medium": (Plinko(12, "medium"), plinko_mult, "4.00"),
        "keno:5-classic": (Keno(5, "classic"), std, "3.00"),
        "wheel:20-medium": (Wheel(20, "medium"), std, "5.00"),
        "mines:3-mines-3-picks": (Mines(3, 3), std, "5.00"),
    }


# how often each configuration is played (a realistic mixed session:
# mostly even-money table bets, a sprinkle of long-shot side action)
MIX = {
    "roulette:red": 0.26,
    "baccarat:banker": 0.20,
    "crash:2.00x": 0.14,
    "plinko:12-medium": 0.12,
    "wheel:20-medium": 0.10,
    "mines:3-mines-3-picks": 0.08,
    "keno:5-classic": 0.06,
    "roulette:straight-17": 0.04,
}


def build_demo_session(n_bets: int = N_BETS, seed: int = SEED) -> Tuple[Session, Dict[str, Any]]:
    """Play the seeded demo session; returns (session, analytics mapping)."""
    engines = build_engines()
    assert abs(sum(MIX.values()) - 1.0) < 1e-12
    names = list(MIX)
    probs = np.array([MIX[g] for g in names])
    rng = np.random.default_rng(seed)

    session = Session(
        STARTING_BANKROLL,
        stop_loss=STOP_LOSS,
        stop_win=STOP_WIN,
        started_at="2026-08-21T19:00:00",
        allow_negative_bankroll=True,   # the ledger keeps counting even if
    )                                   # the human reloads mentally, not in cash

    t = datetime.fromisoformat("2026-08-21T19:02:00")
    nonce = 1
    for _ in range(n_bets):
        game = names[int(rng.choice(len(names), p=probs))]
        engine, mult_fn, stake = engines[game]
        mult = mult_fn(engine, nonce)
        session.record_bet(
            game, engine.config(), Decimal(stake), Decimal(str(mult)),
            t.isoformat(),
        )
        nonce += 1
        t += timedelta(seconds=int(rng.integers(3, 11)))

    analytics = {name: eng for name, (eng, _f, _s) in engines.items()}
    return session, analytics


def build_sizing() -> Dict[str, Any]:
    """Survival-optimal sizing + stops for the session's anchor game
    (roulette red — the largest slice of the handle)."""
    anchor = Roulette("red")
    bet_rec = sizing.survival_optimal_bet(
        2000, anchor, "survive_rounds", n_rounds=2000,
        min_bet=1, bet_grid=[1, 2, 5, 10, 20, 50],
    )
    stops_rec = sizing.recommend_stops(
        2000, 10, anchor, "survive_rounds", n_rounds=2000,
    )
    return {"bet": bet_rec, "stops": stops_rec}


def main() -> str:
    session, analytics = build_demo_session()
    siz = build_sizing()
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    generate_report(
        session, analytics, siz,
        title="SpinQuest Strategy Report — Demo Session",
        output_path=OUT_PATH,
    )
    out = os.path.abspath(OUT_PATH)
    print(f"wrote {out}")
    s = session.summary()
    print(f"bets={s['total_bets']} pnl={s['pnl']} "
          f"staked={s['total_staked']} returned={s['total_returned']} "
          f"max_dd={s['max_drawdown']} ({s['max_drawdown_pct']}) "
          f"stopped={s['stopped']} reason={s['stop_reason']}")
    return out


if __name__ == "__main__":
    main()
