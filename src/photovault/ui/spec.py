from __future__ import annotations

NAVIGATION_ITEMS: tuple[str, ...] = (
    "Dashboard",
    "Library",
    "Import",
    "Review",
    "Events",
    "Event Detail",
    "Tags",
    "Sources",
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

# User-facing groups for the sidebar. Technical pages remain real stacked
# pages, but are reached through Advanced Tools rather than crowding the main
# navigation.
NAVIGATION_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Photos", ("Dashboard", "Library", "Timeline", "Import", "Review", "Events", "Collections", "Favourites")),
    ("Explore", ("People", "Places", "Categories", "Tags", "Sources", "Visual Duplicates")),
    ("Backup", ("Android Devices", "Backup Profiles")),
    ("Storage", ("Disks", "Backup Health", "Advanced Tools")),
    ("Activity", ("Operations",)),
    ("Settings", ("Settings",)),
)

ADVANCED_PAGE_ITEMS: tuple[str, ...] = (
    "Scan", "Redundancy Audit", "Reconciliation", "Folder Safety Audit",
    "Copy Plans", "Quarantine", "Catalog Recovery", "Backup Sets", "Event Detail",
)
