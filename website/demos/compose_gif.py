"""Encode recorded frames into per-demo GIFs and poster stills.

Reads frames written by record-real.cjs. Each directory is named
<demo>-<language> and produces <demo>-<language>.gif plus a matching webp.
The frames are real captures of a running tool, so the animation is presented
as a screen recording rather than an illustration.

Encoder choices that keep the capture faithful:

* Native resolution. The frames are 1120x760; downscaling softened the UI text.
* One 256-colour palette built from every frame at full size. Building it from
  small thumbnails threw away the near-white greys that make up most of an
  office UI, which is what made earlier output look grey and washed out.
* Floyd-Steinberg dithering. The UI is mostly flat panels and text; ordering the
  remaining colours without dithering left visible banding in the charts.
"""

import json
import sys
from pathlib import Path

from PIL import Image

COLORS = 256
# Frames are captured at 2x so text survives the page's downscale. The preview
# renders about 740 CSS px wide, so 1480 is exactly 2 device pixels per CSS pixel
# there: sharp on a retina screen without bloating the GIF.
OUTPUT_WIDTH = 1480


def _palette(frames: list[Image.Image]) -> Image.Image:
    """Median-cut palette from all frames at full resolution."""
    width, height = frames[0].size
    strip = Image.new("RGB", (width, height * len(frames)), "white")
    for index, frame in enumerate(frames):
        strip.paste(frame, (0, index * height))
    try:
        return strip.quantize(colors=COLORS, method=Image.Quantize.MEDIANCUT)
    finally:
        strip.close()


def encode(directory: Path) -> None:
    manifest = directory / "frames.json"
    if not manifest.exists():
        return
    entries = json.loads(manifest.read_text())
    frames = []
    for entry in entries:
        frame = Image.open(directory / entry["file"]).convert("RGB")
        if frame.width != OUTPUT_WIDTH:
            height = round(frame.height * OUTPUT_WIDTH / frame.width)
            frame = frame.resize((OUTPUT_WIDTH, height), Image.Resampling.LANCZOS)
        frames.append(frame)
    palette = _palette(frames)
    indexed = [
        frame.quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG) for frame in frames
    ]

    name = directory.name
    target = directory.parent / f"{name}.gif"
    indexed[0].save(
        target,
        save_all=True,
        append_images=indexed[1:],
        duration=[entry["duration"] for entry in entries],
        loop=0,
        optimize=True,
        disposal=1,
    )
    # The poster is the final frame, which shows the finished workspace.
    frames[-1].save(directory.parent / f"{name}.webp", quality=94, method=6)
    for frame in frames:
        frame.close()
    palette.close()
    print(f"{name}: {target} ({target.stat().st_size} bytes)")


if __name__ == "__main__":
    root = Path(sys.argv[1])
    for directory in sorted(path for path in root.iterdir() if path.is_dir()):
        encode(directory)
