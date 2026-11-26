import fcntl
import os
import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from webhub.manager import Manager
from webhub.server import create_app
from webhub.storage import inventory


def fixture_loader(_key):
    """Small offline pipeline with the Hub's real blob/snapshot layout."""
    cache = Path(os.environ["HF_HUB_CACHE"])
    repo = cache / "models--seed--test"
    blob = repo / "blobs" / "abc"
    link = repo / "snapshots" / "rev" / "model.bin"
    if not link.exists():
        blob.parent.mkdir(parents=True)
        blob.write_bytes(b"1234")
        link.parent.mkdir(parents=True)
        link.symlink_to("../../blobs/abc")

    def convert(*_args):
        yield b"preview", None
        yield b"final", (16000, [0.0, 0.5, -0.5] * 100)

    return convert


def failing_loader(_key):
    raise RuntimeError("fixture load failure")


class HubTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = Path(tmp.name)
        self.manager = Manager(self.data, loader=fixture_loader)
        self.addCleanup(self.manager.unload, shutdown=True)

    def wait_for(self, state):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            status = self.manager.status()[0]
            if status["state"] == state:
                return status
            time.sleep(0.05)
        self.fail(f"Expected {state}, got {status}")

    def test_api_conversion_unload_and_persistence(self):
        with patch.dict(os.environ, SEEDVC_DATA=str(self.data), SEEDVC_PRELOAD=""):
            with TestClient(create_app(self.manager)) as client:
                self.assertEqual(client.get("/healthz").status_code, 200)
                for key in self.manager.slots:
                    self.assertIn(f"/tools/{key}/", client.get("/").text)
                    self.assertIn("components", client.get(f"/tools/{key}/config").json())
                self.assertEqual(client.post("/api/models/unknown/load").status_code, 404)
                self.assertEqual(client.post("/api/models/speech/load").status_code, 202)
                self.assertEqual(self.wait_for("loaded")["disk_bytes"], 4)
                pid = self.manager.slots["speech"].process.pid
                client.post("/api/models/speech/load")
                self.assertEqual(self.manager.slots["speech"].process.pid, pid)

                gen = self.manager.convert("speech", "source", "reference")
                self.assertEqual(next(gen), (b"preview", None))
                self.assertEqual(client.post("/api/models/unload").status_code, 409)
                (_, path), = list(gen)
                with wave.open(path) as audio:
                    self.assertEqual((audio.getframerate(), audio.getnframes()), (16000, 300))
                for _ in range(2):
                    self.assertEqual(client.post("/api/models/unload").status_code, 200)
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)

            fresh = Manager(self.data, loader=fixture_loader)
            with TestClient(create_app(fresh)) as client:
                state = client.get("/api/models").json()[0]
                self.assertEqual((state["state"], state["download"]), ("unloaded", "downloaded"))
                self.assertEqual(state["files"], [{"file": "seed/test/model.bin", "bytes": 4}])
                name = Path(path).name
                self.assertIn(name, client.get("/outputs/").text)
                self.assertEqual(client.get("/outputs/files/" + name).content, Path(path).read_bytes())
                self.assertNotEqual(list(fresh.convert("speech"))[-1][1], path)

    def test_failure_retry_and_cancelled_stream(self):
        self.manager.loader = failing_loader
        self.manager.load("speech")
        self.assertIn("fixture load failure", self.wait_for("error")["error"])
        self.manager.loader = fixture_loader
        gen = self.manager.convert("speech")
        next(gen)
        gen.close()
        status = self.wait_for("unloaded")
        self.assertFalse(status["busy"])
        # Removal of a downloaded blob must invalidate the cached bundle.
        next(self.manager.slots["speech"].cache.glob("*/blobs/abc")).unlink()
        self.assertNotEqual(self.manager.status()[0]["download"], "downloaded")

    def test_partial_is_not_an_active_transfer(self):
        cache = self.manager.slots["style"].cache
        blob = cache / "models--seed--test" / "blobs" / "abc.incomplete"
        lock = cache / ".locks" / "models--seed--test" / "abc.lock"
        blob.parent.mkdir(parents=True)
        blob.write_bytes(b"partial")
        lock.parent.mkdir(parents=True)
        with lock.open("wb") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            status = inventory(cache, loading=True)
            self.assertEqual(status["download"], "downloading")
            self.assertEqual(status["transfers"], [{"repo": "seed/test", "bytes": 7}])
        self.assertEqual(inventory(cache, loading=True)["download"], "partial")
