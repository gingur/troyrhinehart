# Gauntlet — piece `session` — adversarial review (round 1/3, written to round5.md per brief)

Reviewer: independent critic, fresh eyes. Builder's `tests/test_session.py` (36 tests, all
green) was **not** trusted; every claim below comes from my own harness in
`/tmp/claude-0/-home-user-troyrhinehart/b3ce270f-e608-55a6-8515-5735b66f4ebe/scratchpad/sess/`
(`refledger.py`, `attack1.py`, `attack2.py`, `attack3.py`, `attack4.py`, `blind.py`).

**Oracle**: `refledger.py` — a from-scratch ledger in pure **integer cents** with payouts
rounded via `Fraction` (exact rational × exact half-up), so it shares no code, no `Decimal`,
and no rounding path with `spinquest_sim/session.py`.

**Verdict: ours does NOT win.** The money arithmetic is genuinely excellent and should not be
touched. The *ledger integrity* and the *drawdown metric* are not at an audit bar.

---

## 1. What is genuinely strong (do not regress)

| Check | Result |
|---|---|
| 1,000,000-bet fuzz, payout vs `Fraction` half-up oracle | **0 mismatches**; 105,496 exact-halfway (`.5` cent) cases hit |
| Ending bankroll / total staked / total returned after 1M bets | exact match to integer-cent oracle |
| `pnl == total_returned - total_staked` after 1M bets | exact |
| `bankroll_after` chain (`b[i] == b[i-1] + net[i]`) over 1M bets | intact |
| 12,950 payout checks over **all 518 distinct published multipliers** harvested from `references/*/*.md` × 25 stakes | **0 mismatches** |
| bankroll / peak / **absolute** max drawdown / stop reason / stop seq vs oracle, 400 random walks | **400/400 exact** |
| JSONL byte-exact round-trip (500-bet randomized session: unicode, escapes, nested configs, 1e18 ints, `1E+2` multipliers) | **byte-identical** after `load()` → rewrite |
| Stop-loss latch: sticky, first-trigger-wins, non-blocking (50 wins recorded after trigger) | correct |
| Rejection of zero / negative / sub-cent stake, negative multiplier, NaN, inf, `bool` | all `MoneyError`, no state mutated |

The 0.1+0.2 class of bug is genuinely eliminated, and I can quantify it: replaying the same
1M-bet stream through a naive float ledger lands at **-3,279,666.96** vs the exact
**-3,279,140.92** — a **$526.04 drift**. `session.py` has none of it.

`decimal` context flags after 1M ops: only `Inexact`/`Rounded` (from the intended
`quantize`); no `Overflow`, `Clamped`, or `InvalidOperation` in normal operation.

---

## 2. BLOCKER — `max_drawdown_pct` is not the maximum drawdown percent

`session.py:341-346` only recomputes the percentage **when the absolute drawdown sets a new
record**:

```python
drawdown = self.peak_bankroll - self.bankroll
if drawdown > self.max_drawdown:
    self.max_drawdown = drawdown
    self.max_drawdown_pct = drawdown / self.peak_bankroll   # <-- coupled to the $ max
```

So the reported percentage is *"the percentage of whichever drawdown was largest in dollars"*,
which is a different statistic from *"the largest percentage drawdown"*. Once the bankroll
grows, a small later dip that is bigger in dollars **overwrites** an earlier, far deeper
percentage — the "max" goes **down**.

Minimal hand-auditable counterexample:

```
100.00 --(-50)--> 50.00     max_dd = 50.00   max_dd_pct = 0.5   (50.00%)  correct
 50.00 --(+950)--> 1000.00  (new peak)
1000.00 --(-60)--> 940.00   max_dd = 60.00   max_dd_pct = 0.06  ( 6.00%)  <-- WRONG
```

True max drawdown percent for that path is 50.00%. The module reports 6.00%.

Measured over **1000 realistic sessions** (bankroll never allowed negative, stakes capped at
10% of start, real published multipliers):

