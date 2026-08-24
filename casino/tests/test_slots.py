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
    SCARAB_FLOATS_PER_SPIN,
    SCARAB_LINE_PAYS,
    SCARAB_SCATTER,
    SCARAB_SCATTER_PAYS,
    SCARAB_SCATTER_POS,
    SCARAB_SHAPE_GATES,
    SCARAB_STRIPS,
    SCARAB_WILD,
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
def scarab_nowildrow_machine():
    """The Scarab par sheet with the wild's OWN pay row removed (the wild
    still substitutes) — the exact attribution of the wild-as-itself share
    of the line return (SCARAB_SHAPE_GATES['wild_line_return_share_max'])."""
    pays = {s: dict(r) for s, r in SCARAB_LINE_PAYS.items()
            if s != SCARAB_WILD}
    return SlotMachine(
        name="scarab_nowildrow", symbols=S.SCARAB_SYMBOLS,
        strips=SCARAB_STRIPS, line_pays=pays, wild=SCARAB_WILD,
        scatter=SCARAB_SCATTER, scatter_pays=SCARAB_SCATTER_PAYS,
        scatter_pay_basis="line", free_spins=15, free_spin_multiplier=3,
        free_spin_cap=180, wild_substitution_double=True,
        wild5_multiplier_exempt=True)


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
    """Published facts beyond the paytable, all carried by the engine: 15
    free spins on 3 scatters, retriggers hard-capped at 180 total free
    spins, the 3x bonus multiplier with its pure-5-wild exemption, wild-
    substitution doubling (the Sect. 5 rule set of the shared math model),
    10,000x max win, random wilds in the base game (King Tut on the reel
    strips), and the Sect. 3a event math: EXACTLY 5 floats per base spin —
    the verified RNG core's own event count."""
    assert scarab.free_spins == STAKE_SCARAB_PUBLISHED["free_spins"] == 15
    assert scarab.trigger_count == 3
    assert scarab.free_spin_cap \
        == STAKE_SCARAB_PUBLISHED["free_spin_cap"] == 180
    assert scarab.free_spin_multiplier \
        == STAKE_SCARAB_PUBLISHED["free_spin_multiplier"] == 3
    assert scarab.wild5_multiplier_exempt \
        == STAKE_SCARAB_PUBLISHED["wild5_multiplier_exempt"] is True
    assert scarab.wild_substitution_double \
        == STAKE_SCARAB_PUBLISHED["wild_substitution_double"] is True
    assert scarab.max_win == STAKE_SCARAB_PUBLISHED["max_win"] == 10_000.0
    assert STAKE_SCARAB_PUBLISHED["random_wilds"]
    assert any(SCARAB_WILD in strip for strip in scarab.strips)
    assert scarab.floats_per_spin == SCARAB_FLOATS_PER_SPIN == 5
    assert scarab.floats_per_spin == sq_rng.EVENT_COUNTS["scarab_spin"]


