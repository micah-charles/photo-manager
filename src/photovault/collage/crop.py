from __future__ import annotations

from dataclasses import replace

from .models import Cell, Crop, PhotoInput


def cover_crop(photo: PhotoInput, cell_width: int, cell_height: int) -> Crop:
    """Return normalized center crop coordinates, preserving source pixels."""
    target = cell_width / cell_height if cell_height else 1.0
    source = photo.aspect_ratio
    if source > target:
        visible = target / source
        margin = (1.0 - visible) / 2
        return Crop(margin, 0.0, 1.0 - margin, 1.0)
    visible = source / target
    margin = (1.0 - visible) / 2
    return Crop(0.0, margin, 1.0, 1.0 - margin)


def optimise_cell(cell: Cell, photo: PhotoInput) -> Cell:
    """Shift the largest matching crop toward detected faces, without distortion."""
    raw = cover_crop(photo, cell.width, cell.height)
    analysis = photo.analysis
    faces = tuple(getattr(analysis, "faces", ())) if analysis else ()
    candidates = [raw]
    if faces:
        # Translate the crop so the weighted face group is centered whenever possible.
        left = min(face.left for face in faces); top = min(face.top for face in faces)
        right = max(face.right for face in faces); bottom = max(face.bottom for face in faces)
        crop_w, crop_h = raw.right - raw.left, raw.bottom - raw.top
        cx, cy = (left + right) / 2, (top + bottom) / 2
        shifted_left = min(max(cx - crop_w / 2, 0.0), 1.0 - crop_w)
        shifted_top = min(max(cy - crop_h / 2, 0.0), 1.0 - crop_h)
        candidates.append(Crop(shifted_left, shifted_top, shifted_left + crop_w, shifted_top + crop_h))
    def face_score(crop):
        return sum(max(0.0, min(crop.right, f.right) - max(crop.left, f.left)) * max(0.0, min(crop.bottom, f.bottom) - max(crop.top, f.top)) for f in faces)
    optimised = max(candidates, key=face_score)
    excluded = [f for f in faces if f.right <= optimised.left or f.left >= optimised.right or f.bottom <= optimised.top or f.top >= optimised.bottom]
    partial = [f for f in faces if f not in excluded and (f.left < optimised.left or f.top < optimised.top or f.right > optimised.right or f.bottom > optimised.bottom)]
    reason = "FACE_EXCLUDED" if excluded else "FACE_PARTIAL" if partial else None
    changed = optimised != raw
    salient = getattr(analysis, "salient_region", (0.15, 0.15, 0.85, 0.85)) if analysis else (0.15, 0.15, 0.85, 0.85)
    salient_area = max(0.0001, (salient[2] - salient[0]) * (salient[3] - salient[1]))
    overlap = max(0.0, min(optimised.right, salient[2]) - max(optimised.left, salient[0])) * max(0.0, min(optimised.bottom, salient[3]) - max(optimised.top, salient[1]))
    saliency_percent = round(min(100.0, overlap / salient_area * 100.0), 2)
    return replace(cell, crop=optimised, crop_metadata={"raw_center_crop": raw, "optimised_crop": optimised, "faces_detected": len(faces), "faces_retained": len(faces) - len(excluded) - len(partial), "faces_excluded": len(excluded), "saliency_retained_percent": saliency_percent, "crop_penalty": 100.0 if reason else max(0.0, 100.0 - saliency_percent), "hard_rejection_reason": reason, "smart_crop_changed": changed})
