from __future__ import annotations

NAVIGATION_ITEMS: tuple[str, ...] = (
    "Dashboard",
    "Library",
    "Collections",
    "People",
    "Disks",
    "Android Devices",
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
)

# User-facing groups for the sidebar. Page names remain stable so existing
# backend pages and deep links continue to work during migration.
NAVIGATION_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Photos", ("Dashboard", "Library", "Collections", "Favourites")),
    ("Explore", ("People", "Places", "Visual Duplicates")),
    ("Backup", ("Android Devices", "Backup Sets")),
    ("Storage", ("Disks", "Redundancy Audit", "Reconciliation", "Folder Safety Audit")),
    ("Activity", ("Operations", "Timeline")),
    ("Settings", ("Catalog Recovery", "Scan", "Copy Plans", "Quarantine")),
)
