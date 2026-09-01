from __future__ import annotations

NAVIGATION_ITEMS: tuple[str, ...] = (
    "Dashboard",
    "Library",
    "Photo Viewer",
    "Collections",
    "People",
    "Disks",
    "Android Devices",
    "Backup Profiles",
    "Backup Sets",
    "Scan",
    "Redundancy Audit",
    "Reconciliation",
    "Folder Safety Audit",
    "Copy Plans",
    "Quarantine",
    "Operations",
    "Catalog Recovery",
    "Timeline",
    "Favourites",
    "Visual Duplicates",
    "Places",
    "Categories",
    "Backup Health",
    "Advanced Tools",
    "Settings",
)

# User-facing groups for the sidebar. Page names remain stable so existing
# backend pages and deep links continue to work during migration.
NAVIGATION_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Photos", ("Dashboard", "Library", "Photo Viewer", "Collections", "Favourites")),
    ("Explore", ("People", "Places", "Categories", "Visual Duplicates")),
    ("Backup", ("Android Devices", "Backup Profiles", "Backup Sets")),
    ("Storage", ("Disks", "Backup Health", "Redundancy Audit", "Reconciliation", "Folder Safety Audit")),
    ("Activity", ("Operations", "Timeline")),
    ("Settings", ("Settings", "Advanced Tools", "Catalog Recovery", "Scan", "Copy Plans", "Quarantine")),
)
