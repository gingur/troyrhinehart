"""Stake-style Crash (salted hash-chain, published 1% house edge).

Math (references/stake/crash.md — Stake's own seeding-event thread, verbatim):

    const gameHash = hashChain.pop()
    const hmac = createHmac('sha256', gameHash);
    hmac.update(blockHash);
    const hex = hmac.digest('hex').substr(0, 8);
    const int = parseInt(hex, 16);
    const crashpoint = Math.max(1, (2 ** 32 / (int + 1)) * (1 - 0.01))

so with ``int`` uniform on [0, 2^32 - 1]:

    P(crash point >= w) = 0.99 / w        (for 1 < w <= raw max)
    RTP at any cashout target w = w * P   = 0.99  ->  1% house edge
    P(instant bust, crash point == 1)     ~ 1%

This module implements that formula byte-for-byte (the ``(1 - 0.01)`` literal
is kept verbatim; it equals the float64 ``0.99`` exactly), plus the salted
hash-chain provable-fairness mechanism itself: a pre-committed chain of
SHA-256 hashes (each hash = SHA-256 of the *hex representation* of the
previous one, terminating hash published in advance) is consumed in reverse,
and each game hash is the HMAC-SHA256 *key* while the public salt (Bitcoin
block 584,500's hash for Stake's real chain) is the HMAC *message*.

Unlike Stake's seed-pair games, Crash is multiplayer and does NOT use the
server-seed/client-seed/nonce stream.  Two provably-fair paths are provided:

* **Chain path** (Stake's actual Crash mechanism): :class:`HashChain`,
  :func:`crash_point_from_hash`, :meth:`Crash.play_round`, and the streaming
  chain simulator :meth:`Crash.simulate_chain` / :func:`simulate_chain_targets`.
* **Seed-pair path** (the critic-verified :mod:`spinquest_sim.rng` stream):
  the published float is exactly ``k / 2^32`` for a uniform 32-bit ``k``, so
  ``int(float * 2^32)`` recovers a uniform ``int`` bit-exactly and the same
  published crash formula applies.  :meth:`Crash.play_round_seedpair` (scalar)
  and :meth:`Crash.simulate` (vectorized :class:`BulkRng`) use this; it is a
  single-player provably-fair adaptation with the *identical* crash-point
  distribution (both mechanisms feed the same formula a uniform 32-bit int).

**Commitment ordering** (the heart of the fairness guarantee): the reference
says Stake chose "a future bitcoin block as a client seed so players can be
certain that we did not pick one in the house's favor" — i.e. the terminating
hash is published FIRST, and only then is the salt fixed, by a source the
operator cannot control.  If the salt is known while the chain is being
generated — or if the operator may draw/grind the salt itself after the
commitment (game hashes are salt-independent once committed, so a free salt
is grindable at one HMAC per candidate per round) — the first rounds of a
fully verifiable chain can be rigged to bust early.  Timestamp order is
therefore necessary but nowhere near sufficient, and this module applies the
general rule **no external commitment => not fair** — and a beacon CLAIM is
never taken at the operator's word: it is validated structurally, its reveal
time is a mandatory attestation, and the certifying boolean is gated behind
an explicit out-of-band verification step performed by the VERIFIER:

* ``fair_ordering: True`` requires ALL of:

  1. a structured ``salt_source`` naming a recognized public randomness
     beacon and index — ``{"beacon": "bitcoin", "height": N}`` or
     ``{"beacon": "drand", "round": R}`` (:data:`EXTERNAL_BEACONS` /
     :func:`is_external_commitment`) — bound via
     :meth:`HashChain.bind_salt` only after the terminating hash exists;
  2. a structurally possible salt for that beacon: 64 hex characters, and
     for ``bitcoin`` at least :data:`BITCOIN_MIN_LEADING_ZEROS` (= 8)
     leading zero nibbles — the difficulty-1 proof-of-work floor satisfied
     by every block ever mined (genesis has 10, block 1 has 8,
     ``STAKE_SALT`` — block 584,500 — has 18), so a ground SHA-256 salt
     dressed as a block hash is refused as arithmetically impossible;
  3. a MANDATORY ``revealed_at`` attestation strictly AFTER
     :attr:`HashChain.committed_at` and not in the future: an
     already-published beacon value honestly attested (e.g. Bitcoin
     block 1, mined 2009-01-09) is refused at bind time — the named index
     must be one whose value did not yet exist at the commitment;
  4. an explicit :meth:`HashChain.verify_salt_against_beacon` call in
     which the verifier supplies the beacon's published value and
     publication time resolved OUT-OF-BAND (never by the operator's
     process): the resolved value must equal the bound salt byte-for-byte
     and the resolved publication time must strictly postdate the
     commitment.  Until then the record says ``order:
     "external_commitment_claimed_unverified", fair_ordering: False``
     (with ``fair_ordering_claimed: True``); a failed verification marks
     the claim ``order: "external_commitment_refuted"`` permanently.

  Together these kill the seed-grinding rig (grind the SECRET SEED against
  an already-published beacon value, then bind the genuine beacon value):
  binding without ``revealed_at`` raises, attesting the true (past) reveal
  time raises, and lying about the reveal time still yields
  ``fair_ordering: False`` — when any verifier resolves the named index,
  its genuine publication time (before the commitment) refutes the claim.
* A salt the operator's own process drew after the commitment (including
  the default two-phase path of :func:`simulate_chain_targets`, which uses
  ``secrets.token_hex``) is recorded honestly as
  ``order: "operator_drawn_after_commitment", fair_ordering: False`` — a
  reproducible-simulation convenience, not the published guarantee.
* A caller-supplied salt that provably existed before the chain was
  generated warns (:class:`CommitmentOrderWarning`) and is recorded as
  ``order: "salt_preexisting_reproducible_mode", fair_ordering: False``.
* ``STAKE_SALT`` (Bitcoin block 584,500, mined 2019-07-21, matched
  case-insensitively and with any ``0x`` prefix stripped) is additionally
  refused outright for any newly generated chain — a special-cased hint,
  not the mechanism; it is accepted only for replaying/verifying Stake's
  own published 2019 chain.  A salt attested (``revealed_at``) to predate
  the commitment also raises.

The verification dicts record the commitment order, timestamps, and the
structured ``salt_source``.

Analytic probabilities here are exact *under float64 semantics*: the largest
``int`` that still reaches a target is found by bisection over the published
formula (monotone in ``int``), so analytic and simulated values share the
same quantization.  RTP at target w is w * ceil-quantized P, which differs
from 0.99 by at most w / 2^32 (~2.3e-4 at the 1,000,000x cashout cap).

Note: references/woo/crash.md analyzes a DIFFERENT game (SmartSoft's JetX,
97% RTP / 3% edge, tick-based mechanism with a 3% instant runway crash).
Its *shape* (P(win) = RTP / w, flat edge across targets) is identical;
its *numbers* intentionally do not match and are reported as a comparison
table, not a target, in ``scripts/validate_crash.py``.
"""

