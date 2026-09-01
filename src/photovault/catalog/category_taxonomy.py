"""Small, deterministic display taxonomy for raw local model labels."""
from __future__ import annotations


_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Animals", ("animal", "bird", "cat", "dog", "fish", "horse", "insect", "mammal", "pet", "reptile")),
    ("Architecture", ("building", "castle", "church", "dome", "house", "palace", "skyscraper", "tower")),
    ("Food", ("cake", "coffee", "dish", "food", "fruit", "meal", "pizza", "plate", "restaurant")),
    ("Nature", ("beach", "forest", "landscape", "mountain", "nature", "ocean", "river", "valley", "waterfall")),
    ("Transport", ("aircraft", "bicycle", "boat", "bus", "car", "motorcycle", "ship", "train", "vehicle")),
    ("People", ("baby", "boy", "bride", "child", "face", "man", "person", "portrait", "woman")),
    ("Music", ("guitar", "microphone", "music", "piano", "stage")),
    ("Sunset", ("sunrise", "sunset")),
)


def normalize_label(label: str) -> str:
    """Map a raw model label to a stable user-facing category title."""
    clean = " ".join(str(label).replace("_", " ").split())
    lowered = clean.casefold()
    for category, keywords in _KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return category
    return clean or "Uncategorised"
