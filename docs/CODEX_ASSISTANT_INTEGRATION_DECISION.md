# Codex Assistant Integration Decision

## Environment observed

- Codex CLI: `codex-cli 0.151.0-alpha.7.2`
- `codex mcp-server --help`: available
- `codex mcp --help`: external MCP registration commands available
- `codex app-server --help`: available, stdio transport supported
- PhotoVault OpenAI API key: none added or required

## Decision

Use Architecture A first: Codex calls the local PhotoVault MCP server over
stdio.

### Why

- Codex retains ownership of ChatGPT authentication.
- PhotoVault stays usable when Codex is unavailable.
- No localhost HTTP assistant endpoint or credential proxy is needed.
- Typed tools are easy to unit-test without real model inference.
- The same Python service can later support a web assistant or App Server.

Architecture B, embedding `codex app-server` inside PhotoVault, remains a
follow-up POC. It is not declared passed until thread creation, streaming,
approval handling, reconnect, and auth reuse are tested on the installed CLI.
