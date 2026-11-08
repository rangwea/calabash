"""Extract exactly the signed files; never restore archive permissions or links."""

import hashlib
import stat
from pathlib import Path
from threading import Event
from zipfile import BadZipFile, ZipFile

from service.capabilities.capability_manifest import (
    MAX_FILES,
    Package,
    PackError,
    safe_path,
)


def cancelled(event: Event) -> None:
    if event.is_set():
        raise PackError("cancelled")


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(64 * 1024):
            checksum.update(chunk)
    return checksum.hexdigest()


def extract(archive: Path, destination: Path, package: Package, event: Event) -> None:
    expected = {item.path: item for item in package.files}
    try:
        with ZipFile(archive) as incoming:
            infos = incoming.infolist()
            if len(infos) > MAX_FILES:
                raise PackError("archive_limit")
            seen = set()
            for info in infos:
                cancelled(event)
                name = safe_path(info.filename)
                mode = info.external_attr >> 16
                if name.casefold() in seen or name not in expected or info.is_dir() or stat.S_IFMT(mode) not in {0, stat.S_IFREG} or info.flag_bits & 1:
                    raise PackError("unsafe_archive")
                seen.add(name.casefold())
                item = expected[name]
                if info.file_size != item.size:
                    raise PackError("size_mismatch")
                output = destination / name
                output.parent.mkdir(parents=True, exist_ok=True)
                count, checksum = 0, hashlib.sha256()
                with incoming.open(info) as source, output.open("xb") as target:
                    while chunk := source.read(64 * 1024):
                        cancelled(event)
                        count += len(chunk)
                        if count > item.size:
                            raise PackError("archive_limit")
                        checksum.update(chunk)
                        target.write(chunk)
                if count != item.size or checksum.hexdigest() != item.sha256:
                    raise PackError("file_hash_mismatch")
                output.chmod(0o700 if item.executable else 0o600)
            if seen != {name.casefold() for name in expected}:
                raise PackError("missing_file")
    except (BadZipFile, RuntimeError, NotImplementedError) as error:
        raise PackError("unsafe_archive") from error


def verify_files(directory: Path, package: Package) -> None:
    if directory.is_symlink() or not directory.is_dir():
        raise PackError("installation_damaged")
    expected = {item.path: item for item in package.files}
    actual = set()
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise PackError("installation_damaged")
        if path.is_dir():
            continue
        name = path.relative_to(directory).as_posix()
        item = expected.get(name)
        info = path.lstat()
        if not item or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != item.size or digest(path) != item.sha256:
            raise PackError("installation_damaged")
        if item.executable and not info.st_mode & stat.S_IXUSR:
            raise PackError("installation_damaged")
        actual.add(name)
    if actual != set(expected):
        raise PackError("installation_damaged")
