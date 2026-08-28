from __future__ import annotations

import sqlite3


MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE volumes (
            id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            identity_kind TEXT NOT NULL,
            identity_value TEXT NOT NULL UNIQUE,
            filesystem TEXT,
            capacity_bytes INTEGER,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            current_mount_path TEXT,
            status TEXT NOT NULL DEFAULT 'OFFLINE'
                CHECK (status IN ('CONNECTED', 'OFFLINE'))
        );

        CREATE TABLE assets (
            id TEXT PRIMARY KEY,
            media_type TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE asset_locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
            volume_id TEXT NOT NULL REFERENCES volumes(id) ON DELETE CASCADE,
            relative_path TEXT NOT NULL,
            filename TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            modified_ns INTEGER NOT NULL,
            capture_date TEXT,
            scan_session_id TEXT,
            missing_since TEXT,
            UNIQUE(volume_id, relative_path)
        );

        CREATE TABLE scan_sessions (
            id TEXT PRIMARY KEY,
            volume_id TEXT NOT NULL REFERENCES volumes(id),
            root_path TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')),
            files_seen INTEGER NOT NULL DEFAULT 0,
            files_catalogued INTEGER NOT NULL DEFAULT 0,
            errors INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE scan_errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_session_id TEXT NOT NULL REFERENCES scan_sessions(id),
            path TEXT NOT NULL,
            error_type TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX idx_asset_locations_volume ON asset_locations(volume_id);
        CREATE INDEX idx_asset_locations_asset ON asset_locations(asset_id);
        CREATE INDEX idx_asset_locations_size ON asset_locations(size_bytes);
        CREATE INDEX idx_scan_sessions_volume ON scan_sessions(volume_id);
        """,
    ),
    (
        2,
        """
        CREATE TABLE exact_hashes (
            asset_id TEXT PRIMARY KEY REFERENCES assets(id) ON DELETE CASCADE,
            sha256 TEXT NOT NULL UNIQUE,
            byte_count INTEGER NOT NULL,
            hashed_at TEXT NOT NULL
        );
        CREATE INDEX idx_exact_hashes_sha256 ON exact_hashes(sha256);
        """,
    ),
    (
        3,
        """
        CREATE TABLE backup_sets (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            required_copies INTEGER NOT NULL CHECK (required_copies >= 1),
            scope TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE backup_set_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            backup_set_id TEXT NOT NULL REFERENCES backup_sets(id) ON DELETE CASCADE,
            volume_id TEXT NOT NULL REFERENCES volumes(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK (role IN ('PRIMARY', 'BACKUP')),
            relative_root TEXT NOT NULL DEFAULT '',
            UNIQUE(backup_set_id, volume_id),
            UNIQUE(backup_set_id, role, relative_root)
        );

        CREATE INDEX idx_backup_members_set ON backup_set_members(backup_set_id);
        CREATE INDEX idx_backup_members_volume ON backup_set_members(volume_id);
        """,
    ),
    (
        4,
        """
        CREATE TABLE operations (
            id TEXT PRIMARY KEY,
            operation_type TEXT NOT NULL,
            created_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            status TEXT NOT NULL CHECK (status IN ('PLANNED', 'RUNNING', 'COMPLETED', 'PARTIAL', 'FAILED')),
            dry_run INTEGER NOT NULL DEFAULT 0 CHECK (dry_run IN (0, 1)),
            details_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE operation_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation_id TEXT NOT NULL REFERENCES operations(id) ON DELETE CASCADE,
            asset_id TEXT,
            source_path TEXT,
            destination_path TEXT,
            expected_sha256 TEXT,
            result TEXT NOT NULL,
            verification_result TEXT,
            error_message TEXT
        );

        CREATE TABLE verification_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation_item_id INTEGER REFERENCES operation_items(id),
            asset_id TEXT REFERENCES assets(id),
            path TEXT NOT NULL,
            expected_sha256 TEXT NOT NULL,
            actual_sha256 TEXT,
            result TEXT NOT NULL,
            verified_at TEXT NOT NULL
        );

        CREATE INDEX idx_operations_status ON operations(status);
        CREATE INDEX idx_operation_items_operation ON operation_items(operation_id);
        CREATE INDEX idx_verification_history_asset ON verification_history(asset_id);
        """,
    ),
    (
        5,
        """
        CREATE TABLE media_metadata (
            asset_id TEXT PRIMARY KEY REFERENCES assets(id) ON DELETE CASCADE,
            capture_datetime TEXT,
            date_source TEXT,
            camera_make TEXT,
            camera_model TEXT,
            lens TEXT,
            orientation INTEGER,
            width INTEGER,
            height INTEGER,
            rating INTEGER,
            keywords_json TEXT NOT NULL DEFAULT '[]',
            extracted_at TEXT NOT NULL
        );

        CREATE TABLE gps_metadata (
            asset_id TEXT PRIMARY KEY REFERENCES assets(id) ON DELETE CASCADE,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            extracted_at TEXT NOT NULL
        );

        CREATE TABLE thumbnails (
            asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
            version TEXT NOT NULL,
            path TEXT NOT NULL,
            width INTEGER NOT NULL,
            height INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(asset_id, version)
        );

        CREATE INDEX idx_media_metadata_capture ON media_metadata(capture_datetime);
        CREATE INDEX idx_gps_metadata_coordinates ON gps_metadata(latitude, longitude);
        """,
    ),
    (
        6,
        """
        CREATE TABLE perceptual_hashes (
            asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
            algorithm TEXT NOT NULL CHECK (algorithm IN ('dhash64', 'phash64')),
            hash_value TEXT NOT NULL,
            bit_count INTEGER NOT NULL DEFAULT 64,
            computed_at TEXT NOT NULL,
            PRIMARY KEY(asset_id, algorithm)
        );
        CREATE INDEX idx_perceptual_hashes_lookup
            ON perceptual_hashes(algorithm, hash_value);

        CREATE TABLE duplicate_groups (
            id TEXT PRIMARY KEY,
            group_type TEXT NOT NULL CHECK (group_type IN ('REENCODED_COPY', 'NEAR_DUPLICATE')),
            algorithm TEXT NOT NULL CHECK (algorithm IN ('dhash64', 'phash64')),
            threshold INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE duplicate_group_members (
            group_id TEXT NOT NULL REFERENCES duplicate_groups(id) ON DELETE CASCADE,
            asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
            distance INTEGER NOT NULL,
            PRIMARY KEY(group_id, asset_id)
        );
        CREATE INDEX idx_duplicate_group_members_asset
            ON duplicate_group_members(asset_id);
        """,
    ),
    (
        7,
        """
        CREATE TABLE place_clusters (
            id TEXT PRIMARY KEY,
            label TEXT,
            centroid_latitude REAL NOT NULL,
            centroid_longitude REAL NOT NULL,
            radius_meters REAL NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE place_cluster_members (
            cluster_id TEXT NOT NULL REFERENCES place_clusters(id) ON DELETE CASCADE,
            asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
            distance_meters REAL NOT NULL,
            PRIMARY KEY(cluster_id, asset_id)
        );
        CREATE INDEX idx_place_cluster_members_asset ON place_cluster_members(asset_id);
        """,
    ),
    (
        8,
        """
        CREATE TABLE embeddings (
            asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
            model TEXT NOT NULL,
            vector_json TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            computed_at TEXT NOT NULL,
            PRIMARY KEY(asset_id, model)
        );
        CREATE INDEX idx_embeddings_model ON embeddings(model);
        """,
    ),
    (
        9,
        """
        CREATE TABLE source_profiles (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL UNIQUE,
            manufacturer TEXT NOT NULL,
            model TEXT NOT NULL,
            display_name TEXT NOT NULL,
            adapter TEXT NOT NULL,
            usb_vendor_id INTEGER,
            usb_product_id INTEGER,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL
        );

        CREATE TABLE source_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL REFERENCES source_profiles(source_id) ON DELETE CASCADE,
            object_id TEXT NOT NULL,
            logical_path TEXT NOT NULL,
            name TEXT NOT NULL,
            media_type TEXT NOT NULL,
            size_bytes INTEGER,
            created_at TEXT,
            modified_at TEXT,
            last_seen TEXT NOT NULL,
            UNIQUE(source_id, logical_path)
        );
        CREATE INDEX idx_source_items_source ON source_items(source_id);
        """,
    ),
]


def apply_migrations(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    applied = {
        row[0] for row in connection.execute("SELECT version FROM schema_migrations")
    }
    for version, sql in MIGRATIONS:
        if version in applied:
            continue
        connection.executescript(sql)
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, datetime('now'))",
            (version,),
        )
    connection.commit()
