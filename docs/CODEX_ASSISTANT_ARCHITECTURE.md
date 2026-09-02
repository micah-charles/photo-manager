# PhotoVault Codex Assistant Architecture

PhotoVault exposes a local, credential-free MCP server. Codex owns model access
and authentication; PhotoVault never reads, stores, logs, or proxies an OpenAI
API key.

## Current flow

```text
Codex
  -> stdio JSON-RPC MCP server
  -> PhotoVaultToolService
  -> existing catalog services
  -> SQLite catalog
```

Start it with:

```bash
PYTHONPATH=src python3 -m photovault.cli --catalog /path/to/catalog.db \
  mcp-server --catalog /path/to/catalog.db
```

The server is stdio-only. It does not listen on the LAN and does not expose
filesystem or shell tools.

## Current tools

Read-only tools include `library_summary`, `search_photos`,
`summarize_date_range`, `list_topics`, `list_places`, `list_tags`,
`list_people`, and `get_photo`. `organize_trip_plan` creates a deterministic
preview only. It reports affected counts and `physical_file_changes: 0`; it
does not write the catalog or media files.

Search and summary responses are bounded. Search is capped at 200 items and
date summaries return per-day aggregates, so the full catalog is not sent to a
model by default.

## Safety boundary

PhotoVault remains the authority for validation and execution. The current
slice deliberately has no apply-plan tool. Future logical writes must use a
persisted plan, explicit approval, a transaction, audit history, and undo data.
Physical moves/deletes must remain separate higher-risk tools and must never be
part of normal topic, place, or tag operations.

## App Server option

The installed Codex CLI exposes `codex app-server`, but this sprint does not
embed it into the PhotoVault web process. That would add a second lifecycle and
approval/reconnect surface. The MCP server is the first integration because it
lets the existing authenticated Codex process call typed local tools without
duplicating authentication.
