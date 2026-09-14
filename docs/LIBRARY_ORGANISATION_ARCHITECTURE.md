# PhotoVault library organisation architecture

PhotoVault separates verified storage from logical photo organisation. Originals
remain ordinary user-owned files. The catalog records identity, provenance and
derived views; changing an Event, Tag, Collection, Person, Place or Review state
does not move, rename, rewrite or delete an original.

## Core model

```text
Source ──< AssetLocation >── Volume
                 │
                 └── Asset ── media metadata / exact hash / thumbnail
                       ├── Event membership
                       ├── Tag membership
                       ├── Collection membership
                       ├── Person membership
                       ├── Place assignment
                       ├── Category suggestions
                       └── Review state + rating + favourite
```

### Source

A Source is a persistent logical origin such as a Pixel phone, camera, SD card,
or existing folder. Its identity is independent of an IP address or mount path.
Source provenance is shown in the Library and inspector and may carry a
display-only capture-time offset. The offset changes ordering, never raw
metadata or file bytes.

### Volume and AssetLocation

A Volume is physical storage identified through the platform provider. An
AssetLocation connects an Asset to a volume and relative path, including
availability state. Multiple locations may represent verified copies of the same
Asset. Offline locations remain catalogued and are not treated as deleted.

### Asset

An Asset is the stable catalog identity for media content. Exact SHA-256 hashes
and byte counts are integrity evidence; capture time, camera, dimensions and GPS
are extracted metadata. Import time is retained separately so Timeline can use
capture time while Recently Added uses catalog/import time.

## Logical organisation

- **Event** is usually time-bound (for example, “Scotland Trip 2026”) and can
  include assets from multiple Sources. Date-range membership is inclusive and
  membership removal is catalog-only.
- **Tag** is user-owned, many-to-many metadata (for example, “Family”). Tags
  are separate from AI categories and can be assigned in bulk.
- **Collection / Album** is a curated logical set. An Asset may belong to many
  albums without physical duplication.
- **Person** is a catalog identity with manual assignments or imported derived
  face groups. AI is optional; manual decisions remain authoritative.
- **Place** can be manually assigned even when the file has no GPS. Embedded GPS
  is preserved and is not overwritten by a manual place.
- **Category** is an advisory model output normalised for user browsing. Raw
  model labels and model identity remain available as evidence. Accepting a
  category as a Tag is an explicit user action.
- **Review state** is independent from Favourite and Rating: `UNREVIEWED`,
  `PICKED`, `REJECTED` and `HIDDEN`. Reject hides an item from the normal view
  but never deletes or changes the file.
- **Rating** is an independent 0–5 user value. Favourite is an independent
  boolean annotation.

## Metadata provenance

Where applicable, metadata records its origin, such as `embedded`,
`user_assigned`, `event_inherited`, `ai_suggested`, or `ai_confirmed`.
User-assigned values must not be silently replaced by later AI analysis. Derived
indexes (thumbnails, perceptual hashes, embeddings, categories and face groups)
are rebuildable and keyed to source hashes where supported.

## Import and safety boundary

```text
Source inventory
      ↓
Import plan / conflict check
      ↓
partial destination file
      ↓ size + SHA-256 verification
      ↓
atomic rename + catalog registration + ImportBatch journal
```

Backup/import is responsible for source provenance, destination identity,
verification, resumability and operation history. Library organisation is
responsible for catalog-only metadata and queries. Physical Copy, Move, Export,
Quarantine and Permanent Delete remain explicit Storage workflows with review
and safety checks; ordinary organisation actions never invoke them.

## Query behaviour

Timeline merges all available Sources chronologically using effective display
time. Library uses the same query engine for All Photos, Recently Added,
Events, Tags, Places, People, Categories, Collections and Review queues. Filters
are composable, and counts use the same predicates as item listing so the UI
does not report misleading totals.

The Photo Viewer exposes the same logical assignments for the current Asset,
while bulk controls in Library apply the same catalog services to a selection.
Both paths preserve original bytes and backup truth.

## Platform boundary

The Python catalog and organisation services are platform-neutral. macOS and
Windows volume providers supply physical identity and native dialogs. Android
Companion is a read-only network Source; its transfer bytes enter through the
same verified import pipeline as folder and camera sources.
