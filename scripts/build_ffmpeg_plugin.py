"""Maintainer-only FFmpeg builder/signer. Never included in the desktop bundle.

Run with: uv run --with pgpy --with standard-imghdr python3 -m scripts.build_ffmpeg_plugin --help
"""

import argparse
import base64
import json
import os
import platform
import shlex
import shutil
import stat
import subprocess
import tarfile
import tempfile
from pathlib import Path
from threading import Event
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from service.capabilities.capability_archive import digest
from service.capabilities.capability_manifest import verify_manifest
from service.capabilities.media_runtime import OPERATIONS, selfcheck

VERSION = "9.0.2"
FINGERPRINT = "FCF986EA15E6E293A5644F10B4322F04D67658D8"
SOURCE_URL = f"https://www.ffmpeg.org/releases/ffmpeg-{VERSION}.tar.xz"
CONFIGURE = [
    "--disable-autodetect", "--disable-everything", "--disable-network",
    "--disable-gpl", "--disable-nonfree", "--disable-version3",
    "--disable-shared", "--enable-static", "--disable-doc", "--disable-debug",
    "--disable-avdevice", "--disable-videotoolbox", "--disable-audiotoolbox",
    "--disable-securetransport", "--disable-iconv",
    "--enable-ffmpeg", "--enable-ffprobe", "--disable-ffplay",
    "--enable-protocol=file,pipe",
    "--enable-demuxer=mov,matroska,mp3,wav,flac,ogg,aiff,avi,rawvideo",
    "--enable-muxer=mp4,mov,wav,flac,matroska",
    "--enable-decoder=aac,mp3,mp3float,h264,hevc,mpeg4,pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,flac,vorbis,opus,alac,mjpeg,rawvideo",
    "--enable-encoder=aac,mpeg4,pcm_s16le,flac",
    "--enable-parser=aac,mpegaudio,h264,hevc,mpeg4video,flac,opus,vorbis",
    "--enable-filter=aresample,aformat,format,scale,null,anull",
    "--enable-bsf=aac_adtstoasc,extract_extradata",
    "--cc=/usr/bin/clang", "--extra-cflags=-mmacosx-version-min=13.0",
    "--extra-ldflags=-mmacosx-version-min=13.0",
]


def keygen(path):
    path = Path(path)
    repository = Path(__file__).resolve().parents[1]
    if path.resolve().is_relative_to(repository):
        raise ValueError("Signing private keys must be stored outside the repository")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = Ed25519PrivateKey.generate()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    print(json.dumps({"public_key_hex": key.public_key().public_bytes_raw().hex(), "private_key": str(path)}))


def verify_upstream(source, signature, key_path):
    import pgpy

    key, _ = pgpy.PGPKey.from_file(str(key_path))
    if str(key.fingerprint) != FINGERPRINT:
        raise ValueError("Unexpected FFmpeg release signing key")
    signed = pgpy.PGPSignature.from_file(str(signature))
    if not key.verify(source.read_bytes(), signed):
        raise ValueError("FFmpeg source signature verification failed")


def _run(arguments, cwd):
    subprocess.run(arguments, cwd=cwd, check=True)


