"""Tests for the slots engine (references/woo/slots.md + references/stake/slots.md)."""

import math
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spinquest_sim import rng as sq_rng  # noqa: E402
from spinquest_sim.games import slots as S  # noqa: E402
from spinquest_sim.games.slots import (  # noqa: E402
    ATKINS_LINE_PAYS,
    ATKINS_SCATTER,
    ATKINS_STRIPS,
    ATKINS_SYMBOLS,
    ATKINS_WILD,
    N_LINES,
    PAYLINES_20,
    SCARAB_COUNTS,
    SCARAB_LINE_PAYS,
    SCARAB_SCATTER,
    SCARAB_SCATTER_PAYS,
    SCARAB_SHAPE_GATES,
    SCARAB_STRIPS,
    SCARAB_WILD,
    SCARAB_WILD_FIRE_K,
    SCARAB_WILD_TILE_K,
    STAKE_SCARAB_PRINTED,
    STAKE_SCARAB_PUBLISHED,
    STAKE_SCARAB_RTP_TOL,
    WOO_ATKINS_PRINTED,
    WOO_ATKINS_PUBLISHED,
    WOO_ATKINS_TOL,
    WOO_CLEOPATRA_HIT_20LINE,
    WOO_SLOT_SD_BAND,
    SlotMachine,
    atkins_machine,
    scarab_machine,
    tome_of_life_machine,
)
from spinquest_sim.rng import BulkRng  # noqa: E402

SEED = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
CLIENT = "slots-test-client"
TWO32 = 1 << 32


@pytest.fixture(scope="module")
def atkins():
    return atkins_machine()


@pytest.fixture(scope="module")
def scarab():
    return scarab_machine()


@pytest.fixture(scope="module")
def atkins_exact(atkins):
    return atkins.enumerate_exact()


@pytest.fixture(scope="module")
def scarab_exact(scarab):
    return scarab.enumerate_exact()


@pytest.fixture(scope="module")
def scarab_base_machine():
    """The Scarab strips WITHOUT the wild drop — exercises the brute-force
    stop-enumeration path on the same par sheet (the no-wild mixture
    component), used to cross-check the factorized analytics."""
    return SlotMachine(
        name="scarab_base", symbols=S.SCARAB_SYMBOLS, strips=SCARAB_STRIPS,
        line_pays=SCARAB_LINE_PAYS, wild=SCARAB_WILD, scatter=SCARAB_SCATTER,
        scatter_pays=SCARAB_SCATTER_PAYS, scatter_pay_basis="line",
        free_spins=15, free_spin_multiplier=1)


@pytest.fixture(scope="module")
def scarab_base_exact(scarab_base_machine):
    return scarab_base_machine.enumerate_exact()


# ---------------------------------------------------------------------------
# Structure / paytable transcription
# ---------------------------------------------------------------------------

def test_geometry():
    assert len(PAYLINES_20) == N_LINES == 20
    assert len(set(PAYLINES_20)) == 20
    for line in PAYLINES_20:
        assert len(line) == 5 and all(r in (0, 1, 2) for r in line)
    assert tuple(len(s) for s in ATKINS_STRIPS) == (32,) * 5
    assert tuple(len(s) for s in SCARAB_STRIPS) == (30, 30, 30, 30, 41)


def test_scarab_reels_match_verified_rng_core(scarab):
    # references/stake/slots.md Sect. 3a: 30/30/30/30/41 central stops — the
    # verified RNG core carries the same constant.
    assert scarab.reel_lengths == sq_rng.SCARAB_SPIN_REELS
    assert scarab.reel_lengths == STAKE_SCARAB_PUBLISHED["reel_lengths"]


