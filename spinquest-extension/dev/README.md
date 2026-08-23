# Dev / critique harness

Open `dev/mock-page.html` in any browser (or `mock-popup.html` for the toolbar
popup) — `chrome-stub.js` fakes the extension APIs so the real, unmodified
`src/overlay.js` / `src/popup/popup.js` run on a fake casino page, and
`fixtures.js` provides deterministic snapshots for every game and state
(inject one via the bottom-right picker, `?fixture=<name>`, or
`window.__SQX_INJECT(state, rawLog)` in the console). For screenshots:
`node dev/shot.mjs crash-mid-deal out/shot.png` writes the full page plus a
tight `out/shot-hud.png` crop of the HUD, and `node dev/shot.mjs all out/`
renders every fixture (popup fixtures are the ones named `popup-*`; needs
`playwright-core` — `cd dev && npm install` — and the Chromium at
`/opt/pw-browsers/chromium`). To compare two renders blind,
`node dev/blindpair.mjs a.png b.png out/` copies them to
`candidate-A.png`/`candidate-B.png` with the A/B assignment derived from the
file contents and records the truth in `mapping.json` — critique A vs B first,
peek at the mapping only after the verdict is written.
