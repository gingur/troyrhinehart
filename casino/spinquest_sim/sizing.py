"""Survival-optimal bet sizing for NEGATIVE-EV games.

Intellectual honesty, up front
-----------------------------

Every engine in :mod:`spinquest_sim.games` has RTP < 1 (house edge > 0), so
for every bet size ``b`` the expected net result of one round is

    E[net] = b * (RTP - 1) < 0.

Three consequences that no bet-sizing scheme can escape:

1. **No positive Kelly bet exists.**  The Kelly criterion maximizes
   ``E[log(bankroll)]``; its derivative at stake fraction 0 is exactly
   ``E[net per unit] = RTP - 1 < 0``, so the maximizer is the boundary
   ``f* = 0`` — the growth-optimal stake in a subfair game is *not playing*.
   :func:`kelly_fraction` returns 0 for every engine here, and that is the
   honest answer, not a bug.

2. **Longer play means larger expected loss.**  Expected loss is
   ``house_edge * (total amount wagered)``, which grows with every round
   played.  Any rule that reduces the expected number of rounds (bigger
   bets toward a fixed target, stop rules, quitting) reduces expected loss
   only by reducing exposure; nothing turns the EV positive.

3. **Sizing only shapes the outcome distribution.**  Bet size reallocates
   probability mass between "bust early" and "bleed slowly" (and, with a
   target, between "hit the target" and "grind down to ruin").  The mean of
   that distribution is pinned below the starting bankroll regardless.

What sizing CAN legitimately optimize is a *distributional* objective:

- ``reach_target``: maximize P(bankroll reaches T before ruin).  For a
  subfair even-money game this is the classical Dubins-Savage result
  (*How to Gamble If You Must*, 1965): **bold play** — stake
  ``min(bankroll, target - bankroll)``, i.e. as much as is useful, as fast
  as possible — is optimal, because every extra round played hands the
  house another edge payment.  Under flat betting the same force makes
  P(reach target) increase with bet size (fewest expected rounds at the
  same per-round odds); this module computes the exact absorption
  probabilities per bet size so the monotonicity is demonstrated, not
  assumed.  For non-even-money payouts Dubins-Savage boldness is not
  guaranteed to be exactly optimal (counterexamples exist), so there the
  flat-bet table is the evidence and the "bold" stake is the analogous
  reach-the-target-in-one-win stake.

- ``survive_rounds``: maximize P(still solvent after N rounds).  Here the
  regime flips to **timid play**: survival probability is nonincreasing in
  bet size (fewer bet-units of cushion between you and the ruin barrier),
  and as ``bet -> 0`` survival tends to 1 while expected loss tends to 0
  because almost nothing is wagered.  There is *no interior optimum*: the
  survival-optimal bet is the smallest bet the table allows.  The function
  returns exactly that, with the survival curve per candidate size so the
  monotone tradeoff is visible.

The machinery:

- :func:`reach_probability_even_money` /
  :func:`ruin_probability_even_money` /
  :func:`expected_rounds_even_money`: the exact closed-form gambler's-ruin
  absorption probabilities and expected duration for even-money bets
  (win/lose one unit per round), with a numerically stable log-space branch
  and an exact-``Fraction`` twin for verification.

- :class:`BankrollChain`: a finite Markov chain on a discretized bankroll
  lattice for ARBITRARY payout distributions (any engine), stepped by
  convolution (shift-and-add of the probability vector).  When every payout
  multiplier is rational (all engines expose ``multiplier_exact``) the
  lattice is chosen as the exact common denominator, so the chain has ZERO
  discretization error; otherwise a rounding grid with a documented
  resolution is used.

- :func:`survival_curve` / :func:`survival_curves`:
  P(still able to bet after n rounds), n = 1..N, per bet size.

- :func:`survival_optimal_bet`: the goal-directed recommendation for
  ``reach_target`` (bold) and ``survive_rounds`` (timid), each derived from
  the absorption math above and returned with the full per-candidate
  evidence table and the honest EV accounting.

- :func:`recommend_stops`: stop-loss / stop-win levels derived from the
  SAME first-passage math (no new assumptions): for ``reach_target`` the
  math says stop-win = the target itself and no early loss stop (any
  binding stop-loss strictly lowers P(reach target) — the tradeoff table
  is computed and returned); for ``survive_rounds`` the stops are
  first-passage quantiles of the N-round loss/gain distribution.

Conventions
-----------

Payout **multipliers are total-return ("for one")**: a lost bet is 0, an
even-money win is 2, a push is 1 — the same convention as the engines and
:mod:`spinquest_sim.session`.  "Alive"/"survival" means *able to place the
next flat bet* (bankroll >= bet); a terminal bankroll in ``(0, bet)`` is
counted as busted for sizing purposes because the strategy under analysis
cannot continue.  For even-money bets on a bankroll that is a whole number
of bet units the two notions coincide exactly (the only sub-``bet`` state
is 0), so the closed form and the chain agree with no caveat.
"""

from __future__ import annotations

import math
import numbers
from fractions import Fraction
from typing import Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

__all__ = [
    "normalize_game_config",
    "kelly_fraction",
    "reach_probability_even_money",
    "reach_probability_even_money_exact",
    "ruin_probability_even_money",
    "expected_rounds_even_money",
    "BankrollChain",
    "survival_curve",
    "survival_curves",
    "survival_optimal_bet",
    "recommend_stops",
]

NumberLike = Union[int, float, str, Fraction]
# One outcome of a single round, per unit staked: (total-return multiplier,
# probability).  Both exact Fractions after normalization.
Outcome = Tuple[Fraction, Fraction]