from __future__ import annotations

import binascii
import hashlib
import hmac
import math
import secrets
import time
import warnings
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from spinquest_sim import rng as sq_rng
from spinquest_sim.rng import BulkRng

__all__ = [
    "TWO32",
    "EDGE_MULTIPLIER",
    "HOUSE_EDGE",
    "MAX_CASHOUT",
    "STAKE_SALT",
    "STAKE_TERMINATING_HASH",
    "STAKE_CHAIN_LENGTH",
    "STAKE_SALT_BLOCK_TIME",
    "CommitmentOrderError",
    "CommitmentOrderWarning",
    "EXTERNAL_BEACONS",
    "BITCOIN_MIN_LEADING_ZEROS",
    "is_external_commitment",
    "crash_int_from_hash",
    "crash_point_from_int",
    "crash_point_from_hash",
    "crash_point_from_float",
    "next_chain_hash",
    "build_hash_chain",
    "verify_game_hash",
    "win_count",
    "win_probability",
    "win_probability_ideal",
    "instant_bust_probability",
    "analytic_table",
    "HashChain",
    "Crash",
    "simulate_targets",
    "simulate_chain_targets",
]

TWO32 = 1 << 32                 # 2^32 possible values of the 32-bit event
_TWO32_F = float(TWO32)
EDGE_MULTIPLIER = 1 - 0.01      # verbatim ``(1 - 0.01)``; == float64 0.99
HOUSE_EDGE = 0.01               # published "Edge: 1.00%"
MIN_CRASH = 1.0                 # "lowest crashpoint of 1"
MAX_CASHOUT = 1_000_000.0       # "maximum cashout value of 1,000,000x"

# Stake's real 2019 seeding event (references/stake/crash.md):
STAKE_TERMINATING_HASH = (
    "78a9757d3be42b74a3f70239078ad9317125fe9ee630d5bdada46de963e56752"
)
# Bitcoin block 584,500's hash — the public salt used for every game of
# STAKE'S OWN 2019 CHAIN.  The block was mined 2019-07-21, i.e. AFTER the
# chain's terminating hash was published; that ordering — commitment first,
# salt from an uncontrollable source second — is the entire guarantee.
# Valid ONLY for replaying/verifying Stake's published chain: pairing it
# with any chain generated today raises CommitmentOrderError.
STAKE_SALT = "0000000000000000001b34dc6a1e86083f95500b096231436e9b25cbdd0075c4"
# Reveal date of that salt (block 584,500 "mined July 21, 2019" per the
# reference); midnight UTC is a conservative lower bound on the mine time.
STAKE_SALT_BLOCK_TIME = datetime(2019, 7, 21, tzinfo=timezone.utc).timestamp()
STAKE_CHAIN_LENGTH = 10_000_000  # "chain of 10,000,000 SHA256 hashes"


class CommitmentOrderError(ValueError):
    """A salt was bound to a chain in the wrong commitment order.

    The provable-fairness guarantee requires the chain's terminating hash to
    be published BEFORE the salt is fixed by a source the operator cannot
    control ("a future bitcoin block ... so players can be certain that we
    did not pick one in the house's favor").  A salt already known while the
    chain is generated lets the operator grind secret seeds until the first
    playable rounds of a fully verifiable chain all bust early.
    """


class CommitmentOrderWarning(UserWarning):
    """A caller-supplied salt provably existed before the chain it salts.

    Emitted (not raised) for reproducible-simulation use; the resulting
    verification dict is marked ``fair_ordering: False``.
    """


# Recognized public randomness beacons a verifier can resolve out-of-band:
# beacon name -> the key naming the future index that must be chosen before
# its value exists (the salt is then that index's published value).
EXTERNAL_BEACONS: Dict[str, str] = {
    "bitcoin": "height",   # {"beacon": "bitcoin", "height": N} -> block N's hash
    "drand": "round",      # {"beacon": "drand", "round": R} -> round R's randomness
}

# One-sentence honesty note attached to every non-external salt record.
_NO_EXTERNAL_COMMITMENT_NOTE = (
    "salt has no verifier-resolvable external commitment (no recognized "
    "beacon + future index named in salt_source), so a verifier cannot rule "
    "out operator grinding: reproducible-simulation convenience only, NOT "
    "the published guarantee — fair_ordering is False"
)

# Attached while a structured beacon claim awaits out-of-band verification.
_UNVERIFIED_CLAIM_NOTE = (
    "external beacon commitment CLAIMED but not verified: fair_ordering "
    "stays False until the VERIFIER calls verify_salt_against_beacon() "
    "with the named beacon value and its publication time resolved "
    "out-of-band — the resolved value must equal the bound salt "
    "byte-for-byte and its publication time must strictly postdate the "
    "commitment"
)


def is_external_commitment(salt_source: object) -> bool:
    """True iff ``salt_source`` is a verifier-resolvable external commitment.

    The structured form is ``{"beacon": <name in EXTERNAL_BEACONS>,
    <index_key>: <positive int>}`` — e.g. ``{"beacon": "bitcoin",
    "height": 584500}`` or ``{"beacon": "drand", "round": 3366570}`` — naming
    a public beacon and a future index chosen BEFORE its value exists.  A
    verifier resolves the index out-of-band and checks the bound salt equals
    the beacon's published value; anything else (a free-text string, a
    self-drawn token, no source at all) is NOT an external commitment and can
    never yield ``fair_ordering: True``.
    """
    if not isinstance(salt_source, dict):
        return False
    index_key = EXTERNAL_BEACONS.get(salt_source.get("beacon"))
    if index_key is None:
        return False
    index = salt_source.get(index_key)
    return isinstance(index, int) and not isinstance(index, bool) and index > 0


# Structural floor for a salt CLAIMED to be a beacon's value.  Every Bitcoin
# block hash ever mined carries at least 8 leading zero nibbles (the
# difficulty-1 proof-of-work target is 0x00000000FFFF...): genesis has 10,
# block 1 has 8, STAKE_SALT (block 584,500) has 18.  A claimed block hash
# with fewer is arithmetically impossible AT ANY HEIGHT and is refused
# before any ordering question arises.  drand randomness is an unstructured
# 32-byte value (64 hex chars, no leading-zero floor).
BITCOIN_MIN_LEADING_ZEROS = 8
_BEACON_MIN_LEADING_ZEROS: Dict[str, int] = {
    "bitcoin": BITCOIN_MIN_LEADING_ZEROS,
    "drand": 0,
}
_HEX_DIGITS = frozenset("0123456789abcdef")


def _normalize_hex_value(value: str) -> str:
    """Lowercase, whitespace-stripped, ``0x``-stripped hex form."""
    v = value.strip().lower()
    if v.startswith("0x"):
        v = v[2:]
    return v