def test_scarab_paytable_payout_for_payout():
    """Stake's published Scarab Spin table (references/stake/slots.md Sect. 4),
    literal transcription — payout-for-payout against the engine tables."""
    published = {
        "Cat": (0.10, 0.25, 1.25, 5.00),
        "Gold Coin": (None, 0.25, 1.25, 5.00),
        "Diamond": (None, 0.25, 1.25, 5.00),
        "Spade": (None, 0.25, 1.25, 5.00),
        "Club": (None, 0.25, 2.50, 5.00),
        "Heart": (None, 0.50, 2.50, 6.25),
        "Blue Coin": (None, 0.50, 2.50, 12.50),
        "Green Gem": (None, 0.50, 3.75, 12.50),
        "Purple Gem": (None, 0.75, 5.00, 20.00),
        "Red Gem": (0.10, 1.25, 5.00, 37.50),
        "Yellow Gem": (0.10, 1.25, 5.00, 37.50),
        "King Tut (Wild)": (0.50, 10.00, 100.00, 500.00),
        "Scarab Beetle Scatter": (2.00, 6.00, 50.00, 500.00),
    }
    m = scarab_machine()
    for name, row in published.items():
        if name == "Scarab Beetle Scatter":
            table = {k: SCARAB_SCATTER_PAYS.get(k) for k in (2, 3, 4, 5)}
        else:
            idx = list(m.symbols).index(name)
            table = {k: SCARAB_LINE_PAYS[idx].get(k) for k in (2, 3, 4, 5)}
        for k, pay in zip((2, 3, 4, 5), row):
            assert table[k] == pay, (name, k, table[k], pay)


def test_scarab_published_rules_carried(scarab):
    """Published Sect. 4 facts beyond the paytable: 15 free spins on 3
    scatters, 10,000x max win, random wilds in the base game."""
    assert scarab.free_spins == STAKE_SCARAB_PUBLISHED["free_spins"] == 15
    assert scarab.trigger_count == 3
    assert scarab.max_win == STAKE_SCARAB_PUBLISHED["max_win"] == 10_000.0
    assert scarab.overlay and STAKE_SCARAB_PUBLISHED["random_wilds"]
    assert scarab.floats_per_spin == 21


def test_tome_of_life_shares_scarab_model(scarab):
    tome = tome_of_life_machine()
    assert tome.symbols[11] == "Tome of Life (Wild)"
    assert tome.strips == scarab.strips
    # same strips + paytable + wild drop => identical math without
    # re-running the analytics
    assert tome._lut_cents.tolist() == scarab._lut_cents.tolist()
    assert tome.wild_drop_fire_k == scarab.wild_drop_fire_k
    assert tome.wild_drop_tile_k == scarab.wild_drop_tile_k
    assert tome.max_win == scarab.max_win


# ---------------------------------------------------------------------------
# Par-sheet shape (the round-4 gates: no inverted ladder artifacts)
# ---------------------------------------------------------------------------

def _spearman(x, y):
    def ranks(a):
        a = np.asarray(a, dtype=np.float64)
        order = np.argsort(a, kind="stable")
        r = np.empty(len(a))
        srt = a[order]
        i = 0
        while i < len(a):
            j = i
            while j + 1 < len(a) and srt[j + 1] == srt[i]:
                j += 1
            r[order[i:j + 1]] = (i + j) / 2.0 + 1.0
            i = j + 1
        return r
    rx, ry = ranks(x), ranks(y)
    rx -= rx.mean()
    ry -= ry.mean()
    return float((rx * ry).sum() / math.sqrt((rx ** 2).sum() * (ry ** 2).sum()))


def test_scarab_counts_match_strips():
    """SCARAB_COUNTS is exactly the per-reel content of SCARAB_STRIPS."""
    for r, strip in enumerate(SCARAB_STRIPS):
        for s in range(11):
            assert strip.count(s) == SCARAB_COUNTS[r][s], (r, s)
        assert strip.count(SCARAB_WILD) == 0
        assert strip.count(SCARAB_SCATTER) == 1


def test_scarab_ladder_monotone_in_pay():
    """Counts monotone non-increasing as the 5-of-a-kind pay rises, on
    every reel: commons frequent, premiums rare."""
    pays = [SCARAB_LINE_PAYS[s][5] for s in range(11)]
    assert pays == sorted(pays)  # symbols are in ascending-pay order
    for r in range(5):
        row = SCARAB_COUNTS[r]
        assert all(row[i] >= row[i + 1] for i in range(10)), (r, row)


