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
2.16% / RTP 97.84%, reel geometry 30/30/30/30/41 central stops (the
provably-fair game-event mapping ``floor(float * reel_length)`` is already
in the verified RNG core: :func:`spinquest_sim.rng.scarab_spin_stops`).
Stake publishes the COMPLETE line paytable payout-for-payout (transcribed
below symbol-for-symbol; Tome of Life's table is identical), the bonus
rule (3 scatters -> 15 free spins), the max win (10,000x the bet) and the
wild mechanic — "random wilds in the base game, represented by King Tut's
mask. Wild symbols substitute for all symbols except scatter symbols"
(reference Sect. 4, verbatim) — but not the reel strips or the wild-drop
frequencies (Sect. 7).

The reconstruction is therefore split into what the reference pins and
what must be calibrated:

* The PAYTABLE is transcribed payout-for-payout (wins multiply the bet per
  line, not the total bet; the scatter pays 2+ anywhere on the reels —
  both published verbatim).
* The REEL STRIPS are a conventional descending par-sheet ladder derived
  deterministically by ``scripts/calibrate_slots.py``: per-reel symbol
  counts are monotone non-increasing in the symbol's 5-of-a-kind pay
  (commons most frequent, premiums rarest), chosen as the ranked nearest
  integer ladders to the inverse-square-root-of-pay profile — see the
  script for the exact ordered search.  No wild appears on any strip
  (wilds are the published RANDOM overlay below), every reel carries one
  scatter, all five count vectors are distinct, and every reel's count
  vector has coefficient of variation >= 0.4 (``SCARAB_SHAPE_GATES``).
* The published "random wilds in the base game" are modelled as a
  provably-fair OVERLAY FEATURE (the "wild drop"): each spin consumes 21
  floats — floats 0-4 pick the 5 central stops (the published Sect. 3a
  mapping), float 5 arms the wild drop (it fires iff the float's 32-bit
  value is below ``SCARAB_WILD_FIRE_K``), and floats 6-20 cover the 15
  visible tiles reel-major (tile (reel i, row r) <- float 6+3i+r): when
  the drop fired, a tile turns wild iff its float's 32-bit value is below
  ``SCARAB_WILD_TILE_K`` and the tile is not a scatter.  When the drop did
  not fire the 15 tile floats are simply unused — exactly the convention
  Stake publishes for Blue Samurai ("for the sake of simplicity in the
  provably fair model, we just generate 12 floats every time, and if the
  float ... has a stuck samurai ..., then that float is not used at all").
  The drop applies to base and free spins alike, and never covers a
  scatter, so scatter counts and the bonus trigger stay strip-only.

Why an overlay is forced by the published numbers: exact enumeration of
Stake's published paytable over ANY conventional descending ladder yields
a base line return of well under 1% of the total bet (the table tops out
at 37.50x bet-per-line for a regular 5-of-a-kind; with the shipped strips
it is exactly 23,929,000/(30^4*41*100) = 0.7205% per line), while the
published 97.84% RTP with the published 15-free-spin feature needs a base
return of ~87% — only the published wild feature (its row pays 0.50/10/
100/500) can carry the difference.  The two calibrated constants close
that gap exactly and deterministically (``scripts/calibrate_slots.py``):

* ``SCARAB_WILD_TILE_K = 2**31`` (tile probability exactly 1/2 on fire
  spins) is selected by a fixed scan of the dyadic grid j/16 as the value
  whose full-round relative standard deviation (8.5921) lands inside the
  Wizard of Odds' published slot-SD band 5.18-13.45 (Cleopatra, 20 lines
  .. 1 line) closest to his published typical slot SD 8.74
  (references/woo/slots.md, house-edge master table).
* ``SCARAB_WILD_FIRE_K = 203404370`` (fire probability K/2^32 =
  0.047358770...) is the unique 32-bit threshold minimising the exact
  distance |RTP - 97.84%|: RTP = (E0 + pi*(E1-E0) + sc)/(1 - 15*p) with
  every term an exact rational — E0 = 23929000/(30^4*41*100) the no-wild
  line return, E1 = 1919198207150/(30^4*41*3200) the fire-spin line
  return (per-tile symbol distributions contracted exactly against the
  integer paytable LUT), sc = the scatter return, p = 119/16400 the
  3+-scatter probability — giving RTP = 0.9784000009194...  which prints
  "97.84" (house edge "2.16") with 9.2e-10 to spare against the half-ULP
  window of the printed figure (5e-5).

Base-game shape with the ladder strips (all recomputed, none asserted):
92.16%-of-spins-pay is gone — without a wild drop 29.41% of spins hit a
line (exact 30^4*41 enumeration; vs the only published 20-line hit
frequency, Cleopatra's 35.88%), per-line hit frequency 2.89%, and the
wild drop fires on 4.74% of spins.  The published 10,000x-bet max win is
enforced as a payout cap on every round (the cap binds with probability
too small to affect any analytic figure at double precision: a single
spin cannot exceed 500x the total bet, so a capped round needs 20+
near-perfect wild screens in one bonus chain).

**Engine contract** (same as every other game in this package):

(a) analytic paytable / probability / RTP / variance computation — exact
    enumeration of all reel-stop combinations for strip-only machines;
    for wild-drop machines an exact per-reel factorization (the 5 stops
    and 15 overlay indicators are independent across reels, so every
    line-pair moment is a tensor contraction of the paytable LUT against
    per-reel joint distributions — first moments in exact integer /
    Fraction arithmetic, second moments in float64), cross-checked in the
    tests against the brute-force stop enumeration of the no-wild
    component;
(b) provably-fair single-round play on the verified scalar RNG path
    (5 floats -> 5 central stops, plus the 16 wild-drop floats for Scarab;
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
distribution (per-line marginals depend only on per-reel symbol counts and
the wild-drop probabilities), so the pattern choice affects only
inter-line correlation (variance), not any published return figure.
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import math
import struct
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
    "SCARAB_WILD_FIRE_K",
    "SCARAB_WILD_TILE_K",
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
_TWO32 = 1 << 32

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
# and its wild-drop tile probability targets the 8.74 exemplar.
WOO_SLOT_SD_BAND: Tuple[float, float] = (5.18, 13.45)
WOO_TYPICAL_SLOT_SD = 8.74
WOO_CLEOPATRA_HIT_20LINE = 0.3588

# references/stake/slots.md — Scarab Spin / Tome of Life published math.
STAKE_SCARAB_PUBLISHED: Dict[str, object] = {
    "rtp": 0.9784,                 # "RTP 97.84%"
    "house_edge": 0.0216,          # "Edge: 2.16 %" badge
    "reel_lengths": (30, 30, 30, 30, 41),
    "free_spins": 15,              # "receive 15 bonus free spins"
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
# non-increasing in pay on every reel; the wild must not occupy strip stops
# (it is the published random overlay); no two reels may share a count
# vector; every reel's 13-entry count vector needs cv >= 0.4; and the
# full-round relative SD must sit inside the published slot band.
SCARAB_SHAPE_GATES: Dict[str, object] = {
    "spearman_abs_min": 0.9,
    "per_reel_cv_min": 0.4,
    "sd_band": WOO_SLOT_SD_BAND,
    "wild_on_strips": False,
    "distinct_reel_count_vectors": True,
    "counts_monotone_in_pay": True,
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
SCARAB_FREE_MULT = 1
SCARAB_REEL_LENGTHS: Tuple[int, ...] = (30, 30, 30, 30, 41)
SCARAB_MAX_WIN = 10_000.0     # "Max win: 10,000x your bet" (Sect. 4)
SCARAB_FLOATS_PER_SPIN = 21   # 5 stops + 1 wild-drop arm + 15 tiles

# CALIBRATED par sheet (scripts/calibrate_slots.py, Scarab stages — fully
# deterministic, re-runnable, byte-for-byte reproducible).  Per-reel counts
# for the 11 line symbols (order = SCARAB_SYMBOLS[0..10], i.e. ascending
# 5-of-a-kind pay): monotone non-increasing in pay on every reel, the
# ranked nearest integer ladders to the pay^(-1/2) profile (reels 1-4 take
# ranks 1-4 of the 29-stop ladder enumeration so no two reels share a
# vector; reel 5 takes rank 1 of the 40-stop enumeration).  The wild NEVER
# occupies a strip stop — it enters only through the published random
# wild drop.  One scatter per reel at deterministic position (4+7i) mod L.
SCARAB_COUNTS: Tuple[Tuple[int, ...], ...] = (
    (4, 4, 4, 3, 3, 3, 2, 2, 2, 1, 1),
    (4, 4, 3, 3, 3, 3, 2, 2, 2, 2, 1),
    (4, 4, 3, 3, 3, 3, 3, 2, 2, 1, 1),
    (4, 4, 4, 4, 3, 3, 2, 2, 1, 1, 1),
    (5, 5, 5, 5, 5, 4, 3, 3, 2, 2, 1),
)
SCARAB_SCATTER_POS: Tuple[Tuple[int, ...], ...] = ((4,), (11,), (18,), (25,), (32,))

# The strips: the deterministic greedy interleave of SCARAB_COUNTS with the
# scatters at SCARAB_SCATTER_POS (identical arrangement routine as the
# Atkins strips; order never touches any published figure — marginals
# depend only on counts).  Totals across the machine: Cat 21, Gold Coin 21,
# Diamond 19, Spade 18, Club 17, Heart 16, Blue Coin 12, Green Gem 11,
# Purple Gem 9, Red Gem 7, Yellow Gem 5, King Tut 0 —
# Spearman(5-of-a-kind pay, total count) = -0.96 (commons frequent,
# premiums rare, the wild rarest of all on the strips at zero).
SCARAB_STRIPS: Tuple[Tuple[int, ...], ...] = (
    (0, 2, 0, 5, 12, 1, 3, 1, 4, 2, 6, 2, 0, 7, 5, 1, 3, 8, 4, 7, 3, 6, 2, 0, 10, 8, 5, 1, 4, 9),
    (0, 5, 1, 3, 1, 4, 2, 0, 9, 4, 0, 12, 6, 8, 3, 5, 1, 7, 2, 5, 1, 4, 0, 9, 2, 6, 3, 8, 10, 7),
    (1, 6, 0, 3, 1, 4, 0, 5, 2, 7, 1, 4, 6, 3, 0, 2, 8, 5, 12, 3, 10, 2, 9, 7, 0, 4, 1, 6, 8, 5),
    (2, 0, 3, 1, 5, 2, 0, 3, 1, 4, 7, 5, 1, 4, 6, 0, 2, 9, 3, 8, 0, 10, 5, 7, 2, 12, 4, 1, 6, 3),
    (3, 1, 4, 2, 0, 3, 1, 4, 0, 5, 2, 0, 5, 3, 7, 2, 6, 4, 1, 6, 9, 5, 3, 7, 0, 8, 2, 4, 1, 10, 6, 9, 12, 8, 3, 5, 0, 2, 7, 4, 1),
)

# Wild-drop thresholds (32-bit; a float f = V/2^32 passes iff V < K).
# Both are the deterministic output of scripts/calibrate_slots.py — see the
# module docstring for the derivation and the exact rational RTP.
SCARAB_WILD_TILE_K = 1 << 31          # tile wild probability 1/2 on fire spins
SCARAB_WILD_FIRE_K = 203404370        # fire probability 0.047358770...


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

    ``wild_drop_fire_k`` / ``wild_drop_tile_k`` switch on the random
    overlay-wild feature (Stake's published "random wilds in the base
    game"): each spin then consumes 21 floats — 5 stops, 1 drop-arm float
    (fires iff its 32-bit value < fire_k) and 15 tile floats reel-major
    (tile (reel i, row r) <- float 6+3i+r; on a fired spin a non-scatter
    tile turns wild iff its 32-bit value < tile_k; on other spins the tile
    floats are unused, Blue-Samurai style).  ``max_win`` caps every round's
    total payout in total-bet multiples (Stake publishes 10,000x).
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
        wild_drop_fire_k: int = 0,
        wild_drop_tile_k: int = 0,
        max_win: Optional[float] = None,
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
        self.wild_drop_fire_k = int(wild_drop_fire_k)
        self.wild_drop_tile_k = int(wild_drop_tile_k)
        if not (0 <= self.wild_drop_fire_k < _TWO32
                and 0 <= self.wild_drop_tile_k < _TWO32):
            raise ValueError("wild-drop thresholds must be 32-bit")
        if (self.wild_drop_fire_k > 0) != (self.wild_drop_tile_k > 0):
            raise ValueError("wild drop needs both fire_k and tile_k")
        self.overlay = self.wild_drop_fire_k > 0
        self.max_win = None if max_win is None else float(max_win)
        if self.max_win is not None and self.max_win <= 0:
            raise ValueError("max_win must be positive")

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
        self._exact_cache: Optional[Dict[str, object]] = None

    # ------------------------------------------------------------------
    # shared structure
    # ------------------------------------------------------------------

    @property
    def floats_per_spin(self) -> int:
        """Floats one spin consumes from the verifiable stream: 5 stops,
        plus (wild-drop machines) 1 drop-arm float and 15 tile floats."""
        return SCARAB_FLOATS_PER_SPIN if self.overlay else 5

    def line_pay(self, line_symbols: Sequence[int]) -> float:
        """Reference (scalar) line evaluation: highest pay among all
        left-aligned interpretations; wild substitutes for everything except
        the scatter; a wild run can also pay as the wild's own symbol."""
        return self._line_pay_cents_scalar(tuple(line_symbols)) / 100.0

    def _line_pay_cents_scalar(self, tup: Tuple[int, ...]) -> int:
        best = 0
        for s_id, pays in self._line_pays_cents.items():
            k = 0
            for s in tup:
                if s == s_id or (s == self.wild and s_id != self.wild):
                    k += 1
                else:
                    break
            p = pays.get(k, 0)
            if k >= 5:
                p = pays.get(5, p)
            if p > best:
                best = p
        return best

    @property
    def _lut_cents(self) -> np.ndarray:
        """Flat int64 LUT of line pay (cents of a line bet) for every
        symbol 5-tuple, index = sum(sym_i * n_sym^(4-i)).  Vectorized build;
        cross-checked against the scalar rule in the tests."""
        if self._lut_cache is not None:
            return self._lut_cache
        n = self.n_symbols
        shape = (n,) * 5
        # grid[j] = symbol index along axis j (broadcast views, no copies)
        grids = [np.arange(n).reshape([n if a == j else 1 for a in range(5)])
                 for j in range(5)]
        best = np.zeros(shape, dtype=np.int64)
        for s_id, pays in self._line_pays_cents.items():
            if s_id == self.wild:
                match = [(g == self.wild) for g in grids]
            else:
                match = [(g == s_id) | (g == self.wild) for g in grids]
            run = np.ones(shape, dtype=bool)
            k = np.zeros(shape, dtype=np.int64)
            for j in range(5):
                run = run & match[j]
                k = k + run
            pay_by_k = np.zeros(6, dtype=np.int64)
            for kk, cents in pays.items():
                if kk <= 5:
                    pay_by_k[kk] = cents
            best = np.maximum(best, pay_by_k[k])
        self._lut_cache = best.reshape(-1)
        return self._lut_cache

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

    def _tile_numerators(self, reel: int, tile_k: int) -> Tuple[List[int], int]:
        """Exact effective per-tile symbol distribution on one reel under a
        wild overlay with probability tile_k/2^32: (numerators, denominator).
        A scatter tile is never overlaid; any other tile turns wild with the
        overlay probability, else keeps its strip symbol."""
        counts = self.symbol_counts()[reel]
        L = self.reel_lengths[reel]
        cs = int(counts[self.scatter])
        cw = int(counts[self.wild])
        nums = [0] * self.n_symbols
        for s in range(self.n_symbols):
            if s == self.scatter:
                nums[s] = cs * _TWO32
            elif s == self.wild:
                nums[s] = cw * _TWO32 + (L - cs - cw) * tile_k
            else:
                nums[s] = int(counts[s]) * (_TWO32 - tile_k)
        g = 0
        for v in nums:
            g = math.gcd(g, v)
        g = g or 1
        return [v // g for v in nums], (L * _TWO32) // g

    def _exact_line_component(self, tile_k: int) -> Tuple[Fraction, Fraction]:
        """(E[single-line pay] in line-bet units, P(line pays)) under a
        constant per-tile overlay probability tile_k/2^32 — exact rational
        big-integer contraction of the paytable LUT (no float rounding)."""
        per_reel = []
        denom = 1
        for i in range(5):
            nums, den = self._tile_numerators(i, tile_k)
            per_reel.append(nums)
            denom *= den
        lut = self._lut_cents
        m = _contract_int(lut, per_reel, self.n_symbols)
        h = _contract_int((lut > 0).astype(np.int64), per_reel, self.n_symbols)
        return Fraction(m, denom * 100), Fraction(h, denom)

    def marginal_line_stats(self) -> Tuple[Fraction, Fraction]:
        """(per-line expected pay in line-bet units, per-line hit prob),
        computed from symbol COUNTS (and, for wild-drop machines, the
        overlay probabilities) only — independent of strip order and of the
        payline patterns.  For strip-only machines this is the cross-check
        for the full enumeration."""
        if not self.overlay:
            counts = self.symbol_counts().astype(np.float64)
            lut = self._lut_cents.reshape((self.n_symbols,) * 5)
            # integer-valued float64 contractions stay exact (< 2^53)
            total = lut.astype(np.float64)
            hits = (lut > 0).astype(np.float64)
            for axis in range(4, -1, -1):
                total = np.tensordot(total, counts[axis], axes=([axis], [0]))
                hits = np.tensordot(hits, counts[axis], axes=([axis], [0]))
            denom = 1
            for L in self.reel_lengths:
                denom *= L
            return (Fraction(int(round(float(total))), denom * 100),
                    Fraction(int(round(float(hits))), denom))
        pi = Fraction(self.wild_drop_fire_k, _TWO32)
        e0, h0 = self._exact_line_component(0)
        e1, h1 = self._exact_line_component(self.wild_drop_tile_k)
        return (1 - pi) * e0 + pi * e1, (1 - pi) * h0 + pi * h1

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
        """Exact analytics.

        Strip-only machines (Atkins): brute-force enumeration of ALL
        reel-stop combinations (32^5) with the full 20-line + scatter
        evaluation per outcome — first moments in exact integer/Fraction
        arithmetic, second moments float64 — then the exact free-spin
        recursion.

        Wild-drop machines (Scarab): the stops and the 16 overlay floats
        are independent across reels, so every moment factorizes per reel:
        first moments (returns, probabilities, RTP) are exact rational
        big-integer contractions; second moments (variance/SD only) are
        float64 tensor contractions over per-reel joint distributions of
        the 20x20 line pairs (correlations through shared tiles and shared
        overlay indicators are exact by construction).  The no-wild
        component is cross-checked against the brute-force stop enumeration
        in the tests.
        """
        if self._exact_cache is not None:
            return self._exact_cache
        if self.overlay:
            result = self._overlay_exact(progress=progress)
        else:
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

        line_cents_total = 0            # exact
        scatter_cents_total = 0         # exact
        line_hits_total = 0             # exact, summed over lines
        any_hit_total = 0               # outcomes with any line pay
        trigger_total = 0               # outcomes with k >= trigger_count
        k_hist = np.zeros(5 * ROWS + 1, dtype=np.int64)
        sum_y2 = 0.0                    # float64: E[Y^2] (line-bet cents^2)
        sum_yz = 0                      # exact: E[Y * 1{trigger}]
        y = np.empty(inner_size, dtype=np.int64)
        for t1 in range(lens[0]):
            y[:] = 0
            hits_here = np.zeros(inner_size, dtype=np.int64)
            for l in range(self.n_lines):
                pays = lut[inners[l] + heads[l][t1]]
                y += pays
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
        fold = self._fold_free_spins(F, m, p, mu, e_y2, float(e_yz))

        result: Dict[str, object] = {
            "outcomes": denom,
            "line_return": line_return,
            "scatter_return": scatter_return,
            "base_return": mu_y,
            "bonus_return": p * fold["e_t"],
            "rtp": fold["rtp"],
            "house_edge": 1.0 - fold["rtp"],
            "p_bonus_trigger": p_trigger,
            "hit_frequency": hit_freq,
            "any_line_hit_frequency": Fraction(any_hit_total, denom),
            "scatter_pmf": k_hist / denom,
            "scatter_counts": k_hist,
            "expected_bonus_spins": fold["e_spins"],
            "expected_bonus_win": fold["e_t"],
            "e_y": mu,
            "e_y2": e_y2,
            "e_yz": float(e_yz),
            "e_x2": fold["e_x2"],
            "variance_per_unit": fold["var"],
            "std_per_unit": math.sqrt(fold["var"]),
            "elapsed_s": time.perf_counter() - t0,
        }
        return result

    # -- wild-drop analytics (per-reel factorization) -------------------

    def _eff_rows(self, w: float) -> np.ndarray:
        """(n, n) raw-symbol -> effective-symbol distribution rows under a
        per-tile overlay probability w (scatter never overlaid)."""
        n = self.n_symbols
        E = np.zeros((n, n))
        for x in range(n):
            if x == self.scatter:
                E[x, x] = 1.0
            else:
                E[x, x] += 1.0 - w
                E[x, self.wild] += w
        return E

    def _pair_mats(self, w: float) -> List[Dict[int, np.ndarray]]:
        """Per reel: {delta: (n, n) joint distribution of the effective
        symbols at two rows offset by delta}.  delta=0 shares the tile (and
        its overlay indicator); other deltas have independent indicators."""
        n = self.n_symbols
        E = self._eff_rows(w)
        out: List[Dict[int, np.ndarray]] = []
        for strip in self.strips:
            L = len(strip)
            mats: Dict[int, np.ndarray] = {}
            for d in range(-2, 3):
                M = np.zeros((n, n))
                if d == 0:
                    for u in range(L):
                        M[np.arange(n), np.arange(n)] += E[strip[u]]
                else:
                    for u in range(L):
                        M += np.outer(E[strip[u]], E[strip[(u + d) % L]])
                mats[d] = M / L
            out.append(mats)
        return out

    def _kappa_joints(self, w: float) -> List[List[np.ndarray]]:
        """Per reel, per row: (n, 3) joint of (effective symbol at that
        row, scatter count in the same reel's window)."""
        n = self.n_symbols
        E = self._eff_rows(w)
        out: List[List[np.ndarray]] = []
        for i, strip in enumerate(self.strips):
            L = len(strip)
            scnt = self._scnt[i]
            rows = []
            for r in range(ROWS):
                J = np.zeros((n, 3))
                for t in range(L):
                    J[:, scnt[t]] += E[strip[(t + r - 1) % L]]
                rows.append(J / L)
            out.append(rows)
        return out

    def _component_moments(self, tile_k: int) -> Tuple[float, float]:
        """(E[Y^2], E[Y * 1{trigger}]) of one mixture component (constant
        per-tile overlay probability tile_k/2^32), with Y the spin win in
        line-bet cents.  Float64 tensor contractions on exact rational
        per-reel joints (used only for variance / SD)."""
        w = tile_k / _TWO32
        n = self.n_symbols
        G = self._lut_cents.reshape((n,) * 5).astype(np.float64)
        PM = self._pair_mats(w)
        KJ = self._kappa_joints(w)
        pmf = self.scatter_distribution()
        sc = self._scatter_cents.astype(np.float64)
        z_vec = (np.arange(5 * ROWS + 1) >= self.trigger_count).astype(float)

        cache: Dict[Tuple[int, ...], float] = {}
        e_pairs = 0.0
        for la in self.paylines:
            for lb in self.paylines:
                dt = tuple(lb[i] - la[i] for i in range(5))
                if dt not in cache:
                    H = G
                    for i in range(5):
                        H = np.tensordot(H, PM[i][dt[i]], axes=([0], [0]))
                    cache[dt] = float(np.tensordot(H, G, axes=5))
                e_pairs += cache[dt]

        e_pay_sc = 0.0
        e_pay_z = 0.0
        for line in self.paylines:
            acc: Dict[int, np.ndarray] = {0: G}
            for i in range(5):
                J = KJ[i][line[i]]
                nxt: Dict[int, np.ndarray] = {}
                for k, tens in acc.items():
                    for kap in range(3):
                        col = J[:, kap]
                        if not col.any():
                            continue
                        r = np.tensordot(tens, col, axes=([0], [0]))
                        if k + kap in nxt:
                            nxt[k + kap] = nxt[k + kap] + r
                        else:
                            nxt[k + kap] = r
                acc = nxt
            dist = np.zeros(5 * ROWS + 1)
            for k, v in acc.items():
                dist[k] = float(v)
            e_pay_sc += float(dist @ sc)
            e_pay_z += float(dist @ z_vec)

        e_sc2 = float(pmf @ (sc ** 2))
        e_sc_z = float((pmf * z_vec) @ sc)
        e_y2 = e_pairs + 2.0 * e_pay_sc + e_sc2
        e_yz = e_pay_z + e_sc_z
        return e_y2, e_yz

    def _overlay_exact(self, progress: bool = False) -> Dict[str, object]:
        t0 = time.perf_counter()
        pi = Fraction(self.wild_drop_fire_k, _TWO32)
        e0, h0 = self._exact_line_component(0)
        e1, h1 = self._exact_line_component(self.wild_drop_tile_k)
        line_return = (1 - pi) * e0 + pi * e1
        hit_freq = (1 - pi) * h0 + pi * h1
        sc_ret, p_trigger, pmf = self._scatter_return_exact()
        mu_y = line_return + sc_ret

        F = self.free_spins
        m_frac = Fraction(self.free_spin_multiplier)
        if F * p_trigger >= 1:
            raise ValueError("free-spin retrigger process does not terminate")
        e_t_frac = F * m_frac * mu_y / (1 - F * p_trigger)
        rtp_frac = mu_y + p_trigger * e_t_frac

        # second moments (variance/SD only): mixture over the two components
        pi_f = float(pi)
        y2_0, yz_0 = self._component_moments(0)
        y2_1, yz_1 = self._component_moments(self.wild_drop_tile_k)
        unit = 100 * self.n_lines
        e_y2 = ((1.0 - pi_f) * y2_0 + pi_f * y2_1) / unit ** 2
        e_yz = ((1.0 - pi_f) * yz_0 + pi_f * yz_1) / unit
        p = float(p_trigger)
        mu = float(mu_y)
        fold = self._fold_free_spins(F, self.free_spin_multiplier, p, mu,
                                     e_y2, e_yz)

        denom = 1
        for L in self.reel_lengths:
            denom *= L
        k_hist = np.array([int(pr * denom) for pr in pmf], dtype=np.int64)
        result: Dict[str, object] = {
            "outcomes": denom,
            "line_return": line_return,
            "scatter_return": sc_ret,
            "base_return": mu_y,
            "bonus_return": float(p_trigger * e_t_frac),
            "rtp": float(rtp_frac),
            "rtp_fraction": rtp_frac,
            "house_edge": float(1 - rtp_frac),
            "p_bonus_trigger": p_trigger,
            "hit_frequency": hit_freq,
            "any_line_hit_frequency": None,   # not factorizable; see tests
            "scatter_pmf": k_hist / denom,
            "scatter_counts": k_hist,
            "expected_bonus_spins": fold["e_spins"],
            "expected_bonus_win": fold["e_t"],
            "e_y": mu,
            "e_y2": e_y2,
            "e_yz": e_yz,
            "e_x2": fold["e_x2"],
            "variance_per_unit": fold["var"],
            "std_per_unit": math.sqrt(fold["var"]),
            "components": {
                "base": {"line_return": e0, "hit_frequency": h0,
                         "e_y2_cents2": y2_0, "e_yz_cents": yz_0},
                "fire": {"line_return": e1, "hit_frequency": h1,
                         "e_y2_cents2": y2_1, "e_yz_cents": yz_1},
            },
            "overlay": {
                "fire_prob": pi,
                "tile_prob": Fraction(self.wild_drop_tile_k, _TWO32),
                "floats_per_spin": self.floats_per_spin,
            },
            "elapsed_s": time.perf_counter() - t0,
        }
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
            "max_win": self.max_win,
        }
        if self.overlay:
            cfg["wild_drop"] = {
                "fire_threshold_k": self.wild_drop_fire_k,
                "fire_prob": self.wild_drop_fire_k / _TWO32,
                "tile_threshold_k": self.wild_drop_tile_k,
                "tile_prob": self.wild_drop_tile_k / _TWO32,
                "floats_per_spin": self.floats_per_spin,
                "applies_to": "base and free spins",
                "never_covers_scatter": True,
            }
        else:
            cfg["wild_drop"] = None
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
        """floor(float * reel_length) per reel — Stake's published mapping
        (identical to rng.scarab_spin_stops for the 30/30/30/30/41 reels)."""
        return [sq_rng.float_to_index(f, L)
                for f, L in zip(floats, self.reel_lengths)]

    def _window(self, stops: Sequence[int]) -> List[List[int]]:
        """3x5 visible grid (rows x reels); stop = central row."""
        return [[self.strips[i][(stops[i] + r - 1) % self.reel_lengths[i]]
                 for i in range(5)] for r in range(ROWS)]

    def _overlay_from_floats(self, floats: Sequence[float]
                             ) -> Tuple[bool, List[bool]]:
        """(drop fired, 15 tile-wild flags reel-major) from one spin's
        floats.  Floats are exactly V/2^32 so the comparisons against the
        32-bit thresholds are exact."""
        if not self.overlay:
            return False, [False] * 15
        fire = floats[5] < self.wild_drop_fire_k / _TWO32
        tile_thresh = self.wild_drop_tile_k / _TWO32
        tiles = [bool(fire and floats[6 + j] < tile_thresh) for j in range(15)]
        return bool(fire), tiles

    def _effective_window(self, stops: Sequence[int], fire: bool,
                          tiles: Sequence[bool]) -> List[List[int]]:
        window = self._window(stops)
        if fire:
            for i in range(5):
                for r in range(ROWS):
                    if tiles[3 * i + r] and window[r][i] != self.scatter:
                        window[r][i] = self.wild
        return window

    def _spin_cents(self, stops: Sequence[int], fire: bool = False,
                    tiles: Sequence[bool] = ()) -> Tuple[int, int, List[int]]:
        """(total win in line-bet cents, scatter count, per-line cents)."""
        window = self._effective_window(stops, fire, tiles or [False] * 15)
        line_cents = []
        for line in self.paylines:
            tup = tuple(window[line[i]][i] for i in range(5))
            line_cents.append(self._line_pay_cents_scalar(tup))
        k = sum(int(self._scnt[i][stops[i]]) for i in range(5))
        total = sum(line_cents) + int(self._scatter_cents[k])
        return total, k, line_cents

    def play_round(
        self, server_seed: str, client_seed: str, nonce: int
    ) -> Dict[str, object]:
        """Play one verifiable round: base spin (floats 0..fps-1 of the
        bet's stream, fps = :attr:`floats_per_spin`) plus, when 3+ scatters
        land, the full free-spin feature.  Bonus spin j consumes floats
        fps*(j+1) .. fps*(j+2)-1 of the SAME nonce's stream (the cursor
        keeps incrementing within the bet — Stake: "Slots: the incremental
        number is only utilised for bonus rounds").  Returns win
        multipliers per unit TOTAL bet, capped at ``max_win`` when set.
        """
        fps = self.floats_per_spin
        unit = 100 * self.n_lines
        floats = sq_rng.generate_floats(server_seed, client_seed, nonce, 0, fps)
        stops = self._stops_from_floats(floats)
        fire, tiles = self._overlay_from_floats(floats)
        base_cents, k, line_cents = self._spin_cents(stops, fire, tiles)
        triggered = k >= self.trigger_count
        total_cents = base_cents
        bonus_spins = 0
        bonus_cents = 0
        if triggered:
            remaining = self.free_spins
            while remaining > 0 and bonus_spins < _SAFETY_SPIN_CAP:
                cursor = 4 * fps * (1 + bonus_spins)   # bytes
                f = sq_rng.generate_floats(
                    server_seed, client_seed, nonce, cursor, fps)
                s = self._stops_from_floats(f)
                bf, bt = self._overlay_from_floats(f)
                cents, kk, _ = self._spin_cents(s, bf, bt)
                bonus_cents += round(cents * self.free_spin_multiplier)
                if kk >= self.trigger_count:
                    remaining += self.free_spins
                remaining -= 1
                bonus_spins += 1
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
            "effective_window": self._effective_window(stops, fire, tiles),
            "wild_drop": fire,
            "overlay_wilds": sum(
                1 for i in range(5) for r in range(ROWS)
                if fire and tiles[3 * i + r]
                and self._window(stops)[r][i] != self.scatter),
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
        self, stops: np.ndarray, fire: Optional[np.ndarray] = None,
        tiles: Optional[np.ndarray] = None,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """(win cents, scatter counts) for a (N, 5) stop matrix — vectorized
        version of :meth:`_spin_cents` (LUT gathers per payline).  ``fire``
        (N,) bool and ``tiles`` (N, 15) bool carry the wild-drop overlay
        for wild-drop machines."""
        n = self.n_symbols
        lut = self._lut_cents
        strides = [n ** (4 - i) for i in range(5)]
        overlay = fire is not None
        cents = np.zeros(stops.shape[0], dtype=np.int64)
        for line in self.paylines:
            idx = np.zeros(stops.shape[0], dtype=np.int64)
            for i in range(5):
                sym = self._sym_at[i][line[i]][stops[:, i]]
                if overlay:
                    wm = fire & tiles[:, 3 * i + line[i]] & (sym != self.scatter)
                    sym = np.where(wm, self.wild, sym)
                idx += sym * strides[i]
            cents += lut[idx]
        k = np.zeros(stops.shape[0], dtype=np.int64)
        for i in range(5):
            k += self._scnt[i][stops[:, i]]
        cents += self._scatter_cents[k]
        return cents, k

    def _resolve_bonuses(
        self, server_seed: str, client_seed: str, nonces: np.ndarray
    ) -> Tuple[np.ndarray, int]:
        """Resolve the free-spin feature for every triggered round.

        Walks each triggered nonce's byte stream exactly like
        :meth:`play_round` (floats fps, 2*fps, ... of the same nonce) but
        extracts only STOPS and the overlay flags scalar-side (stops alone
        decide retriggers); all line evaluation is done vectorized on the
        collected spin matrix afterwards.  Returns (bonus cents per round,
        total bonus spins).
        """
        key = server_seed.encode("utf-8")
        prefix = client_seed.encode("utf-8") + b":"
        fps = self.floats_per_spin
        B = 4 * fps
        fmt = ">%dI" % fps
        lens = self.reel_lengths
        scnt = [c.tolist() for c in self._scnt]
        fire_k = self.wild_drop_fire_k
        tile_k = self.wild_drop_tile_k
        rows: List[Tuple[int, ...]] = []
        owner: List[int] = []
        total_spins = 0
        for ridx, nonce in enumerate(nonces.tolist()):
            msg = prefix + b"%d:" % nonce
            stream = bytearray()
            n_digests = 0
            remaining = self.free_spins
            spin = 0
            while remaining > 0 and spin < _SAFETY_SPIN_CAP:
                base = B * (1 + spin)
                while len(stream) < base + B:
                    stream += _hmac.new(
                        key, msg + b"%d" % n_digests, hashlib.sha256).digest()
                    n_digests += 1
                vals = struct.unpack_from(fmt, stream, base)
                stops = tuple((vals[i] * lens[i]) >> 32 for i in range(5))
                k = sum(scnt[i][stops[i]] for i in range(5))
                if self.overlay:
                    f = 1 if vals[5] < fire_k else 0
                    tiles = tuple(
                        1 if (f and vals[6 + j] < tile_k) else 0
                        for j in range(15))
                    rows.append(stops + (f,) + tiles)
                else:
                    rows.append(stops)
                owner.append(ridx)
                if k >= self.trigger_count:
                    remaining += self.free_spins
                remaining -= 1
                spin += 1
            total_spins += spin
        bonus_cents = np.zeros(len(nonces), dtype=np.int64)
        if rows:
            mat = np.array(rows, dtype=np.int64)
            stops_mat = mat[:, :5]
            if self.overlay:
                fire = mat[:, 5].astype(bool)
                tiles = mat[:, 6:21].astype(bool)
                cents, _ = self._bulk_spin_cents(stops_mat, fire, tiles)
            else:
                cents, _ = self._bulk_spin_cents(stops_mat)
            if self.free_spin_multiplier != 1:
                cents = np.round(cents * self.free_spin_multiplier).astype(np.int64)
            np.add.at(bonus_cents, np.array(owner, dtype=np.int64), cents)
        return bonus_cents, total_spins

    def simulate(
        self,
        n_rounds: int,
        bulk: Optional[BulkRng] = None,
        chunk_rounds: int = 1_000_000,
        progress: bool = True,
    ) -> Dict[str, object]:
        """Simulate ``n_rounds`` provably-fair rounds (one nonce per round,
        fps floats per base spin; triggered rounds resolve their free spins
        from the same nonce's continuing stream, exactly like
        :meth:`play_round`) and return the standard result dict.

        Win accumulation is exact integer cents; empirical RTP/SD are
        computed from the exact totals.  Chunked so per-chunk arrays stay
        far below 500 MB.
        """
        if n_rounds <= 0:
            raise ValueError("n_rounds must be positive")
        rng = bulk if bulk is not None else BulkRng()
        exact = self.enumerate_exact()
        fps = self.floats_per_spin
        if self.overlay:
            chunk_rounds = min(chunk_rounds, 500_000)
        unit = 100 * self.n_lines
        reel_lens = np.array(self.reel_lengths, dtype=np.float64)
        cap_cents = (None if self.max_win is None
                     else int(round(self.max_win * unit)))
        fire_thresh = self.wild_drop_fire_k / _TWO32
        tile_thresh = self.wild_drop_tile_k / _TWO32

        nonce_first = rng.nonce_next
        total_cents = 0
        sum_sq = 0.0           # (units of total bet)^2, float64
        n_triggered = 0
        n_bonus_spins = 0
        n_base_winners = 0
        n_fired = 0
        n_capped = 0
        done = 0
        t0 = time.perf_counter()
        while done < n_rounds:
            step = min(chunk_rounds, n_rounds - done)
            chunk_nonce0 = rng.nonce_next
            fm = rng.float_matrix(step, fps)
            stops = np.floor(fm[:, :5] * reel_lens).astype(np.int64)
            if self.overlay:
                fire = fm[:, 5] < fire_thresh
                tiles = (fm[:, 6:21] < tile_thresh) & fire[:, None]
                n_fired += int(np.count_nonzero(fire))
                cents, k = self._bulk_spin_cents(stops, fire, tiles)
            else:
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
            "n_wild_drops": n_fired,
            "wild_drop_rate": n_fired / n_rounds,
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
    paytable payout-for-payout, published reel geometry 30/30/30/30/41,
    published 10,000x max win, published random wilds modelled as the
    calibrated wild-drop overlay, ladder strips calibrated so the exact
    RTP prints the published 97.84%."""
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
        wild_drop_fire_k=SCARAB_WILD_FIRE_K,
        wild_drop_tile_k=SCARAB_WILD_TILE_K,
        max_win=SCARAB_MAX_WIN,
    )


def tome_of_life_machine() -> SlotMachine:
    """Tome of Life — Stake publishes the structurally identical paytable
    and the same 2.16% edge / fixed-reel event math as Scarab Spin
    (reference Sect. 5 note), so it shares the Scarab math model with
    re-skinned symbol names.  (Tome-specific flourishes — wild-substitution
    pays doubled, 3x bonus multiplier, 180-spin cap, 37x bonus buy — are
    published without the reel data needed to model them separately and are
    NOT modelled.)"""
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
        wild_drop_fire_k=SCARAB_WILD_FIRE_K,
        wild_drop_tile_k=SCARAB_WILD_TILE_K,
        max_win=SCARAB_MAX_WIN,
    )