# ---------------------------------------------------------------------------
# input normalization
# ---------------------------------------------------------------------------

def _as_fraction(value: NumberLike, name: str) -> Fraction:
    """Exact Fraction from a user-supplied number.

    Floats are converted through ``str`` so the *printed* value is honored
    (``0.1 -> 1/10``, not ``3602879701896397/2**55``) — same policy as the
    session ledger's Decimal conversion.
    """
    if isinstance(value, bool):
        raise TypeError(f"{name} must be a number, got bool")
    if isinstance(value, Fraction):
        return value
    if isinstance(value, numbers.Integral):
        return Fraction(int(value))
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite, got {value}")
        return Fraction(str(value))
    if isinstance(value, str):
        return Fraction(value)
    if isinstance(value, numbers.Rational):
        return Fraction(value)
    raise TypeError(
        f"{name} must be int/float/str/Fraction, got {type(value).__name__}"
    )


def normalize_game_config(game_config: object) -> List[Outcome]:
    """Normalize a game description to an exact outcome distribution.

    Accepted forms:

    - an **engine object** exposing the standard analytic API — preferably
      ``multiplier_exact`` / ``win_probability_exact`` (Fractions, e.g.
      :class:`~spinquest_sim.games.roulette.Roulette`,
      :class:`~spinquest_sim.games.mines.Mines`), falling back to the float
      ``multiplier`` / ``win_probability`` pair.  Interpreted as the
      two-point distribution {multiplier w.p. p, 0 w.p. 1-p}.
    - ``{"win_probability": p, "multiplier": m}``: same two-point form.
    - ``{"distribution": [(multiplier, probability), ...]}``: arbitrary
      finite payout distribution (multipliers are total-return per unit).

    Returns a merged, sorted list of ``(multiplier, probability)`` exact
    Fractions with probabilities scaled to sum to exactly 1 (inputs must
    already sum to 1 within 1e-9; the residual float dust is rescaled away
    so the Markov chain conserves probability exactly).
    """
    pairs: List[Tuple[Fraction, Fraction]]
    if hasattr(game_config, "multiplier_exact") and hasattr(
        game_config, "win_probability_exact"
    ):
        m = Fraction(game_config.multiplier_exact)
        p = Fraction(game_config.win_probability_exact)
        pairs = [(m, p), (Fraction(0), 1 - p)]
    elif hasattr(game_config, "multiplier") and hasattr(
        game_config, "win_probability"
    ):
        m = _as_fraction(game_config.multiplier, "multiplier")
        p = _as_fraction(game_config.win_probability, "win_probability")
        pairs = [(m, p), (Fraction(0), 1 - p)]
    elif isinstance(game_config, dict) and "distribution" in game_config:
        dist = game_config["distribution"]
        pairs = [
            (_as_fraction(m, "multiplier"), _as_fraction(p, "probability"))
            for m, p in dist
        ]
    elif isinstance(game_config, dict) and {"win_probability", "multiplier"} <= set(
        game_config
    ):
        m = _as_fraction(game_config["multiplier"], "multiplier")
        p = _as_fraction(game_config["win_probability"], "win_probability")
        pairs = [(m, p), (Fraction(0), 1 - p)]
    else:
        raise TypeError(
            "game_config must be an engine with multiplier/win_probability, "
            "a {'win_probability', 'multiplier'} dict, or a "
            "{'distribution': [(mult, prob), ...]} dict"
        )

    merged: Dict[Fraction, Fraction] = {}
    for m, p in pairs:
        if m < 0:
            raise ValueError(f"multiplier must be >= 0, got {m}")
        if p < 0:
            raise ValueError(f"probability must be >= 0, got {p}")
        if p == 0:
            continue
        merged[m] = merged.get(m, Fraction(0)) + p
    if not merged:
        raise ValueError("distribution has no outcome with positive probability")
    total = sum(merged.values())
    if abs(float(total) - 1.0) > 1e-9:
        raise ValueError(f"probabilities must sum to 1, got {float(total)}")
    return sorted((m, p / total) for m, p in merged.items())


def _rtp_exact(outcomes: Sequence[Outcome]) -> Fraction:
    return sum((m * p for m, p in outcomes), Fraction(0))


# ---------------------------------------------------------------------------
# Kelly (the honest zero)
# ---------------------------------------------------------------------------

def kelly_fraction(game_config: object) -> float:
    """Kelly-optimal fraction of bankroll to stake per round.

    For a two-outcome game (win multiplier ``m`` w.p. ``p``, lose the stake
    otherwise) the interior stationary point of ``E[log(1 + f*(X-1))]`` is

        f* = (p*m - 1) / (m - 1)    (m > 1)

    and its sign is the sign of the edge ``p*m - 1 = RTP - 1``.  For ANY
    distribution the derivative of the log-growth at ``f = 0`` is
    ``E[X] - 1 = RTP - 1``, so when RTP < 1 the constrained maximizer over
    ``f in [0, 1]`` is the boundary ``f* = 0``: **the growth-optimal stake
    in a negative-EV game is zero**.  This function returns that honest 0.0
    for every engine in this project (all have RTP < 1); a positive value
    is returned only for a hypothetical RTP > 1 two-outcome input.
    """
    outcomes = normalize_game_config(game_config)
    edge = _rtp_exact(outcomes) - 1
    if edge <= 0:
        return 0.0
    nonzero = [(m, p) for m, p in outcomes if m != 0]
    if len(nonzero) == 1 and nonzero[0][0] > 1:
        m, p = nonzero[0]
        return float((p * m - 1) / (m - 1))
    # Positive-EV multi-outcome: not needed for this project's engines; the
    # exact optimum would require solving E[(X-1)/(1+f(X-1))] = 0.
    raise NotImplementedError(
        "kelly_fraction only solves the two-outcome case for RTP > 1 inputs; "
        "every engine in this project has RTP < 1, where the answer is 0.0"
    )


