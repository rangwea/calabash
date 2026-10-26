import json
import os
import subprocess
import sys
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch

from scripts import build_desktop_sidecar as builder

SKILL = Path(__file__).resolve().parents[1] / "agent/skills/calabash"


class BuiltinSkillTests(unittest.TestCase):
    def test_development_skill_links_to_builtin_source(self):
        root = SKILL.parents[2]
        self.assertTrue((root / ".agents/skills/calabash").is_symlink())
        self.assertEqual(SKILL, (root / ".agents/skills/calabash").resolve())
        self.assertIn("name: calabash", (SKILL / "SKILL.md").read_text())
        self.assertIn("Use $calabash", (SKILL / "agents/openai.yaml").read_text())

    def test_prelog_cli_supports_current_json_and_plain_protocol(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/api/tools/preview/list":
                    content = json.dumps(
                        {
                            "tools": [
                                {
                                    "key": "preview-current-key",
                                    "title": "Current preview",
                                    "created_at": "now",
                                }
                            ]
                        }
                    ).encode()
                elif self.path == "/api/tools/preview/log/current?lines=1":
                    content = b"first\nlast\n"
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.end_headers()
                self.wfile.write(content)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:

            def cli(*args):
                result = subprocess.run(
                    [
                        sys.executable,
                        str(SKILL / "scripts/tool-cli.py"),
                        "--server",
                        f"http://127.0.0.1:{server.server_port}",
                        *args,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                return result.stdout

            self.assertEqual(
                "preview-current-key",
                json.loads(cli("--json", "prelog"))["tools"][0]["key"],
            )
            self.assertEqual(
                "last\n",
                json.loads(cli("--json", "prelog", "current", "--lines", "1"))[
                    "content"
                ],
            )
            self.assertIn("Current preview", cli("prelog"))
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)

    def test_sidecar_still_bundles_skill_for_runtime_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            commands = []

            def build(command):
                commands.append(command)
                suffix = ".exe" if os.name == "nt" else ""
                (target / f"calabash-backend{suffix}").write_bytes(b"test binary")

            with (
                patch.object(builder, "BIN_DIR", target),
                patch.object(builder, "PYINSTALLER_WORK_DIR", target / "work"),
                patch.object(builder, "_host_triple", return_value="test-target"),
                patch.object(builder, "_run", build),
            ):
                builder.main()
            command = commands[0]
            resources = [
                command[i + 1]
                for i, value in enumerate(command)
                if value == "--add-data"
            ]
            self.assertIn(f"{builder.ROOT / 'package.json'}{os.pathsep}.", resources)
            self.assertIn(
                f"{builder.ROOT / 'component/context_menu.js'}{os.pathsep}component",
                resources,
            )
            source, _ = next(
                item.rsplit(os.pathsep, 1)
                for item in resources
                if item.endswith("agent/skills/calabash")
            )
            self.assertEqual(SKILL, Path(source))
            for name in (
                "SKILL.md",
                "scripts/validate-tool.py",
                "scripts/preview_log.py",
                "references/runtime-libraries.json",
                "references/file-tool.py",
            ):
                self.assertTrue((Path(source) / name).is_file(), name)

    def test_local_cli_create_publish_status_and_delete_without_server(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = {**os.environ, "CALABASH_HOME": str(root)}

            def cli(*args, success=True):
                result = subprocess.run(
                    [
                        sys.executable,
                        str(SKILL / "scripts/tool-cli.py"),
                        "--json",
                        *args,
                    ],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(
                    0 if success else 2,
                    result.returncode,
                    result.stderr + result.stdout,
                )
                return json.loads(result.stdout) if success else result

            cli("create", "demo", "cleanup_test")
            tool = root / "tools/demo/cleanup_test.py"
            self.assertTrue(tool.is_file())
            cli("publish", "demo", "cleanup_test", "--yes")
            state = cli("status", "demo", "cleanup_test")
            self.assertTrue(state["success"])
            self.assertTrue(state["state"]["published"])
            cli("delete", "demo", "cleanup_test", "--yes")
            self.assertFalse(tool.exists())
            cli("databases", success=False)
            cli("variables", success=False)
