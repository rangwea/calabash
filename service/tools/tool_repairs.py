"""Local, consent-gated repair requests; never store raw exception messages."""

import ast
import hashlib
import io
import json
import re
import tokenize
from contextlib import closing
from uuid import uuid4
from datetime import datetime, timezone


def exception_kind(error):
    from service.tools.tool_runtime import ToolEntryPointError
    if isinstance(error, ToolEntryPointError):
        return 'ToolEntryPointError'
    name = type(error).__name__
    allowed = {"Exception", "ValueError", "TypeError", "NameError", "UnboundLocalError", "KeyError", "AttributeError", "ImportError", "ModuleNotFoundError", "SyntaxError", "RuntimeError", "NotImplementedError", "AssertionError", "OverflowError", "OSError", "TimeoutError", "PermissionError", "FileNotFoundError", "FileExistsError", "IsADirectoryError", "NotADirectoryError", "IndexError", "ZeroDivisionError", "UnicodeError", "UnicodeDecodeError", "UnicodeEncodeError", "StopIteration", "StopAsyncIteration", "ExceptionGroup"}
    return name if name in allowed else 'ToolError'


def initialize(db):
    db.execute("CREATE TABLE IF NOT EXISTS tool_repairs (id TEXT PRIMARY KEY, chat_id TEXT, data TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending', started TEXT)")
    db.execute("UPDATE tool_repairs SET state='failed' WHERE state='running' AND started < datetime('now','-10 minutes')")


def capture(error, project, name, *, preview_key=None, context=None, phase="render", log_run_id=None):
    from service.chat import ai_chat
    from service.tools import preview_service
    from service.files import tool_inputs
    path = ai_chat.tool_path(project, name)
    chat_id = None
    if preview_key:
        owner, chat_id = tool_inputs.owner(context, preview_key)
        if owner != f"tool:{project}/{name}" or not chat_id:
            raise ValueError("Unbound preview")
        path = preview_service.get_preview_file(preview_key)
    seen, chain = set(), []
    while id(error) not in seen and len(chain) < 8:
        seen.add(id(error))
        chain.append(error)
        # "raise ... from None" suppresses incidental implementation details
        # such as inspect.Signature.bind's internal StopIteration. An explicit
        # cause still takes priority, even though Python marks context suppressed.
        nested = error.__cause__
        if nested is None and not error.__suppress_context__:
            nested = error.__context__
        if nested is None or id(nested) in seen or len(chain) >= 8:
            break
        error = nested
    frames = []
    from pathlib import Path
    for linked in chain:
        tb = linked.__traceback__
        while tb:
            if Path(tb.tb_frame.f_code.co_filename).resolve() == path.resolve() and tb.tb_lineno not in frames:
                frames.append(tb.tb_lineno)
            tb = tb.tb_next
    kind = exception_kind(error)
    if isinstance(error, SyntaxError) and error.filename and Path(error.filename).resolve() == path.resolve():
        frames.append(error.lineno)
    data = {"project": project, "name": name, "preview_key": preview_key, "context": context,
            "phase": phase, "exception": kind, "lines": frames[-3:], "revision": hashlib.sha256(path.read_bytes()).hexdigest()}
    from core import tool_run_logs
    candidate = tool_run_logs._active.get(log_run_id or tool_run_logs.current_id())
    if candidate and (candidate.project, candidate.name, candidate.preview_key) != (project, name, preview_key):
        candidate = None
    log_run_id = candidate.id if candidate else None
    isolated_run = None
    if not log_run_id:
        isolated_run = tool_run_logs.start(project, name, preview_key=preview_key)
        log_run_id = isolated_run.id
    data['log_run_id'] = log_run_id
    report_id = uuid4().hex
    from service.tools import tool_diagnostics
    data['captured_at'] = datetime.now(timezone.utc).isoformat()
    try:
        data['log_window'] = tool_diagnostics.record_failure(data, chain[0])
    finally:
        if isolated_run:
            isolated_run.close()
    with closing(ai_chat.connect()) as db, db:
        db.execute("INSERT INTO tool_repairs(id,chat_id,data) VALUES(?,?,?)", (report_id, chat_id, json.dumps(data)))
    return report_id


def get(report_id):
    from service.chat import ai_chat
    with closing(ai_chat.connect()) as db:
        row = db.execute("SELECT chat_id,data,state FROM tool_repairs WHERE id=?", (report_id,)).fetchone()
    if not row:
        raise ValueError("Repair request unavailable")
    return dict(id=report_id, chat_id=row[0], **json.loads(row[1]), state=row[2])