def _check_beacon_value_shape(value: str, beacon: str, what: str) -> str:
    """Structural sanity of a value claimed to BE ``beacon``'s output.

    Returns the normalized hex form, or raises :class:`CommitmentOrderError`
    when the claim is impossible for that beacon (wrong length / non-hex /
    too few leading zero nibbles for a Bitcoin block hash).
    """
    normalized = _normalize_hex_value(value)
    if len(normalized) != 64 or not _HEX_DIGITS.issuperset(normalized):
        raise CommitmentOrderError(
            f"{what} {value!r} is not a 64-character hex digest, so it "
            f"cannot be a {beacon} beacon value"
        )
    zeros = len(normalized) - len(normalized.lstrip("0"))
    floor = _BEACON_MIN_LEADING_ZEROS[beacon]
    if zeros < floor:
        raise CommitmentOrderError(
            f"{what} has {zeros} leading zero nibbles, but every genuine "
            f"{beacon} value carries at least {floor} (proof-of-work "
            "floor, true at every height since genesis): the claimed "
            "beacon commitment is arithmetically impossible"
        )
    return normalized


def _reject_stake_salt_for_new_chain(salt: Optional[str]) -> None:
    # Special-cased HINT only (the general rule "no external commitment =>
    # not fair" is the mechanism): normalized so case or a 0x prefix cannot
    # sneak the known 2019 salt past the refusal.
    if salt is None:
        return
    normalized = salt.strip().lower()
    if normalized.startswith("0x"):
        normalized = normalized[2:]
    if normalized == STAKE_SALT:
        raise CommitmentOrderError(
            "STAKE_SALT is Bitcoin block 584,500's hash (mined 2019-07-21). "
            "It may only be used to replay/verify Stake's own published 2019 "
            f"chain (terminating hash {STAKE_TERMINATING_HASH[:16]}...); "
            "binding it to a newly generated chain inverts the commitment "
            "order — the salt must come from a source revealed AFTER the "
            "chain's terminating hash is published."
        )