def test_tome_of_life_shares_scarab_model(scarab):
    """Reference Sect. 5: Tome of Life is the same math model as Scarab
    Spin (same paytable ladder, same 2.16% edge, same event math) — the
    engine runs the identical par sheet AND the identical published bonus
    rule set (15 spins, 180-spin cap, 3x multiplier with the 5-wild
    exemption, wild-substitution doubling) under re-skinned names, so the
    one calibrated sheet prints 97.84 as Scarab AND as Tome — the joint
    solve."""
    tome = tome_of_life_machine()
    assert tome.symbols[11] == "Tome of Life (Wild)"
    assert tome.strips == scarab.strips
    # same strips + paytable + rules => identical math without re-running
    # the analytics
    assert tome._lut_cents.tolist() == scarab._lut_cents.tolist()
    assert tome._lut_cents_bonus.tolist() == scarab._lut_cents_bonus.tolist()
    assert tome.free_spins == scarab.free_spins == 15
    assert tome.free_spin_cap == scarab.free_spin_cap == 180
    assert tome.free_spin_multiplier == scarab.free_spin_multiplier == 3
    assert tome.wild_substitution_double and scarab.wild_substitution_double
    assert tome.wild5_multiplier_exempt and scarab.wild5_multiplier_exempt
    assert tome.floats_per_spin == scarab.floats_per_spin == 5
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
    """SCARAB_COUNTS (13 columns: 11 line symbols + wild + scatter) is
    exactly the per-reel content of SCARAB_STRIPS."""
    for r, strip in enumerate(SCARAB_STRIPS):
        assert sum(SCARAB_COUNTS[r]) == len(strip)
        for s in range(13):
            assert strip.count(s) == SCARAB_COUNTS[r][s], (r, s)
        # scatters sit at the committed positions, spaced >= 3 (a 3-row
        # window never shows two scatters of one reel)
        pos = tuple(i for i, s in enumerate(strip) if s == SCARAB_SCATTER)
        assert pos == SCARAB_SCATTER_POS[r]
        ext = sorted(pos)
        for a, b in zip(ext, ext[1:] + [ext[0] + len(strip)]):
            assert b - a >= 3, (r, pos)


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
    symbols (wild included, at its real strip stops) must be <= -0.9:
    higher pay => fewer stops.  (The inverted round-2/3 sheet had the 500x
    wild as the MOST common symbol on the machine.)"""
    pays = [SCARAB_LINE_PAYS[s][5] for s in range(12)]  # incl wild 500x
    totals = [sum(SCARAB_COUNTS[r][s] for r in range(5)) for s in range(11)]
    totals.append(sum(strip.count(SCARAB_WILD) for strip in SCARAB_STRIPS))
    rho = _spearman(pays, totals)
    assert rho <= -SCARAB_SHAPE_GATES["spearman_abs_min"], rho


def test_scarab_wild_on_strips():
    """The King Tut wild OCCUPIES strip stops — Stake's "random wilds in
    the base game" land from the reels (the only mechanism the published
    5-floats-per-spin event math permits) — but stays rare: 1-2 stops per
    reel, and its own paytable row is a paytable row with reel presence
    (the round-4 sheet had a 500x row with ZERO stops)."""
    assert SCARAB_SHAPE_GATES["wild_on_strips"]
    cap = SCARAB_SHAPE_GATES["wild_max_stops_per_reel"]
    for strip in SCARAB_STRIPS:
        assert 1 <= strip.count(SCARAB_WILD) <= cap, strip


def test_scarab_wild_line_return_share(scarab, scarab_exact,
                                       scarab_nowildrow_machine):
    """The wild's own row (0.50/10/100/500) may carry at most 20% of the
    line return (round 4 measured 91.4% for the overlay model).  Exact:
    compare the line return against the same par sheet with the wild row
    removed (wild still substitutes) — both by independent count-marginal
    contraction."""
    full, _ = scarab.marginal_line_stats()
    nowild, _ = scarab_nowildrow_machine.marginal_line_stats()
    share = 1 - nowild / full
    assert full == scarab_exact["line_return"]
    assert 0 < share <= SCARAB_SHAPE_GATES["wild_line_return_share_max"], \
        float(share)


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


def test_scarab_hit_frequency_sane(scarab_exact):
    """The fraction of spins with any line win must sit in the
    neighbourhood of the only published 20-line hit frequency (Cleopatra
    35.88%) — not the 92.16% of the inverted round-3 sheet, and not the
    54.69% of the round-4 overlay's fire spins."""
    h0 = float(scarab_exact["any_line_hit_frequency"])
    assert 0.15 <= h0 <= 0.50, h0
    assert abs(h0 - WOO_CLEOPATRA_HIT_20LINE) < 0.15


def test_scarab_every_spin_same_reels_published_multiplier(scarab,
                                                          scarab_exact):
    """No barbell, no overlay: base and free spins draw stops from the
    IDENTICAL reels through the identical 5-float event math — a free spin
    differs from a base spin ONLY by the published 3x multiplier (with its
    published pure-5-wild exemption).  Exact consequence, verified from
    the enumeration: 3*E[Y] - E[W] equals exactly twice the pure-5-wild
    line return (the sole exempted combination), a tiny non-negative
    correction."""
    assert SCARAB_SHAPE_GATES["same_reels_every_spin"]
    ey = float(scarab_exact["base_return"])          # base eval, same stops
    ew = float(scarab_exact["e_w"])                  # bonus eval, same stops
    # multiplier bounds: the exemption can only LOWER the tripled value,
    # and never below pay-1x
    assert ey < ew <= 3.0 * ey + 1e-15
    gap = 3.0 * ey - ew
    assert 0.0 <= gap < 1e-3                         # exemption correction
    # and the free-spin package is exactly E[N] * E[W] of the SAME spin
    # value — no separate feature distribution anywhere
    assert math.isclose(float(scarab_exact["expected_bonus_win"]),
                        float(scarab_exact["expected_bonus_spins"]) * ew,
                        rel_tol=1e-12)


