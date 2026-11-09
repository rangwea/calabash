"""Offline acceptance for a packaged macOS app using only synthetic tool data.

Run from the repository: uv run python -m scripts.check_electron_package [App path].
"""

import json
import os
import pathlib
import select
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

from service.tools.tool_templates import base_template

app = (
    pathlib.Path(sys.argv[1])
    if len(sys.argv) > 1
    else pathlib.Path(__file__).resolve().parents[1]
    / "dist/electron/mac-arm64/Calabash.app"
).resolve() / "Contents/Resources"
with tempfile.TemporaryDirectory(prefix="calabash-installed-smoke-") as temporary:
    env = {
        **os.environ,
        "HOME": temporary,
        "PATH": "/usr/bin:/bin",
        "CALABASH_FRONTEND_RUNTIME": str(app / "calabash/frontend-runtime"),
        "CALABASH_HARNESS_EMBEDDED": "1",
    }
    binary = app / "calabash/backend/calabash-backend"
    with open(pathlib.Path(temporary) / "executor.log", "w+") as error:
        process = subprocess.Popen(
            [str(binary)],
            cwd=temporary,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=error,
            text=True,
        )
        sequence = 0

        def call(method, params):
            global sequence
            sequence += 1
            process.stdin.write(
                json.dumps({"id": str(sequence), "method": method, "params": params})
                + "\n"
            )
            process.stdin.flush()
            if not select.select([process.stdout], [], [], 120)[0]:
                raise TimeoutError(method)
            line = process.stdout.readline()
            if not line:
                error.seek(0)
                raise RuntimeError(error.read()[-4000:])
            result = json.loads(line)
            if "error" in result:
                error.seek(0)
                raise RuntimeError(str(result) + "\n" + error.read()[-4000:])
            return result["result"]

        try:
            assert call("tools.list", {}) == []
            for path, content in base_template("demo", "installed_smoke").items():
                call(
                    "agent.call",
                    {
                        "session": "smoke",
                        "call_id": "write-" + str(sequence),
                        "operation": "write_tool_file",
                        "arguments": {
                            "project": "demo",
                            "name": "installed_smoke",
                            "path": path,
                            "content": content,
                        },
                        "requested_preset": None,
                    },
                )
            result = call(
                "agent.call",
                {
                    "session": "smoke",
                    "call_id": "check",
                    "operation": "check_tool_build",
                    "arguments": {"project": "demo", "name": "installed_smoke"},
                    "requested_preset": None,
                },
            )
            assert result["state"] == "passed", result
            value = call("workspace.preview", {"session": "smoke", "refresh": False})
            parsed = urllib.parse.urlsplit(value["url"])
            token = urllib.parse.parse_qs(parsed.query)["session"][0]
            origin = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
            request = urllib.request.Request(
                origin + "/api/message",
                data=json.dumps({"text": "Installed runtime"}).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + token,
                },
            )
            result = json.load(urllib.request.urlopen(request, timeout=10))
            assert result["message"] == "Installed runtime", result
            from scripts.office_action_smoke import verify
            verify(origin, token)
            assert call("app.prepare_exit", {}) is True
            print(
                "PASS installed frozen runtime: no system Node/Python; real draft, React build, preview, Python API and Excel→Word Actions; no source cwd"
            )
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=10)
