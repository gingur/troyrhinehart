# SpinQuest MCP server

An [MCP](https://modelcontextprotocol.io) server (stdio transport, official
python SDK `FastMCP`) exposing the critic-verified `spinquest_sim` engines:
exact odds, provably-fair simulation, bankroll session tracking, honest
negative-EV bet sizing, HTML strategy reports and single-bet verification.

## Requirements

```bash
pip install "mcp<2"        # official python SDK (FastMCP lives in 1.x)
# plus the repo dependencies: numpy scipy pandas matplotlib
```

Run manually (from the repository root):

```bash
python -m mcp_server.server
```

## Client configuration

Claude Desktop / any stdio MCP client (`claude_desktop_config.json` or
equivalent):

```json
{
  "mcpServers": {
    "spinquest": {
      "command": "python3",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/path/to/casino",
      "env": { "SPINQUEST_HOME": "~/.spinquest_sim" }
    }
  }
}
```

`claude mcp add` form:

```bash
claude mcp add spinquest -- python3 -m mcp_server.server
# (run from the repository root, or set cwd/PYTHONPATH to it)
```

Session ledgers and reports are persisted under `$SPINQUEST_HOME`
(default `~/.spinquest_sim`): `sessions/<id>.jsonl` (append-only,
crash-safe, reload-safe) and `reports/<id>.html`.

## Tools

| tool | what it does |
| --- | --- |
| `list_games(bankroll?, bet?, rounds?, top?)` | all 412 playable configurations, RTP-ranked live from the engines (first call builds the analytic table, ~30–40 s, then cached) |
| `game_odds(game, config)` | exact analytic RTP / house edge / per-unit SD for one configuration |
| `simulate(game, n_rounds, config?, seed?)` | vectorized provably-fair simulation, `n_rounds` ≤ 10,000,000; with `seed` the campaign is deterministic and every row verifiable via `verify_bet` |
| `optimal_sizing(bankroll, game, goal, config?, target?, n_rounds?, min_bet?, max_bet?, bet_grid?)` | bold (`reach_target`) / timid (`survive_rounds`) sizing with exact evidence tables and honest negative-EV accounting |
| `session_start(starting_bankroll, stop_loss?, stop_win?, stop_loss_pct?, stop_win_pct?, ...)` | open an exact-cent bankroll ledger (JSONL-persisted) |
| `session_record_bet(session_id, game, stake, multiplier, config?, timestamp?)` | record one resolved bet (`multiplier` is total-return "for one": 0 lost, 1 push, 2 even-money win) |
| `session_status(session_id)` | full summary: P&L, drawdown episodes, per-game breakdown, stop state |
| `session_end(session_id)` | final summary + close the ledger handle (the file stays reloadable) |
| `strategy_report(session_id, title?)` | self-contained HTML tear sheet; returns the file path |
| `verify_bet(game, server_seed, client_seed, nonce, config?)` | replay one bet through the scalar provably-fair RNG (byte-exact port of Stake's published verifier) |

### Game configs

Same keys everywhere (`game_odds`, `simulate`, `optimal_sizing`,
`verify_bet`; an engine's own `config()` output round-trips too):

| game | config |
| --- | --- |
| `keno` | `{"picks": 1..10, "risk": "classic"\|"low"\|"medium"\|"high"}` |
| `plinko` | `{"rows": 8..16, "risk": "low"\|"medium"\|"high"}` |
| `mines` | `{"mines": 1..24, "picks": 1..(25-mines)}` |
| `wheel` | `{"segments": 10\|20\|30\|40\|50, "risk": "low"\|"medium"\|"high"}` |
| `roulette` | `{"bet_type": ..., "selection": ...}` (European; e.g. `{"bet_type": "red"}`, `{"bet_type": "straight", "selection": 17}`, `{"bet_type": "split", "selection": [17, 20]}`) |
| `baccarat` | `{"bet_type": "player"\|"banker"\|"tie"}` (optional `decks`, `tie_odds`) |
| `crash` | `{"target": >1 .. 1000000}` |
| `blackjack` | `{}` (optional `dealer_hits_soft_17`, `das`, `max_hands`, `bj_payout`) |
| `video_poker` | `{"paytable": "stake"\|"9/6"}` |
| `slots` | `{}` (the validated Atkins par-sheet model) |

`verify_bet` extras: keno `"selection"` (squares to mark), mines
`"reveal"` (tile order to reveal), video_poker `"holds"` (5 booleans;
omitted = optimal play). Crash verifies via the seed-pair mechanism.

### Honest limits

- Every engine has RTP < 1; `optimal_sizing` optimizes *distributional*
  goals only and says so in its output.
- `optimal_sizing` refuses blackjack (doubles/splits put extra money in
  play, so no flat-stake total-return distribution exists) and slots (no
  closed-form outcome distribution for the free-spin chain).
- `list_games` excludes Scarab Spin slots — its bonus-chain reconstruction
  is documented as under-determined; the validated slots model is Atkins.

All tool failures come back as MCP tool errors with a clear message; the
server never crashes on bad input and never writes to stdout (the protocol
channel).