def test_scarab_capped_chain_exact(scarab, scarab_exact):
    """The published bonus rules, exactly: P(chain > 180) = 0
    STRUCTURALLY (pmf support ends at the published cap), E[spins/bonus]
    <= 180, the exact pmf sums to 1, and the chain support starts at the
    published 15 free spins."""
    cap = scarab.free_spin_cap
    assert cap == 180
    pmf = scarab_exact["chain_pmf"]
    assert len(pmf) == cap + 1
    assert scarab_exact["p_chain_exceeds_cap"] == 0.0
    assert math.isclose(float(np.sum(pmf)), 1.0, abs_tol=1e-12)
    assert float(np.sum(pmf[:scarab.free_spins])) == 0.0   # N >= 15 always
    en = float(scarab_exact["expected_bonus_spins"])
    assert scarab.free_spins <= en <= cap
    # exact fraction consistency
    en_frac = scarab_exact["expected_bonus_spins_fraction"]
    assert isinstance(en_frac, Fraction)
    assert math.isclose(en, float(en_frac), rel_tol=1e-15)
    # pmf mean equals the exact E[N] (float DP vs big-integer DP)
    mean_pmf = float(np.dot(np.arange(cap + 1), pmf))
    assert math.isclose(mean_pmf, en, rel_tol=1e-9)


def test_capped_retrigger_hard_stop_end_to_end():
    """A machine whose windows ALWAYS show 3 scatters (scatter every 3rd
    stop on reels 1-3) retriggers on every free spin; without the
    published cap the chain would never end — with it, play_round runs
    EXACTLY 180 free spins and stops."""
    strips = []
    for i, L in enumerate((30, 30, 30, 30, 41)):
        strip = []
        for pos in range(L):
            if i < 3 and pos % 3 == 0:
                strip.append(SCARAB_SCATTER)
            else:
                strip.append((pos + i) % 3)     # cheap commons filler
        strips.append(strip)
    m = SlotMachine(
        name="always_retrigger", symbols=S.SCARAB_SYMBOLS, strips=strips,
        line_pays=SCARAB_LINE_PAYS, wild=SCARAB_WILD, scatter=SCARAB_SCATTER,
        scatter_pays=SCARAB_SCATTER_PAYS, scatter_pay_basis="line",
        free_spins=15, free_spin_multiplier=3, free_spin_cap=180,
        wild_substitution_double=True, wild5_multiplier_exempt=True)
    for i in range(3):
        assert all(int(c) >= 1 for c in m._scnt[i])   # every window: scatter
    r = m.play_round(SEED, CLIENT, 0)
    assert r["triggered"] and r["bonus_spins"] == 180
    # analytics agree: P(N = cap) = 1, E[N] = cap
    ex = m.enumerate_exact()
    assert float(ex["chain_pmf"][180]) == 1.0
    assert float(ex["expected_bonus_spins"]) == 180.0
    # and the vectorized simulator walks the identical capped chain
    bulk = BulkRng(server_seed=SEED, client_seed=CLIENT, nonce_start=0)
    sim = m.simulate(50, bulk=bulk, progress=False)
    assert sim["n_bonus_spins"] == 50 * 180


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
        lut_b = m._lut_cents_bonus
        strides = [n ** (4 - i) for i in range(5)]
        for _ in range(500):
            tup = tuple(int(x) for x in rng.integers(0, n, size=5))
            idx = sum(t * s for t, s in zip(tup, strides))
            assert lut[idx] == m._line_pay_cents_scalar(tup), tup
            assert lut_b[idx] == m._line_pay_cents_scalar(tup, bonus=True), tup
    # Atkins (no exemption, no doubling): the bonus table is exactly the
    # base table tripled — the published "all wins tripled" free spins
    assert (atkins._lut_cents_bonus == 3 * atkins._lut_cents).all()