# ---------------------------------------------------------------------------
# (1a) exact gambler's ruin, even-money closed form
# ---------------------------------------------------------------------------

def _check_units(start_units: int, target_units: int) -> Tuple[int, int]:
    for name, v in (("start_units", start_units), ("target_units", target_units)):
        if isinstance(v, bool) or not isinstance(v, numbers.Integral):
            raise TypeError(f"{name} must be an integer, got {v!r}")
    i, n = int(start_units), int(target_units)
    if n < 1:
        raise ValueError(f"target_units must be >= 1, got {n}")
    if not 0 <= i <= n:
        raise ValueError(f"start_units must be in 0..target_units, got {i}")
    return i, n


def _check_p(p_win: float) -> float:
    p = float(p_win)
    if not 0.0 < p < 1.0:
        raise ValueError(f"p_win must be in (0, 1), got {p_win}")
    return p


def reach_probability_even_money(
    p_win: float, start_units: int, target_units: int
) -> float:
    """P(bankroll reaches ``target_units`` before 0) — exact closed form.

    Classical gambler's ruin for an even-money bet of one unit per round:
    win +1 w.p. ``p``, lose -1 w.p. ``q = 1 - p``.  With ``r = q/p``:

        P(reach N before 0 | start i) = (r**i - 1) / (r**N - 1)   (p != 1/2)
                                      = i / N                     (p == 1/2)

    Computed stably as ``expm1(i*L)/expm1(N*L)`` with ``L = ln(q/p)``, and
    in log space (``exp((i-N)*L) * expm1(-i*L)/expm1(-N*L)``) when ``N*L``
    would overflow ``exp`` — so ``p_win=0.49, target_units=10**6`` returns
    the correct subnormal-or-zero probability instead of ``nan``.

    Both absorbing barriers are certain to be hit eventually (the walk is
    finite), so :func:`ruin_probability_even_money` is exactly the
    complement: reach + ruin = 1.
    """
    p = _check_p(p_win)
    i, n = _check_units(start_units, target_units)
    if i == 0:
        return 0.0
    if i == n:
        return 1.0
    ln_l = math.log1p(-p) - math.log(p)          # L = ln(q/p)
    if ln_l == 0.0:
        return i / n
    a, b = i * ln_l, n * ln_l
    if b > 700.0:                                # r**N overflows float64
        return math.exp(a - b) * math.expm1(-a) / math.expm1(-b)
    return math.expm1(a) / math.expm1(b)


def reach_probability_even_money_exact(
    p_win: NumberLike, start_units: int, target_units: int
) -> Fraction:
    """Exact-Fraction twin of :func:`reach_probability_even_money`.

    ``(r**i - 1)/(r**N - 1)`` evaluated in rational arithmetic — the ground
    truth the stable float implementation is verified against.  ``p_win``
    may be a Fraction (e.g. ``Fraction(18, 37)`` for roulette even-money).
    """
    p = _as_fraction(p_win, "p_win")
    if not 0 < p < 1:
        raise ValueError(f"p_win must be in (0, 1), got {p}")
    i, n = _check_units(start_units, target_units)
    if i == 0:
        return Fraction(0)
    if i == n:
        return Fraction(1)
    q = 1 - p
    if p == q:
        return Fraction(i, n)
    r = q / p
    return (r**i - 1) / (r**n - 1)


def ruin_probability_even_money(
    p_win: float, start_units: int, target_units: int
) -> float:
    """P(hitting 0 before ``target_units``) = 1 - reach probability."""
    return 1.0 - reach_probability_even_money(p_win, start_units, target_units)


def expected_rounds_even_money(
    p_win: float, start_units: int, target_units: int
) -> float:
    """Expected rounds until absorption at 0 or ``target_units``.

        E[T] = (i - N * P_reach) / (q - p)    (p != 1/2)
             = i * (N - i)                    (p == 1/2)

    Honest corollary: expected loss of the whole session is
    ``bet * house_edge_per_round * E[T]`` (Wald), so *shorter* expected
    sessions — bigger bets relative to the barriers — lose less on average.
    """
    p = _check_p(p_win)
    i, n = _check_units(start_units, target_units)
    q = 1.0 - p
    if q == p:
        return float(i * (n - i))
    reach = reach_probability_even_money(p, i, n)
    return (i - n * reach) / (q - p)


# ---------------------------------------------------------------------------
# (1b) general Markov / convolution solver on a discretized bankroll
# ---------------------------------------------------------------------------

_DEFAULT_RESOLUTION = 1000       # cells per bet unit when rounding is needed
_MAX_STATES = 5_000_000          # guard against runaway lattices


