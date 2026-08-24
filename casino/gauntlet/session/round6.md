# Gauntlet — piece `session` — adversarial review (round 2/3, written to round6.md)

Reviewer: independent critic, fresh eyes. The builder's `tests/test_session.py` (59 tests,
all green) was **not** trusted. Every number below comes from my own harness in
`/tmp/claude-0/-home-user-troyrhinehart/b3ce270f-e608-55a6-8515-5735b66f4ebe/scratchpad/s2/`:
`oracle.py`, `mults.py`, `a1_money.py`, `a1b_fuzz1m.py`, `a2_adversarial.py`,
`a3_tamper.py`, `a4_drawdown.py`, `a5_cash.py`, `a6_jsonl.py`, `a7_footing.py`,
`a8_longest.py`, `a9_blind.py`, `a10_final.py`.

**Oracle**: `oracle.py` — a from-scratch ledger in pure **integer cents** with payouts
rounded by exact `Fraction` half-up. It shares no code, no `Decimal`, no `quantize`, and no
rounding path with `spinquest_sim/session.py`. Its online drawdown tracker was itself
validated against a naive O(n²) `max_{i<j}(P_i−P_j)/P_i` scan (500 positive paths, 0
mismatches).

**Verdict: ours does NOT win.** Round 1's two blockers are genuinely, verifiably fixed and
the money arithmetic is audit-grade. The remaining gap has moved from *drawdown depth* to
*drawdown duration and ledger completeness*.

---

## 1. Round 1's blockers: FIXED, confirmed independently

| Round-1 blocker | Round-2 result |
|---|---|
| §2 `max_drawdown_pct` coupled to the dollar max | **fixed** — 1,200 random walks (1–400 bets, 6 starting bankrolls, ±negative bankrolls): **0/1200** mismatches on `max_drawdown`, `max_drawdown_pct`, `peak_bankroll`, `bankroll` vs the integer-cent oracle |
| non-monotone "max" (decreased 711×) | **fixed** — over 60,000 bets across 200 sessions, `max_drawdown` decreased **0** times, `max_drawdown_pct` decreased **0** times |
| the exact round-1 counterexample | **fixed** — 100 → 50 → 1000 → 940 now reports `max_drawdown 60.00`, `max_drawdown_pct 50.00%`, with `max_drawdown_peak=1000.00` and `max_drawdown_pct_peak=100.00` correctly *decoupled* |
| §3a torn-tail resume silently swallowed a committed bet | **fixed** — torn tails truncated at 5/20/60 bytes and torn-tail+`\n\n`: resume, +1 bet, reload → **no bet lost** in any case |
| §3b config validated with a different `json.dumps` than it is written with | **fixed** — `_canonical_config_json` uses the exact persist-time call, with a mixed-key-type fallback; `{1:"a","1":"b"}` now serializes before any state mutation |
| §4 `payout`/`net`/`seq` unauthenticated on replay | **fixed** — see the tamper matrix below |
| §5 `BetRecord` shallow-copied a mutable config | **fixed** — config is snapshotted as canonical JSON; `.config` returns a fresh dict |
| §6.1 raw `InvalidOperation` escaping `MoneyError` | **fixed** — `1e30`/`1e300` stake and multiplier all raise `MoneyError` |
| §6.2 negative zero on the ledger | **fixed** — `multiplier="-0.00"` stores `0`, payout `0.00` |
| §6.5 timestamps unvalidated | **partly fixed** — still stored verbatim (by design) but backwards/unparseable/tz-mixed now counted in `timestamp_anomalies` (verified: 3 anomalies from 1 backwards + 1 junk + 1 naive→aware; identical timestamps correctly *not* flagged) |
| §6.6 no deposit/withdrawal record | **fixed** — `deposit()`/`withdraw()` exist and are excluded from `pnl` (see §5 for what is still missing) |
| §6.7 raw 28-digit Decimal in `summary()` | **fixed** — `"46.67%"`, exact half-up |
| §6.3 two sessions on one file | **partly fixed** — see §4.2 |

## 2. Money arithmetic: audit-grade. Do not touch it.

