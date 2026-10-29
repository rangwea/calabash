import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.tool_api import router
from service.tools import preview_service


class PreviewApiTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name, value in {
            "_TMP_DIR": self.root,
            "_PREVIEW_META_DIR": self.root / "_meta",
        }.items():
            patcher = patch.object(preview_service, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(preview_service, "get_preview_logger")
        patcher.start()
        self.addCleanup(patcher.stop)
        from core import tool_run_logs
        for target, value in [('logs_dir', self.root / 'logs'), ('app_dir', self.root)]:
            patcher = patch.object(tool_run_logs, target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_only_preview_routes_are_registered(self):
        self.assertEqual(
            {
                "/api/tools/preview/list",
                "/api/tools/preview/log/fixed/{username}/{tool_name}",
                "/api/tools/preview/log/{preview_key}",
                "/api/tools/preview/code/fixed/{username}/{tool_name}",
                "/api/tools/preview/code/{preview_key}",
                "/api/tools/preview",
                "/api/tools/preview/{username}/{tool_name}",
            },
            {route.path for route in router.routes},
        )
        for method, path in (
            ("GET", "/api/tools"),
            ("GET", "/api/tools/projects"),
            ("GET", "/api/tools/demo/hello"),
            ("GET", "/api/tools/demo/hello/state"),
            ("POST", "/api/tools/demo/hello/publish"),
            ("DELETE", "/api/tools/demo/hello"),
        ):
            self.assertEqual(404, self.client.request(method, path).status_code)

    def test_temporary_preview_validates_and_stores_without_execution(self):
        content = "raise RuntimeError('must not execute')\ndef main(): pass\n"
        response = self.client.post("/api/tools/preview", json={"content": content})
        self.assertEqual(200, response.status_code)
        result = response.json()
        key = result["key"]
        self.assertEqual(content.strip(), (self.root / f"{key}.py").read_text())
        self.assertEqual(f"/preview/{key}", result["url"])
        self.assertEqual(
            content.strip(), self.client.get(f"/api/tools/preview/code/{key}").text
        )
        self.assertEqual(
            key, self.client.get("/api/tools/preview/list").json()["tools"][0]["key"]
        )

    def test_invalid_temporary_preview_is_actionable_and_creates_no_code(self):
        for content, code in (
            ("print('legacy')", "missing_main"),
            ("def main(:", "invalid_syntax"),
        ):
            response = self.client.post("/api/tools/preview", json={"content": content})
            self.assertEqual(400, response.status_code)
            self.assertFalse(response.json()["success"])
            self.assertEqual(code, response.json()["code"])
            self.assertTrue(response.json()["next_action"])
        self.assertFalse(list(self.root.glob("*.py")))

    def test_preview_listing_requires_current_metadata_and_uses_key(self):
        (self.root / "orphan.py").write_text("def main(): pass")
        current = self.client.post("/api/tools/preview", json={"content": "def main(): pass"}).json()
        rows = self.client.get("/api/tools/preview/list").json()["tools"]
        self.assertEqual([current["key"]], [row["key"] for row in rows])
        self.assertNotIn("token", rows[0])
        self.assertEqual(current["url"], rows[0]["url"])

    def test_fixed_preview_reuses_key_and_reads_log_tail(self):
        url = "/api/tools/preview/demo/hello"
        first = self.client.post(url, json={"content": "def main(): return 1"}).json()
        second = self.client.post(url, json={"content": "def main(): return 2"}).json()
        self.assertEqual(first["key"], second["key"])
        self.assertEqual(
            "def main(): return 2",
            self.client.get("/api/tools/preview/code/fixed/demo/hello").text,
        )
        from core import tool_run_logs
        run = tool_run_logs.start('demo', 'hello', preview_key=first['key'])
        self.addCleanup(run.close)
        run.writer.write('first\nlast\n')
        # The API obtains the path through preview_service, whose globals are isolated above.
        response = self.client.get("/api/tools/preview/log/fixed/demo/hello?lines=1")
        self.assertEqual(200, response.status_code)
        self.assertEqual("last\n", response.text)