def test_scarab_ladder_spearman():
    """Spearman(5-of-a-kind pay, total strip count) over all 12 paying
    symbols (wild included, at its 0 strip stops) must be <= -0.9: higher
    pay => fewer stops.  (Equivalently >= +0.9 against the pay rank taken
    in DESCENDING order — the inverted round-2/3 sheet scored -0.88 on that
    convention with the 500x wild the most common symbol on the machine.)"""
    pays = [SCARAB_LINE_PAYS[s][5] for s in range(12)]  # incl wild 500x
    totals = [sum(SCARAB_COUNTS[r][s] for r in range(5)) for s in range(11)]
    totals.append(sum(strip.count(SCARAB_WILD) for strip in SCARAB_STRIPS))
    rho = _spearman(pays, totals)
    assert rho <= -SCARAB_SHAPE_GATES["spearman_abs_min"], rho


def test_scarab_wild_not_on_strips():
    """The King Tut wild is the published RANDOM overlay ("random wilds in
    the base game") — it must not occupy any strip stop."""
    assert not SCARAB_SHAPE_GATES["wild_on_strips"]
    for strip in SCARAB_STRIPS:
        assert SCARAB_WILD not in strip


def test_scarab_no_duplicate_reel_count_vectors():
    """No two reels may share a full count vector (round-2/3 shipped reels
    1 and 2 byte-identical in counts)."""
    full = []
    for strip in SCARAB_STRIPS:
        full.append(tuple(strip.count(s) for s in range(13)))
    assert len(set(full)) == 5, full


def test_scarab_per_reel_cv():
    """Every reel's 13-entry count vector needs cv >= 0.4 (round-3 reel 5
    was eight 3s + four 4s + 1 scatter, cv 0.244)."""
    for strip in SCARAB_STRIPS:
        v = np.array([strip.count(s) for s in range(13)], dtype=np.float64)
        cv = v.std() / v.mean()
        assert cv >= SCARAB_SHAPE_GATES["per_reel_cv_min"], (strip, cv)


def test_scarab_sd_inside_published_band(scarab_exact):
    """Full-round relative SD must sit inside the Wizard of Odds' published
    slot band 5.18 (Cleopatra, 20 lines) .. 13.45 (1 line).  Round 3
    shipped 3.15."""
    lo, hi = WOO_SLOT_SD_BAND
    sd = float(scarab_exact["std_per_unit"])
    assert lo <= sd <= hi, sd


def test_scarab_base_hit_frequency_sane(scarab_base_exact, scarab_exact):
    """Without the wild drop, the fraction of spins with any line win must
    sit in the neighbourhood of the only published 20-line hit frequency
    (Cleopatra 35.88%) — not the 92.16% of the inverted round-3 sheet.
    The drop fires on only ~4.7% of spins, so the round-total stays close."""
    h0 = float(scarab_base_exact["any_line_hit_frequency"])
    assert 0.15 <= h0 <= 0.50, h0
    assert abs(h0 - WOO_CLEOPATRA_HIT_20LINE) < 0.15
    pi = float(scarab_exact["overlay"]["fire_prob"])
    assert pi < 0.10  # the drop is a feature, not the norm


def test_scarab_factorized_matches_brute_force(scarab_exact, scarab_base_exact):
    """The factorized analytics' no-wild component must equal the
    brute-force 30^4*41 stop enumeration of the same strips: exact Fraction
    equality on the first moments, float64 agreement on the second."""
    base = scarab_exact["components"]["base"]
    assert base["line_return"] == scarab_base_exact["line_return"]
    assert base["hit_frequency"] == scarab_base_exact["hit_frequency"]
    unit2 = (100 * 20) ** 2
    assert math.isclose(base["e_y2_cents2"] / unit2,
                        scarab_base_exact["e_y2"], rel_tol=1e-11)
    assert math.isclose(base["e_yz_cents"] / (100 * 20),
                        scarab_base_exact["e_yz"], rel_tol=1e-11)
    # scatter machinery identical
    assert scarab_exact["p_bonus_trigger"] == scarab_base_exact["p_bonus_trigger"]
    assert scarab_exact["scatter_return"] == scarab_base_exact["scatter_return"]


# ---------------------------------------------------------------------------
# Line evaluation rule
# ---------------------------------------------------------------------------

