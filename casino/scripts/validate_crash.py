#!/usr/bin/env python3
"""Validate the Crash engine against the published references.

1. Published-spec parity (references/stake/crash.md): the module's constants
   (terminating hash, block-584,500 salt, chain length, 1% edge, 1,000,000x
   cashout cap) and the verbatim crash-point formula are re-parsed from the
   reference document and asserted equal.

2. Payout-for-payout comparison: Crash has no discrete paytable — the
   published payout rule is continuous (cashout target w pays w iff the
   crash point >= w, with P(crash >= w) = 0.99/w and RTP = 0.99 at EVERY
   target).  We therefore compare, on a grid of targets, the exact
   float64-semantics analytic P(win)/RTP against the reference's closed
   forms; RTP must sit within the 32-bit quantization bound w/2^32 of 0.99.

3. Chain-mechanics check: a 10,001-hash chain is built and verified
   (terminating hash reached by re-hashing, per-game verification steps,
   streamed simulator bit-identical to scalar chain play).

3b. Commitment-ordering enforcement (the fairness guarantee itself): the
   reference binds the salt to "a future bitcoin block ... so players can
   be certain that we did not pick one in the house's favor" — terminating
   hash FIRST, salt from an EXTERNAL beacon SECOND.  The general rule is
   "no external commitment => not fair", and a beacon CLAIM is never taken
   at the operator's word: a structured ``salt_source``
   ({"beacon":"bitcoin","height":N} / {"beacon":"drand","round":R}) is
   validated structurally (64 hex chars; >= 8 leading zero nibbles for a
   claimed Bitcoin block hash — true at every height since genesis),
   requires a MANDATORY ``revealed_at`` strictly after the commitment and
   not in the future, and even then is only recorded as ``order:
   "external_commitment_claimed_unverified", fair_ordering: False``.
   ``fair_ordering: True`` exists ONLY after the VERIFIER calls
   ``verify_salt_against_beacon(resolved_value, resolved_time)`` with the
   named beacon's value and publication time resolved out-of-band — a
   byte-identical match published strictly after the commitment; any
   failure refutes the claim permanently.  Gates: a salt the operator's
   own process drew after the commitment (including the default two-phase
   simulator path) is recorded as ``order:
   "operator_drawn_after_commitment", fair_ordering: False``; the round-4
   salt-grinding exploit is reproduced dressed in beacon claims (Bitcoin
   dress refused structurally, drand dress refuted on resolution) and
   shown NOT certified; the round-5 SEED-grinding exploit (grind the
   secret seed against Bitcoin block 1's already-published hash, bind the
   genuine block hash) is reproduced and shown dead on every path;
   malformed beacon claims are rejected; STAKE_SALT (block 584,500, mined
   2019-07-21; case-insensitive, 0x-stripped) is refused as a hint for any
   newly generated chain; chains cannot be played before a salt is bound;
   a salt attested to predate the commitment is refused; a caller-supplied
   (pre-existing) salt warns and is marked ``fair_ordering: False``; the
   claim -> out-of-band-verify path (exercised with a clearly labeled
   SIMULATED resolution — this validator runs offline) grants
   ``fair_ordering: True`` only after the verify step; and replaying
   Stake's own published chain with an explicit STAKE_SALT still works.

4. Empirical bar: 10M+ provably-fair rounds per mechanism —
   (a) vectorized BulkRng stream (critic-verified rng core), and
   (b) Stake's ACTUAL salted hash-chain mechanism, streamed.
   At every target, empirical P(win) and RTP must land within 3 SE of the
   exact analytic values.

5. Wizard-of-Odds comparison (references/woo/crash.md): WoO analyzes
   SmartSoft's JetX (97% RTP, 3% edge, tick-based mechanism), NOT Stake's
   Crash.  A side-by-side table is printed as a documented comparison —
   the numbers intentionally do NOT match and are not a pass/fail target;
   only the shared shape (P = RTP/w, flat edge) is checked.

Prints a human-readable report plus a machine-readable JSON line prefixed
``CRASH_VALIDATION_JSON:``.  Exit code 0 iff every gate passes.

Usage:
    python scripts/validate_crash.py [--rounds N] [--chain-rounds N]
                                     [--targets w,w,...] [--skip-sim]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
import warnings
from pathlib import Path
from typing import Dict, List

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from spinquest_sim.games.crash import (  # noqa: E402
    EDGE_MULTIPLIER,
    HOUSE_EDGE,
    MAX_CASHOUT,
    STAKE_CHAIN_LENGTH,
    STAKE_SALT,
    STAKE_TERMINATING_HASH,
    TWO32,
    CommitmentOrderError,
    CommitmentOrderWarning,
    Crash,
    HashChain,
    analytic_table,
    crash_point_from_hash,
    build_hash_chain,
    crash_int_from_hash,
    crash_point_from_int,
    instant_bust_probability,
    is_external_commitment,
    next_chain_hash,
    simulate_chain_targets,
    simulate_targets,
    verify_game_hash,
)
from spinquest_sim.games import crash as crash_mod  # noqa: E402
from spinquest_sim.rng import BulkRng  # noqa: E402

STAKE_MD = _ROOT / "references" / "stake" / "crash.md"
WOO_MD = _ROOT / "references" / "woo" / "crash.md"

DEFAULT_TARGETS = [1.01, 1.5, 2.0, 5.0, 10.0, 100.0, 1000.0]
PAYTABLE_TARGETS = [
    1.01, 1.02, 1.1, 1.23, 1.5, 1.98, 2.0, 2.5, 3.0, 3.33, 5.0, 10.0,
    20.0, 33.33, 50.0, 100.0, 250.0, 1000.0, 10_000.0, 100_000.0, 1_000_000.0,
]
DEFAULT_ROUNDS = 10_000_000
DEFAULT_CHAIN_ROUNDS = 10_000_000

# Deterministic, reproducible campaign seeds.
SIM_SERVER_SEED = hashlib.sha256(b"spinquest crash validation v1").hexdigest()
SIM_CLIENT_SEED = "spinquest-crash"
SIM_CHAIN_SECRET = hashlib.sha256(b"spinquest crash chain v1").hexdigest()
# Fixed salt for the reproducible 10M chain campaign — NOT STAKE_SALT (the
# engine refuses that for new chains); using it emits CommitmentOrderWarning
# and marks the run fair_ordering=False, both asserted below.
SIM_CHAIN_SALT = hashlib.sha256(b"spinquest crash validation salt v1").hexdigest()


# ---------------------------------------------------------------------------
# Reference parsers
# ---------------------------------------------------------------------------

def parse_stake_reference(path: Path = STAKE_MD) -> Dict[str, object]:
    """Re-parse the published constants and formula from the reference doc."""
    text = path.read_text()
    hashes = re.findall(r"`([0-9a-f]{64})`", text)
    term = next(h for h in hashes if not h.startswith("0000000000"))
    salt = next(h for h in hashes if h.startswith("0000000000"))
    chain_len = int(
        re.search(r"chain of \*\*([\d,]+)\s*\n?\s*SHA256 hashes", text)
        .group(1).replace(",", "")
    )
    edge = float(re.search(r"House edge.*?\*\*([\d.]+)%\*\*", text).group(1)) / 100
    max_cash = float(
        re.search(r"Maximum cashout value.*?\*\*([\d,]+)[x×]\*\*", text)
        .group(1).replace(",", "")
    )
    formula_found = (
        "Math.max(1, (2 ** 32 / (int + 1)) * (1 - 0.01))" in text
        and "hmac.digest('hex').substr(0, 8)" in text
        and "createHmac('sha256', gameHash)" in text
        and "hmac.update(blockHash)" in text
    )
    return {
        "terminating_hash": term,
        "salt": salt,
        "chain_length": chain_len,
        "house_edge": edge,
        "max_cashout": max_cash,
        "formula_found": formula_found,
        "min_crash_is_1": "lowest\ncrashpoint of 1" in text
        or "lowest crashpoint of 1" in text.replace("\n", " "),
    }


def parse_woo_reference(path: Path = WOO_MD) -> Dict[str, object]:
    """JetX facts from the WoO reference (comparison only, not a target)."""
    text = path.read_text()
    rtp = float(re.search(r"Return \(RTP\): \*\*(\d+)%\*\*", text).group(1)) / 100
    edge = float(re.search(r"House edge: \*\*(\d+)%\*\*", text).group(1)) / 100
    pwin = re.search(r"P\(win\) = ([\d.]+) / w", text).group(1)
    example = re.search(
        r"goal 3x → P\(win\) = 0\.97/3 ≈ ([\d.]+)%", text
    )
    goal_range = re.search(r"\*\*([\d.]+)x to ([\d.]+)x\*\*", text)
    return {
        "game": "JetX (SmartSoft Gaming)",
        "rtp": rtp,
        "house_edge": edge,
        "p_win_formula": f"{pwin} / w",
        "p_win_numerator": float(pwin),
        "example_3x_pct": float(example.group(1)) if example else None,
        "goal_min": float(goal_range.group(1)) if goal_range else None,
        "goal_max": float(goal_range.group(2)) if goal_range else None,
    }


# ---------------------------------------------------------------------------
# Validation sections
# ---------------------------------------------------------------------------

def check_spec_parity() -> Dict[str, object]:
    ref = parse_stake_reference()
    checks = {
        "terminating_hash": ref["terminating_hash"] == STAKE_TERMINATING_HASH,
        "salt_block_584500": ref["salt"] == STAKE_SALT,
        "chain_length_10M": ref["chain_length"] == STAKE_CHAIN_LENGTH,
        "house_edge_1pct": ref["house_edge"] == HOUSE_EDGE,
        "max_cashout_1Mx": ref["max_cashout"] == MAX_CASHOUT,
        "verbatim_formula_present": bool(ref["formula_found"]),
        "edge_multiplier_is_1_minus_001": EDGE_MULTIPLIER == 1 - 0.01 == 0.99,
        "min_crash_1": crash_point_from_int(TWO32 - 1) == 1.0,
    }
    return {"reference": ref, "checks": checks, "pass": all(checks.values())}


def check_payout_table() -> Dict[str, object]:
    """The continuous 'paytable': exact vs published closed forms per target."""
    rows = analytic_table(PAYTABLE_TARGETS)
    worst_rtp_dev = 0.0
    worst_p_reldev = 0.0
    ok = True
    bust = instant_bust_probability()
    for r in rows:
        rtp_dev = abs(r["rtp"] - 0.99)
        p_reldev = abs(r["win_probability"] - r["win_probability_ideal"]) / r[
            "win_probability_ideal"
        ]
        worst_rtp_dev = max(worst_rtp_dev, rtp_dev)
        worst_p_reldev = max(worst_p_reldev, p_reldev)
        r["rtp_dev_from_099"] = rtp_dev
        r["within_quantization"] = rtp_dev <= r["rtp_quantization_bound"] + 1e-12
        ok = ok and r["within_quantization"]
    bust_ok = abs(bust - 0.01) < 1e-4
    return {
        "rows": rows,
        "worst_rtp_dev_from_099": worst_rtp_dev,
        "worst_p_rel_dev_from_ideal": worst_p_reldev,
        "instant_bust_probability": bust,
        "instant_bust_ok": bust_ok,
        "pass": ok and bust_ok,
    }


def check_chain_mechanics() -> Dict[str, object]:
    """Build and fully verify a 10,001-hash chain (10,000 playable games)."""
    seed = "validation-chain-secret"
    length = 10_001
    chain = build_hash_chain(seed, length)
    term = chain[-1]
    # terminating hash reachable from the chain's oldest hash in length-1 steps
    h = chain[0]
    for _ in range(length - 1):
        h = next_chain_hash(h)
    term_ok = h == term
    # spot verification steps for games 1, 100, 10,000
    steps_ok = all(
        verify_game_hash(chain[-1 - g], term, length) == g
        for g in (1, 100, length - 1)
    )
    # streamed simulator bit-identical to scalar HashChain play (all 10k
    # games), honest protocol: chain committed first, salt bound afterwards
    hc = HashChain(seed, length=length)
    hc.bind_salt(SIM_CHAIN_SALT, salt_source="validation fixture")
    scalar_ints = [
        crash_int_from_hash(hc.pop_hash()[1], hc.salt)
        for _ in range(length - 1)
    ]
    ints, term_stream = crash_mod._stream_chain_ints(
        seed, length - 1, SIM_CHAIN_SALT, progress=False
    )
    stream_ok = term_stream == term and ints.tolist() == scalar_ints
    return {
        "chain_length": length,
        "terminating_hash": term,
        "terminating_reachable": term_ok,
        "verification_steps_ok": steps_ok,
        "stream_bit_identical_to_scalar": stream_ok,
        "pass": term_ok and steps_ok and stream_ok,
    }


def check_commitment_ordering() -> Dict[str, object]:
    """Gate 3b: the commitment order the reference's guarantee rests on."""
    checks: Dict[str, bool] = {}

    # (1) STAKE_SALT (revealed 2019-07-21) refused for any NEW chain, at
    # every chain-generating entry point.
    def _raises_commitment_error(fn) -> bool:
        try:
            fn()
        except CommitmentOrderError:
            return True
        except Exception:
            return False
        return False

    checks["stake_salt_refused_at_hashchain_init"] = _raises_commitment_error(
        lambda: HashChain("grind-attempt", length=6, salt=STAKE_SALT)
    )
    checks["stake_salt_refused_at_bind_salt"] = _raises_commitment_error(
        lambda: HashChain("grind-attempt", length=6).bind_salt(STAKE_SALT)
    )
    checks["stake_salt_refused_in_chain_simulator"] = _raises_commitment_error(
        lambda: simulate_chain_targets(
            [2.0], 10, secret_seed="grind-attempt", salt=STAKE_SALT,
            progress=False,
        )
    )

    # (2) no play before a salt is bound (commitment must be publishable
    # while the salt does not yet exist).
    hc = HashChain("ordering-demo", length=64)
    commitment_first = len(hc.terminating_hash) == 64 and hc.salt is None
    try:
        hc.pop_hash()
        no_play = False
    except RuntimeError:
        no_play = True
    checks["terminating_hash_available_before_salt"] = commitment_first
    checks["play_refused_before_salt_bound"] = no_play

    # (3) a salt attested to predate the commitment is refused.
    stale_salt = hashlib.sha256(b"a block mined years ago").hexdigest()
    checks["salt_predating_commitment_refused"] = _raises_commitment_error(
        lambda: hc.bind_salt(stale_salt, revealed_at=hc.committed_at - 86400.0)
    )

    # (3.5) STAKE_SALT disguises (uppercase, 0x prefix) are refused too —
    # the refusal is a normalized hint, not a single equality test.
    checks["stake_salt_uppercase_refused"] = _raises_commitment_error(
        lambda: HashChain("grind-attempt", length=6).bind_salt(STAKE_SALT.upper())
    )
    checks["stake_salt_0x_prefixed_refused"] = _raises_commitment_error(
        lambda: HashChain("grind-attempt", length=6).bind_salt("0x" + STAKE_SALT)
    )

    # (4) THE GENERAL RULE — no external commitment => not fair — and a
    # beacon CLAIM is never taken at the operator's word.
    # (4a) claim -> out-of-band verify protocol.  The resolution below is
    # SIMULATED (this validator runs offline and resolves no real beacon):
    # it exercises the gate's mechanics and the stored record is labeled
    # as such — a drand round can genuinely land milliseconds after a
    # commitment (one round every few seconds), so the timing here is
    # internally consistent, but the round number and value are synthetic.
    demo_drand_value = hashlib.sha256(
        b"simulated drand resolution for gate demo"
    ).hexdigest()
    time.sleep(0.005)  # the 'beacon' publishes strictly after the commitment
    demo_reveal_time = time.time()
    hc.bind_salt(
        demo_drand_value,
        salt_source={"beacon": "drand", "round": 3_366_570},
        revealed_at=demo_reveal_time,
    )
    claim_rec = hc.commitment
    checks["beacon_claim_alone_not_certified_fair"] = (
        claim_rec["fair_ordering"] is False
        and claim_rec["fair_ordering_claimed"] is True
        and claim_rec["order"] == "external_commitment_claimed_unverified"
        and "verify_salt_against_beacon" in str(claim_rec.get("note", ""))
    )
    rec = hc.verify_salt_against_beacon(demo_drand_value, demo_reveal_time)
    checks["verify_gate_grants_fair_after_matching_resolution"] = (
        rec["fair_ordering"] is True
        and rec["order"] == "terminating_hash_first"
        and rec["beacon_verification"]["verified"] is True
        and rec["salt_bound_at_unix"] >= rec["terminating_hash_committed_at_unix"]
    )
    rec = dict(rec)
    rec["demo_note"] = (
        "SIMULATED out-of-band resolution (offline mechanism demo): the "
        "drand round number and value above are synthetic; a real verifier "
        "must resolve the named round from the drand network itself — see "
        "stake_2019_reference_event for the real-world exemplar"
    )
    checks["is_external_commitment_recognizes_beacons"] = (
        is_external_commitment({"beacon": "bitcoin", "height": 900_000})
        and is_external_commitment({"beacon": "drand", "round": 3_366_570})
    )
    # (4a-neg) the claim path's own guards.
    fake_block_salt = "0" * 10 + hashlib.sha256(b"demo block").hexdigest()[10:]
    btc_source = {"beacon": "bitcoin", "height": 1_000_000}
    checks["beacon_claim_requires_revealed_at"] = _raises_commitment_error(
        lambda: HashChain("guard-demo", length=6).bind_salt(
            fake_block_salt, salt_source=btc_source
        )
    )
    checks["future_dated_revealed_at_refused"] = _raises_commitment_error(
        lambda: HashChain("guard-demo", length=6).bind_salt(
            fake_block_salt, salt_source=btc_source,
            revealed_at=time.time() + 3600.0,
        )
    )

    def _impossible_block_hash():
        h = HashChain("guard-demo", length=6)
        time.sleep(0.002)
        h.bind_salt(
            hashlib.sha256(b"salt with no leading zeros").hexdigest(),
            salt_source=btc_source, revealed_at=time.time(),
        )

    checks["bitcoin_claim_without_8_leading_zeros_refused"] = (
        _raises_commitment_error(_impossible_block_hash)
    )
    # sanity anchor: the real block-584,500 salt easily clears the >=8
    # leading-zero structural floor (it has 18).
    checks["stake_salt_clears_bitcoin_structural_floor"] = (
        len(STAKE_SALT) - len(STAKE_SALT.lstrip("0")) >= 8
    )

    def _mismatched_resolution():
        h = HashChain("guard-demo-2", length=6)
        time.sleep(0.002)
        h.bind_salt(
            hashlib.sha256(b"operator's claimed drand value").hexdigest(),
            salt_source={"beacon": "drand", "round": 3_366_570},
            revealed_at=time.time(),
        )
        try:
            h.verify_salt_against_beacon(
                hashlib.sha256(b"the actually published value").hexdigest(),
                time.time(),
            )
        finally:
            _mismatched_resolution.order = h.commitment["order"]  # type: ignore

    checks["mismatched_resolution_refutes_claim"] = (
        _raises_commitment_error(_mismatched_resolution)
        and getattr(_mismatched_resolution, "order", None)
        == "external_commitment_refuted"
    )
    # (4b) the SAME bind with only a free-text source (timestamps identical,
    # revealed_at attested) is NOT certified — timestamp order is necessary
    # but never sufficient.
    hc_text = HashChain("ordering-demo-text", length=64)
    hc_text.bind_salt(
        hashlib.sha256(b"another demo salt").hexdigest(),
        salt_source="free-text claim, not verifier-resolvable",
        revealed_at=hc_text.committed_at + 1.0,
    )
    trec = hc_text.commitment
    checks["textual_source_not_certified_fair"] = (
        trec["fair_ordering"] is False
        and trec["order"] == "operator_drawn_after_commitment"
        and "external commitment" in str(trec.get("note", ""))
    )
    # (4c) malformed beacon claims are not external commitments.
    checks["malformed_beacon_claims_rejected"] = not any(
        is_external_commitment(bad)
        for bad in (
            None, "bitcoin height 1000000",
            {"beacon": "urandom", "height": 5},
            {"beacon": "bitcoin"}, {"beacon": "bitcoin", "round": 5},
            {"beacon": "bitcoin", "height": 0},
            {"beacon": "bitcoin", "height": True},
            {"beacon": "drand", "height": 5},
        )
    )

    # (5) caller-supplied (pre-existing) salt warns and is marked unfair.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        res = simulate_chain_targets(
            [2.0], 200, secret_seed="warn-demo", salt=SIM_CHAIN_SALT,
            progress=False,
        )
    checks["preexisting_salt_warns"] = any(
        issubclass(w.category, CommitmentOrderWarning) for w in caught
    )
    checks["preexisting_salt_marked_unfair"] = (
        res["verification"]["commitment"]["fair_ordering"] is False
    )

    # (6) the two-phase simulator path SELF-DRAWS its salt (secrets.token_hex
    # in the operator's own process): it must be recorded honestly as
    # operator_drawn_after_commitment / fair_ordering False, with the
    # one-sentence reproducible-simulation note — and it must refuse to dress
    # a self-drawn salt in an external-beacon claim.
    two_phase = simulate_chain_targets(
        [2.0], 20_000, secret_seed="two-phase-demo", progress=False
    )
    hrec = two_phase["verification"]["commitment"]
    checks["self_drawn_salt_marked_operator_drawn_unfair"] = (
        hrec["fair_ordering"] is False
        and hrec["order"] == "operator_drawn_after_commitment"
        and "external commitment" in str(hrec.get("note", ""))
        and hrec["terminating_hash_committed_at_unix"]
        <= hrec["salt_bound_at_unix"]
        and hrec["salt"] != STAKE_SALT
    )
    checks["self_drawn_salt_cannot_claim_beacon"] = _raises_commitment_error(
        lambda: simulate_chain_targets(
            [2.0], 10, secret_seed="s",
            salt_source={"beacon": "bitcoin", "height": 1_000_000},
            progress=False,
        )
    )

    # (6b) the round-4 exploit itself: grind candidate salts against a
    # committed chain until the first 3 rounds all bust below 2x, bind the
    # winner — the rig works, but the engine refuses to certify it fair,
    # no matter how the ground salt's salt_source is dressed (the round-5
    # critic's swap: replace the confession string with a beacon dict).
    grind_secret = "validator-grind-target"
    grind_len = 8
    hc_grind = HashChain(grind_secret, length=grind_len)
    grind_chain = build_hash_chain(grind_secret, grind_len)
    first_three = grind_chain[-2:-5:-1]
    rigged, tries = None, 0
    while rigged is None:
        cand = hashlib.sha256(f"validator grind {tries}".encode()).hexdigest()
        tries += 1
        if all(crash_point_from_hash(h, cand) < 2.0 for h in first_three):
            rigged = cand
    # bitcoin dress: a ground SHA-256 salt has ~0 leading zero nibbles —
    # arithmetically impossible for any block, refused at bind.
    def _btc_dress():
        h = HashChain(grind_secret, length=grind_len)
        time.sleep(0.002)
        h.bind_salt(rigged, salt_source=btc_source, revealed_at=time.time())

    checks["ground_salt_bitcoin_dress_refused"] = _raises_commitment_error(
        _btc_dress
    )
    # drand dress: binds only as an UNVERIFIED claim (fair stays False);
    # out-of-band resolution returns a different value -> refuted.
    hc_drand = HashChain(grind_secret, length=grind_len)
    time.sleep(0.002)
    hc_drand.bind_salt(
        rigged, salt_source={"beacon": "drand", "round": 3_366_570},
        revealed_at=time.time(),
    )
    drand_dress_unverified = (
        hc_drand.fair_ordering is False
        and hc_drand.commitment["order"]
        == "external_commitment_claimed_unverified"
    )
    drand_dress_refuted = _raises_commitment_error(
        lambda: hc_drand.verify_salt_against_beacon(
            hashlib.sha256(b"what round 3366570 really published").hexdigest(),
            time.time(),
        )
    ) and hc_drand.commitment["order"] == "external_commitment_refuted"
    checks["ground_salt_drand_dress_refuted_on_resolution"] = (
        drand_dress_unverified and drand_dress_refuted
    )
    # confession-string source: recorded as operator-drawn, not certified.
    hc_grind.bind_salt(rigged, salt_source=f"ground in {tries} candidates")
    grind_points = hc_grind.crash_points(3)
    checks["ground_salt_rig_not_certified_fair"] = (
        all(p < 2.0 for p in grind_points)          # the rig itself worked...
        and hc_grind.fair_ordering is False         # ...but is not certified
        and hc_grind.commitment["order"] == "operator_drawn_after_commitment"
    )

    # (6c) the round-5 exploit: grind the SECRET SEED against an
    # ALREADY-PUBLISHED beacon value (Bitcoin block 1's hash, mined
    # 2009-01-09), so the bound salt genuinely IS the named beacon's value
    # and a verifier's value lookup matches byte-for-byte.  Every
    # certification path must be dead.
    block1 = "00000000839a8e6886ab5951d76f411475428afc90947ee320161bbf18eb6048"
    block1_time = 1_231_469_665.0  # 2009-01-09 UTC
    seed_tries, ground_seed = 0, None
    while ground_seed is None:
        cand = f"validator seed grind {seed_tries}"
        cand_chain = build_hash_chain(cand, 5)
        if all(
            crash_point_from_hash(h, block1) < 2.0
            for h in cand_chain[-2:-5:-1]
        ):
            ground_seed = cand
        seed_tries += 1
    hc_seed = HashChain(ground_seed, length=5)
    block1_source = {"beacon": "bitcoin", "height": 1}
    checks["seed_grind_claim_without_revealed_at_refused"] = (
        _raises_commitment_error(
            lambda: hc_seed.bind_salt(block1, salt_source=block1_source)
        )
    )
    checks["seed_grind_honest_reveal_time_refused"] = _raises_commitment_error(
        lambda: hc_seed.bind_salt(
            block1, salt_source=block1_source, revealed_at=block1_time
        )
    )
    time.sleep(0.002)
    hc_seed.bind_salt(
        block1, salt_source=block1_source, revealed_at=time.time()  # a LIE
    )
    seed_points = hc_seed.crash_points(3)
    checks["seed_grind_lying_reveal_not_certified"] = (
        all(p < 2.0 for p in seed_points)           # the rig itself worked...
        and hc_seed.fair_ordering is False          # ...but is only a claim
        and hc_seed.commitment["order"]
        == "external_commitment_claimed_unverified"
    )
    checks["seed_grind_refuted_by_out_of_band_resolution"] = (
        _raises_commitment_error(
            lambda: hc_seed.verify_salt_against_beacon(block1, block1_time)
        )
        and hc_seed.fair_ordering is False
        and hc_seed.commitment["order"] == "external_commitment_refuted"
    )
    checks["refuted_claim_cannot_be_revived"] = _raises_commitment_error(
        lambda: hc_seed.verify_salt_against_beacon(block1, time.time())
    ) and hc_seed.fair_ordering is False

    # (7) the one legitimate STAKE_SALT use — replay verification of a hash
    # claimed to belong to Stake's published 2019 chain — still works.
    try:
        pt = crash_point_from_hash(
            hashlib.sha256(b"claimed stake hash").hexdigest(), STAKE_SALT
        )
        checks["stake_replay_verification_still_works"] = pt >= 1.0
    except Exception:
        checks["stake_replay_verification_still_works"] = False

    return {
        "checks": checks,
        # The real-world exemplar of a fair record (all facts from
        # references/stake/crash.md): commitment published 2019-07-08,
        # salt = Bitcoin block 584,500 named IN ADVANCE and mined
        # 2019-07-21 — 13 days later — with 18 leading zero nibbles.
        "stake_2019_reference_event": {
            "terminating_hash": STAKE_TERMINATING_HASH,
            "terminating_hash_published": "2019-07-08 (bitcointalk post)",
            "salt": STAKE_SALT,
            "salt_source": {"beacon": "bitcoin", "height": 584_500},
            "salt_revealed": "2019-07-21 (block 584,500 mined)",
            "commit_to_reveal_gap_days": 13,
            "salt_leading_zero_nibbles":
                len(STAKE_SALT) - len(STAKE_SALT.lstrip("0")),
        },
        "beacon_claim_record_unverified": claim_rec,
        # gate-mechanics demo with a SIMULATED resolution (see demo_note)
        "beacon_verify_demo_record": rec,
        "two_phase_commitment_record": hrec,
        "grind_demo": {
            "exploit": "round-4 salt grind (ground salt, chain fixed)",
            "candidates_ground": tries,
            "rigged_first_three_crash_points": grind_points,
            "bitcoin_dress_verdict": "refused at bind (0 leading zero "
            "nibbles: impossible for any block hash)",
            "drand_dress_verdict": hc_drand.commitment["order"],
            "engine_verdict_order": hc_grind.commitment["order"],
            "engine_verdict_fair_ordering": hc_grind.fair_ordering,
        },
        "seed_grind_demo": {
            "exploit": "round-5 seed grind vs already-published beacon "
            "value (Bitcoin block 1's hash, mined 2009-01-09)",
            "seeds_ground": seed_tries,
            "rigged_first_three_crash_points": seed_points,
            "no_revealed_at": "refused at bind (mandatory)",
            "honest_revealed_at_2009": "refused at bind (predates commit)",
            "lying_revealed_at": "binds as unverified claim only, "
            "fair_ordering False",
            "out_of_band_resolution": "refuted (block 1 published before "
            "the commitment)",
            "engine_verdict_order": hc_seed.commitment["order"],
            "engine_verdict_fair_ordering": hc_seed.fair_ordering,
        },
        "pass": all(checks.values()),
    }


