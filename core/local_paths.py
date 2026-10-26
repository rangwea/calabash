"""Calabash 本地桌面数据路径。"""

from pathlib import Path

APP_DIR_NAME = ".calabash"
DB_FILENAME = "calabash.db"


def app_dir() -> Path:
    """返回 Calabash 本地数据根目录。"""
    return Path.home() / APP_DIR_NAME


def database_path() -> Path:
    """返回本地 SQLite 数据库路径。"""
    return app_dir() / DB_FILENAME


def tools_dir() -> Path:
    """返回本地工具目录。"""
    return app_dir() / "tools"


def logs_dir() -> Path:
    """返回本地日志目录。"""
    return app_dir() / "logs"


def ensure_local_dirs() -> None:
    """确保桌面运行所需目录存在。"""
    app_dir().mkdir(parents=True, exist_ok=True)
    tools_dir().mkdir(parents=True, exist_ok=True)
    logs_dir().mkdir(parents=True, exist_ok=True)