def test_line_pay_hand_examples(atkins):
    W, SC = ATKINS_WILD, ATKINS_SCATTER
    pay = atkins.line_pay
    # plain runs
    assert pay((1, 1, 1, 4, 5)) == 25          # 3 Steaks
    assert pay((1, 1, 4, 4, 4)) == 2           # leftmost 2 Steaks only
    assert pay((2, 2, 5, 5, 5)) == 0           # 2 Hams pay nothing
    assert pay((1, 1, 1, 1, 1)) == 300
    # wild substitution
    assert pay((W, 1, 1, 4, 5)) == 25          # W-S-S = 3 Steaks
    assert pay((1, W, 1, 1, 9)) == 100         # 4 Steaks via wild
    assert pay((W, W, 2, 2, 2)) == 200         # 5 Hams via wilds
    # highest interpretation only: WW alone pays 5, but WW+Bacon3 = 5 too;
    # W,W,Steak -> Steak x3 = 25 beats wild x2 = 5
    assert pay((W, W, 1, 9, 9)) == 25
    # wild's own pay beats a low-symbol continuation:
    # W,W,W,Bacon -> wild x3 = 50 > bacon x4 = 25
    assert pay((W, W, W, 8, 3)) == 50
    assert pay((W, W, W, W, W)) == 5000
    # scatter on a line is a dead symbol and breaks runs
    assert pay((1, SC, 1, 1, 1)) == 0
    assert pay((SC, 1, 1, 1, 1)) == 0


def test_lut_matches_scalar_rule(atkins, scarab):
    rng = np.random.default_rng(7)
    for m in (atkins, scarab):
        n = m.n_symbols
        lut = m._lut_cents
        strides = [n ** (4 - i) for i in range(5)]
        for _ in range(500):
            tup = tuple(int(x) for x in rng.integers(0, n, size=5))
            idx = sum(t * s for t, s in zip(tup, strides))
            assert lut[idx] == m._line_pay_cents_scalar(tup), tup


def test_scatter_pays_interior_hole_carries_forward():
    """Regression: a scatter_pays dict with an interior hole (e.g.
    {2: 1.00, 5: 100.00}) must pay the highest published rung at or below
    the count — never silently 0 at k=3, 4."""
    m = SlotMachine(
        name="hole", symbols=S.SCARAB_SYMBOLS, strips=SCARAB_STRIPS,
        line_pays=SCARAB_LINE_PAYS, wild=SCARAB_WILD, scatter=SCARAB_SCATTER,
        scatter_pays={2: 1.00, 5: 100.00}, scatter_pay_basis="line",
        free_spins=15, free_spin_multiplier=1)
    sc = m._scatter_cents
    assert sc[0] == 0 and sc[1] == 0          # below the lowest rung: 0
    assert sc[2] == 100                        # published
    assert sc[3] == 100 and sc[4] == 100       # interior hole carried
    assert sc[5] == 10000                      # published
    for k in range(6, 16):
        assert sc[k] == 10000                  # beyond top rung: top rung


# ---------------------------------------------------------------------------
# Exact analytics vs published figures
# ---------------------------------------------------------------------------

def test_atkins_reproduces_every_published_figure(atkins_exact):
    ex = atkins_exact
    assert ex["outcomes"] == WOO_ATKINS_PUBLISHED["outcomes"] == 32 ** 5
    checks = {
        "line_return": ex["line_return"],
        "scatter_return": ex["scatter_return"],
        "bonus_return": ex["bonus_return"],
        "total_rtp": ex["rtp"],
        "hit_frequency": ex["hit_frequency"],
        "p_bonus_trigger": ex["p_bonus_trigger"],
        "expected_bonus_spins": ex["expected_bonus_spins"],
        "expected_bonus_win": ex["expected_bonus_win"],
    }
    for key, mine in checks.items():
        diff = abs(float(mine) - WOO_ATKINS_PUBLISHED[key])
        assert diff <= WOO_ATKINS_TOL[key], (key, float(mine), diff)