def _iso(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

# build_hash_chain stores every hex hash in memory (~130 bytes each); larger
# campaigns must use the streaming simulator instead.
_MAX_STORED_CHAIN = 2_000_000
_SIM_CHUNK_ROUNDS = 2_000_000     # 2M float64 rounds per chunk (~50 MB peak)
_CHAIN_PROGRESS_EVERY = 1_000_000


# ---------------------------------------------------------------------------
# Published event-generation math (verbatim ports)
# ---------------------------------------------------------------------------

def crash_int_from_hash(game_hash: str, salt: str) -> int:
    """The round's uniform 32-bit event ``int`` from a game hash.

    Verbatim port of the published JS: the game hash (a hex *string*) is the
    HMAC-SHA256 key, the salt (Bitcoin block hash, hex string) is the
    message, and the first 8 hex characters of the digest are parsed as an
    unsigned integer — i.e. the big-endian first 4 bytes.

    ``salt`` is required (no default): pass :data:`STAKE_SALT` explicitly to
    replay/verify Stake's published 2019 chain, or the chain's own bound
    salt for any other chain.
    """
    digest = hmac.new(
        game_hash.encode("utf-8"), salt.encode("utf-8"), hashlib.sha256
    ).digest()
    return int.from_bytes(digest[:4], "big")  # == parseInt(hex.substr(0,8), 16)


def crash_point_from_int(event_int: int) -> float:
    """``Math.max(1, (2 ** 32 / (int + 1)) * (1 - 0.01))`` — verbatim.

    Evaluated in float64 exactly as JS evaluates it in doubles (same IEEE-754
    operations in the same order), so scalar, vectorized and any external JS
    verifier agree bit-for-bit.  Weakly decreasing in ``event_int``.
    """
    if not 0 <= event_int < TWO32:
        raise ValueError(f"event int must be in [0, 2^32), got {event_int}")
    return max(1.0, (TWO32 / (event_int + 1)) * EDGE_MULTIPLIER)


def crash_point_from_hash(game_hash: str, salt: str) -> float:
    """Crash point for one game hash (chain mechanism, both steps).

    ``salt`` is required — see :func:`crash_int_from_hash`.
    """
    return crash_point_from_int(crash_int_from_hash(game_hash, salt))


def crash_point_from_float(value: float) -> float:
    """Crash point from one provably-fair stream float (seed-pair adaptation).

    The critic-verified stream's floats are exactly ``k / 2^32`` for a
    uniform 32-bit ``k`` (rng.py, generate_floats), and ``value * 2^32`` is
    an *exact* float64 product for every lattice point, so this recovers the
    uniform ``int`` bit-exactly and feeds it to the published formula.  Same
    crash-point distribution as the chain mechanism by construction.
    """
    if not 0.0 <= value < 1.0:
        raise ValueError(f"stream float must be in [0, 1), got {value}")
    return crash_point_from_int(int(value * _TWO32_F))


# ---------------------------------------------------------------------------
# Hash chain (the provable-fairness mechanism itself)
# ---------------------------------------------------------------------------

def next_chain_hash(hash_hex: str) -> str:
    """"each hash is the hash of the hexadecimal representation of the
    previous hash" — SHA-256 over the ASCII hex string."""
    return hashlib.sha256(hash_hex.encode("utf-8")).hexdigest()


def build_hash_chain(secret_seed: str, length: int) -> List[str]:
    """Chain of ``length`` hex hashes, oldest first.

    ``chain[0] = sha256(secret_seed)`` (the raw secret never doubles as a
    game hash), ``chain[i+1] = sha256(hex(chain[i]))``.  ``chain[-1]`` is the
    terminating hash to publish; games consume ``chain[-2], chain[-3], ...``
    (see :class:`HashChain`).
    """
    if length < 2:
        raise ValueError("chain needs at least 2 hashes (1 game + terminator)")
    if length > _MAX_STORED_CHAIN:
        raise ValueError(
            f"refusing to store {length:,} hashes in memory; use the "
            "streaming simulator (simulate_chain / simulate_chain_targets)"
        )
    chain = [hashlib.sha256(secret_seed.encode("utf-8")).hexdigest()]
    for _ in range(length - 1):
        chain.append(next_chain_hash(chain[-1]))
    return chain


def verify_game_hash(
    game_hash: str, terminating_hash: str, max_steps: int = STAKE_CHAIN_LENGTH
) -> Optional[int]:
    """Number of SHA-256 steps from ``game_hash`` to the published
    terminating hash ("repeatedly SHA256-hashing it until the published
    terminating hash is reached"), or None if not reached in ``max_steps``.
    Game g (1-indexed, newest first) verifies in exactly g steps.
    """
    current = game_hash
    for step in range(1, max_steps + 1):
        current = next_chain_hash(current)
        if current == terminating_hash:
            return step
    return None


class HashChain:
    """A pre-committed crash hash chain, played newest-hash-first.

    Honest protocol (the order Stake's 2019 seeding event followed):

    1. ``hc = HashChain(length=...)`` — the chain is generated and
       :attr:`terminating_hash` (the public commitment) exists from this
       moment (:attr:`committed_at`).  Publish it.
    2. ``hc.bind_salt(salt, salt_source={"beacon": ..., ...},
       revealed_at=...)`` — AFTER publishing, bind a salt from a source the
       operator cannot control.  A structured EXTERNAL commitment
       (:func:`is_external_commitment`) naming a recognized beacon and
       index — e.g. ``{"beacon": "bitcoin", "height": N}`` — is validated
       structurally (64 hex chars; >= 8 leading zero nibbles for a Bitcoin
       block hash) and requires a MANDATORY ``revealed_at`` strictly after
       :attr:`committed_at` and not in the future; it is then recorded as
       ``order: "external_commitment_claimed_unverified", fair_ordering:
       False`` — a CLAIM, not a certification.  Any salt bound without a
       structured claim (including a salt the operator drew itself) is
       recorded as ``order: "operator_drawn_after_commitment",
       fair_ordering: False``.  ``STAKE_SALT`` is refused outright (it
       predates any new chain); a ``revealed_at`` earlier than
       :attr:`committed_at` is refused.
    2b. ``hc.verify_salt_against_beacon(resolved_value, resolved_time)`` —
       the VERIFIER resolves the named beacon index out-of-band and feeds
       the published value and its publication time here.  Only a
       byte-identical match published strictly after the commitment flips
       ``fair_ordering`` to True (``order: "terminating_hash_first"``); any
       failure refutes the claim permanently.
    3. Play: each round pops the next game hash (``chain[-2]`` first — the
       terminator itself is the commitment and is not played).  Every popped
       hash re-hashes to the terminating hash in exactly ``game_index``
       steps.  Playing before a salt is bound raises ``RuntimeError``.

    Passing ``salt=`` at construction is a *reproducible-simulation*
    convenience: the salt provably existed before the chain, so a
    :class:`CommitmentOrderWarning` is emitted and :attr:`commitment`
    records ``fair_ordering: False``.
    """

    def __init__(
        self,
        secret_seed: Optional[str] = None,
        length: int = 10_001,
        salt: Optional[str] = None,
        salt_source: Optional[object] = None,
    ) -> None:
        if secret_seed is None:
            secret_seed = secrets.token_hex(32)
        self.secret_seed = secret_seed
        self._chain = build_hash_chain(secret_seed, length)
        self.length = length
        self.games_played = 0
        # The commitment exists as soon as the chain (hence its terminating
        # hash) exists — any salt bound later is bound after this instant.
        self.committed_at: float = time.time()
        self.salt: Optional[str] = None
        self.salt_source: Optional[object] = None
        self.salt_bound_at: Optional[float] = None
        self.salt_revealed_at: Optional[float] = None
        self._salt_preexisting = False
        self._beacon_verified = False
        self._beacon_refuted: Optional[str] = None
        self.beacon_verification: Optional[Dict[str, object]] = None
        if salt is not None:
            # Convenience path: this salt was in the caller's hands while
            # the chain was generated -> provably not a fair ordering.
            self.bind_salt(salt, salt_source=salt_source, _preexisting=True)

    @property
    def terminating_hash(self) -> str:
        """The published commitment (last hash of the chain)."""
        return self._chain[-1]

    @property
    def games_remaining(self) -> int:
        return self.length - 1 - self.games_played

    @property
    def fair_ordering_claimed(self) -> bool:
        """True iff a structured external beacon commitment is CLAIMED.

        A claim alone certifies nothing — it merely names a beacon and
        index a verifier can resolve out-of-band.  See
        :attr:`fair_ordering` / :meth:`verify_salt_against_beacon`.
        """
        return (
            self.salt is not None
            and not self._salt_preexisting
            and is_external_commitment(self.salt_source)
        )

    @property
    def fair_ordering(self) -> bool:
        """True iff the claimed beacon commitment has been VERIFIED.

        Timestamp order alone is not enough (a salt the operator drew after
        the commitment is freely grindable), and a beacon claim alone is
        not enough either (the operator could name an already-published
        index and grind the SEED against its value).  True requires a
        structured claim (:attr:`fair_ordering_claimed`) AND a successful
        :meth:`verify_salt_against_beacon` call with the beacon's value and
        publication time resolved out-of-band by the verifier.  No external
        commitment, or no verification => not fair.
        """
        return self.fair_ordering_claimed and self._beacon_verified

    @property
    def commitment(self) -> Dict[str, object]:
        """The commitment-order record (included in verification dicts)."""
        if self.salt is None:
            order = "unbound (commitment published, awaiting salt)"
        elif self._salt_preexisting:
            order = "salt_preexisting_reproducible_mode"
        elif self._beacon_refuted is not None:
            order = "external_commitment_refuted"
        elif self.fair_ordering:
            order = "terminating_hash_first"
        elif self.fair_ordering_claimed:
            order = "external_commitment_claimed_unverified"
        else:
            # Bound after the commitment but with no external commitment —
            # indistinguishable, to a verifier, from a salt the operator
            # drew (and possibly ground) itself.
            order = "operator_drawn_after_commitment"
        record: Dict[str, object] = {
            "terminating_hash": self.terminating_hash,
            "terminating_hash_committed_at": _iso(self.committed_at),
            "terminating_hash_committed_at_unix": self.committed_at,
            "salt": self.salt,
            "salt_source": self.salt_source,
            "salt_bound_at": _iso(self.salt_bound_at),
            "salt_bound_at_unix": self.salt_bound_at,
            "salt_revealed_at": _iso(self.salt_revealed_at),
            "order": order,
            "fair_ordering": self.fair_ordering,
            "fair_ordering_claimed": self.fair_ordering_claimed,
            "beacon_verification": self.beacon_verification,
        }
        if self.salt is not None and not self.fair_ordering:
            if self._salt_preexisting:
                record["note"] = (
                    "salt existed before the chain was generated, so the "
                    "commitment order is inverted regardless of its source "
                    "— fair_ordering is False"
                )
            elif self._beacon_refuted is not None:
                record["note"] = (
                    "beacon claim REFUTED by out-of-band resolution: "
                    + self._beacon_refuted
                )
            elif self.fair_ordering_claimed:
                record["note"] = _UNVERIFIED_CLAIM_NOTE
            else:
                record["note"] = _NO_EXTERNAL_COMMITMENT_NOTE
        return record

    def bind_salt(
        self,
        salt: str,
        salt_source: Optional[object] = None,
        revealed_at: Optional[float] = None,
        _preexisting: bool = False,
    ) -> None:
        """Bind the public salt to the already-committed chain (one-time).

        A structured external commitment as ``salt_source``
        (:func:`is_external_commitment`) — e.g. ``{"beacon": "bitcoin",
        "height": N}`` — is a CLAIM the verifier can resolve out-of-band,
        and it is policed at bind time:

        * the salt must be structurally possible for the named beacon
          (64 hex chars; a Bitcoin block hash needs at least
          :data:`BITCOIN_MIN_LEADING_ZEROS` leading zero nibbles — every
          real block at any height has them);
        * ``revealed_at`` is MANDATORY, must be strictly after
          :attr:`committed_at` (the named index must be one whose value
          did not exist at commitment time — an honestly attested
          already-published value is refused here), and must not be in the
          future (a salt cannot be bound before its source revealed it).

        Even then ``fair_ordering`` stays False: the record says ``order:
        "external_commitment_claimed_unverified"`` until
        :meth:`verify_salt_against_beacon` succeeds with out-of-band data.
        Any other source (free text, none, a self-drawn token) binds fine
        for simulation but records ``order:
        "operator_drawn_after_commitment", fair_ordering: False``.

        ``revealed_at`` (unix time), when known, attests when the salt's
        source made it public; a value earlier than :attr:`committed_at`
        raises :class:`CommitmentOrderError` (necessary, never sufficient).
        ``STAKE_SALT`` always raises (it was revealed 2019-07-21, before any
        chain generated by this code).
        """
        if self.salt is not None:
            raise CommitmentOrderError(
                "a salt is already bound to this chain; a commitment binds "
                "exactly one salt"
            )
        _reject_stake_salt_for_new_chain(salt)
        if not salt:
            raise ValueError("salt must be a non-empty string")
        if revealed_at is not None and revealed_at < self.committed_at:
            raise CommitmentOrderError(
                f"salt reveal time {_iso(revealed_at)} predates the chain "
                f"commitment {_iso(self.committed_at)}; the salt must come "
                "from a source revealed after the terminating hash was "
                "published"
            )
        if not _preexisting and is_external_commitment(salt_source):
            beacon = salt_source["beacon"]  # type: ignore[index]
            _check_beacon_value_shape(salt, beacon, "claimed beacon salt")
            if revealed_at is None:
                raise CommitmentOrderError(
                    "a beacon salt_source claim requires a mandatory "
                    "revealed_at (unix time the beacon published this "
                    "value): without it the claim can never be checked "
                    "against the commitment order — an already-published "
                    "beacon value has no honest revealed_at after the "
                    "commitment, so omitting it is not an escape hatch"
                )
            if revealed_at <= self.committed_at:
                raise CommitmentOrderError(
                    f"claimed {beacon} value attested revealed at "
                    f"{_iso(revealed_at)}, not strictly after the chain "
                    f"commitment {_iso(self.committed_at)}: the named "
                    "index must be a FUTURE one whose value did not exist "
                    "when the terminating hash was published"
                )
            if revealed_at > time.time():
                raise CommitmentOrderError(
                    f"revealed_at {_iso(revealed_at)} is in the future: a "
                    "salt cannot be bound before its source has revealed "
                    "it"
                )
        if _preexisting:
            warnings.warn(
                "salt was supplied while the chain was generated "
                "(reproducible-simulation mode): commitment ordering is NOT "
                "fair — a real deployment must publish terminating_hash "
                "first and bind_salt() afterwards",
                CommitmentOrderWarning,
                stacklevel=3,
            )
        self.salt = salt
        self.salt_source = salt_source
        self.salt_revealed_at = revealed_at
        self._salt_preexisting = _preexisting
        self.salt_bound_at = time.time()

    def verify_salt_against_beacon(
        self, resolved_value: str, resolved_time: float
    ) -> Dict[str, object]:
        """Confirm (or refute) the claimed beacon commitment — VERIFIER step.

        The verifier resolves the beacon index named in ``salt_source``
        OUT-OF-BAND — a Bitcoin node or block explorer for ``{"beacon":
        "bitcoin", "height": N}``, the drand HTTP API for ``{"beacon":
        "drand", "round": R}`` — never through the operator's process, and
        passes the published value and its publication time (unix).
        ``fair_ordering`` becomes True iff BOTH hold:

        * ``resolved_value`` equals the bound salt byte-for-byte (after
          case/``0x`` normalization), and
        * ``resolved_time`` is strictly AFTER :attr:`committed_at` — the
          beacon value did not yet exist when the terminating hash was
          published, so nothing could have been ground against it.

        Any failure raises :class:`CommitmentOrderError` and PERMANENTLY
        marks the claim ``order: "external_commitment_refuted"`` (an
        already-published beacon value — e.g. Bitcoin block 1's hash,
        mined 2009-01-09 — is refuted here no matter what ``revealed_at``
        the operator attested at bind time).  Returns the updated
        :attr:`commitment` record.

        Trust model: this call is the verifier's OWN act with the
        verifier's OWN resolved data.  An operator-produced record whose
        ``beacon_verification`` says ``verified: True`` proves nothing to
        anyone else — a verifier re-runs this method against their own
        resolution of the named index.
        """
        if self.salt is None:
            raise RuntimeError("no salt bound: nothing to verify")
        if self._salt_preexisting or not is_external_commitment(
            self.salt_source
        ):
            raise CommitmentOrderError(
                "no external beacon commitment is claimed for this "
                "chain's salt; there is nothing a beacon resolution could "
                "certify"
            )
        if self._beacon_refuted is not None:
            raise CommitmentOrderError(
                "beacon claim was already refuted and stays refuted: "
                + self._beacon_refuted
            )
        beacon = self.salt_source["beacon"]  # type: ignore[index]

        def _refute(reason: str) -> None:
            self._beacon_refuted = reason
            self._beacon_verified = False
            self.beacon_verification = {
                "verified": False,
                "reason": reason,
                "resolved_time": resolved_time,
                "resolved_time_iso": _iso(resolved_time)
                if isinstance(resolved_time, (int, float))
                and math.isfinite(resolved_time)
                else None,
                "checked_at": _iso(time.time()),
            }
            raise CommitmentOrderError(reason)

        if not isinstance(resolved_time, (int, float)) or isinstance(
            resolved_time, bool
        ) or not math.isfinite(resolved_time):
            _refute(
                "resolved_time must be a finite unix timestamp from the "
                "verifier's own out-of-band resolution"
            )
        resolved_norm = _normalize_hex_value(resolved_value)
        salt_norm = _normalize_hex_value(self.salt)
        if resolved_norm != salt_norm:
            _refute(
                f"resolved {beacon} value {resolved_norm[:16]}... does "
                f"not match the bound salt {salt_norm[:16]}...: the "
                "operator's beacon claim is false"
            )
        if resolved_time <= self.committed_at:
            _refute(
                f"the {beacon} value named in salt_source was published "
                f"{_iso(float(resolved_time))}, BEFORE the chain "
                f"commitment {_iso(self.committed_at)}: it was grindable "
                "while the chain was generated, so the fairness claim is "
                "refuted (the named index was not a future one)"
            )
        self._beacon_verified = True
        self.beacon_verification = {
            "verified": True,
            "resolved_time": float(resolved_time),
            "resolved_time_iso": _iso(float(resolved_time)),
            "checked_at": _iso(time.time()),
            "note": "resolved out-of-band by the verifier: value matched "
            "the bound salt byte-for-byte and its publication time "
            "postdates the commitment",
        }
        return self.commitment

    def pop_hash(self) -> Tuple[int, str]:
        """(1-indexed game number, game hash) for the next round."""
        if self.salt is None:
            raise RuntimeError(
                "no salt bound: publish terminating_hash, then bind_salt() "
                "with a salt revealed after the commitment — rounds cannot "
                "be played before the salt exists"
            )
        if self.games_remaining <= 0:
            raise RuntimeError("hash chain exhausted")
        self.games_played += 1
        return self.games_played, self._chain[self.length - 1 - self.games_played]

    def crash_points(self, count: int) -> List[float]:
        """Crash points of the next ``count`` rounds, in play order."""
        return [
            crash_point_from_hash(self.pop_hash()[1], self.salt)
            for _ in range(count)
        ]


def _stream_chain_ints(
    secret_seed: str, n_rounds: int, salt: str, progress: bool = True
) -> Tuple[np.ndarray, str]:
    """Event ints for a full chain campaign, without storing the chain.

    Walks a chain of ``n_rounds + 1`` hashes forward from ``secret_seed``
    (constant memory), computes each game hash's HMAC event int, and returns
    ``(ints in PLAY order — newest hash first, terminating_hash)``.  Row g
    (0-indexed) equals ``crash_int_from_hash(chain[n_rounds - 1 - g], salt)``
    — bit-identical to :class:`HashChain` play.
    """
    salt_bytes = salt.encode("utf-8")
    out = np.empty(n_rounds, dtype=np.int64)
    hex_hash = hashlib.sha256(secret_seed.encode("utf-8")).hexdigest().encode()
    t0 = time.perf_counter()
    for i in range(n_rounds):
        digest = hmac.new(hex_hash, salt_bytes, hashlib.sha256).digest()
        out[i] = int.from_bytes(digest[:4], "big")
        hex_hash = binascii.hexlify(hashlib.sha256(hex_hash).digest())
        if progress and (i + 1) % _CHAIN_PROGRESS_EVERY == 0:
            rate = (i + 1) / (time.perf_counter() - t0)
            print(
                f"  chain walk: {i + 1:,}/{n_rounds:,} hashes ({rate:,.0f}/s)",
                flush=True,
            )
    return out[::-1].copy(), hex_hash.decode()


def _stream_chain_terminator(
    secret_seed: str, n_rounds: int, progress: bool = True
) -> str:
    """Terminating hash of the ``n_rounds + 1``-hash chain, salt-free.

    Constant-memory forward walk (SHA-256 only, no HMAC): this is the
    COMMIT phase of the honest protocol — the terminating hash can be
    computed and published before any salt exists.
    """
    hex_hash = hashlib.sha256(secret_seed.encode("utf-8")).hexdigest().encode()
    t0 = time.perf_counter()
    for i in range(n_rounds):
        hex_hash = binascii.hexlify(hashlib.sha256(hex_hash).digest())
        if progress and (i + 1) % _CHAIN_PROGRESS_EVERY == 0:
            rate = (i + 1) / (time.perf_counter() - t0)
            print(
                f"  chain commit: {i + 1:,}/{n_rounds:,} hashes ({rate:,.0f}/s)",
                flush=True,
            )
    return hex_hash.decode()


# ---------------------------------------------------------------------------
# Analytics (exact under float64 semantics)
# ---------------------------------------------------------------------------

def _validate_target(target: float) -> float:
    target = float(target)
    if not math.isfinite(target) or not MIN_CRASH < target <= MAX_CASHOUT:
        raise ValueError(
            f"cashout target must satisfy 1 < target <= {MAX_CASHOUT:,.0f}x "
            f"(published cashout cap), got {target}"
        )
    return target


def win_count(target: float) -> int:
    """EXACT number of event ints ``k`` with ``crash_point(k) >= target``.

    The published formula is weakly decreasing in ``k`` (IEEE-754 division
    and multiplication are monotone), so the boundary is found by bisection
    over the *actual float64 formula* — no closed-form approximation.  The
    winning set is exactly ``{0, 1, ..., win_count - 1}``.
    """
    target = _validate_target(target)
    if crash_point_from_int(0) < target:
        return 0
    if crash_point_from_int(TWO32 - 1) >= target:
        return TWO32
    lo, hi = 0, TWO32 - 1  # invariant: crash(lo) >= target > crash(hi)
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if crash_point_from_int(mid) >= target:
            lo = mid
        else:
            hi = mid
    return lo + 1


def win_probability(target: float) -> float:
    """Exact P(crash point >= target) = win_count / 2^32."""
    return win_count(target) / TWO32


def win_probability_ideal(target: float) -> float:
    """The reference's closed form 0.99 / w (ignores 32-bit quantization)."""
    return 0.99 / _validate_target(target)


def instant_bust_probability() -> float:
    """Exact P(crash point == 1.0) — the published "~1%" instant bust."""
    # crash == 1 iff the raw (un-maxed) value <= 1, i.e. k >= win boundary
    # of the raw formula at 1.0; reuse the bisection with target just above 1.
    lo, hi = 0, TWO32 - 1
    raw = lambda k: (TWO32 / (k + 1)) * EDGE_MULTIPLIER  # noqa: E731
    if raw(hi) > 1.0:
        return 0.0
    while hi - lo > 1:  # invariant: raw(lo) > 1 >= raw(hi)
        mid = (lo + hi) // 2
        if raw(mid) > 1.0:
            lo = mid
        else:
            hi = mid
    return (TWO32 - hi) / TWO32


def analytic_table(targets: Sequence[float]) -> List[Dict[str, float]]:
    """Per-target analytic row: exact and ideal P(win)/RTP, quantization
    bound, and per-unit SD — the continuous game's 'paytable'."""
    rows = []
    for w in targets:
        game = Crash(w)
        rows.append(
            {
                "target": game.target,
                "win_probability": game.win_probability,
                "win_probability_ideal": game.win_probability_ideal,
                "rtp": game.rtp,
                "rtp_ideal": 0.99,
                "rtp_quantization_bound": game.rtp_quantization_bound,
                "house_edge": game.house_edge,
                "std_per_unit": game.std_per_unit,
                "std_per_unit_ideal": game.std_per_unit_ideal,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def _sim_stats(
    game: "Crash", n_rounds: int, wins: int, elapsed: float
) -> Dict[str, object]:
    p_hat = wins / n_rounds
    rtp_emp = p_hat * game.target
    se_p = math.sqrt(game.win_probability * (1.0 - game.win_probability) / n_rounds)
    se_rtp = game.target * se_p
    z = (p_hat - game.win_probability) / se_p if se_p > 0 else 0.0
    return {
        "rtp": rtp_emp,
        "house_edge": 1.0 - rtp_emp,
        "std_per_unit": game.target * math.sqrt(max(p_hat * (1.0 - p_hat), 0.0)),
        "config": game.config(),
        "n_rounds": n_rounds,
        "wins": wins,
        "win_rate": p_hat,
        "analytic_win_probability": game.win_probability,
        "analytic_rtp": game.rtp,
        "analytic_std_per_unit": game.std_per_unit,
        "se_win_probability": se_p,
        "se_rtp": se_rtp,
        "z_score": z,           # same z for win prob and RTP (RTP = w * p)
        "within_3se": abs(z) <= 3.0,
        "elapsed_s": elapsed,
        "rounds_per_sec": n_rounds / elapsed if elapsed > 0 else float("inf"),
    }


class Crash:
    """Crash engine for one auto-cashout target ``w``.

    Strategy modelled: bet 1 unit with "Cashout At" = w; win ``w`` per unit
    iff the round's crash point >= w (Stake pays bet x m for any cashout
    m <= crash point; auto-cashout fires exactly at w), else lose the bet.

    (a) analytic probability / RTP / variance (exact float64-semantics),
    (b) provably-fair single rounds — chain mechanism (:meth:`play_round`)
        and seed-pair scalar path (:meth:`play_round_seedpair`),
    (c) vectorized simulators for 10M+ rounds — :meth:`simulate` (BulkRng)
        and :meth:`simulate_chain` (real streamed hash chain),
    (d) the standard result dict {rtp, house_edge, std_per_unit, config}.
    """

    def __init__(self, target: float) -> None:
        self.target = _validate_target(target)
        self._win_count = win_count(self.target)

    # --- (a) analytics -----------------------------------------------------

    @property
    def win_count_exact(self) -> int:
        return self._win_count

    @property
    def win_probability(self) -> float:
        return self._win_count / TWO32

    @property
    def win_probability_ideal(self) -> float:
        return 0.99 / self.target

    @property
    def payout_multiplier(self) -> float:
        return self.target

    @property
    def rtp(self) -> float:
        return self.target * self.win_probability

    @property
    def house_edge(self) -> float:
        return 1.0 - self.rtp

    @property
    def rtp_quantization_bound(self) -> float:
        """|RTP - 0.99| <= target / 2^32 (32-bit event quantization)."""
        return self.target / TWO32

    @property
    def variance_per_unit(self) -> float:
        """Var of the for-one payout X per unit: X = w w.p. p, else 0."""
        p, w = self.win_probability, self.target
        return w * w * p - (w * p) ** 2

    @property
    def std_per_unit(self) -> float:
        return math.sqrt(self.variance_per_unit)

    @property
    def std_per_unit_ideal(self) -> float:
        """Closed form sqrt(0.99 w - 0.99^2) from P = 0.99/w."""
        return math.sqrt(0.99 * self.target - 0.99 ** 2)

    def config(self) -> Dict[str, object]:
        return {
            "game": "crash",
            "target": self.target,
            "payout_multiplier": self.target,
            "win_probability": self.win_probability,
            "house_edge_published": HOUSE_EDGE,
            "max_cashout": MAX_CASHOUT,
        }

    def analytic_summary(self) -> Dict[str, object]:
        """Standard result dict, analytic (no simulation)."""
        return {
            "rtp": self.rtp,
            "house_edge": self.house_edge,
            "std_per_unit": self.std_per_unit,
            "config": self.config(),
        }

    # --- (b) provably-fair single rounds ------------------------------------

    def play_round(self, game_hash: str, salt: str) -> Dict[str, object]:
        """One round of Stake's actual mechanism, from a chain game hash.

        ``salt`` is required: the chain's bound salt (``HashChain.salt``),
        or :data:`STAKE_SALT` explicitly when replaying Stake's published
        2019 chain.
        """
        event_int = crash_int_from_hash(game_hash, salt)
        crash_point = crash_point_from_int(event_int)
        win = crash_point >= self.target
        return {
            "win": win,
            "payout": self.target if win else 0.0,
            "crash_point": crash_point,
            "event_int": event_int,
            "config": self.config(),
            "verification": {
                "mechanism": "hash_chain",
                "game_hash": game_hash,
                "salt": salt,
            },
        }

    def play_round_seedpair(
        self, server_seed: str, client_seed: str, nonce: int
    ) -> Dict[str, object]:
        """One round on the critic-verified seed-pair stream (1 float).

        Single-player adaptation: the stream float is exactly ``k / 2^32``,
        so the recovered ``k`` is uniform on [0, 2^32) — identical crash
        distribution to the chain mechanism (documented in the module
        docstring).  Fully verifiable from the returned triple.
        """
        value = sq_rng.generate_floats(server_seed, client_seed, nonce, 0, 1)[0]
        event_int = int(value * _TWO32_F)  # exact for lattice floats
        crash_point = crash_point_from_int(event_int)
        win = crash_point >= self.target
        return {
            "win": win,
            "payout": self.target if win else 0.0,
            "crash_point": crash_point,
            "event_int": event_int,
            "config": self.config(),
            "verification": {
                "mechanism": "seed_pair",
                "server_seed": server_seed,
                "client_seed": client_seed,
                "nonce": nonce,
            },
        }

    # --- (c) vectorized simulators ------------------------------------------

    def simulate(
        self,
        n_rounds: int,
        bulk: Optional[BulkRng] = None,
        chunk_rounds: int = _SIM_CHUNK_ROUNDS,
        progress: bool = True,
    ) -> Dict[str, object]:
        """Simulate on the vectorized BulkRng stream; standard result dict."""
        res = simulate_targets(
            [self.target], n_rounds, bulk=bulk,
            chunk_rounds=chunk_rounds, progress=progress,
        )
        out = res["targets"][0]
        out["verification"] = res["verification"]
        return out

    def simulate_chain(
        self,
        n_rounds: int,
        secret_seed: Optional[str] = None,
        salt: Optional[str] = None,
        salt_source: Optional[str] = None,
        progress: bool = True,
    ) -> Dict[str, object]:
        """Simulate on a real streamed hash chain; standard result dict.

        ``salt=None`` (default) runs the two-phase protocol: commit the
        terminating hash first, then draw a fresh salt — recorded honestly
        as ``order: "operator_drawn_after_commitment", fair_ordering:
        False`` (the salt has no external commitment).  See
        :func:`simulate_chain_targets`.
        """
        res = simulate_chain_targets(
            [self.target], n_rounds, secret_seed=secret_seed,
            salt=salt, salt_source=salt_source, progress=progress,
        )
        out = res["targets"][0]
        out["verification"] = res["verification"]
        return out


# ---------------------------------------------------------------------------
# Multi-target simulators (one stream shared across all targets)
# ---------------------------------------------------------------------------

def _finish_multi(
    games: List[Crash],
    wins: List[int],
    n_rounds: int,
    elapsed: float,
    verification: Dict[str, object],
) -> Dict[str, object]:
    rows = [
        _sim_stats(g, n_rounds, w, elapsed) for g, w in zip(games, wins)
    ]
    return {
        "targets": rows,
        "n_rounds": n_rounds,
        "elapsed_s": elapsed,
        "rounds_per_sec": n_rounds / elapsed if elapsed > 0 else float("inf"),
        "pass": all(r["within_3se"] for r in rows),
        "verification": verification,
    }


def simulate_targets(
    targets: Sequence[float],
    n_rounds: int,
    bulk: Optional[BulkRng] = None,
    chunk_rounds: int = _SIM_CHUNK_ROUNDS,
    progress: bool = True,
) -> Dict[str, object]:
    """N provably-fair BulkRng rounds, evaluated at every target at once.

    One nonce per round; round i is bit-verifiable against
    :meth:`Crash.play_round_seedpair` at nonce ``nonce_start + i`` (the float
    -> int recovery is exact).  Chunked so arrays stay ~50 MB.
    """
    if n_rounds <= 0:
        raise ValueError("n_rounds must be positive")
    games = [Crash(w) for w in targets]
    rng = bulk if bulk is not None else BulkRng()
    nonce_first = rng.nonce_next
    wins = [0] * len(games)
    done = 0
    t0 = time.perf_counter()
    while done < n_rounds:
        step = min(chunk_rounds, n_rounds - done)
        k = rng.floats(step) * _TWO32_F      # exact uniform 32-bit ints
        crash = np.maximum(1.0, (_TWO32_F / (k + 1.0)) * EDGE_MULTIPLIER)
        for i, game in enumerate(games):
            wins[i] += int(np.count_nonzero(crash >= game.target))
        done += step
        if progress and n_rounds > chunk_rounds:
            rate = done / (time.perf_counter() - t0)
            print(
                f"  crash[bulk]: {done:,}/{n_rounds:,} rounds ({rate:,.0f}/s)",
                flush=True,
            )
    elapsed = time.perf_counter() - t0
    return _finish_multi(
        games, wins, n_rounds, elapsed,
        {
            "mechanism": "seed_pair_bulk",
            "server_seed_hash": rng.server_seed_hash,
            "client_seed": rng.client_seed,
            "nonce_range": (nonce_first, rng.nonce_next),
        },
    )


def simulate_chain_targets(
    targets: Sequence[float],
    n_rounds: int,
    secret_seed: Optional[str] = None,
    salt: Optional[str] = None,
    salt_source: Optional[object] = None,
    progress: bool = True,
) -> Dict[str, object]:
    """N rounds of Stake's ACTUAL mechanism: a fresh salted hash chain of
    ``n_rounds + 1`` hashes, streamed in constant memory, played newest-first.

    Commitment ordering: with ``salt=None`` (default) the two-phase protocol
    is run in-process — (1) walk the chain once, salt-free, to COMMIT the
    terminating hash; (2) only then draw a fresh salt; (3) replay the chain
    with the HMAC applied.  Because that salt comes from the operator's own
    ``secrets.token_hex`` — NOT from a verifier-resolvable external beacon —
    the verification dict records it honestly as ``order:
    "operator_drawn_after_commitment", fair_ordering: False``: a
    reproducible-simulation convenience, not the published guarantee (no
    in-process call can be, since a genuinely fair salt must come from a
    beacon value that does not exist until after the commitment is public;
    use :class:`HashChain` with :meth:`HashChain.bind_salt` (structured
    beacon ``salt_source`` + mandatory ``revealed_at``) followed by the
    verifier's :meth:`HashChain.verify_salt_against_beacon` for the real
    protocol).  A caller-supplied
    ``salt`` (reproducible-simulation mode) provably existed before the
    chain, so a :class:`CommitmentOrderWarning` is emitted and the
    verification dict is marked ``fair_ordering: False`` as well.
    ``STAKE_SALT`` is always refused — it may only replay Stake's own
    published 2019 chain.

    Every round is individually verifiable: round g's game hash re-hashes to
    the returned terminating hash in exactly g steps.  ~250k rounds/s
    (2 SHA-256 + 1 HMAC per round, inherently sequential chain walk).
    """
    if n_rounds <= 0:
        raise ValueError("n_rounds must be positive")
    if secret_seed is None:
        secret_seed = secrets.token_hex(32)
    _reject_stake_salt_for_new_chain(salt)
    games = [Crash(w) for w in targets]
    t0 = time.perf_counter()
    committed_hash: Optional[str] = None
    committed_at: Optional[float] = None
    if salt is None:
        if is_external_commitment(salt_source):
            raise CommitmentOrderError(
                "salt_source claims an external beacon commitment but the "
                "salt is about to be self-drawn in-process; supply the "
                "beacon's actual value via HashChain.bind_salt instead"
            )
        # COMMIT first (salt-free walk), then draw the salt.  Timestamp
        # order is honest, but the salt is the operator's own draw — no
        # external commitment, so this is NOT certified as fairly ordered.
        committed_hash = _stream_chain_terminator(secret_seed, n_rounds, progress)
        committed_at = time.time()
        salt = secrets.token_hex(32)
        if salt_source is None:
            salt_source = {
                "type": "operator_drawn",
                "method": "secrets.token_hex(32) after terminating-hash "
                "commitment",
            }
        salt_bound_at = time.time()
        order = "operator_drawn_after_commitment"
        fair = False
    else:
        warnings.warn(
            "caller-supplied salt existed before this chain was generated "
            "(reproducible-simulation mode): commitment ordering is NOT "
            "fair — omit `salt` to run the honest two-phase protocol",
            CommitmentOrderWarning,
            stacklevel=2,
        )
        if salt_source is None:
            salt_source = "caller-supplied (existed before chain generation)"
        salt_bound_at = None
        order = "salt_preexisting_reproducible_mode"
        fair = False
    ints, terminating = _stream_chain_ints(secret_seed, n_rounds, salt, progress)
    if committed_hash is not None and terminating != committed_hash:
        raise RuntimeError(
            "post-salt replay reached a different terminating hash than the "
            "pre-salt commitment — chain walk is not deterministic"
        )
    wins = []
    for game in games:
        # threshold in int domain: winning set is exactly {0..win_count-1}
        wins.append(int(np.count_nonzero(ints < game.win_count_exact)))
    elapsed = time.perf_counter() - t0
    commitment: Dict[str, object] = {
        "terminating_hash": terminating,
        "terminating_hash_committed_at": _iso(committed_at),
        "terminating_hash_committed_at_unix": committed_at,
        "salt": salt,
        "salt_source": salt_source,
        "salt_bound_at": _iso(salt_bound_at),
        "salt_bound_at_unix": salt_bound_at,
        "order": order,
        "fair_ordering": fair,
    }
    if not fair:
        commitment["note"] = _NO_EXTERNAL_COMMITMENT_NOTE
    return _finish_multi(
        games, wins, n_rounds, elapsed,
        {
            "mechanism": "hash_chain",
            "terminating_hash": terminating,
            "salt": salt,
            "chain_length": n_rounds + 1,
            "commitment": commitment,
        },
    )
