import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from photovault.collage.analysis import discover_photos
from photovault.collage.models import Canvas, PageSpec, page_spec_from_dict
from photovault.collage.models import Cell, Crop, PhotoInput
from photovault.collage.analysis import FaceBox, PhotoAnalysis
from photovault.collage.crop import optimise_cell
from photovault.collage.providers import BSPProvider, CeweLayoutProvider, NativeProvider
from photovault.collage.poc.runner import run_poc, run_poc_photos


class CollagePocTests(unittest.TestCase):
    def test_page_spec_derives_preview_canvas_and_round_trips(self):
        portrait = page_spec_from_dict({"preset_id": "a4-portrait"})
        self.assertEqual((portrait.width_mm, portrait.height_mm, portrait.orientation), (210, 297, "portrait"))
        self.assertEqual((portrait.to_preview_canvas().width, portrait.to_preview_canvas().height), (848, 1200))
        spread = PageSpec(type="spread", width_mm=300, height_mm=300, preset_id="large-square")
        self.assertEqual((spread.to_preview_canvas().width, spread.to_preview_canvas().height), (1200, 600))

    def test_crop_optimizer_shifts_to_preserve_edge_face(self):
        photo = PhotoInput("p", Path("/tmp/p.jpg"), 1200, 800, analysis=PhotoAnalysis(1200, 800, None, (FaceBox(.72, .30, .92, .70, .9),)))
        cell = Cell("p", 0, 0, 400, 400, Crop(.0, .0, 1.0, .5))
        result = optimise_cell(cell, photo)
        self.assertTrue(result.crop_metadata["smart_crop_changed"])
        self.assertEqual(result.crop_metadata["faces_excluded"], 0)
        self.assertIsNone(result.crop_metadata["hard_rejection_reason"])

    def test_providers_return_structured_diverse_candidates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            photos = []
            for index in range(7):
                path = root / f"photo-{index}.jpg"
                Image.new("RGB", (900 if index % 2 else 600, 600 if index % 2 else 900), (index * 30, 80, 140)).save(path)
                from photovault.collage.analysis import analyse_photo
                photos.append(analyse_photo(path))
            all_candidates = []
            for provider in (NativeProvider(), CeweLayoutProvider(), BSPProvider()):
                all_candidates.extend(provider.generate(photos, Canvas(), 42, 10))
            self.assertEqual(len(all_candidates), 30)
            self.assertEqual({candidate.provider for candidate in all_candidates}, {"native", "bsp", "cewe-genetic"})
            cewe = next(candidate for candidate in all_candidates if candidate.provider == "cewe-genetic")
            self.assertEqual(cewe.metadata["upstream"], "vincedarley/cewe-layout")
            self.assertGreater(len({tuple((cell.x, cell.y, cell.width, cell.height) for cell in c.cells) for c in all_candidates}), 3)
            self.assertTrue(all(candidate.to_dict()["cells"] for candidate in all_candidates))

    def test_runner_writes_previews_contact_sheet_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root, output = Path(temp) / "input", Path(temp) / "out"
            root.mkdir()
            for index in range(6):
                Image.new("RGB", (800, 600), (index * 30, 100, 120)).save(root / f"photo-{index}.jpg")
            result = run_poc(root, output, limit=6)
            self.assertEqual(result["candidate_count"], 30)
            self.assertEqual(len(list((output / "previews").glob("*.jpg"))), 30)
            self.assertTrue((output / "contact-sheet.jpg").is_file())
            payload = json.loads((output / "candidates.json").read_text())
            self.assertEqual(len(payload), 30)
            document = json.loads((output / "documents" / f"{payload[0]['document_id']}.json").read_text())
            self.assertEqual(document["document_type"], "CollageDocument")
            self.assertEqual(document["document_id"], payload[0]["document_id"])
            self.assertEqual(document["frames"], document["cells"])

    def test_runner_can_select_provider_and_candidate_count(self):
        with tempfile.TemporaryDirectory() as temp:
            root, output = Path(temp) / "input", Path(temp) / "out"
            root.mkdir()
            for index in range(4):
                Image.new("RGB", (800, 600), (index * 30, 100, 120)).save(root / f"photo-{index}.jpg")
            result = run_poc(root, output, limit=4, providers=["bsp"], count=3)
            self.assertEqual(result["candidate_count"], 3)
            self.assertEqual(len(list((output / "previews").glob("*.jpg"))), 3)
            self.assertEqual(result["provider_seconds"].keys(), {"bsp"})

    def test_runner_can_write_a_sharper_view_mode_preview(self):
        with tempfile.TemporaryDirectory() as temp:
            root, output = Path(temp) / "input", Path(temp) / "out"
            root.mkdir()
            for index in range(3):
                Image.new("RGB", (800, 600), (index * 30, 100, 120)).save(root / f"photo-{index}.jpg")
            run_poc_photos(discover_photos(root, 3), output, providers=["native"], count=1, preview_long_edge=2400)
            document = json.loads(next((output / "documents").glob("*.json")).read_text())
            self.assertEqual((document["canvas"]["width"], document["canvas"]["height"]), (2400, 2400))

    def test_runner_persists_page_spec_and_uses_its_ratio(self):
        with tempfile.TemporaryDirectory() as temp:
            root, output = Path(temp) / "input", Path(temp) / "out"
            root.mkdir()
            for index in range(3):
                Image.new("RGB", (800, 600), (index * 30, 100, 120)).save(root / f"photo-{index}.jpg")
            spec = PageSpec(type="single", width_mm=210, height_mm=297, orientation="portrait", preset_id="a4-portrait")
            result = run_poc_photos(discover_photos(root, 3), output, providers=["native"], count=1, page_spec=spec)
            self.assertEqual(result["candidate_count"], 1)
            payload = json.loads(next((output / "documents").glob("*.json")).read_text())
            self.assertEqual(payload["page_spec"]["preset_id"], "a4-portrait")
            self.assertEqual((payload["canvas"]["width"], payload["canvas"]["height"]), (848, 1200))
