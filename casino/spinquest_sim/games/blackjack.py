"""Stake-style Blackjack (Stake Original): infinite deck, provably fair.

Rules published by Stake (references/stake/blackjack.md) and implemented
verbatim:

* Cards: "unlimited amount of decks" — every card (initial deal and every
  hit, for player, split hands and dealer) is an independent uniform draw
  ``floor(float * 52)`` over the bet's HMAC-SHA256 float stream (reference
  section 3); the index-to-card table is :data:`spinquest_sim.rng.CARDS`.
* Payouts (reference section 4): beat the dealer with a standard hand 1:1;
  beat the dealer with Blackjack (A + ten-card first two cards) 3:2;
  insurance side bet (offered only vs an exposed ace) pays 2:1.  The
  basic-strategy player never takes insurance (EV -1/13 per insurance unit,
  see :meth:`Blackjack.insurance_ev`).
* Hit or stand on any total <= 21; split any first-two-card pair, placing an
  equal second bet; double = double the bet for exactly one more card.

Details Stake does NOT publish (dealer soft-17 rule, double-after-split,
resplit cap, surrender, hole-card/peek — reference section 4 closing note)
are adopted from the matching Wizard of Odds infinite-deck expected-return
rule set (references/woo/blackjack.md): dealer STANDS on soft 17, double on
any first two cards, double after split allowed, resplit non-ace pairs up
to THREE times (at most 4 hands — WoO methodology note: "published tables
cap resplits at three (aces excluded)"), aces split once and receive one
card each, no surrender, dealer peeks for blackjack (player loses only the
initial bet to a dealer natural; a player natural pushes it).  WoO's exact
analysis of that rule set gives house edge 0.511734% (player EV
-0.511734%); the exact analytics here reproduce it to < 5e-7 absolute, and
it is the empirical target too, vs Stake's own published headline
"Edge: 0.57%".

The basic-strategy player is DERIVED, not hard-coded: with an infinite deck
the EV of every action depends only on (total, softness, pair value) vs the
dealer upcard, so the total-dependent greedy strategy computed by the DP in
:meth:`Blackjack._build` IS optimal basic strategy for these rules.  It
reproduces the classic S17/DAS chart, including the infinite-deck quirks of
hitting soft 13 vs 5 and soft 15 vs 4 where the 4-deck chart doubles
(references/woo/blackjack.md, methodology notes).

Engine contract:
  (a) exact analytic probability / RTP / variance — the full round-payout
      distribution on the half-unit lattice -8 .. +8 units;
  (b) provably-fair single-round play on the scalar RNG path
      (:meth:`Blackjack.play_round`);
  (c) a vectorized numpy simulator for 10M+ rounds on
      :class:`spinquest_sim.rng.BulkRng` (:meth:`Blackjack.simulate`) —
      per-nonce bit-identical to (b), with automatic scalar fallback for any
      round needing more cards than the per-bet float budget;
  (d) the standard result dict {rtp, house_edge, std_per_unit, config}.

All payouts in this module are NET units per 1-unit initial bet (a 3:2
blackjack win is +1.5, a doubled loss is -2, a 4-hand all-doubled sweep is
+8 or -8); RTP = 1 + EV(net) and house edge = -EV(net), per WoO's
"loss per initial bet" definition.
"""

from __future__ import annotations

import math
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

from spinquest_sim import rng as sq_rng
from spinquest_sim.rng import BulkRng

__all__ = [
    "CARD_VALUES",
    "VALUES",
    "P_VALUE",
    "WOO_INFINITE_DECK_HOUSE_EDGE",
    "INSURANCE_PAYS",
    "hand_value",
    "Blackjack",
]

_DECK = 52

# Card index 0..51 -> blackjack value.  rank = index // 4 (the published
# CARDS table is rank-major: 2,3,...,10,J,Q,K,A with 4 suits each), so
# ranks 0..7 -> 2..9, ranks 8..11 (10,J,Q,K) -> 10, rank 12 (A) -> 11.
CARD_VALUES = np.array(
    [min(rank + 2, 10) if rank < 12 else 11 for rank in range(13) for _ in range(4)],
    dtype=np.int16,
)

VALUES: Tuple[int, ...] = tuple(range(2, 12))  # 2..10, 11 = ace
# Infinite deck: every rank 1/13, four ten-valued ranks -> 4/13.
P_VALUE: Dict[int, float] = {v: (4.0 / 13.0 if v == 10 else 1.0 / 13.0) for v in VALUES}

# Exact figure captured in references/woo/blackjack.md for this rule set
# (infinite deck, S17, DAS, resplit non-aces to 4 hands, aces once/one
# card, no surrender, optimal = total-dependent basic strategy).  The
# validation script re-parses it from the reference file; this constant is
# for tests.  The engine's exact analytics reproduce it to < 5e-7.
WOO_INFINITE_DECK_HOUSE_EDGE = 0.00511734

INSURANCE_PAYS = 2.0  # published: "Insurance bets pay 2:1"