- `max_drawdown_pct` is **wrong in 975 / 1000 = 97.5%** of sessions
- understatement: **median 3.76 pp, p90 12.65 pp, worst 34.38 pp**
- across 400 mixed random walks, the value **decreased** 711 separate times

This also misses the reference bar directly. `references/quantstats/reference_tearsheet.html`
reports **Max Drawdown as a percentage** (`-13.69%` / `-14.93%`) and it is the headline risk
row (item 13 of 79 in `metrics_inventory.md`). A report built on this session object prints
the wrong number for the single most-cited risk metric on the sheet.

Fix: track `max_drawdown_pct` independently of `max_drawdown` — evaluate
`dd / peak` on **every** bet and keep its own running max (my `refledger.py` does exactly this
in 4 lines).

---

## 3. BLOCKER — two independent paths permanently brick the ledger file, one silently losing money

### 3a. Torn-tail resume concatenates onto the torn line and **silently swallows the next bet**

`load()` correctly ignores an unparseable final line (crash mid-append) — but it does not
**truncate** it, and the session then keeps appending to the same handle. Because the torn
line has no trailing `\n`, the next append is glued onto it:

```
{"type":"bet","seq":2,"ga{"bankroll_after":"120.00","config":{},...,"seq":2,...,"type":"bet"}
```

Reproduced in `attack1.py` (A6):

```
in-memory session after resume : 2 bets, bankroll 120.00
Session.load(same file)        : 1 bet,  bankroll 110.00     <-- no error raised
```

A fully settled, `fsync`-ed bet **disappears from the ledger with no error and no warning**,
because the merged line is once again "the final line" and is therefore ignored again. One
more bet after that and the merged line is mid-file, so `load()` raises
`corrupt JSONL at line N` — the file is unloadable forever.

For an append-only ledger, silently dropping a committed entry is the worst available failure
mode. Fix: on load, `truncate()` the file to the end of the last good line (or write a
leading `\n` guard before the next append).

### 3b. Config validation and config serialization use different `json.dumps` calls

`session.py:312` validates with `json.dumps(cfg)`; `session.py:479` writes with
`json.dumps(obj, sort_keys=True, ...)`. A config with **mixed key types** passes validation
and fails at write time:

```
raised: TypeError -> '<' not supported between instances of 'str' and 'int'
in-memory bets: 2   bankroll: 100.00
on-disk bet lines: 1
```

The bankroll, `self.bets`, `per_game`, and the stop evaluation have all already been mutated
(`self.bankroll += net` at line 319 precedes `_append_line` at line 335), so this directly
violates the module's own comment at line 310, *"Fail fast (before mutating state) if the
config can't be persisted."* Memory and disk diverge, the session keeps running, and the next
reload raises permanently:

```
ValueError: replay mismatch at seq 2: replayed bankroll 100.00 != persisted 90.00
```

Fix: validate with the **exact** call used to persist (`json.dumps(cfg, sort_keys=True,
separators=(",", ":"))`), and catch `TypeError` from `_append_line` — or serialize the line
before mutating any state.

---

## 4. MAJOR — replay verifies only `bankroll_after`; the rest of each row is unauthenticated

`load()` recomputes `payout`/`net` from `stake × multiplier` and checks only
`bankroll_after`. Tamper results (`attack1.py` A7):

| Field tampered | Detected? |
|---|---|
| `bankroll_after` `110.00 → 999.00` | **rejected** |
| `payout` `20.00 → 777.00` | **accepted silently** |
| `net` `10.00 → 777.00` | **accepted silently** |
| `seq` `1 → 42` | **accepted silently** |

After a tampered load, the file on disk says `payout: 777.00` while the loaded ledger says
`20.00`, with no error. An accountant reconciling the journal against the reloaded balances
would find rows that do not foot, and the loader raised nothing.

Related (`D5`): the stop latch is not part of the audit trail. Editing `stop_loss` in the
header from `20.00` to `90.00` makes an already-latched stop **vanish** on reload
(`stopped` went `True → False`). A latched stop is a session event and should be journalled,
not re-derived from an editable parameter.