def _sim_rows(res: Dict[str, object]) -> List[Dict[str, object]]:
    return [
        {
            "target": r["config"]["target"],
            "n_rounds": r["n_rounds"],
            "wins": r["wins"],
            "win_rate": r["win_rate"],
            "analytic_win_probability": r["analytic_win_probability"],
            "rtp": r["rtp"],
            "analytic_rtp": r["analytic_rtp"],
            "se_rtp": r["se_rtp"],
            "z_score": r["z_score"],
            "within_3se": r["within_3se"],
            "std_per_unit": r["std_per_unit"],
            "analytic_std_per_unit": r["analytic_std_per_unit"],
        }
        for r in res["targets"]
    ]


def _print_sim(label: str, res: Dict[str, object]) -> None:
    for r in res["targets"]:
        w = r["config"]["target"]
        print(
            f"[sim:{label}] w={w:<8g} p={r['win_rate']:.8f} "
            f"(exact {r['analytic_win_probability']:.8f}) "
            f"rtp={r['rtp']:.6f} (exact {r['analytic_rtp']:.6f}, "
            f"se={r['se_rtp']:.6f}, z={r['z_score']:+.3f}) "
            f"{'PASS' if r['within_3se'] else 'FAIL'}",
            flush=True,
        )
    print(
        f"[sim:{label}] {res['n_rounds']:,} rounds in {res['elapsed_s']:.1f}s "
        f"({res['rounds_per_sec']:,.0f} rounds/s) -> "
        f"{'PASS' if res['pass'] else 'FAIL'}",
        flush=True,
    )


