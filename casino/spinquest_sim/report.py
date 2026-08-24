"""Strategy report generator: one self-contained HTML tear sheet per session.

Input: a :class:`spinquest_sim.session.Session` (the authoritative bankroll
ledger), optional per-game engine analytics, and an optional sizing
recommendation from :mod:`spinquest_sim.sizing`.  Output: a single HTML file
with every plot embedded as a matplotlib (Agg) PNG data URI — no external
requests, no scripts, printable.

The design bar is the QuantStats reference tear sheet
(``references/quantstats/reference_tearsheet.html``): every metric from that
sheet that is *meaningful for a casino session* is covered, and the report
adds casino-native rigor QuantStats cannot offer:

- **Realized vs expected house edge with SE bands.**  Each bet's expected
  net is ``stake * (RTP - 1)`` and its variance ``stake^2 *
  variance_per_unit``, both pulled from the analytic engine figures the
  caller supplies.  Bets are independent (independent RNG nonces), so the
  session-level standard error is ``sqrt(sum of per-bet variances)`` and
  the whole session gets a z-score: *how (un)lucky was this session,
  in standard errors, against the exact math of the games played?*
- **Per-game attribution vs analytic RTP.**  The same decomposition per
  game: handle, realized RTP vs the engine's analytic RTP, the edge paid
  (expected loss), the luck residual in dollars and in z-units.
- **Z-score luck decomposition.**  P&L == (expected P&L) + (luck), with the
  luck term scored against the analytic standard error, cumulatively
  plotted, and tested against a two-sided normal p-value (with an explicit
  CLT caveat for heavy-tailed games).
- **Risk of ruin remaining.**  First-passage (reflection-formula) diffusion
  approximation of P(busting the *current* bankroll within the next N
  bets) at the session's realized stake mix — clearly labeled as a normal
  approximation, coarse for heavy-tailed games.
- **Stop-loss adherence.**  The session's advisory stop latch is audited:
  did a stop trigger, and how much was wagered/won/lost *after* it?
- **Bankroll / underwater curves** with the expected-value path and its
  95% band, drawdown episodes from the session's exact-Decimal episode
  tracker, and rolling realized RTP against the analytic expectation.

Analytics input
---------------

``analytics`` maps each *game name as recorded in the session* to either an
engine object exposing ``rtp`` and ``variance_per_unit`` (or
``std_per_unit``) — every engine in :mod:`spinquest_sim.games` qualifies —
or a plain mapping with those keys.  Record distinct configurations under
distinct game names (e.g. ``"roulette:red"`` vs ``"roulette:straight-17"``)
so each name has one well-defined RTP.  Games without analytics are still
fully reported on the realized side; expectation-based metrics are computed
over the covered bets and the coverage fraction is disclosed.  When
coverage is not 100%, expectation overlays are dropped from the plots
rather than silently extrapolated.

Sizing input
------------

``sizing`` is an optional dict with keys ``"bet"`` (a
:func:`spinquest_sim.sizing.survival_optimal_bet` result) and/or
``"stops"`` (a :func:`spinquest_sim.sizing.recommend_stops` result); both
are rendered verbatim as recommendation panels with their evidence tables.

Conventions and definitions (all recomputable from the ledger)
--------------------------------------------------------------

- *win / push / loss*: payout > / == / < stake.
- *streaks*: longest run of net > 0 (wins) / net < 0 (losses); a push
  breaks both.
- *skew / kurtosis*: population moments of per-bet net (kurtosis is
  excess: normal = 0).
- *VaR / CVaR (95%)*: 5th percentile of per-bet net (linear
  interpolation), and the mean of nets at or below it.
- *tail ratio*: |p95(net)| / |p5(net)|.
- *outlier win (loss) ratio*: p99(net) / mean positive net
  (p1(net) / mean negative net).
- *ulcer index*: root-mean-square percent drawdown over the per-bet
  equity curve (percent of running equity peak).
- *equity curve*: starting bankroll + cumulative bet net — cash flows
  backed out, matching the session's own drawdown convention.

Public API
----------

``compute_metrics(session, analytics=None)``
    Every number in the report, as a JSON-friendly nested dict — the
    testable core.
``generate_report(session, analytics=None, sizing=None, *, title=...,
output_path=None)``
    The full HTML document as a string (optionally written to disk).
"""

from __future__ import annotations

import base64
import html as _html
import io
import math
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence

import numpy as np

import matplotlib

matplotlib.use("Agg")  # before pyplot: headless, deterministic
import matplotlib.pyplot as plt  # noqa: E402  (needs the Agg backend set)

__all__ = ["compute_metrics", "generate_report", "ruin_probability_diffusion"]


# ---------------------------------------------------------------------------
# palette (validated data-viz reference palette, light mode)
# ---------------------------------------------------------------------------

_C = {
    "blue": "#2a78d6",      # primary series (actual)
    "orange": "#eb6834",    # secondary series
    "aqua": "#1baf7a",      # tertiary series (luck)
    "red": "#e34948",       # negative / serious status
    "green": "#008300",     # good status
    "gray": "#8d8c86",      # expectation / de-emphasis
    "grid": "#e8e7e4",      # hairline grid
    "ink": "#0b0b0b",       # primary text
    "ink2": "#52514e",      # secondary text
    "surface": "#ffffff",
}

_FIG_W = 6.9          # inches; left column plots
_DPI = 150


# ---------------------------------------------------------------------------
# small numerics
# ---------------------------------------------------------------------------

def _m(v: float, decimals: int = 0, signed: bool = True) -> str:
    """Money label for plot annotations: −$320 / +$15."""
    sign = "+" if signed and v > 0 else ("−" if v < 0 else "")
    return f"{sign}${abs(v):,.{decimals}f}"


