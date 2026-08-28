from __future__ import annotations

import math
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

EARTH_RADIUS_METERS = 6_371_000.0


def distance_meters(latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float) -> float:
    lat_a, lat_b = math.radians(latitude_a), math.radians(latitude_b)
    d_lat, d_lon = lat_b - lat_a, math.radians(longitude_b - longitude_a)
    value = math.sin(d_lat / 2) ** 2 + math.cos(lat_a) * math.cos(lat_b) * math.sin(d_lon / 2) ** 2
    return 2 * EARTH_RADIUS_METERS * math.asin(min(1.0, math.sqrt(value)))


class ReverseGeocoder(Protocol):
    def label(self, latitude: float, longitude: float) -> str | None: ...


class OfflineReverseGeocoder:
    """Safe default: coordinates are clustered without contacting a service."""
    def label(self, latitude: float, longitude: float) -> str | None:
        return None


@dataclass(frozen=True)
class PlaceCluster:
    id: str
    label: str | None
    latitude: float
    longitude: float
    radius_meters: float
    asset_ids: tuple[str, ...]


def cluster_places(connection: sqlite3.Connection, radius_meters: float = 100.0,
                   geocoder: ReverseGeocoder | None = None) -> list[PlaceCluster]:
    if radius_meters <= 0:
        raise ValueError("radius_meters must be positive")
    rows = list(connection.execute("SELECT asset_id, latitude, longitude FROM gps_metadata ORDER BY asset_id"))
    clusters: list[dict[str, object]] = []
    for row in rows:
        asset_id, latitude, longitude = row[0], float(row[1]), float(row[2])
        selected, selected_distance = None, float("inf")
        for cluster in clusters:
            distance = distance_meters(latitude, longitude, cluster["latitude"], cluster["longitude"])
            if distance <= radius_meters and distance < selected_distance:
                selected, selected_distance = cluster, distance
        if selected is None:
            selected = {"latitude": latitude, "longitude": longitude, "assets": [], "radius": 0.0}
            clusters.append(selected)
        assets = selected["assets"]
        assets.append((asset_id, latitude, longitude))
        count = len(assets)
        selected["latitude"] = sum(item[1] for item in assets) / count
        selected["longitude"] = sum(item[2] for item in assets) / count
        selected["radius"] = max(selected["radius"], distance_meters(latitude, longitude, selected["latitude"], selected["longitude"]))

    connection.execute("DELETE FROM place_clusters")
    result: list[PlaceCluster] = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    geocoder = geocoder or OfflineReverseGeocoder()
    for cluster in clusters:
        cluster_id = "place_" + uuid.uuid4().hex
        latitude, longitude = cluster["latitude"], cluster["longitude"]
        label = geocoder.label(latitude, longitude)
        connection.execute("INSERT INTO place_clusters(id, label, centroid_latitude, centroid_longitude, radius_meters, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                           (cluster_id, label, latitude, longitude, cluster["radius"], now))
        for asset_id, item_latitude, item_longitude in cluster["assets"]:
            connection.execute("INSERT INTO place_cluster_members(cluster_id, asset_id, distance_meters) VALUES (?, ?, ?)",
                               (cluster_id, asset_id, distance_meters(item_latitude, item_longitude, latitude, longitude)))
        result.append(PlaceCluster(cluster_id, label, latitude, longitude, cluster["radius"],
                                   tuple(item[0] for item in cluster["assets"])))
    connection.commit()
    return result
