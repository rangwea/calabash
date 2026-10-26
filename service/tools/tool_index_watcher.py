"""本地工具目录变更监听。"""

from __future__ import annotations

import threading
from pathlib import Path

from watchfiles import watch

from core.local_paths import ensure_local_dirs, tools_dir
from core.logger import get_logger

logger = get_logger(__name__)
_changed = threading.Event()
_started = False
_start_lock = threading.Lock()


def start_tool_index_watcher() -> None:
    """启动一次后台文件监听线程。"""
    global _started
    with _start_lock:
        if _started:
            return
        ensure_local_dirs()
        threading.Thread(target=_watch_tools, name="calabash-tool-watcher", daemon=True).start()
        _started = True


def consume_tool_change() -> bool:
    """消费一次工具目录变更信号。"""
    if not _changed.is_set():
        return False
    _changed.clear()
    return True


def _watch_tools() -> None:
    try:
        for changes in watch(tools_dir()):
            if any(_is_tool_file(path) for _, path in changes):
                _changed.set()
    except Exception:
        logger.exception("工具目录监听停止")


def _is_tool_file(path: str) -> bool:
    candidate = Path(path)
    return candidate.suffix == ".py" and candidate.name != "__init__.py"