def _norm_cdf(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def _norm_logcdf(x: float) -> float:
    """log Phi(x), stable in the deep left tail."""
    if x > -8.0:
        return math.log(_norm_cdf(x))
    # asymptotic: Phi(x) ~ phi(x) / |x| for x << 0
    return -0.5 * x * x - math.log(-x) - 0.5 * math.log(2.0 * math.pi)


def ruin_probability_diffusion(
    bankroll: float, bet: float, edge: float, var_per_unit: float, n_bets: int
) -> float:
    """P(cumulative net P&L hits ``-bankroll`` within ``n_bets`` flat bets).

    Normal (drifted-Brownian) first-passage approximation via the classic
    reflection formula: with per-bet drift ``mu = -edge * bet`` and per-bet
    std ``sigma = sqrt(var_per_unit) * bet``,

        P(ruin <= N) = Phi((-B - mu N) / (sigma sqrt(N)))
                     + exp(-2 mu B / sigma^2) * Phi((-B + mu N) / (sigma sqrt(N)))

    Same formula the selector's survival column uses; it is an
    APPROXIMATION — coarse for heavy-tailed payout distributions — and is
    labeled as such wherever it is reported.  The exponential term is
    evaluated in log space so a large positive exponent cannot overflow.
    """
    if bankroll <= 0:
        return 1.0
    if n_bets <= 0:
        return 0.0
    if bet <= 0:
        raise ValueError("bet must be > 0")
    mu = -edge * bet
    sigma = math.sqrt(max(var_per_unit, 0.0)) * bet
    b = float(bankroll)
    n = float(n_bets)
    if sigma == 0.0:
        return 1.0 if mu * n <= -b else 0.0
    sqn = sigma * math.sqrt(n)
    term1 = _norm_cdf((-b - mu * n) / sqn)
    log_amp = -2.0 * mu * b / (sigma * sigma)
    log_term2 = log_amp + _norm_logcdf((-b + mu * n) / sqn)
    term2 = math.exp(log_term2) if log_term2 < 0 else 1.0
    return min(1.0, max(0.0, term1 + term2))


def _skew_kurtosis(x: np.ndarray) -> tuple:
    """Population skewness and EXCESS kurtosis (normal -> 0, 0)."""
    x = np.asarray(x, dtype=np.float64)
    m = x.mean()
    d = x - m
    m2 = float(np.mean(d * d))
    if m2 <= 0:
        return 0.0, 0.0
    m3 = float(np.mean(d**3))
    m4 = float(np.mean(d**4))
    return m3 / m2**1.5, m4 / (m2 * m2) - 3.0


def _max_run(mask: np.ndarray) -> int:
    """Longest run of consecutive True values."""
    best = cur = 0
    for v in mask:
        cur = cur + 1 if v else 0
        if cur > best:
            best = cur
    return best


def _parse_ts(ts: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# analytics specs
# ---------------------------------------------------------------------------

def _analytic_spec(obj: Any) -> Dict[str, float]:
    """Normalize an engine object or mapping to {rtp, var_per_unit}."""
    if isinstance(obj, Mapping):
        get = obj.get
    else:
        def get(name, default=None):
            return getattr(obj, name, default)
    rtp = get("rtp")
    if rtp is None:
        raise ValueError("analytics entry must provide 'rtp'")
    rtp = float(rtp)
    var = get("variance_per_unit")
    if var is None:
        std = get("std_per_unit")
        if std is None:
            raise ValueError(
                "analytics entry must provide 'variance_per_unit' or "
                "'std_per_unit'"
            )
        var = float(std) ** 2
    else:
        var = float(var)
    if var < 0:
        raise ValueError(f"variance_per_unit must be >= 0, got {var}")
    return {"rtp": rtp, "var_per_unit": var}


# ---------------------------------------------------------------------------
# metric computation (the testable core)
# ---------------------------------------------------------------------------

def compute_metrics(
    session: Any, analytics: Optional[Mapping[str, Any]] = None
) -> Dict[str, Any]:
    """Every number in the report, recomputed from the session ledger.

    See the module docstring for definitions.  Raises ``ValueError`` for a
    session with no recorded bets (there is nothing to report on).
    """
    bets = session.bets
    if not bets:
        raise ValueError("cannot report on a session with no recorded bets")
    specs: Dict[str, Dict[str, float]] = {}
    if analytics:
        for name, obj in analytics.items():
            specs[name] = _analytic_spec(obj)

    n = len(bets)
    stake = np.array([float(b.stake) for b in bets])
    payout = np.array([float(b.payout) for b in bets])
    net = np.array([float(b.net) for b in bets])
    games = [b.game for b in bets]
    seqs = [b.seq for b in bets]

    # exact-Decimal ledger totals (source of truth for money headlines)
    starting = float(session.starting_bankroll)
    final = float(session.bankroll)
    pnl = float(session.pnl)
    handle = float(session.total_staked)
    returned = float(session.total_returned)
    peak = float(session.peak_bankroll)
    summary = session.summary()

    # --- expectation decomposition ------------------------------------
    covered = np.array([g in specs for g in games])
    rtp_arr = np.array([specs[g]["rtp"] if g in specs else np.nan for g in games])
    var_arr = np.array(
        [specs[g]["var_per_unit"] if g in specs else np.nan for g in games]
    )
    cov_stake = stake[covered]
    cov_net = net[covered]
    n_cov = int(covered.sum())
    coverage_bets = n_cov / n
    coverage_handle = float(cov_stake.sum() / stake.sum()) if handle else 0.0
    full_coverage = bool(covered.all()) and bool(specs)

    performance: Dict[str, Any] = {
        "realized_rtp": returned / handle if handle else float("nan"),
        "realized_edge": 1.0 - returned / handle if handle else float("nan"),
        "coverage_bets_frac": coverage_bets,
        "coverage_handle_frac": coverage_handle,
        "full_coverage": full_coverage,
    }
    if n_cov:
        exp_net_i = cov_stake * (rtp_arr[covered] - 1.0)
        var_i = cov_stake**2 * var_arr[covered]
        exp_pnl = float(exp_net_i.sum())
        sd_pnl = float(math.sqrt(var_i.sum()))
        cov_handle = float(cov_stake.sum())
        cov_actual = float(cov_net.sum())
        luck = cov_actual - exp_pnl
        z = luck / sd_pnl if sd_pnl > 0 else float("nan")
        performance.update({
            # expectation figures are over the COVERED bets
            "covered_handle": cov_handle,
            "covered_pnl": cov_actual,
            "expected_rtp": 1.0 + exp_pnl / cov_handle if cov_handle else float("nan"),
            "expected_edge": -exp_pnl / cov_handle if cov_handle else float("nan"),
            "expected_pnl": exp_pnl,
            "expected_loss": -exp_pnl,
            "luck_dollars": luck,
            "sd_pnl": sd_pnl,
            "luck_z": z,
            "luck_p_two_sided": (
                2.0 * _norm_cdf(-abs(z)) if math.isfinite(z) else float("nan")
            ),
            "rtp_se": sd_pnl / cov_handle if cov_handle else float("nan"),
            "covered_realized_rtp": (
                float(payout[covered].sum()) / cov_handle
                if cov_handle else float("nan")
            ),
        })
    else:
        performance.update({
            "covered_handle": 0.0, "covered_pnl": 0.0,
            "expected_rtp": None, "expected_edge": None,
            "expected_pnl": None, "expected_loss": None,
            "luck_dollars": None, "sd_pnl": None, "luck_z": None,
            "luck_p_two_sided": None, "rtp_se": None,
            "covered_realized_rtp": None,
        })

    # --- distribution of per-bet results ------------------------------
    wins = payout > stake
    pushes = payout == stake
    losses = payout < stake
    pos = net[net > 0]
    neg = net[net < 0]
    gross_win = float(pos.sum())
    gross_loss = float(-neg.sum())
    var95 = float(np.percentile(net, 5))
    cvar95 = float(net[net <= var95].mean()) if (net <= var95).any() else var95
    p95 = float(np.percentile(net, 95))
    skew, kurt = _skew_kurtosis(net)
    i_best = int(np.argmax(net))
    i_worst = int(np.argmin(net))
    distribution = {
        "win_rate": float(wins.mean()),
        "push_rate": float(pushes.mean()),
        "loss_rate": float(losses.mean()),
        "n_wins": int(wins.sum()),
        "n_pushes": int(pushes.sum()),
        "n_losses": int(losses.sum()),
        "avg_net_per_bet": float(net.mean()),
        "avg_win": float(pos.mean()) if pos.size else 0.0,
        "avg_loss": float(neg.mean()) if neg.size else 0.0,
        "payoff_ratio": (
            float(pos.mean() / -neg.mean()) if pos.size and neg.size else float("nan")
        ),
        "profit_factor": (
            gross_win / gross_loss if gross_loss > 0 else float("inf")
        ),
        "gross_win": gross_win,
        "gross_loss": gross_loss,
        "best_bet_net": float(net[i_best]),
        "best_bet_seq": seqs[i_best],
        "best_bet_game": games[i_best],
        "worst_bet_net": float(net[i_worst]),
        "worst_bet_seq": seqs[i_worst],
        "worst_bet_game": games[i_worst],
        "max_multiplier_hit": float(max(float(b.multiplier) for b in bets)),
        "std_net_per_bet": float(net.std()),
        "skew": skew,
        "kurtosis_excess": kurt,
        "var95": var95,
        "cvar95": cvar95,
        "tail_ratio": abs(p95) / abs(var95) if var95 != 0 else float("inf"),
        "outlier_win_ratio": (
            float(np.percentile(net, 99) / pos.mean()) if pos.size else float("nan")
        ),
        "outlier_loss_ratio": (
            float(np.percentile(net, 1) / neg.mean()) if neg.size else float("nan")
        ),
        "max_consecutive_wins": _max_run(net > 0),
        "max_consecutive_losses": _max_run(net < 0),
    }

    # --- equity curve / drawdown ---------------------------------------
    equity = starting + np.cumsum(net)
    run_peak = np.maximum.accumulate(np.maximum(equity, starting))
    dd_frac = (run_peak - equity) / run_peak
    ulcer = float(math.sqrt(np.mean(dd_frac**2)))
    dd = dict(summary["drawdown"])
    max_dd = float(session.max_drawdown)
    drawdown = {
        "max_dd": max_dd,
        "max_dd_pct": float(session.max_drawdown_pct),
        "longest_bets": dd["longest_bets"],
        "longest_days": dd["longest_days"],
        "episode_count": dd["count"],
        "avg_pct": dd["avg_pct_value"],
        "avg_days": dd["avg_days"],
        "worst": dd["worst"],
        "max_info": dd["max"],
        "max_pct_info": dd["max_pct"],
        "ulcer_index": ulcer,
        "recovery_factor": pnl / max_dd if max_dd > 0 else float("nan"),
        "current_dd": float(run_peak[-1] - equity[-1]),
        "current_dd_pct": float(dd_frac[-1]),
        "underwater_now": bool(equity[-1] < run_peak[-1]),
    }

    # --- pacing ----------------------------------------------------------
    t0 = _parse_ts(bets[0].timestamp)
    t1 = _parse_ts(bets[-1].timestamp)
    duration_s: Optional[float] = None
    if t0 is not None and t1 is not None:
        try:
            duration_s = (t1 - t0).total_seconds()
        except TypeError:
            duration_s = None
        if duration_s is not None and duration_s < 0:
            duration_s = None
    hours = duration_s / 3600.0 if duration_s else None
    pacing = {
        "duration_seconds": duration_s,
        "bets_per_hour": n / hours if hours else None,
        "handle_per_hour": handle / hours if hours else None,
        "avg_seconds_between_bets": duration_s / (n - 1) if duration_s and n > 1 else None,
    }

    # --- wagering --------------------------------------------------------
    wagering = {
        "handle": handle,
        "total_returned": returned,
        "n_bets": n,
        "avg_stake": float(stake.mean()),
        "median_stake": float(np.median(stake)),
        "min_stake": float(stake.min()),
        "max_stake": float(stake.max()),
        "handle_x_bankroll": handle / starting if starting else float("nan"),
    }

    # --- per-game attribution -------------------------------------------
    per_game: List[Dict[str, Any]] = []
    for g in sorted(set(games)):
        m = np.array([x == g for x in games])
        g_stake = stake[m]
        g_net = net[m]
        g_payout = payout[m]
        g_handle = float(g_stake.sum())
        row: Dict[str, Any] = {
            "game": g,
            "bets": int(m.sum()),
            "handle": g_handle,
            "returned": float(g_payout.sum()),
            "net": float(g_net.sum()),
            "realized_rtp": float(g_payout.sum() / g_handle) if g_handle else float("nan"),
            "win_rate": float((g_payout > g_stake).mean()),
            "avg_stake": float(g_stake.mean()),
            "share_of_handle": g_handle / handle if handle else float("nan"),
        }
        if g in specs:
            s = specs[g]
            exp_net = float((g_stake * (s["rtp"] - 1.0)).sum())
            sd = float(math.sqrt((g_stake**2 * s["var_per_unit"]).sum()))
            luck_g = row["net"] - exp_net
            row.update({
                "analytic_rtp": s["rtp"],
                "analytic_edge": 1.0 - s["rtp"],
                "expected_net": exp_net,
                "edge_paid": -exp_net,
                "luck": luck_g,
                "sd": sd,
                "z": luck_g / sd if sd > 0 else float("nan"),
            })
        else:
            row.update({
                "analytic_rtp": None, "analytic_edge": None,
                "expected_net": None, "edge_paid": None,
                "luck": None, "sd": None, "z": None,
            })
        per_game.append(row)

    # --- risk of ruin remaining -----------------------------------------
    avg_stake = float(stake.mean())
    risk_of_ruin: Dict[str, Any]
    if n_cov and final > 0:
        blended_edge = float(
            (cov_stake * (1.0 - rtp_arr[covered])).sum() / cov_stake.sum()
        )
        blended_var = float(
            (cov_stake**2 * var_arr[covered]).sum() / (cov_stake**2).sum()
        )
        horizons = [250, 1000, 2500, 10000]
        risk_of_ruin = {
            "current_bankroll": final,
            "avg_stake": avg_stake,
            "blended_edge": blended_edge,
            "blended_var_per_unit": blended_var,
            "horizons": [
                {
                    "bets": h,
                    "p_ruin": ruin_probability_diffusion(
                        final, avg_stake, blended_edge, blended_var, h
                    ),
                }
                for h in horizons
            ],
            "expected_bets_to_exhaust": (
                final / (blended_edge * avg_stake)
                if blended_edge > 0 and avg_stake > 0 else None
            ),
            "method": (
                "normal-diffusion first-passage approximation (reflection "
                "formula) at the session's realized average stake and "
                "stake-weighted analytic edge/variance; coarse for "
                "heavy-tailed games"
            ),
        }
    else:
        risk_of_ruin = {
            "current_bankroll": final,
            "avg_stake": avg_stake,
            "blended_edge": None,
            "blended_var_per_unit": None,
            "horizons": [],
            "expected_bets_to_exhaust": None,
            "method": (
                "unavailable: bankroll exhausted or no analytic coverage"
            ),
        }

    # --- stop adherence --------------------------------------------------
    stops_cfg = summary["stops"]
    stop_seq = session.stop_seq
    after = [b for b in bets if stop_seq is not None and b.seq > stop_seq]
    stops = {
        "configured": stops_cfg,
        "any_configured": any(v is not None for v in stops_cfg.values()),
        "stopped": session.stopped,
        "stop_reason": session.stop_reason,
        "stop_seq": stop_seq,
        "bets_after_stop": len(after),
        "handle_after_stop": float(sum(float(b.stake) for b in after)),
        "net_after_stop": float(sum(float(b.net) for b in after)),
        "adhered": (not session.stopped) or not after,
    }
    if session.stopped:
        stop_bet = next((b for b in bets if b.seq == stop_seq), None)
        stops["stop_timestamp"] = stop_bet.timestamp if stop_bet else None
        stops["pnl_at_stop"] = (
            float(stop_bet.bankroll_after) - starting if stop_bet else None
        )
    else:
        stops["stop_timestamp"] = None
        stops["pnl_at_stop"] = None
        # distance to each armed stop, from the current P&L
        dist: Dict[str, float] = {}
        if session.stop_loss is not None:
            dist["stop_loss"] = pnl + float(session.stop_loss)
        if session.stop_loss_pct is not None:
            dist["stop_loss_pct"] = pnl + starting * float(session.stop_loss_pct)
        if session.stop_win is not None:
            dist["stop_win"] = float(session.stop_win) - pnl
        if session.stop_win_pct is not None:
            dist["stop_win_pct"] = starting * float(session.stop_win_pct) - pnl
        stops["distance_to_stops"] = dist

    meta = {
        "session_id": session.session_id,
        "started_at": session.started_at,
        "first_bet_at": bets[0].timestamp,
        "last_bet_at": bets[-1].timestamp,
        "n_bets": n,
        "n_games": len(set(games)),
        "games": sorted(set(games)),
        "timestamp_anomalies": session.timestamp_anomalies,
        "total_deposited": float(session.total_deposited),
        "total_withdrawn": float(session.total_withdrawn),
    }
    bankroll = {
        "starting": starting,
        "final": final,
        "peak": peak,
        "pnl": pnl,
        "pnl_pct_of_start": pnl / starting if starting else float("nan"),
    }
    return {
        "meta": meta,
        "bankroll": bankroll,
        "wagering": wagering,
        "pacing": pacing,
        "performance": performance,
        "distribution": distribution,
        "drawdown": drawdown,
        "per_game": per_game,
        "risk_of_ruin": risk_of_ruin,
        "stops": stops,
    }


# ---------------------------------------------------------------------------
# plotting
# ---------------------------------------------------------------------------

def _style_ax(ax, title: str) -> None:
    ax.set_facecolor(_C["surface"])
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(_C["grid"])
    ax.tick_params(colors=_C["ink2"], labelsize=8, length=3)
    ax.grid(True, color=_C["grid"], linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_title(title, loc="left", fontsize=10.5, fontweight="bold",
                 color=_C["ink"], pad=10)


def _fig_to_datauri(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=_DPI, bbox_inches="tight",
                facecolor=_C["surface"])
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _new_fig(height: float = 2.9):
    fig, ax = plt.subplots(figsize=(_FIG_W, height))
    fig.patch.set_facecolor(_C["surface"])
    return fig, ax


def _plot_bankroll(session, metrics, exp_path, band) -> str:
    bets = session.bets
    net = np.array([float(b.net) for b in bets])
    starting = float(session.starting_bankroll)
    equity = np.concatenate(([starting], starting + np.cumsum(net)))
    x = np.arange(len(equity))
    fig, ax = _new_fig(3.3)
    _style_ax(ax, "Bankroll (equity curve) vs analytic expectation")
    if exp_path is not None:
        lo = exp_path - band
        hi = exp_path + band
        ax.fill_between(x, lo, hi, color=_C["gray"], alpha=0.12, linewidth=0,
                        label="expected ± 1.96 SE")
        ax.plot(x, exp_path, color=_C["gray"], linewidth=1.6,
                linestyle=(0, (4, 3)), label="expected path")
    ax.plot(x, equity, color=_C["blue"], linewidth=2, solid_joinstyle="round",
            label="actual bankroll")
    ax.axhline(starting, color=_C["grid"], linewidth=1)
    st = metrics["stops"]["configured"]
    if st.get("stop_loss") is not None:
        y = starting - float(st["stop_loss"])
        ax.axhline(y, color=_C["red"], linewidth=1.2, linestyle=(0, (2, 2)))
        ax.annotate("stop-loss", (x[-1], y), fontsize=8, color=_C["ink2"],
                    xytext=(-2, 4), textcoords="offset points", ha="right")
    if st.get("stop_win") is not None:
        y = starting + float(st["stop_win"])
        ax.axhline(y, color=_C["green"], linewidth=1.2, linestyle=(0, (2, 2)))
        ax.annotate("stop-win", (x[-1], y), fontsize=8, color=_C["ink2"],
                    xytext=(-2, 4), textcoords="offset points", ha="right")
    if session.stopped and session.stop_seq is not None:
        idx = next((i + 1 for i, b in enumerate(bets)
                    if b.seq == session.stop_seq), None)
        if idx is not None:
            ax.plot([idx], [equity[idx]], "o", markersize=7, color=_C["red"],
                    markeredgecolor=_C["surface"], markeredgewidth=2, zorder=5)
            ax.annotate(f"{session.stop_reason} latched", (idx, equity[idx]),
                        fontsize=8, color=_C["ink2"], xytext=(6, -12),
                        textcoords="offset points")
    ax.set_xlabel("bet #", fontsize=8, color=_C["ink2"])
    ax.set_ylabel("$", fontsize=8, color=_C["ink2"])
    ax.legend(loc="best", fontsize=8, frameon=False)
    return _fig_to_datauri(fig)


def _plot_underwater(session) -> str:
    net = np.array([float(b.net) for b in session.bets])
    starting = float(session.starting_bankroll)
    equity = np.concatenate(([starting], starting + np.cumsum(net)))
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak * 100.0
    x = np.arange(len(equity))
    fig, ax = _new_fig(2.2)
    _style_ax(ax, "Underwater plot (drawdown, % of equity peak)")
    ax.fill_between(x, dd, 0, color=_C["red"], alpha=0.12, linewidth=0)
    ax.plot(x, dd, color=_C["red"], linewidth=1.6)
    i = int(np.argmin(dd))
    ax.plot([x[i]], [dd[i]], "o", markersize=6, color=_C["red"],
            markeredgecolor=_C["surface"], markeredgewidth=2)
    ax.annotate(f"{dd[i]:.1f}%", (x[i], dd[i]), fontsize=8, color=_C["ink2"],
                xytext=(6, -4), textcoords="offset points")
    ax.set_xlabel("bet #", fontsize=8, color=_C["ink2"])
    ax.set_ylim(top=max(1.0, float(dd.max()) + 0.5))
    return _fig_to_datauri(fig)


def _plot_luck(session, exp_path, band) -> str:
    net = np.array([float(b.net) for b in session.bets])
    starting = float(session.starting_bankroll)
    equity = np.concatenate(([starting], starting + np.cumsum(net)))
    luck = equity - exp_path
    x = np.arange(len(equity))
    fig, ax = _new_fig(2.6)
    _style_ax(ax, "Cumulative luck: actual minus expected P&L, with 95% band")
    ax.fill_between(x, -band, band, color=_C["gray"], alpha=0.12, linewidth=0,
                    label="± 1.96 SE (zero-luck band)")
    ax.axhline(0, color=_C["grid"], linewidth=1)
    ax.plot(x, luck, color=_C["aqua"], linewidth=2, label="luck ($)")
    ax.plot([x[-1]], [luck[-1]], "o", markersize=6, color=_C["aqua"],
            markeredgecolor=_C["surface"], markeredgewidth=2)
    ax.annotate(_m(luck[-1]), (x[-1], luck[-1]), fontsize=8.5,
                color=_C["ink2"], xytext=(-4, 6), textcoords="offset points",
                ha="right")
    ax.set_xlabel("bet #", fontsize=8, color=_C["ink2"])
    ax.set_ylabel("$", fontsize=8, color=_C["ink2"])
    ax.legend(loc="best", fontsize=8, frameon=False)
    return _fig_to_datauri(fig)


def _plot_rolling_rtp(session, specs, window: int) -> str:
    bets = session.bets
    stake = np.array([float(b.stake) for b in bets])
    payout = np.array([float(b.payout) for b in bets])
    rtp_a = np.array([specs[b.game]["rtp"] for b in bets])
    var_a = np.array([specs[b.game]["var_per_unit"] for b in bets])
    k = np.ones(window)
    rstake = np.convolve(stake, k, mode="valid")
    rret = np.convolve(payout, k, mode="valid")
    rexp = np.convolve(stake * rtp_a, k, mode="valid")
    rvar = np.convolve(stake**2 * var_a, k, mode="valid")
    x = np.arange(window, window + rstake.size)
    realized = rret / rstake
    expected = rexp / rstake
    se = np.sqrt(rvar) / rstake
    fig, ax = _new_fig(2.6)
    _style_ax(ax, f"Rolling realized RTP ({window}-bet window) vs analytic expectation")
    ax.fill_between(x, expected - 1.96 * se, expected + 1.96 * se,
                    color=_C["gray"], alpha=0.12, linewidth=0,
                    label="expected ± 1.96 SE")
    ax.plot(x, expected, color=_C["gray"], linewidth=1.6,
            linestyle=(0, (4, 3)), label="expected RTP")
    ax.plot(x, realized, color=_C["blue"], linewidth=2, label="realized RTP")
    ax.axhline(1.0, color=_C["grid"], linewidth=1)
    ax.set_xlabel("bet #", fontsize=8, color=_C["ink2"])
    ax.legend(loc="best", fontsize=8, frameon=False)
    return _fig_to_datauri(fig)


def _plot_attribution(per_game) -> str:
    rows = sorted(per_game, key=lambda r: r["net"])
    names = [r["game"] for r in rows]
    nets = [r["net"] for r in rows]
    y = np.arange(len(rows))
    fig, ax = _new_fig(max(2.2, 0.44 * len(rows) + 0.9))
    _style_ax(ax, "Per-game attribution: net P&L vs expected, ± 1.96 SE")
    colors = [_C["blue"] if v >= 0 else _C["red"] for v in nets]
    ax.barh(y, nets, height=0.55, color=colors, zorder=3)
    spans = []  # leftmost/rightmost ink per row, for label placement
    for i, r in enumerate(rows):
        lo = min(0.0, r["net"])
        hi = max(0.0, r["net"])
        if r["expected_net"] is not None:
            ax.errorbar([r["expected_net"]], [i], xerr=[1.96 * r["sd"]],
                        fmt="none", ecolor=_C["ink2"], elinewidth=1.2,
                        capsize=3, zorder=4)
            ax.plot([r["expected_net"]], [i], marker="|", markersize=11,
                    color=_C["ink"], zorder=5)
            lo = min(lo, r["expected_net"] - 1.96 * r["sd"])
            hi = max(hi, r["expected_net"] + 1.96 * r["sd"])
        spans.append((lo, hi))
    for i, r in enumerate(rows):
        lo, hi = spans[i]
        neg = r["net"] < 0
        ax.annotate(_m(r["net"]), (lo if neg else hi, i), fontsize=8,
                    color=_C["ink2"], zorder=6,
                    xytext=(-6 if neg else 6, -3), textcoords="offset points",
                    ha="right" if neg else "left")
    ax.axvline(0, color=_C["grid"], linewidth=1)
    ax.set_yticks(y, names, fontsize=8.5)
    ax.set_xlabel("net P&L ($); tick + whisker = analytic expectation band",
                  fontsize=8, color=_C["ink2"])
    m = max(max(abs(lo), abs(hi)) for lo, hi in spans) or 1.0
    ax.set_xlim(-1.3 * m, 1.3 * m)
    return _fig_to_datauri(fig)


def _plot_net_hist(metrics, session) -> str:
    net = np.array([float(b.net) for b in session.bets])
    fig, ax = _new_fig(2.6)
    _style_ax(ax, "Distribution of per-bet net result (log count)")
    lo, hi = float(net.min()), float(net.max())
    span = hi - lo or 1.0
    bins = np.linspace(lo - 0.02 * span, hi + 0.02 * span, 45)
    ax.hist(net, bins=bins, color=_C["blue"], alpha=0.85, log=True,
            rwidth=0.92, zorder=3)
    var95 = metrics["distribution"]["var95"]
    cvar95 = metrics["distribution"]["cvar95"]
    ymax = ax.get_ylim()[1]
    ax.axvline(var95, color=_C["red"], linewidth=1.4, linestyle=(0, (2, 2)),
               zorder=4)
    if abs(cvar95 - var95) < 1e-9:
        ax.annotate(f"VaR = CVaR 95%: {_m(var95, 2, signed=False)}",
                    (var95, ymax), fontsize=8, color=_C["ink2"],
                    xytext=(6, -12), textcoords="offset points", zorder=5)
    else:
        ax.annotate(f"VaR 95% {_m(var95, 2, signed=False)}", (var95, ymax),
                    fontsize=8, color=_C["ink2"], xytext=(6, -12),
                    textcoords="offset points", zorder=5)
        ax.axvline(cvar95, color=_C["red"], linewidth=1.4, zorder=4)
        ax.annotate(f"CVaR {_m(cvar95, 2, signed=False)}", (cvar95, ymax),
                    fontsize=8, color=_C["ink2"], xytext=(6, -26),
                    textcoords="offset points", zorder=5)
    ax.set_xlabel("net per bet ($)", fontsize=8, color=_C["ink2"])
    return _fig_to_datauri(fig)


def _plot_ruin(metrics) -> str:
    ror = metrics["risk_of_ruin"]
    if not ror["horizons"]:
        return ""
    bankroll = ror["current_bankroll"]
    edge = ror["blended_edge"]
    var = ror["blended_var_per_unit"]
    base = ror["avg_stake"]
    n_max = 10000
    ns = np.unique(np.geomspace(10, n_max, 60).astype(int))
    fig, ax = _new_fig(2.6)
    _style_ax(ax, "Risk of ruin remaining: P(bust current bankroll within N bets)")
    stakes = [(0.5, _C["aqua"]), (1.0, _C["blue"]), (2.0, _C["orange"])]
    for mult, color in stakes:
        b = base * mult
        p = [ruin_probability_diffusion(bankroll, b, edge, var, int(t))
             for t in ns]
        label = f"stake ${b:,.2f} ({mult:g}× session avg)"
        ax.plot(ns, p, color=color, linewidth=2, label=label)
    ax.set_xscale("log")
    ax.set_xlabel("future bets (log scale)", fontsize=8, color=_C["ink2"])
    ax.set_ylabel("P(ruin)", fontsize=8, color=_C["ink2"])
    ax.set_ylim(-0.02, 1.02)
    ax.legend(loc="best", fontsize=8, frameon=False)
    return _fig_to_datauri(fig)


def _build_plots(session, metrics, analytics) -> Dict[str, str]:
    specs = {k: _analytic_spec(v) for k, v in (analytics or {}).items()}
    full = metrics["performance"]["full_coverage"]
    exp_path = band = None
    if full:
        bets = session.bets
        stake = np.array([float(b.stake) for b in bets])
        rtp_a = np.array([specs[b.game]["rtp"] for b in bets])
        var_a = np.array([specs[b.game]["var_per_unit"] for b in bets])
        starting = float(session.starting_bankroll)
        exp_path = np.concatenate(
            ([starting], starting + np.cumsum(stake * (rtp_a - 1.0)))
        )
        band = 1.96 * np.sqrt(np.concatenate(
            ([0.0], np.cumsum(stake**2 * var_a))
        ))
    plots = {
        "bankroll": _plot_bankroll(session, metrics, exp_path, band),
        "underwater": _plot_underwater(session),
        "net_hist": _plot_net_hist(metrics, session),
        "attribution": _plot_attribution(metrics["per_game"]),
        "ruin": _plot_ruin(metrics),
    }
    if full:
        plots["luck"] = _plot_luck(session, exp_path, band)
        n = len(session.bets)
        window = max(10, min(250, n // 4))
        if n >= 2 * window:
            plots["rolling_rtp"] = _plot_rolling_rtp(session, specs, window)
    return plots


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def _esc(x: Any) -> str:
    return _html.escape(str(x))


def _money(v: Optional[float], signed: bool = False, decimals: int = 2) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    sign = "+" if signed and v > 0 else ("−" if v < 0 else "")
    return f"{sign}${abs(v):,.{decimals}f}"


def _pct(v: Optional[float], decimals: int = 2, signed: bool = False) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    sign = "+" if signed and v > 0 else ("−" if v < 0 else "")
    return f"{sign}{abs(v) * 100:,.{decimals}f}%"


def _num(v: Optional[float], decimals: int = 2) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    return f"{v:,.{decimals}f}"


def _dur(seconds: Optional[float]) -> str:
    if not seconds:
        return "—"
    h, rem = divmod(int(round(seconds)), 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m {s:02d}s"


def _fmt_range(first: str, last: str) -> str:
    """Human date range for the header; falls back to the raw strings."""
    a, b = _parse_ts(first), _parse_ts(last)
    if a is None or b is None:
        return f"{_esc(first)} → {_esc(last)}"
    if a.date() == b.date():
        return (f"{a.strftime('%d %b %Y')}, {a.strftime('%H:%M')}"
                f"–{b.strftime('%H:%M')}")
    return (f"{a.strftime('%d %b %Y %H:%M')} → "
            f"{b.strftime('%d %b %Y %H:%M')}")


def _tr(label: str, *cells: str, cls: str = "") -> str:
    tds = "".join(f"<td>{c}</td>" for c in cells)
    klass = f' class="{cls}"' if cls else ""
    return f"<tr{klass}><td>{_esc(label)}</td>{tds}</tr>"


def _sec_row(label: str, n_cells: int) -> str:
    return (f'<tr class="sec"><td colspan="{n_cells + 1}">'
            f"{_esc(label)}</td></tr>")


def _pill(text: str, kind: str) -> str:
    return f'<span class="pill pill-{kind}">{_esc(text)}</span>'


def _key_metrics_table(m: Dict[str, Any]) -> str:
    """The right-column Key Metrics table: Expected vs Realized."""
    perf, dist, dd, bank, wag, pac = (
        m["performance"], m["distribution"], m["drawdown"], m["bankroll"],
        m["wagering"], m["pacing"],
    )
    has_exp = perf["expected_rtp"] is not None
    E = lambda v: v if has_exp else None  # noqa: E731
    rows: List[str] = []
    r = rows.append
    r(_sec_row("Bankroll", 2))
    r(_tr("Starting bankroll", "", _money(bank["starting"])))
    r(_tr("Final bankroll", "", _money(bank["final"])))
    r(_tr("Peak bankroll (equity)", "", _money(bank["peak"])))
    r(_tr("Net P&L", _money(E(perf.get("expected_pnl")), signed=True),
          _money(bank["pnl"], signed=True)))
    r(_tr("P&L, % of start",
          _pct(E(perf.get("expected_pnl", 0) / bank["starting"])
               if has_exp else None, signed=True),
          _pct(bank["pnl_pct_of_start"], signed=True)))
    r(_sec_row("House edge", 2))
    r(_tr("RTP (return to player)", _pct(perf.get("expected_rtp")),
          _pct(perf["realized_rtp"])))
    r(_tr("House edge", _pct(perf.get("expected_edge")),
          _pct(perf["realized_edge"])))
    r(_tr("RTP standard error", _pct(perf.get("rtp_se")), ""))
    r(_tr("Luck (P&L − expected)", "",
          _money(perf.get("luck_dollars"), signed=True)))
    r(_tr("Luck z-score", "", _num(perf.get("luck_z"))))
    r(_tr("Two-sided p-value", "", _num(perf.get("luck_p_two_sided"), 3)))
    r(_sec_row("Wagering", 2))
    r(_tr("Bets", "", f"{wag['n_bets']:,}"))
    r(_tr("Handle (total staked)", "", _money(wag["handle"])))
    r(_tr("Total returned", "", _money(wag["total_returned"])))
    r(_tr("Handle ÷ bankroll", "", _num(wag["handle_x_bankroll"], 1) + "×"))
    r(_tr("Avg / median stake",
          "", f"{_money(wag['avg_stake'])} / {_money(wag['median_stake'])}"))
    r(_tr("Session length", "", _dur(pac["duration_seconds"])))
    r(_tr("Bets per hour", "", _num(pac["bets_per_hour"], 0)))
    r(_tr("Handle per hour", "", _money(pac["handle_per_hour"], decimals=0)))
    r(_sec_row("Per-bet distribution", 2))
    r(_tr("Win / push / loss",
          "", f"{_pct(dist['win_rate'], 1)} / {_pct(dist['push_rate'], 1)}"
              f" / {_pct(dist['loss_rate'], 1)}"))
    r(_tr("Avg win / avg loss",
          "", f"{_money(dist['avg_win'])} / {_money(dist['avg_loss'])}"))
    r(_tr("Payoff ratio", "", _num(dist["payoff_ratio"])))
    r(_tr("Profit factor", "", _num(dist["profit_factor"])))
    r(_tr("Best bet", "",
          f"{_money(dist['best_bet_net'], signed=True)}"
          f" <small>({_esc(dist['best_bet_game'])})</small>"))
    r(_tr("Worst bet", "",
          f"{_money(dist['worst_bet_net'], signed=True)}"
          f" <small>({_esc(dist['worst_bet_game'])})</small>"))
    r(_tr("Max multiplier hit", "", _num(dist["max_multiplier_hit"]) + "×"))
    r(_tr("Max consecutive wins", "", f"{dist['max_consecutive_wins']}"))
    r(_tr("Max consecutive losses", "", f"{dist['max_consecutive_losses']}"))
    r(_tr("Std of net per bet", "", _money(dist["std_net_per_bet"])))
    r(_tr("Skew / excess kurtosis",
          "", f"{_num(dist['skew'])} / {_num(dist['kurtosis_excess'], 1)}"))
    r(_tr("VaR 95% (per bet)", "", _money(dist["var95"])))
    r(_tr("CVaR 95% (per bet)", "", _money(dist["cvar95"])))
    r(_tr("Tail ratio", "", _num(dist["tail_ratio"])))
    r(_tr("Outlier win / loss ratio",
          "", f"{_num(dist['outlier_win_ratio'], 1)} / "
              f"{_num(dist['outlier_loss_ratio'], 1)}"))
    r(_sec_row("Drawdown", 2))
    r(_tr("Max drawdown", "", _money(dd["max_dd"])))
    r(_tr("Max drawdown %", "", _pct(dd["max_dd_pct"])))
    r(_tr("Longest drawdown (bets)", "", f"{dd['longest_bets']:,}"))
    if dd["longest_days"] is not None:
        r(_tr("Longest drawdown (time)", "",
              _dur(dd["longest_days"] * 86400.0)))
    r(_tr("Drawdown episodes", "", f"{dd['episode_count']:,}"))
    r(_tr("Avg episode depth", "", _pct(dd["avg_pct"])))
    r(_tr("Ulcer index", "", _num(dd["ulcer_index"], 4)))
    r(_tr("Recovery factor", "", _num(dd["recovery_factor"])))
    r(_tr("Current drawdown", "",
          f"{_money(dd['current_dd'])} ({_pct(dd['current_dd_pct'])})"))
    r(_sec_row("Kelly & ruin", 2))
    r(_tr("Kelly fraction", "", "0 (negative EV: optimal stake is not playing)"))
    ror = m["risk_of_ruin"]
    for h in ror["horizons"]:
        r(_tr(f"P(ruin within {h['bets']:,} bets)", "", _pct(h["p_ruin"])))
    if ror["expected_bets_to_exhaust"]:
        r(_tr("Bets to exhaust bankroll at EV",
              "", _num(ror["expected_bets_to_exhaust"], 0)))
    return (
        '<table class="metrics"><thead><tr><th>Metric</th>'
        "<th>Expected</th><th>Realized</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table>"
    )


def _per_game_table(per_game: List[Dict[str, Any]]) -> str:
    head = ("<thead><tr><th>Game</th><th>Bets</th><th>Handle</th>"
            "<th>Net</th><th>RTP real.</th><th>RTP analytic</th>"
            "<th>Edge paid</th><th>Luck</th><th>z</th></tr></thead>")
    body = []
    for r in sorted(per_game, key=lambda x: -x["handle"]):
        body.append(
            "<tr>"
            f"<td>{_esc(r['game'])}</td>"
            f"<td>{r['bets']:,}</td>"
            f"<td>{_money(r['handle'], decimals=0)}</td>"
            f"<td>{_money(r['net'], signed=True)}</td>"
            f"<td>{_pct(r['realized_rtp'])}</td>"
            f"<td>{_pct(r['analytic_rtp'])}</td>"
            f"<td>{_money(r['edge_paid'])}</td>"
            f"<td>{_money(r['luck'], signed=True)}</td>"
            f"<td>{_num(r['z'])}</td>"
            "</tr>"
        )
    tot_handle = sum(r["handle"] for r in per_game)
    tot_net = sum(r["net"] for r in per_game)
    tot_bets = sum(r["bets"] for r in per_game)
    covered = [r for r in per_game if r["expected_net"] is not None]
    tot_edge = sum(r["edge_paid"] for r in covered) if covered else None
    tot_luck = sum(r["luck"] for r in covered) if covered else None
    body.append(
        '<tr class="total">'
        f"<td>Total</td><td>{tot_bets:,}</td>"
        f"<td>{_money(tot_handle, decimals=0)}</td>"
        f"<td>{_money(tot_net, signed=True)}</td><td></td><td></td>"
        f"<td>{_money(tot_edge)}</td>"
        f"<td>{_money(tot_luck, signed=True)}</td><td></td></tr>"
    )
    return f'<table class="wide">{head}<tbody>{"".join(body)}</tbody></table>'


def _drawdown_table(dd: Dict[str, Any]) -> str:
    head = ("<thead><tr><th>#</th><th>Started</th><th>Trough</th>"
            "<th>Ended</th><th>Depth</th><th>Depth %</th><th>Bets</th>"
            "<th>Recovered</th></tr></thead>")
    rows = []
    for i, ep in enumerate(dd["worst"][:10], 1):
        rows.append(
            "<tr>"
            f"<td>{i}</td>"
            f"<td>{_esc(_short_ts(ep['start_at']))}</td>"
            f"<td>{_esc(_short_ts(ep['trough_at']))}</td>"
            f"<td>{_esc(_short_ts(ep['end_at']))}</td>"
            f"<td>{_money(float(ep['drawdown']))}</td>"
            f"<td>{_esc(ep['drawdown_pct'])}</td>"
            f"<td>{ep['bets']:,}</td>"
            f"<td>{'yes' if ep['recovered'] else 'no (open)'}</td>"
            "</tr>"
        )
    return f'<table class="wide">{head}<tbody>{"".join(rows)}</tbody></table>'


def _short_ts(ts: Optional[str]) -> str:
    if not ts:
        return "—"
    dt = _parse_ts(ts)
    return dt.strftime("%H:%M:%S") if dt else str(ts)


def _stops_panel(stops: Dict[str, Any]) -> str:
    cfg = stops["configured"]
    cfg_bits = []
    if cfg.get("stop_loss") is not None:
        cfg_bits.append(f"stop-loss ${cfg['stop_loss']}")
    if cfg.get("stop_loss_pct") is not None:
        cfg_bits.append(f"stop-loss {float(cfg['stop_loss_pct']) * 100:g}%")
    if cfg.get("stop_win") is not None:
        cfg_bits.append(f"stop-win ${cfg['stop_win']}")
    if cfg.get("stop_win_pct") is not None:
        cfg_bits.append(f"stop-win {float(cfg['stop_win_pct']) * 100:g}%")
    cfg_txt = ", ".join(cfg_bits) if cfg_bits else "none configured"
    lines = [f"<p><strong>Configured:</strong> {_esc(cfg_txt)}</p>"]
    if not stops["any_configured"]:
        lines.append("<p>No stop discipline was set for this session.</p>")
    elif not stops["stopped"]:
        lines.append(
            "<p>" + _pill("no stop triggered", "good")
            + " Neither stop level was reached.</p>"
        )
        dist = stops.get("distance_to_stops") or {}
        if dist:
            bits = ", ".join(
                f"{k.replace('_', '-')}: {_money(v)} away"
                for k, v in dist.items()
            )
            lines.append(f"<p class='fine'>Remaining headroom — {bits}.</p>")
    else:
        lines.append(
            f"<p>{_pill(str(stops['stop_reason']), 'serious')} latched at bet "
            f"seq {stops['stop_seq']}"
            + (f" ({_esc(_short_ts(stops['stop_timestamp']))})"
               if stops.get("stop_timestamp") else "")
            + f", P&L {_money(stops['pnl_at_stop'], signed=True)}.</p>"
        )
        if stops["adhered"]:
            lines.append(
                "<p>" + _pill("adhered", "good")
                + " No bets were placed after the stop latched.</p>"
            )
        else:
            lines.append(
                "<p>" + _pill("violated", "serious")
                + f" <strong>{stops['bets_after_stop']:,} bets</strong> were "
                f"placed after the stop, wagering "
                f"{_money(stops['handle_after_stop'])} for a further net of "
                f"{_money(stops['net_after_stop'], signed=True)}.</p>"
            )
    return "".join(lines)


def _sizing_table(table: Sequence[Mapping[str, Any]], cols: Sequence[tuple]) -> str:
    head = "".join(f"<th>{_esc(h)}</th>" for h, _k, _f in cols)
    rows = []
    for row in table:
        tds = []
        for _h, k, f in cols:
            tds.append(f"<td>{f(row.get(k))}</td>")
        rows.append("<tr>" + "".join(tds) + "</tr>")
    return (f'<table class="wide"><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')


def _sizing_panel(sizing: Mapping[str, Any]) -> str:
    out = []
    bet = sizing.get("bet")
    if bet:
        out.append("<h3>Bet sizing (survival-optimal)</h3>")
        out.append(
            f"<p><strong>Recommended bet: {_money(bet.get('recommended_bet'))}"
            f"</strong> — {_esc(bet.get('regime', ''))} play, goal "
            f"<em>{_esc(bet.get('goal', ''))}</em>"
            + (f", horizon {bet['n_rounds']:,} rounds" if bet.get("n_rounds") else "")
            + (f", target {_money(bet.get('target'))}" if bet.get("target") else "")
            + ".</p>"
        )
        if bet.get("recommended_bet_rule"):
            out.append(f"<p class='fine'>{_esc(bet['recommended_bet_rule'])}</p>")
        if bet.get("rationale"):
            out.append(f"<p class='fine'>{_esc(bet['rationale'])}</p>")
        table = bet.get("flat_bet_table")
        if table:
            if "p_survive" in table[0]:
                cols = [("Bet", "bet", lambda v: _money(v)),
                        ("P(survive)", "p_survive", lambda v: _pct(v)),
                        ("E[rounds played]", "expected_rounds_played",
                         lambda v: _num(v, 0)),
                        ("E[loss]", "expected_loss", lambda v: _money(v))]
            else:
                cols = [("Bet", "bet", lambda v: _money(v)),
                        ("P(reach target)", "p_reach_target", lambda v: _pct(v)),
                        ("P(ruin)", "p_ruin", lambda v: _pct(v)),
                        ("E[rounds]", "expected_rounds", lambda v: _num(v, 0)),
                        ("E[loss]", "expected_loss", lambda v: _money(v))]
            out.append(_sizing_table(table, cols))
        if bet.get("note"):
            out.append(f"<p class='fine'>{_esc(bet['note'])}</p>")
    st = sizing.get("stops")
    if st:
        out.append("<h3>Recommended stops (first-passage derived)</h3>")
        out.append(
            f"<p><strong>Stop-loss {_money(st.get('stop_loss'))}</strong>"
            + (f" (P(hit) = {_pct(st.get('p_stop_loss_hit'))})"
               if st.get("p_stop_loss_hit") is not None else "")
            + f" &nbsp;·&nbsp; <strong>Stop-win {_money(st.get('stop_win'))}"
            f"</strong>"
            + (f" (P(hit) = {_pct(st.get('p_stop_win_hit'))})"
               if st.get("p_stop_win_hit") is not None else "")
            + ".</p>"
        )
        for k in ("stop_loss_rationale", "stop_win_rationale", "note"):
            if st.get(k):
                out.append(f"<p class='fine'>{_esc(st[k])}</p>")
    return "".join(out)


_CSS = """
:root { --ink:#0b0b0b; --ink2:#52514e; --ink3:#8d8c86; --grid:#e8e7e4;
  --surface:#ffffff; --panel:#fafaf8; --blue:#2a78d6; --red:#e34948;
  --green:#008300; --aqua:#1baf7a; }
* { box-sizing: border-box; }
body { margin:0; background:var(--surface); color:var(--ink);
  font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI","Helvetica Neue",
  Arial,sans-serif; -webkit-font-smoothing:antialiased; }
.container { max-width:1100px; margin:0 auto; padding:36px 28px 64px; }
header h1 { font-size:26px; font-weight:700; margin:0 0 4px; letter-spacing:-0.02em; }
header .sub { color:var(--ink2); font-size:13px; margin:0 0 6px; }
header .sub b { color:var(--ink); font-weight:600; }
hr { border:0; border-top:1px solid var(--grid); margin:22px 0; }
.tiles { display:grid; grid-template-columns:repeat(6,1fr); gap:12px; margin:20px 0 8px; }
.tile { background:var(--panel); border:1px solid var(--grid); border-radius:10px;
  padding:12px 14px; }
.tile .label { font-size:11px; color:var(--ink2); letter-spacing:0.02em; }
.tile .value { font-size:21px; font-weight:600; margin-top:2px; }
.tile .delta { font-size:11.5px; color:var(--ink2); margin-top:2px; }
.pos { color:var(--green); } .negv { color:var(--red); }
.cols { display:flex; gap:26px; align-items:flex-start; }
.col-l { flex:1 1 62%; min-width:0; }
.col-r { flex:1 1 38%; min-width:0; }
.fig { margin:0 0 22px; }
.fig img { width:100%; display:block; border-radius:6px; }
.fig .cap { font-size:11.5px; color:var(--ink3); margin-top:4px; }
h2 { font-size:16px; font-weight:700; margin:26px 0 10px; letter-spacing:-0.01em; }
h3 { font-size:13.5px; font-weight:700; margin:16px 0 6px; }
table { width:100%; border-collapse:collapse; font-size:12.5px; margin:0 0 18px; }
table td, table th { padding:4px 6px; text-align:right;
  font-variant-numeric:tabular-nums; }
table td:first-child, table th:first-child { text-align:left; padding-left:2px; }
table thead th { font-weight:700; border-bottom:1.5px solid var(--ink);
  font-size:11.5px; text-transform:uppercase; letter-spacing:0.04em; }
table tbody tr { border-bottom:1px solid var(--grid); }
table tr.sec td { font-weight:700; padding-top:14px; border-bottom:1.5px solid
  var(--ink2); font-size:11.5px; text-transform:uppercase; letter-spacing:0.05em;
  color:var(--ink2); }
table tr.total td { font-weight:700; border-top:1.5px solid var(--ink);
  border-bottom:none; }
table small { color:var(--ink3); }
.pill { display:inline-block; border-radius:99px; padding:1px 9px 2px;
  font-size:11px; font-weight:600; }
.pill-good { background:#e3f2e3; color:var(--green); }
.pill-serious { background:#fdeaea; color:var(--red); }
.panel { background:var(--panel); border:1px solid var(--grid);
  border-radius:10px; padding:14px 18px; margin:0 0 18px; }
.panel p { margin:6px 0; }
.fine { font-size:11.5px; color:var(--ink3); }
footer { margin-top:34px; border-top:1px solid var(--grid); padding-top:14px; }
footer p { font-size:11.5px; color:var(--ink3); margin:4px 0; }
@media print { .container { max-width:100%; padding:0; } }
@media (max-width:900px) { .cols { flex-direction:column; }
  .tiles { grid-template-columns:repeat(3,1fr); } }
"""


def _tiles(m: Dict[str, Any]) -> str:
    bank, perf, dd, stops = (m["bankroll"], m["performance"], m["drawdown"],
                             m["stops"])
    pnl = bank["pnl"]
    pnl_cls = "pos" if pnl > 0 else ("negv" if pnl < 0 else "")
    z = perf.get("luck_z")
    ror = m["risk_of_ruin"]["horizons"]
    ror1k = next((h["p_ruin"] for h in ror if h["bets"] == 1000), None)
    if stops["stopped"]:
        stop_val = "Violated" if not stops["adhered"] else "Adhered"
        stop_cls = "negv" if not stops["adhered"] else "pos"
        stop_note = f"{stops['stop_reason']} at seq {stops['stop_seq']}"
    elif stops["any_configured"]:
        stop_val, stop_cls, stop_note = "Not hit", "", "stops stayed armed"
    else:
        stop_val, stop_cls, stop_note = "None set", "", "no stop discipline"
    tiles = [
        ("Net P&L", _money(pnl, signed=True), pnl_cls,
         _pct(bank["pnl_pct_of_start"], 1, signed=True) + " of bankroll"),
        ("Realized RTP", _pct(perf["realized_rtp"]), "",
         "expected " + _pct(perf.get("expected_rtp"))),
        ("Luck z-score", _num(z),
         "" if z is None or not math.isfinite(z)
         else ("pos" if z > 0 else "negv"),
         "luck " + _money(perf.get("luck_dollars"), signed=True)),
        ("Max drawdown", _pct(dd["max_dd_pct"], 1), "negv" if dd["max_dd_pct"] else "",
         _money(dd["max_dd"]) + " peak to trough"),
        ("P(ruin) next 1,000 bets", _pct(ror1k, 1), "",
         "at avg stake, current bankroll"),
        ("Stop discipline", stop_val, stop_cls, stop_note),
    ]
    out = []
    for label, value, cls, note in tiles:
        out.append(
            f'<div class="tile"><div class="label">{_esc(label)}</div>'
            f'<div class="value {cls}">{value}</div>'
            f'<div class="delta">{note}</div></div>'
        )
    return '<div class="tiles">' + "".join(out) + "</div>"


def generate_report(
    session: Any,
    analytics: Optional[Mapping[str, Any]] = None,
    sizing: Optional[Mapping[str, Any]] = None,
    *,
    title: str = "SpinQuest Strategy Report",
    output_path: Optional[str] = None,
) -> str:
    """Render the full self-contained HTML report; optionally write it.

    Returns the HTML string.  See the module docstring for the ``analytics``
    and ``sizing`` input contracts.
    """
    m = compute_metrics(session, analytics)
    plots = _build_plots(session, m, analytics)
    meta, perf = m["meta"], m["performance"]

    date_bits = _fmt_range(meta["first_bet_at"], meta["last_bet_at"])
    games_txt = ", ".join(meta["games"])
    cov_note = ""
    if analytics and not perf["full_coverage"]:
        cov_note = (
            f" &bull; analytic coverage {_pct(perf['coverage_handle_frac'], 1)}"
            " of handle (expectation figures cover those bets only)"
        )

    fig_order = [
        ("bankroll", "Actual equity (blue) against the analytic expected path "
                     "with a 95% (±1.96 SE) band; stop levels and the stop "
                     "latch are marked."),
        ("underwater", "Percent below the running equity peak after every bet."),
        ("luck", "The luck term of P&L = expected + luck. Leaving the gray "
                 "band means the session is outside the 95% zero-luck range."),
        ("rolling_rtp", "Stake-weighted realized RTP over a rolling window "
                        "against the analytic expectation for the same bets."),
        ("attribution", "Realized net per game (bars) against each game's "
                        "analytic expectation (tick) with a ±1.96 SE whisker."),
        ("net_hist", "Per-bet net results on a log count scale, with the "
                     "95% Value-at-Risk and expected shortfall marked."),
        ("ruin", "Diffusion (reflection-formula) approximation at the "
                 "session's stake mix — an approximation, coarse for "
                 "heavy-tailed games."),
    ]
    figs_html = []
    for key, cap in fig_order:
        uri = plots.get(key)
        if uri:
            figs_html.append(
                f'<div class="fig"><img alt="{_esc(key)}" src="{uri}">'
                f'<div class="cap">{_esc(cap)}</div></div>'
            )

    sizing_html = ""
    if sizing:
        sizing_html = (
            "<h2>Sizing &amp; stop recommendations (from the absorption "
            "math)</h2><div class='panel'>" + _sizing_panel(sizing) + "</div>"
        )

    z = perf.get("luck_z")
    if z is None or not math.isfinite(z):
        verdict = ("No analytic expectation was supplied, so the luck "
                   "decomposition is unavailable.")
    else:
        side = "above" if z > 0 else "below"
        verdict = (
            f"The session ran {_num(abs(z))} standard errors {side} the exact "
            f"analytic expectation of the games played (two-sided p = "
            f"{_num(perf['luck_p_two_sided'], 3)}). "
            + ("That is well within ordinary variance — the result is "
               "explained by the house edge plus unremarkable luck."
               if abs(z) < 1.96 else
               "That is outside the 95% band — an unusually "
               + ("lucky" if z > 0 else "unlucky") + " session.")
        )

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="container">
<header>
  <h1>{_esc(title)}</h1>
  <p class="sub"><b>{date_bits}</b> &bull; {meta['n_bets']:,} bets &bull;
  {meta['n_games']} games ({_esc(games_txt)}) &bull; session
  <code>{_esc(meta['session_id'][:12])}</code>{cov_note}</p>
  <p class="sub">{_esc(verdict)}</p>
</header>
{_tiles(m)}
<hr>
<div class="cols">
  <div class="col-l">
    {''.join(figs_html)}
  </div>
  <div class="col-r">
    <h2 style="margin-top:0">Key metrics</h2>
    {_key_metrics_table(m)}
  </div>
</div>
<h2>Per-game attribution vs analytic RTP</h2>
{_per_game_table(m['per_game'])}
<h2>Worst drawdown episodes</h2>
{_drawdown_table(m['drawdown'])}
<h2>Stop-loss / stop-win adherence</h2>
<div class="panel">{_stops_panel(m['stops'])}</div>
{sizing_html}
<footer>
<p><strong>Methodology.</strong> Money figures come from the session's
exact-cent Decimal ledger. Expected P&amp;L per bet is stake × (RTP − 1) and
its variance stake² × per-unit variance, both from the analytic engine
figures; bets are independent, so the session standard error is the root of
the summed variances. The z-score and its two-sided p-value assume the CLT
normal approximation — conservative for heavy-tailed games (high-variance
keno/plinko tails converge slowly). Risk-of-ruin curves use the
drifted-Brownian reflection formula at the session's realized stake mix and
are approximations, not guarantees. Drawdowns are measured on the gambling
equity curve (deposits/withdrawals backed out); the open episode is closed
at the last recorded bet. Win = payout &gt; stake; push breaks both streak
counters. Skew/kurtosis are population moments (kurtosis is excess).
VaR/CVaR are the 5th percentile of per-bet net and the tail mean at or
below it.</p>
<p>Every game here has RTP &lt; 1: no bet sizing or stop rule changes the
sign of the expected value — sizing only shapes the outcome distribution.
Timestamp anomalies detected: {meta['timestamp_anomalies']}.</p>
</footer>
</div>
</body>
</html>
"""
    if output_path is not None:
        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(html_doc)
    return html_doc
