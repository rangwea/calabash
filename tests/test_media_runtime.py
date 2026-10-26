import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from threading import Event, Timer
from unittest.mock import patch
from zipfile import ZipFile

from service.capabilities.capability_manifest import PackError
from service.capabilities.capability_packs import official_manager
from service.capabilities.media_runtime import MediaRuntime, _run


class MediaProcessTests(unittest.TestCase):
    def test_timeout_cancel_and_output_limit_reap_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            for code, script, timeout, event in [
                ("engine_timeout", "import time; time.sleep(10)", 0.1, Event()),
                ("engine_output_limit", "print('x' * 3000000)", 5, Event()),
            ]:
                with self.subTest(code=code), self.assertRaises(PackError) as caught:
                    _run(sys.executable, ["-c", script], event=event, timeout=timeout, cwd=cwd)
                self.assertEqual(code, caught.exception.code)
            event = Event()
            timer = Timer(0.1, event.set)
            timer.start()
            try:
                with self.assertRaises(PackError) as caught:
                    _run(sys.executable, ["-c", "import time; time.sleep(10)"],
                         event=event, timeout=5, cwd=cwd)
                self.assertEqual("cancelled", caught.exception.code)
            finally:
                timer.join()

    def test_invalid_timeout_and_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input.wav"
            source.write_bytes(b"fixture")
            runtime = MediaRuntime()
            for value in (0, -1, 601, float("nan"), float("inf")):
                with self.assertRaises(PackError):
                    _run(sys.executable, [], event=Event(), timeout=value, cwd=root)
            with self.assertRaises(PackError) as caught:
                runtime.convert(source, root / "output.exe")
            self.assertEqual("unsupported_profile", caught.exception.code)
            existing = root / "existing.wav"
            existing.write_bytes(b"keep")
            with self.assertRaises(PackError) as caught:
                runtime.convert(source, existing)
            self.assertEqual("output_exists", caught.exception.code)
            self.assertEqual(b"keep", existing.read_bytes())


@unittest.skipUnless(os.environ.get("CALABASH_FFMPEG_TEST_ZIP"), "Set CALABASH_FFMPEG_TEST_ZIP to a signed real plugin ZIP")
class RealFFmpegTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.manager = official_manager()
        self.manager.root = self.root / "plugins"
        self.assertEqual("ready", self.manager.import_zip(os.environ["CALABASH_FFMPEG_TEST_ZIP"])["state"])
        self.runtime = MediaRuntime(self.manager)
        self.source = self.root / "input.wav"
        with wave.open(str(self.source), "wb") as audio:
            audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            audio.writeframes(b"\x00\x00" * 8000)

    def test_offline_audio_roundtrip_no_system_tools(self):
        with patch.dict(os.environ, {"PATH": ""}), patch("socket.socket", side_effect=AssertionError("no network")):
            probe = self.runtime.probe(self.source)
            self.assertEqual("pcm_s16le", probe["streams"][0]["codec_name"])
            result = self.runtime.convert(self.source, self.root / "audio.flac")
            self.assertEqual("flac", self.runtime.probe(result)["streams"][0]["codec_name"])
            restored = self.runtime.extract_audio(result, self.root / "restored.wav")
            with wave.open(str(restored)) as audio:
                self.assertEqual(8000, audio.getnframes())
            self.assertFalse(list(self.root.glob(".calabash-media-*")))

    def test_real_video_conversion_and_audio_extraction(self):
        raw = self.root / "pixels.rgb"
        raw.write_bytes(bytes([220, 20, 30]) * 64 * 48 * 10)
        video = self.root / "input.mp4"
        with self.manager.acquire("media.ffmpeg") as (package, directory):
            _run(directory / package.entries["ffmpeg"], [
                "-nostdin", "-v", "error", "-n", "-f", "rawvideo", "-pixel_format", "rgb24",
                "-video_size", "64x48", "-framerate", "10", "-i", str(raw), "-i", str(self.source),
                "-c:v", "mpeg4", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video),
            ], event=Event(), timeout=30, cwd=self.root)
        types = {stream["codec_type"] for stream in self.runtime.probe(video)["streams"]}
        self.assertEqual({"video", "audio"}, types)
        converted = self.runtime.convert(video, self.root / "converted.mp4")
        self.assertGreater(converted.stat().st_size, 0)
        audio = self.runtime.extract_audio(video, self.root / "track.wav")
        self.assertEqual("audio", self.runtime.probe(audio)["streams"][0]["codec_type"])

    def test_invalid_media_and_cancel_leave_no_outputs(self):
        broken = self.root / "broken.mp4"
        broken.write_bytes(b"not media")
        output = self.root / "output.wav"
        with self.assertRaises(PackError):
            self.runtime.convert(broken, output)
        self.assertFalse(output.exists())
        event = Event()
        event.set()
        with self.assertRaises(PackError) as caught:
            self.runtime.convert(self.source, output, event=event)
        self.assertEqual("cancelled", caught.exception.code)
        self.assertFalse(output.exists())
        self.assertFalse(list(self.root.glob(".calabash-media-*")))

    def test_tampered_bundle_preserves_installed_engine(self):
        with ZipFile(os.environ["CALABASH_FFMPEG_TEST_ZIP"]) as original:
            manifest, payload = original.read("manifest.json"), bytearray(original.read("payload.zip"))
        payload[-1] ^= 1
        tampered = self.root / "tampered.zip"
        with ZipFile(tampered, "w") as archive:
            archive.writestr("manifest.json", manifest)
            archive.writestr("payload.zip", payload)
        with self.assertRaises(PackError) as caught:
            self.manager.import_zip(tampered)
        self.assertEqual("archive_hash_mismatch", caught.exception.code)
        self.assertEqual("ready", self.manager.status("media.ffmpeg")["state"])
        self.assertEqual("audio", self.runtime.probe(self.source)["streams"][0]["codec_type"])

    def test_local_playlist_is_not_followed(self):
        playlist = self.root / "playlist.m3u8"
        playlist.write_text("#EXTM3U\n#EXTINF:1,\n" + str(self.source) + "\n")
        with self.assertRaises(PackError):
            self.runtime.probe(playlist)

    def test_output_race_never_overwrites_existing_file(self):
        destination = self.root / "result.flac"
        original = os.link
        def raced(source, target):
            destination.write_bytes(b"keep")
            return original(source, target)
        with patch("service.capabilities.media_runtime.os.link", side_effect=raced), self.assertRaises(PackError) as caught:
            self.runtime.convert(self.source, destination)
        self.assertEqual("output_exists", caught.exception.code)
        self.assertEqual(b"keep", destination.read_bytes())