def test_atkins_prints_every_published_figure(atkins_exact):
    """The stronger gate: each enumerated figure, formatted at the precision
    WoO printed it, must equal WoO's printed string EXACTLY — e.g.
    f"{100*rtp:.3f}" == "97.046".  No float tolerance can hide a last-digit
    miss here."""
    for fig, (key, scale, spec, want) in WOO_ATKINS_PRINTED.items():
        got = format(scale * float(atkins_exact[key]), spec)
        assert got == want, (fig, got, want)


def test_atkins_tolerances_are_true_half_ulp():
    """Guard against tolerance fudging: every tolerance must be exactly half
    an ULP of the corresponding printed figure's precision (percent figures
    printed to 3 dp -> 5e-6 on the fraction; 5.45% to 2 dp -> 5e-5;
    6-decimal figures -> 5e-7)."""
    half_ulp = {
        "total_rtp": 5.0e-6,
        "line_return": 5.0e-6,
        "scatter_return": 5.0e-6,
        "bonus_return": 5.0e-6,
        "hit_frequency": 5.0e-5,
        "p_bonus_trigger": 5.0e-7,
        "expected_bonus_spins": 5.0e-7,
        "expected_bonus_win": 5.0e-7,
    }
    assert WOO_ATKINS_TOL == half_ulp
    assert STAKE_SCARAB_RTP_TOL == 5.0e-5   # "97.84%" printed to 2 dp


def test_scarab_reproduces_published_rtp(scarab_exact):
    assert abs(float(scarab_exact["rtp"]) - STAKE_SCARAB_PUBLISHED["rtp"]) \
        <= STAKE_SCARAB_RTP_TOL
    assert abs(float(scarab_exact["house_edge"])
               - STAKE_SCARAB_PUBLISHED["house_edge"]) <= STAKE_SCARAB_RTP_TOL
    # the exact rational RTP is carried alongside the float
    rtp_frac = scarab_exact["rtp_fraction"]
    assert isinstance(rtp_frac, Fraction)
    assert abs(rtp_frac - Fraction(9784, 10000)) < Fraction(1, 10 ** 8)


def test_scarab_prints_published_figures(scarab_exact):
    for fig, (key, scale, spec, want) in STAKE_SCARAB_PRINTED.items():
        got = format(scale * float(scarab_exact[key]), spec)
        assert got == want, (fig, got, want)


def test_no_duplicate_reels():
    assert len(set(ATKINS_STRIPS)) == 5
    assert len(set(SCARAB_STRIPS)) == 5


def test_marginals_cross_check_enumeration(atkins, atkins_exact,
                                           scarab_base_machine,
                                           scarab_base_exact):
    """Per-line return/hit-frequency computed from symbol COUNTS alone
    (independent code path, no windows, no paylines) must equal the full
    joint enumeration exactly — Fraction equality, not approximate."""
    for m, ex in ((atkins, atkins_exact),
                  (scarab_base_machine, scarab_base_exact)):
        L, H = m.marginal_line_stats()
        assert L == ex["line_return"]
        assert H == ex["hit_frequency"]


def test_scarab_mixture_marginals(scarab, scarab_exact):
    """The wild-drop machine's marginal stats are the exact fire-probability
    mixture of the component contractions."""
    L, H = scarab.marginal_line_stats()
    assert L == scarab_exact["line_return"]
    assert H == scarab_exact["hit_frequency"]
    pi = Fraction(SCARAB_WILD_FIRE_K, TWO32)
    comp = scarab_exact["components"]
    assert L == (1 - pi) * comp["base"]["line_return"] \
        + pi * comp["fire"]["line_return"]


def test_scatter_distribution_cross_check(atkins, atkins_exact):
    pmf = atkins.scatter_distribution()
    enum_pmf = atkins_exact["scatter_pmf"]
    assert np.allclose(pmf, enum_pmf, atol=1e-15)
    # scatters spaced >= 3 on every Atkins reel -> never 2 per window
    assert all(int(c.max()) <= 1 for c in atkins._scnt)