| Check | Result |
|---|---|
| **1,000,000-op fuzz** (5×200k chained so the money stream is continuous), payouts vs `Fraction` half-up | **0 mismatches**; **34,628** exact-halfway (`.5`-cent) ties exercised |
| bankroll / staked / returned after 1M ops | exact match to integer cents (`1,956,309,399,665` cents) |
| `pnl == returned − staked` after 1M ops | exact |
| naive-float shadow ledger over the same 1M ops | **19,563,093,833.84** vs exact **19,563,093,996.65** — a **$162.81 drift** that `session.py` does not have |
| 27,328 payout checks over **all 976 numeric multipliers harvested from `references/*/*.md`** × 28 stakes (1,539 halfway ties) | **0 mismatches** |
| `bankroll_after` chain intact across 1M bets | yes |
| balance-sheet identity `end == start + deposits − withdrawals + returned − staked`, 500 mixed sessions | **0** failures |
| rejection matrix — zero / negative / sub-cent / NaN / inf / `bool` / `None` / `"abc"` / `1e30` stake; negative / NaN / inf / `bool` / non-numeric / `1e300` multiplier; overdraw | **20/20 `MoneyError`**, no state mutated (bankroll, `bets`, `per_game` all unchanged) |
| decimal context flags after 1M ops | only `Inexact`/`Rounded` (from the intended `quantize`) |
| peak RSS, 1M ops | 259 MB (under the 500 MB bar) |

The 0.1+0.2 class of bug is eliminated. This is the strongest part of the module.

## 3. JSONL: byte-exact, and now tamper-evident

- **20 trials × 250 records** with adversarial payloads (`♠♥♦♣`, emoji, RTL overrides, NUL and
  `\x1f`, embedded newlines/tabs/quotes/backslashes, 5,000-char strings, `10**18` and
  `-10**18`, `-0.0`, mixed int/str keys, 200-char game names, 9 timestamp shapes including
  junk): re-serializing every on-disk line with the canonical serializer is **SHA-256
  byte-identical** to the file, `load()` is idempotent, and every `BetRecord` field survives
  the round trip.
- `load()` leaves the file **byte-identical**; a subsequent append is a **pure suffix**.
- Multiplier spelling is canonical and stable: `1E+2`/`1e2`/`100.00`/`0100` → `100`;
  `2.500000` → `2.5`; `-0.00` → `0`.