# Net-payout lattice: -8.0 .. +8.0 in half-unit steps (33 bins).  +-8 is the
# extreme 4-hand all-doubled round; +1.5 is the blackjack payout.
_LATTICE = np.arange(-16, 17, dtype=np.float64) / 2.0
_NBINS = 33
_LAT_OFF = 16  # bin index of net 0.0


def _lat_idx(x: float) -> int:
    """Lattice bin for a net payout (must be a multiple of 0.5 in [-8, 8])."""
    k = round(2.0 * x)
    if abs(2.0 * x - k) > 1e-9 or not -_LAT_OFF <= k <= _LAT_OFF:
        raise ValueError(f"payout {x} not on the half-unit lattice [-8, 8]")
    return int(k) + _LAT_OFF


def _add(t: int, s: bool, v: int) -> Tuple[int, bool]:
    """Add card value ``v`` to hand state (total, soft).

    ``soft`` means exactly one ace currently counted as 11.  Aces demote
    (11 -> 1) as needed; at most two demotions can be required (existing
    soft ace + newly drawn ace).
    """
    a = int(bool(s)) + (1 if v == 11 else 0)
    t += v
    while t > 21 and a:
        t -= 10
        a -= 1
    return t, a > 0


def _two(c1: int, c2: int) -> Tuple[int, bool]:
    """Hand state of the two-card hand (c1, c2) (values, ace = 11)."""
    return _add(c1, c1 == 11, c2)


def hand_value(card_indices) -> Tuple[int, bool]:
    """(total, soft) of a hand given card indices 0..51."""
    t, s = 0, False
    for i in card_indices:
        t, s = _add(t, s, int(CARD_VALUES[int(i)]))
    return t, s


# Default per-bet float budget for the vectorized simulator: 24 floats = 3
# HMAC digests.  A round consuming more than 24 cards requires a chain of
# a dozen-plus aces/tiny cards across four split hands plus the dealer —
# probability far below 1e-10 per round — and is handled exactly anyway by
# the scalar fallback in :meth:`Blackjack.simulate`.
_DEFAULT_FLOAT_BUDGET = 24
_SIM_CHUNK_ROUNDS = 500_000