def test_scarab_wild_doubling_and_bonus_rule_hand_examples(scarab):
    """Published Sect. 5 line rules, by hand: wild-substitution combos pay
    double (base AND bonus); every bonus win is tripled EXCEPT a pure
    5-wild line, which pays its 500x unmultiplied."""
    W = SCARAB_WILD
    pay, bpay = scarab.line_pay, scarab.bonus_line_pay
    # doubling: W,Cat,Cat = 3-oak Cat 0.25 -> 0.50; tripled in the bonus
    assert pay((W, 0, 0, 4, 5)) == 0.50
    assert bpay((W, 0, 0, 4, 5)) == 1.50
    # no wild used -> no doubling
    assert pay((0, 0, 0, 4, 5)) == 0.25
    assert bpay((0, 0, 0, 4, 5)) == 0.75
    # wild mid-run doubles too
    assert pay((0, W, 0, 4, 5)) == 0.50
    # best interpretation AFTER doubling: W,W,RedGem,RedGem,RedGem =
    # 5-oak RedGem 37.50 doubled = 75 > pure-wild 2-oak 0.50
    assert pay((W, W, 9, 9, 9)) == 75.0
    assert bpay((W, W, 9, 9, 9)) == 225.0
    # 4 wilds + RedGem: wild's own 4-oak 100 beats RedGem 5-oak doubled 75;
    # in the bonus the wild 4-oak IS tripled (only 5 wilds are exempt)
    assert pay((W, W, W, W, 9)) == 100.0
    assert bpay((W, W, W, W, 9)) == 300.0
    # pure 5 wilds: 500x, and NOT tripled in the bonus (published
    # exemption: "except when 5 WILD symbols are spun")
    assert pay((W,) * 5) == 500.0
    assert bpay((W,) * 5) == 500.0
    # the wild's own row never doubles (doubling is for wilds used AS
    # another symbol)
    assert pay((W, W, 3, 9, 9)) == max(0.50, 2 * 0.25)  # wild2 vs Spade-3 dbl
    # scatter breaks runs and is never substituted
    assert pay((SCARAB_SCATTER, 0, 0, 0, 0)) == 0.0


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
    # The exact rational RTP is carried alongside the float: E[Y] +
    # p * E[N] * E[W] with E[N] the exact capped-chain expectation — every
    # factor a Fraction.  The RTP comes from the integer count matrix
    # under the PUBLISHED bonus rules (no fitted threshold, no free
    # amplification knob), quantized by the count lattice: the shipped
    # sheet lands within 3e-5 of the published 0.9784, inside the half-ULP
    # window of the printed "97.84" (5e-5), and prints exactly.
    rtp_frac = scarab_exact["rtp_fraction"]
    assert isinstance(rtp_frac, Fraction)
    assert abs(rtp_frac - Fraction(9784, 10000)) < Fraction(3, 10 ** 5)
    assert format(100 * float(rtp_frac), ".2f") == "97.84"


def test_scarab_prints_published_figures(scarab_exact):
    for fig, (key, scale, spec, want) in STAKE_SCARAB_PRINTED.items():
        got = format(scale * float(scarab_exact[key]), spec)
        assert got == want, (fig, got, want)


def test_no_duplicate_reels():
    assert len(set(ATKINS_STRIPS)) == 5
    assert len(set(SCARAB_STRIPS)) == 5


def test_marginals_cross_check_enumeration(atkins, atkins_exact,
                                           scarab, scarab_exact):
    """Per-line return/hit-frequency computed from symbol COUNTS alone
    (independent code path, no windows, no paylines, exact big-integer
    contraction) must equal the full joint enumeration exactly — Fraction
    equality, not approximate."""
    for m, ex in ((atkins, atkins_exact), (scarab, scarab_exact)):
        L, H = m.marginal_line_stats()
        assert L == ex["line_return"]
        assert H == ex["hit_frequency"]


def test_scatter_distribution_cross_check(atkins, atkins_exact):
    pmf = atkins.scatter_distribution()
    enum_pmf = atkins_exact["scatter_pmf"]
    assert np.allclose(pmf, enum_pmf, atol=1e-15)
    # scatters spaced >= 3 on every Atkins reel -> never 2 per window
    assert all(int(c.max()) <= 1 for c in atkins._scnt)


