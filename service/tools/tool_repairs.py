"""Local, consent-gated repair requests; never store raw exception messages."""

import ast
import hashlib
import io
import json
import tokenize
from contextlib import closing
from uuid import uuid4


def initialize(db):
    db.execute("CREATE TABLE IF NOT EXISTS tool_repairs (id TEXT PRIMARY KEY, chat_id TEXT, data TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending', started TEXT)")
    db.execute("UPDATE tool_repairs SET state='failed' WHERE state='running' AND started < datetime('now','-10 minutes')")


def capture(error, project, name, *, preview_key=None, context=None, phase="render"):
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
    seen = set()
    while id(error) not in seen:
        seen.add(id(error))
        nested = error.__cause__ or error.__context__
        if nested is None or id(nested) in seen:
            break
        error = nested
    frames = []
    tb = error.__traceback__
    while tb:
        if tb.tb_frame.f_code.co_filename == str(path):
            frames.append(tb.tb_lineno)
        tb = tb.tb_next
    kind = type(error).__name__
    if kind not in {"ValueError", "TypeError", "NameError", "KeyError", "AttributeError", "ImportError", "ModuleNotFoundError", "SyntaxError", "RuntimeError", "PermissionError", "FileNotFoundError", "IndexError", "ZeroDivisionError"}:
        kind = "ToolError"
    if isinstance(error, SyntaxError) and error.filename == str(path):
        frames.append(error.lineno)
    data = {"project": project, "name": name, "preview_key": preview_key, "context": context,
            "phase": phase, "exception": kind, "lines": frames[-3:], "revision": hashlib.sha256(path.read_bytes()).hexdigest()}
    from service.tools.tool_runtime import ToolEntryPointError
    if isinstance(error, ToolEntryPointError):
        from core.tool_api_contracts import api_errors
        # Recompute trusted diagnostics; never forward exception message text.
        try:
            errors = api_errors(ast.parse(path.read_text(encoding="utf-8")))
        except (OSError, SyntaxError, UnicodeError):
            errors = []
        if errors:
            data["diagnosis"] = {"problem": "invalid_component_api", "details": errors}
    # Never parse or forward arbitrary exception text: it can contain user data.
    # Python supplies structured AttributeError metadata for missing attributes.
    if isinstance(error, AttributeError):
        from service.tools.component_api import diagnose
        diagnosis = diagnose(error, path)
        if diagnosis:
            data["diagnosis"] = diagnosis
    report_id = uuid4().hex
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
    keys = ("project", "name", "phase", "exception", "lines", "diagnosis")
    return json.dumps({key: report[key] for key in keys if key in report}, ensure_ascii=False, indent=2)


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
    chat_id = report["chat_id"] or ai_chat.create_tool_chat(report["project"], report["name"], report["name"])
    with closing(ai_chat.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        if not db.execute("SELECT 1 FROM chats WHERE id=? AND deleted=0", (chat_id,)).fetchone():
            raise ValueError("Original conversation was deleted")
        data = {k: v for k, v in report.items() if k not in {"id", "state", "chat_id"}}
        data["model_fingerprint"] = fingerprint
        db.execute("UPDATE tool_repairs SET chat_id=?,data=?,state='queued' WHERE id=? AND state IN ('pending','failed')", (chat_id, json.dumps(data), report_id))
    return chat_id


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


class RepairSession:
    """A repair cannot read attachments, change targets or execute code."""

    def __init__(self, report):
        self.report = report
        self.read_revision = None
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
        for placeholder, secret in self.secrets.items():
            content = content.replace(placeholder, secret)
        validate_tool_entrypoint(content)
        if operation == "validate_tool":
            return {"validated": True, "executed": False}
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
        return {"success": True, "requires_manual_run": True, "preview_url": url, "url": url}