def summary(report):
    keys = ("project", "name", "phase", "exception", "lines", "captured_at", "revision", "log_run_id")
    return json.dumps({**{key: report[key] for key in keys if key in report},
                       'source': 'preview' if report.get('preview_key') else 'published'}, ensure_ascii=False, indent=2)


def model_fingerprint():
    from service.chat.model_providers import active
    return hashlib.sha256(json.dumps(active(), sort_keys=True).encode()).hexdigest()


def approve(report_id, fingerprint):
    from service.chat import ai_chat
    if fingerprint != model_fingerprint():
        raise ValueError("Model configuration changed; confirm again")
    report = get(report_id)
    if report["state"] not in {"pending", "failed"}:
        return report["chat_id"]
    from service.tools import tool_diagnostics
    if not report.get('log_window') or not tool_diagnostics.is_latest(report) or tool_diagnostics.current_revision(report) != report['revision']:
        raise ValueError('The failure is stale; retry the tool and confirm its new error')
    chat_id = report["chat_id"] or ai_chat.create_tool_chat(report["project"], report["name"], report["name"])
    with closing(ai_chat.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        if not db.execute("SELECT 1 FROM chats WHERE id=? AND deleted=0", (chat_id,)).fetchone():
            raise ValueError("Original conversation was deleted")
        data = {k: v for k, v in report.items() if k not in {"id", "state", "chat_id"}}
        data["model_fingerprint"] = fingerprint
        db.execute("UPDATE tool_repairs SET chat_id=?,data=?,state='queued' WHERE id=? AND state IN ('pending','failed')", (chat_id, json.dumps(data), report_id))
    return chat_id


def delete_chat_references(db, chat_id):
    db.execute('DELETE FROM tool_repairs WHERE chat_id=?', (chat_id,))


def claim(chat_id):
    from service.chat import ai_chat
    with closing(ai_chat.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        if not db.execute("SELECT 1 FROM chats WHERE id=? AND deleted=0", (chat_id,)).fetchone():
            return None
        if db.execute("SELECT 1 FROM tool_repairs WHERE chat_id=? AND state='running'", (chat_id,)).fetchone():
            return None
        row = db.execute("SELECT id FROM tool_repairs WHERE chat_id=? AND state='queued' ORDER BY rowid LIMIT 1", (chat_id,)).fetchone()
        if not row:
            return None
        data = json.loads(db.execute("SELECT data FROM tool_repairs WHERE id=?", (row[0],)).fetchone()[0])
        data["attempt"] = uuid4().hex
        db.execute("UPDATE tool_repairs SET state='running',started=CURRENT_TIMESTAMP,data=? WHERE id=?", (json.dumps(data), row[0]))
    return get(row[0])


def finish(report_id, success, attempt=None):
    from service.chat import ai_chat
    with closing(ai_chat.connect()) as db, db:
        if attempt:
            row = db.execute("SELECT data FROM tool_repairs WHERE id=? AND state='running'", (report_id,)).fetchone()
            if not row or json.loads(row[0]).get("attempt") != attempt:
                return
        db.execute("UPDATE tool_repairs SET state=? WHERE id=?", ("completed" if success else "failed", report_id))
    from core.tool_run_logs import cleanup
    cleanup()


class RepairSession:
    """A repair cannot read attachments, change targets or execute code."""

    def __init__(self, report):
        self.report = report
        self.read_revision = None
        self.diagnosed_revision = None
        self.secrets = {}

    def redact(self, content):
        """Keep literal credentials local and restore opaque placeholders on write."""
        from service.chat import model_providers
        values = [c.get("key") for c in model_providers.load()["connections"].values()]
        try:
            tree = ast.parse(content)
        except SyntaxError:
            # Invalid Python still needs repair; conservatively hide all literals.
            for token in tokenize.generate_tokens(io.StringIO(content).readline):
                if token.type == tokenize.STRING:
                    try:
                        value = ast.literal_eval(token.string)
                    except (ValueError, SyntaxError):
                        continue
                    if isinstance(value, str):
                        values.append(value)
            tree = ast.Module(body=[], type_ignores=[])
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if node.value and any(any(word in ast.unparse(target).lower() for word in ("password", "secret", "token", "api_key", "authorization")) for target in targets):
                    values.extend(n.value for n in ast.walk(node.value) if isinstance(n, ast.Constant) and isinstance(n.value, str))
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values, strict=True):
                    if isinstance(key, ast.Constant) and isinstance(key.value, str) and any(word in key.value.lower() for word in ("password", "secret", "token", "api_key", "authorization")):
                        values.extend(n.value for n in ast.walk(value) if isinstance(n, ast.Constant) and isinstance(n.value, str))
            if isinstance(node, ast.keyword) and node.arg and any(word in node.arg.lower() for word in ("password", "secret", "token", "api_key", "authorization")):
                values.extend(n.value for n in ast.walk(node.value) if isinstance(n, ast.Constant) and isinstance(n.value, str))
        for value in sorted({v for v in values if v}, key=len, reverse=True):
            if value in content:
                placeholder = "REDACTED_CREDENTIAL_" + uuid4().hex
                self.secrets[placeholder] = value
                content = content.replace(value, placeholder)
        return content

    def execute(self, operation, args):
        from service.chat import ai_chat
        from service.tools import preview_service
        from service.tools.tool_runtime import validate_tool_entrypoint
        report = self.report
        if report.get("attempt"):
            current = get(report["id"])
            with closing(ai_chat.connect()) as db, db:
                valid = db.execute("SELECT 1 FROM chats WHERE id=? AND deleted=0", (report["chat_id"],)).fetchone()
                if not valid or current["state"] != "running" or current.get("attempt") != report["attempt"]:
                    raise ValueError("Repair approval expired")
                db.execute("UPDATE tool_repairs SET started=CURRENT_TIMESTAMP WHERE id=?", (report["id"],))
        if operation == "read_component_api":
            from service.tools.component_api import read_api
            return read_api(args.get("component"))
        if operation == 'read_tool_logs':
            if not report.get('attempt'):
                return {'error': 'Diagnostics require a user-confirmed active repair'}
            if not {'project', 'name'} <= set(args) or set(args) - {'project', 'name', 'offset', 'limit', 'query'} or any(args.get(key) != report[key] for key in ('project', 'name')):
                return {'error': 'Diagnostics are restricted to the confirmed tool'}
            if not self.read_revision:
                return {'error': 'Read current tool code and revision before diagnostics'}
            from service.tools import tool_diagnostics
            if tool_diagnostics.current_revision(report) != self.read_revision:
                return {'error': 'Code changed; read the current code again'}
            # Read the live approval, not caller-supplied fields or a checkpoint.
            current = get(report['id'])
            result = tool_diagnostics.read(current, **{key: args[key] for key in ('offset', 'limit', 'query') if key in args})
            if result['status'] == 'current':
                self.diagnosed_revision = result['current_revision']
            return result
        if operation not in {"read_tool", "write_tool", "validate_tool", "preview_tool"} or any(args.get(k) != report[k] for k in ("project", "name")):
            return {"error": "Repair is restricted to the referenced tool code"}
        path = ai_chat.tool_path(report["project"], report["name"])
        if report["preview_key"]:
            path = preview_service.get_preview_file(report["preview_key"])
        data = path.read_bytes()
        revision = hashlib.sha256(data).hexdigest()
        if operation == "read_tool":
            self.read_revision = revision
            return {"content": self.redact(data.decode()), "revision": revision}
        content = args.get("content", "")
        if any(placeholder not in self.secrets for placeholder in re.findall(r"REDACTED_CREDENTIAL_[a-f0-9]+", content)):
            return {"error": "Credential placeholders expired; read current code before editing"}
        for placeholder, secret in self.secrets.items():
            content = content.replace(placeholder, secret)
        validate_tool_entrypoint(content)
        if operation == "validate_tool":
            return {"validated": True, "executed": False}
        if report.get('attempt') and self.diagnosed_revision != revision:
            return {'error': 'Read current code and read_tool_logs before saving. If the code changed, ask the user to retry manually for a fresh failure.'}
        if self.read_revision != revision or (operation == "write_tool" and args.get("revision") != revision):
            return {"error": "Read current code and revision before editing"}
        temp = path.with_suffix(f".{uuid4().hex}.tmp")
        try:
            temp.write_text(content, encoding="utf-8")
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)
        self.read_revision = None
        if report["preview_key"]:
            url = f"/preview/{report['preview_key']}?context={report['context']}"
        else:
            from service.files import tool_inputs
            # A published tool is still saved in place, but manual retry belongs
            # in this conversation's preview rather than navigating away.
            preview = preview_service.create_temporary_preview(content)
            if not preview.get("success"):
                raise ValueError("Unable to prepare repair preview")
            chat_id = report["chat_id"] or ai_chat.create_tool_chat(report["project"], report["name"], report["name"])
            token = tool_inputs.create(chat_id, preview["key"], [], tool_key=f"tool:{report['project']}/{report['name']}")
            url = f"{preview['preview_url']}?context={token}"
        return {"success": True, "requires_manual_run": True, "validation": "static_only", "executed": False, "runtime_verified": False, "source": "preview" if report['preview_key'] else "published", "preview_url": url, "url": url}
