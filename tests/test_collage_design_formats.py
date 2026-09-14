import unittest

from photovault.collage.design_formats import to_collage_document, validate_design_spec


class CollageDesignFormatTests(unittest.TestCase):
    def spec(self, elements):
        return {
            "format": "CollageDesignSpec", "schema_version": 1,
            "page_spec": {"width_mm": 300, "height_mm": 300, "background": "#f5f2ed"},
            "assets": [{"asset_id": "a1", "filename": "one.jpg"}],
            "alternatives": [{"id": "alt-1", "name": "Test alternative", "elements": elements}],
        }

    def test_validates_photo_and_converts_to_stable_element_document(self):
        spec = self.spec([{"id": "photo-01", "type": "photo", "asset_id": "a1", "x_mm": 10, "y_mm": 8,
                           "width_mm": 94, "height_mm": 94, "image": {"focus_x": .5, "focus_y": .4}}])
        checked = validate_design_spec(spec, {"a1"})
        document = to_collage_document(checked, asset_map={"a1": spec["assets"][0]})
        self.assertEqual(document["schema_version"], 2)
        self.assertEqual(document["elements"][0]["element_id"], "photo-01")
        self.assertEqual(document["elements"][0]["photo_id"], "a1")
        self.assertEqual(document["metadata"]["design_id"], "alt-1")
        self.assertEqual(document["metadata"]["design_name"], "Test alternative")

    def test_rejects_unknown_asset_and_unsafe_numbers(self):
        with self.assertRaisesRegex(ValueError, "outside the package"):
            validate_design_spec(self.spec([{"id": "p", "type": "photo", "asset_id": "missing", "x_mm": 0, "y_mm": 0, "width_mm": 10, "height_mm": 10}]), {"a1"})
        with self.assertRaisesRegex(ValueError, "finite"):
            validate_design_spec(self.spec([{"id": "p", "type": "photo", "asset_id": "a1", "x_mm": "NaN", "y_mm": 0, "width_mm": 10, "height_mm": 10}]), {"a1"})

    def test_supports_text_and_decoration_layers(self):
        spec = self.spec([
            {"id": "bg", "type": "rectangle", "x_mm": 0, "y_mm": 0, "width_mm": 300, "height_mm": 300, "fill": "#f5f2ed", "z_index": 0},
            {"id": "title", "type": "text", "content": "Kew Gardens", "x_mm": 10, "y_mm": 250, "width_mm": 180, "height_mm": 20, "z_index": 5},
        ])
        document = to_collage_document(spec, asset_map={"a1": spec["assets"][0]})
        self.assertEqual([x["element_id"] for x in document["elements"]], ["bg", "title"])


if __name__ == "__main__":
    unittest.main()