class Blackjack:
    """Blackjack engine (infinite deck, provably fair, basic strategy).

    Parameters
    ----------
    dealer_hits_soft_17:
        False (default) = S17, the WoO infinite-deck reference rule.
    das:
        double after split allowed (default True, reference rule).
    max_hands:
        2, 3 or 4 (default 4 = three resplits, the WoO published-table
        rule "resplits capped at three, aces excluded"); aces are always
        split at most once regardless.
    bj_payout:
        net units paid for a winning natural (default 1.5 = 3:2, Stake's
        published payout).  Must be a multiple of 0.5.
    """

    def __init__(
        self,
        dealer_hits_soft_17: bool = False,
        das: bool = True,
        max_hands: int = 4,
        bj_payout: float = 1.5,
    ) -> None:
        if max_hands not in (2, 3, 4):
            raise ValueError("max_hands must be 2, 3 or 4")
        if abs(2 * bj_payout - round(2 * bj_payout)) > 1e-9 or not 0 < bj_payout <= 2:
            raise ValueError("bj_payout must be a multiple of 0.5 in (0, 2]")
        self.h17 = bool(dealer_hits_soft_17)
        self.das = bool(das)
        self.max_hands = int(max_hands)
        self.bj_payout = float(bj_payout)

        # Strategy tables (filled by _build), indexed [total, upcard-value]
        # (upcard value 2..11; rows/cols outside the valid range are False).
        self.HIT_HARD = np.zeros((22, 12), dtype=bool)
        self.HIT_SOFT = np.zeros((22, 12), dtype=bool)
        self.DBL_HARD = np.zeros((22, 12), dtype=bool)
        self.DBL_SOFT = np.zeros((22, 12), dtype=bool)
        self.SPLIT = np.zeros((12, 12), dtype=bool)  # [pair value, upcard]

        self._build()

    # ------------------------------------------------------------------
    # (a) exact analytics: dealer distribution, strategy DP, EV, variance
    # ------------------------------------------------------------------

    def _build(self) -> None:
        pv = P_VALUE

        # --- dealer final-category distribution -----------------------
        # Categories: index 0..4 = totals 17..21, index 5 = bust.
        dealer_memo: Dict[Tuple[int, bool], np.ndarray] = {}

        def dealer_cat(t: int, s: bool) -> np.ndarray:
            key = (t, s)
            hit17 = self.h17
            cached = dealer_memo.get(key)
            if cached is not None:
                return cached
            if t >= 18 or (t == 17 and not (s and hit17)):
                out = np.zeros(6)
                out[t - 17] = 1.0
            else:
                out = np.zeros(6)
                for v, p in pv.items():
                    t2, s2 = _add(t, s, v)
                    if t2 > 21:
                        out[5] += p
                    else:
                        out = out + p * dealer_cat(t2, s2)
            dealer_memo[key] = out
            return out

        self._dealer_nobj: Dict[int, np.ndarray] = {}
        self._p_dealer_bj: Dict[int, float] = {}
        for u in VALUES:
            excl = 10 if u == 11 else (11 if u == 10 else None)
            p_bj = pv[excl] if excl is not None else 0.0
            d = np.zeros(6)
            for v, p in pv.items():
                if v == excl:
                    continue  # peek: hole card cannot complete a natural
                t2, s2 = _add(u, u == 11, v)
                d = d + p * dealer_cat(t2, s2)
            self._dealer_nobj[u] = d / (1.0 - p_bj)
            self._p_dealer_bj[u] = p_bj

        # Probability the PLAYER's first two cards are a natural.
        self._p_player_bj = 2.0 * pv[11] * pv[10]

        total_ev = 0.0
        total_dist = np.zeros(_NBINS)
        self._ev_split_table: Dict[Tuple[int, int], float] = {}

        for u in VALUES:
            d = self._dealer_nobj[u]
            p_dbj = self._p_dealer_bj[u]

            # EV of standing on total t (dealer already known not to have a
            # natural; dealer 21s here are multi-card 21s).
            evs = np.empty(22)
            for t in range(22):
                win = d[5] + sum(d[c - 17] for c in range(17, 22) if c < t)
                lose = sum(d[c - 17] for c in range(17, 22) if c > t)
                evs[t] = win - lose

            # Optimal hit/stand DP (total-dependent = optimal, infinite deck).
            hs_memo: Dict[Tuple[int, bool], float] = {}
            hit_dec: Dict[Tuple[int, bool], bool] = {}

            def ev_hs(t: int, s: bool) -> float:
                key = (t, s)
                cached = hs_memo.get(key)
                if cached is not None:
                    return cached
                hit = 0.0
                for v, p in pv.items():
                    t2, s2 = _add(t, s, v)
                    hit += p * (-1.0 if t2 > 21 else ev_hs(t2, s2))
                dec = hit > evs[t]
                hit_dec[key] = dec
                val = hit if dec else float(evs[t])
                hs_memo[key] = val
                return val

            dbl_memo: Dict[Tuple[int, bool], float] = {}

            def ev_dbl(t: int, s: bool) -> float:
                key = (t, s)
                cached = dbl_memo.get(key)
                if cached is not None:
                    return cached
                tot = 0.0
                for v, p in pv.items():
                    t2, _ = _add(t, s, v)
                    tot += p * 2.0 * (evs[t2] if t2 <= 21 else -1.0)
                dbl_memo[key] = tot
                return tot

            def ev2(t: int, s: bool, dbl: bool) -> float:
                base = ev_hs(t, s)
                return max(base, ev_dbl(t, s)) if dbl else base

            # Fill strategy tables for this upcard.
            for t in range(4, 22):
                ev_hs(t, False)
                self.HIT_HARD[t, u] = hit_dec[(t, False)]
                self.DBL_HARD[t, u] = ev_dbl(t, False) > ev_hs(t, False)
            for t in range(12, 22):
                ev_hs(t, True)
                self.HIT_SOFT[t, u] = hit_dec[(t, True)]
                self.DBL_SOFT[t, u] = ev_dbl(t, True) > ev_hs(t, True)

            # Split EVs.  Resolution model (mirrored exactly by the players
            # in play_round/_play_chunk): a queue of pending one-card-r
            # hands, initially two, with max_hands - 2 further splits in
            # budget.  The front hand draws its second card c; if c == r
            # and budget remains, the hand splits immediately into two
            # pending hands (the drawn r starts the new hand); otherwise
            # the hand is played to completion before the next pending
            # hand draws.  EV recursion g(m, b) over (pending hands m,
            # split budget b); infinite deck makes hands independent, so
            # g(m, b) = sum_c p_c * [g(m+1, b-1) if c == r and b > 0 else
            # e_after(c) + g(m-1, b)].  Aces: one card each, no resplit,
            # no double.
            ev_split: Dict[int, float] = {}
            for r in VALUES:
                if r == 11:
                    one = 0.0
                    for v, p in pv.items():
                        t2, _ = _add(11, True, v)
                        one += p * evs[t2]
                    ev_split[r] = 2.0 * one
                else:
                    e_after = {}
                    for c, p in pv.items():
                        t2, s2 = _two(r, c)
                        e_after[c] = ev2(t2, s2, self.das)

                    g_memo: Dict[Tuple[int, int], float] = {}

                    def g(m: int, b: int, r=r, e_after=e_after) -> float:
                        if m == 0:
                            return 0.0
                        key = (m, b)
                        cached = g_memo.get(key)
                        if cached is not None:
                            return cached
                        tot = 0.0
                        for c, p in pv.items():
                            if c == r and b > 0:
                                tot += p * g(m + 1, b - 1)
                            else:
                                tot += p * (e_after[c] + g(m - 1, b))
                        g_memo[key] = tot
                        return tot

                    ev_split[r] = g(2, self.max_hands - 2)
                t0, s0 = _two(r, r)
                self.SPLIT[r, u] = ev_split[r] > ev2(t0, s0, True)
                self._ev_split_table[(r, u)] = ev_split[r]

            # --- payout DISTRIBUTION for this upcard ------------------
            # Final-total categories: 0..17 = totals 4..21, 18 = bust.
            fd_memo: Dict[Tuple[int, bool], np.ndarray] = {}

            def fdist(t: int, s: bool) -> np.ndarray:
                key = (t, s)
                cached = fd_memo.get(key)
                if cached is not None:
                    return cached
                ev_hs(t, s)  # ensure decision recorded
                if not hit_dec[key]:
                    out = np.zeros(19)
                    out[t - 4] = 1.0
                else:
                    out = np.zeros(19)
                    for v, p in pv.items():
                        t2, s2 = _add(t, s, v)
                        if t2 > 21:
                            out[18] += p
                        else:
                            out = out + p * fdist(t2, s2)
                fd_memo[key] = out
                return out

            def hand_fd(t: int, s: bool, dbl: bool) -> Tuple[np.ndarray, int]:
                """(final-total dist, wager) for a two-card hand played out."""
                if dbl and ev_dbl(t, s) > ev_hs(t, s):
                    out = np.zeros(19)
                    for v, p in pv.items():
                        t2, _ = _add(t, s, v)
                        if t2 > 21:
                            out[18] += p
                        else:
                            out[t2 - 4] += p
                    return out, 2
                return fdist(t, s), 1

            def paydist_given_d(fd: np.ndarray, w: int, dcat: int) -> np.ndarray:
                """Net-payout lattice dist of one hand vs dealer category."""
                vec = np.zeros(_NBINS)
                for f_idx in range(19):
                    pf = fd[f_idx]
                    if pf == 0.0:
                        continue
                    if f_idx == 18:  # player bust loses even to dealer bust
                        res = -w
                    elif dcat == 5:  # dealer bust
                        res = w
                    else:
                        ft, dtot = f_idx + 4, 17 + dcat
                        res = w if ft > dtot else (-w if ft < dtot else 0)
                    vec[2 * res + _LAT_OFF] += pf
                return vec

            def conv(a: np.ndarray, b: np.ndarray) -> np.ndarray:
                """Lattice convolution (sum of independent hand payouts)."""
                return np.convolve(a, b)[_LAT_OFF:_LAT_OFF + _NBINS]

            def split_dist(r: int) -> np.ndarray:
                out = np.zeros(_NBINS)
                if r == 11:
                    fd = np.zeros(19)
                    for v, p in pv.items():
                        t2, _ = _add(11, True, v)
                        fd[t2 - 4] += p
                    for dcat in range(6):
                        g1 = paydist_given_d(fd, 1, dcat)
                        out += d[dcat] * conv(g1, g1)
                    return out
                # Same pending-hand recursion as the EV (see ev_split
                # above), on the payout lattice: gd(m, b) is the net
                # distribution of m pending one-card-r hands with b splits
                # left, conditioned on the dealer category.
                pd_after: Dict[int, np.ndarray] = {}
                comps = []  # per second-card component: (c, p, fd, w)
                for c, p in pv.items():
                    t2, s2 = _two(r, c)
                    fd_c, w_c = hand_fd(t2, s2, self.das)
                    comps.append((c, p, fd_c, w_c))
                delta0 = np.zeros(_NBINS)
                delta0[_LAT_OFF] = 1.0
                for dcat in range(6):
                    for c, _p, fd_c, w_c in comps:
                        pd_after[c] = paydist_given_d(fd_c, w_c, dcat)

                    gd_memo: Dict[Tuple[int, int], np.ndarray] = {}

                    def gd(m: int, b: int, r=r, pd_after=pd_after) -> np.ndarray:
                        if m == 0:
                            return delta0
                        key = (m, b)
                        cached = gd_memo.get(key)
                        if cached is not None:
                            return cached
                        acc = np.zeros(_NBINS)
                        for c, p in pv.items():
                            if c == r and b > 0:
                                acc = acc + p * gd(m + 1, b - 1)
                            else:
                                acc = acc + p * conv(pd_after[c], gd(m - 1, b))
                        gd_memo[key] = acc
                        return acc

                    out += d[dcat] * gd(2, self.max_hands - 2)
                return out

            inner_ev = 0.0
            inner_dist = np.zeros(_NBINS)
            split_cache: Dict[int, np.ndarray] = {}
            hand_cache: Dict[Tuple[int, int], Tuple[float, np.ndarray]] = {}
            for c1 in VALUES:
                for c2 in VALUES:
                    if (c1, c2) in ((10, 11), (11, 10)):
                        continue  # naturals handled at round level
                    p12 = pv[c1] * pv[c2]
                    if c1 == c2 and self.SPLIT[c1, u]:
                        if c1 not in split_cache:
                            split_cache[c1] = split_dist(c1)
                        ev_h = ev_split[c1]
                        dist_h = split_cache[c1]
                    else:
                        key = (min(c1, c2), max(c1, c2))
                        if key not in hand_cache:
                            t0, s0 = _two(c1, c2)
                            ev_h0 = ev2(t0, s0, True)
                            fd0, w0 = hand_fd(t0, s0, True)
                            dist0 = np.zeros(_NBINS)
                            for dcat in range(6):
                                dist0 += d[dcat] * paydist_given_d(fd0, w0, dcat)
                            hand_cache[key] = (ev_h0, dist0)
                        ev_h, dist_h = hand_cache[key]
                    inner_ev += p12 * ev_h
                    inner_dist = inner_dist + p12 * dist_h

            p_pbj = self._p_player_bj
            u_ev = p_dbj * ((1.0 - p_pbj) * -1.0) + (1.0 - p_dbj) * (
                p_pbj * self.bj_payout + inner_ev
            )
            u_dist = np.zeros(_NBINS)
            u_dist[_lat_idx(0.0)] += p_dbj * p_pbj  # both naturals: push
            u_dist[_lat_idx(-1.0)] += p_dbj * (1.0 - p_pbj)
            u_dist[_lat_idx(self.bj_payout)] += (1.0 - p_dbj) * p_pbj
            u_dist += (1.0 - p_dbj) * inner_dist

            total_ev += pv[u] * u_ev
            total_dist += pv[u] * u_dist

        mass = float(total_dist.sum())
        if abs(mass - 1.0) > 1e-9:
            raise AssertionError(f"payout distribution mass {mass} != 1")
        mean = float(total_dist @ _LATTICE)
        if abs(mean - total_ev) > 1e-9:
            raise AssertionError(
                f"distribution mean {mean} disagrees with EV DP {total_ev}"
            )
        self._ev = total_ev
        self.payout_dist = total_dist
        self.variance_per_unit = float(total_dist @ (_LATTICE**2) - mean * mean)

    # --- analytic properties -------------------------------------------

    @property
    def ev(self) -> float:
        """Exact expected NET payout per unit initial bet (negative)."""
        return self._ev

    @property
    def rtp(self) -> float:
        return 1.0 + self._ev

    @property
    def house_edge(self) -> float:
        return -self._ev

    @property
    def std_per_unit(self) -> float:
        return math.sqrt(self.variance_per_unit)

    @staticmethod
    def insurance_ev() -> float:
        """EV per unit insurance bet: pays 2:1, dealer natural odds 4/13."""
        return INSURANCE_PAYS * (4.0 / 13.0) - (9.0 / 13.0)

    def payout_distribution(self) -> Dict[float, float]:
        """{net payout: exact probability} over the half-unit lattice."""
        return {
            float(x): float(p)
            for x, p in zip(_LATTICE, self.payout_dist)
            if p > 0.0
        }

    def outcome_probabilities(self) -> Dict[str, float]:
        """Summary probabilities of the round's net result."""
        dist = self.payout_dist
        return {
            "win": float(dist[_LATTICE > 0].sum()),
            "push": float(dist[_LATTICE == 0].sum()),
            "loss": float(dist[_LATTICE < 0].sum()),
            "blackjack_win": float(dist[_lat_idx(self.bj_payout)])
            if self.bj_payout != 1.0
            else float("nan"),
        }

    def config(self) -> Dict[str, object]:
        return {
            "game": "blackjack",
            "decks": "infinite",
            "dealer_soft_17": "hit" if self.h17 else "stand",
            "double": "any first two cards, one card dealt",
            "das": self.das,
            "max_hands": self.max_hands,
            "split_aces": "once, one card each",
            "resplit_non_aces": self.max_hands > 2,
            "surrender": False,
            "dealer_peeks": True,
            "blackjack_pays": self.bj_payout,
            "standard_win_pays": 1.0,
            "insurance_pays": INSURANCE_PAYS,
            "insurance_taken": False,
            "strategy": "derived optimal total-dependent basic strategy",
        }

    def analytic_summary(self) -> Dict[str, object]:
        """Standard result dict, exact analytic (no simulation)."""
        return {
            "rtp": self.rtp,
            "house_edge": self.house_edge,
            "std_per_unit": self.std_per_unit,
            "config": self.config(),
        }

    # ------------------------------------------------------------------
    # (b) provably-fair single round (scalar verification path)
    # ------------------------------------------------------------------

    def play_round(
        self, server_seed: str, client_seed: str, nonce: int
    ) -> Dict[str, object]:
        """Play one verifiable basic-strategy round.

        Cards are drawn in stream order — player 1, dealer upcard, player 2,
        dealer hole card, then exactly as needed (split hands in order, one
        hand played to completion before the next is dealt; dealer only if
        at least one player hand stands).  The vectorized simulator consumes
        the identical sequence, so payouts match per nonce bit-for-bit.
        """
        gen = sq_rng.byte_generator(server_seed, client_seed, nonce)
        drawn: List[int] = []

        def card() -> int:
            b0, b1, b2, b3 = next(gen), next(gen), next(gen), next(gen)
            f = (
                b0 / 256 + b1 / 256**2 + b2 / 256**3 + b3 / 256**4
            )  # == k / 2**32, exact (see rng.generate_floats)
            idx = math.floor(f * _DECK)
            drawn.append(idx)
            return int(CARD_VALUES[idx])

        v1 = card()
        u = card()
        v2 = card()
        hv = card()
        player_bj = {v1, v2} == {10, 11}
        dealer_bj = {u, hv} == {10, 11}

        hands: List[Dict[str, object]] = []
        actions: List[str] = []

        def finish(net: float, dealer_total: int, dealer_soft: bool) -> Dict[str, object]:
            total_bet = sum(int(h["wager"]) for h in hands) if hands else 1
            return {
                "net": net,
                "total_bet": total_bet,
                "total_returned": total_bet + net,
                "player_blackjack": player_bj,
                "dealer_blackjack": dealer_bj,
                "hands": hands,
                "dealer_total": dealer_total,
                "dealer_bust": dealer_total > 21,
                "actions": actions,
                "cards": list(drawn),
                "card_names": [sq_rng.CARDS[i] for i in drawn],
                "config": self.config(),
                "verification": {
                    "server_seed": server_seed,
                    "client_seed": client_seed,
                    "nonce": nonce,
                },
            }

        dt, dsf = _two(u, hv)
        if player_bj or dealer_bj:
            if player_bj and dealer_bj:
                net = 0.0
                actions.append("push: both naturals")
            elif player_bj:
                net = self.bj_payout
                actions.append("player blackjack")
            else:
                net = -1.0
                actions.append("dealer blackjack")
            hands.append(
                {"total": _two(v1, v2)[0], "wager": 1, "bust": False, "cards": 2}
            )
            return finish(net, dt, dsf)

        def play(t: int, s: bool, allow_double: bool) -> Tuple[int, int, int]:
            """Play a two-card hand; returns (final total, wager, n_cards)."""
            n = 2
            if allow_double and (self.DBL_SOFT if s else self.DBL_HARD)[t, u]:
                t, s = _add(t, s, card())
                actions.append(f"double -> {t}")
                return t, 2, 3
            while t <= 21 and (self.HIT_SOFT if s else self.HIT_HARD)[t, u]:
                t, s = _add(t, s, card())
                n += 1
                actions.append(f"hit -> {t}")
            actions.append("bust" if t > 21 else f"stand {t}")
            return t, 1, n

        def add_hand(t: int, w: int, n: int) -> None:
            hands.append({"total": t, "wager": w, "bust": t > 21, "cards": n})

        pair = v1 == v2
        if pair and bool(self.SPLIT[v1, u]):
            if v1 == 11:
                actions.append("split aces")
                for _ in range(2):
                    t, _s = _add(11, True, card())
                    add_hand(t, 1, 2)
            else:
                # Pending-hand queue: the front one-card-r hand draws its
                # second card; drawing r with split budget left resplits
                # immediately (the drawn r starts a new pending hand);
                # otherwise the hand is played to completion before the
                # next pending hand draws.  Mirrors ev_split/split_dist
                # and _play_chunk exactly, card for card.
                r = v1
                actions.append(f"split {r}s")
                pending = 2
                splits_left = self.max_hands - 2
                while pending > 0:
                    c = card()
                    if c == r and splits_left > 0:
                        splits_left -= 1
                        pending += 1
                        actions.append(f"resplit {r}s")
                        continue
                    t, s = _add(r, False, c)
                    t, w, n = play(t, s, self.das)
                    add_hand(t, w, n)
                    pending -= 1
        else:
            t, s = _two(v1, v2)
            t, w, n = play(t, s, True)
            add_hand(t, w, n)

        if any(not h["bust"] for h in hands):
            while dt < 17 or (self.h17 and dt == 17 and dsf):
                dt, dsf = _add(dt, dsf, card())
            actions.append(f"dealer {'bust' if dt > 21 else dt}")

        net = 0.0
        for h in hands:
            w = int(h["wager"])
            if h["bust"]:
                net -= w
            elif dt > 21 or int(h["total"]) > dt:
                net += w
            elif int(h["total"]) < dt:
                net -= w
        return finish(net, dt, dsf)

    # ------------------------------------------------------------------
    # (c) vectorized simulator
    # ------------------------------------------------------------------

    def _play_chunk(self, vals: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Play one chunk of rounds.

        ``vals``: (N, budget) int16 card VALUES in stream order.  Returns
        (net payouts float64 (N,), overflow bool (N,)); overflow rounds
        attempted to draw past the budget and must be replayed scalar.
        """
        n, budget = vals.shape
        cur = np.full(n, 4, dtype=np.int64)
        overflow = np.zeros(n, dtype=bool)

        def draw(mask: np.ndarray) -> np.ndarray:
            out = np.zeros(n, dtype=np.int16)
            rows = np.nonzero(mask)[0]
            if rows.size == 0:
                return out
            idx = cur[rows]
            over = idx >= budget
            if over.any():
                overflow[rows[over]] = True
            idx = np.minimum(idx, budget - 1)
            out[rows] = vals[rows, idx]
            cur[rows] = idx + 1
            return out

        def vadd_masked(t: np.ndarray, s: np.ndarray, v: np.ndarray, m: np.ndarray) -> None:
            tm = t[m] + v[m]
            am = s[m].astype(np.int16) + (v[m] == 11)
            for _ in range(2):
                k = (tm > 21) & (am > 0)
                tm = tm - 10 * k
                am = am - k
            t[m] = tm
            s[m] = am > 0

        v1 = vals[:, 0].astype(np.int64)
        up = vals[:, 1].astype(np.int64)
        v2 = vals[:, 2].astype(np.int64)
        hole = vals[:, 3].astype(np.int64)

        net = np.zeros(n, dtype=np.float64)
        p_bj = ((v1 == 11) & (v2 == 10)) | ((v1 == 10) & (v2 == 11))
        d_bj = ((up == 11) & (hole == 10)) | ((up == 10) & (hole == 11))
        net[p_bj & ~d_bj] = self.bj_payout
        net[d_bj & ~p_bj] = -1.0
        live = ~(p_bj | d_bj)

        max_h = self.max_hands
        ft = np.zeros((n, max_h), dtype=np.int16)  # final totals; > 21 = bust
        wg = np.ones((n, max_h), dtype=np.int16)
        nh = np.zeros(n, dtype=np.int16)

        hit_hard, hit_soft = self.HIT_HARD, self.HIT_SOFT
        dbl_hard, dbl_soft = self.DBL_HARD, self.DBL_SOFT

        def play(m: np.ndarray, t: np.ndarray, s: np.ndarray, w: np.ndarray,
                 allow_double: bool) -> None:
            """Play two-card hands at mask ``m`` in place; w gets 2 on doubles."""
            if allow_double:
                tt = np.minimum(t, 21)
                dbl = m & np.where(s, dbl_soft[tt, up], dbl_hard[tt, up])
                if dbl.any():
                    c = draw(dbl)
                    vadd_masked(t, s, c, dbl)
                    w[dbl] = 2
                hm = m & ~dbl
            else:
                hm = m
            while True:
                tt = np.minimum(t, 21)
                want = hm & (t <= 21) & np.where(s, hit_soft[tt, up], hit_hard[tt, up])
                if not want.any():
                    break
                c = draw(want)
                vadd_masked(t, s, c, want)

        # --- non-split rounds ------------------------------------------
        pair = live & (v1 == v2)
        do_split = pair & self.SPLIT[v1, up]
        m1 = live & ~do_split
        if m1.any():
            t = (v1 + v2).astype(np.int16)
            a = (v1 == 11).astype(np.int16) + (v2 == 11)
            for _ in range(2):
                k = (t > 21) & (a > 0)
                t = t - 10 * k
                a = (a - k).astype(np.int16)
            s = a > 0
            play(m1, t, s, wg[:, 0], True)
            ft[m1, 0] = t[m1]
            nh[m1] = 1

        # --- split rounds ----------------------------------------------
        m_a = do_split & (v1 == 11)  # aces: one card each, forced stand
        if m_a.any():
            for j in range(2):
                c = draw(m_a)
                t = np.full(n, 11, dtype=np.int16)
                s = np.ones(n, dtype=bool)
                vadd_masked(t, s, c, m_a)
                ft[m_a, j] = t[m_a]
            nh[m_a] = 2

        m_s = do_split & (v1 != 11)
        if m_s.any():
            # Vectorized pending-hand queue, identical card order to
            # play_round: per row, the front pending hand draws; a drawn r
            # with split budget left resplits (pending += 1); otherwise
            # the hand plays to completion (double/hits) before the next
            # pending hand draws.  Per-row draw order is preserved because
            # draw() advances per-row cursors independently.
            r = v1.astype(np.int16)
            pending = np.where(m_s, 2, 0).astype(np.int16)
            left = np.where(m_s, max_h - 2, 0).astype(np.int16)
            hidx = np.zeros(n, dtype=np.int64)
            active = m_s & (pending > 0)
            while active.any():
                c = draw(active)
                is_sp = active & (c == r) & (left > 0)
                if is_sp.any():
                    left[is_sp] -= 1
                    pending[is_sp] += 1
                resolve = active & ~is_sp
                if resolve.any():
                    t = r.copy()
                    s = np.zeros(n, dtype=bool)
                    vadd_masked(t, s, c, resolve)
                    wtmp = np.ones(n, dtype=np.int16)
                    play(resolve, t, s, wtmp, self.das)
                    rows = np.nonzero(resolve)[0]
                    ft[rows, hidx[rows]] = t[rows]
                    wg[rows, hidx[rows]] = wtmp[rows]
                    hidx[rows] += 1
                    pending[rows] -= 1
                active = m_s & (pending > 0)
            nh[m_s] = hidx[m_s]

        # --- dealer ----------------------------------------------------
        hand_used = np.arange(max_h, dtype=np.int16)[None, :] < nh[:, None]
        any_standing = (hand_used & (ft <= 21)).any(axis=1)
        md = live & any_standing
        dt = (up + hole).astype(np.int16)
        a = (up == 11).astype(np.int16) + (hole == 11)
        for _ in range(2):
            k = (dt > 21) & (a > 0)
            dt = dt - 10 * k
            a = (a - k).astype(np.int16)
        ds = a > 0
        while True:
            want = md & ((dt < 17) | (self.h17 & (dt == 17) & ds))
            if not want.any():
                break
            c = draw(want)
            vadd_masked(dt, ds, c, want)

        # --- settle ----------------------------------------------------
        d_bust = dt > 21
        for j in range(max_h):
            hj = live & (nh > j)
            if not hj.any():
                continue
            f = ft[:, j].astype(np.int64)
            w = wg[:, j].astype(np.int64)
            res = np.where(f > 21, -w, np.where(d_bust, w, np.sign(f - dt) * w))
            net[hj] += res[hj]
        return net, overflow

    def simulate(
        self,
        n_rounds: int,
        bulk: Optional[BulkRng] = None,
        chunk_rounds: int = _SIM_CHUNK_ROUNDS,
        progress: bool = True,
        float_budget: int = _DEFAULT_FLOAT_BUDGET,
        keep_payouts: bool = False,
    ) -> Dict[str, object]:
        """Simulate ``n_rounds`` provably-fair rounds (one nonce per round)
        on the vectorized :class:`BulkRng` stream; standard result dict.

        ``float_budget`` floats (= cards) are generated per bet; any round
        that would need more is replayed exactly on the scalar path (same
        seeds and nonce — the byte stream is open-ended there), so results
        are exact for every round regardless of budget.  Chunked so
        per-chunk arrays stay ~100 MB; prints progress for long campaigns.
        """
        if n_rounds <= 0:
            raise ValueError("n_rounds must be positive")
        if float_budget < 6:
            raise ValueError("float_budget must be at least 6 (4 deal + 2)")
        rng = bulk if bulk is not None else BulkRng()
        nonce_first = rng.nonce_next

        s1 = 0.0
        s2 = 0.0
        hist = np.zeros(_NBINS, dtype=np.int64)
        n_overflow = 0
        kept: List[np.ndarray] = []
        done = 0
        t0 = time.perf_counter()
        while done < n_rounds:
            step = min(chunk_rounds, n_rounds - done)
            chunk_nonce0 = rng.nonce_next
            # card_hands is BulkRng's per-bet blackjack/hilo method: ONE
            # nonce per round, float_budget independent floor(f*52) draws
            # from that round's stream — the event accounting lives in the
            # RNG core, not re-derived here.
            cards = rng.card_hands(float_budget, step)
            vals = CARD_VALUES[cards]
            del cards
            net, ov = self._play_chunk(vals)
            if ov.any():
                for i in np.nonzero(ov)[0]:
                    net[i] = self.play_round(
                        rng.server_seed, rng.client_seed, chunk_nonce0 + int(i)
                    )["net"]
                n_overflow += int(ov.sum())
            s1 += float(net.sum())
            s2 += float((net * net).sum())
            bins = np.rint(net * 2.0).astype(np.int64) + _LAT_OFF
            if bins.min() < 0 or bins.max() >= _NBINS:
                bad = net[(bins < 0) | (bins >= _NBINS)]
                raise AssertionError(
                    f"net payout(s) off the [-8, 8] lattice: {bad[:5]}"
                )
            hist += np.bincount(bins, minlength=_NBINS)
            if keep_payouts:
                kept.append(net)
            done += step
            if progress and n_rounds > chunk_rounds:
                rate = done / (time.perf_counter() - t0)
                print(
                    f"  blackjack: {done:,}/{n_rounds:,} rounds ({rate:,.0f}/s)",
                    flush=True,
                )
        elapsed = time.perf_counter() - t0

        mean = s1 / n_rounds
        var = max(s2 / n_rounds - mean * mean, 0.0)
        std_emp = math.sqrt(var)
        se = self.std_per_unit / math.sqrt(n_rounds)
        z = (mean - self._ev) / se if se > 0 else 0.0
        result: Dict[str, object] = {
            "rtp": 1.0 + mean,
            "house_edge": -mean,
            "std_per_unit": std_emp,
            "config": self.config(),
            "n_rounds": n_rounds,
            "mean_net": mean,
            "analytic_rtp": self.rtp,
            "analytic_house_edge": self.house_edge,
            "analytic_std_per_unit": self.std_per_unit,
            "se_rtp": se,
            "z_score": z,
            "within_3se": abs(z) <= 3.0,
            "payout_hist": hist.tolist(),
            "payout_lattice": _LATTICE.tolist(),
            "overflow_rounds": n_overflow,
            "float_budget": float_budget,
            "elapsed_s": elapsed,
            "rounds_per_sec": n_rounds / elapsed if elapsed > 0 else float("inf"),
            "verification": {
                "server_seed_hash": rng.server_seed_hash,
                "client_seed": rng.client_seed,
                "nonce_range": (nonce_first, rng.nonce_next),
            },
        }
        if keep_payouts:
            result["payouts"] = np.concatenate(kept)
        return result
