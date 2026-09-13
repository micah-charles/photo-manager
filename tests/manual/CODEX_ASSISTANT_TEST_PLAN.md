# Codex Assistant Manual Test Plan

These tests require the user to register the local MCP command in their Codex
configuration. Do not record tokens or inspect credential files.

1. Ask Codex: “How many photos are in my PhotoVault catalog? Do not change anything.”
   Expected: it calls `library_summary`; catalog and files are unchanged.
2. Ask for counts between two dates.
   Expected: it calls `summarize_date_range` and returns per-day aggregates.
3. Ask for a Scotland trip proposal for 22–23 August.
   Expected: it calls `organize_trip_plan`, returns `PREVIEW_ONLY`, and states
   physical file changes are zero.
4. Verify no write tool is offered by `tools/list`.
5. Run the same tests with Codex unavailable. PhotoVault web UI must still work.

The real Codex MCP registration and ChatGPT-authenticated end-to-end call are
not marked PASS by automated tests in this repository.
