"""Frozen tool executor entry; installed apps never need a system Python."""

import asyncio
import json
import multiprocessing
import sys


def main():
    multiprocessing.freeze_support()
    if "--check-runtime" in sys.argv:
        from core.runtime_capabilities import check_runtime

        result = check_runtime()
        print(json.dumps(result))
        raise SystemExit(0 if result["ok"] else 1)
    from backend.harness_bridge import serve

    asyncio.run(serve())


if __name__ == "__main__":
    main()