def test_bonus_recursion_consistency(atkins_exact, scarab_exact):
    for ex, F, m in ((atkins_exact, 10, 3.0), (scarab_exact, 15, 1.0)):
        p = float(ex["p_bonus_trigger"])
        mu = float(ex["base_return"])
        assert math.isclose(ex["expected_bonus_spins"], F / (1 - F * p),
                            rel_tol=1e-12)
        assert math.isclose(ex["expected_bonus_win"],
                            F * m * mu / (1 - F * p), rel_tol=1e-12)
        assert math.isclose(float(ex["rtp"]),
                            mu + p * float(ex["expected_bonus_win"]),
                            rel_tol=1e-12)
        assert float(ex["variance_per_unit"]) > 0


# ---------------------------------------------------------------------------
# Provably-fair mechanics
# ---------------------------------------------------------------------------

def test_play_round_stops_come_from_verified_stream(atkins, scarab):
    for nonce in (0, 1, 17, 123):
        floats = sq_rng.generate_floats(SEED, CLIENT, nonce, 0, 5)
        r = atkins.play_round(SEED, CLIENT, nonce)
        assert r["stops"] == [math.floor(f * 32) for f in floats]
        r2 = scarab.play_round(SEED, CLIENT, nonce)
        # identical to the verified scalar helper for the 30/30/30/30/41 reels
        assert r2["stops"] == sq_rng.scarab_spin(SEED, CLIENT, nonce)


def _independent_line_cents(tup, wild):
    """Independent re-implementation of the published line rule: highest
    left-aligned interpretation, wild substitutes for all but scatter."""
    best = 0
    for s_id, pays in SCARAB_LINE_PAYS.items():
        run = 0
        for s in tup:
            if s == s_id or (s == wild and s_id != wild):
                run += 1
            else:
                break
        best = max(best, round(100 * pays.get(min(run, 5), 0.0)))
    return best


def test_scarab_wild_drop_replay():
    """Replay Scarab base spins byte-for-byte from the published stream: 21
    floats — 5 stops, drop-arm float 5 vs SCARAB_WILD_FIRE_K, tile floats
    6..20 vs SCARAB_WILD_TILE_K reel-major — through an INDEPENDENT line
    evaluator; every nonce must match play_round exactly."""
    m = scarab_machine()
    fired = 0
    for nonce in range(400):
        f = sq_rng.generate_floats(SEED, CLIENT, nonce, 0, 21)
        stops = [math.floor(f[i] * L) for i, L in
                 zip(range(5), (30, 30, 30, 30, 41))]
        fire = f[5] < SCARAB_WILD_FIRE_K / TWO32
        grid = [[SCARAB_STRIPS[i][(stops[i] + r - 1) % len(SCARAB_STRIPS[i])]
                 for i in range(5)] for r in range(3)]
        if fire:
            fired += 1
            for i in range(5):
                for r in range(3):
                    if (f[6 + 3 * i + r] < SCARAB_WILD_TILE_K / TWO32
                            and grid[r][i] != SCARAB_SCATTER):
                        grid[r][i] = SCARAB_WILD
        cents = 0
        for line in PAYLINES_20:
            tup = tuple(grid[line[i]][i] for i in range(5))
            cents += _independent_line_cents(tup, SCARAB_WILD)
        k = sum(1 for r in range(3) for i in range(5)
                if SCARAB_STRIPS[i][(stops[i] + r - 1) % len(SCARAB_STRIPS[i])]
                == SCARAB_SCATTER)
        cents += {2: 200, 3: 600, 4: 5000, 5: 50000}.get(k, 0)
        r = m.play_round(SEED, CLIENT, nonce)
        assert r["stops"] == stops and r["wild_drop"] == fire, nonce
        assert math.isclose(r["base_win"], cents / 2000.0, abs_tol=1e-12), nonce
    assert fired > 5   # the drop actually fires at ~4.7%


