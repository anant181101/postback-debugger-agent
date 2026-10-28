# Postback Debugger Agent

An AI agent that explains why a postback to an ad network failed.

Given a click ID, the agent inspects click, install, event and postback logs through tools and
diagnoses the failure: install not attributed, event not mapped, partner endpoint returned
4xx/5xx, timeout, missing macro, duplicate, or outside the attribution window.

All data in this project is synthetic.

## Interfaces

- MCP server (works with Claude Desktop and Claude Code)
- Standalone agent client
- Web UI with a live timeline of agent steps

## Repository layout

```
backend/    Python: data, tools, agent, MCP server, API, evals
frontend/   React + TypeScript + Vite
```

## Status

Work in progress.

## License

MIT
