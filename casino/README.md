# spinquest_sim

An offline casino simulation stack for studying game odds, bet sizing, and session outcomes without touching a real casino. It reproduces a Stake-style provably-fair HMAC-SHA256 RNG so simulated results match verifiable on-site outcomes, and layers a harness, selector, sizing, session, and reporting pipeline on top for large-scale offline experiments. An optional MCP server exposes the simulator to agent tooling.

```
casino/
├── pyproject.toml
├── README.md
├── spinquest_sim/
│   ├── __init__.py
│   ├── rng.py          # provably-fair HMAC-SHA256 RNG
│   ├── harness.py      # simulation harness
│   ├── selector.py     # game/bet selector
│   ├── sizing.py       # bet sizing strategies
│   ├── session.py      # session/bankroll state
│   ├── report.py       # reporting
│   └── games/
│       └── __init__.py
├── mcp_server/
│   └── __init__.py
└── tests/
    └── __init__.py
```