def package_zip(directory, source, signature, upstream_key, private_key, output, provenance):
    if private_key.is_symlink() or stat.S_IMODE(private_key.stat().st_mode) & 0o077:
        raise ValueError("Private key must be a non-symlink owner-only file")
    key = serialization.load_pem_private_key(private_key.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError("Expected an Ed25519 signing key")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        root = Path(temporary)
        payload = root / "payload"
        (payload / "bin").mkdir(parents=True)
        for name in ("ffmpeg", "ffprobe"):
            shutil.copy2(directory / name, payload / "bin" / name)
            (payload / "bin" / name).chmod(0o700)
        shutil.copy2(directory / "COPYING.LGPLv2.1", payload / "LICENSE")
        (payload / "BUILD.json").write_text(json.dumps(provenance, indent=2) + "\n")
        (payload / "NOTICE.txt").write_text(
            "FFmpeg is Copyright the FFmpeg developers, licensed under LGPL-2.1-or-later.\n"
            "This standalone build does not enable GPL, nonfree, or version3 components.\n"
            "Corresponding unmodified source and its upstream signature are included in source/.\n"
            "Build configuration is in BUILD.json. Use the accompanying maintainer build script to rebuild.\n"
        )
        (payload / "source").mkdir()
        for path in (source, signature, upstream_key):
            shutil.copy2(path, payload / "source" / path.name)
        (payload / "source" / "REBUILD.sh").write_text(
            "#!/bin/sh\nset -eu\n" + shlex.join(["tar", "-xf", source.name]) + "\n"
            + f"cd ffmpeg-{VERSION}\n" + shlex.join(["/bin/sh", "./configure", *CONFIGURE])
            + "\n/usr/bin/make -j4 ffmpeg ffprobe\n"
        )
        # Include the exact build script so recipients can reproduce the executable build.
        shutil.copy2(Path(__file__), payload / "source" / "build_ffmpeg_plugin.py")
        entries = {"ffmpeg": "bin/ffmpeg", "ffprobe": "bin/ffprobe"}
        files = []
        for path in sorted(payload.rglob("*")):
            if path.is_file():
                name = path.relative_to(payload).as_posix()
                files.append({"path": name, "size": path.stat().st_size, "sha256": digest(path),
                              "executable": name in entries.values()})
        archive = root / "payload.zip"
        with ZipFile(archive, "w", compression=ZIP_DEFLATED) as target:
            for item in files:
                target.write(payload / item["path"], item["path"])
        package = {
            "id": "media.ffmpeg", "version": VERSION, "platform": "macos-arm64", "protocol": 1,
            "size": archive.stat().st_size, "sha256": digest(archive),
            "expanded_size": sum(item["size"] for item in files), "files": files,
            "entries": entries, "operations": list(OPERATIONS), "license": "LGPL-2.1-or-later",
            "source": SOURCE_URL,
        }
        raw = json.dumps({"schema_version": 1, "packages": [package]}, sort_keys=True, separators=(",", ":")).encode()
        envelope = json.dumps({"payload": base64.b64encode(raw).decode(),
                               "signature": base64.b64encode(key.sign(raw)).decode()}).encode()
        manifest = verify_manifest(envelope, (key.public_key().public_bytes_raw(),))
        if not selfcheck(payload, manifest.packages[0], Event()):
            raise ValueError("Built engine selfcheck failed")
        bundle = root / "plugin.zip"
        with ZipFile(bundle, "w", compression=ZIP_STORED) as target:
            target.writestr("manifest.json", envelope)
            target.write(archive, "payload.zip")
        if output.exists():
            raise FileExistsError(output)
        os.link(bundle, output)
    print(json.dumps({"path": str(output), "size": output.stat().st_size, "sha256": digest(output),
                      "public_key_hex": key.public_key().public_bytes_raw().hex()}))


def build(args):
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise ValueError("This recipe targets macOS arm64 only")
    source = args.source.resolve(strict=True)
    signature, upstream_key = args.signature.resolve(strict=True), args.upstream_key.resolve(strict=True)
    verify_upstream(source, signature, upstream_key)
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    directory = work / f"ffmpeg-{VERSION}"
    if directory.exists():
        raise FileExistsError("Use a fresh build directory to avoid reusing unverified sources")
    with tarfile.open(source) as archive:
        members = archive.getmembers()
        if any(member.name != f"ffmpeg-{VERSION}" and not member.name.startswith(f"ffmpeg-{VERSION}/") for member in members):
            raise ValueError("Unexpected source archive root")
        archive.extractall(work, filter="data")
    _run(["/bin/sh", "./configure", *CONFIGURE], directory)
    _run(["/usr/bin/make", f"-j{args.jobs}", "ffmpeg", "ffprobe"], directory)
    for name in ("ffmpeg", "ffprobe"):
        linked = subprocess.check_output(["/usr/bin/otool", "-L", str(directory / name)], text=True)
        if any(line.strip() and not line.startswith(str(directory / name)) and not line.strip().startswith(
            ("/usr/lib/", "/System/Library/")) for line in linked.splitlines()):
            raise ValueError("Build links to a non-system shared library")
    provenance = {"version": VERSION, "platform": "macos-arm64", "minimum_macos": "13.0",
                  "source_url": SOURCE_URL, "source_sha256": digest(source),
                  "upstream_pgp_fingerprint": FINGERPRINT, "upstream_signature_verified": True,
                  "configure": CONFIGURE, "compiler": subprocess.check_output(["/usr/bin/clang", "--version"], text=True)}
    package_zip(directory, source, signature, upstream_key, args.private_key, args.output, provenance)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    key = subcommands.add_parser("keygen")
    key.add_argument("--private-key", type=Path, required=True)
    command = subcommands.add_parser("build")
    for name in ("source", "signature", "upstream-key", "private-key", "output", "work"):
        command.add_argument("--" + name, type=Path, required=True)
    command.add_argument("--jobs", type=int, default=4, choices=range(1, 17))
    args = parser.parse_args()
    if args.command == "keygen":
        keygen(args.private_key)
    else:
        build(args)


if __name__ == "__main__":
    main()