class BankrollChain:
    """Finite Markov chain for a flat-betting bankroll on a lattice.

    Models: stake ``bet`` every round while ``bankroll >= bet``; each round
    multiplies the stake by an outcome drawn from ``game_config``'s payout
    distribution (total-return multipliers).  Absorbing sets:

    - **ruin**: bankroll < ``bet`` (cannot place the next flat bet; includes
      every state in ``[0, bet)`` — see the module docstring),
    - **target** (optional): bankroll >= ``target``.

    The bankroll is discretized in units of ``bet / D``.  When the start
    bankroll, target and every net step ``bet*(m - 1)`` are rational (true
    for all project engines via ``multiplier_exact``), ``D`` is chosen as
    their exact least common denominator and the chain is EXACT — zero
    discretization error (attribute ``exact_lattice`` is True).  Otherwise
    a rounding grid of ``resolution`` cells per bet is used and the maximum
    per-round step rounding error is recorded
    (``max_step_rounding_error``, in bet units).

    Stepping is a convolution: each outcome shifts the alive probability
    vector by a fixed cell offset and accumulates (numpy shift-and-add), so
    one round costs O(states * outcomes).
    """

    def __init__(
        self,
        bankroll: NumberLike,
        bet: NumberLike,
        game_config: object,
        *,
        target: Optional[NumberLike] = None,
        resolution: int = _DEFAULT_RESOLUTION,
        max_states: int = _MAX_STATES,
    ) -> None:
        self.outcomes = normalize_game_config(game_config)
        bet_f = _as_fraction(bet, "bet")
        if bet_f <= 0:
            raise ValueError(f"bet must be > 0, got {bet}")
        bank_f = _as_fraction(bankroll, "bankroll")
        if bank_f < bet_f:
            raise ValueError(
                f"bankroll must be >= bet (cannot place even one flat bet), "
                f"got bankroll={bankroll}, bet={bet}"
            )
        self.bet = bet_f
        self.bankroll = bank_f
        # Work in units of one bet.
        self._start_units = bank_f / bet_f
        self._target_units: Optional[Fraction] = None
        if target is not None:
            t = _as_fraction(target, "target")
            if t <= bank_f:
                raise ValueError(
                    f"target must exceed bankroll, got target={t} <= {bank_f}"
                )
            self._target_units = t / bet_f
        self.rtp_exact = _rtp_exact(self.outcomes)
        self.house_edge = float(1 - self.rtp_exact)

        # --- lattice ----------------------------------------------------
        steps = [m - 1 for m, _ in self.outcomes]     # net, in bet units
        denoms = [s.denominator for s in steps] + [self._start_units.denominator]
        if self._target_units is not None:
            denoms.append(self._target_units.denominator)
        d_exact = math.lcm(*denoms)
        span_units = (
            self._target_units if self._target_units is not None
            else self._start_units
        )
        if d_exact * span_units <= max_states:
            self.lattice_denominator = d_exact
            self.exact_lattice = True
        else:
            if resolution < 1:
                raise ValueError("resolution must be >= 1")
            self.lattice_denominator = int(resolution)
            self.exact_lattice = False
        d = self.lattice_denominator

        def to_idx(units: Fraction) -> int:
            scaled = units * d
            if scaled.denominator == 1:
                return scaled.numerator
            return round(float(scaled))

        self._alive_lo = d                            # bankroll >= bet
        self._start_idx = to_idx(self._start_units)
        self._target_idx: Optional[int] = (
            to_idx(self._target_units) if self._target_units is not None else None
        )
        self.max_step_rounding_error = 0.0
        offs: Dict[int, float] = {}
        for (m, p), s in zip(self.outcomes, steps):
            scaled = s * d
            if scaled.denominator == 1:
                off = scaled.numerator
            else:
                off = round(float(scaled))
                self.max_step_rounding_error = max(
                    self.max_step_rounding_error, abs(float(scaled) - off) / d
                )
            if off < -d:
                # A multiplier >= 0 can lose at most the stake (one bet =
                # d cells), so this can only be a rounding artifact; clamp.
                off = -d
            offs[off] = offs.get(off, 0.0) + float(p)
        self._offsets = sorted(offs.items())
        self._max_up = max(0, max(off for off, _ in self._offsets))
        self._max_states = int(max_states)

    # -- helpers ---------------------------------------------------------

    def value_of_index(self, j: int) -> float:
        """Bankroll amount (in money units) of lattice index ``j``."""
        return float(self.bet) * j / self.lattice_denominator

    def _initial(self, length: int) -> np.ndarray:
        cur = np.zeros(length, dtype=np.float64)
        cur[self._start_idx] = 1.0
        return cur

    def _sweep(
        self, new: np.ndarray, ruined: float, reached: float
    ) -> Tuple[float, float]:
        """Move absorbed mass out of the alive vector; return the updates."""
        lo = self._alive_lo
        below = float(new[:lo].sum())
        if below:
            ruined += below
            new[:lo] = 0.0
        if self._target_idx is not None:
            above = float(new[self._target_idx:].sum())
            if above:
                reached += above
                new[self._target_idx:] = 0.0
        return ruined, reached

    def _step(self, cur: np.ndarray, hi: int) -> np.ndarray:
        """One convolution step of the alive slice ``cur[lo:hi]``."""
        lo = self._alive_lo
        new = np.zeros_like(cur)
        alive = cur[lo:hi]
        for off, p in self._offsets:
            new[lo + off:hi + off] += p * alive
        return new

    # -- public solvers --------------------------------------------------

    def run(self, n_rounds: int) -> Dict[str, object]:
        """Evolve the chain exactly ``n_rounds`` rounds.

        Returns a dict with, per round ``t = 1..n``:

        - ``alive`` (np.ndarray): P(still able to bet after t rounds),
        - ``ruined`` (np.ndarray): cumulative P(busted by round t),
        - ``reached`` (np.ndarray): cumulative P(target hit by round t)
          (all zeros when no target is set),

        plus the terminal state: ``grid`` (bankroll values of the alive
        lattice cells) and ``probs`` (their probabilities), ``p_alive``,
        ``p_ruined``, ``p_reached``.  Probability is conserved:
        ``p_alive + p_ruined + p_reached == 1`` up to float rounding.
        """
        if isinstance(n_rounds, bool) or not isinstance(n_rounds, numbers.Integral):
            raise TypeError(f"n_rounds must be an integer, got {n_rounds!r}")
        n = int(n_rounds)
        if n < 1:
            raise ValueError("n_rounds must be >= 1")
        if self._target_idx is not None:
            hi_cap = self._target_idx
            length = self._target_idx + self._max_up + 1
        else:
            hi_cap = self._start_idx + n * self._max_up + 1
            length = hi_cap + self._max_up
        if length > self._max_states:
            raise ValueError(
                f"lattice would need {length} states (> max_states="
                f"{self._max_states}); coarsen with resolution=, or reduce "
                f"n_rounds"
            )
        cur = self._initial(length)
        ruined = reached = 0.0
        alive_c = np.empty(n)
        ruined_c = np.empty(n)
        reached_c = np.empty(n)
        top = self._start_idx + 1
        for t in range(n):
            hi = min(top, hi_cap)
            cur = self._step(cur, hi)
            ruined, reached = self._sweep(cur, ruined, reached)
            top = min(top + self._max_up, length)
            alive_c[t] = cur.sum()
            ruined_c[t] = ruined
            reached_c[t] = reached
        grid_idx = np.nonzero(cur)[0]
        return {
            "alive": alive_c,
            "ruined": ruined_c,
            "reached": reached_c,
            "p_alive": float(alive_c[-1]),
            "p_ruined": float(ruined),
            "p_reached": float(reached),
            "grid": np.array([self.value_of_index(int(j)) for j in grid_idx]),
            "probs": cur[grid_idx].copy(),
            "n_rounds": n,
            "exact_lattice": self.exact_lattice,
        }

    def survival_curve(self, n_rounds: int) -> np.ndarray:
        """P(still able to place the flat bet after t rounds), t = 1..N.

        Requires no target (survival is about outlasting the ruin barrier
        alone).  Nonincreasing in t; every round played still costs
        ``bet * house_edge`` in expectation — surviving is not winning.
        """
        if self._target_idx is not None:
            raise ValueError(
                "survival_curve is defined for the no-target chain; "
                "construct without target= (use run()/absorption() for "
                "target questions)"
            )
        return self.run(n_rounds)["alive"]

    def absorption(
        self, *, tol: float = 1e-12, max_rounds: int = 10_000_000
    ) -> Dict[str, float]:
        """Iterate to (near-)total absorption; requires a target.

        Returns ``p_target`` (reach target before ruin), ``p_ruin``, the
        expected number of rounds until absorption (``expected_rounds`` =
        sum over t of P(alive after t rounds), plus the round being played),
        and the unabsorbed ``residual`` (< tol unless ``max_rounds`` hit).
        ``p_target + p_ruin + residual = 1`` up to float rounding.
        """
        if self._target_idx is None:
            raise ValueError("absorption requires target= at construction")
        length = self._target_idx + self._max_up + 1
        if length > self._max_states:
            raise ValueError(
                f"lattice would need {length} states (> max_states="
                f"{self._max_states}); coarsen with resolution="
            )
        cur = self._initial(length)
        ruined = reached = 0.0
        hi = self._target_idx
        expected_rounds = 0.0
        alive = 1.0
        rounds = 0
        while alive > tol and rounds < max_rounds:
            expected_rounds += alive        # this round is played by `alive`
            cur = self._step(cur, hi)
            ruined, reached = self._sweep(cur, ruined, reached)
            alive = float(cur.sum())
            rounds += 1
        return {
            "p_target": reached,
            "p_ruin": ruined,
            "residual": alive,
            "expected_rounds": expected_rounds,
            "rounds_iterated": rounds,
            "expected_loss": float(self.bet) * self.house_edge * expected_rounds,
        }


