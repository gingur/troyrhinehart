# SpinQuest Session HUD

A Chrome (MV3) extension that unifies game data across the SpinQuest casino games
(**Plinko, Mines, Crash, Blackjack, Roulette**) into one consistent view:

- **A session per game** — rounds are grouped into per-game sessions, auto-rotated
  after 30 minutes of inactivity (or manually via the HUD's *new session* button).
- **Current deal** — the in-flight state of the round you're in: your blackjack
  hand and totals, mines revealed so far with the running multiplier, the crash
  multiplier as it climbs, pending bets.
- **History** — settled rounds (bet, multiplier, profit) plus shared outcomes the
  table produced even when you sat out: recent crash points, roulette numbers
  with hot/cold and color counts.
- **Session stats** — rounds, win rate, wagered, net, current streak, biggest
  win/loss, and per-game extras (median crash point / % under 2×, plinko
  multiplier average, mines cashouts vs. busts, blackjack W-L-P record).

Everything stays local: data lives in `chrome.storage.local` on your machine,
nothing is sent anywhere. The extension only observes traffic — it never
modifies requests or game behavior.

> One honest caveat: history describes what happened, not what happens next.
> These games are independent RNG rounds, so stats are for bankroll awareness
> (net, wagered, streaks), not outcome prediction.

## Install

1. Open `chrome://extensions`, enable **Developer mode**.
2. **Load unpacked** → select this `spinquest-extension/` directory.
3. Open a game on `spinquest.com` — the HUD appears top-right (draggable,
   collapsible). The toolbar popup shows all sessions and has JSON export.

## How it works

```
page (MAIN world)                 isolated world                 service worker
┌──────────────────┐   postMessage   ┌──────────────┐   runtime   ┌─────────────────┐
│ page-hook.js     │ ──────────────► │ content.js   │ ──────────► │ background.js   │
│ hooks fetch/XHR/ │                 │ + adapters/* │  messages   │ sessions, stats │
│ WebSocket (JSON) │                 │ normalize    │             │ storage.local   │
└──────────────────┘                 └──────┬───────┘             └────────┬────────┘
                                            │ overlay.js (HUD)  ◄──────────┘ broadcast
                                            │ popup/           ◄────────────
```

- `src/page-hook.js` mirrors every JSON payload (fetch, XHR, WebSocket frames,
  both directions) to the content script. Capture only, never mutation.
- `src/adapters/*.js` — one per game — translate raw payloads into three event
  types: `state` (current deal updates), `round` (a settled bet), and `tick`
  (shared outcomes like a crash point or roulette number). A `generic.js`
  fallback records any settled-looking bet on a known game page so the ledger
  stays complete even where the specific adapter misses.
- `src/lib/normalize.js` does heuristic field extraction (`bet`/`wager`/`stake`,
  `payout`/`win`, `multiplier`/`crashPoint`, …) so the adapters tolerate API
  shape differences, and derives the missing leg of bet × multiplier = payout.
- `src/background.js` owns the session model, computes stats, persists, and
  broadcasts snapshots to the HUD and popup.

## Refining the adapters against the real site

The adapters were written heuristically (the site's API isn't publicly
documented), so expect to tune them once against live traffic:

1. On a game page, click **raw** in the HUD header. That shows the recent
   captured payloads — transport, direction, URL path, and top-level JSON keys.
2. Find the payloads that carry bets/results, note their URL and key names.
3. In the matching `src/adapters/<game>.js`, extend `match()` (URL hints) and
   the key regexes in `parse()` / `src/lib/normalize.js` to cover them.
4. Reload the extension at `chrome://extensions` and refresh the game tab.

### Cross-frame games: what works and what doesn't

Capture runs in **every frame whose URL matches `*.spinquest.com`** (the
capture content scripts and the MAIN-world hook are injected with
`all_frames` + `match_about_blank`), so a game living in a same-site iframe is
captured; sub-frames that can't tell which game they host from their own URL
fall back to `document.referrer`. The HUD overlay itself only ever renders in
the top frame.

Honest limitations:

- **Cross-origin provider iframes are not captured.** If the game is served
  from a third-party origin (e.g. `games.provider.example`), the extension has
  no injection rights there. Grab the iframe's origin from DevTools and add it
  to both `host_permissions` and every `content_scripts[].matches` list in
  `manifest.json`, then reload — that is a manual, per-provider step.
- **Sandboxed frames without `allow-same-origin`** run with an opaque origin;
  content scripts may not be injected at all there, and nothing can fix that
  from the extension side.
- In a captured sub-frame the game-detection heuristic is weaker (frame URLs
  are often opaque provider paths); the referrer fallback covers the common
  "lobby page embeds /games/crash/ frame" case, but a wrongly-named frame
  path can still misattribute events to the wrong game. The raw view (HUD →
  **raw**) is the debugging tool for this.
- Events captured in sub-frames still reach the background (session data is
  correct), but the top frame's **raw** inspector only shows traffic from its
  own frame.

## Data model

```js
Session {
  id, game, startedAt, lastActivityAt, endedAt?,
  current: { phase, bet?, multiplier?, detail{...} } | null,  // the live deal
  rounds:  [{ id, ts, bet, payout, multiplier, profit, result, detail{...} }],
  ticks:   [{ ts, crashPoint? | number?, color? }],           // shared outcomes
  stats:   { rounds, wins, losses, pushes, winRate, wagered, returned, net,
             biggestWin, biggestLoss, streak, extra{...} }
}
```

Caps: 300 rounds per session, 100 ticks, 30 archived sessions — oldest dropped.

## Capture robustness

The pipeline is built to survive real-world payload chaos without ever
throwing into the page (the MAIN-world hook is fully guarded — a hostile
payload degrades to "not captured", never to a broken game):

- **Transports**: fetch (response clones, locked bodies, missing/`text/plain`
  content types sniffed), XHR (`''`/`text`/`json`/`arraybuffer`/`blob`
  responseTypes, throwing getters), WebSocket (text frames, socket.io-style
  prefixed frames like `42["event",{...}]` / `42/ns,17[...]`, binary
  ArrayBuffer/Blob frames).
- **Shapes**: GraphQL envelopes (`{data:{...}}`), nested money objects
  (`{bet:{amount,currency}}`), snake_case/camelCase, string-encoded numbers
  (`"1.23"`), arrays of results (history endpoints, autobet batches — one
  round per entry), epoch-seconds vs -ms timestamps.
- **Garbage guards**: big-int-ish strings stay exact ids and are never read
  as money; absurd magnitudes (≥1e12) are rejected; multiplayer bet boards
  (arrays whose entries carry usernames) are stripped so another player's bet
  can't become yours.
- **Dedupe**: byte-identical bodies within 400 ms (double listeners,
  fetch+XHR mirrors) collapse to one event; rounds dedupe on per-bet ids
  (trusted strong keys like `betId`; payload-constant weak ids like `gameId`
  get deterministic synthetic ids); shared-outcome ticks dedupe by per-round
  id when present, else "same content within 10 s is a rebroadcast".
  Known limitation: id-less single rounds with identical bodies more than
  400 ms apart are counted separately — indistinguishable from real repeats.

`dev/payloads/` holds an adversarial corpus (35 payload files, per game and
generic, each with its expected normalized output), and `dev/replay.mjs`
feeds every one through the real hook + adapter + normalize pipeline in plain
node:

```
node dev/replay.mjs          # whole corpus
node dev/replay.mjs crash    # filter by filename
node dev/model-test.mjs      # session/stats model tests
```

## Files

| Path | Role |
| --- | --- |
| `manifest.json` | MV3 manifest; script load order matters (adapters before `content.js`) |
| `src/page-hook.js` | MAIN-world network interceptor |
| `src/lib/util.js`, `src/lib/normalize.js` | shared helpers + heuristic field extraction |
| `src/adapters/{plinko,mines,crash,blackjack,roulette,generic}.js` | per-game normalization |
| `src/content.js` | capture pipeline, game detection, dedupe, raw log |
| `src/overlay.js` + `src/overlay.css` | in-page HUD |
| `src/background.js` | session store, stats, persistence, broadcast |
| `src/popup/` | toolbar popup: all sessions, export, clear |
| `dev/payloads/`, `dev/replay.mjs` | adversarial payload corpus + pipeline replay tests |
| `dev/model-test.mjs` | session/stats model tests (`src/lib/stats.js`) |