Fix: verify `payout`, `net`, and `seq` against the persisted values on replay (the data is
already there); journal a `stop` record when the latch fires.

---

## 5. MAJOR — `BetRecord` is not immutable; config is shallow-copied

`cfg = dict(config)` (line 309) is a shallow copy. The caller retains a live reference to
every nested value, and `BetRecord.config` is itself a mutable `dict` on a `frozen=True`
dataclass:

```python
cfg = {"picks": [1, 2, 3]}
r = s.record_bet("keno", cfg, 1, 0, TS)
cfg["picks"].append(99)
r.config          # -> {'picks': [1, 2, 3, 99]}    the recorded ledger row changed
r.config["injected"] = True   # accepted; s.bets[0].config now carries it
```

The file already has the original value, so this is a third route to memory/disk divergence.
Fix: `copy.deepcopy` (or store the canonical JSON string and expose a parsed copy).

---

## 6. MODERATE and MINOR

| # | Finding | Evidence |
|---|---|---|
| 6.1 | **Uncaught `decimal.InvalidOperation`** escapes the `MoneyError` contract for magnitudes ≳1e27: `stake=1e30`, `stake="1e30"`, `multiplier="1e30"`, `Session("1e30")` all raise raw `InvalidOperation` from `quantize` | `attack1.py` A3, 4/5 cases |
| 6.2 | **Negative zero on the ledger.** `multiplier="-0.00"` is accepted (correct, `-0.00 == 0`) but writes `"payout":"-0.00"` to the JSONL. `_money_str` does not normalize `-0` | `attack3.py` B2 |
| 6.3 | **Two live sessions on one file corrupt it.** No locking or advisory check; interleaved appends produce two `seq: 1` rows and `load()` then raises `replay mismatch at seq 1` permanently. The design explicitly contemplates several headers per file (`test_multiple_headers_last_session_wins`), so this is reachable | `D3` |
| 6.4 | **Torn tail + trailing blank line is not recognized as "final"** — only one trailing `""` is popped, so a crash that leaves `...torn\n\n` raises `corrupt JSONL at line 3` instead of being ignored | `D2` |
| 6.5 | **Timestamps entirely unvalidated**: `"not a timestamp at all"`, `"\t\n\"weird\\"`, and a 2020 timestamp after a 2026 one are all accepted; no monotonicity check and no parsed datetime is retained | `attack1.py` A4 |
| 6.6 | **No deposit/withdrawal record type.** The `allow_negative_bankroll` docstring cites "tracking a bankroll the human is willing to reload", but no operation records a reload — cash-in/cash-out is unrepresentable, so `bankroll` stops meaning the account balance the moment a human tops up | `D4`, API surface is `record_bet` only |
| 6.7 | `summary()["max_drawdown_pct"]` serializes as `'0.3333333333333333333333333333'` (raw 28-digit `Decimal`). Reference bar prints `-13.69%` | `D1` |
| 6.8 | **No drawdown dates, durations, or episodes.** The reference sheet requires Max DD Date, DD Period Start/End, Longest DD Days, and a Worst-10-Drawdowns table (Started / Recovered / Drawdown / Days). The session stores timestamps only as opaque strings, so none of it is derivable downstream | `metrics_inventory.md` items 13-17, 65-66, table 2 |
| 6.9 | Config key types are not preserved: `{1: "a"}` → `{"1": "a"}` after reload, so `s.bets != loaded.bets` for such configs (byte-exactness of the *file* is unaffected) | `attack3.py` B3 |

## 7. Performance (acceptable — not a headline gap)

| Path | Result |
|---|---|
| 1,000,000 bets, in memory | 18.9 s (**19 µs/bet**) |
| 100,000 bets **with** JSONL | 48.5 s (**485 µs/bet**), 18.8 MB file |
| `Session.load` of that 100k file | 2.0 s, bankroll reproduces exactly |
| `to_dataframe()` 100k rows | 0.4 s |
| `summary()` | 0.1 ms |
| RSS, 100k-bet session | 157 MB (222 MB after `to_dataframe`) — under the 500 MB bar |