# ---------------------------------------------------------------------------
# (2) survival curves per bet size
# ---------------------------------------------------------------------------

def survival_curve(
    bankroll: NumberLike,
    bet: NumberLike,
    game_config: object,
    n_rounds: int,
    *,
    resolution: int = _DEFAULT_RESOLUTION,
) -> np.ndarray:
    """P(still able to bet after t rounds), t = 1..N, for one flat bet size."""
    chain = BankrollChain(bankroll, bet, game_config, resolution=resolution)
    return chain.survival_curve(n_rounds)


def survival_curves(
    bankroll: NumberLike,
    bet_sizes: Sequence[NumberLike],
    game_config: object,
    n_rounds: int,
    *,
    resolution: int = _DEFAULT_RESOLUTION,
) -> Dict[float, np.ndarray]:
    """Survival curves for several flat bet sizes: {bet: curve}.

    The curves are pointwise ordered: smaller bets survive (weakly) better
    at every horizon — the timid-play regime.  Expected loss, however, is
    ``bet * house_edge * E[rounds actually played]`` for EVERY size: the
    choice shapes the distribution, never the sign of the drift.
    """
    out: Dict[float, np.ndarray] = {}
    for b in bet_sizes:
        out[float(_as_fraction(b, "bet"))] = survival_curve(
            bankroll, b, game_config, n_rounds, resolution=resolution
        )
    return out


# ---------------------------------------------------------------------------
# (3) survival_optimal_bet
# ---------------------------------------------------------------------------

