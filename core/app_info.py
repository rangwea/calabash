"""Application identity shared by source and bundled Python runtimes."""

import json
from pathlib import Path

_METADATA = json.loads(
    (Path(__file__).resolve().parents[1] / "package.json").read_text(encoding="utf-8")
)
APP_NAME = _METADATA["productName"]
APP_VERSION = _METADATA["version"]
