import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from photovault.collage.models import Canvas
from photovault.collage.models import Cell, Crop, PhotoInput
from photovault.collage.analysis import FaceBox, PhotoAnalysis
from photovault.collage.crop import optimise_cell
from photovault.collage.providers import BSPProvider, CeweLayoutProvider, NativeProvider
from photovault.collage.poc.runner import run_poc


class CollagePocTests(unittest.TestCase):
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