_DEFAULT_BET_FRACTIONS = (
    Fraction(1), Fraction(1, 2), Fraction(1, 4), Fraction(1, 5),
    Fraction(1, 10), Fraction(1, 20), Fraction(1, 50), Fraction(1, 100),
)


def _candidate_bets(
    bankroll: Fraction,
    min_bet: Optional[Fraction],
    max_bet: Optional[Fraction],
    bet_grid: Optional[Sequence[NumberLike]],
) -> List[Fraction]:
    if bet_grid is not None:
        cands = sorted({_as_fraction(b, "bet") for b in bet_grid})
    else:
        cands = sorted({bankroll * f for f in _DEFAULT_BET_FRACTIONS})
        if min_bet is not None:
            cands.append(min_bet)
        if max_bet is not None:
            cands.append(max_bet)
        cands = sorted(set(cands))
    out = []
    for b in cands:
        if b <= 0 or b > bankroll:
            continue
        if min_bet is not None and b < min_bet:
            continue
        if max_bet is not None and b > max_bet:
            continue
        out.append(b)
    if not out:
        raise ValueError("no candidate bet sizes fit the min/max constraints")
    return out


def survival_optimal_bet(
    bankroll: NumberLike,
    game_config: object,
    goal: str,
    *,
    target: Optional[NumberLike] = None,
    n_rounds: Optional[int] = None,
    min_bet: Optional[NumberLike] = None,
    max_bet: Optional[NumberLike] = None,
    bet_grid: Optional[Sequence[NumberLike]] = None,
    resolution: int = _DEFAULT_RESOLUTION,
) -> Dict[str, object]:
    """Goal-directed bet sizing for a negative-EV game.

    ``goal='reach_target'`` (requires ``target``) — **bold play**.
        For subfair even-money odds, Dubins & Savage (1965) prove bold play
        (stake ``min(bankroll, target - bankroll)``) maximizes the
        probability of reaching the target: every additional round played
        pays the house edge again, so the optimal policy minimizes exposure
        by resolving the question in as few bets as possible.  The returned
        ``recommended_bet`` is the bold stake — for a general win multiplier
        ``m`` the stake that reaches the target in one win,
        ``(target - bankroll)/(m - 1)``, capped by the bankroll and
        ``max_bet``.  The flat-bet evidence table (exact absorption
        probability, expected rounds and expected loss per candidate size)
        is computed with :class:`BankrollChain`; ``best_flat_bet`` is its
        argmax.  For even-money games P(reach) is strictly increasing in the
        flat bet size, so the table's argmax is its largest bet; for
        non-even-money payouts boldness is no longer guaranteed optimal in
        general and the table is the evidence.

    ``goal='survive_rounds'`` (requires ``n_rounds``) — **timid play**.
        P(surviving N rounds) is nonincreasing in the bet size and tends to
        1 as the bet tends to 0: there is NO interior optimum, so the
        survival-optimal bet is the smallest allowed (``min_bet``, or the
        smallest candidate when no minimum is given — with the honest note
        that only a table minimum stops the answer from being "don't
        play").  The per-candidate survival probabilities are returned.

    Every result carries the honest accounting: ``rtp``/``house_edge`` of
    the game, per-candidate ``expected_loss`` (= bet * edge * expected
    rounds played), and an explicit note that no bet size changes the sign
    of the EV — the choice only shapes the outcome distribution.
    """
    outcomes = normalize_game_config(game_config)
    bank = _as_fraction(bankroll, "bankroll")
    if bank <= 0:
        raise ValueError("bankroll must be > 0")
    min_b = _as_fraction(min_bet, "min_bet") if min_bet is not None else None
    max_b = _as_fraction(max_bet, "max_bet") if max_bet is not None else None
    if min_b is not None and max_b is not None and min_b > max_b:
        raise ValueError("min_bet must be <= max_bet")
    rtp = _rtp_exact(outcomes)
    base = {
        "goal": goal,
        "bankroll": float(bank),
        "rtp": float(rtp),
        "house_edge": float(1 - rtp),
        "ev_per_unit_staked": float(rtp - 1),
        "kelly_fraction": 0.0 if rtp <= 1 else None,
        "note": (
            "Negative-EV game: expected loss = house_edge * total wagered "
            "grows with every round; bet sizing shapes the outcome "
            "distribution but cannot change the sign of the EV."
        ),
    }
    dist_cfg = {"distribution": [(m, p) for m, p in outcomes]}

    if goal == "reach_target":
        if target is None:
            raise ValueError("goal='reach_target' requires target=")
        tgt = _as_fraction(target, "target")
        if tgt <= bank:
            raise ValueError("target must exceed bankroll")
        cands = _candidate_bets(bank, min_b, max_b, bet_grid)
        table = []
        for b in cands:
            chain = BankrollChain(
                bank, b, dist_cfg, target=tgt, resolution=resolution
            )
            res = chain.absorption()
            table.append({
                "bet": float(b),
                "p_reach_target": res["p_target"],
                "p_ruin": res["p_ruin"],
                "expected_rounds": res["expected_rounds"],
                "expected_loss": res["expected_loss"],
                "exact_lattice": chain.exact_lattice,
            })
        best = max(table, key=lambda row: (row["p_reach_target"], row["bet"]))
        max_win_step = max(m - 1 for m, _ in outcomes)
        if max_win_step <= 0:
            raise ValueError("distribution has no winning outcome (m > 1)")
        bold = min(bank, (tgt - bank) / max_win_step)
        if max_b is not None:
            bold = min(bold, max_b)
        if min_b is not None:
            bold = max(bold, min_b)
        base.update({
            "target": float(tgt),
            "regime": "bold",
            "recommended_bet": float(bold),
            "recommended_bet_rule": (
                "bold play: stake enough to reach the target in one win, "
                "min(bankroll, (target - bankroll) / (win multiplier - 1))"
                + ("" if max_b is None and min_b is None
                   else ", clamped to the table limits")
            ),
            "best_flat_bet": best["bet"],
            "flat_bet_table": table,
            "rationale": (
                "Dubins-Savage: under subfair even-money odds, bold play "
                "maximizes P(reach target) by minimizing the number of "
                "rounds over which the house edge is paid; among flat bets, "
                "larger bets dominate for the same reason (see table)."
            ),
        })
        return base

    if goal == "survive_rounds":
        if n_rounds is None:
            raise ValueError("goal='survive_rounds' requires n_rounds=")
        cands = _candidate_bets(bank, min_b, max_b, bet_grid)
        table = []
        for b in cands:
            chain = BankrollChain(bank, b, dist_cfg, resolution=resolution)
            res = chain.run(n_rounds)
            expected_played = float(
                np.concatenate(([1.0], res["alive"][:-1])).sum()
            )
            table.append({
                "bet": float(b),
                "p_survive": res["p_alive"],
                "expected_rounds_played": expected_played,
                "expected_loss": float(b) * float(1 - rtp) * expected_played,
                "exact_lattice": chain.exact_lattice,
            })
        recommended = min_b if min_b is not None else cands[0]
        rec_row = min(table, key=lambda row: row["bet"])
        base.update({
            "n_rounds": int(n_rounds),
            "regime": "timid",
            "recommended_bet": float(recommended),
            "recommended_bet_rule": (
                "timid play: the minimum allowed bet — survival probability "
                "is nonincreasing in bet size, so only a table minimum "
                "keeps the answer from being 'bet 0 / don't play'"
            ),
            "p_survive_at_recommended": rec_row["p_survive"],
            "flat_bet_table": table,
            "rationale": (
                "P(survive N rounds) is maximized by the smallest stake: "
                "smaller bets put more bet-units between the bankroll and "
                "the ruin barrier and shrink per-round variance; as bet -> "
                "0 survival -> 1 (and expected loss -> 0 because almost "
                "nothing is wagered) - there is no interior optimum."
            ),
        })
        return base

    raise ValueError(
        f"goal must be 'reach_target' or 'survive_rounds', got {goal!r}"
    )


