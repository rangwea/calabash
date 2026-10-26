"""Calabash 桌面模式后端入口。"""

import argparse
import json
import multiprocessing
import socket
import sys


def _find_free_port() -> int:
    """查找一个本地空闲端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calabash desktop backend")
    parser.add_argument(
        "--print-ready",
        action="store_true",
        help="Print a machine-readable readiness line before starting uvicorn.",
    )
    parser.add_argument("--check-runtime", action="store_true", help="Check bundled tool libraries offline and exit.")
    parser.add_argument("--check-media", action="store_true", help="Check the installed media plugin offline and exit.")
    return parser.parse_args()


def _prepare_runtime(args: argparse.Namespace) -> tuple[str, int]:
    host = "127.0.0.1"
    port = _find_free_port()
    return host, port


def main() -> None:
    multiprocessing.freeze_support()
    if "--file-reader" in sys.argv:
        from service.files.file_reader_worker import main as read_file
        read_file()
        return
    args = _parse_args()
    if args.check_media:
        from service.capabilities.media_runtime import check_media
        try:
            result = check_media()
        except (OSError, ValueError) as error:
            result = {"ok": False, "error": str(error)}
        print(json.dumps(result), flush=True)
        if not result["ok"]:
            raise SystemExit(1)
        return
    if args.check_runtime:
        from core.runtime_capabilities import check_runtime
        result = check_runtime()
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if not result["ok"]:
            raise SystemExit(1)
        return
    host, port = _prepare_runtime(args)

    import uvicorn

    from core.app_factory import create_app
    from core.database import db_manager
    from core.local_paths import ensure_local_dirs
    from core.logger import get_logger

    logger = get_logger(__name__)

    try:
        ensure_local_dirs()

        if db_manager:
            db_manager.create_tables()

        fapp = create_app()
        url = f"http://{host}:{port}/"
        logger.info(f"桌面后端启动: {url}")
        if args.print_ready:
            print(
                "CALABASH_READY "
                + json.dumps({"host": host, "port": port, "url": url}),
                flush=True,
            )
            sys.stdout.flush()
        uvicorn.run(
            fapp,
            host=host,
            port=port,
            log_config=None,
            access_log=False,
        )
    finally:
        if db_manager:
            db_manager.close()
        logger.info("桌面后端已关闭")


if __name__ == "__main__":
    main()
