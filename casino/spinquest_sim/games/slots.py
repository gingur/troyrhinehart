"""Slots — representative published-RTP par-sheet models (5x3 line slots).

Two models, one engine (:class:`SlotMachine` — a generic 5-reel, 3-row,
20-payline video slot with wilds, scatters and retriggerable free spins):

**1. "Atkins deconstruction" (primary; references/woo/slots.md).**
The Wizard of Odds' Atkins Diet deconstruction is his canonical
fully-published slot model: 5 reels x 32 stops -> 32^5 = 33,554,432 equally
likely outcomes, exactly enumerated.  The reference captures his published
AGGREGATES — total return 97.046% split into line pays 63.460% + scatter
6.976% + free-spin feature 26.610%, hit frequency 5.45% per line,
P(3+ scatters) = 0.011185 triggering 10 free spins with all wins tripled,
retriggers giving E[spins/bonus] = 11.259335 and E[bonus win] =
23.791632 x bet — but NOT the underlying reel strips or symbol paytable
(the reference .md files are the only ground truth here; the live WoO page
was not consulted).  The published figures are internally consistent and
pin the model completely:

    E[spins]     = 10 / (1 - 10 * 0.011185)            = 11.259337
    E[bonus win] = 3 * (0.63460 + 0.06976) * E[spins]  = 23.79174
    bonus return = 0.011185 * E[bonus win]             = 0.266105
    total        = 0.63460 + 0.06976 + bonus return    = 0.970465 -> 97.046%

so this module ships an Atkins-style par sheet (11 symbols: the Atkins
wild, 9 food symbols, the Scale scatter) whose reel strips are the output
of ``scripts/calibrate_slots.py`` — a fully deterministic, committed,
re-runnable search (exact integer arithmetic, no randomness anywhere):
because the per-line marginal depends only on per-reel symbol COUNTS and
the scatter figures only on scatters-per-reel (spaced >= 3), the eight
published figures pin the single-line pay sum to the one attainable
integer M* = 21,293,527 = line_return * 32^5, and the script finds the
count matrix hitting M* EXACTLY (meet-in-the-middle over one reel, joint
with a bounded box on a second), then arranges the counts into strips.
Exact 32^5 enumeration of the strips reproduces every published aggregate
at its printed precision — each one PRINTS as WoO printed it (see
``WOO_ATKINS_PRINTED``) and sits within half an ULP of the printed figure
(``WOO_ATKINS_TOL``).  ``enumerate_exact`` re-derives all of them from the
strips alone — nothing is asserted that is not recomputed.

**2. Scarab Spin / Tome of Life (secondary; references/stake/slots.md).**
Stake's fixed-reel Originals slot pair: 5x3, 20 lines, published house edge
2.16% / RTP 97.84%, reel geometry 30/30/30/30/41 central stops.  Stake
publishes the COMPLETE line paytable payout-for-payout (transcribed below
symbol-for-symbol; Tome of Life's table is identical), the bonus rule
(3 scatters -> 15 free spins), the max win (10,000x the bet), the wild
mechanic — "random wilds in the base game, represented by King Tut's
mask. Wild symbols substitute for all symbols except scatter symbols"
(reference Sect. 4, verbatim) — and, critically, the EVENT MATH: "This
game consists of 5 game event numbers, until the case of a bonus round,
where more are generated" (Sect. 3a, verbatim), with the stop mapping
``floor(float * reel_length)`` that is already in the verified RNG core
(:func:`spinquest_sim.rng.scarab_spin_stops`,
``rng.EVENT_COUNTS["scarab_spin"] == 5``).  A base spin therefore
consumes EXACTLY 5 floats — one per reel, nothing else — and this engine
does exactly that, base and free spins alike, through the verified core.
What Stake does NOT publish are the reel strips (Sect. 7).

The reconstruction is therefore split into what the reference pins and
what must be calibrated:

* The PAYTABLE is transcribed payout-for-payout (wins multiply the bet per
  line, not the total bet; the scatter pays 2+ anywhere on the reels —
  both published verbatim).
* The REEL STRIPS — including the King Tut wild, which occupies real strip
  stops (1-2 per reel, ``SCARAB_COUNTS`` column 11): wilds land in the
  base game from the reels themselves, the only reading of "random wilds
  in the base game" consistent with the published 5-floats-per-spin event
  math.  The full count matrix (11 line symbols + wild + scatter per
  reel) is the deterministic output of ``scripts/calibrate_slots.py``: a
  conventional descending par-sheet ladder (counts monotone
  non-increasing in 5-of-a-kind pay on every reel, Spearman(pay, total
  count) <= -0.9 with the wild among the rarest paying symbols, per-reel
  count cv >= 0.4, all five count vectors distinct, wild's own row
  carrying <= 20% of the line return) solved EXACTLY, by big-integer
  contraction of the paytable LUT, so that the full-round RTP prints the
  published "97.84" (``SCARAB_SHAPE_GATES``).
* The SCATTER density is the published free-spin engine's throttle and is
  the one degree of freedom that can carry a 97.84% total on this
  paytable: the published table tops out at 37.50x bet-per-line for a
  regular 5-of-a-kind, so ANY descending ladder's base return is a few
  percent of the total bet (ours, exactly: line 2.13% + scatter 6.30% =
  8.44%).  The published bonus rule (3+ scatters -> 15 free spins,
  retriggerable, same reels, no multiplier stated for Scarab) amplifies a
  base return mu into RTP = mu / (1 - 15p), so the published 97.84% pins
  15p = 1 - mu/0.9784: the calibration places 2/2/2/2/3 scatters (spaced
  >= 3 on every reel, so a 3-row window never shows two scatters per
  reel), giving the exact trigger probability p = 0.06091707... and
  E[spins per bonus] = 173.9 — long retrigger chains, exactly the regime
  Stake's own Tome of Life page corroborates with its published bonus cap
  of "respins up to an impressive 180 times".  EVERY spin, base or free,
  has the identical win distribution (mu = 8.44% of the total bet per
  spin) — there is no fire/non-fire barbell, no overlay, no unpublished
  mechanism, and no fitted threshold anywhere: the RTP comes from the
  count matrix, i.e. from the par sheet itself.

The exact full-round RTP of the shipped par sheet is the rational
7,005,731/7,160,400 = 0.978399391095... — within 6.1e-7 of the published
0.9784 against the half-ULP window of the printed figure (5e-5) — and it
prints "97.84" (house edge "2.16").  Base-game shape (all recomputed,
none asserted): 44.01% of spins hit a line (exact 30^4*41 enumeration;
vs the only published 20-line hit frequency, Cleopatra's 35.88%),
per-line hit frequency 5.35%, full-round relative SD 12.60 inside the
published slot band 5.18-13.45, and the wild's own row carries 5.5% of
the line return.  The published 10,000x-bet max win is enforced as a
payout cap on every round (the cap binds with probability too small to
affect any analytic figure at double precision).

**Engine contract** (same as every other game in this package):

(a) analytic paytable / probability / RTP / variance computation — exact
    enumeration of ALL reel-stop combinations (32^5 for Atkins, 30^4*41
    for Scarab), first moments in exact integer / Fraction arithmetic,
    second moments in float64, cross-checked in the tests against an
    independent count-marginal contraction;
(b) provably-fair single-round play on the verified scalar RNG path
    (exactly 5 floats -> 5 central stops per spin, routed through
    rng.scarab_spin_stops for the published 30/30/30/30/41 geometry;
    bonus spins keep consuming the SAME nonce's byte stream, matching
    Stake's published "Slots: the incremental number is only utilised for
    bonus rounds"),
(c) a vectorized numpy simulator for 10M+ rounds on :class:`BulkRng`
    (base spins bulk; the rounds that trigger the bonus are resolved from
    the identical per-nonce byte stream and evaluated vectorized),
(d) the standard result dict {rtp, house_edge, std_per_unit, config}.

Free-spin math (exact, used by the analytics): let Y = one spin's base win
per unit total bet (line + scatter pays), Z = 1{spin triggers}, p = P(Z=1),
F = spins per (re)trigger, m = free-spin win multiplier.  A trigger awards
the package T = sum_{i=1..F} (m*Y_i + Z_i*T_i') with (Y_i, Z_i) iid copies
of (Y, Z) and T_i' iid copies of T:

    E[T]  = F*m*E[Y] / (1 - F*p)
    E[T^2]*(1 - F*p) = F*(m^2 E[Y^2] + 2m E[YZ] E[T]) + F(F-1) (E[T]/F)^2

and a full round pays X = Y + Z*T, so

    RTP     = E[X]  = E[Y] + p E[T]
    E[X^2]  = E[Y^2] + 2 E[YZ] E[T] + p E[T^2]
    Var(X)  = E[X^2] - E[X]^2,   std_per_unit = sqrt(Var(X)).

The 20 payline patterns are the classic 5x3 set; because each reel stop is
uniform over a cyclic strip, every payline has the IDENTICAL win
distribution (per-line marginals depend only on per-reel symbol counts),
so the pattern choice affects only inter-line correlation (variance), not
any published return figure.
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import math
import time
from fractions import Fraction
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from spinquest_sim import rng as sq_rng
from spinquest_sim.rng import BulkRng

__all__ = [
    "PAYLINES_20",
    "N_LINES",
    "ROWS",
    "ATKINS_SYMBOLS",
    "ATKINS_LINE_PAYS",
    "ATKINS_SCATTER_PAYS",
    "ATKINS_STRIPS",
    "SCARAB_SYMBOLS",
    "SCARAB_LINE_PAYS",
    "SCARAB_SCATTER_PAYS",
    "SCARAB_COUNTS",
    "SCARAB_SCATTER_POS",
    "SCARAB_STRIPS",
    "SCARAB_MAX_WIN",
    "SCARAB_FLOATS_PER_SPIN",
    "SCARAB_SHAPE_GATES",
    "WOO_ATKINS_PUBLISHED",
    "WOO_ATKINS_PRINTED",
    "WOO_SLOT_SD_BAND",
    "WOO_TYPICAL_SLOT_SD",
    "WOO_CLEOPATRA_HIT_20LINE",
    "STAKE_SCARAB_PUBLISHED",
    "STAKE_SCARAB_PRINTED",
    "SlotMachine",
    "atkins_machine",
    "scarab_machine",
    "tome_of_life_machine",
]

ROWS = 3                       # visible rows; stop = CENTRAL row position
N_LINES = 20                   # both models: 20 lines, 1 line-bet each
_SAFETY_SPIN_CAP = 100_000     # free-spin safety cap (P ~ 0 at any horizon)

# The classic 20-line pattern set for a 5x3 grid (row per reel; 0=top,
# 1=middle, 2=bottom).  Marginals are pattern-independent (see module doc).
PAYLINES_20: Tuple[Tuple[int, ...], ...] = (
    (1, 1, 1, 1, 1), (0, 0, 0, 0, 0), (2, 2, 2, 2, 2), (0, 1, 2, 1, 0),
    (2, 1, 0, 1, 2), (1, 0, 0, 0, 1), (1, 2, 2, 2, 1), (0, 0, 1, 2, 2),
    (2, 2, 1, 0, 0), (1, 2, 1, 0, 1), (1, 0, 1, 2, 1), (0, 1, 1, 1, 0),
    (2, 1, 1, 1, 2), (0, 1, 0, 1, 0), (2, 1, 2, 1, 2), (1, 1, 0, 1, 1),
    (1, 1, 2, 1, 1), (0, 2, 0, 2, 0), (2, 0, 2, 0, 2), (1, 0, 2, 0, 1),
)

# ---------------------------------------------------------------------------
# Published reference figures (targets the computations must reproduce)
# ---------------------------------------------------------------------------

# references/woo/slots.md — WoO Atkins Diet deconstruction, published
# aggregates at their printed precision.
WOO_ATKINS_PUBLISHED: Dict[str, float] = {
    "total_rtp": 0.97046,          # "97.046%"
    "line_return": 0.63460,        # "line pays 63.460%"
    "scatter_return": 0.06976,     # "scatter pay 6.976%"
    "bonus_return": 0.26610,       # "bonus (free-spin) feature 26.610%"
    "hit_frequency": 0.0545,       # "hit frequency 5.45% per line"
    "p_bonus_trigger": 0.011185,   # "3+ scatters (probability 0.011185)"
    "expected_bonus_spins": 11.259335,
    "expected_bonus_win": 23.791632,   # x total bet
    "outcomes": 32 ** 5,           # "32^5 = 33,554,432 equally likely"
}

# TRUE half-ULP tolerances of each figure's printed precision — no figure
# is loosened past half an ULP of what WoO printed (97.046% -> 5e-6 on the
# fraction; 5.45% -> 5e-5; 0.011185 / 11.259335 / 23.791632 -> 5e-7 on the
# last printed digit).
WOO_ATKINS_TOL: Dict[str, float] = {
    "total_rtp": 5.0e-6,
    "line_return": 5.0e-6,
    "scatter_return": 5.0e-6,
    "bonus_return": 5.0e-6,
    "hit_frequency": 5.0e-5,
    "p_bonus_trigger": 5.0e-7,
    "expected_bonus_spins": 5.0e-7,
    "expected_bonus_win": 5.0e-7,
}

# The stronger gate: every figure must PRINT, at WoO's printed precision,
# as the exact string WoO printed.  {figure: (enumerate_exact key, scale,
# format spec, expected printed string)} — tests and validate_slots.py gate
# on these strings, not just on float tolerances.
WOO_ATKINS_PRINTED: Dict[str, Tuple[str, float, str, str]] = {
    "total_rtp": ("rtp", 100.0, ".3f", "97.046"),
    "line_return": ("line_return", 100.0, ".3f", "63.460"),
    "scatter_return": ("scatter_return", 100.0, ".3f", "6.976"),
    "bonus_return": ("bonus_return", 100.0, ".3f", "26.610"),
    "hit_frequency": ("hit_frequency", 100.0, ".2f", "5.45"),
    "p_bonus_trigger": ("p_bonus_trigger", 1.0, ".6f", "0.011185"),
    "expected_bonus_spins": ("expected_bonus_spins", 1.0, ".6f", "11.259335"),
    "expected_bonus_win": ("expected_bonus_win", 1.0, ".6f", "23.791632"),
}

# references/woo/slots.md — the Wizard's published slot volatility anchors:
# Cleopatra (the only published model with per-configuration SDs) spans
# relative SD 13.45 (1 line) down to 5.18 (all 20 lines) with 20-line hit
# frequency 35.88%; his house-edge master table lists the typical slot SD
# as 8.74.  The Scarab par sheet is gated on this band (SCARAB_SHAPE_GATES)
# and, under the published capped bonus rules, lands near the 8.74
# typical-slot exemplar (round 5 shipped 12.60, at the one-line end).
WOO_SLOT_SD_BAND: Tuple[float, float] = (5.18, 13.45)
WOO_TYPICAL_SLOT_SD = 8.74
WOO_CLEOPATRA_HIT_20LINE = 0.3588

# references/stake/slots.md — Scarab Spin / Tome of Life published math.
# The two games are ONE math model in the reference's own words (Sect. 5
# note: same paytable ladder, same 2.16% edge, same Sect. 3a event math);
# the Tome page publishes the model's full bonus rule set, the Scarab page
# a strict subset of it.
STAKE_SCARAB_PUBLISHED: Dict[str, object] = {
    "rtp": 0.9784,                 # "RTP 97.84%" (both game pages)
    "house_edge": 0.0216,          # "Edge: 2.16 %" badge (both game pages)
    "reel_lengths": (30, 30, 30, 30, 41),
    "free_spins": 15,              # "receive 15 bonus free spins" /
                                   # "15 free spins are awarded"
    "free_spin_cap": 180,          # "Bonus rounds are capped at 180 free
                                   #  spins" ("respins up to ... 180 times")
    "free_spin_multiplier": 3,     # "a 3x multiplier on winning combos" /
                                   # "all wins during the bonus rounds are
                                   #  tripled, ..."
    "wild5_multiplier_exempt": True,   # "... except when 5 WILD symbols
                                   #  are spun"
    "wild_substitution_double": True,  # "Combinations where WILD symbols
                                   #  are used as another symbol pay double"
    "paylines": 20,
    "max_win": 10_000.0,           # "Max win: 10,000x your bet"
    "random_wilds": True,          # "random wilds in the base game"
}
STAKE_SCARAB_RTP_TOL = 5.0e-5      # half-ULP of the printed "97.84%"

# Printed-string gate for the Stake headline figures (same convention as
# WOO_ATKINS_PRINTED): {figure: (key, scale, format spec, printed string)}.
STAKE_SCARAB_PRINTED: Dict[str, Tuple[str, float, str, str]] = {
    "rtp": ("rtp", 100.0, ".2f", "97.84"),
    "house_edge": ("house_edge", 100.0, ".2f", "2.16"),
}

# Par-sheet shape gates the calibrated Scarab reconstruction must satisfy
# (checked in tests/test_slots.py and scripts/validate_slots.py): the count
# ladder must run the RIGHT way (commons frequent, premiums rare) with
# |Spearman(5-of-a-kind pay, total strip count)| >= 0.9 and counts monotone
# non-increasing in pay on every reel; the King Tut wild OCCUPIES strip
# stops ("random wilds in the base game" land from the reels — the only
# reading consistent with the published 5-floats-per-spin event math) but
# at most 2 per reel, and its own paytable row may carry at most 20% of
# the line return; no two reels may share a count vector; every reel's
# 13-entry count vector needs cv >= 0.4; the full-round relative SD must
# sit inside the published slot band; every spin (base or free) draws the
# IDENTICAL stop distribution from the same reels (no overlay, no
# fire/non-fire barbell — free spins differ from base spins only by the
# PUBLISHED 3x multiplier and its published pure-5-wild exemption).
#
# Round-5 gates on the published bonus rule set and the return
# composition: the bonus is 15 free spins with retriggers hard-capped at
# 180 total (P(chain > 180) = 0 STRUCTURALLY — the published cap, not a
# safety net), so E[spins/bonus] <= 180 always; the trigger probability
# and the chain load are capped (p <= 0.05, 15p <= 0.70 — the calibrated
# minimum feasible on the published paytable, far from the round-5
# rho = 0.914 criticality; Atkins' published anchor is 0.011185); and the
# published PAYTABLE must carry the return: attributing every win (base
# and free spins alike) to the paytable row that pays it, the eleven line
# rows + wild row must carry >= 50% of the RTP and the scatter row <= 25%
# (round 5 measured 25.29% / 74.71% — inverted).  The base-game feature
# split (line + scatter + feature = RTP) is reported alongside; on this
# paytable (top regular 5-of-a-kind 37.50 line-bets = 1.875x the total
# bet) the feature necessarily carries the balance — see the calibration
# script for the exact achievable-line-return certificate.
SCARAB_SHAPE_GATES: Dict[str, object] = {
    "spearman_abs_min": 0.9,
    "per_reel_cv_min": 0.4,
    "sd_band": WOO_SLOT_SD_BAND,
    "wild_on_strips": True,
    "wild_max_stops_per_reel": 2,
    "wild_line_return_share_max": 0.20,
    "distinct_reel_count_vectors": True,
    "counts_monotone_in_pay": True,
    "same_reels_every_spin": True,
    "published_bonus_rules": {
        "free_spins": 15,
        "free_spin_cap": 180,
        "free_spin_multiplier": 3,
        "wild5_multiplier_exempt": True,
        "wild_substitution_double": True,
    },
    "p_trigger_max": 0.05,
    "chain_load_max": 0.70,             # 15p (retrigger chain criticality)
    "expected_bonus_spins_max": 180.0,  # published cap
    "p_chain_exceeds_cap": 0.0,         # structural
    "line_rows_rtp_share_min": 0.50,    # paytable rows carry the return
    "scatter_row_rtp_share_max": 0.35,  # certified minimum region: the
                                        # ascending-p calibration walk
                                        # proves no admissible sheet gets
                                        # below ~0.28 on this paytable
}

# ---------------------------------------------------------------------------
# Atkins-style par sheet (model of references/woo/slots.md)
# ---------------------------------------------------------------------------

# Symbol order: index 0 = the Atkins wild, 1..9 food symbols, 10 = Scale
# scatter.  The paytable is a model paytable in the style of the game (the
# reference captures WoO's aggregates, not his par sheet); every published
# figure is reproduced by the strips below via exact enumeration.
ATKINS_SYMBOLS: Tuple[str, ...] = (
    "Atkins (Wild)", "Steak", "Ham", "Buffalo Wings", "Sausage", "Eggs",
    "Cheese", "Butter", "Bacon", "Mayonnaise", "Scale (Scatter)",
)
ATKINS_WILD = 0
ATKINS_SCATTER = 10

# Line pays x bet-per-line, {symbol: {count: pay}} — left-aligned
# consecutive, wild substitutes for every symbol except the scatter, only
# the highest interpretation of a line pays.
ATKINS_LINE_PAYS: Dict[int, Dict[int, float]] = {
    0: {2: 5, 3: 50, 4: 500, 5: 5000},   # Atkins (wild) own pays
    1: {2: 2, 3: 25, 4: 100, 5: 300},    # Steak
    2: {3: 20, 4: 75, 5: 200},           # Ham
    3: {3: 15, 4: 50, 5: 150},           # Buffalo Wings
    4: {3: 10, 4: 40, 5: 100},           # Sausage
    5: {3: 10, 4: 40, 5: 100},           # Eggs
    6: {3: 5, 4: 30, 5: 75},             # Cheese
    7: {3: 5, 4: 30, 5: 75},             # Butter
    8: {3: 5, 4: 25, 5: 50},             # Bacon
    9: {3: 5, 4: 25, 5: 50},             # Mayonnaise
}

# Scatter pays x TOTAL bet by number of Scales anywhere on screen (3+ also
# triggers 10 free spins, all wins tripled, retriggerable).
ATKINS_SCATTER_PAYS: Dict[int, float] = {3: 5, 4: 25, 5: 100}
ATKINS_FREE_SPINS = 10
ATKINS_FREE_MULT = 3

# CALIBRATED reel strips (5 x 32 stops, symbol indices) — the verbatim
# output of ``scripts/calibrate_slots.py`` (fully deterministic: exact
# integer meet-in-the-middle search over per-reel symbol counts to the one
# attainable target M* = 21,293,527 = line_return * 32^5, then a fixed
# greedy interleave of the counts into strip order; re-run the script to
# reproduce these tuples byte-for-byte).  Exact 32^5 enumeration of these
# strips reproduces every WOO_ATKINS_PUBLISHED figure at its printed
# precision (WOO_ATKINS_PRINTED) and within half an ULP (WOO_ATKINS_TOL):
# line return    = 21293527/32^5   = 0.6345965...  -> prints 63.460%
# scatter return = 1170315/2^24    = 0.0697562...  -> prints  6.976%
# P(3+ scatters) = 93825/2^23      = 0.0111848...  -> prints 0.011185
# hit frequency  = 1828864/32^5    = 0.0545043...  -> prints  5.45%
# and the derived bonus chain prints 11.259335 / 23.791632 / 26.610% /
# 97.046% (validate_slots.py and test_slots.py recompute all of these from
# the strips alone and gate on the printed strings).  Scale scatters are
# spaced >= 3 apart on every reel (incl. wrap), so a 3-row window never
# shows more than one Scale per reel.
ATKINS_STRIPS: Tuple[Tuple[int, ...], ...] = (
    (8, 2, 8, 2, 10, 8, 0, 8, 2, 8, 0, 9, 5, 9, 2, 8, 1, 8, 4, 9, 7, 9, 5, 8, 2, 0, 7, 3, 8, 1, 9, 6),
    (6, 8, 6, 8, 6, 9, 4, 6, 9, 10, 4, 0, 6, 8, 3, 0, 4, 9, 7, 3, 6, 8, 3, 9, 0, 6, 8, 4, 1, 5, 2, 7),
    (7, 9, 7, 9, 2, 6, 8, 5, 7, 2, 9, 4, 6, 4, 10, 1, 7, 9, 5, 8, 6, 2, 9, 7, 3, 1, 6, 2, 4, 0, 8, 5),
    (2, 7, 4, 9, 10, 2, 7, 1, 9, 4, 6, 3, 5, 7, 2, 4, 8, 1, 9, 6, 10, 3, 0, 7, 5, 1, 4, 9, 2, 8, 6, 3),
    (3, 9, 4, 8, 3, 0, 7, 4, 8, 2, 9, 3, 5, 0, 8, 6, 2, 7, 4, 1, 9, 5, 3, 7, 10, 0, 8, 6, 2, 4, 1, 9),
)

# ---------------------------------------------------------------------------
# Scarab Spin / Tome of Life (references/stake/slots.md Sect. 3a, 4, 5)
# ---------------------------------------------------------------------------

# 13 symbols; index 11 = King Tut wild, 12 = Scarab Beetle scatter.  Tome of
# Life uses the structurally identical table (Sect. 5 note) with re-skinned
# names — same math model, same published 2.16% edge.
SCARAB_SYMBOLS: Tuple[str, ...] = (
    "Cat", "Gold Coin", "Diamond", "Spade", "Club", "Heart", "Blue Coin",
    "Green Gem", "Purple Gem", "Red Gem", "Yellow Gem", "King Tut (Wild)",
    "Scarab Beetle (Scatter)",
)
TOME_SYMBOLS: Tuple[str, ...] = (
    "Green Rune", "Red Rune", "Yellow Rune", "Aqua Rune", "Blue Rune",
    "Purple Rune", "Eye Pendant", "Hand", "Blue Pendant", "Red Bat",
    "Green Skull", "Tome of Life (Wild)", "Healer (Scatter)",
)
SCARAB_WILD = 11
SCARAB_SCATTER = 12

# Stake's complete published paytable, transcribed payout-for-payout
# (multipliers of bet-per-line) — references/stake/slots.md Sect. 4.
SCARAB_LINE_PAYS: Dict[int, Dict[int, float]] = {
    0: {2: 0.10, 3: 0.25, 4: 1.25, 5: 5.00},    # Cat
    1: {3: 0.25, 4: 1.25, 5: 5.00},             # Gold Coin
    2: {3: 0.25, 4: 1.25, 5: 5.00},             # Diamond
    3: {3: 0.25, 4: 1.25, 5: 5.00},             # Spade
    4: {3: 0.25, 4: 2.50, 5: 5.00},             # Club
    5: {3: 0.50, 4: 2.50, 5: 6.25},             # Heart
    6: {3: 0.50, 4: 2.50, 5: 12.50},            # Blue Coin
    7: {3: 0.50, 4: 3.75, 5: 12.50},            # Green Gem
    8: {3: 0.75, 4: 5.00, 5: 20.00},            # Purple Gem
    9: {2: 0.10, 3: 1.25, 4: 5.00, 5: 37.50},   # Red Gem
    10: {2: 0.10, 3: 1.25, 4: 5.00, 5: 37.50},  # Yellow Gem
    11: {2: 0.50, 3: 10.00, 4: 100.00, 5: 500.00},  # King Tut (Wild)
}
# Scarab Beetle scatter: "pays out for landing 2 or more anywhere on the
# reels" — published row of the same bet-per-line table.
SCARAB_SCATTER_PAYS: Dict[int, float] = {2: 2.00, 3: 6.00, 4: 50.00, 5: 500.00}
SCARAB_FREE_SPINS = 15        # "Land 3 scatter symbols ... 15 bonus free spins"
# The published bonus rule set of the shared Scarab/Tome math model
# (references/stake/slots.md Sect. 5, quoted verbatim in the module doc):
# retriggers up to a HARD cap of 180 total free spins, every bonus win
# tripled except a pure 5-wild line, and wild-substitution combos doubled.
SCARAB_FREE_MULT = 3          # "a 3x multiplier on winning combos"
SCARAB_FREE_SPIN_CAP = 180    # "Bonus rounds are capped at 180 free spins"
SCARAB_WILD_DOUBLE = True     # "Combinations where WILD symbols are used as
                              #  another symbol pay double"
SCARAB_WILD5_EXEMPT = True    # "all wins during the bonus rounds are
                              #  tripled, except when 5 WILD symbols are spun"
SCARAB_REEL_LENGTHS: Tuple[int, ...] = (30, 30, 30, 30, 41)
SCARAB_MAX_WIN = 10_000.0     # "Max win: 10,000x your bet" (Sect. 4)
# "This game consists of 5 game event numbers" (Sect. 3a) — one float per
# reel, nothing else; identical to the verified RNG core's event count
# (rng.EVENT_COUNTS["scarab_spin"], asserted below and in the tests).
SCARAB_FLOATS_PER_SPIN = 5

# CALIBRATED par sheet (scripts/calibrate_slots.py, Scarab stages — fully
# deterministic, re-runnable, byte-for-byte reproducible).  Per-reel counts
# for ALL 13 symbols (order = SCARAB_SYMBOLS: columns 0..10 the line
# symbols in ascending 5-of-a-kind pay, column 11 the King Tut wild,
# column 12 the scatter; each row sums to the reel length).  The 11-symbol
# ladder is monotone non-increasing in pay on every reel; the wild sits ON
# the strips at 1-2 stops per reel (7 stops machine-wide — among the
# rarest paying symbols, Spearman(pay, total count) = -0.93); scatters
# are 2/2/2/2/3, spaced >= 3 so a window never shows two per reel.  The
# count matrix is solved exactly against the published RTP — see the
# module docstring and the calibration script.
SCARAB_COUNTS: Tuple[Tuple[int, ...], ...] = (
    (4, 4, 3, 3, 3, 2, 2, 2, 2, 1, 1, 1, 2),
    (4, 4, 4, 3, 3, 3, 2, 1, 1, 1, 1, 1, 2),
    (4, 4, 4, 3, 3, 2, 2, 1, 1, 1, 1, 2, 2),
    (5, 4, 3, 3, 3, 3, 1, 1, 1, 1, 1, 2, 2),
    (5, 5, 5, 4, 4, 4, 3, 3, 2, 1, 1, 1, 3),
)
SCARAB_SCATTER_POS: Tuple[Tuple[int, ...], ...] = (
    (4, 19), (11, 26), (3, 18), (10, 25), (5, 18, 32))

# The strips: the deterministic greedy interleave of SCARAB_COUNTS with the
# scatters at SCARAB_SCATTER_POS (identical arrangement routine as the
# Atkins strips; order never touches any published figure — marginals
# depend only on counts).  Totals across the machine: Cat 22, Gold Coin
# 21, Diamond 19, Spade 16, Club 16, Heart 14, Blue Coin 10, Green Gem 8,
# Purple Gem 7, Red Gem 5, Yellow Gem 5, King Tut (wild) 7, scatter 11 —
# commons frequent, premiums rare, the wild among the rarest.
SCARAB_STRIPS: Tuple[Tuple[int, ...], ...] = (
    (0, 2, 0, 4, 12, 1, 3, 1, 7, 3, 6, 2, 0, 4, 8, 5, 1, 3, 7, 12, 4, 0, 6, 2, 11, 1, 8, 5, 10, 9),
    (0, 2, 0, 3, 1, 5, 2, 4, 1, 4, 0, 12, 6, 2, 5, 3, 1, 9, 5, 2, 6, 4, 0, 3, 11, 8, 12, 10, 1, 7),
    (1, 3, 0, 12, 2, 4, 1, 3, 0, 2, 4, 1, 6, 0, 11, 5, 2, 10, 12, 3, 0, 7, 2, 9, 4, 6, 1, 11, 8, 5),
    (0, 4, 1, 3, 0, 5, 1, 3, 0, 2, 12, 4, 2, 0, 5, 1, 11, 8, 1, 9, 5, 0, 10, 2, 7, 12, 4, 6, 11, 3),
    (0, 2, 0, 5, 1, 12, 3, 1, 4, 2, 6, 2, 0, 5, 3, 7, 4, 1, 12, 7, 4, 6, 3, 8, 0, 5, 2, 8, 1, 6, 10, 7, 12, 3, 9, 5, 0, 2, 11, 4, 1),
)


def _pays_to_cents(pays: Dict[int, Dict[int, float]]) -> Dict[int, Dict[int, int]]:
    out: Dict[int, Dict[int, int]] = {}
    for s, row in pays.items():
        out[s] = {}
        for k, v in row.items():
            cents = round(v * 100)
            if abs(cents - v * 100) > 1e-9:
                raise ValueError(f"pay {v} is not an exact cent multiple")
            out[s][k] = int(cents)
    return out


def _contract_int(lut_flat: np.ndarray, per_reel: Sequence[Sequence[int]],
                  n: int) -> int:
    """Exact big-integer contraction sum(lut[t] * prod_i nums[i][t_i]) over
    all symbol 5-tuples t (object dtype — no float rounding ever)."""
    t = lut_flat.astype(object)
    for nums in reversed(list(per_reel)):
        vec = np.array([int(v) for v in nums], dtype=object)
        t = t.reshape(-1, n).dot(vec)
    return int(t[0])


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class SlotMachine:
    """Generic 5-reel / 3-row / 20-line video slot with wild, scatter and
    retriggerable free spins, driven by the verified provably-fair RNG.

    ``scatter_pay_basis`` is ``"total"`` (scatter pays multiply the total
    bet — the Atkins model) or ``"line"`` (they multiply the bet per line —
    Stake's published Scarab convention: the whole paytable, scatter row
    included, is in bet-per-line multipliers).  All returns reported by this
    class are per unit TOTAL bet (20 line-bets).

    Published rule switches (references/stake/slots.md Sect. 5, the bonus
    rule set of the shared Scarab/Tome math model):

    * ``free_spin_cap`` — hard cap on TOTAL free spins per bonus ("Bonus
      rounds are capped at 180 free spins"): retriggers extend the bonus
      but never past the cap, so P(chain > cap) = 0 structurally.  With
      ``None`` the chain is the uncapped geometric one (the Atkins model;
      a safety cap guards the loop at negligible probability).
    * ``wild_substitution_double`` — "Combinations where WILD symbols are
      used as another symbol pay double": an interpretation that uses a
      wild AS another symbol pays 2x (base and free spins alike; the
      wild's own row never doubles).
    * ``wild5_multiplier_exempt`` — "all wins during the bonus rounds are
      tripled, except when 5 WILD symbols are spun": the free-spin
      multiplier applies per interpretation, but a pure 5-wild line pays
      its published 500x unmultiplied.

    Every spin — base or free — consumes EXACTLY 5 floats, one per reel
    (Stake Sect. 3a: "This game consists of 5 game event numbers"); for
    the published 30/30/30/30/41 Scarab geometry the float -> stop mapping
    is routed through the verified RNG core's
    :func:`spinquest_sim.rng.scarab_spin_stops`.  Free spins draw stops
    from the SAME reels through the same mapping — they differ from base
    spins only by the published multiplier rules above.  ``max_win`` caps
    every round's total payout in total-bet multiples (Stake publishes
    10,000x).
    """

    def __init__(
        self,
        name: str,
        symbols: Sequence[str],
        strips: Sequence[Sequence[int]],
        line_pays: Dict[int, Dict[int, float]],
        wild: int,
        scatter: int,
        scatter_pays: Dict[int, float],
        scatter_pay_basis: str,
        free_spins: int,
        free_spin_multiplier: float,
        paylines: Sequence[Sequence[int]] = PAYLINES_20,
        trigger_count: int = 3,
        max_win: Optional[float] = None,
        free_spin_cap: Optional[int] = None,
        wild_substitution_double: bool = False,
        wild5_multiplier_exempt: bool = False,
    ) -> None:
        if len(strips) != 5:
            raise ValueError("need exactly 5 reel strips")
        if scatter_pay_basis not in ("total", "line"):
            raise ValueError("scatter_pay_basis must be 'total' or 'line'")
        self.name = name
        self.symbols = tuple(symbols)
        self.n_symbols = len(self.symbols)
        self.strips = tuple(tuple(int(s) for s in strip) for strip in strips)
        self.reel_lengths = tuple(len(s) for s in self.strips)
        for strip in self.strips:
            if any(not 0 <= s < self.n_symbols for s in strip):
                raise ValueError("strip symbol index out of range")
        self.line_pays = {s: dict(row) for s, row in line_pays.items()}
        self.wild = int(wild)
        self.scatter = int(scatter)
        if self.scatter in self.line_pays:
            raise ValueError("the scatter cannot have line pays")
        self.scatter_pays = dict(scatter_pays)
        self.scatter_pay_basis = scatter_pay_basis
        self.free_spins = int(free_spins)
        self.free_spin_multiplier = float(free_spin_multiplier)
        self.paylines = tuple(tuple(int(r) for r in line) for line in paylines)
        if any(len(line) != 5 or not all(0 <= r < ROWS for r in line)
               for line in self.paylines):
            raise ValueError("paylines must be 5 rows in 0..2")
        self.n_lines = len(self.paylines)
        self.trigger_count = int(trigger_count)
        self.max_win = None if max_win is None else float(max_win)
        if self.max_win is not None and self.max_win <= 0:
            raise ValueError("max_win must be positive")
        self.free_spin_cap = None if free_spin_cap is None else int(free_spin_cap)
        if self.free_spin_cap is not None and self.free_spin_cap < free_spins:
            raise ValueError("free_spin_cap must be >= free_spins")
        self.wild_substitution_double = bool(wild_substitution_double)
        self.wild5_multiplier_exempt = bool(wild5_multiplier_exempt)
        # bonus pays are exact integer cents: k-oak pay * multiplier must be
        # a whole number of cents for every published rung
        for s, row in line_pays.items():
            for k, v in row.items():
                bm = v * 100 * self.free_spin_multiplier
                if abs(bm - round(bm)) > 1e-9:
                    raise ValueError("bonus pay not an exact cent multiple")

        self._line_pays_cents = _pays_to_cents(self.line_pays)
        # scatter pays in cents of a LINE bet (exact ints): 'total' basis
        # multiplies by n_lines line-bets.
        scale = self.n_lines if scatter_pay_basis == "total" else 1
        self._scatter_cents = np.zeros(5 * ROWS + 1, dtype=np.int64)
        for k, v in self.scatter_pays.items():
            cents = round(v * 100 * scale)
            if abs(cents - v * 100 * scale) > 1e-6:
                raise ValueError("scatter pay not an exact cent multiple")
            self._scatter_cents[int(k)] = int(cents)
        # A count above the lowest published rung pays the highest published
        # rung at or below it: interior holes in the published dict carry
        # the previous rung forward (more scatters never pay less), and
        # counts beyond the top rung pay the top rung (a 3-row screen can
        # show up to 2 scatters per reel window).
        if self.scatter_pays:
            lo = min(int(k) for k in self.scatter_pays)
            for k in range(lo + 1, 5 * ROWS + 1):
                if k not in self.scatter_pays:
                    self._scatter_cents[k] = self._scatter_cents[k - 1]
        # bonus-spin scatter pays: published free-spin multiplier, exact cents
        self._scatter_cents_bonus = np.array(
            [int(round(int(c) * self.free_spin_multiplier))
             for c in self._scatter_cents], dtype=np.int64)

        # per-reel window scatter counts: scnt[i][t] = scatters visible in
        # the 3-row window centred on stop t.
        self._scnt = []
        for strip in self.strips:
            L = len(strip)
            self._scnt.append(np.array(
                [sum(strip[(t + r) % L] == self.scatter for r in (-1, 0, 1))
                 for t in range(L)], dtype=np.int64))
        # symbol at (reel, row, stop): row 0 = stop-1, 1 = stop, 2 = stop+1
        self._sym_at = []
        for strip in self.strips:
            L = len(strip)
            arr = np.array(
                [[strip[(t + r - 1) % L] for t in range(L)] for r in range(ROWS)],
                dtype=np.int64)
            self._sym_at.append(arr)

        self._lut_cache: Optional[np.ndarray] = None
        self._lut_bonus_cache: Optional[np.ndarray] = None
        self._exact_cache: Optional[Dict[str, object]] = None

    # ------------------------------------------------------------------
    # shared structure
    # ------------------------------------------------------------------

    @property
    def floats_per_spin(self) -> int:
        """Floats one spin consumes from the verifiable stream: exactly 5,
        one per reel — Stake's published "5 game event numbers" (Sect. 3a),
        identical to rng.EVENT_COUNTS["scarab_spin"]."""
        return 5

    def line_pay(self, line_symbols: Sequence[int]) -> float:
        """Reference (scalar) line evaluation: highest pay among all
        left-aligned interpretations; wild substitutes for everything except
        the scatter; a wild run can also pay as the wild's own symbol.  With
        ``wild_substitution_double`` (published Tome of Life rule,
        references/stake/slots.md Sect. 5: "Combinations where WILD symbols
        are used as another symbol pay double") an interpretation that uses
        at least one wild AS another symbol pays 2x."""
        return self._line_pay_cents_scalar(tuple(line_symbols)) / 100.0

    def bonus_line_pay(self, line_symbols: Sequence[int]) -> float:
        """Scalar line evaluation for a FREE spin: every interpretation is
        multiplied by ``free_spin_multiplier`` except — with
        ``wild5_multiplier_exempt`` (Stake Sect. 5: "all wins during the
        bonus rounds are tripled, except when 5 WILD symbols are spun") —
        the pure 5-wild combination, which pays its published 500x
        unmultiplied.  The best interpretation is taken AFTER applying the
        multiplier."""
        return self._line_pay_cents_scalar(tuple(line_symbols),
                                           bonus=True) / 100.0

    def _line_pay_cents_scalar(self, tup: Tuple[int, ...],
                               bonus: bool = False) -> int:
        best = 0
        mult = self.free_spin_multiplier if bonus else 1
        for s_id, pays in self._line_pays_cents.items():
            k = 0
            wild_used = False
            for s in tup:
                if s == s_id or (s == self.wild and s_id != self.wild):
                    if s == self.wild and s_id != self.wild:
                        wild_used = True
                    k += 1
                else:
                    break
            p = pays.get(k, 0)
            if k >= 5:
                p = pays.get(5, p)
            if bonus:
                if s_id == self.wild and k >= 5 and self.wild5_multiplier_exempt:
                    pass                       # published exemption: pay 1x
                else:
                    p = int(round(p * mult))
            if self.wild_substitution_double and s_id != self.wild and wild_used:
                p *= 2
            if p > best:
                best = p
        return best

    def _build_lut(self, bonus: bool) -> np.ndarray:
        """Flat int64 LUT of line pay (cents of a line bet) for every
        symbol 5-tuple, index = sum(sym_i * n_sym^(4-i)).  Vectorized build;
        cross-checked against the scalar rule in the tests.  ``bonus``
        applies the free-spin multiplier per interpretation (with the
        published pure-5-wild exemption when configured); the
        wild-substitution doubling applies to both tables."""
        n = self.n_symbols
        shape = (n,) * 5
        # grid[j] = symbol index along axis j (broadcast views, no copies)
        grids = [np.arange(n).reshape([n if a == j else 1 for a in range(5)])
                 for j in range(5)]
        mult = self.free_spin_multiplier if bonus else 1
        best = np.zeros(shape, dtype=np.int64)
        for s_id, pays in self._line_pays_cents.items():
            if s_id == self.wild:
                match = [(g == self.wild) for g in grids]
            else:
                match = [(g == s_id) | (g == self.wild) for g in grids]
            run = np.ones(shape, dtype=bool)
            k = np.zeros(shape, dtype=np.int64)
            aw = np.zeros(shape, dtype=bool)      # wild used AS s_id
            for j in range(5):
                run = run & match[j]
                k = k + run
                if s_id != self.wild:
                    aw = aw | (run & (grids[j] == self.wild))
            pay_by_k = np.zeros(6, dtype=np.int64)
            pay_by_k_b = np.zeros(6, dtype=np.int64)
            for kk, cents in pays.items():
                if kk <= 5:
                    pay_by_k[kk] = cents
                    pay_by_k_b[kk] = int(round(cents * mult))
            if bonus and s_id == self.wild and self.wild5_multiplier_exempt:
                pay_by_k_b[5] = pay_by_k[5]       # published exemption
            p = pay_by_k_b[k] if bonus else pay_by_k[k]
            if self.wild_substitution_double and s_id != self.wild:
                p = np.where(aw, 2 * p, p)
            best = np.maximum(best, p)
        return best.reshape(-1)

    @property
    def _lut_cents(self) -> np.ndarray:
        if self._lut_cache is None:
            self._lut_cache = self._build_lut(bonus=False)
        return self._lut_cache

    @property
    def _lut_cents_bonus(self) -> np.ndarray:
        if self._lut_bonus_cache is None:
            self._lut_bonus_cache = self._build_lut(bonus=True)
        return self._lut_bonus_cache

    def symbol_counts(self) -> np.ndarray:
        """(5, n_symbols) per-reel symbol counts."""
        out = np.zeros((5, self.n_symbols), dtype=np.int64)
        for i, strip in enumerate(self.strips):
            for s in strip:
                out[i, s] += 1
        return out

    def scatter_distribution(self) -> np.ndarray:
        """Exact P(k scatters visible), k = 0..15, from the per-reel window
        counts (reels independent)."""
        pmf = np.array([1.0])
        for i in range(5):
            L = self.reel_lengths[i]
            c = np.bincount(self._scnt[i], minlength=3) / L
            pmf = np.convolve(pmf, c)
        out = np.zeros(5 * ROWS + 1)
        out[: len(pmf)] = pmf
        return out

    def _scatter_pmf_exact(self) -> List[Fraction]:
        """Exact Fractions version of :meth:`scatter_distribution`."""
        pmf: Dict[int, Fraction] = {0: Fraction(1)}
        for i in range(5):
            L = self.reel_lengths[i]
            hist = np.bincount(self._scnt[i], minlength=3)
            new: Dict[int, Fraction] = {}
            for k, pr in pmf.items():
                for kap in range(len(hist)):
                    if hist[kap]:
                        new[k + kap] = new.get(k + kap, Fraction(0)) \
                            + pr * Fraction(int(hist[kap]), L)
            pmf = new
        return [pmf.get(k, Fraction(0)) for k in range(5 * ROWS + 1)]

    # ------------------------------------------------------------------
    # (a) analytics
    # ------------------------------------------------------------------

    def marginal_line_stats(self) -> Tuple[Fraction, Fraction]:
        """(per-line expected pay in line-bet units, per-line hit prob),
        computed from symbol COUNTS only — independent of strip order and
        of the payline patterns.  This is the cross-check for the full
        stop enumeration (an independent code path: no windows, no lines).
        Exact: the count products are contracted as big integers."""
        counts = self.symbol_counts()
        per_reel = [[int(c) for c in counts[i]] for i in range(5)]
        lut = self._lut_cents
        m = _contract_int(lut, per_reel, self.n_symbols)
        h = _contract_int((lut > 0).astype(np.int64), per_reel,
                          self.n_symbols)
        denom = 1
        for L in self.reel_lengths:
            denom *= L
        return Fraction(m, denom * 100), Fraction(h, denom)

    def _scatter_return_exact(self) -> Tuple[Fraction, Fraction, List[Fraction]]:
        """(scatter return per unit total bet, P(trigger), exact pmf)."""
        pmf = self._scatter_pmf_exact()
        unit = 100 * self.n_lines
        sc_ret = sum((pr * Fraction(int(self._scatter_cents[k]), unit)
                      for k, pr in enumerate(pmf)), Fraction(0))
        p = sum((pr for k, pr in enumerate(pmf) if k >= self.trigger_count),
                Fraction(0))
        return sc_ret, p, pmf

    @staticmethod
    def _capped_chain_exact(a: int, denom: int, F: int, cap: int
                            ) -> Tuple[Fraction, np.ndarray]:
        """EXACT distribution of N = total free spins of one bonus under
        the published capped-retrigger rule (F spins per (re)trigger, total
        spins hard-capped at ``cap`` — Stake Sect. 5: "Bonus rounds are
        capped at 180 free spins").  ``a / denom`` is the exact per-spin
        retrigger probability.  Forward DP on (spins played t, spins
        remaining r); level-t weights are integers over denom^t, so E[N]
        comes out as an exact Fraction; the pmf (support 15..cap, hence
        P(N > cap) = 0 STRUCTURALLY) is returned in float64.
        E[N] = sum_t P(spin t+1 is played) — the alive mass per level."""
        b = denom - a
        probs: Dict[int, int] = {min(F, cap): 1}
        alive: List[int] = []
        pmf_w: Dict[int, int] = {}
        for t in range(cap):
            if not probs:
                break
            alive.append(sum(probs.values()))
            new: Dict[int, int] = {}
            for r, wgt in probs.items():
                rt = min(r - 1 + F, cap - (t + 1))
                rn = r - 1
                if rt > 0:
                    new[rt] = new.get(rt, 0) + wgt * a
                else:
                    pmf_w[t + 1] = pmf_w.get(t + 1, 0) + wgt * a
                if rn > 0:
                    new[rn] = new.get(rn, 0) + wgt * b
                else:
                    pmf_w[t + 1] = pmf_w.get(t + 1, 0) + wgt * b
            probs = new
        if probs:
            pmf_w[cap] = pmf_w.get(cap, 0) + sum(probs.values())
        depth = len(alive)
        e_n = Fraction(
            sum(w * denom ** (depth - 1 - t) for t, w in enumerate(alive)),
            denom ** (depth - 1))
        pmf = np.zeros(cap + 1)
        for nn, wgt in pmf_w.items():
            pmf[nn] = wgt / denom ** nn
        return e_n, pmf

    @staticmethod
    def _capped_chain_moments(p: float, F: int, cap: int, e_w: float,
                              e_w2: float, e_wz: float
                              ) -> Tuple[float, float]:
        """(E[T], E[T^2]) of the capped bonus package T = sum of the N
        free-spin wins W_i, by backward DP over (t, r).  The per-spin win W
        and the retrigger indicator Z are dependent WITHIN a spin (e_wz =
        E[W Z]), which the recursion carries exactly:

            T(t,r)      = W + T(next state)
            E[T]        = E[W] + p*m1[s+] + q*m1[s-]
            E[W*T']     = E[WZ]*m1[s+] + (E[W]-E[WZ])*m1[s-]
            E[T^2]      = E[W^2] + 2*E[W*T'] + p*m2[s+] + q*m2[s-]

        with s+ = (t+1, min(r-1+F, cap-t-1)) and s- = (t+1, r-1)."""
        q = 1.0 - p
        size = cap + F + 2
        m1_next = np.zeros(size)
        m2_next = np.zeros(size)
        for t in range(cap - 1, -1, -1):
            rmax = cap - t
            r = np.arange(1, rmax + 1)
            rt = np.minimum(r - 1 + F, cap - (t + 1))
            rn = r - 1
            m1n = np.where(rt > 0, m1_next[rt], 0.0)
            m1d = np.where(rn > 0, m1_next[rn], 0.0)
            m2n = np.where(rt > 0, m2_next[rt], 0.0)
            m2d = np.where(rn > 0, m2_next[rn], 0.0)
            m1_cur = np.zeros(size)
            m2_cur = np.zeros(size)
            m1_cur[1:rmax + 1] = e_w + p * m1n + q * m1d
            m2_cur[1:rmax + 1] = (e_w2 + 2.0 * (e_wz * m1n
                                                + (e_w - e_wz) * m1d)
                                  + p * m2n + q * m2d)
            m1_next, m2_next = m1_cur, m2_cur
        r0 = min(F, cap)
        return float(m1_next[r0]), float(m2_next[r0])

    @staticmethod
    def _fold_free_spins(F: int, m: float, p: float, mu: float,
                         e_y2: float, e_yz: float) -> Dict[str, float]:
        """Exact free-spin branching recursion (see module docstring)."""
        if F * p >= 1.0:
            raise ValueError("free-spin retrigger process does not terminate")
        e_t = F * m * mu / (1.0 - F * p)
        e_spins = F / (1.0 - F * p)
        e_u = e_t / F
        a = m * m * e_y2 + 2.0 * m * e_yz * e_t
        e_t2 = (F * a + F * (F - 1) * e_u * e_u) / (1.0 - F * p)
        rtp = mu + p * e_t
        e_x2 = e_y2 + 2.0 * e_yz * e_t + p * e_t2
        var = e_x2 - rtp * rtp
        return {"e_t": e_t, "e_spins": e_spins, "e_t2": e_t2, "rtp": rtp,
                "e_x2": e_x2, "var": var}

    def enumerate_exact(self, progress: bool = False) -> Dict[str, object]:
        """Exact analytics: brute-force enumeration of ALL reel-stop
        combinations (32^5 Atkins, 30^4*41 Scarab) with the full 20-line +
        scatter evaluation per outcome — first moments in exact
        integer/Fraction arithmetic, second moments float64 — then the
        exact free-spin recursion.  Cross-checked in the tests against the
        independent count-marginal contraction."""
        if self._exact_cache is not None:
            return self._exact_cache
        result = self._enumerate_stops(progress=progress)
        self._exact_cache = result
        return result

    def _enumerate_stops(self, progress: bool = False) -> Dict[str, object]:
        t0 = time.perf_counter()
        n = self.n_symbols
        lens = self.reel_lengths
        lut = self._lut_cents
        inner_shape = lens[1:]
        inner_size = int(np.prod(inner_shape))
        strides = [n ** (4 - i) for i in range(5)]

        # Per line: index contribution of reels 2..5 (flattened) and the
        # reel-1 head contributions per stop.
        heads = []
        inners = []
        for line in self.paylines:
            heads.append(self._sym_at[0][line[0]] * strides[0])   # (L1,)
            acc = np.zeros(inner_shape, dtype=np.int64)
            for i in range(1, 5):
                shape = [1, 1, 1, 1]
                shape[i - 1] = lens[i]
                acc = acc + (self._sym_at[i][line[i]] * strides[i]).reshape(shape)
            inners.append(np.ascontiguousarray(acc.reshape(-1), dtype=np.int64))
        # scatter counts of reels 2..5 (flattened)
        sc_inner = np.zeros(inner_shape, dtype=np.int64)
        for i in range(1, 5):
            shape = [1, 1, 1, 1]
            shape[i - 1] = lens[i]
            sc_inner = sc_inner + self._scnt[i].reshape(shape)
        sc_inner = sc_inner.reshape(-1)

        # A machine with the published capped bonus (Scarab/Tome) also needs
        # the FREE-SPIN evaluation moments (the bonus LUT is not a scalar
        # multiple of the base LUT once the pure-5-wild exemption applies).
        capped = self.free_spin_cap is not None
        lut_b = self._lut_cents_bonus if capped else None

        line_cents_total = 0            # exact
        scatter_cents_total = 0         # exact
        line_hits_total = 0             # exact, summed over lines
        any_hit_total = 0               # outcomes with any line pay
        trigger_total = 0               # outcomes with k >= trigger_count
        k_hist = np.zeros(5 * ROWS + 1, dtype=np.int64)
        sum_y2 = 0.0                    # float64: E[Y^2] (line-bet cents^2)
        sum_yz = 0                      # exact: E[Y * 1{trigger}]
        w_line_cents_total = 0          # exact: bonus-eval line cents
        sum_w2 = 0.0                    # float64: E[W^2]
        sum_wz = 0                      # exact: E[W * 1{trigger}]
        max_y_cents = 0                 # largest single base-spin win
        max_w_cents = 0                 # largest single free-spin win
        y = np.empty(inner_size, dtype=np.int64)
        w = np.empty(inner_size, dtype=np.int64) if capped else None
        for t1 in range(lens[0]):
            y[:] = 0
            if capped:
                w[:] = 0
            hits_here = np.zeros(inner_size, dtype=np.int64)
            for l in range(self.n_lines):
                idx = inners[l] + heads[l][t1]
                pays = lut[idx]
                y += pays
                if capped:
                    w += lut_b[idx]
                nz = pays > 0
                line_hits_total += int(np.count_nonzero(nz))
                hits_here += nz
            any_hit_total += int(np.count_nonzero(hits_here))
            line_cents_total += int(y.sum())
            k = sc_inner + self._scnt[0][t1]
            k_hist += np.bincount(k, minlength=5 * ROWS + 1)
            sc_pay = self._scatter_cents[k]
            scatter_cents_total += int(sc_pay.sum())
            y += sc_pay
            trig = k >= self.trigger_count
            trigger_total += int(np.count_nonzero(trig))
            sum_y2 += float(np.dot(y.astype(np.float64), y.astype(np.float64)))
            sum_yz += int(y[trig].sum())
            max_y_cents = max(max_y_cents, int(y.max()))
            if capped:
                w_line_cents_total += int(w.sum())
                w += self._scatter_cents_bonus[k]
                sum_w2 += float(np.dot(w.astype(np.float64),
                                       w.astype(np.float64)))
                sum_wz += int(w[trig].sum())
                max_w_cents = max(max_w_cents, int(w.max()))
            if progress and (t1 + 1) % 8 == 0:
                print(f"  enumerate {self.name}: reel-1 stop {t1 + 1}/{lens[0]}",
                      flush=True)
        denom = lens[0] * inner_size
        unit = 100 * self.n_lines       # line-bet cents per unit total bet

        line_return = Fraction(line_cents_total, denom * unit)
        scatter_return = Fraction(scatter_cents_total, denom * unit)
        p_trigger = Fraction(trigger_total, denom)
        hit_freq = Fraction(line_hits_total, denom * self.n_lines)
        mu_y = line_return + scatter_return
        e_y2 = sum_y2 / denom / unit ** 2
        e_yz = Fraction(sum_yz, denom * unit)

        F, m = self.free_spins, self.free_spin_multiplier
        p = float(p_trigger)
        mu = float(mu_y)

        result: Dict[str, object] = {
            "outcomes": denom,
            "line_return": line_return,
            "scatter_return": scatter_return,
            "base_return": mu_y,
            "p_bonus_trigger": p_trigger,
            "hit_frequency": hit_freq,
            "any_line_hit_frequency": Fraction(any_hit_total, denom),
            "scatter_pmf": k_hist / denom,
            "scatter_counts": k_hist,
            "e_y": mu,
            "e_y2": e_y2,
            "e_yz": float(e_yz),
            "free_spin_cap": self.free_spin_cap,
            "max_spin_cents": max_y_cents,
            "elapsed_s": 0.0,
        }
        if not capped:
            # uncapped geometric retrigger chain (the Atkins model) — the
            # bonus-spin win is exactly m * Y here, so the closed-form
            # branching recursion applies (path unchanged, bit-identical)
            fold = self._fold_free_spins(F, m, p, mu, e_y2, float(e_yz))
            m_frac = Fraction(m)
            if F * p_trigger >= 1:
                raise ValueError(
                    "free-spin retrigger process does not terminate")
            e_t_frac = F * m_frac * mu_y / (1 - F * p_trigger)
            rtp_frac = mu_y + p_trigger * e_t_frac
            result.update({
                "bonus_return": p * fold["e_t"],
                "rtp": fold["rtp"],
                "rtp_fraction": rtp_frac,
                "house_edge": 1.0 - fold["rtp"],
                "expected_bonus_spins": fold["e_spins"],
                "expected_bonus_win": fold["e_t"],
                "e_x2": fold["e_x2"],
                "variance_per_unit": fold["var"],
                "std_per_unit": math.sqrt(fold["var"]),
            })
        else:
            # published capped bonus (Scarab/Tome): 15 free spins, capped
            # retriggers (never past free_spin_cap total spins), free-spin
            # wins from the bonus LUT (published multiplier per
            # interpretation, pure-5-wild exemption).  First moments exact.
            cap = self.free_spin_cap
            sc_b_total = int(sum(
                int(k_hist[kk]) * int(self._scatter_cents_bonus[kk])
                for kk in range(len(k_hist))))
            bonus_line_return = Fraction(w_line_cents_total, denom * unit)
            bonus_scatter_return = Fraction(sc_b_total, denom * unit)
            e_w_frac = bonus_line_return + bonus_scatter_return
            e_w2 = sum_w2 / denom / unit ** 2
            e_wz = Fraction(sum_wz, denom * unit)
            e_n_frac, chain_pmf = self._capped_chain_exact(
                trigger_total, denom, F, cap)
            # E[T] = E[N] * E[W]: the i-th free spin being played depends
            # only on the PRECEDING spins' trigger indicators, so each
            # played spin contributes E[W] (optional-stopping argument);
            # verified against the backward DP below.
            e_t_frac = e_n_frac * e_w_frac
            rtp_frac = mu_y + p_trigger * e_t_frac
            et_dp, et2_dp = self._capped_chain_moments(
                p, F, cap, float(e_w_frac), e_w2, float(e_wz))
            if not math.isclose(et_dp, float(e_t_frac), rel_tol=1e-9):
                raise AssertionError(
                    f"capped-chain moment mismatch: {et_dp} vs "
                    f"{float(e_t_frac)}")
            rtp = float(rtp_frac)
            e_x2 = e_y2 + 2.0 * float(e_yz) * float(e_t_frac) + p * et2_dp
            var = e_x2 - rtp * rtp
            result.update({
                "bonus_return": p * float(e_t_frac),
                "rtp": rtp,
                "rtp_fraction": rtp_frac,
                "house_edge": 1.0 - rtp,
                "expected_bonus_spins": float(e_n_frac),
                "expected_bonus_spins_fraction": e_n_frac,
                "expected_bonus_win": float(e_t_frac),
                "bonus_line_return": bonus_line_return,
                "bonus_scatter_return": bonus_scatter_return,
                "e_w": float(e_w_frac),
                "e_w2": e_w2,
                "e_wz": float(e_wz),
                "chain_pmf": chain_pmf,
                "p_chain_at_cap": float(chain_pmf[cap]),
                "p_chain_exceeds_cap": 0.0,
                "max_bonus_spin_cents": max_w_cents,
                "e_x2": e_x2,
                "variance_per_unit": var,
                "std_per_unit": math.sqrt(var),
            })
        result["elapsed_s"] = time.perf_counter() - t0
        return result

    @property
    def rtp(self) -> float:
        return float(self.enumerate_exact()["rtp"])

    @property
    def house_edge(self) -> float:
        return 1.0 - self.rtp

    @property
    def std_per_unit(self) -> float:
        return float(self.enumerate_exact()["std_per_unit"])

    def config(self) -> Dict[str, object]:
        cfg: Dict[str, object] = {
            "game": "slots",
            "name": self.name,
            "symbols": list(self.symbols),
            "reel_lengths": list(self.reel_lengths),
            "reel_strips": [list(s) for s in self.strips],
            "n_lines": self.n_lines,
            "paylines": [list(l) for l in self.paylines],
            "line_pays": {self.symbols[s]: dict(row)
                          for s, row in self.line_pays.items()},
            "wild": self.symbols[self.wild],
            "scatter": self.symbols[self.scatter],
            "scatter_pays": dict(self.scatter_pays),
            "scatter_pay_basis": self.scatter_pay_basis,
            "trigger_count": self.trigger_count,
            "free_spins": self.free_spins,
            "free_spin_multiplier": self.free_spin_multiplier,
            "free_spin_cap": self.free_spin_cap,
            "wild_substitution_double": self.wild_substitution_double,
            "wild5_multiplier_exempt": self.wild5_multiplier_exempt,
            "max_win": self.max_win,
            "floats_per_spin": self.floats_per_spin,
        }
        return cfg

    def analytic_summary(self) -> Dict[str, object]:
        """Standard result dict, analytic (exact computation, no simulation)."""
        exact = self.enumerate_exact()
        return {
            "rtp": float(exact["rtp"]),
            "house_edge": float(exact["house_edge"]),
            "std_per_unit": float(exact["std_per_unit"]),
            "config": self.config(),
        }

    # ------------------------------------------------------------------
    # (b) provably-fair single round (scalar verification path)
    # ------------------------------------------------------------------

    def _stops_from_floats(self, floats: Sequence[float]) -> List[int]:
        """floor(float * reel_length) per reel — Stake's published mapping.
        For the published 30/30/30/30/41 Scarab geometry this is ROUTED
        THROUGH the verified RNG core's scarab_spin_stops; other geometries
        (Atkins 32^5) use the core's generic float_to_index."""
        if self.reel_lengths == tuple(sq_rng.SCARAB_SPIN_REELS):
            return sq_rng.scarab_spin_stops(list(floats))
        return [sq_rng.float_to_index(f, L)
                for f, L in zip(floats, self.reel_lengths)]

    def _window(self, stops: Sequence[int]) -> List[List[int]]:
        """3x5 visible grid (rows x reels); stop = central row."""
        return [[self.strips[i][(stops[i] + r - 1) % self.reel_lengths[i]]
                 for i in range(5)] for r in range(ROWS)]

    def _spin_cents(self, stops: Sequence[int],
                    bonus: bool = False) -> Tuple[int, int, List[int]]:
        """(total win in line-bet cents, scatter count, per-line cents).
        ``bonus`` evaluates the spin under the free-spin rules (published
        multiplier baked in, pure-5-wild exemption when configured)."""
        window = self._window(stops)
        line_cents = []
        for line in self.paylines:
            tup = tuple(window[line[i]][i] for i in range(5))
            line_cents.append(self._line_pay_cents_scalar(tup, bonus=bonus))
        k = sum(int(self._scnt[i][stops[i]]) for i in range(5))
        sc = self._scatter_cents_bonus if bonus else self._scatter_cents
        total = sum(line_cents) + int(sc[k])
        return total, k, line_cents

    def play_round(
        self, server_seed: str, client_seed: str, nonce: int
    ) -> Dict[str, object]:
        """Play one verifiable round: base spin (floats 0..4 of the bet's
        stream — the published "5 game event numbers") plus, when 3+
        scatters land, the full free-spin feature.  Bonus spin j consumes
        floats 5*(j+1) .. 5*(j+1)+4 of the SAME nonce's stream (the cursor
        keeps incrementing within the bet — Stake: "Slots: the incremental
        number is only utilised for bonus rounds").  Returns win
        multipliers per unit TOTAL bet, capped at ``max_win`` when set.
        """
        fps = self.floats_per_spin
        unit = 100 * self.n_lines
        floats = sq_rng.generate_floats(server_seed, client_seed, nonce, 0, fps)
        stops = self._stops_from_floats(floats)
        base_cents, k, line_cents = self._spin_cents(stops)
        triggered = k >= self.trigger_count
        total_cents = base_cents
        bonus_spins = 0
        bonus_cents = 0
        if triggered:
            cap = self.free_spin_cap
            hard = _SAFETY_SPIN_CAP if cap is None else cap
            remaining = min(self.free_spins, hard)
            while remaining > 0 and bonus_spins < hard:
                cursor = 4 * fps * (1 + bonus_spins)   # bytes
                f = sq_rng.generate_floats(
                    server_seed, client_seed, nonce, cursor, fps)
                s = self._stops_from_floats(f)
                cents, kk, _ = self._spin_cents(s, bonus=True)
                bonus_cents += cents
                bonus_spins += 1
                remaining -= 1
                if kk >= self.trigger_count:
                    remaining += self.free_spins
                if cap is not None:
                    # published rule: "Bonus rounds are capped at 180 free
                    # spins" — retriggers never extend a bonus past the cap
                    remaining = min(remaining, cap - bonus_spins)
            total_cents += bonus_cents
        capped = False
        if self.max_win is not None:
            cap_cents = round(self.max_win * unit)
            if total_cents > cap_cents:
                total_cents = cap_cents
                capped = True
        return {
            "stops": stops,
            "window": self._window(stops),
            "scatters": k,
            "line_wins": [c / 100.0 for c in line_cents],   # x bet per line
            "base_win": base_cents / unit,                  # x total bet
            "triggered": triggered,
            "bonus_spins": bonus_spins,
            "bonus_win": bonus_cents / unit,
            "payout": total_cents / unit,
            "multiplier": total_cents / unit,
            "capped": capped,
            "win": total_cents > 0,
            "config": self.config(),
            "verification": {
                "server_seed": server_seed,
                "client_seed": client_seed,
                "nonce": nonce,
            },
        }

    # ------------------------------------------------------------------
    # (c) vectorized simulator
    # ------------------------------------------------------------------

    def _bulk_spin_cents(
        self, stops: np.ndarray, bonus: bool = False
    ) -> Tuple[np.ndarray, np.ndarray]:
        """(win cents, scatter counts) for a (N, 5) stop matrix — vectorized
        version of :meth:`_spin_cents` (LUT gathers per payline)."""
        n = self.n_symbols
        lut = self._lut_cents_bonus if bonus else self._lut_cents
        strides = [n ** (4 - i) for i in range(5)]
        cents = np.zeros(stops.shape[0], dtype=np.int64)
        for line in self.paylines:
            idx = np.zeros(stops.shape[0], dtype=np.int64)
            for i in range(5):
                idx += self._sym_at[i][line[i]][stops[:, i]] * strides[i]
            cents += lut[idx]
        k = np.zeros(stops.shape[0], dtype=np.int64)
        for i in range(5):
            k += self._scnt[i][stops[:, i]]
        cents += (self._scatter_cents_bonus if bonus
                  else self._scatter_cents)[k]
        return cents, k

    def _resolve_bonuses(
        self, server_seed: str, client_seed: str, nonces: np.ndarray
    ) -> Tuple[np.ndarray, int]:
        """Resolve the free-spin feature for every triggered round.

        Walks each triggered nonce's byte stream exactly like
        :meth:`play_round` (floats 5, 10, ... of the same nonce — 5 floats
        per spin) but extracts only STOPS scalar-side (stops alone decide
        retriggers); all line evaluation is done vectorized on the
        collected spin matrix afterwards.  Returns (bonus cents per round,
        total bonus spins).
        """
        key = server_seed.encode("utf-8")
        prefix = client_seed.encode("utf-8") + b":"
        base_hmac = _hmac.new(key, b"", hashlib.sha256)
        fps = self.floats_per_spin
        B = 4 * fps
        lens_u64 = np.array(self.reel_lengths, dtype=np.uint64)
        scnt = self._scnt
        mats: List[np.ndarray] = []   # per-round (spins, 5) stop matrices
        spins_per: List[int] = []     # bonus spins per triggered round
        total_spins = 0
        trigger_count = self.trigger_count
        free_spins = self.free_spins
        fs_cap = self.free_spin_cap
        hard = _SAFETY_SPIN_CAP if fs_cap is None else fs_cap

        for nonce in nonces.tolist():
            msg = prefix + b"%d:" % nonce
            stream = bytearray()
            n_digests = 0
            # speculative stream generation (Blue-Samurai-style over-read is
            # NOT happening on the verifiable path: play_round consumes the
            # identical floats — extra generated bytes are simply not used)
            cap_spins = 4 * free_spins
            st = k_list = None
            spin = 0
            remaining = min(free_spins, hard)
            while remaining > 0 and spin < hard:
                if st is None or spin >= cap_spins:
                    if st is not None:
                        cap_spins *= 2
                    cap_spins = min(cap_spins, hard)
                    need = (1 + cap_spins) * B
                    while len(stream) < need:
                        h = base_hmac.copy()
                        h.update(msg + b"%d" % n_digests)
                        stream += h.digest()
                        n_digests += 1
                    vals = np.frombuffer(bytes(stream), dtype=">u4")
                    vals = vals[fps:fps * (1 + cap_spins)].astype(np.uint64)
                    st = ((vals.reshape(-1, fps) * lens_u64) >> np.uint64(32)
                          ).astype(np.int64)
                    k_arr = scnt[0][st[:, 0]]
                    for i in range(1, 5):
                        k_arr = k_arr + scnt[i][st[:, i]]
                    k_list = k_arr.tolist()
                if k_list[spin] >= trigger_count:
                    remaining += free_spins
                remaining -= 1
                spin += 1
                if fs_cap is not None:
                    # published 180-spin bonus cap (same clamp as play_round)
                    remaining = min(remaining, fs_cap - spin)
            mats.append(st[:spin])
            spins_per.append(spin)
            total_spins += spin
        bonus_cents = np.zeros(len(nonces), dtype=np.int64)
        if total_spins:
            stops_mat = np.concatenate(mats, axis=0)
            # free-spin evaluation: the published multiplier (and the pure-
            # 5-wild exemption, when configured) is baked into the bonus LUT
            cents, _ = self._bulk_spin_cents(stops_mat, bonus=True)
            owner = np.repeat(np.arange(len(nonces), dtype=np.int64),
                              np.array(spins_per, dtype=np.int64))
            np.add.at(bonus_cents, owner, cents)
        return bonus_cents, total_spins

    def simulate(
        self,
        n_rounds: int,
        bulk: Optional[BulkRng] = None,
        chunk_rounds: int = 1_000_000,
        progress: bool = True,
    ) -> Dict[str, object]:
        """Simulate ``n_rounds`` provably-fair rounds (one nonce per round,
        5 floats per base spin; triggered rounds resolve their free spins
        from the same nonce's continuing stream, exactly like
        :meth:`play_round`) and return the standard result dict.

        Win accumulation is exact integer cents; empirical RTP/SD are
        computed from the exact totals.  Chunked so per-chunk arrays stay
        far below 500 MB — the chunk size adapts to the expected free-spin
        load (p * E[spins per bonus]) so the collected bonus-spin matrix
        stays small even for high-trigger par sheets.
        """
        if n_rounds <= 0:
            raise ValueError("n_rounds must be positive")
        rng = bulk if bulk is not None else BulkRng()
        exact = self.enumerate_exact()
        fps = self.floats_per_spin
        spin_load = (float(exact["p_bonus_trigger"])
                     * float(exact["expected_bonus_spins"]))
        chunk_rounds = min(chunk_rounds,
                           max(50_000, int(2_000_000 / max(spin_load, 0.02))))
        unit = 100 * self.n_lines
        reel_lens = np.array(self.reel_lengths, dtype=np.float64)
        cap_cents = (None if self.max_win is None
                     else int(round(self.max_win * unit)))
        scarab_geometry = self.reel_lengths == tuple(sq_rng.SCARAB_SPIN_REELS)

        nonce_first = rng.nonce_next
        total_cents = 0
        sum_sq = 0.0           # (units of total bet)^2, float64
        n_triggered = 0
        n_bonus_spins = 0
        n_base_winners = 0
        n_capped = 0
        done = 0
        t0 = time.perf_counter()
        while done < n_rounds:
            step = min(chunk_rounds, n_rounds - done)
            chunk_nonce0 = rng.nonce_next
            if scarab_geometry:
                # published 30/30/30/30/41 stops through the verified core
                stops = rng.scarab_spins(step)
            else:
                fm = rng.float_matrix(step, fps)
                stops = np.floor(fm[:, :5] * reel_lens).astype(np.int64)
            cents, k = self._bulk_spin_cents(stops)
            trig = k >= self.trigger_count
            trig_idx = np.nonzero(trig)[0]
            if trig_idx.size:
                nonces = chunk_nonce0 + trig_idx
                bonus_cents, spins = self._resolve_bonuses(
                    rng.server_seed, rng.client_seed, nonces)
                cents[trig_idx] += bonus_cents
                n_triggered += int(trig_idx.size)
                n_bonus_spins += spins
            if cap_cents is not None:
                over = cents > cap_cents
                n_over = int(np.count_nonzero(over))
                if n_over:
                    n_capped += n_over
                    np.minimum(cents, cap_cents, out=cents)
            n_base_winners += int(np.count_nonzero(cents))
            total_cents += int(cents.sum())
            x = cents.astype(np.float64) / unit
            sum_sq += float(np.dot(x, x))
            done += step
            if progress and n_rounds > chunk_rounds:
                rate = done / (time.perf_counter() - t0)
                print(f"  slots {self.name}: {done:,}/{n_rounds:,} rounds "
                      f"({rate:,.0f}/s)", flush=True)
        elapsed = time.perf_counter() - t0

        rtp_emp = float(Fraction(total_cents, n_rounds * unit))
        var_emp = sum_sq / n_rounds - rtp_emp ** 2
        std_emp = math.sqrt(max(var_emp, 0.0))
        se = float(exact["std_per_unit"]) / math.sqrt(n_rounds)
        z = (rtp_emp - float(exact["rtp"])) / se if se > 0 else 0.0
        return {
            "rtp": rtp_emp,
            "house_edge": 1.0 - rtp_emp,
            "std_per_unit": std_emp,
            "config": self.config(),
            "n_rounds": n_rounds,
            "n_triggered": n_triggered,
            "trigger_rate": n_triggered / n_rounds,
            "n_bonus_spins": n_bonus_spins,
            "n_capped": n_capped,
            "total_payout": total_cents / unit,
            "analytic_rtp": float(exact["rtp"]),
            "analytic_std_per_unit": float(exact["std_per_unit"]),
            "se_rtp": se,
            "z_score": z,
            "within_3se": abs(z) <= 3.0,
            "elapsed_s": elapsed,
            "rounds_per_sec": n_rounds / elapsed if elapsed > 0 else float("inf"),
            "verification": {
                "server_seed_hash": rng.server_seed_hash,
                "client_seed": rng.client_seed,
                "nonce_range": (nonce_first, rng.nonce_next),
            },
        }


# ---------------------------------------------------------------------------
# Model constructors
# ---------------------------------------------------------------------------

def atkins_machine() -> SlotMachine:
    """The calibrated Atkins-style par sheet (references/woo/slots.md)."""
    return SlotMachine(
        name="atkins",
        symbols=ATKINS_SYMBOLS,
        strips=ATKINS_STRIPS,
        line_pays=ATKINS_LINE_PAYS,
        wild=ATKINS_WILD,
        scatter=ATKINS_SCATTER,
        scatter_pays=ATKINS_SCATTER_PAYS,
        scatter_pay_basis="total",
        free_spins=ATKINS_FREE_SPINS,
        free_spin_multiplier=ATKINS_FREE_MULT,
    )


def scarab_machine() -> SlotMachine:
    """Scarab Spin (references/stake/slots.md Sect. 3a + 4): published
    paytable payout-for-payout, published reel geometry 30/30/30/30/41
    driven by exactly 5 floats per spin through the verified RNG core,
    published 10,000x max win, King Tut wild ON the reel strips (the
    published "random wilds in the base game"), count matrix calibrated
    so the exact RTP prints the published 97.84%."""
    return SlotMachine(
        name="scarab_spin",
        symbols=SCARAB_SYMBOLS,
        strips=SCARAB_STRIPS,
        line_pays=SCARAB_LINE_PAYS,
        wild=SCARAB_WILD,
        scatter=SCARAB_SCATTER,
        scatter_pays=SCARAB_SCATTER_PAYS,
        scatter_pay_basis="line",
        free_spins=SCARAB_FREE_SPINS,
        free_spin_multiplier=SCARAB_FREE_MULT,
        max_win=SCARAB_MAX_WIN,
        free_spin_cap=SCARAB_FREE_SPIN_CAP,
        wild_substitution_double=SCARAB_WILD_DOUBLE,
        wild5_multiplier_exempt=SCARAB_WILD5_EXEMPT,
    )


def tome_of_life_machine() -> SlotMachine:
    """Tome of Life — the same published math model as Scarab Spin with
    re-skinned symbol names, exactly as the reference states (Sect. 5 note:
    structurally identical paytable, same 2.16% edge, same fixed-reel
    event math).  The bonus rule set of the SHARED model is the one the
    reference publishes in full on the Tome page (Sect. 5) and in part on
    the Scarab page (Sect. 4, a strict subset — "receive 15 bonus free
    spins"): 15 free spins on 3 scatters, retriggers hard-capped at 180
    total spins, all bonus wins tripled except a pure 5-wild line, and
    wild-substitution combinations paying double.  Both games therefore
    run the identical par sheet and print the identical published
    97.84% / 2.16%."""
    m = scarab_machine()
    return SlotMachine(
        name="tome_of_life",
        symbols=TOME_SYMBOLS,
        strips=m.strips,
        line_pays=SCARAB_LINE_PAYS,
        wild=SCARAB_WILD,
        scatter=SCARAB_SCATTER,
        scatter_pays=SCARAB_SCATTER_PAYS,
        scatter_pay_basis="line",
        free_spins=SCARAB_FREE_SPINS,
        free_spin_multiplier=SCARAB_FREE_MULT,
        max_win=SCARAB_MAX_WIN,
        free_spin_cap=SCARAB_FREE_SPIN_CAP,
        wild_substitution_double=SCARAB_WILD_DOUBLE,
        wild5_multiplier_exempt=SCARAB_WILD5_EXEMPT,
    )