# ---------------------------------------------------------------------------
# (4) stop-loss / stop-win recommendation
# ---------------------------------------------------------------------------

def recommend_stops(
    bankroll: NumberLike,
    bet: NumberLike,
    game_config: object,
    goal: str,
    *,
    target: Optional[NumberLike] = None,
    n_rounds: Optional[int] = None,
    stop_loss_alpha: float = 0.10,
    stop_win_prob_floor: float = 0.25,
    max_candidates: int = 24,
    resolution: int = _DEFAULT_RESOLUTION,
) -> Dict[str, object]:
    """Stop-loss / stop-win levels derived from the same absorption math.

    ``goal='reach_target'``:
        The absorption analysis itself dictates the stops.  **Stop-win =
        the target** (profit ``target - bankroll``): the objective is
        achieved the instant the target is hit, and any further bet re-risks
        it at negative EV.  **Stop-loss = the whole bankroll**: committing
        only ``L < bankroll`` is equivalent to playing the same chain from
        the smaller start ``L`` toward the now-more-distant target, which
        strictly lowers P(reach) — the returned ``stop_loss_tradeoff``
        table (P(reach target) as a function of the committed loss L,
        computed with :class:`BankrollChain`) shows the monotone cost of a
        tighter stop.  A tighter stop-loss is still a legitimate *risk*
        choice (it caps the worst case); the table prices it honestly.

    ``goal='survive_rounds'``:
        Stops are first-passage quantiles of the N-round play distribution.
        **Stop-loss** = the smallest loss level L (multiple of ``bet``)
        whose probability of being hit within N rounds is <=
        ``stop_loss_alpha`` — i.e. the stop only fires in the worst
        ``alpha`` tail of sessions.  **Stop-win** = the largest gain level
        W (multiple of ``bet``) still reached within N rounds with
        probability >= ``stop_win_prob_floor`` — a lock-in point that is
        actually attainable, not decoration.  Both are computed from
        :class:`BankrollChain` first-passage probabilities (loss side: the
        chain started at L absorbs at its ruin barrier exactly when the
        cumulative loss reaches L; win side: the chain with target
        ``bankroll + W`` absorbs above exactly when the gain reaches W).

    Honest note carried in the result: stop rules cannot create positive
    EV.  They reduce expected loss ONLY by reducing the expected number of
    rounds played (expected loss = house_edge * bet * E[rounds]), and they
    reshape the outcome distribution (bounded worst case / banked best
    case).  ``expected_loss_cap`` prices the recommended stop pair.
    """
    outcomes = normalize_game_config(game_config)
    bank = _as_fraction(bankroll, "bankroll")
    bet_f = _as_fraction(bet, "bet")
    if bet_f <= 0 or bank <= 0:
        raise ValueError("bankroll and bet must be > 0")
    if bet_f > bank:
        raise ValueError("bet cannot exceed bankroll")
    rtp = _rtp_exact(outcomes)
    dist_cfg = {"distribution": [(m, p) for m, p in outcomes]}
    base = {
        "goal": goal,
        "bankroll": float(bank),
        "bet": float(bet_f),
        "house_edge": float(1 - rtp),
        "note": (
            "Stop rules cannot create positive EV: they reduce expected "
            "loss only by reducing expected rounds played, and reshape the "
            "outcome distribution (bounded worst case / banked best case)."
        ),
    }

    if goal == "reach_target":
        if target is None:
            raise ValueError("goal='reach_target' requires target=")
        tgt = _as_fraction(target, "target")
        if tgt <= bank:
            raise ValueError("target must exceed bankroll")
        profit = tgt - bank
        units = bank / bet_f
        # Committed-loss candidates: quarters of the bankroll, snapped to
        # whole bets (the lattice the flat-bet strategy actually lives on).
        fracs = (Fraction(1, 4), Fraction(1, 2), Fraction(3, 4), Fraction(1))
        cand_units = sorted({
            max(1, math.floor(units * f)) for f in fracs
        })
        tradeoff = []
        for u in cand_units:
            committed = u * bet_f          # loss cap L, in money
            sub_target = committed + profit
            chain = BankrollChain(
                committed, bet_f, dist_cfg, target=sub_target,
                resolution=resolution,
            )
            res = chain.absorption()
            tradeoff.append({
                "stop_loss": float(committed),
                "p_reach_target": res["p_target"],
                "expected_rounds": res["expected_rounds"],
                "expected_loss": res["expected_loss"],
            })
        base.update({
            "target": float(tgt),
            "stop_win": float(profit),
            "stop_loss": float(bank),
            "stop_win_rationale": (
                "quit the instant the target is reached: any further bet "
                "re-risks the achieved goal at negative EV"
            ),
            "stop_loss_rationale": (
                "P(reach target) is maximized by committing the whole "
                "bankroll; any binding stop-loss L < bankroll strictly "
                "lowers it (see stop_loss_tradeoff)"
            ),
            "stop_loss_tradeoff": tradeoff,
            "p_reach_target": tradeoff[-1]["p_reach_target"],
        })
        return base

    if goal == "survive_rounds":
        if n_rounds is None:
            raise ValueError("goal='survive_rounds' requires n_rounds=")
        n = int(n_rounds)
        if n < 1:
            raise ValueError("n_rounds must be >= 1")
        max_units = math.floor(bank / bet_f)
        step = max(1, math.ceil(max_units / max_candidates))
        loss_units = list(range(step, max_units + 1, step))
        if loss_units[-1] != max_units:
            loss_units.append(max_units)
        # Stop-loss: first-passage of the cumulative loss.  A chain started
        # at L (same bet, no target) is ruined exactly when the loss since
        # the start reaches its full cushion — P(hit stop-loss within N).
        loss_table = []
        stop_loss_units = loss_units[-1]
        stop_loss_p = None
        for u in loss_units:
            chain = BankrollChain(u * bet_f, bet_f, dist_cfg,
                                  resolution=resolution)
            p_hit = 1.0 - float(chain.run(n)["p_alive"])
            loss_table.append({"stop_loss": float(u * bet_f),
                               "p_hit_within_n": p_hit})
            if p_hit <= stop_loss_alpha and stop_loss_p is None:
                stop_loss_units, stop_loss_p = u, p_hit
        if stop_loss_p is None:      # even the full bankroll busts too often
            stop_loss_units = loss_units[-1]
            stop_loss_p = loss_table[-1]["p_hit_within_n"]
        # Stop-win: first passage of the cumulative gain.
        win_units_max = max(
            1, math.ceil(n * float(max(m - 1 for m, _ in outcomes)))
        )
        wstep = max(1, math.ceil(win_units_max / max_candidates))
        win_table = []
        stop_win_units, stop_win_p = None, None
        for u in range(wstep, win_units_max + 1, wstep):
            chain = BankrollChain(
                bank, bet_f, dist_cfg, target=bank + u * bet_f,
                resolution=resolution,
            )
            p_hit = float(chain.run(n)["p_reached"])
            win_table.append({"stop_win": float(u * bet_f),
                              "p_hit_within_n": p_hit})
            if p_hit >= stop_win_prob_floor:
                stop_win_units, stop_win_p = u, p_hit
            else:
                break                # p_hit is decreasing in W; no point on
        if stop_win_units is None:
            stop_win_units, stop_win_p = wstep, win_table[0]["p_hit_within_n"]
        base.update({
            "n_rounds": n,
            "stop_loss": float(stop_loss_units * bet_f),
            "p_stop_loss_hit": stop_loss_p,
            "stop_loss_alpha": stop_loss_alpha,
            "stop_loss_rationale": (
                f"smallest loss cap hit within {n} rounds with probability "
                f"<= {stop_loss_alpha}: the stop only fires in the worst "
                f"tail of sessions while capping the worst case"
            ),
            "stop_win": float(stop_win_units * bet_f),
            "p_stop_win_hit": stop_win_p,
            "stop_win_prob_floor": stop_win_prob_floor,
            "stop_win_rationale": (
                f"largest gain still reached within {n} rounds with "
                f"probability >= {stop_win_prob_floor}: an attainable "
                f"lock-in point, not decoration"
            ),
            "stop_loss_table": loss_table,
            "stop_win_table": win_table,
            "expected_loss_cap": float(stop_loss_units * bet_f),
        })
        return base

    raise ValueError(
        f"goal must be 'reach_target' or 'survive_rounds', got {goal!r}"
    )
