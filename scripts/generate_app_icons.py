"""Generate Calabash desktop app icons without third-party dependencies."""

from __future__ import annotations

import math
import struct
import subprocess
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ICONS_DIR = ROOT / "src-tauri" / "icons"

BACKGROUND = (8, 9, 11, 255)
WHITE = (255, 255, 255, 255)
TRANSPARENT = (0, 0, 0, 0)


def _blend(dst: tuple[int, int, int, int], src: tuple[int, int, int, int], coverage: float) -> tuple[int, int, int, int]:
    alpha = max(0.0, min(1.0, coverage)) * (src[3] / 255)
    inv = 1 - alpha
    return (
        round(src[0] * alpha + dst[0] * inv),
        round(src[1] * alpha + dst[1] * inv),
        round(src[2] * alpha + dst[2] * inv),
        round(255 * (alpha + (dst[3] / 255) * inv)),
    )


def _rounded_rect_coverage(x: float, y: float, size: int, radius: float, inset: float) -> float:
    left = inset
    top = inset
    right = size - inset
    bottom = size - inset
    inner_left = left + radius
    inner_right = right - radius
    inner_top = top + radius
    inner_bottom = bottom - radius
    dx = max(inner_left - x, 0, x - inner_right)
    dy = max(inner_top - y, 0, y - inner_bottom)
    distance = math.hypot(dx, dy)
    if left <= x <= right and top <= y <= bottom and distance <= radius:
        return max(0.0, min(1.0, radius - distance + 1.0))
    return 0.0


def _letter_distance(x: float, y: float) -> float:
    dx, dy = x - 20.7, y - 20
    radius = 9.5
    # The right-hand opening and round stroke caps form a capital C.
    if abs(math.atan2(dy, dx)) >= math.pi / 4:
        return abs(math.hypot(dx, dy) - radius)
    end = radius / math.sqrt(2)
    return min(math.hypot(dx - end, dy - end), math.hypot(dx - end, dy + end))


def _stroke_coverage(distance: float, width: float) -> float:
    return max(0.0, min(1.0, (width / 2) - distance + 1.0))


def _write_png(path: Path, width: int, height: int, pixels: list[tuple[int, int, int, int]]) -> None:
    rows = []
    for y in range(height):
        row = bytearray([0])
        for pixel in pixels[y * width : (y + 1) * width]:
            row.extend(pixel)
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _render(size: int) -> list[tuple[int, int, int, int]]:
    scale = size / 40
    pixels: list[tuple[int, int, int, int]] = []
    for y in range(size):
        for x in range(size):
            # Keep the artwork inside the macOS Dock's optical icon bounds.
            px = ((x + 0.5) / scale - 20) / 0.84 + 20
            py = ((y + 0.5) / scale - 20) / 0.84 + 20
            samples = []
            # Supersample in output-pixel space; design-unit feathering blurs
            # high-resolution icons and exaggerates curved-edge stair steps.
            for ox, oy in ((-0.25, -0.25), (0.25, -0.25), (-0.25, 0.25), (0.25, 0.25)):
                sx = px + ox / (scale * 0.84)
                sy = py + oy / (scale * 0.84)
                if _rounded_rect_coverage(sx, sy, 40, 10, 1) == 0:
                    samples.append(TRANSPARENT)
                    continue
                distance = _letter_distance(sx, sy)
                samples.append(WHITE if distance <= 2.5 else BACKGROUND)
            opaque = [sample for sample in samples if sample[3]]
            if opaque:
                pixels.append(tuple(round(sum(s[i] for s in opaque) / len(opaque)) for i in range(3)) + (round(255 * len(opaque) / 4),))
            else:
                pixels.append(TRANSPARENT)
    return pixels


def _save_png(name: str, size: int) -> None:
    _write_png(ICONS_DIR / name, size, size, _render(size))


def main() -> None:
    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    _save_png("icon.png", 1024)

    subprocess.run(["npm", "exec", "tauri", "icon", str(ICONS_DIR / "icon.png")], cwd=ROOT, check=True)

    cleanup_paths = [
        ICONS_DIR / "android",
        ICONS_DIR / "ios",
        *ICONS_DIR.glob("Square*Logo.png"),
        ICONS_DIR / "StoreLogo.png",
    ]
    for path in cleanup_paths:
        if path.is_dir():
            for child in sorted(path.rglob("*"), reverse=True):
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            path.rmdir()
        elif path.exists():
            path.unlink()

    print(f"Generated icons in {ICONS_DIR}")


if __name__ == "__main__":
    main()