def test_bonus_recursion_consistency(atkins_exact, scarab_exact):
    # Atkins: uncapped geometric chain, closed form (unchanged)
    ex, F, m = atkins_exact, 10, 3.0
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
    # Scarab/Tome: published CAPPED chain — E[N] from the exact DP (never
    # the uncapped geometric formula), E[T] = E[N]*E[W], RTP = E[Y]+p*E[T]
    ex = scarab_exact
    F = 15
    p = float(ex["p_bonus_trigger"])
    mu = float(ex["base_return"])
    en = float(ex["expected_bonus_spins"])
    uncapped = F / (1 - F * p)
    assert en < uncapped          # the cap strictly truncates the chain
    assert math.isclose(ex["expected_bonus_win"],
                        en * float(ex["e_w"]), rel_tol=1e-12)
    assert math.isclose(float(ex["rtp"]),
                        mu + p * float(ex["expected_bonus_win"]),
                        rel_tol=1e-12)
    # exact rational composition agrees with the float
    assert math.isclose(float(ex["rtp_fraction"]), float(ex["rtp"]),
                        rel_tol=1e-15)
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


def _independent_line_cents(tup, wild, bonus=False):
    """Independent re-implementation of the published line rules: highest
    left-aligned interpretation, wild substitutes for all but scatter,
    wild-substitution combinations pay DOUBLE (Sect. 5), and in the bonus
    every interpretation is tripled except a pure 5-wild line (Sect. 5:
    "all wins during the bonus rounds are tripled, except when 5 WILD
    symbols are spun")."""
    best = 0
    for s_id, pays in SCARAB_LINE_PAYS.items():
        run = 0
        wild_used = False
        for s in tup:
            if s == s_id or (s == wild and s_id != wild):
                if s == wild and s_id != wild:
                    wild_used = True
                run += 1
            else:
                break
        cents = round(100 * pays.get(min(run, 5), 0.0))
        if bonus and not (s_id == wild and run >= 5):
            cents *= 3
        if wild_used:
            cents *= 2
        best = max(best, cents)
    return best


def test_scarab_base_spin_replay_five_floats():
    """Replay Scarab base spins byte-for-byte from the published stream:
    EXACTLY 5 floats -> 5 central stops (floor(f * L), the Sect. 3a rule)
    -> 3x5 window off the strips -> 20 lines + scatter count, through an
    INDEPENDENT line evaluator; every nonce must match play_round exactly.
    Wilds appear when a strip stop brings King Tut into the window — no
    other floats exist to consume."""
    m = scarab_machine()
    wild_seen = 0
    for nonce in range(400):
        f = sq_rng.generate_floats(SEED, CLIENT, nonce, 0, 5)
        stops = [math.floor(f[i] * L) for i, L in
                 zip(range(5), (30, 30, 30, 30, 41))]
        grid = [[SCARAB_STRIPS[i][(stops[i] + r - 1) % len(SCARAB_STRIPS[i])]
                 for i in range(5)] for r in range(3)]
        wild_seen += sum(row.count(SCARAB_WILD) for row in grid)
        cents = 0
        for line in PAYLINES_20:
            tup = tuple(grid[line[i]][i] for i in range(5))
            cents += _independent_line_cents(tup, SCARAB_WILD)
        k = sum(row.count(SCARAB_SCATTER) for row in grid)
        cents += {2: 200, 3: 600, 4: 5000, 5: 50000}.get(k, 0)
        r = m.play_round(SEED, CLIENT, nonce)
        assert r["stops"] == stops, nonce
        assert r["stops"] == sq_rng.scarab_spin(SEED, CLIENT, nonce), nonce
        assert r["scatters"] == k, nonce
        assert math.isclose(r["base_win"], cents / 2000.0, abs_tol=1e-12), nonce
    assert wild_seen > 5   # wilds do land in the base game, from the reels


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
    """Scarab bonus spin j uses floats 5(j+1)..5(j+1)+4 (20-byte cursor
    strides) of the same nonce — "the incremental number is only utilised
    for bonus rounds"; each free spin is again exactly 5 floats through
    the published stop mapping, evaluated by the INDEPENDENT line rule
    (3x with the 5-wild exemption, wild doubling) plus tripled scatter
    pays, with the published 180-spin retrigger cap."""
    nonce = next(n for n in range(3000)
                 if scarab.play_round(SEED, CLIENT, n)["triggered"])
    r = scarab.play_round(SEED, CLIENT, nonce)
    assert r["bonus_spins"] >= scarab.free_spins
    unit = 100 * scarab.n_lines
    total = 0
    remaining, spin = scarab.free_spins, 0
    while remaining > 0 and spin < 180:
        f = sq_rng.generate_floats(SEED, CLIENT, nonce, 20 * (1 + spin), 5)
        stops = sq_rng.scarab_spin_stops(f)
        grid = [[SCARAB_STRIPS[i][(stops[i] + rr - 1)
                                  % len(SCARAB_STRIPS[i])]
                 for i in range(5)] for rr in range(3)]
        cents = sum(_independent_line_cents(
            tuple(grid[line[i]][i] for i in range(5)), SCARAB_WILD,
            bonus=True) for line in PAYLINES_20)
        k = sum(row.count(SCARAB_SCATTER) for row in grid)
        cents += 3 * {2: 200, 3: 600, 4: 5000, 5: 50000}.get(k, 0)
        total += cents
        if k >= 3:
            remaining += scarab.free_spins
        remaining -= 1
        spin += 1
        remaining = min(remaining, 180 - spin)     # published cap
    assert spin == r["bonus_spins"] <= 180
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
        free_spins=15, free_spin_multiplier=3, max_win=0.05,
        free_spin_cap=180, wild_substitution_double=True,
        wild5_multiplier_exempt=True)
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