def test_bonus_spins_consume_same_nonce_stream_atkins(atkins):
    """Find a triggered round; its bonus spin j must use floats
    5(j+1)..5(j+1)+4 of the SAME nonce (cursor continues within the bet —
    'the incremental number is only utilised for bonus rounds')."""
    nonce = next(n for n in range(5000)
                 if atkins.play_round(SEED, CLIENT, n)["triggered"])
    r = atkins.play_round(SEED, CLIENT, nonce)
    assert r["bonus_spins"] >= atkins.free_spins
    # replay the feature by hand from the published float stream
    unit = 100 * atkins.n_lines
    total = 0
    remaining, spin = atkins.free_spins, 0
    while remaining > 0:
        f = sq_rng.generate_floats(SEED, CLIENT, nonce, 20 * (1 + spin), 5)
        stops = [math.floor(x * L) for x, L in zip(f, atkins.reel_lengths)]
        cents, k, _ = atkins._spin_cents(stops)
        total += cents * 3
        if k >= 3:
            remaining += atkins.free_spins
        remaining -= 1
        spin += 1
    assert spin == r["bonus_spins"]
    assert math.isclose(total / unit, r["bonus_win"], abs_tol=1e-12)
    assert math.isclose(r["payout"], r["base_win"] + r["bonus_win"],
                        abs_tol=1e-12)


def test_bonus_spins_consume_same_nonce_stream_scarab(scarab):
    """Scarab bonus spin j uses floats 21(j+1)..21(j+1)+20 (84-byte cursor
    strides) of the same nonce — wild drop included in free spins."""
    nonce = next(n for n in range(3000)
                 if scarab.play_round(SEED, CLIENT, n)["triggered"])
    r = scarab.play_round(SEED, CLIENT, nonce)
    assert r["bonus_spins"] >= scarab.free_spins
    unit = 100 * scarab.n_lines
    total = 0
    remaining, spin = scarab.free_spins, 0
    while remaining > 0:
        f = sq_rng.generate_floats(SEED, CLIENT, nonce, 84 * (1 + spin), 21)
        stops = [math.floor(x * L) for x, L in zip(f[:5], scarab.reel_lengths)]
        fire, tiles = scarab._overlay_from_floats(f)
        cents, k, _ = scarab._spin_cents(stops, fire, tiles)
        total += cents
        if k >= 3:
            remaining += scarab.free_spins
        remaining -= 1
        spin += 1
    assert spin == r["bonus_spins"]
    assert math.isclose(total / unit, r["bonus_win"], abs_tol=1e-12)
    assert math.isclose(r["payout"], r["base_win"] + r["bonus_win"],
                        abs_tol=1e-12)


def test_window_layout(atkins):
    r = atkins.play_round(SEED, CLIENT, 3)
    stops = r["stops"]
    win = r["window"]
    for i in range(5):
        L = atkins.reel_lengths[i]
        assert win[1][i] == atkins.strips[i][stops[i]]              # centre
        assert win[0][i] == atkins.strips[i][(stops[i] - 1) % L]    # top
        assert win[2][i] == atkins.strips[i][(stops[i] + 1) % L]    # bottom


def test_max_win_cap():
    """The published 10,000x max win is enforced as a round cap; a clone
    with a tiny cap demonstrates the mechanism end to end."""
    m = scarab_machine()
    assert m.config()["max_win"] == 10_000.0
    tiny = SlotMachine(
        name="tiny_cap", symbols=S.SCARAB_SYMBOLS, strips=SCARAB_STRIPS,
        line_pays=SCARAB_LINE_PAYS, wild=SCARAB_WILD, scatter=SCARAB_SCATTER,
        scatter_pays=SCARAB_SCATTER_PAYS, scatter_pay_basis="line",
        free_spins=15, free_spin_multiplier=1,
        wild_drop_fire_k=SCARAB_WILD_FIRE_K,
        wild_drop_tile_k=SCARAB_WILD_TILE_K, max_win=0.05)
    capped = 0
    for nonce in range(200):
        r = tiny.play_round(SEED, CLIENT, nonce)
        assert r["payout"] <= 0.05 + 1e-12
        capped += r["capped"]
        full = m.play_round(SEED, CLIENT, nonce)
        if full["payout"] > 0.05:
            assert r["capped"] and r["payout"] == 0.05
    assert capped > 0
    # capped simulate agrees with capped scalar play
    bulk = BulkRng(server_seed=SEED, client_seed=CLIENT, nonce_start=0)
    sim = tiny.simulate(200, bulk=bulk, progress=False)
    tot = sum(tiny.play_round(SEED, CLIENT, k)["payout"] for k in range(200))
    assert math.isclose(sim["rtp"], tot / 200, abs_tol=1e-9)
    assert sim["n_capped"] == capped


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------

