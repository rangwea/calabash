"""Signed official package metadata. No user-provided install URLs or commands."""

import base64
import json
import platform
import re
import unicodedata
from pathlib import PurePosixPath

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, ValidationError

PACK_IDS = ("media.ffmpeg", "document.ocr")
HOST_PROTOCOL = 1
MAX_MANIFEST = 1024 * 1024
MAX_ARCHIVE = 1024 * 1024 * 1024
MAX_EXPANDED = 2 * MAX_ARCHIVE
MAX_FILES = 4096
VERSION = r"[0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6}"
SHA256 = r"[a-f0-9]{64}"


class PackError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def target_platform() -> str:
    system = {"Darwin": "macos", "Windows": "windows", "Linux": "linux"}.get(platform.system(), "unknown")
    machine = platform.machine().lower()
    arch = {"aarch64": "arm64", "arm64": "arm64", "amd64": "x86_64", "x86_64": "x86_64"}.get(machine, "unknown")
    return f"{system}-{arch}"


def safe_path(value: str) -> str:
    """Use one portable, case-insensitive path policy on every platform."""
    if not value or len(value) > 240 or any(char in value for char in '\\:<>"|?*') or any(ord(char) < 32 for char in value):
        raise PackError("unsafe_path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} or part[-1:] in {".", " "} for part in parts):
        raise PackError("unsafe_path")
    reserved = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(10)), *(f"lpt{i}" for i in range(10))}
    if PurePosixPath(value).is_absolute() or any(unicodedata.normalize("NFKC", part.split(".", 1)[0]).casefold() in reserved for part in parts):
        raise PackError("unsafe_path")
    if unicodedata.normalize("NFC", value) != value:
        raise PackError("unsafe_path")
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class PackageFile(StrictModel):
    path: str = Field(min_length=1, max_length=240)
    size: int = Field(ge=0, le=MAX_EXPANDED)
    sha256: str = Field(pattern=f"^{SHA256}$")
    executable: bool = False


class Package(StrictModel):
    id: str
    version: str = Field(pattern=f"^{VERSION}$")
    platform: str = Field(pattern=r"^(macos|windows|linux)-(arm64|x86_64)$")
    protocol: int
    size: int = Field(gt=0, le=MAX_ARCHIVE)
    sha256: str = Field(pattern=f"^{SHA256}$")
    expanded_size: int = Field(ge=0, le=MAX_EXPANDED)
    files: tuple[PackageFile, ...] = Field(min_length=1, max_length=MAX_FILES)
    entries: dict[str, str] = Field(min_length=1, max_length=8)
    operations: tuple[str, ...] = Field(min_length=1, max_length=32)
    license: str = Field(min_length=1, max_length=200)
    source: str = Field(min_length=1, max_length=2048)


class Manifest(StrictModel):
    schema_version: int
    packages: tuple[Package, ...] = Field(min_length=1, max_length=1)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PackError("invalid_manifest")
        result[key] = value
    return result


def verify_manifest(envelope: bytes, public_keys: tuple[bytes, ...]) -> Manifest:
    if not public_keys:
        raise PackError("not_configured")
    if len(envelope) > MAX_MANIFEST:
        raise PackError("manifest_too_large")
    try:
        wrapper = json.loads(envelope, object_pairs_hook=_unique_object)
        if not isinstance(wrapper, dict) or set(wrapper) != {"payload", "signature"}:
            raise ValueError
        payload = base64.b64decode(wrapper["payload"], validate=True)
        signature = base64.b64decode(wrapper["signature"], validate=True)
        verified = False
        for key in public_keys:
            try:
                Ed25519PublicKey.from_public_bytes(key).verify(signature, payload)
                verified = True
                break
            except (ValueError, InvalidSignature):
                continue
        if not verified:
            raise PackError("signature_invalid")
        json.loads(payload, object_pairs_hook=_unique_object)
        result = Manifest.model_validate_json(payload)
    except (ValueError, TypeError, KeyError, ValidationError) as error:
        if isinstance(error, PackError):
            raise
        raise PackError("invalid_manifest") from error
    if result.schema_version != 1:
        raise PackError("invalid_manifest")
    identities = set()
    for package in result.packages:
        identity = (package.id, package.version, package.platform)
        if package.id not in PACK_IDS or identity in identities or package.protocol != HOST_PROTOCOL:
            raise PackError("incompatible_manifest")
        identities.add(identity)
        names, files = set(), {}
        for item in package.files:
            name = safe_path(item.path)
            folded = name.casefold()
            if folded in names:
                raise PackError("unsafe_path")
            names.add(folded)
            files[name] = item
        for name in names:
            if any(parent.as_posix().casefold() in names for parent in PurePosixPath(name).parents if parent.as_posix() != "."):
                raise PackError("unsafe_path")
        if sum(item.size for item in package.files) != package.expanded_size:
            raise PackError("size_mismatch")
        if any(not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", operation) for operation in package.operations):
            raise PackError("invalid_manifest")
        for entry, path in package.entries.items():
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", entry) or path not in files or not files[path].executable:
                raise PackError("invalid_entry")
    return result


def version_key(value: str) -> tuple[int, ...]:
    if not re.fullmatch(VERSION, value):
        raise PackError("invalid_version")
    return tuple(int(part) for part in value.split("."))
