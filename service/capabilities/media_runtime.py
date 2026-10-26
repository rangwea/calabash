"""Blocking, local-file-only FFmpeg operations. UI callers use run.io_bound."""

import json
import math
import os
import signal
import stat
import subprocess
import tempfile
import time
import wave
from pathlib import Path
from threading import Event

from service.capabilities.capability_archive import cancelled
from service.capabilities.capability_manifest import PackError

OPERATIONS = ("probe", "convert", "extract_audio")
FORMATS = "mov,matroska,webm,mp3,wav,flac,ogg,aiff,avi"
PROFILES = {
    "wav": ["-vn", "-c:a", "pcm_s16le", "-f", "wav"],
    "flac": ["-vn", "-c:a", "flac", "-f", "flac"],
    "mp4": ["-c:v", "mpeg4", "-q:v", "5", "-pix_fmt", "yuv420p", "-c:a", "aac", "-f", "mp4"],
}


def _run(executable, arguments, *, event, timeout, cwd):
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 600:
        raise PackError("invalid_timeout")
    cancelled(event)
    env = {"PATH": "", "HOME": str(cwd), "TMPDIR": str(cwd), "LANG": "C", "LC_ALL": "C"}
    # Files avoid pipe deadlocks; bound diagnostics and always reap on exit.
    with tempfile.TemporaryFile(dir=cwd) as output, tempfile.TemporaryFile(dir=cwd) as errors:
        process = subprocess.Popen(
            [str(executable), *arguments], stdin=subprocess.DEVNULL, stdout=output, stderr=errors,
            cwd=cwd, env=env, shell=False, start_new_session=os.name != "nt",
        )
        started = time.monotonic()
        try:
            while True:
                cancelled(event)
                if time.monotonic() - started > timeout:
                    raise PackError("engine_timeout")
                if os.fstat(output.fileno()).st_size > 2 * 1024 * 1024 or os.fstat(errors.fileno()).st_size > 256 * 1024:
                    raise PackError("engine_output_limit")
                if process.poll() is not None:
                    break
                time.sleep(0.05)
            if process.returncode:
                raise PackError("media_failed")
            output.seek(0)
            return output.read(2 * 1024 * 1024)
        finally:
            if process.poll() is None:
                if os.name == "nt":
                    process.kill()
                else:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            process.wait()


def _input(path):
    path = Path(path).expanduser().resolve(strict=True)
    if not stat.S_ISREG(path.stat().st_mode):
        raise PackError("invalid_input")
    return path


def _entries(directory, package):
    if set(package.entries) != {"ffmpeg", "ffprobe"} or set(package.operations) != set(OPERATIONS):
        raise PackError("incompatible_engine")
    return directory / package.entries["ffmpeg"], directory / package.entries["ffprobe"]


def _probe(executable, source, event, timeout, cwd):
    raw = _run(executable, [
        "-v", "error", "-protocol_whitelist", "file,pipe", "-format_whitelist", FORMATS,
        "-show_entries", "format=format_name,duration,size:stream=index,codec_type,codec_name,width,height,sample_rate,channels,duration",
        "-of", "json", "-i", str(source),
    ], event=event, timeout=timeout, cwd=cwd)
    try:
        result = json.loads(raw)
        if not isinstance(result, dict) or not result.get("streams"):
            raise ValueError("missing streams")
        return result
    except (ValueError, TypeError) as error:
        raise PackError("invalid_media") from error


def selfcheck(directory, package, event):
    ffmpeg, ffprobe = _entries(directory, package)
    with tempfile.TemporaryDirectory(prefix="calabash-media-check-") as temporary:
        root = Path(temporary)
        for executable, name in ((ffmpeg, b"ffmpeg version "), (ffprobe, b"ffprobe version ")):
            if not _run(executable, ["-version"], event=event, timeout=15, cwd=root).startswith(name):
                raise PackError("selfcheck_failed")
        source = root / "input.wav"
        with wave.open(str(source), "wb") as audio:
            audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            audio.writeframes(b"\x00\x00" * 800)
        destination = root / "output.flac"
        _run(ffmpeg, ["-nostdin", "-v", "error", "-n", "-i", str(source), "-c:a", "flac", str(destination)],
             event=event, timeout=20, cwd=root)
        result = _probe(ffprobe, destination, event, 15, root)
        return result["streams"][0]["codec_name"] == "flac"


class MediaRuntime:
    """Uses installed, verified engines only; never searches PATH or downloads."""

    def __init__(self, manager=None):
        if manager is None:
            from service.capabilities.capability_packs import official_manager
            manager = official_manager()
        self.manager = manager

    def status(self):
        return self.manager.status("media.ffmpeg")

    def probe(self, source, *, event=None, timeout=30):
        source = _input(source)
        event = event if event is not None else Event()
        with self.manager.acquire("media.ffmpeg") as (package, directory), tempfile.TemporaryDirectory() as temporary:
            _, ffprobe = _entries(directory, package)
            return _probe(ffprobe, source, event, timeout, Path(temporary))

    def convert(self, source, destination, *, profile=None, event=None, timeout=120):
        source = _input(source)
        destination = Path(destination).expanduser().absolute()
        profile = profile or destination.suffix.lower().lstrip(".")
        if profile not in PROFILES or destination.suffix.lower() != "." + profile:
            raise PackError("unsupported_profile")
        if destination.exists() or destination.is_symlink():
            raise PackError("output_exists")
        event = event if event is not None else Event()
        with self.manager.acquire("media.ffmpeg") as (package, directory):
            ffmpeg, ffprobe = _entries(directory, package)
            # Same-filesystem staging + hard-link publication never overwrites a target.
            with tempfile.TemporaryDirectory(prefix=".calabash-media-", dir=destination.parent) as temporary:
                root = Path(temporary)
                staged = root / ("output." + profile)
                _run(ffmpeg, [
                    "-nostdin", "-v", "error", "-n", "-protocol_whitelist", "file,pipe",
                    "-format_whitelist", FORMATS, "-i", str(source), "-map_metadata", "-1",
                    "-threads", "2", *PROFILES[profile], str(staged),
                ], event=event, timeout=timeout, cwd=root)
                _probe(ffprobe, staged, event, min(timeout, 30), root)
                cancelled(event)
                try:
                    os.link(staged, destination)
                except FileExistsError as error:
                    raise PackError("output_exists") from error
        return destination

    def extract_audio(self, source, destination, *, event=None, timeout=120):
        if Path(destination).suffix.lower() not in {".wav", ".flac"}:
            raise PackError("unsupported_profile")
        return self.convert(source, destination, event=event, timeout=timeout)


def check_media():
    """Offline frozen-app diagnostic: synthetic files only, no UI or web server."""
    media = MediaRuntime()
    with tempfile.TemporaryDirectory(prefix="calabash-media-runtime-") as temporary:
        root = Path(temporary)
        source = root / "synthetic.wav"
        with wave.open(str(source), "wb") as audio:
            audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            audio.writeframes(b"\x00\x00" * 8000)
        converted = media.convert(source, root / "converted.flac")
        metadata = media.probe(converted)
        restored = media.extract_audio(converted, root / "restored.wav")
        with wave.open(str(restored)) as audio:
            frames = audio.getnframes()
        return {"ok": frames == 8000 and metadata["streams"][0]["codec_name"] == "flac",
                "plugin": media.status(), "checks": ["convert_flac", "probe", "extract_wav"],
                "restored_frames": frames}