def run_empirical_bulk(targets: List[float], n_rounds: int) -> Dict[str, object]:
    bulk = BulkRng(
        server_seed=SIM_SERVER_SEED, client_seed=SIM_CLIENT_SEED, nonce_start=0
    )
    print(
        f"[sim:bulk] {n_rounds:,} provably-fair BulkRng rounds, "
        f"{len(targets)} targets ...",
        flush=True,
    )
    res = simulate_targets(targets, n_rounds, bulk=bulk)
    _print_sim("bulk", res)
    return {
        "mechanism": "seed_pair_bulk",
        "n_rounds": n_rounds,
        "rounds_per_sec": res["rounds_per_sec"],
        "elapsed_s": res["elapsed_s"],
        "targets": _sim_rows(res),
        "verification": res["verification"],
        "pass": res["pass"],
    }


def run_empirical_chain(targets: List[float], n_rounds: int) -> Dict[str, object]:
    print(
        f"[sim:chain] {n_rounds:,} rounds of the ACTUAL salted hash-chain "
        f"mechanism (sequential SHA-256 walk + HMAC) ...",
        flush=True,
    )
    print(
        "[sim:chain] reproducible mode: fixed validation salt (never "
        "STAKE_SALT — the engine refuses that for new chains); the engine "
        "warns and records fair_ordering=False, asserted below.",
        flush=True,
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        res = simulate_chain_targets(
            targets, n_rounds, secret_seed=SIM_CHAIN_SECRET,
            salt=SIM_CHAIN_SALT,
        )
    warned = any(issubclass(w.category, CommitmentOrderWarning) for w in caught)
    commitment = res["verification"]["commitment"]
    guard_ok = warned and commitment["fair_ordering"] is False
    print(
        f"[sim:chain] CommitmentOrderWarning emitted={warned}, "
        f"commitment order recorded as '{commitment['order']}' "
        f"(fair_ordering={commitment['fair_ordering']}) -> "
        f"{'PASS' if guard_ok else 'FAIL'}",
        flush=True,
    )
    _print_sim("chain", res)
    return {
        "mechanism": "hash_chain",
        "n_rounds": n_rounds,
        "rounds_per_sec": res["rounds_per_sec"],
        "elapsed_s": res["elapsed_s"],
        "targets": _sim_rows(res),
        "verification": res["verification"],
        "reproducible_mode_guard_ok": guard_ok,
        "pass": bool(res["pass"] and guard_ok),
    }


def check_woo_comparison(targets: List[float]) -> Dict[str, object]:
    woo = parse_woo_reference()
    # Shape check only: WoO's published P(win) = 0.97/w with his example.
    shape_ok = (
        abs(woo["p_win_numerator"] - woo["rtp"]) < 1e-12
        and abs(woo["rtp"] - (1 - woo["house_edge"])) < 1e-12
    )
    example_ok = (
        woo["example_3x_pct"] is None
        or abs(100 * woo["rtp"] / 3 - woo["example_3x_pct"]) < 0.005
    )
    rows = []
    for w in targets:
        game = Crash(w)
        p_jetx = woo["rtp"] / w if w >= (woo["goal_min"] or 1.01) else None
        rows.append(
            {
                "target": w,
                "stake_p_win": game.win_probability,
                "stake_rtp": game.rtp,
                "stake_std": game.std_per_unit,
                "jetx_p_win": p_jetx,
                "jetx_rtp": woo["rtp"] if p_jetx is not None else None,
                "jetx_std": math.sqrt(woo["rtp"] * w - woo["rtp"] ** 2)
                if p_jetx is not None
                else None,
            }
        )
    return {
        "woo_reference": woo,
        "comparison_rows": rows,
        "shape_ok": shape_ok,
        "example_ok": example_ok,
        # DOCUMENTED comparison, not a numeric target: pass = parse + shape.
        "pass": shape_ok and example_ok,
    }


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    ap.add_argument("--chain-rounds", type=int, default=DEFAULT_CHAIN_ROUNDS)
    ap.add_argument(
        "--targets", type=str,
        default=",".join(str(w) for w in DEFAULT_TARGETS),
    )
    ap.add_argument("--skip-sim", action="store_true")
    args = ap.parse_args(argv)
    targets = [float(w) for w in args.targets.split(",") if w]

    print("=" * 72)
    print("CRASH VALIDATION — Stake hash-chain math + WoO comparison + empirical")
    print("=" * 72)

    spec = check_spec_parity()
    for name, ok in spec["checks"].items():
        print(f"[spec]  {name}: {'PASS' if ok else 'FAIL'}")
    print(f"[spec]  -> {'PASS' if spec['pass'] else 'FAIL'}")

    table = check_payout_table()
    print(
        "[table] target      P(win) exact    0.99/w          RTP exact   "
        "|dev|      bound"
    )
    for r in table["rows"]:
        print(
            f"[table] {r['target']:<11g} {r['win_probability']:<15.10f} "
            f"{r['win_probability_ideal']:<15.10f} {r['rtp']:<11.8f} "
            f"{r['rtp_dev_from_099']:<10.2e} {r['rtp_quantization_bound']:.2e}"
            f" {'PASS' if r['within_quantization'] else 'FAIL'}"
        )
    print(
        f"[table] worst |RTP - 0.99| = {table['worst_rtp_dev_from_099']:.3e} "
        f"(all within the 32-bit quantization bound w/2^32); "
        f"worst rel |P - 0.99/w| = {table['worst_p_rel_dev_from_ideal']:.3e}"
    )
    print(
        f"[table] instant-bust P(crash=1) = "
        f"{table['instant_bust_probability']:.8f} (published ~1%) -> "
        f"{'PASS' if table['pass'] else 'FAIL'}"
    )

    chain = check_chain_mechanics()
    print(
        f"[chain] 10,001-hash chain: terminating reachable="
        f"{chain['terminating_reachable']}, per-game verification steps ok="
        f"{chain['verification_steps_ok']}, streamed simulator bit-identical "
        f"to scalar play={chain['stream_bit_identical_to_scalar']} -> "
        f"{'PASS' if chain['pass'] else 'FAIL'}"
    )

    ordering = check_commitment_ordering()
    for name, ok in ordering["checks"].items():
        print(f"[order] {name}: {'PASS' if ok else 'FAIL'}")
    sref = ordering["stake_2019_reference_event"]
    print(
        f"[order] real-world exemplar (reference): commitment published "
        f"{sref['terminating_hash_published']}, salt = bitcoin block "
        f"584,500 named in advance, mined {sref['salt_revealed']} "
        f"({sref['commit_to_reveal_gap_days']} days later, "
        f"{sref['salt_leading_zero_nibbles']} leading zero nibbles)"
    )
    crec = ordering["beacon_claim_record_unverified"]
    print(
        f"[order] beacon-claim demo: salt {str(crec['salt'])[:16]}... "
        f"claimed as {crec['salt_source']} -> order='{crec['order']}', "
        f"fair_ordering={crec['fair_ordering']} (a claim certifies nothing)"
    )
    brec = ordering["beacon_verify_demo_record"]
    print(
        f"[order] verify-gate demo (SIMULATED out-of-band resolution): "
        f"matching value + post-commit publication time -> "
        f"order='{brec['order']}', fair_ordering={brec['fair_ordering']}"
    )
    hrec = ordering["two_phase_commitment_record"]
    print(
        f"[order] two-phase self-drawn demo: salt {str(hrec['salt'])[:16]}... "
        f"drawn by the operator's own secrets.token_hex -> honestly recorded "
        f"as order='{hrec['order']}', fair_ordering={hrec['fair_ordering']}"
    )
    grind = ordering["grind_demo"]
    print(
        f"[order] round-4 exploit replay: ground {grind['candidates_ground']} "
        f"candidate salts to rig first 3 rounds "
        f"{['%.2f' % p for p in grind['rigged_first_three_crash_points']]} "
        f"(all < 2x) -> bitcoin dress refused (impossible block hash), "
        f"drand dress '{grind['drand_dress_verdict']}', confession source "
        f"'{grind['engine_verdict_order']}', fair_ordering="
        f"{grind['engine_verdict_fair_ordering']} (rig NOT certified)"
    )
    sgrind = ordering["seed_grind_demo"]
    print(
        f"[order] round-5 exploit replay: ground {sgrind['seeds_ground']} "
        f"candidate SEEDS vs bitcoin block 1's published hash, first 3 "
        f"rounds "
        f"{['%.2f' % p for p in sgrind['rigged_first_three_crash_points']]} "
        f"(all < 2x) -> no revealed_at/honest 2009 reveal both refused at "
        f"bind; lying reveal binds as unverified claim (fair_ordering "
        f"False); out-of-band resolution refutes -> final verdict order="
        f"'{sgrind['engine_verdict_order']}', fair_ordering="
        f"{sgrind['engine_verdict_fair_ordering']} -> "
        f"{'PASS' if ordering['pass'] else 'FAIL'}"
    )

    woo = check_woo_comparison(targets)
    print(
        "[woo]   COMPARISON ONLY (documented, not a target): WoO analyzes "
        "SmartSoft's JetX — 97% RTP / 3% edge, tick-based with 3% instant "
        "runway crash — vs Stake Crash 99% RTP / 1% edge, pre-committed "
        "salted hash chain."
    )
    print("[woo]   target    Stake P(win)  Stake RTP   JetX P(win)   JetX RTP")
    for r in woo["comparison_rows"]:
        jp = f"{r['jetx_p_win']:.8f}" if r["jetx_p_win"] is not None else "n/a"
        jr = f"{r['jetx_rtp']:.2f}" if r["jetx_rtp"] is not None else "n/a"
        print(
            f"[woo]   {r['target']:<9g} {r['stake_p_win']:<13.8f} "
            f"{r['stake_rtp']:<11.6f} {jp:<13} {jr}"
        )
    print(
        f"[woo]   shared shape P = RTP/w and flat edge: "
        f"{'PASS' if woo['pass'] else 'FAIL'} (numeric gap ~2pp is the "
        f"different published game, as expected)"
    )

    if args.skip_sim:
        bulk_sim = {"targets": [], "pass": True, "skipped": True}
        chain_sim = {"targets": [], "pass": True, "skipped": True}
        print("[sim]   skipped (--skip-sim)")
    else:
        bulk_sim = run_empirical_bulk(targets, args.rounds)
        chain_sim = run_empirical_chain(targets, args.chain_rounds)

    overall = bool(
        spec["pass"] and table["pass"] and chain["pass"] and ordering["pass"]
        and woo["pass"] and bulk_sim["pass"] and chain_sim["pass"]
    )
    summary = {
        "game": "crash",
        "overall_pass": overall,
        "spec_parity": {"checks": spec["checks"], "pass": spec["pass"]},
        "commitment_ordering": ordering,
        "payout_table": {
            "worst_rtp_dev_from_099": table["worst_rtp_dev_from_099"],
            "worst_p_rel_dev_from_ideal": table["worst_p_rel_dev_from_ideal"],
            "instant_bust_probability": table["instant_bust_probability"],
            "n_targets": len(table["rows"]),
            "pass": table["pass"],
        },
        "chain_mechanics": chain,
        "woo_comparison": {
            "woo_reference": woo["woo_reference"],
            "shape_ok": woo["shape_ok"],
            "pass": woo["pass"],
        },
        "empirical_bulk": bulk_sim,
        "empirical_chain": chain_sim,
        "sim_seeds": {
            "server_seed": SIM_SERVER_SEED,
            "client_seed": SIM_CLIENT_SEED,
            "chain_secret_seed": SIM_CHAIN_SECRET,
            "chain_salt": SIM_CHAIN_SALT,
        },
    }
    print("CRASH_VALIDATION_JSON: " + json.dumps(summary, default=float))
    print(f"OVERALL: {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
