"""Offline acceptance for a packaged native app using only synthetic tool data.

Run from the repository: uv run python -m scripts.check_electron_package [App path].
"""

import json
import os
import pathlib
import queue
import re
import subprocess
import sys
import tempfile
import threading
import urllib.parse
import urllib.request

from service.tools.tool_templates import base_template

root = pathlib.Path(__file__).resolve().parents[1]
if len(sys.argv) > 1:
    package = pathlib.Path(sys.argv[1]).resolve()
    app = package / ("resources" if os.name == "nt" else "Contents/Resources")
else:
    app = pathlib.Path(json.loads((root / "dist/electron/package-layout.json").read_text())["resources"])
with tempfile.TemporaryDirectory(prefix="calabash-installed-smoke-") as temporary:
    env = {
        **os.environ,
        "HOME": temporary,
        "USERPROFILE": temporary,
        "PYTHONUTF8": "1",
        "PATH": str(pathlib.Path(os.environ["SystemRoot"]) / "System32") if os.name == "nt" else "/usr/bin:/bin",
        "CALABASH_FRONTEND_RUNTIME": str(app / "calabash/frontend-runtime"),
        "CALABASH_HARNESS_EMBEDDED": "1",
    }
    binary = app / "calabash/backend" / ("calabash-backend.exe" if os.name == "nt" else "calabash-backend")
    with open(pathlib.Path(temporary) / "executor.log", "w+") as error:
        process = subprocess.Popen(
            [str(binary)],
            cwd=temporary,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=error,
            text=True,
            encoding="utf-8",
        )
        sequence = 0
        responses = queue.Queue()
        def collect():
            for line in process.stdout:
                responses.put(line)
            responses.put(None)
        threading.Thread(target=collect, daemon=True).start()

        def call(method, params):
            global sequence
            sequence += 1
            process.stdin.write(
                json.dumps({"id": str(sequence), "method": method, "params": params})
                + "\n"
            )
            process.stdin.flush()
            try:
                line = responses.get(timeout=120)
            except queue.Empty:
                raise TimeoutError(method) from None
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
            from scripts.office_library_smoke import BACKEND
            files = base_template("demo", "installed_smoke")
            files["backend/main.py"] += "\n    install_office_smoke(app, sdk)\n    @app.get('/api/runtime-pid')\n    async def runtime_pid():\n        import os\n        return {'pid': os.getpid()}\n" + BACKEND
            for path, content in files.items():
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
            page = urllib.request.Request(origin + "/", headers={"Authorization": "Bearer " + token})
            with urllib.request.urlopen(page, timeout=10) as response:
                html = response.read().decode()
            modules = re.findall(r'src="(/assets/[^"?]+\.js)"', html)
            assert modules, "Preview must use the verified production build"
            for module in ["/api/sdk/runtime-guard.js", *modules]:
                resource = urllib.request.Request(origin + module, headers={"Authorization": "Bearer " + token})
                with urllib.request.urlopen(resource, timeout=10) as response:
                    assert response.status == 200, module
                    assert "javascript" in response.headers.get("Content-Type", ""), module
                    assert response.read(), module
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
            from scripts.office_library_smoke import verify
            verify(origin, token)
            value = call("workspace.preview", {"session": "smoke", "refresh": True})
            parsed = urllib.parse.urlsplit(value["url"])
            token = urllib.parse.parse_qs(parsed.query)["session"][0]
            origin = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
            request = urllib.request.Request(origin + "/api/message", headers={"Authorization": "Bearer " + token})
            assert json.load(urllib.request.urlopen(request, timeout=10)) == {"message": "Installed runtime"}
            database = pathlib.Path(temporary) / ".calabash/tools/demo/installed_smoke/data.sqlite"
            assert database.is_file(), "Tool database must be directly under the tool directory"
            assert call("workspace.publish", {"session": "smoke", "expected": value["revision"], "replace_revision": "", "confirmed": True})["saved"]
            official = call("tools.open", {"project": "demo", "name": "installed_smoke"})
            parsed = urllib.parse.urlsplit(official["url"])
            token = urllib.parse.parse_qs(parsed.query)["session"][0]
            origin = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
            request = urllib.request.Request(origin + "/api/message", headers={"Authorization": "Bearer " + token})
            assert json.load(urllib.request.urlopen(request, timeout=10)) == {"message": "Installed runtime"}
            pid_request = urllib.request.Request(origin + "/api/runtime-pid", headers={"Authorization": "Bearer " + token})
            assert json.load(urllib.request.urlopen(pid_request, timeout=10))["pid"] == process.pid
            tasks = call("schedules.action", {"operation": "tasks", "arguments": {"project": "demo", "name": "installed_smoke"}})
            assert tasks and tasks[0]["name"] == "export_saved_message", tasks
            rows = call("schedules.action", {"operation": "create", "arguments": {"project": "demo", "name": "installed_smoke", "task": tasks[0]["name"], "minutes": 60, "confirmed": True}})
            call("schedules.action", {"operation": "run", "arguments": {"id": rows[0]["id"], "confirmed": True}})
            import time
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                plans = call("schedules.action", {"operation": "list", "arguments": {}})
                if plans[0]["status"] != "running":
                    break
                time.sleep(.05)
            assert plans[0]["status"] == "succeeded", plans
            call("schedules.action", {"operation": "remove", "arguments": {"id": rows[0]["id"], "confirmed": True}})
            assert call("app.prepare_exit", {}) is True
            print(
                "PASS installed frozen runtime: no system Node/Python; real draft, React build, preview, tool-root SQLite state across refresh and publication, shared Python PID, authorized scheduled task, Python API and tool-owned Excel/Word library processing; no source cwd"
            )
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=10)
