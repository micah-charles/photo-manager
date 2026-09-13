from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .service import PhotoVaultToolService


TOOLS = [
    ("library_summary", "Summarize the catalog without returning all assets.", {}),
    ("search_photos", "Search catalogued photos using dates, source, topic, place, tag, person, category, rating or review filters.", {"limit": {"type": "integer", "maximum": 200}}),
    ("summarize_date_range", "Return per-day counts, bytes, source and place hints for a date range.", {"date_from": {"type": "string"}, "date_to": {"type": "string"}}),
    ("list_topics", "List logical PhotoVault topics.", {}),
    ("list_places", "List catalogued places.", {}),
    ("list_tags", "List catalogued tags.", {}),
    ("list_people", "List catalogued people groups.", {}),
    ("get_photo", "Inspect one catalogued asset by stable asset ID.", {"asset_id": {"type": "string"}}),
    ("organize_trip_plan", "Create a read-only logical organization proposal. It never changes the catalog or files.", {"name": {"type": "string"}, "date_from": {"type": "string"}, "date_to": {"type": "string"}, "day_places": {"type": "object"}}),
    ("inspect_android_source", "Read a Companion device identity and folder summary without downloading files.", {"url": {"type": "string"}, "token": {"type": "string"}}),
    ("create_backup_job", "Create a persisted-in-process backup job plan; it does not start copying. Use session_token and android_fingerprint from secure Android pairing when available; otherwise use the legacy phone token.", {"url": {"type": "string"}, "token": {"type": "string"}, "session_token": {"type": "string"}, "android_fingerprint": {"type": "string"}, "folders": {"type": "array"}, "destination": {"type": "string"}, "workers": {"type": "integer", "minimum": 1, "maximum": 8}}),
    ("start_backup_job", "Start an explicitly requested verified Android backup job.", {"job_id": {"type": "string"}}),
    ("backup_status", "Return bounded progress and interval throughput for a backup job.", {"job_id": {"type": "string"}}),
    ("cancel_backup_job", "Request cancellation of a running backup job; resumable files are retained.", {"job_id": {"type": "string"}}),
]


def schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "additionalProperties": True}


def result(value: Any) -> dict[str, Any]:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return {"content": [{"type": "text", "text": text}], "structuredContent": value}


def run(catalog: Path) -> None:
    service = PhotoVaultToolService(catalog)
    for raw in sys.stdin:
        try:
            request = json.loads(raw)
            method = request.get("method")
            if method == "initialize":
                response = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "photo-manager", "version": "0.1"}}
            elif method == "notifications/initialized":
                continue
            elif method == "tools/list":
                response = {"tools": [{"name": name, "description": description, "inputSchema": schema(properties)} for name, description, properties in TOOLS]}
            elif method == "tools/call":
                name = request.get("params", {}).get("name")
                arguments = request.get("params", {}).get("arguments", {})
                if name == "search_photos": value = service.search_photos(**arguments)
                elif name == "summarize_date_range": value = service.summarize_date_range(**arguments)
                elif name == "organize_trip_plan": value = service.organize_trip_plan(**arguments)
                elif name == "inspect_android_source": value = service.inspect_android_source(**arguments)
                elif name == "create_backup_job": value = service.create_backup_job(**arguments)
                elif name == "start_backup_job": value = service.start_backup_job(**arguments)
                elif name == "backup_status": value = service.backup_status(**arguments)
                elif name == "cancel_backup_job": value = service.cancel_backup_job(**arguments)
                elif name == "get_photo": value = service.get_photo(**arguments)
                elif name == "library_summary": value = service.library_summary()
                elif name == "list_topics": value = service.list_topics()
                elif name == "list_places": value = service.list_places()
                elif name == "list_tags": value = service.list_tags()
                elif name == "list_people": value = service.list_people()
                else: raise ValueError(f"unknown tool: {name}")
                response = result(value)
            else:
                continue
            if "id" in request:
                sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": response}, ensure_ascii=False) + "\n")
                sys.stdout.flush()
        except Exception as exc:  # protocol errors must remain JSON, never crash the server
            if "id" in locals().get("request", {}):
                sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": request["id"], "error": {"code": -32000, "message": str(exc)}}) + "\n")
                sys.stdout.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description="PhotoVault local MCP server for Codex")
    parser.add_argument("--catalog", type=Path, required=True)
    args = parser.parse_args()
    run(args.catalog)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
