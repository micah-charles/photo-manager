from __future__ import annotations

import io
import unittest

from PIL import Image, ImageDraw

from photovault.collage.layered_templates import validate_layered_template
from photovault.collage.design_formats import to_collage_document


class _Archive:
    def __init__(self, files: dict[str, bytes]):
        self.files = files

    def read(self, path: str) -> bytes:
        return self.files[path]


def png(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def package_images(*, foreground_alpha: int = 0, mask_shape: str = "rectangle", slot_role: str = "hero") -> tuple[_Archive, dict, dict, set[str]]:
    foreground = Image.new("RGBA", (200, 200), (255, 255, 255, foreground_alpha))
    mask = Image.new("L", (200, 200), 0)
    draw = ImageDraw.Draw(mask)
    if mask_shape == "circle":
        draw.ellipse((20, 20, 180, 180), fill=255)
    elif mask_shape == "film-strip":
        draw.rectangle((10, 40, 80, 160), fill=255)
        draw.rectangle((120, 40, 190, 160), fill=255)
    else:
        draw.rectangle((20, 20, 180, 180), fill=255)
    files = {
        "template/foreground.png": png(foreground),
        "template/masks/A01.png": png(mask),
    }
    manifest = {
        "format": "PhotoManager AI Design Package", "schema_version": 2,
        "capabilities": ["layered-template", "transparent-photo-slots"],
        "template": {
            "foreground": "template/foreground.png",
            "masks": {"A01": "template/masks/A01.png"},
            "slots": {"A01": {"role": slot_role, "x_mm": 10, "y_mm": 10, "width_mm": 80, "height_mm": 80}},
        },
    }
    design = {"page_spec": {"type": "single", "width_mm": 100, "height_mm": 100}}
    return _Archive(files), manifest, design, set(files)


class LayeredTemplateTests(unittest.TestCase):
    def test_accepts_all_supported_photo_roles_for_layered_slots(self):
        for role in ("sequence", "context", "secondary"):
            with self.subTest(role=role):
                archive, manifest, design, names = package_images(slot_role=role)
                result = validate_layered_template(manifest, design, archive, names)
                self.assertIsNotNone(result)
                self.assertEqual(result["template"]["slots"]["A01"]["role"], role)

    def test_normalises_white_mask_to_alpha_without_changing_contract(self):
        archive, manifest, design, names = package_images(mask_shape="circle")
        result = validate_layered_template(manifest, design, archive, names)
        self.assertIsNotNone(result)
        normalised = Image.open(io.BytesIO(result["files"]["template/masks/A01.png"]))
        self.assertEqual(normalised.mode, "RGBA")
        self.assertEqual(normalised.getpixel((100, 100))[3], 255)
        self.assertEqual(normalised.getpixel((0, 0))[3], 0)

    def test_rejects_opaque_foreground_at_aperture(self):
        archive, manifest, design, names = package_images(foreground_alpha=255)
        with self.assertRaisesRegex(ValueError, "foreground aperture A01 is opaque"):
            validate_layered_template(manifest, design, archive, names)

    def test_rejects_traversal_and_missing_slot_mask(self):
        archive, manifest, design, names = package_images()
        manifest["template"]["foreground"] = "template/../foreground.png"
        with self.assertRaisesRegex(ValueError, "unsafe template path"):
            validate_layered_template(manifest, design, archive, names)
        archive, manifest, design, names = package_images()
        manifest["template"]["masks"]["A01"] = "template/masks/missing.png"
        with self.assertRaisesRegex(ValueError, "missing from the ZIP"):
            validate_layered_template(manifest, design, archive, names)

    def test_document_places_template_layers_around_photo_elements(self):
        asset_map = {
            "photo-1": {"asset_id": "photo-1"},
            "pa-foreground": {"package_asset_id": "pa-foreground", "asset_url": "/api/collage/design-assets/pa-foreground"},
            "pa-mask": {"package_asset_id": "pa-mask", "asset_url": "/api/collage/design-assets/pa-mask"},
        }
        spec = {
            "format": "CollageDesignSpec", "schema_version": 2,
            "page_spec": {"type": "single", "width_mm": 100, "height_mm": 100},
            "assets": [{"asset_id": "photo-1", "label": "A01"}],
            "layered_template": {
                "version": 1, "foreground_asset_id": "pa-foreground",
                "mask_asset_ids": {"A01": "pa-mask"},
                "slots": {"A01": {"role": "hero", "x_mm": 10, "y_mm": 10, "width_mm": 80, "height_mm": 80}},
            },
            "alternatives": [{"id": "film-strip", "elements": [{
                "id": "photo-01", "type": "photo", "asset_id": "photo-1", "slot_id": "A01",
                "x_mm": 10, "y_mm": 10, "width_mm": 80, "height_mm": 80,
                "template_mask_asset_id": "pa-mask", "z_index": 1,
            }]}],
        }
        document = to_collage_document(spec, asset_map=asset_map)
        self.assertEqual([item["template_layer"] for item in document["elements"] if item.get("template_layer")], ["foreground"])
        self.assertEqual(document["elements"][0]["type"], "photo")
        self.assertEqual(document["elements"][0]["template_slot_id"], "A01")
        self.assertEqual(document["elements"][0]["template_mask_url"], "/api/collage/design-assets/pa-mask")


if __name__ == "__main__":
    unittest.main()
