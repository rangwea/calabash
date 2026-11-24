"""Encode recorded frames into per-demo GIFs and poster stills.

Reads frames written by record-real.cjs. Each directory is named
<demo>-<language> and produces <demo>-<language>.gif plus a matching webp.
The frames are real captures of a running tool, so the animation is presented
as a screen recording rather than an illustration.
"""

import json
import sys
from pathlib import Path

from PIL import Image

SIZE = (960, 651)


def encode(directory: Path) -> None:
    manifest = directory / "frames.json"
    if not manifest.exists():
        return
    entries = json.loads(manifest.read_text())
    frames = [Image.open(directory / entry["file"]).convert("RGB") for entry in entries]
    resized = [frame.resize(SIZE, Image.Resampling.LANCZOS) for frame in frames]

    montage = Image.new("RGB", (320, 217 * len(frames)), "white")
    for index, frame in enumerate(frames):
        montage.paste(frame.resize((320, 217)), (0, index * 217))
    palette = montage.quantize(colors=192, method=Image.Quantize.MEDIANCUT)
    indexed = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in resized]

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
    resized[-1].save(directory.parent / f"{name}.webp", quality=92, method=6)
    for frame in frames:
        frame.close()
    print(f"{name}: {target} ({target.stat().st_size} bytes)")


if __name__ == "__main__":
    root = Path(sys.argv[1])
    for directory in sorted(path for path in root.iterdir() if path.is_dir()):
        encode(directory)