I/O breakdown at 20k lines: reopen+fsync 238 µs, held-handle+fsync 201 µs, held+flush 1 µs.
So **199 µs/bet is `fsync`** — a defensible durability choice for a ledger — and only
**37 µs/bet is the needless `open`/`close` per append**. Keep the fsync; hold the handle.

Float export sanity: `df["net"].sum()` matched `float(s.pnl)` to 0.0 at 100k rows, so the
documented float-export caveat is not currently biting.

---

## 8. Blind comparison

Two ledgers over the **same 22 settled bets** of a realistic $500 hand-play session (blackjack
/ keno / crash / wheel / slots, published multipliers, bankroll never negative), labels
stripped. One is `spinquest_sim.session`, one is the hand-audited integer-cent ledger.

```
LEDGER  ⟨A⟩                                     LEDGER  ⟨B⟩
------------------------------------------------------------------------------------------
  Starting bankroll                500.00         Starting bankroll                500.00
  Ending bankroll                  860.00         Ending bankroll                  860.00
  Net P&L                          360.00         Net P&L                          360.00
  Total staked                   1,040.00         Total staked                   1,040.00
  Total returned                 1,400.00         Total returned                 1,400.00
  Hold / edge on turnover         34.62%          Hold / edge on turnover         34.62%
  Bets settled                         22         Bets settled                         22
  Peak bankroll                  1,230.00         Peak bankroll                  1,230.00
  Max drawdown ($)                 370.00         Max drawdown ($)                 370.00
  Max drawdown (%)                46.67%          Max drawdown (%)                30.08%  <<<
  ...measured from a peak of     1,230.00         ...measured from a peak of     1,230.00
------------------------------------------------------------------------------------------
```

Hand audit of the same 22 rows:

```
   from peak   trough $   depth %      bets
      525.00     245.00    46.67%     2-11
    1,230.00     370.00    30.08%    13-22
```

**An expert can tell, and it takes one line.** ⟨B⟩ is the imitation. Every dollar figure is
identical — but ⟨B⟩'s max-$ and max-% drawdown are forced to come from the *same* episode
(`370.00 / 0.3008 = 1,230.00`, the final peak), which is the signature of the coupling bug.
A reviewer who reads the bet rows sees the bankroll fall from $525 to $245 — a 46.67% hole,
and 51% below the starting bankroll — and immediately flags a "worst drawdown 30.08%" as not
footing. This is not a coin flip; it favours ⟨A⟩.

Note the tell needs no adversarial input at all: a small early bleed followed by a big
multiplier and a later dollar-larger bleed is the *normal* shape of a slots/crash session,
which is why the metric is wrong in 97.5% of sessions.

---

## 9. Verdict

- `ours_wins`: **false**
- `payout_match`: **true** — every number sourced from the references reproduces exactly
  (all 518 published multipliers × 25 stakes = 12,950 payout checks, 0 mismatches; 1M-op fuzz,
  0 mismatches). The money arithmetic is audit-grade.
- `stats_pass`: **false** — the drawdown-percent check against the independent oracle fails in
  975/1000 realistic sessions. This is a definitional error, not a sampling-noise question, so
  the 3-SE band does not apply; it is simply the wrong statistic. All other empirical checks
  are exact.

### Biggest remaining gap (one)

**`max_drawdown_pct` computes the percentage of the largest *dollar* drawdown instead of the
largest *percentage* drawdown.** It is wrong in 97.5% of realistic sessions, understates the
worst drawdown by up to 34 percentage points, is non-monotone (a "max" that decreases 711
times across 400 walks), contradicts the reference tear sheet's percent-based Max Drawdown,
and is the single line that gives the ledger away in the blind comparison.

*Runner-up, and more dangerous per occurrence:* §3a — a torn-tail resume silently deletes a
committed, `fsync`-ed bet from the persisted ledger with no error, then bricks the file.
Fix both before round 2.