- **Tamper matrix** (each on its own file — round 1's runner-up finding is closed):

| Tampered field | Detected? |
|---|---|
| `bet.bankroll_after`, `bet.payout`, `bet.net`, `bet.seq`, `bet.stake`, `bet.multiplier`, `bet.session_id` | **all rejected** |
| `stop.reason`, `stop.seq`, `stop.pnl`, `stop.bankroll` | **all rejected** |
| deleting any `bet` line | **rejected** |
| duplicating a `bet` line | **rejected** |
| deleting the `stop` line | accepted and **re-journalled** (documented) |
| header `stop_loss` edited to hide a latch | **rejected** |
| `bet.game` / `bet.config` / `bet.timestamp` | accepted — these are *replayed inputs*, so the loaded ledger mirrors the file and still foots. No money impact. |

- Two **different** sessions interleaved on one file now load correctly (last header wins,
  foreign `session_id`s skipped): verified `200.00 → 220.00`, 2 bets.

## 4. Adversarial sequences

### 4.1 Clean

- **Wins after a stop-loss trigger**: latch is sticky and first-trigger-wins. 3 losses latch
  `stop_loss` at seq 2; 50 subsequent 10× wins take P&L to +420.00 and the latch does not
  move, does not clear, and does not block recording (53 bets on the ledger). With
  `stop_loss` *and* `stop_win` both armed, a later stop-win does not overwrite the latched
  stop-loss. Boundary `pnl == -stop_loss` latches (`<=`).
- **Cash cannot launder a stop**: a 10,000 deposit after a latch leaves `pnl=-200.00`,
  `stopped=True`; a deposit *before* the loss does not suppress the percent stop.
- **Duplicate timestamps**: 5 identical timestamps produce 0 anomalies; empty string and
  `int` timestamps rejected.
- **Reload mid-session**: bankroll, pnl, peak, `max_drawdown`, `max_drawdown_pct`,
  `total_deposited`, `stopped`, and `session_id` all reproduce exactly across
  reload → play → reload, including across a mid-session deposit.
- **Performance, 100,000 bets with JSONL**: 32.0 s (320 µs/bet, fsync-dominated), 23.2 MB
  file; `load` 4.0 s reproducing the bankroll exactly; `to_dataframe()` 0.19 s;
  `summary()` 0.2 ms; peak RSS **137 MB**. Float export drift `df.net.sum()` vs `pnl`:
  **exactly 0** at 100k rows.

### 4.2 MODERATE — `Session.load()` clones the `session_id`, defeating the module's own
concurrency defence

The module's answer to two writers is `session_id` separation (`load` skips foreign ids).
But `load()` reuses the *same* id, so any two loaded handles are indistinguishable:

```
a = Session.load(p); b = Session.load(p)      # a.session_id == b.session_id -> True
a.record_bet(...); b.record_bet(...)
Session.load(p)  ->  ValueError: replay mismatch: persisted seq 2 != replayed seq 3
```

The file is then permanently unloadable (two `seq: 2` rows, both carrying the right id).
Same outcome if `load()` is called while the original writer is still open. There is no
advisory lock and no "this file already has a live writer" check. Fix: give a loaded session
a fresh `session_id` (journalling a `resume` record that links it to the previous id), or
take an `flock` on the append handle.

## 5. MAJOR — the exported ledger does not foot once cash moves

`to_dataframe()` exports **bets only**. Cash movements change `bankroll_after` but appear in
no column, so the only ledger the report layer receives has unexplained jumps:

```
 seq           timestamp    net  bankroll_after
   1 2026-03-01T10:00:00 -100.0           900.0
   2 2026-03-01T11:00:00 -100.0           800.0
   3 2026-03-01T12:00:00 -100.0          1200.0   <-- +500 deposit, unrecorded
   4 2026-03-01T13:00:00  100.0          1100.0   <-- -200 withdrawal, unrecorded
```

`bankroll_after[i] − bankroll_after[i−1] == net[i]` — the first thing an accountant checks —
fails at every cash flow, and nothing in the frame explains why.

Worse, the journal **cannot be reassembled in memory**: `CashRecord` has fields
`(kind, timestamp, amount, bankroll_after)` and **no sequence number**. Timestamps are
free-form caller strings that may be duplicated or unparseable, so with four identical
timestamps the order of two bets and two cash records is unrecoverable from the API. The
JSONL file has the true order; the object model throws it away.

Fix: give `CashRecord` a `seq` on the same counter as bets and expose one ordered
`ledger()` / `to_dataframe(include_cash=True)`.

## 6. BLOCKER — drawdown **duration** statistics are wrong, and `summary()` contradicts itself

`longest_drawdown_bets` / `longest_drawdown_days` are only updated inside
`_finalize_episode` (`session.py:729-733`), which runs **only on recovery**. A drawdown that
is still open when the session ends never contributes — and in a negative-EV game that is
almost always the deepest and longest one. **99%** of realistic sessions I generated end with
an unrecovered episode.

Minimal hand-auditable case (all numbers exact, `references`-plausible multipliers):

```
2026-03-01  -100 @ 0     1000.00 -> 900.00
2026-03-03  -100 @ 3      900.00 -> 1100.00   (new peak, earlier dd recovered)
2026-03-04  -400 @ 0     1100.00 -> 700.00
2026-03-05 .. 2026-03-30   26 pushes, bankroll flat at 700.00
```

Truth: underwater from the 2026-03-03 peak to the last bet on 2026-03-30 — **27 bets,
27 days**, never recovered, 36.36% deep.

`summary()` reports:

```
drawdown.longest_days : null
drawdown.longest_bets : 2
drawdown.worst[0]     : start 2026-03-03  recovered null  36.36%  days 1.0  bets 1
```

Two separate errors compound:

1. the open 27-bet / 27-day episode is excluded from `longest_*` entirely; and
2. the open episode's own `days`/`bets` are measured **peak → trough**, not **peak → last
   observation** — so even the row that *is* printed says `days 1.0` for a drawdown that has
   been running for 27 days. (The reference sheet closes an unrecovered drawdown at the last
   observation: its final row is `2026-07-13 → 2026-08-21, −10.10, 40` days.)

Measured, against a clean independent longest-underwater-run tracker:

- **509/600 (85%)** of realistic sessions **understate** Longest DD; worst gap **200 bets**
  (i.e. the entire session).
- **150/600 (25%)** report `longest_bets = 0` while genuinely underwater.
- **401/515 (78%)** of sessions have `summary()` **self-contradict**: the headline
  `Longest DD Days` is `null` or *smaller* than a row printed in its own
  `drawdown.worst` table, on the same page.
- **31%** report `Longest DD Days = null` outright; **48%** emit at least one
  worst-drawdowns row with `Days = null`.

`Longest DD Days` is row 17 of the 79-row reference bar. A report built on this object prints
a number that its own supporting table refutes.

## 7. MAJOR — cash flows corrupt the percentage-drawdown story

`_record_cash` shifts `peak_bankroll` and `_trough` by the transfer amount. That preserves
the *dollar* drawdown but rewrites the *percentage*, and the docstring's promise that a
transfer "neither erases nor fabricates a drawdown" does not hold in percent terms.

**A withdrawal fabricates a percent drawdown out of nothing** (hand audit):

```
1000.00  -100 @ 0  ->  900.00      max_dd 100.00   max_dd%  10.00%
         withdraw 850.00 ->  50.00 (peak shifted 1000.00 -> 150.00)
          10.00 @ 1  (a PUSH)      max_dd 100.00   max_dd%  66.67%   <-- no money lost
```

A break-even bet after a cash-out drives the headline max drawdown from 10.00% to 66.67%.

**A deposit shrinks a live drawdown and orphans the headline**:

```
1000.00  -500 @ 0 -> 500.00        headline max_dd% = 50.00%
         deposit 1000.00 -> 1500.00 (peak 2000.00)
          500.00 @ 3 -> 2500.00     episode recorded as from_peak 2000.00, dd 500.00, 25.00%
```

`summary()` then reports `max_drawdown_pct = 50.00%` while the **only** row of its
worst-drawdowns table says `25.00%`. Randomized: in **217/400 (54%)** of sessions containing
cash flows the headline max-percent drawdown appears in **no row** of the worst-drawdowns
table. (Without cash flows, 400/400 walks reconcile perfectly — this failure mode is entirely
introduced by the baseline shift.)

Related: a withdrawal can drive `peak_bankroll` to **≤ 0** (`Session("100.00",
allow_negative_bankroll=True).withdraw("500.00")` → peak `-400.00`), after which
`max_drawdown_pct` silently reports `0.00%` while the bankroll keeps falling.

## 8. MODERATE / MINOR

| # | Finding | Evidence |
|---|---|---|
| 8.1 | **`Avg. Drawdown` and `Avg. Drawdown Days` (reference rows 65-66) are uncomputable downstream.** `_WORST_EPISODES_KEPT = 32` discards every other episode and no episode count or running sum is exposed. 400 bets producing ~200 episodes → `drawdown_episodes()` returns 32, with no indication that 168 were dropped | `a10_final.py` §2 |
| 8.2 | **`Max DD Period End` (reference row 16) is not in `summary()`.** `drawdown.max_pct` carries only `from_peak / pct / start_seq / start_at / trough_seq / trough_at` — no recovery date. It is recoverable only by matching the episode inside the *capped* worst table | `a10_final.py` §3 |
| 8.3 | **The session has no start timestamp.** The constructor takes none and the `session_start` header records none, so any episode rooted at the opening peak has `start_at = null` and `days = null`. That is **10–13%** of realistic sessions reporting `Max DD Period Start = null`, and it is *always* the first episode | `a4_drawdown.py` §H, `a5_cash.py` §5 |
| 8.4 | `drawdown_episodes()` sorts by percent depth only, so the **max-dollar** episode can fall outside `worst_drawdowns(10)` while `summary()["max_drawdown"]` still cites it | code read, `session.py:763` |
| 8.5 | An accepted bet can have a non-zero multiplier and a `0.00` payout (`1.00 × 0.000001`), and is then classified a *loss* in `per_game`. Correct rounding, but the `wins/pushes/losses` split is a rounding artifact at sub-cent multipliers | `a6_jsonl.py` §3 |
| 8.6 | `total_staked` / `total_returned` are recomputed by summing `per_game` on **every** property access; `record_bet` reads neither, but `summary()` and any per-bet caller pay O(#games) each time | code read, `session.py:472-477` |

## 9. Blind comparison

Same 30-bet, 25-day hand-play session (blackjack / keno / roulette / crash / wheel / slots /
baccarat, published multipliers only, $800 start). Rows are the reference tear sheet's
drawdown block. One block is `spinquest_sim.session`; one is the hand audit. Labels stripped.

```
                                          ⟨A⟩                  ⟨B⟩
  --------------------------------------------------------------------
  Max Drawdown                        -27.28%              -27.28%
  Max Drawdown ($)                     403.00               403.00
  Max DD Date                      2026-03-26           2026-03-26
  Max DD Period Start              2026-03-05           2026-03-05
  Max DD Period End                2026-03-26                 null   <<<
  Longest DD Days                          21                    3   <<<
  Avg. Drawdown                       -12.49%         not reported   <<<
  Avg. Drawdown Days                        8         not reported   <<<

  Worst Drawdowns  ⟨A⟩                    Worst Drawdowns  ⟨B⟩
  Started    Recovered   Drawdown Days    Started    Recovered  Drawdown Days
  2026-03-05 2026-03-26   -27.28%   21    2026-03-05 null        -27.28%   21
  2026-03-02 2026-03-05    -7.16%    3    2026-03-02 2026-03-05   -7.16%    3
  2026-03-02 2026-03-02    -3.03%    0    2026-03-02 2026-03-02   -3.03%    0

  ending bankroll  1074.50 / 1074.50      peak  1477.50 / 1477.50
```

**An expert can tell, and does not even need ⟨A⟩ to do it.** ⟨B⟩ is the imitation. Every
dollar figure, the max drawdown percent, the max-DD date and the period start are now
identical — round 1's tell is gone. But ⟨B⟩ prints `Longest DD Days: 3` **directly above its
own table showing a 21-day drawdown**. A single glance down the page refutes the headline.
`Max DD Period End: null` on a sheet whose format guarantees a date, and two blank rows where
the bar has `Avg. Drawdown` / `Avg. Drawdown Days`, confirm it. This is not a coin flip; it
favours ⟨A⟩.

The tell needs no adversarial input: it is the *normal* shape of a negative-EV session — end
below the running peak — which is why the headline contradicts its own table in 78% of
sessions.

## 10. Verdict

- `ours_wins`: **false**
- `payout_match`: **true** — every number sourced from the references reproduces exactly:
  27,328 checks over all 976 harvested published multipliers × 28 stakes, 0 mismatches;
  1,000,000-op fuzz vs an exact-rational half-up oracle, 0 mismatches, 34,628 halfway ties;
  balance-sheet identity holds in 500/500 mixed sessions. The money arithmetic is audit-grade
  and should not be touched.
- `stats_pass`: **false** — drawdown *depth* now passes exactly (0/1200 walk mismatches, 0
  monotonicity violations, headline reconciles with the episode table in 400/400 cash-free
  walks). Drawdown *duration* fails: `Longest DD` is understated in 509/600 (85%) of sessions
  against an independent tracker and `summary()` self-contradicts in 401/515 (78%). These are
  definitional/completeness errors, not sampling noise, so the 3-SE band does not apply.

### Biggest remaining gap (one)

**Drawdown-duration statistics ignore the drawdown that is still open at session end.**
`longest_drawdown_bets` / `longest_drawdown_days` are updated only in `_finalize_episode`,
which runs only on recovery, and the open episode's own `days`/`bets` are measured peak→trough
rather than peak→last observation. 99% of realistic sessions end underwater, so the module
understates Longest DD in 85% of them (worst gap: the entire 200-bet session), reports it as
`null` in 31%, and prints a headline that its own worst-drawdowns table refutes in 78% — the
one line that gives the ledger away in the blind comparison against reference row 17.

Fix: close the open episode at the last recorded event when reporting (as the reference sheet
does), fold it into `longest_*`, and measure an open episode's span peak→last-observation.

*Runners-up, in order:* §7 (a withdrawal plus a break-even bet inflates max drawdown from
10% to 67%; the headline percent is unreconcilable with the episode table in 54% of
cash-flow sessions), §5 (`to_dataframe()` does not foot across cash flows and `CashRecord`
has no `seq`, so the ordered journal is unrecoverable in memory), §4.2 (`load()` clones the
`session_id`, so two loads brick the file).
