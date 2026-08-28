from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import BinaryIO, Iterable, Protocol


@dataclass(frozen=True)
class SourceIdentity:
    source_id: str
    manufacturer: str
    model: str
    display_name: str
    adapter: str
    usb_vendor_id: int | None = None
    usb_product_id: int | None = None


@dataclass(frozen=True)
class SourceStorage:
    storage_id: int
    name: str
    capacity_bytes: int | None = None
    free_bytes: int | None = None


@dataclass(frozen=True)
class PhotoItem:
    source_id: str
    object_id: str
    parent_id: str | None
    name: str
    media_type: str
    size_bytes: int | None
    created_at: datetime | None = None
    modified_at: datetime | None = None
    is_collection: bool = False


class PhotoSource(Protocol):
    def identity(self) -> SourceIdentity: ...

    def list_storages(self) -> Iterable[SourceStorage]: ...

    def list_children(self, parent_id: str | None) -> Iterable[PhotoItem]: ...

    def stat_item(self, object_id: str) -> PhotoItem: ...

    def capabilities(self) -> frozenset[str]: ...

    def stream_object(self, object_id: str, sink: BinaryIO) -> dict[str, int | float]: ...
