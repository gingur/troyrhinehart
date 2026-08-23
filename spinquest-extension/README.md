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

If nothing at all appears in the raw view on a game that's clearly making
requests, the game may run inside a cross-origin `<iframe>` (a third-party game
provider). Grab the iframe's origin from DevTools and add it to both
`host_permissions` and the `content_scripts[].matches` lists in
`manifest.json`, then reload.

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
