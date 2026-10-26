"""Official package installation foundation; deliberately not a model tool/API."""

import base64
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Lock
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from core.local_paths import app_dir
from service.capabilities.capability_archive import cancelled, extract, verify_files
from service.capabilities.capability_manifest import (
    MAX_ARCHIVE,
    MAX_MANIFEST,
    PACK_IDS,
    PackError,
    target_platform,
    verify_manifest,
    version_key,
)

# Public verification material only. Signing keys live outside the repository.
OFFICIAL_PUBLIC_KEYS = (bytes.fromhex("76d1a5f78b2dcfb2f5c796e78f22813fe0e57ad8ee41899f5ec32f1f9200b15e"),)


def _read(path: Path, limit=2 * MAX_MANIFEST):
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode) or path.stat().st_size > limit:
        raise PackError("invalid_state")
    result = json.loads(path.read_bytes())
    if not isinstance(result, dict):
        raise PackError("invalid_state")
    return result


def _atomic(path: Path, data) -> None:
    temporary = path.with_name(f".{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as target:
            temporary.chmod(0o600)
            json.dump(data, target)
            target.flush()
            os.fsync(target.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _lock(path: Path):
    """One nonblocking OS lock also protects leases across application processes."""
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    handle = os.fdopen(descriptor, "r+b")
    locked = False
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode) or os.fstat(descriptor).st_nlink != 1:
            raise PackError("invalid_state")
        if os.name == "nt":
            import msvcrt
            handle.write(b"0")
            handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                locked = True
            except OSError as error:
                raise PackError("busy") from error
        else:
            import fcntl
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except OSError as error:
                raise PackError("busy") from error
        yield
    finally:
        if locked and os.name == "nt":
            handle.seek(0)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        handle.close()


class PackManager:
    """Synchronous I/O API: call from a worker, cancel from the UI thread.

    Selfchecks are host-owned adapters, not commands supplied by a package.
    No engine is usable until its host adapter has been implemented.
    """

    def __init__(self, root=None, *, public_keys=(), selfchecks=None, target=None):
        self.root = Path(root) if root is not None else app_dir() / "plugins"
        self.public_keys = tuple(public_keys)
        self.selfchecks = dict(selfchecks or {})
        self.target = target or target_platform()
        self._events = {}
        self._mutex = Lock()

    @property
    def configured(self):
        return bool(self.public_keys)

    def _directory(self, path):
        if self.root.is_symlink():
            raise PackError("invalid_state")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        relative = path.relative_to(self.root)
        current = self.root
        for name in relative.parts:
            current = current / name
            if current.is_symlink():
                raise PackError("invalid_state")
            current.mkdir(exist_ok=True, mode=0o700)
        return path

    def _pack(self, pack_id):
        if pack_id not in PACK_IDS:
            raise PackError("unknown_package")
        return self._directory(self.root / pack_id)

    @contextmanager
    def _claim(self, pack_id):
        base = self._pack(pack_id)
        locks = self._directory(self.root / ".locks")
        with _lock(locks / f"{pack_id}.lock"):
            yield base

    def _progress(self, base, phase, *, error=None, received=0, total=0):
        _atomic(base / "status.json", {"phase": phase, "error": error, "received": received, "total": total})

    def import_zip(self, path):
        """Import a local ZIP containing manifest.json and payload.zip, offline."""
        if not self.configured:
            raise PackError("not_configured")
        path = Path(path)
        if path.is_symlink() or not path.is_file():
            raise PackError("invalid_archive")
        if path.stat().st_size > MAX_ARCHIVE + MAX_MANIFEST + 1024 * 1024:
            raise PackError("archive_limit")
        # Open once; validation and copying use the same source handle.
        try:
            with path.open("rb") as handle, ZipFile(handle) as bundle:
                infos = bundle.infolist()
                if len(infos) != 2 or {item.filename for item in infos} != {"manifest.json", "payload.zip"}:
                    raise PackError("unsafe_archive")
                for item in infos:
                    mode = item.external_attr >> 16
                    if item.flag_bits & 1 or stat.S_IFMT(mode) not in {0, stat.S_IFREG}:
                        raise PackError("unsafe_archive")
                manifest = bundle.getinfo("manifest.json")
                if manifest.file_size > MAX_MANIFEST:
                    raise PackError("manifest_too_large")
                envelope = bundle.read(manifest)
                metadata = verify_manifest(envelope, self.public_keys)
                if len(metadata.packages) != 1:
                    raise PackError("invalid_manifest")
                package = metadata.packages[0]
                if package.platform != self.target:
                    raise PackError("platform_unavailable")
                if bundle.getinfo("payload.zip").file_size != package.size:
                    raise PackError("size_mismatch")
                with bundle.open("payload.zip") as source:
                    return self._install(package, envelope, source)
        except (BadZipFile, RuntimeError, NotImplementedError) as error:
            raise PackError("unsafe_archive") from error

    def _receipt(self, pack_id, base):
        receipt = _read(base / "active.json")
        envelope = base64.b64decode(receipt["envelope"], validate=True)
        manifest = verify_manifest(envelope, self.public_keys)
        generation = receipt["generation"]
        if not isinstance(generation, str) or not re.fullmatch(r"[a-f0-9]{32}", generation):
            raise PackError("invalid_state")
        matches = [item for item in manifest.packages if item.id == pack_id and item.version == receipt["version"] and item.platform == self.target]
        if len(matches) != 1 or receipt.get("selfcheck") is not True:
            raise PackError("invalid_state")
        package = matches[0]
        directory = base / package.version / package.platform / generation
        if any(parent.is_symlink() for parent in (base, base / package.version, directory.parent)):
            raise PackError("invalid_state")
        return package, directory

    def _active(self, pack_id, base):
        package, directory = self._receipt(pack_id, base)
        verify_files(directory, package)
        if pack_id not in self.selfchecks:
            raise PackError("engine_check_unavailable")
        return package, directory

    def status(self, pack_id):
        if pack_id not in PACK_IDS:
            raise PackError("unknown_package")
        result = {"id": pack_id, "state": "not_installed" if self.configured else "unavailable", "version": None, "activity": None, "error": None}
        base = self.root / pack_id
        if self.root.is_symlink() or base.is_symlink():
            return {**result, "state": "invalid", "error": "invalid_state"}
        if not base.exists():
            return result
        try:
            if (base / "status.json").exists():
                result["activity"] = _read(base / "status.json")
            if (base / "active.json").exists():
                package, _ = self._active(pack_id, base)
                result.update(state="ready", version=package.version)
        except (ValueError, OSError, KeyError, TypeError):
            result.update(state="invalid", error="installation_damaged")
        return result

    def cancel(self, pack_id):
        with self._mutex:
            event = self._events.get(pack_id)
            if event is not None:
                event.set()
                return True
        return False

    def _recover(self, base):
        staging = base / ".staging"
        if staging.is_symlink():
            raise PackError("invalid_state")
        if staging.exists():
            shutil.rmtree(staging)
        for path in base.glob(".*.tmp"):
            if path.is_file() or path.is_symlink():
                path.unlink()

    def recover(self, pack_id):
        """Call on application startup; never clean an in-flight install."""
        with self._claim(pack_id) as base:
            self._recover(base)
            status = base / "status.json"
            if status.exists():
                try:
                    phase = _read(status).get("phase")
                except (OSError, ValueError, TypeError, AttributeError):
                    phase = "invalid"
                if phase in {"importing", "extracting", "checking", "activating", "invalid"}:
                    self._progress(base, "failed", error="invalid_state" if phase == "invalid" else "interrupted")
        return self.status(pack_id)

    def _install(self, package, envelope, source):
        pack_id = package.id
        if pack_id not in self.selfchecks:
            raise PackError("engine_check_unavailable")
        with self._claim(pack_id) as base:
            event = Event()
            with self._mutex:
                self._events[pack_id] = event
            published, active = None, False
            try:
                self._recover(base)
                if (base / "active.json").exists():
                    try:
                        old, _ = self._receipt(pack_id, base)
                    except (ValueError, OSError, KeyError, TypeError):
                        old = None
                    if old and version_key(package.version) < version_key(old.version):
                        raise PackError("version_rollback")
                required = package.size + package.expanded_size + 16 * 1024 * 1024
                if shutil.disk_usage(base).free < required:
                    raise PackError("disk_full")
                staging = self._directory(base / ".staging")
                with tempfile.TemporaryDirectory(dir=staging) as temporary:
                    temporary = Path(temporary)
                    archive = temporary / "package.zip"
                    count, checksum = 0, hashlib.sha256()
                    self._progress(base, "importing", total=package.size)
                    with archive.open("xb") as output:
                        while chunk := source.read(64 * 1024):
                            cancelled(event)
                            count += len(chunk)
                            if count > package.size:
                                raise PackError("archive_limit")
                            checksum.update(chunk)
                            output.write(chunk)
                            self._progress(base, "importing", received=count, total=package.size)
                    cancelled(event)
                    if count != package.size or checksum.hexdigest() != package.sha256:
                        raise PackError("archive_hash_mismatch")
                    extracted = temporary / "files"
                    extracted.mkdir()
                    self._progress(base, "extracting")
                    extract(archive, extracted, package, event)
                    verify_files(extracted, package)
                    self._progress(base, "checking")
                    if self.selfchecks[pack_id](extracted, package, event) is not True:
                        raise PackError("selfcheck_failed")
                    cancelled(event)
                    self._progress(base, "activating")
                    generation = uuid4().hex
                    parent = self._directory(base / package.version / package.platform)
                    published = parent / generation
                    extracted.rename(published)
                    receipt = {"version": package.version, "generation": generation, "envelope": base64.b64encode(envelope).decode("ascii"), "selfcheck": True}
                    cancelled(event)
                    _atomic(base / "active.json", receipt)
                    active = True
                    try:
                        self._progress(base, "complete")
                    except OSError:
                        pass  # Activation is already committed; progress cannot roll it back.
            except Exception as error:
                code = error.code if isinstance(error, PackError) else "install_failed"
                try:
                    self._progress(base, "cancelled" if code == "cancelled" else "failed", error=code)
                except OSError:
                    pass
                if isinstance(error, PackError):
                    raise
                raise PackError(code) from error
            finally:
                with self._mutex:
                    self._events.pop(pack_id, None)
                if published is not None and not active:
                    shutil.rmtree(published)
        return self.status(pack_id)

    @contextmanager
    def acquire(self, pack_id):
        """Internal lease for future engine adapters; not a command executor."""
        with self._claim(pack_id) as base:
            package, directory = self._active(pack_id, base)
            yield package, directory

    def uninstall(self, pack_id):
        with self._claim(pack_id) as base:
            (base / "active.json").unlink(missing_ok=True)
            self._recover(base)
            for child in base.iterdir():
                if child.is_symlink():
                    child.unlink()
                elif child.is_dir():
                    shutil.rmtree(child)
            self._progress(base, "removed")
        return self.status(pack_id)


def official_manager() -> PackManager:
    from service.capabilities.media_runtime import selfcheck
    return PackManager(public_keys=OFFICIAL_PUBLIC_KEYS, selfchecks={"media.ffmpeg": selfcheck})


def recover_existing() -> list[dict]:
    manager = official_manager()
    if not manager.root.exists():
        return []
    result = []
    for pack_id in PACK_IDS:
        if not (manager.root / pack_id).exists():
            continue
        try:
            result.append(manager.recover(pack_id))
        except (OSError, ValueError) as error:
            result.append({"id": pack_id, "state": "invalid", "error": error.code if isinstance(error, PackError) else "recovery_failed"})
    return result