def test_published_max_win_reachable(scarab, scarab_exact):
    """Round-5 item: the published 10,000x max win must be reachable.
    Under the published rules the ceiling is live: with the 3x multiplier
    a single free spin can pay hundreds of total bets, and a 180-spin
    bonus of maximal spins clears 10,000x by an order of magnitude — the
    cap binds with positive probability (every spin outcome has positive
    probability on fixed reels)."""
    unit = 100 * scarab.n_lines
    max_bonus_spin = float(scarab_exact["max_bonus_spin_cents"]) / unit
    max_base_spin = float(scarab_exact["max_spin_cents"]) / unit
    assert max_bonus_spin > 60.0            # one free spin, x total bet
    assert 180 * max_bonus_spin + max_base_spin > 10_000.0
    assert scarab.max_win == 10_000.0


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
    assert sim["n_triggered"] > 0 and sim["n_bonus_spins"] > 0


def test_simulate_within_3se_fixed_seed(scarab, scarab_exact):
    # deterministic seed -> deterministic z; 200k rounds catches a broken
    # payout path
    bulk = BulkRng(server_seed=SEED, client_seed=CLIENT, nonce_start=0)
    sim = scarab.simulate(200_000, bulk=bulk, progress=False)
    assert sim["within_3se"], (sim["rtp"], sim["analytic_rtp"], sim["z_score"])
    assert sim["n_triggered"] > 0 and sim["n_bonus_spins"] > 0
    # trigger rate near the exact p (SE of p-hat ~ 0.0005 at 200k rounds)
    p = float(scarab_exact["p_bonus_trigger"])
    assert abs(sim["trigger_rate"] - p) < 0.002
    # no bonus can exceed the published 180-spin cap; with the exact
    # P(N = 180) ~ a few percent, 200k rounds contain capped chains but
    # never longer ones
    assert sim["n_bonus_spins"] <= sim["n_triggered"] * 180


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
    assert cfg["floats_per_spin"] == 5


def test_scarab_config_declares_five_floats(scarab):
    cfg = scarab.analytic_summary()["config"]
    assert cfg["floats_per_spin"] == 5 == sq_rng.EVENT_COUNTS["scarab_spin"]
    assert cfg["max_win"] == 10_000.0
    assert cfg["reel_lengths"] == [30, 30, 30, 30, 41]


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
        # max_win must be positive
        SlotMachine("bad", S.SCARAB_SYMBOLS, SCARAB_STRIPS,
                    SCARAB_LINE_PAYS, SCARAB_WILD, SCARAB_SCATTER,
                    SCARAB_SCATTER_PAYS, "line", 15, 1, max_win=-1.0)
    with pytest.raises(ValueError):
        m = atkins_machine()
        m.simulate(0)
