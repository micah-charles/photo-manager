from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any

from photovault.catalog.library import LibraryQuery, count_library_items, list_library_items
from photovault.catalog.organization import list_events, list_places, list_tags
from photovault.catalog.people import list_people
from photovault.database.connection import connect
from photovault.backup.jobs import BackupJobManager
from photovault.sources.android_wifi import AndroidCompanionWifiSource


class PhotoVaultToolService:
    """Small semantic facade over existing catalog services.

    This service never receives credentials and never mutates originals.  The
    initial Codex integration exposes reads and proposal generation only.
    """

    def __init__(self, catalog: Path | str):
        self.catalog = Path(catalog).expanduser().resolve()
        self.backup_jobs = BackupJobManager(self.catalog)

    @contextmanager
    def _db(self):
        db = connect(self.catalog)
        try:
            yield db
        finally:
            db.close()

    @staticmethod
    def _item(row) -> dict[str, Any]:
        return {
            "asset_id": str(row["asset_id"]), "filename": row["filename"],
            "media_type": row["media_type"], "relative_path": row["relative_path"],
            "size_bytes": row["size_bytes"], "captured": row["display_captured"] or row["captured"],
            "source": row["source_name"], "places": row["place_names"] or row["inherited_place_names"],
            "topics": row["event_names"], "tags": row["tag_names"], "review_status": row["review_status"],
        }

    def library_summary(self) -> dict[str, Any]:
        with self._db() as db:
            total = count_library_items(db, LibraryQuery(limit=1))
            row = db.execute("SELECT COALESCE(SUM(size_bytes), 0) FROM asset_locations WHERE missing_since IS NULL").fetchone()
            return {"catalog": str(self.catalog), "asset_count": total, "total_bytes": int(row[0] or 0)}

    def search_photos(self, **kwargs: Any) -> dict[str, Any]:
        allowed = {"search", "captured_from", "captured_to", "captured_month", "source_id", "event_id", "tag_id", "place_id", "person_id", "category", "review_status", "min_rating", "media_type", "asset_ids"}
        values = {key: value for key, value in kwargs.items() if key in allowed and value not in (None, "")}
        limit = min(max(int(kwargs.get("limit", 50)), 1), 200)
        query = LibraryQuery(**values, limit=limit, sort="captured_desc_id")
        with self._db() as db:
            rows = list_library_items(db, query)
            return {"total": count_library_items(db, query), "items": [self._item(row) for row in rows], "limit": limit}

    def summarize_date_range(self, date_from: str, date_to: str) -> dict[str, Any]:
        date.fromisoformat(date_from); date.fromisoformat(date_to)
        result = self.search_photos(captured_from=date_from, captured_to=date_to, limit=200)
        days: dict[str, dict[str, Any]] = defaultdict(lambda: {"asset_count": 0, "bytes": 0, "sources": set(), "places": set()})
        for item in result["items"]:
            day = str(item.get("captured") or "Undated")[:10]
            entry = days[day]; entry["asset_count"] += 1; entry["bytes"] += int(item.get("size_bytes") or 0)
            if item.get("source"): entry["sources"].add(item["source"])
            if item.get("places"): entry["places"].update(str(item["places"]).split(", "))
        return {"date_from": date_from, "date_to": date_to, "asset_count": result["total"], "days": [{"day": day, "asset_count": data["asset_count"], "bytes": data["bytes"], "sources": sorted(data["sources"]), "places": sorted(data["places"])} for day, data in sorted(days.items())]}

    def list_topics(self) -> list[dict[str, Any]]:
        with self._db() as db:
            return [{"id": e.id, "name": e.name, "start_datetime": e.start_datetime, "end_datetime": e.end_datetime, "item_count": e.item_count} for e in list_events(db)]

    def list_places(self) -> list[dict[str, Any]]:
        with self._db() as db:
            return [{"id": p.id, "name": p.name, "item_count": p.item_count} for p in list_places(db)]

    def list_tags(self) -> list[dict[str, Any]]:
        with self._db() as db:
            return [{"id": t.id, "name": t.name, "item_count": t.item_count} for t in list_tags(db)]

    def list_people(self) -> list[dict[str, Any]]:
        with self._db() as db:
            return [{"id": p.id, "name": p.display_name, "item_count": p.item_count} for p in list_people(db)]

    def get_photo(self, asset_id: str) -> dict[str, Any]:
        result = self.search_photos(asset_ids=(asset_id,), limit=1)
        if not result["items"]:
            raise ValueError(f"unknown asset: {asset_id}")
        return result["items"][0]

    def organize_trip_plan(self, name: str, date_from: str, date_to: str, day_places: dict[str, str] | None = None) -> dict[str, Any]:
        summary = self.summarize_date_range(date_from, date_to)
        operations = [{"type": "create_topic", "name": name, "start_date": date_from, "end_date": date_to}]
        for day in summary["days"]:
            place = (day_places or {}).get(day["day"])
            if place:
                operations.append({"type": "assign_place", "day": day["day"], "place": place, "asset_count": day["asset_count"]})
        return {"plan_id": f"plan_preview_{date_from}_{date_to}", "summary": summary, "operations": operations, "physical_file_changes": 0, "requires_approval": True, "status": "PREVIEW_ONLY"}

    def create_backup_job(self, **kwargs: Any) -> dict[str, Any]:
        return self.backup_jobs.create(**kwargs).payload()

    def start_backup_job(self, job_id: str) -> dict[str, Any]:
        return self.backup_jobs.start(job_id).payload()

    def backup_status(self, job_id: str) -> dict[str, Any]:
        return self.backup_jobs.get(job_id).payload()

    def cancel_backup_job(self, job_id: str) -> dict[str, Any]:
        return self.backup_jobs.cancel(job_id).payload()

    def inspect_android_source(self, url: str, token: str) -> dict[str, Any]:
        source = AndroidCompanionWifiSource(url, token)
        device = source.device_details()
        return {"device": device, "folders": [folder.__dict__ for folder in source.folders()]}
