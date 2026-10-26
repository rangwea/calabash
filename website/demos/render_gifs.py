"""Turn real captured UI states into optimized GIFs and still posters."""

import argparse
import json
from pathlib import Path

from PIL import Image


def render(source: Path, destination: Path, workflow: bool = False) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for manifest in sorted(source.glob("*/frames.json")):
        entries = json.loads(manifest.read_text())
        frames = [
            Image.open(manifest.parent / entry["file"]).convert("RGB")
            for entry in entries
        ]
        resized = [
            frame.resize((960, 651), Image.Resampling.LANCZOS) for frame in frames
        ]
        montage = Image.new("RGB", (320, 217 * len(frames)), "white")
        for index, frame in enumerate(frames):
            montage.paste(frame.resize((320, 217)), (0, index * 217))
        palette = montage.quantize(colors=192, method=Image.Quantize.MEDIANCUT)
        indexed = [
            frame.quantize(palette=palette, dither=Image.Dither.NONE)
            for frame in resized
        ]
        name = manifest.parent.name
        indexed[0].save(
            destination / f"{name}.gif",
            save_all=True,
            append_images=indexed[1:],
            duration=[entry["duration"] for entry in entries],
            loop=0,
            optimize=True,
            disposal=1,
        )
        poster_index = 0 if name.startswith("customers-") else 3
        poster = frames[poster_index + 7 if workflow else poster_index]
        poster.save(destination / f"{name}.webp", quality=92, method=6)
        if name.startswith("ledger-"):
            poster.save(
                destination / f"hero-{name.split('-')[-1]}.webp", quality=95, method=6
            )
        for frame in frames:
            frame.close()
        print(name, (destination / f"{name}.gif").stat().st_size)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--workflow", action="store_true", help="Render illustrated chat plus real tool recordings")
    arguments = parser.parse_args()
    render(arguments.source, arguments.destination, arguments.workflow)
