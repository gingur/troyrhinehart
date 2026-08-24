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
generated, the operator can grind secret seeds until the first rounds of a
fully verifiable chain all bust early.  This module therefore enforces the
order: ``STAKE_SALT`` (Bitcoin block 584,500, mined 2019-07-21) is accepted
ONLY for replaying/verifying Stake's own published 2019 chain — pairing it
with any newly generated chain raises :class:`CommitmentOrderError`; every
chain-generating API requires an explicit salt bound AFTER the terminating
hash exists (:meth:`HashChain.bind_salt`, or the two-phase auto protocol in
:func:`simulate_chain_targets`); a salt attested to predate the commitment
raises, a caller-supplied salt that provably existed before the chain was
generated warns (:class:`CommitmentOrderWarning`, reproducible-simulation
mode); and the verification dicts record the commitment order and timestamps.

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


def _reject_stake_salt_for_new_chain(salt: Optional[str]) -> None:
    if salt == STAKE_SALT:
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
    2. ``hc.bind_salt(salt, ...)`` — AFTER publishing, bind a salt from a
       source the operator cannot control (e.g. a future Bitcoin block's
       hash).  ``STAKE_SALT`` is refused (it predates any new chain); a
       ``revealed_at`` earlier than :attr:`committed_at` is refused.
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
        salt_source: Optional[str] = None,
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
        self.salt_source: Optional[str] = None
        self.salt_bound_at: Optional[float] = None
        self.salt_revealed_at: Optional[float] = None
        self._salt_preexisting = False
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
    def fair_ordering(self) -> bool:
        """True iff the salt was bound only after the commitment existed."""
        return self.salt is not None and not self._salt_preexisting

    @property
    def commitment(self) -> Dict[str, object]:
        """The commitment-order record (included in verification dicts)."""
        return {
            "terminating_hash": self.terminating_hash,
            "terminating_hash_committed_at": _iso(self.committed_at),
            "terminating_hash_committed_at_unix": self.committed_at,
            "salt": self.salt,
            "salt_source": self.salt_source,
            "salt_bound_at": _iso(self.salt_bound_at),
            "salt_bound_at_unix": self.salt_bound_at,
            "salt_revealed_at": _iso(self.salt_revealed_at),
            "order": (
                "unbound (commitment published, awaiting salt)"
                if self.salt is None
                else "salt_preexisting_reproducible_mode"
                if self._salt_preexisting
                else "terminating_hash_first"
            ),
            "fair_ordering": self.fair_ordering,
        }

    def bind_salt(
        self,
        salt: str,
        salt_source: Optional[str] = None,
        revealed_at: Optional[float] = None,
        _preexisting: bool = False,
    ) -> None:
        """Bind the public salt to the already-committed chain (one-time).

        ``revealed_at`` (unix time), when known, attests when the salt's
        source made it public; a value earlier than :attr:`committed_at`
        raises :class:`CommitmentOrderError`.  ``STAKE_SALT`` always raises
        (it was revealed 2019-07-21, before any chain generated by this
        code).
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

        ``salt=None`` (default) runs the honest two-phase protocol: commit
        the terminating hash first, then draw a fresh salt.  See
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
    salt_source: Optional[str] = None,
    progress: bool = True,
) -> Dict[str, object]:
    """N rounds of Stake's ACTUAL mechanism: a fresh salted hash chain of
    ``n_rounds + 1`` hashes, streamed in constant memory, played newest-first.

    Commitment ordering: with ``salt=None`` (default) the honest two-phase
    protocol is run in-process — (1) walk the chain once, salt-free, to
    COMMIT the terminating hash; (2) only then draw a fresh salt; (3) replay
    the chain with the HMAC applied.  The verification dict records both
    timestamps (``fair_ordering: True``).  A caller-supplied ``salt``
    (reproducible-simulation mode) provably existed before the chain, so a
    :class:`CommitmentOrderWarning` is emitted and the verification dict is
    marked ``fair_ordering: False``.  ``STAKE_SALT`` is always refused —
    it may only replay Stake's own published 2019 chain.

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
        # COMMIT first (salt-free walk), then draw the salt — honest order.
        committed_hash = _stream_chain_terminator(secret_seed, n_rounds, progress)
        committed_at = time.time()
        salt = secrets.token_hex(32)
        if salt_source is None:
            salt_source = "drawn after terminating-hash commitment"
        salt_bound_at = time.time()
        order = "terminating_hash_first"
        fair = True
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
    return _finish_multi(
        games, wins, n_rounds, elapsed,
        {
            "mechanism": "hash_chain",
            "terminating_hash": terminating,
            "salt": salt,
            "chain_length": n_rounds + 1,
            "commitment": {
                "terminating_hash": terminating,
                "terminating_hash_committed_at": _iso(committed_at),
                "terminating_hash_committed_at_unix": committed_at,
                "salt": salt,
                "salt_source": salt_source,
                "salt_bound_at": _iso(salt_bound_at),
                "salt_bound_at_unix": salt_bound_at,
                "order": order,
                "fair_ordering": fair,
            },
        },
    )
