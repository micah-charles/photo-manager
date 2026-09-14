import unittest

from photovault.collage.design_formats import to_collage_document, validate_and_repair_design_spec, validate_design_spec


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

    def test_converts_polygon_points_and_strokes_from_mm_to_pixels(self):
        spec = self.spec([{
            "id": "shape", "type": "polygon", "points": [{"x": 1, "y": 2}, {"x": 4, "y": 6}, {"x": 7, "y": 3}],
            "x_mm": 0, "y_mm": 0, "width_mm": 20, "height_mm": 20,
            "stroke_width": 1.5, "fill": "#ffffff", "z_index": 2,
        }])
        document = to_collage_document(spec, asset_map={"a1": spec["assets"][0]})
        shape = document["elements"][0]
        self.assertEqual(shape["points"], [{"x": 4, "y": 8}, {"x": 16, "y": 24}, {"x": 28, "y": 12}])
        self.assertEqual(shape["stroke_width"], 6)

    def test_v2_supports_object_masks_and_reports_text_repair(self):
        spec = self.spec([
            {"id": "photo-01", "type": "photo", "asset_id": "a1", "x_mm": 10, "y_mm": 10,
             "width_mm": 100, "height_mm": 80, "mask": {"type": "circle"}},
            {"id": "title", "type": "text", "content": "A very long heading that needs a bounded font repair",
             "x_mm": 10, "y_mm": 250, "width_mm": 25, "height_mm": 10,
             "text_style": {"font_id": "script", "font_size_pt": 44, "text_fit": "shrink_to_fit"}},
        ])
        spec["schema_version"] = 2
        checked, report = validate_and_repair_design_spec(spec, {"a1"})
        self.assertEqual(checked["alternatives"][0]["elements"][0]["mask"], {"type": "circle"})
        self.assertTrue(report["repairs"])


if __name__ == "__main__":
    unittest.main()
