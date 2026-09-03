from __future__ import annotations

import random
from abc import ABC, abstractmethod

from ..collage.crop import cover_crop
from .models import Canvas, Cell, LayoutCandidate, PhotoInput


class LayoutProvider(ABC):
    name = "provider"

    @abstractmethod
    def generate(self, photos: list[PhotoInput], canvas: Canvas, seed: int, count: int = 10) -> list[LayoutCandidate]:
        raise NotImplementedError


def _candidate(name: str, number: int, seed: int, photos: list[PhotoInput], canvas: Canvas, rects: list[tuple[int, int, int, int]], style: str) -> LayoutCandidate:
    cells = [Cell(photo.photo_id, x, y, width, height, cover_crop(photo, width, height)) for photo, (x, y, width, height) in zip(photos, rects)]
    return LayoutCandidate(name, number, seed, canvas, cells, style)


class NativeProvider(LayoutProvider):
    name = "native"

    def generate(self, photos, canvas, seed, count=10):
        result = []
        for number in range(count):
            rng = random.Random(seed + number)
            order = list(photos)
            rng.shuffle(order)
            n = len(order)
            if n == 1:
                rects = [(0, 0, canvas.width, canvas.height)]
            elif number % 3 == 0:
                split = canvas.width // 2
                rects = [(0, 0, split - canvas.gutter // 2, canvas.height), (split + canvas.gutter // 2, 0, canvas.width - split - canvas.gutter // 2, canvas.height)]
                rects = _grid_rects(n, canvas, 2, order)
            else:
                cols = 2 if n <= 4 or number % 2 else 3
                rects = _grid_rects(n, canvas, cols, order)
            result.append(_candidate(self.name, number + 1, seed + number, order, canvas, rects, "grid"))
        return result


def _grid_rects(n: int, canvas: Canvas, cols: int, _photos) -> list[tuple[int, int, int, int]]:
    rows = (n + cols - 1) // cols
    cell_w = (canvas.width - canvas.gutter * (cols - 1)) // cols
    cell_h = (canvas.height - canvas.gutter * (rows - 1)) // rows
    return [(col * (cell_w + canvas.gutter), row * (cell_h + canvas.gutter), cell_w, cell_h) for row in range(rows) for col in range(cols)][:n]


class BSPProvider(LayoutProvider):
    name = "bsp"

    def generate(self, photos, canvas, seed, count=10):
        result = []
        for number in range(count):
            order = list(photos)
            random.Random(seed + number).shuffle(order)
            rects: list[tuple[int, int, int, int]] = []
            _partition(0, 0, canvas.width, canvas.height, len(order), canvas.gutter, random.Random(seed + number * 17), rects)
            result.append(_candidate(self.name, number + 1, seed + number, order, canvas, rects, "recursive-bsp"))
        return result


def _partition(x, y, width, height, count, gutter, rng, output):
    if count <= 1:
        output.append((x, y, width, height))
        return
    left_count = count // 2
    horizontal = width / height > (1.25 if count % 2 else 1.0)
    ratio = 0.42 + rng.random() * 0.16
    if horizontal:
        first = int(width * ratio) - gutter // 2
        _partition(x, y, first, height, left_count, gutter, rng, output)
        _partition(x + first + gutter, y, width - first - gutter, height, count - left_count, gutter, rng, output)
    else:
        first = int(height * ratio) - gutter // 2
        _partition(x, y, width, first, left_count, gutter, rng, output)
        _partition(x, y + first + gutter, width, height - first - gutter, count - left_count, gutter, rng, output)


class OptimisationProvider(BSPProvider):
    """Small original CEWE-style heuristic: varied weighted partitions, no copied code."""
    name = "optimisation"

    def generate(self, photos, canvas, seed, count=10):
        result = super().generate(photos, canvas, seed + 101, count)
        for number, candidate in enumerate(result):
            candidate.provider = self.name
            candidate.style = "weighted-editorial"
            # Make the first cell a deliberate hero while keeping geometry reproducible.
            if number % 2 == 0 and candidate.cells:
                candidate.metadata["hero_photo_id"] = candidate.cells[0].photo_id
        return result


class CeweLayoutProvider(LayoutProvider):
    """Adapter for the upstream cewe-layout Genetic Algorithm (Fan)."""
    name = "cewe-genetic"

    def generate(self, photos, canvas, seed, count=10):
        # The upstream algorithm uses Python's module-level random generator.
        # Isolate and seed it so the PhotoVault provider remains reproducible.
        from .vendor.cewe_layout.algorithms.base import LayoutRectangle
        from .vendor.cewe_layout.algorithms.fan_layout import FanLayoutAlgorithm

        result = []
        for number in range(count):
            state = random.getstate()
            random.seed(seed + number * 997)
            try:
                rectangles = [LayoutRectangle(photo.photo_id, photo.width, photo.height, preferred_size=1.0) for photo in photos]
                algorithm = FanLayoutAlgorithm(population_size=28, generations=45, elite_size=2)
                success, rectangles, error = algorithm.generate_layout(canvas.width, canvas.height, rectangles)
                if not success:
                    raise RuntimeError(error)
                # The upstream wrapper identifies each rectangle by item_id and
                # maps it back to the source item. Do the same here rather than
                # relying on the algorithm preserving list order. This keeps the
                # stable PhotoVault asset identity attached to the original photo.
                photos_by_id = {photo.photo_id: photo for photo in photos}
                cells = []
                for rect in rectangles:
                    photo = photos_by_id.get(str(rect.item_id))
                    if photo is None:
                        raise RuntimeError(f"CEWE returned unknown item_id: {rect.item_id}")
                    width = max(1, round(rect.width))
                    height = max(1, round(rect.height))
                    cells.append(Cell(photo.photo_id, round(rect.x), round(rect.y), width, height, cover_crop(photo, width, height)))
                result.append(LayoutCandidate(self.name, number + 1, seed + number * 997, canvas, cells, "genetic-fan", metadata={"upstream": "vincedarley/cewe-layout", "algorithm": "FanLayoutAlgorithm"}))
            finally:
                random.setstate(state)
        return result
