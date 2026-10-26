"""Bounded single-tool ZIP interchange. Inspection never executes source code."""

import hashlib
import io
import json
import os
import stat
import tempfile
import time
import zlib
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from core.local_paths import tools_dir
from service.tools.tool_activity import is_tool_running
from service.tools.tool_manage_service import list_tools
from service.tools.tool_metadata import parse_tool_metadata
from service.tools.tool_runtime import validate_tool_entrypoint
from service.tools.tool_service import _validate_tool_identity

MAX_SOURCE = 1024 * 1024
MAX_MANIFEST = 16 * 1024
MAX_ARCHIVE = 2 * 1024 * 1024
FORMAT = "calabash-tool"


class ToolArchiveError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ToolPackage:
    project: str
    name: str
    source: bytes
    title: str
    description: str
    requires: str


def _identity(project, name):
    try:
        _validate_tool_identity(project, name)
    except (ValueError, TypeError):
        raise ToolArchiveError("identity") from None
    if name == "__init__" or project.startswith("_"):
        raise ToolArchiveError("identity")


def _package(project, name, source):
    _identity(project, name)
    if not source or len(source) > MAX_SOURCE:
        raise ToolArchiveError("limit")
    try:
        text = source.decode("utf-8")
        validate_tool_entrypoint(text)
        metadata = parse_tool_metadata(text)
    except (UnicodeError, ValueError, SyntaxError, RecursionError):
        raise ToolArchiveError("source") from None
    return ToolPackage(
        project,
        name,
        source,
        metadata.get("name") or name,
        metadata.get("description", ""),
        metadata.get("requires", ""),
    )


def _read_regular(path, limit):
    if Path(path).is_symlink():
        raise ToolArchiveError("path")
    descriptor = os.open(
        path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    )
    with os.fdopen(descriptor, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ToolArchiveError("limit")
        data = handle.read(limit + 1)
        if len(data) > limit:
            raise ToolArchiveError("limit")
        return data


def inspect_zip(path):
    """Read exact whitelisted entries into memory; never extract arbitrary paths."""
    try:
        data = _read_regular(path, MAX_ARCHIVE)
        with ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) != 2 or {entry.filename for entry in entries} != {
                "manifest.json",
                "tool.py",
            }:
                raise ToolArchiveError("format")
            for entry in entries:
                mode = entry.external_attr >> 16
                limit = MAX_SOURCE if entry.filename == "tool.py" else MAX_MANIFEST
                if (
                    entry.is_dir()
                    or entry.flag_bits & 1
                    or (stat.S_IFMT(mode) not in (0, stat.S_IFREG))
                    or entry.file_size > limit
                    or entry.compress_type not in (0, ZIP_DEFLATED)
                ):
                    raise ToolArchiveError("format")
            manifest = json.loads(archive.read("manifest.json"))
            if (
                not isinstance(manifest, dict)
                or manifest.get("format") != FORMAT
                or type(manifest.get("version")) is not int
                or manifest["version"] != 1
            ):
                raise ToolArchiveError("format")
            return _package(
                manifest.get("project"), manifest.get("name"), archive.read("tool.py")
            )
    except ToolArchiveError:
        raise
    except (
        BadZipFile,
        UnicodeError,
        ValueError,
        RuntimeError,
        NotImplementedError,
        RecursionError,
        zlib.error,
    ):
        raise ToolArchiveError("format") from None


def _target(project, name):
    _identity(project, name)
    root = Path(tools_dir()).resolve()
    path = root / project / f"{name}.py"
    sidecar = path.with_name(f"{path.name}.calabash.json")
    if (
        path.parent.is_symlink()
        or path.is_symlink()
        or sidecar.is_symlink()
        or (sidecar.exists() and not sidecar.is_file())
        or not path.resolve().is_relative_to(root)
    ):
        raise ToolArchiveError("path")
    return path, sidecar


def target_revision(project, name):
    path, _ = _target(project, name)
    try:
        return hashlib.sha256(_read_regular(path, MAX_SOURCE)).hexdigest()
    except FileNotFoundError:
        return None


def export_zip(project, name):
    path, _ = _target(project, name)
    package = _package(project, name, _read_regular(path, MAX_SOURCE))
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {"format": FORMAT, "version": 1, "project": project, "name": name}
            ),
        )
        archive.writestr("tool.py", package.source)
    return buffer.getvalue()


def install(package, project, name, *, expected_revision=None):
    """Create exclusively, or replace only after explicit approval of this revision."""
    package = _package(project, name, package.source)
    path, sidecar = _target(project, name)
    if is_tool_running(project, name):
        raise ToolArchiveError("busy")
    current = target_revision(project, name)
    if current is not None and expected_revision is None:
        raise ToolArchiveError("conflict")
    if current != expected_revision:
        raise ToolArchiveError("changed")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{name}-{uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(package.source)
        temporary.chmod(0o600)
        if current is None:
            try:
                os.link(temporary, path)
            except FileExistsError:
                raise ToolArchiveError("conflict") from None
        else:
            # Recheck immediately before replacing; no await or task execution occurs here.
            if target_revision(project, name) != expected_revision:
                raise ToolArchiveError("changed")
            temporary.replace(path)
        sidecar.unlink(missing_ok=True)
    finally:
        temporary.unlink(missing_ok=True)
    list_tools(project=project)
    return {"project": project, "name": name, "title": package.title}


@contextmanager
def export_delivery(project, name):
    """Prepare a private short-lived native save ticket, with browser fallback."""
    data = export_zip(project, name)
    directory = os.environ.get("CALABASH_SELECTION_DIR")
    if not directory:
        yield data, None
        return
    token = uuid4().hex
    ticket = Path(directory) / f"output-{token}.json"
    with tempfile.TemporaryDirectory(prefix="calabash-tool-export-") as temporary:
        path = Path(temporary) / f"{name}.zip"
        path.write_bytes(data)
        path.chmod(0o600)
        try:
            with ticket.open("x", encoding="utf-8") as handle:
                ticket.chmod(0o600)
                json.dump(
                    {"path": str(path), "size": len(data), "created": time.time()},
                    handle,
                )
            yield data, token
        finally:
            ticket.unlink(missing_ok=True)
