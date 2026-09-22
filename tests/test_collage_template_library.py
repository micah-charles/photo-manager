"""The browser library must still pass the existing Python import/save contract."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from photovault.collage.design_formats import (
    to_collage_document, validate_and_repair_design_spec, validate_collage_document,
)

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("node"), "Node required for the shared composition engine")
class TemplateContractTests(unittest.TestCase):
    def test_every_family_imports_and_saves_without_losing_photos(self):
        script = """
const lib = require('./src/photovault/web/static/collage_template_library.js');
const outputs = [];
for (const f of lib.families) for (const preset of lib.presets) for (const count of [10, 15, 20, 60]) {
  const photos = Array.from({length: count}, (_, i) => ({asset_id: `photo-${i}`, width: i%3 ? 4000 : 3000, height: i%3 ? 3000 : 4000}));
  outputs.push(lib.build({familyId: f.id, photos, page: {preset_id: preset.id}, title: 'Painswick | 樹下同行', subtitle: '16 April 2026 · Our spring journey', caption: 'A day together beneath the trees.'}).spec);
}
console.log(JSON.stringify(outputs));
"""
        specs = json.loads(subprocess.check_output(["node", "-e", script], cwd=ROOT))
        for spec in specs:
            with self.subTest(family=spec["style"], page=spec["page_spec"]["preset_id"], count=len(spec["assets"])):
                ids = {a["asset_id"] for a in spec["assets"]}
                checked, report = validate_and_repair_design_spec(spec, ids)
                self.assertEqual(report["errors"], [])
                doc = to_collage_document(checked, asset_map={i: {} for i in ids})
                saved = validate_collage_document(doc, ids)
                photos = [e for e in saved["elements"] if e["type"] == "photo"]
                self.assertEqual(len(photos), len(ids))
                self.assertEqual({e["photo_id"] for e in photos}, ids)
                self.assertTrue(all(not e.get("locked") for e in photos))
                self.assertEqual(saved["metadata"]["selection_asset_ids"], [a["asset_id"] for a in spec["assets"]])


if __name__ == "__main__":
    unittest.main()
