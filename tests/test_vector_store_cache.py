import shutil
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import vector_store as vector_module
from app.services.vector_store import VectorStoreService
from app.utils.atomic_io import write_json_atomic


class VectorStoreCacheManifestTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / "_tmp" / "vector_store_cache"
        if self.root.exists():
            shutil.rmtree(self.root)

        self.learning_dir = self.root / "database" / "learning_data"
        self.chats_dir = self.root / "database" / "chats_data"
        self.vector_dir = self.root / "database" / "vector_store"
        self.learning_dir.mkdir(parents=True)
        self.chats_dir.mkdir(parents=True)
        self.vector_dir.mkdir(parents=True)

        self.patches = [
            patch.object(vector_module, "LEARNING_DATA_DIR", self.learning_dir),
            patch.object(vector_module, "CHATS_DATA_DIR", self.chats_dir),
            patch.object(vector_module, "VECTOR_STORE_DIR", self.vector_dir),
        ]
        for p in self.patches:
            p.start()

        self.service = VectorStoreService.__new__(VectorStoreService)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        if self.root.exists():
            shutil.rmtree(self.root)

    def test_source_manifest_tracks_learning_and_chat_files(self):
        (self.learning_dir / "profile.txt").write_text("user facts", encoding="utf-8")
        (self.chats_dir / "chat_abc.json").write_text(
            '{"messages":[{"role":"user","content":"hello"}]}',
            encoding="utf-8",
        )

        manifest = self.service._build_source_manifest()
        paths = [source["path"] for source in manifest["sources"]]

        self.assertEqual(manifest["version"], vector_module.INDEX_MANIFEST_VERSION)
        self.assertEqual(paths, ["learning_data/profile.txt", "chats_data/chat_abc.json"])

    def test_cache_is_invalidated_when_source_file_changes(self):
        source = self.learning_dir / "profile.txt"
        source.write_text("one", encoding="utf-8")

        current_manifest = self.service._build_source_manifest()
        (self.vector_dir / vector_module.INDEX_FAISS_FILE).write_bytes(b"fake-faiss")
        (self.vector_dir / vector_module.INDEX_PICKLE_FILE).write_bytes(b"fake-pkl")
        write_json_atomic(
            self.vector_dir / vector_module.INDEX_MANIFEST_FILE,
            current_manifest,
        )

        self.assertTrue(self.service._cache_is_valid(current_manifest))

        source.write_text("one plus changed content", encoding="utf-8")
        changed_manifest = self.service._build_source_manifest()

        self.assertFalse(self.service._cache_is_valid(changed_manifest))

    def test_cache_manifest_ignores_recent_chat_history_until_it_stabilizes(self):
        chat_file = self.chats_dir / "chat_recent.json"
        chat_file.write_text(
            '{"messages":[{"role":"user","content":"hello"}]}',
            encoding="utf-8",
        )

        manifest_now = self.service._build_cache_manifest()
        paths_now = [source["path"] for source in manifest_now["sources"]]
        self.assertEqual(paths_now, [])

        old_time = time.time() - (vector_module.CHAT_HISTORY_CACHE_STABILIZATION_SECONDS + 5)
        chat_file.touch()
        import os
        os.utime(chat_file, (old_time, old_time))

        manifest_stable = self.service._build_cache_manifest()
        paths_stable = [source["path"] for source in manifest_stable["sources"]]
        self.assertEqual(paths_stable, ["chats_data/chat_recent.json"])


class VectorStoreStartupResilienceTests(unittest.TestCase):
    def test_app_main_import_does_not_require_optional_vector_deps(self):
        code = """
import sys
for name in (
    "langchain_text_splitters",
    "langchain_huggingface",
    "langchain_community.vectorstores",
    "langchain_core.documents",
    "sentence_transformers",
    "pyarrow",
):
    sys.modules[name] = None
import app.main
print("ok")
"""

        result = subprocess.run(
            [sys.executable, "-c", code],
            text=True,
            capture_output=True,
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok", result.stdout)

    def test_create_vector_store_degrades_with_one_warning_when_disabled(self):
        service = VectorStoreService()

        with patch.dict(os.environ, {"JARVIS_ENABLE_VECTOR_STORE": ""}, clear=False):
            with self.assertLogs("J.A.R.V.I.S", level="WARNING") as logs:
                self.assertIsNone(service.create_vector_store())
                self.assertIsNone(service.create_vector_store())

        self.assertEqual(len(logs.output), 1)
        self.assertIn("Retrieval degraded", logs.output[0])
        status = service.status()
        self.assertFalse(status["available"])
        self.assertTrue(status["degraded"])
        self.assertIn("JARVIS_ENABLE_VECTOR_STORE", status["reason"])

    def test_health_reports_degraded_retrieval_status(self):
        code = """
import asyncio
import json
import app.main as main
from app.services.vector_store import VectorStoreService
service = VectorStoreService()
service._degrade("test degraded retrieval")
main.vector_store_service = service
response = asyncio.run(main.health())
print(json.dumps(response["retrieval"]))
"""

        result = subprocess.run(
            [sys.executable, "-c", code],
            text=True,
            capture_output=True,
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        retrieval = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(retrieval["reason"], "test degraded retrieval")
        self.assertTrue(retrieval["degraded"])


if __name__ == "__main__":
    unittest.main()
