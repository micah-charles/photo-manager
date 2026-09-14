import tempfile
import unittest
from pathlib import Path

from photovault.catalog.consolidation import build_consolidation_plan, execute_consolidation


class ConsolidationTests(unittest.TestCase):
    def test_pairs_two_folders_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            jpeg_root, raw_root, destination = root / "jpeg", root / "raw", root / "organized"
            jpeg_root.mkdir(); raw_root.mkdir()
            (jpeg_root / "DSC_0001.JPG").write_bytes(b"jpeg-data")
            (raw_root / "DSC_0001.NEF").write_bytes(b"raw-data")
            (jpeg_root / "DSC_0002.JPG").write_bytes(b"jpeg-only")
            (jpeg_root / "VID_0001.MP4").write_bytes(b"video-data")
            plan = build_consolidation_plan((jpeg_root, raw_root), destination)
            self.assertEqual(len(plan.pairs), 3)
            self.assertEqual(len(plan.moves), 4)
            self.assertEqual(len(plan.videos), 1)
            self.assertEqual(len(plan.unpaired_jpegs), 1)
            self.assertEqual(len(plan.unpaired_raw), 0)
            result = execute_consolidation(plan)
            self.assertEqual(result["moved"], 4)
            self.assertEqual(len(list(destination.glob("????-??-??"))), 1)

    def test_conflict_aborts_without_moving(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root / "source"; destination = root / "organized"
            source.mkdir(); (source / "DSC_0001.JPG").write_bytes(b"one")
            plan = build_consolidation_plan((source,), destination)
            target = plan.actions[0].destination; target.parent.mkdir(parents=True); target.write_bytes(b"different")
            conflict = build_consolidation_plan((source,), destination)
            self.assertEqual(len(conflict.conflicts), 1)
            with self.assertRaises(ValueError): execute_consolidation(conflict)
            self.assertTrue((source / "DSC_0001.JPG").exists())