def test_simulate_bit_matches_scalar_play(atkins):
    n = 3000
    bulk = BulkRng(server_seed=SEED, client_seed=CLIENT, nonce_start=0)
    sim = atkins.simulate(n, bulk=bulk, progress=False)
    total = sum(atkins.play_round(SEED, CLIENT, k)["payout"] for k in range(n))
    assert math.isclose(sim["rtp"], total / n, abs_tol=1e-9)
    assert sim["verification"]["nonce_range"] == (0, n)
    assert sim["verification"]["server_seed_hash"] == sq_rng.hash_server_seed(SEED)


def test_simulate_bit_matches_scalar_play_scarab(scarab):
    n = 2000
    bulk = BulkRng(server_seed=SEED, client_seed=CLIENT, nonce_start=0)
    sim = scarab.simulate(n, bulk=bulk, progress=False)
    total = sum(scarab.play_round(SEED, CLIENT, k)["payout"] for k in range(n))
    assert math.isclose(sim["rtp"], total / n, abs_tol=1e-9)
    assert sim["n_wild_drops"] > 0


def test_simulate_within_3se_fixed_seed(scarab):
    # deterministic seed -> deterministic z; 200k rounds catches a broken
    # payout path (SE ~ 0.019 at SD 8.59)
    bulk = BulkRng(server_seed=SEED, client_seed=CLIENT, nonce_start=0)
    sim = scarab.simulate(200_000, bulk=bulk, progress=False)
    assert sim["within_3se"], (sim["rtp"], sim["analytic_rtp"], sim["z_score"])
    assert sim["n_triggered"] > 0 and sim["n_bonus_spins"] > 0
    assert 0.04 < sim["wild_drop_rate"] < 0.055


def test_standard_result_dicts(atkins):
    a = atkins.analytic_summary()
    for key in ("rtp", "house_edge", "std_per_unit", "config"):
        assert key in a
    assert math.isclose(a["rtp"] + a["house_edge"], 1.0, abs_tol=1e-12)
    cfg = a["config"]
    assert cfg["game"] == "slots" and cfg["n_lines"] == 20
    assert cfg["reel_strips"] == [list(s) for s in ATKINS_STRIPS]
    assert cfg["wild"] == ATKINS_SYMBOLS[ATKINS_WILD]
    assert cfg["scatter"] == ATKINS_SYMBOLS[ATKINS_SCATTER]
    assert cfg["wild_drop"] is None


def test_scarab_config_declares_wild_drop(scarab):
    cfg = scarab.analytic_summary()["config"]
    wd = cfg["wild_drop"]
    assert wd["fire_threshold_k"] == SCARAB_WILD_FIRE_K
    assert wd["tile_threshold_k"] == SCARAB_WILD_TILE_K == 2 ** 31
    assert wd["floats_per_spin"] == 21
    assert wd["never_covers_scatter"]
    assert cfg["max_win"] == 10_000.0


def test_input_validation():
    with pytest.raises(ValueError):
        SlotMachine("bad", ATKINS_SYMBOLS, ATKINS_STRIPS[:4],
                    ATKINS_LINE_PAYS, ATKINS_WILD, ATKINS_SCATTER,
                    {3: 5}, "total", 10, 3)
    with pytest.raises(ValueError):
        SlotMachine("bad", ATKINS_SYMBOLS, ATKINS_STRIPS,
                    ATKINS_LINE_PAYS, ATKINS_WILD, ATKINS_SCATTER,
                    {3: 5}, "nope", 10, 3)
    with pytest.raises(ValueError):
        # wild drop needs both thresholds
        SlotMachine("bad", S.SCARAB_SYMBOLS, SCARAB_STRIPS,
                    SCARAB_LINE_PAYS, SCARAB_WILD, SCARAB_SCATTER,
                    SCARAB_SCATTER_PAYS, "line", 15, 1,
                    wild_drop_fire_k=100, wild_drop_tile_k=0)
    with pytest.raises(ValueError):
        m = atkins_machine()
        m.simulate(0)
