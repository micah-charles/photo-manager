from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from time import perf_counter

from photovault.catalog.metadata import extract_metadata

from .models import PhotoInput

try:
    from PIL import Image, ImageFilter, ImageStat
except ImportError:  # pragma: no cover
    Image = ImageFilter = ImageStat = None


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif", ".tiff", ".heic", ".heif"}


@dataclass(frozen=True)
class FaceBox:
    left: float
    top: float
    right: float
    bottom: float
    confidence: float


@dataclass(frozen=True)
class PhotoAnalysis:
    width: int
    height: int
    orientation: int | None
    faces: tuple[FaceBox, ...] = ()
    salient_region: tuple[float, float, float, float] = (0.15, 0.15, 0.85, 0.85)
    quality_score: float = 0.0
    detector: str = "none"
    detection_ms: float = 0.0

    def to_dict(self):
        return asdict(self)


class LocalFaceDetector:
    """Optional CPU-local OpenCV Haar detector; no cloud service or weights download."""

    name = "opencv-haar-cascade"

    def __init__(self):
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.cv2 = None
            self.np = None
            self.classifier = None
            return
        self.cv2 = cv2
        self.np = np
        cascade_class = getattr(cv2, "CascadeClassifier", None)
        self.classifier = cascade_class(str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml")) if cascade_class else None

    def detect(self, image) -> tuple[FaceBox, ...]:
        if self.classifier is None:
            return ()
        gray = self.cv2.cvtColor(self.np.asarray(image), self.cv2.COLOR_RGB2GRAY)
        found = self.classifier.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(24, 24))
        width, height = image.size
        return tuple(FaceBox(x / width, y / height, (x + w) / width, (y + h) / height, 0.85) for x, y, w, h in found)


def analyse_photo(path: Path) -> PhotoInput:
    if Image is None:
        raise RuntimeError("Pillow is required for the collage POC; install photovault[desktop]")
    detector = LocalFaceDetector()
    started = perf_counter()
    with Image.open(path) as image:
        width, height = image.size
        # A cheap, cached-friendly quality proxy. It is deliberately not an AI score.
        gray = image.convert("L").resize((96, 96))
        edges = gray.filter(ImageFilter.FIND_EDGES)
        quality = min(100.0, ImageStat.Stat(edges).var[0] / 8.0)
        faces = detector.detect(image.convert("RGB"))
    metadata = extract_metadata(path)
    analysis = PhotoAnalysis(width, height, metadata.orientation, faces, quality_score=quality, detector=detector.name if detector.classifier is not None else "unavailable", detection_ms=round((perf_counter() - started) * 1000, 3))
    return PhotoInput(path.stem, path, width, height, metadata.capture_datetime, quality, analysis)


def discover_photos(folder: Path, limit: int = 15) -> list[PhotoInput]:
    paths = sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES), key=lambda p: p.name.lower())
    return [analyse_photo(path) for path in paths[:limit]]
