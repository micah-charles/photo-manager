"""File-backed collage Projects and deterministic A4 storyboard generation.

Projects deliberately sit above CollageDocument v2.  A project keeps the
source section and the current editable document together, so regenerating or
editing a page never changes the photo catalog or the original files.
"""
from __future__ import annotations

import json
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .design_formats import to_collage_document, validate_design_spec


PROJECT_ID_PREFIX = "project_"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _root(catalog_path: Path) -> Path:
    return catalog_path.parent / "collage-projects"


def _path(catalog_path: Path, project_id: str) -> Path:
    return _root(catalog_path) / f"{project_id}.json"


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def read_project(catalog_path: Path, project_id: str) -> dict[str, Any] | None:
    path = _path(catalog_path, project_id)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) and value.get("project_id") == project_id else None


def list_projects(catalog_path: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in _root(catalog_path).glob("project_*.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(value, dict) and str(value.get("project_id", "")).startswith(PROJECT_ID_PREFIX):
            result.append({
                "project_id": value["project_id"],
                "name": value.get("name", "Untitled project"),
                "description": value.get("description", ""),
                "document_count": len(value.get("documents", [])),
                "created_at": value.get("created_at"),
                "updated_at": value.get("updated_at"),
            })
    return sorted(result, key=lambda item: str(item.get("updated_at") or ""), reverse=True)


def create_project(catalog_path: Path, name: str, description: str = "") -> dict[str, Any]:
    clean = " ".join(str(name).strip().split())
    if not clean:
        raise ValueError("project name is required")
    now = _now()
    project = {
        "project_id": PROJECT_ID_PREFIX + uuid.uuid4().hex,
        "name": clean,
        "description": str(description or "").strip(),
        "created_at": now,
        "updated_at": now,
        "generation": {"format": "PhotoManager A4 Collage Guidance", "schema_version": 1},
        "documents": [],
    }
    _write(_path(catalog_path, project["project_id"]), project)
    return project


def save_project(catalog_path: Path, project: dict[str, Any]) -> dict[str, Any]:
    project["updated_at"] = _now()
    _write(_path(catalog_path, str(project["project_id"])), project)
    return project


def _pick_indices(asset_ids: list[str], indices: list[int], fallback_start: int) -> list[str]:
    picked: list[str] = []
    for index in indices:
        position = int(index) - 1
        if 0 <= position < len(asset_ids) and asset_ids[position] not in picked:
            picked.append(asset_ids[position])
    if not picked and asset_ids:
        picked.append(asset_ids[min(fallback_start, len(asset_ids) - 1)])
    return picked


def _advice_for(section: dict[str, Any], guidance: dict[str, Any]) -> dict[str, Any]:
    advice = guidance.get(str(section.get("title")), {})
    return advice if isinstance(advice, dict) else {}


def _archetype(section: dict[str, Any], advice: dict[str, Any]) -> str:
    explicit = str(advice.get("layout_archetype") or "").strip().lower()
    if explicit:
        return explicit
    title = str(section.get("title") or "").lower()
    if "flower" in title:
        return "detail_mosaic"
    if "cathedral" in title or "church" in title or "penrhyn castle 0" in title:
        return "architecture_journey"
    if "cable car" in title or "railway" in title or "on the way" in title:
        return "sequence_journey"
    if "group" in title or "mum" in title or "micah" in title:
        return "family_memory"
    if any(word in title for word in ("summit", "mountatin", "mountain", "valley", "snowdonia")):
        return "scenic_hero"
    return "travel_scrapbook"


def _composition_variant(archetype: str, advice: dict[str, Any], album_context: dict[str, Any] | None) -> str:
    """Choose a repeatable variation without turning layouts into random noise.

    A section can opt into a named variant, otherwise the album position cycles
    through a small set of art-directed alternatives.  The cycle is deliberately
    local to each archetype, so repeated visits to the same kind of place still
    feel related while adjacent pages do not become clones.
    """
    explicit = str(advice.get("composition_variant") or "").strip().lower()
    if explicit:
        return explicit
    variants = {
        "architecture_journey": ("hero_left", "hero_right", "spine"),
        "scenic_hero": ("wide_open", "hero_right", "panorama_then_portraits"),
        "sequence_journey": ("journey", "filmstrip", "stepped"),
        "family_memory": ("hero_left", "hero_right", "group_grid"),
        "portrait_editorial": ("portrait_left", "portrait_right"),
        "detail_mosaic": ("mosaic", "anchors_left", "three_beats"),
        "travel_scrapbook": ("hero_left", "hero_right", "stacked"),
    }
    choices = variants.get(archetype, variants["travel_scrapbook"])
    index = int((album_context or {}).get("index", 0) or 0)
    previous = str((album_context or {}).get("previous_archetype") or "")
    if previous == archetype:
        index += 1
    return choices[index % len(choices)]


def _role_ids(asset_ids: list[str], advice: dict[str, Any]) -> dict[str, list[str]]:
    """Turn editorial index hints into one dominant hero plus all remaining assets.

    The old generator treated every item in ``hero_indices`` as a large hero.  The
    guidance is now interpreted as a preference order: one dominant hero, then a
    complementary subhero, then supporting/detail material.  No asset is dropped.
    """
    dominant = _pick_indices(asset_ids, list(advice.get("dominant_indices") or advice.get("hero_indices") or [1]), 0)
    dominant = dominant[:1]
    subhero = _pick_indices(asset_ids, list(advice.get("subhero_indices") or []), 1)
    if not subhero:
        subhero = _pick_indices(asset_ids, list(advice.get("hero_indices") or [2]), 1)
    subhero = [item for item in subhero if item not in dominant][:2]
    supporting = _pick_indices(asset_ids, list(advice.get("supporting_indices") or []), 2)
    supporting = [item for item in supporting if item not in dominant and item not in subhero]
    detail = _pick_indices(asset_ids, list(advice.get("detail_indices") or []), 0)
    detail = [item for item in detail if item not in dominant and item not in subhero and item not in supporting]
    remaining = [item for item in asset_ids if item not in dominant and item not in subhero and item not in supporting and item not in detail]
    # Explicit alternates are still rendered, but in the lower sequence/contact area.
    alternates = _pick_indices(asset_ids, list(advice.get("alternate_indices") or []), 0)
    alternates = [item for item in alternates if item not in dominant and item not in subhero and item not in supporting and item not in detail]
    remaining = alternates + [item for item in remaining if item not in alternates]
    return {"dominant": dominant, "subhero": subhero, "supporting": supporting, "detail": detail, "remaining": remaining}


def _contact_slots(count: int, y: float, height: float, style: str = "grid") -> list[tuple[float, float, float, float]]:
    if count <= 0:
        return []
    # A single remaining photo is still required, but it must not suddenly
    # become a second hero just because it is the last item in the list.
    # Keep it as a small closing vignette with intentional breathing room.
    if count == 1:
        return [(76, y, 58, min(38.0, height))]
    if count <= 2:
        columns = count
        max_cell_height = 42.0
    elif count <= 6:
        columns = min(3, count)
        max_cell_height = 38.0
    else:
        if style == "filmstrip":
            columns = min(7, max(1, (count + 1) // 2))
            max_cell_height = 31.0
        elif style == "staggered":
            columns = min(5, max(1, (count + 2) // 3))
            max_cell_height = 30.0
        else:
            columns = min(6, max(1, (count + 1) // 2))
            max_cell_height = 27.0
    if count >= 8 and style == "grid":
        # Five columns keeps the last row balanced for the common 8–12 photo
        # case. Six columns made the lower story read like an inventory wall.
        columns = 5
    rows = (count + columns - 1) // columns
    gap = 3.0
    cell_height = min(max_cell_height, (height - gap * (rows - 1)) / rows)
    slots: list[tuple[float, float, float, float]] = []
    for row in range(rows):
        offset = 0.0
        if style == "staggered" and row % 2:
            offset = 4.0
        row_width = 182 - offset
        width = (row_width - gap * (columns - 1)) / columns
        for column in range(columns):
            slots.append((14 + offset + column * (width + gap), y + row * (cell_height + gap), width, cell_height))
    return slots[:count]


def _adaptive_editorial_layout(
    archetype: str,
    variant: str,
    asset_count: int,
) -> tuple[list[tuple[float, float, float, float, str, str]], float, float, str] | None:
    """Use more editorial slots before falling back to the all-assets gallery.

    The old layouts reserved only four or five slots, so a 10–12 photo section
    pushed most of its story into a tiny contact sheet.  These layouts preserve
    the same visual grammar but promote more content-specific images into
    readable supporting/detail frames.  The final gallery still receives every
    remaining asset, so this is a hierarchy change, never a filtering change.
    """
    if asset_count < 6:
        return None

    hero_right = variant in {"hero_right", "spine"}
    if archetype == "detail_mosaic":
        top = [
            (14, 45, 88, 70, "hero", "rectangle"),
            (108, 45, 88, 70, "secondary", "rectangle"),
        ]
    elif hero_right:
        top = [
            (14, 45, 58, 70, "secondary", "rounded"),
            (76, 45, 120, 70, "hero", "rectangle"),
        ]
    else:
        top = [
            (14, 45, 120, 70, "hero", "rectangle"),
            (138, 45, 58, 70, "secondary", "rounded"),
        ]

    if asset_count == 6:
        # Six photos are enough for a complete story, so do not leave the
        # sixth image as a lonely centred afterthought below the grid.
        slots = top + [
            (14, 128, 43, 57, "supporting", "rectangle"),
            (60, 128, 43, 57, "detail", "rectangle"),
            (106, 128, 43, 57, "detail", "rectangle"),
            (152, 128, 44, 57, "detail", "rectangle"),
        ]
        return slots, 191, 75, "grid"

    if asset_count == 10:
        # Ten photos should also resolve to a complete story grid.  Leaving
        # one asset for the gallery creates a singleton that reads like an
        # accidental leftover rather than an intentional closing beat.
        slots = top + [
            # Keep a second guided sub-hero in the editorial flow instead of
            # allowing it to fall through into a one-photo gallery.
            (14, 121, 58, 39, "secondary", "rectangle"),
            (76, 121, 58, 39, "supporting", "rectangle"),
            (138, 121, 58, 39, "detail", "rectangle"),
            (14, 166, 33, 34, "detail", "rectangle"),
            (50, 166, 33, 34, "detail", "rectangle"),
            (86, 166, 33, 34, "detail", "rectangle"),
            (122, 166, 33, 34, "detail", "rectangle"),
            (158, 166, 38, 34, "detail", "rectangle"),
        ]
        return slots, 207, 62, "grid"

    if asset_count == 9:
        # Nine photos form a complete 2 + 3 + 4 page.  Allocate both guided
        # sub-heroes and the supporting beat explicitly so role imbalance
        # cannot strand one source photo in a singleton gallery.
        if archetype == "scenic_hero" and variant == "snowdonia_sheep_lake":
            # Snowdonia is a landscape-led story: promote the lake/sheep
            # frame to the dominant anchor, keep the dead-tree and open-slope
            # views as complementary landscape beats, and demote the people
            # frame to a small supporting moment.  The 2 + 3 + 4 rhythm fills
            # the usable A4 field while retaining all nine source photos.
            slots = [
                (14, 45, 118, 78, "hero", "rectangle"),
                (138, 45, 58, 78, "secondary", "rounded"),
                (14, 131, 58, 52, "secondary", "rectangle"),
                (76, 131, 58, 52, "supporting", "rectangle"),
                (138, 131, 58, 52, "detail", "rectangle"),
                (14, 189, 43, 75, "detail", "rectangle"),
                (61, 189, 43, 75, "detail", "rectangle"),
                (108, 189, 43, 75, "detail", "rectangle"),
                (155, 189, 41, 75, "detail", "rectangle"),
            ]
            return slots, 264, 0, "grid"
        if archetype == "scenic_hero" and variant == "waterfall_family_walk":
            # Keep the family-led hero and waterfall sub-hero, but use the
            # extended 2 + 3 + 4 rhythm so the supporting walk and cascade
            # frames remain readable instead of ending in a compressed strip.
            slots = [
                (14, 45, 118, 78, "hero", "rectangle"),
                (138, 45, 58, 78, "secondary", "rounded"),
                (14, 131, 58, 52, "secondary", "rectangle"),
                (76, 131, 58, 52, "supporting", "rectangle"),
                (138, 131, 58, 52, "detail", "rectangle"),
                (14, 189, 43, 75, "detail", "rectangle"),
                (61, 189, 43, 75, "detail", "rectangle"),
                (108, 189, 43, 75, "detail", "rectangle"),
                (155, 189, 41, 75, "detail", "rectangle"),
            ]
            return slots, 264, 0, "grid"
        if archetype == "scenic_hero" and variant == "ridge_people_right":
            # This ridge story has one wide scenic anchor and one vertical
            # mother/child portrait.  Keep both readable at the top, then use
            # a 3 + 4 closing grid that reaches the lower A4 field.  The
            # supporting single-person frame stays visible, but never competes
            # with the people-led sub-hero.
            slots = [
                (14, 45, 58, 78, "secondary", "rounded"),
                (78, 45, 118, 78, "hero", "rectangle"),
                (14, 131, 58, 52, "supporting", "rectangle"),
                (76, 131, 58, 52, "secondary", "rectangle"),
                (138, 131, 58, 52, "detail", "rectangle"),
                (14, 189, 43, 75, "detail", "rectangle"),
                (61, 189, 43, 75, "detail", "rectangle"),
                (108, 189, 43, 75, "detail", "rectangle"),
                (155, 189, 41, 75, "detail", "rectangle"),
            ]
            return slots, 264, 0, "grid"
        slots = top + [
            (14, 121, 58, 39, "secondary", "rectangle"),
            (76, 121, 58, 39, "supporting", "rectangle"),
            (138, 121, 58, 39, "detail", "rectangle"),
            (14, 166, 44, 34, "detail", "rectangle"),
            (61, 166, 44, 34, "detail", "rectangle"),
            (108, 166, 44, 34, "detail", "rectangle"),
            (155, 166, 41, 34, "detail", "rectangle"),
        ]
        return slots, 207, 62, "grid"

    if asset_count == 14 and archetype == "scenic_hero" and variant == "family_lakeside_sequence":
        # This family/lakeside section contains a near-duplicate burst.  Keep
        # every frame, but make the repeated family shots read as a deliberate
        # closing strip while the lake, mountain and walking views retain
        # readable editorial slots in the middle of the page.
        slots = [
            (14, 45, 118, 78, "hero", "rectangle"),
            (138, 45, 58, 78, "secondary", "rounded"),
            (14, 131, 58, 48, "supporting", "rectangle"),
            (76, 131, 58, 48, "supporting", "rectangle"),
            (138, 131, 58, 48, "supporting", "rectangle"),
            (14, 184, 58, 48, "supporting", "rectangle"),
            (76, 184, 58, 48, "supporting", "rectangle"),
            (138, 184, 58, 48, "detail", "rectangle"),
            (14, 237, 28, 27, "detail", "rectangle"),
            (45, 237, 28, 27, "detail", "rectangle"),
            (76, 237, 28, 27, "detail", "rectangle"),
            (107, 237, 28, 27, "detail", "rectangle"),
            (138, 237, 28, 27, "detail", "rectangle"),
            (169, 237, 27, 27, "detail", "rectangle"),
        ]
        return slots, 264, 0, "filmstrip"

    if asset_count == 8:
        # Eight-photo stories need two secondary beats in the editorial flow.
        # Without the second secondary slot, a second guided sub-hero falls
        # through to the contact area and becomes a lonely closing card.  Use
        # a balanced 2 + 3 + 3 composition instead: the final row becomes a
        # real closing cluster, while every source asset remains prominent
        # enough to read as part of the story.
        if archetype == "scenic_hero" and variant == "panorama_then_portraits":
            # For an eight-photo scenic/family story, keep the establishing
            # view and the people-led sub-hero as comparable top anchors.
            # The full 2 + 3 + 3 grid then reaches into the lower A4 field,
            # avoiding both a landscape-dominated hierarchy and a dead-space
            # tail while retaining every source photo.
            slots = [
                (14, 45, 92, 72, "hero", "rectangle"),
                (110, 45, 86, 72, "secondary", "rounded"),
                (14, 125, 58, 55, "secondary", "rectangle"),
                (76, 125, 58, 55, "supporting", "rectangle"),
                (138, 125, 58, 55, "detail", "rectangle"),
                (14, 185, 58, 72, "detail", "rectangle"),
                (76, 185, 58, 72, "detail", "rectangle"),
                (138, 185, 58, 72, "detail", "rectangle"),
            ]
            return slots, 257, 0, "grid"
        slots = top + [
            (14, 121, 58, 42, "secondary", "rectangle"),
            (76, 121, 58, 42, "supporting", "rectangle"),
            (138, 121, 58, 42, "detail", "rectangle"),
            (14, 169, 58, 50, "detail", "rectangle"),
            (76, 169, 58, 50, "detail", "rectangle"),
            (138, 169, 58, 50, "detail", "rectangle"),
        ]
        return slots, 226, 50, "grid"

    if asset_count <= 12:
        # 2 top anchors + 3 readable beats + 4 smaller details = 9 editorial
        # positions. Only 1–3 photos need the closing gallery.
        slots = top + [
            (14, 121, 58, 39, "supporting", "rectangle"),
            (76, 121, 58, 39, "detail", "rectangle"),
            (138, 121, 58, 39, "detail", "rectangle"),
            (14, 166, 44, 34, "detail", "rectangle"),
            (61, 166, 44, 34, "detail", "rectangle"),
            (108, 166, 44, 34, "detail", "rectangle"),
            (155, 166, 41, 34, "detail", "rectangle"),
        ]
        return slots, 207, 62, "staggered"

    # Larger sections still need all photos, but the upper two thirds retain
    # a clear reading order before the final balanced gallery row(s).
    slots = top + [
        (14, 121, 58, 39, "supporting", "rectangle"),
        (76, 121, 58, 39, "detail", "rectangle"),
        (138, 121, 58, 39, "detail", "rectangle"),
        (14, 166, 58, 34, "detail", "rectangle"),
        (76, 166, 58, 34, "detail", "rectangle"),
        (138, 166, 58, 34, "detail", "rectangle"),
    ]
    return slots, 207, 62, "grid"


def _layout_slots(archetype: str, variant: str) -> tuple[list[tuple[float, float, float, float, str, str]], float, float, str]:
    """Return editorial slots and the reserved all-assets contact area."""
    if archetype == "architecture_journey" and variant == "hero_right":
        return [
            (14, 45, 48, 78, "secondary", "rounded"),
            (66, 45, 130, 78, "hero", "rectangle"),
            (14, 128, 58, 57, "supporting", "rectangle"),
            (76, 128, 58, 57, "detail", "rectangle"),
            (138, 128, 58, 57, "detail", "rectangle"),
        ], 191, 75, "staggered"
    if archetype == "architecture_journey" and variant == "spine":
        return [
            (14, 45, 58, 122, "hero", "rectangle"),
            (76, 45, 120, 78, "secondary", "rounded"),
            (76, 128, 58, 39, "supporting", "rectangle"),
            (138, 128, 58, 39, "detail", "rectangle"),
        ], 171, 95, "filmstrip"
    if archetype == "architecture_journey":
        return [
            (14, 45, 126, 78, "hero", "rectangle"),
            (148, 45, 48, 78, "secondary", "rounded"),
            (14, 128, 80, 57, "supporting", "rectangle"),
            (98, 128, 47, 57, "detail", "rectangle"),
            (149, 128, 47, 57, "detail", "rectangle"),
        ], 191, 75, "grid"
    if archetype == "scenic_hero" and variant == "hero_right":
        return [
            (14, 45, 58, 80, "secondary", "rounded"),
            (76, 45, 120, 80, "hero", "rectangle"),
            (14, 130, 58, 54, "supporting", "rectangle"),
            (76, 130, 58, 54, "supporting", "rectangle"),
            (138, 130, 58, 54, "detail", "rectangle"),
        ], 190, 76, "staggered"
    if archetype == "scenic_hero" and variant == "panorama_then_portraits":
        return [
            (14, 45, 182, 72, "hero", "rectangle"),
            (14, 122, 88, 62, "secondary", "rectangle"),
            (108, 122, 88, 62, "supporting", "rectangle"),
        ], 190, 76, "filmstrip"
    if archetype == "scenic_hero":
        return [
            (14, 45, 182, 80, "hero", "rectangle"),
            (14, 130, 88, 54, "secondary", "rectangle"),
            (108, 130, 88, 54, "supporting", "rectangle"),
        ], 190, 76, "grid"
    if archetype == "family_memory" and variant == "hero_right":
        return [
            (14, 45, 66, 82, "secondary", "rounded"),
            (88, 45, 108, 82, "hero", "rectangle"),
            (14, 132, 88, 54, "supporting", "rectangle"),
            (108, 132, 88, 54, "supporting", "rectangle"),
        ], 192, 74, "staggered"
    if archetype == "family_memory" and variant == "group_grid":
        return [
            (14, 45, 182, 68, "hero", "rectangle"),
            (14, 119, 58, 58, "secondary", "rounded"),
            (76, 119, 58, 58, "supporting", "rectangle"),
            (138, 119, 58, 58, "supporting", "rectangle"),
        ], 180, 87, "filmstrip"
    if archetype == "family_memory":
        return [
            (14, 45, 112, 82, "hero", "rectangle"),
            (130, 45, 66, 82, "secondary", "rounded"),
            (14, 132, 88, 54, "supporting", "rectangle"),
            (108, 132, 88, 54, "supporting", "rectangle"),
        ], 192, 74, "grid"
    if archetype == "portrait_editorial":
        return [
            (14, 45, 88, 120, "hero", "rounded"),
            (108, 45, 88, 56, "secondary", "rectangle"),
            (108, 108, 88, 57, "supporting", "rectangle"),
        ], 171, 95, "grid"
    if archetype == "detail_mosaic" and variant == "anchors_left":
        return [
            (14, 45, 118, 68, "hero", "rectangle"),
            (138, 45, 58, 68, "secondary", "rectangle"),
            (14, 119, 88, 54, "supporting", "rectangle"),
            (108, 119, 88, 54, "detail", "rectangle"),
        ], 179, 89, "staggered"
    if archetype == "detail_mosaic" and variant == "three_beats":
        return [
            (14, 45, 58, 72, "hero", "rectangle"),
            (76, 45, 58, 72, "secondary", "rectangle"),
            (138, 45, 58, 72, "supporting", "rectangle"),
            (14, 123, 58, 50, "detail", "rectangle"),
            (76, 123, 58, 50, "detail", "rectangle"),
            (138, 123, 58, 50, "detail", "rectangle"),
        ], 179, 89, "filmstrip"
    if archetype == "detail_mosaic":
        return [
            (14, 45, 88, 75, "hero", "rectangle"),
            (108, 45, 88, 75, "secondary", "rectangle"),
            (14, 126, 58, 53, "supporting", "rectangle"),
            (76, 126, 58, 53, "detail", "rectangle"),
            (138, 126, 58, 53, "detail", "rectangle"),
        ], 185, 81, "staggered"
    if archetype == "sequence_journey" and variant == "filmstrip":
        return [
            (14, 45, 100, 78, "hero", "rectangle"),
            (120, 45, 76, 78, "secondary", "rounded"),
            (14, 128, 58, 48, "supporting", "rectangle"),
            (76, 128, 58, 48, "supporting", "rectangle"),
            (138, 128, 58, 48, "detail", "rectangle"),
        ], 182, 84, "filmstrip"
    if archetype == "sequence_journey" and variant == "stepped":
        return [
            (14, 45, 82, 90, "hero", "rectangle"),
            (104, 45, 92, 65, "secondary", "rounded"),
            (104, 116, 44, 52, "supporting", "rectangle"),
            (152, 116, 44, 52, "supporting", "rectangle"),
        ], 173, 93, "staggered"
    if archetype == "sequence_journey":
        return [
            (14, 45, 110, 80, "hero", "rectangle"),
            (128, 45, 68, 80, "secondary", "rounded"),
            (14, 130, 58, 55, "supporting", "rectangle"),
            (76, 130, 58, 55, "supporting", "rectangle"),
            (138, 130, 58, 55, "detail", "rectangle"),
        ], 191, 75, "grid"
    if archetype == "travel_scrapbook" and variant == "hero_right":
        return [
            (14, 45, 58, 82, "secondary", "rounded"),
            (88, 45, 108, 82, "hero", "rectangle"),
            (14, 132, 88, 54, "supporting", "rectangle"),
            (108, 132, 88, 54, "supporting", "rectangle"),
        ], 192, 74, "staggered"
    if archetype == "travel_scrapbook" and variant == "stacked":
        return [
            (14, 45, 182, 72, "hero", "rectangle"),
            (14, 124, 88, 62, "secondary", "rounded"),
            (108, 124, 88, 62, "supporting", "rectangle"),
        ], 192, 74, "filmstrip"
    # Travel scrapbook: one clear anchor, one complementary view, then two
    # supporting moments before the full-width all-assets contact area.
    return [
        (14, 45, 118, 82, "hero", "rectangle"),
        (138, 45, 58, 82, "secondary", "rounded"),
        (14, 132, 88, 54, "supporting", "rectangle"),
        (108, 132, 88, 54, "supporting", "rectangle"),
    ], 192, 74, "grid"


def build_a4_design_spec(section: dict[str, Any], asset_ids: list[str], guidance: dict[str, Any], album_context: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[str], list[str]]:
    """Build an editorial A4 spec while retaining every source photo.

    Prominence is adaptive, but inclusion is not: every ``asset_id`` receives
    exactly one photo element.  The lower contact area is intentionally part of
    the composition, not a discard bucket, so a 10–18 photo section remains an
    honest visual record without forcing every image to compete for hero scale.
    """
    advice = _advice_for(section, guidance)
    title = str(advice.get("title") or section.get("title") or "Untitled section")
    archetype = _archetype(section, advice)
    variant = _composition_variant(archetype, advice, album_context)
    groups = _role_ids(asset_ids, advice)
    hero_ids = groups["dominant"]
    subhero_ids = groups["subhero"]
    editorial_order = hero_ids + subhero_ids + groups["supporting"] + groups["detail"] + groups["remaining"]

    title_label = title
    elements: list[dict[str, Any]] = [
        {"id": "paper", "type": "rectangle", "x_mm": 0, "y_mm": 0, "width_mm": 210, "height_mm": 297, "fill": "#f5f2ed", "z_index": 0},
        {"id": "title", "type": "text", "content": title_label, "x_mm": 14, "y_mm": 11, "width_mm": 182, "height_mm": 14, "text_style": {"font_id": "serif", "font_size_pt": 18, "weight": "bold", "color": "#263b35", "line_height": 1.05}, "z_index": 10},
        {"id": "context", "type": "text", "content": f"{section.get('topic_name', '2026 Apr Mothers Visit')} · {section.get('title', '')}", "x_mm": 14, "y_mm": 28, "width_mm": 182, "height_mm": 7, "text_style": {"font_id": "sans", "font_size_pt": 7, "weight": "600", "color": "#5f655e", "line_height": 1.1, "letter_spacing": 0.4}, "z_index": 11},
        {"id": "rule", "type": "line", "x_mm": 14, "y_mm": 38, "width_mm": 182, "height_mm": 0, "stroke": "#9aa99c", "stroke_width": 0.7, "z_index": 12},
    ]

    asset_index = {asset_id: index + 1 for index, asset_id in enumerate(asset_ids)}

    def photo(element_id: str, asset_id: str, x: float, y: float, width: float, height: float, role: str, z: int, mask: str = "rectangle") -> dict[str, Any]:
        visual_weight = {"hero": 1.0, "secondary": 0.55, "supporting": 0.3, "detail": 0.18}.get(role, 0.12)
        focus_x = 0.5
        focus_by_index = advice.get("focus_x_by_index")
        if isinstance(focus_by_index, dict):
            try:
                focus_x = float(focus_by_index.get(str(asset_index[asset_id]), focus_x))
            except (KeyError, TypeError, ValueError):
                focus_x = 0.5
        focus_x = min(1.0, max(0.0, focus_x))
        focus_y = 0.5
        focus_by_index = advice.get("focus_y_by_index")
        if isinstance(focus_by_index, dict):
            try:
                focus_y = float(focus_by_index.get(str(asset_index[asset_id]), focus_y))
            except (KeyError, TypeError, ValueError):
                focus_y = 0.5
        focus_y = min(1.0, max(0.0, focus_y))
        return {"id": element_id, "type": "photo", "asset_id": asset_id, "role": role, "visual_weight": visual_weight, "x_mm": x, "y_mm": y, "width_mm": width, "height_mm": height, "rotation_deg": 0, "image": {"focus_x": focus_x, "focus_y": focus_y, "zoom": 1}, "mask": {"type": mask}, "border": {"width_mm": 1.2, "color": "#ffffff", "opacity": 1}, "shadow": {"color": "#000000", "opacity": 0.12, "blur_mm": 1.5, "offset_x_mm": 0.3, "offset_y_mm": 0.6}, "z_index": z}

    slots, contact_y, contact_height, contact_style = _layout_slots(archetype, variant)
    adaptive = _adaptive_editorial_layout(archetype, variant, len(asset_ids))
    if adaptive is not None:
        slots, contact_y, contact_height, contact_style = adaptive
    slot_roles = {
        "hero": hero_ids,
        "secondary": subhero_ids,
        "supporting": groups["supporting"],
        "detail": groups["detail"] + groups["remaining"],
    }
    role_cursor = {role: 0 for role in slot_roles}
    used: set[str] = set()

    def next_candidate(role: str) -> str | None:
        candidates = slot_roles.get(role, [])
        index = role_cursor.get(role, 0)
        while index < len(candidates) and candidates[index] in used:
            index += 1
        if index >= len(candidates):
            role_cursor[role] = index
            return None
        role_cursor[role] = index + 1
        return candidates[index]

    for x, y, width, height, role, mask in slots:
        asset_id = next_candidate(role)
        actual_role = role
        if asset_id is None and role in {"secondary", "supporting", "detail"}:
            # A guidance file often names only the best hero candidates.  Fill
            # an intentional editorial slot with the next lower-weight asset
            # instead of leaving a conspicuous hole in the page.  The asset
            # keeps its lower semantic role, so filling geometry never turns a
            # detail into a second hero.
            fallback = [item for item in groups["detail"] + groups["remaining"] if item not in used]
            if fallback:
                asset_id = fallback[0]
                actual_role = "detail"
                detail_candidates = slot_roles["detail"]
                if asset_id in detail_candidates:
                    role_cursor["detail"] = detail_candidates.index(asset_id) + 1
        if asset_id is None:
            continue
        if asset_id in used:
            continue
        used.add(asset_id)
        elements.append(photo(f"{role}-{len(used)}", asset_id, x, y, width, height, actual_role, 20 + len(used), mask))

    # Any role group that did not fit in the editorial slots, plus every asset
    # not used above, flows into the intentionally visible contact area.
    remaining_ids = [asset_id for asset_id in editorial_order if asset_id not in used]
    for index, (asset_id, (x, y, width, height)) in enumerate(zip(remaining_ids, _contact_slots(len(remaining_ids), contact_y, contact_height, contact_style)), 1):
        used.add(asset_id)
        elements.append(photo(f"contact-{index}", asset_id, x, y, width, height, "detail", 50 + index))

    rendered_photo_elements = [element for element in elements if element.get("type") == "photo"]
    rendered_photo_ids = [str(element["asset_id"]) for element in rendered_photo_elements]
    if len(rendered_photo_ids) != len(asset_ids) or set(rendered_photo_ids) != set(asset_ids):
        raise ValueError(
            f"collage generator lost or duplicated assets: expected {len(asset_ids)}, rendered {len(rendered_photo_ids)}"
        )

    # Report the roles that actually made it into the page.  Guidance can
    # nominate several possible sub-heroes, but a given archetype/variant may
    # only have one prominent secondary frame.  The exported metadata must
    # describe the rendered page rather than the unbounded preference list.
    rendered_role_ids = {
        role: [str(element["asset_id"]) for element in rendered_photo_elements if element.get("role") == role]
        for role in ("hero", "secondary", "supporting", "detail")
    }
    rendered_hero_ids = rendered_role_ids["hero"][:1]
    rendered_subhero_ids = rendered_role_ids["secondary"]

    closing_caption = str(advice.get("closing_caption") or "")
    photo_bottom = max(
        (float(element["y_mm"]) + float(element["height_mm"]) for element in elements if element.get("type") == "photo"),
        default=contact_y,
    )
    caption_y = min(photo_bottom + 3.5, 270.0)
    if closing_caption and caption_y + 8 <= 280:
        elements.append({"id": "closing-caption", "type": "text", "content": closing_caption, "x_mm": 14, "y_mm": caption_y, "width_mm": 182, "height_mm": 7, "text_style": {"font_id": "serif", "font_size_pt": 7.5, "weight": "600", "color": "#43534b", "line_height": 1.1}, "z_index": 80})
    # Rendering diagnostics belong in ``metadata.composition`` and the editor
    # inspector, never in the artwork itself.  Keeping the page free of a
    # generated "N photos · hero · sub-hero" footer makes the exported page
    # read as a finished story rather than a debug sheet.
    composition = {
        "layout_archetype": archetype,
        "composition_variant": variant,
        "contact_style": contact_style,
        "narrative_direction": str(advice.get("narrative_direction") or "top_to_bottom"),
        "dominant_hero": rendered_hero_ids[0] if rendered_hero_ids else None,
        "subheroes": rendered_subhero_ids,
        "supporting": rendered_role_ids["supporting"],
        "details": rendered_role_ids["detail"],
        "all_asset_ids": asset_ids,
        "asset_count": len(asset_ids),
        "rendered_asset_count": len(rendered_photo_ids),
        "all_assets_rendered": len(rendered_photo_ids) == len(asset_ids) and set(rendered_photo_ids) == set(asset_ids),
        "photo_element_asset_ids": rendered_photo_ids,
        "editorial_slot_count": len(slots),
        "gallery_asset_count": len(remaining_ids),
        "visual_weight_policy": {"hero": 1.0, "secondary": 0.55, "supporting": 0.3, "detail": "0.12-0.22"},
        "rendered_role_counts": {role: len(ids) for role, ids in rendered_role_ids.items()},
        "similarity_groups": advice.get("similarity_groups") or [],
        "album_context": dict(album_context or {}),
        "invariants": {"all_assets_rendered": True, "max_dominant_heroes": 1, "avoid_duplicate_prominent_members": True},
    }
    spec = {
        "format": "CollageDesignSpec", "schema_version": 1, "composition": composition, "page_spec": {"type": "single", "preset_id": "a4-portrait", "width_mm": 210, "height_mm": 297, "orientation": "portrait", "bleed_mm": 3, "safe_margin_mm": 8, "gutter_mm": 4, "dpi": 300, "background": "#f5f2ed"},
        "assets": [{"asset_id": asset_id, "label": f"A{index + 1:02d}"} for index, asset_id in enumerate(asset_ids)],
        "alternatives": [{"id": "a4-storyboard", "style": f"editorial {archetype.replace('_', ' ')} · {variant}", "reason": f"One dominant hero leads a {archetype.replace('_', ' ')} reading order; controlled variation {variant} prevents adjacent pages from becoming clones, while every source asset remains visible in an intentional supporting/detail area.", "elements": elements}],
    }
    return spec, rendered_hero_ids, rendered_subhero_ids


def make_document(section: dict[str, Any], asset_items: list[dict[str, Any]], guidance: dict[str, Any], project_id: str, album_context: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[str], list[str]]:
    asset_ids = [str(item["asset_id"]) for item in asset_items]
    spec, hero_ids, subhero_ids = build_a4_design_spec(section, asset_ids, guidance, album_context)
    asset_map = {str(item["asset_id"]): item for item in asset_items}
    checked = validate_design_spec(spec, set(asset_map))
    document = to_collage_document(checked, 0, asset_map)
    document["metadata"] = {
        **document.get("metadata", {}), "project_id": project_id, "topic_id": section.get("topic_id"), "topic_name": section.get("topic_name"),
        "section_id": section.get("section_id"), "section_title": section.get("title"), "design_title": str((guidance.get(str(section.get("title")), {}) or {}).get("title") or section.get("title")), "guidance_title": spec["alternatives"][0]["reason"],
        "generation_method": "semantic-all-assets-editorial-v3", "hero_asset_ids": hero_ids, "subhero_asset_ids": subhero_ids, "composition": spec.get("composition", {}),
    }
    document["style"] = "A4 editorial family travel scrapbook"
    return document, hero_ids, subhero_ids
