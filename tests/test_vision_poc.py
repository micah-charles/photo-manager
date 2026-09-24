import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from photovault.vision_poc import VisionPocError, analyze_images, template_analysis, validate_payload


def sample_payload():
    return {
        "schema_version": 1,
        "engine": "apple-vision",
        "os_version": "macOS test",
        "face_request_revision": 3,
        "human_request_revision": 1,
        "images": [{
            "source": "/private/photos/IMG 001.jpg",
            "filename": "IMG 001.jpg",
            "width": 1200,
            "height": 800,
            "exif_orientation": 1,
            "coordinate_space": "oriented",
            "box_convention": "normalized-top-left",
            "elapsed_ms": 12.5,
            "faces": [{"box": {"left": 0.4, "top": 0.1, "right": 0.5, "bottom": 0.25}, "confidence": 0.97}],
            "subjects": [{"label": "person", "box": {"left": 0.2, "top": 0.1, "right": 0.7, "bottom": 0.95}, "confidence": 0.88}],
        }],
        "errors": [],
    }


class VisionPocTests(unittest.TestCase):
    def test_maps_native_observations_to_existing_template_analysis_contract(self):
        result = template_analysis(sample_payload()["images"][0])
        self.assertEqual(result["coordinate_space"], "oriented")
        self.assertEqual(result["faces"][0]["top"], 0.1)
        self.assertEqual(result["subjects"][0]["label"], "person")
        self.assertEqual(result["subjects"][0]["box"]["bottom"], 0.95)

    def test_rejects_out_of_bounds_boxes_and_wrong_coordinate_convention(self):
        payload = sample_payload()
        payload["images"][0]["faces"][0]["box"]["left"] = -0.01
        with self.assertRaisesRegex(VisionPocError, "outside the normalized image bounds"):
            validate_payload(payload)
        image = sample_payload()["images"][0]
        image["coordinate_space"] = "original"
        with self.assertRaisesRegex(VisionPocError, "unknown Vision coordinate convention"):
            template_analysis(image)

    def test_runs_one_argument_safe_local_swift_batch_without_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "photo with spaces.jpg"
            image.write_bytes(b"only a mocked local input")
            completed = subprocess.CompletedProcess([], 0, json.dumps(sample_payload()), "")
            with patch("photovault.vision_poc.sys.platform", "darwin"), \
                 patch("photovault.vision_poc.shutil.which", return_value="/usr/bin/swift"), \
                 patch("photovault.vision_poc.subprocess.run", return_value=completed) as run:
                payload = analyze_images([image])
            command = run.call_args.args[0]
            self.assertEqual(command[0], "/usr/bin/swift")
            self.assertEqual(command[-1], str(image.resolve()))
            self.assertNotIn("shell", run.call_args.kwargs)
            self.assertEqual(payload["engine"], "apple-vision")

    def test_refuses_non_macos_without_starting_a_process(self):
        with patch("photovault.vision_poc.sys.platform", "linux"), \
             patch("photovault.vision_poc.subprocess.run") as run:
            with self.assertRaisesRegex(VisionPocError, "macOS only"):
                analyze_images([Path("photo.jpg")])
            run.assert_not_called()

    def test_limits_batch_and_rejects_missing_input(self):
        with patch("photovault.vision_poc.sys.platform", "darwin"):
            with self.assertRaisesRegex(VisionPocError, "limited to 200"):
                analyze_images([Path("photo.jpg")] * 201)
            with self.assertRaisesRegex(VisionPocError, "does not exist"):
                analyze_images([Path("/path/that/does/not/exist.jpg")])


if __name__ == "__main__":
    unittest.main()
