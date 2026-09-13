from __future__ import annotations

import http.client
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from PIL import Image

from photovault.catalog.scanner import register_volume, scan_volume
from photovault.database.connection import connect
from photovault.platform.base import VolumeIdentity
from photovault.web.server import PhotoVaultHandler, ThreadingHTTPServer, load_collage_analysis_cache


class _Provider:
    def identify(self, path: Path) -> VolumeIdentity:
        return VolumeIdentity("test", "collage-job-volume", "Collage job volume")


class CollageJobTests(unittest.TestCase):
    def test_generate_returns_job_immediately_and_publishes_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "photos"
            root.mkdir()
            for index in range(2):
                Image.new("RGB", (80, 60), (index * 40, 80, 120)).save(root / f"photo-{index}.jpg")
            catalog = Path(directory) / "catalog.db"
            db = connect(catalog)
            volume_id = register_volume(db, root, _Provider())
            scan_volume(db, volume_id, root)
            asset_ids = [str(row[0]) for row in db.execute("SELECT id FROM assets ORDER BY id")]
            db.close()

            server = ThreadingHTTPServer(("127.0.0.1", 0), PhotoVaultHandler)
            server.catalog_path = catalog
            server.collage_runs = {}
            server.collage_jobs = {}
            server.collage_analysis_cache_path = Path(directory) / "analysis.json"
            server.collage_analysis_cache, server.collage_analysis_fingerprints = load_collage_analysis_cache(server.collage_analysis_cache_path)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.server_close)

            payload = json.dumps({"asset_ids": asset_ids, "providers": ["native"], "count": 1}).encode()
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            started = time.perf_counter()
            connection.request("POST", "/api/collage/generate", payload, {"Content-Type": "application/json"})
            response = connection.getresponse()
            queued = json.loads(response.read())
            self.assertEqual(response.status, 202)
            self.assertLess(time.perf_counter() - started, 2)

            for _ in range(60):
                connection.request("GET", f"/api/collage/jobs/{queued['job_id']}")
                job_response = connection.getresponse()
                job = json.loads(job_response.read())
                if job["status"] in {"complete", "failed"}:
                    break
                time.sleep(0.1)
            self.assertEqual(job["status"], "complete", job)
            self.assertEqual(len(job["result"]["candidates"]), 1)
            connection.close()


if __name__ == "__main__":
    unittest.main()
