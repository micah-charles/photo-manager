from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    from PIL import ExifTags, Image
except ImportError:  # pragma: no cover - optional dependency path
    ExifTags = None
    Image = None


@dataclass(frozen=True)
class MetadataRecord:
    capture_datetime: str | None = None
    date_source: str | None = None
    camera_make: str | None = None
    camera_model: str | None = None
    lens: str | None = None
    orientation: int | None = None
    width: int | None = None
    height: int | None = None
    rating: int | None = None
    keywords: tuple[str, ...] = ()
    latitude: float | None = None
    longitude: float | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _date_value(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    value = raw.strip().replace("/", ":")
    if len(value) >= 19 and value[4] == ":" and value[7] == ":":
        return value[:19].replace(":", "-", 2).replace(" ", "T")
    return None


def _coordinate(value: object) -> float | None:
    try:
        if isinstance(value, (tuple, list)) and len(value) == 3:
            return float(value[0]) + float(value[1]) / 60 + float(value[2]) / 3600
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _image_metadata(path: Path) -> MetadataRecord:
    if Image is None:
        return MetadataRecord()
    with Image.open(path) as image:
        exif = image.getexif()
        values = {ExifTags.TAGS.get(key, key): value for key, value in exif.items()} if ExifTags else {}
        capture = _date_value(values.get("DateTimeOriginal")) or _date_value(values.get("DateTimeDigitized")) or _date_value(values.get("DateTime"))
        source = "exif" if capture else None
        latitude = longitude = None
        gps = exif.get(34853)
        # Some real-world files contain a malformed GPS pointer/value instead
        # of the expected nested EXIF mapping. Treat that field as unavailable;
        # one damaged tag must not abort a whole read-only library scan.
        if hasattr(gps, "items"):
            gps_values = {ExifTags.GPSTAGS.get(key, key): value for key, value in gps.items()} if ExifTags else {}
            latitude = _coordinate(gps_values.get("GPSLatitude"))
            longitude = _coordinate(gps_values.get("GPSLongitude"))
            latitude_ref = gps_values.get("GPSLatitudeRef", "N")
            longitude_ref = gps_values.get("GPSLongitudeRef", "E")
            if isinstance(latitude_ref, bytes):
                latitude_ref = latitude_ref.decode("ascii", errors="ignore")
            if isinstance(longitude_ref, bytes):
                longitude_ref = longitude_ref.decode("ascii", errors="ignore")
            if latitude is not None and str(latitude_ref).upper() == "S":
                latitude = -latitude
            if longitude is not None and str(longitude_ref).upper() == "W":
                longitude = -longitude
        keywords = values.get("XPKeywords") or values.get("Keywords") or ()
        if isinstance(keywords, bytes):
            keywords = keywords.decode("utf-16le", errors="ignore")
        if isinstance(keywords, str):
            keywords = tuple(item.strip() for item in keywords.replace(";", ",").split(",") if item.strip())
        elif isinstance(keywords, (tuple, list)):
            keywords = tuple(str(item) for item in keywords)
        else:
            keywords = ()
        return MetadataRecord(
            capture_datetime=capture,
            date_source=source,
            camera_make=str(values["Make"]) if values.get("Make") else None,
            camera_model=str(values["Model"]) if values.get("Model") else None,
            lens=str(values["LensModel"]) if values.get("LensModel") else None,
            orientation=int(values["Orientation"]) if values.get("Orientation") is not None else None,
            width=image.width,
            height=image.height,
            rating=int(values["Rating"]) if values.get("Rating") is not None else None,
            keywords=keywords,
            latitude=latitude,
            longitude=longitude,
        )


def _video_metadata(path: Path) -> MetadataRecord:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return MetadataRecord()
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, check=True,
        )
        payload = json.loads(result.stdout)
        fmt = payload.get("format", {})
        tags = fmt.get("tags", {})
        streams = payload.get("streams", [])
        video = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
        capture = tags.get("creation_time")
        return MetadataRecord(
            capture_datetime=capture[:19] if isinstance(capture, str) else None,
            date_source="video_metadata" if capture else None,
            width=video.get("width"), height=video.get("height"),
        )
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
        return MetadataRecord()


def extract_metadata(path: Path) -> MetadataRecord:
    try:
        if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".heic", ".heif", ".tif", ".tiff", ".webp", ".cr2", ".cr3", ".nef", ".arw", ".dng", ".raf", ".orf", ".rw2"}:
            return _image_metadata(path)
        if path.suffix.lower() in {".mov", ".mp4", ".m4v", ".avi"}:
            return _video_metadata(path)
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return MetadataRecord()


def store_metadata(connection, asset_id: str, record: MetadataRecord) -> None:
    connection.execute(
        """
        INSERT INTO media_metadata(asset_id, capture_datetime, date_source, camera_make, camera_model,
                                   lens, orientation, width, height, rating, keywords_json, extracted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(asset_id) DO UPDATE SET capture_datetime=excluded.capture_datetime,
          date_source=excluded.date_source, camera_make=excluded.camera_make,
          camera_model=excluded.camera_model, lens=excluded.lens, orientation=excluded.orientation,
          width=excluded.width, height=excluded.height, rating=excluded.rating,
          keywords_json=excluded.keywords_json, extracted_at=excluded.extracted_at
        """,
        (asset_id, record.capture_datetime, record.date_source, record.camera_make, record.camera_model,
         record.lens, record.orientation, record.width, record.height, record.rating,
         json.dumps(record.keywords, ensure_ascii=False), _utc_now()),
    )
    if record.latitude is not None and record.longitude is not None:
        connection.execute(
            "INSERT INTO gps_metadata(asset_id, latitude, longitude, extracted_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(asset_id) DO UPDATE SET latitude=excluded.latitude, longitude=excluded.longitude, extracted_at=excluded.extracted_at",
            (asset_id, record.latitude, record.longitude, _utc_now()),
        )
