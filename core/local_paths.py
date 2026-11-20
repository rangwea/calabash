"""Calabash 本地桌面数据路径。"""

from pathlib import Path

APP_DIR_NAME = ".calabash"


def app_dir() -> Path:
    """返回 Calabash 本地数据根目录。"""
    return Path.home() / APP_DIR_NAME




def tools_dir() -> Path:
    """返回本地工具目录。"""
    return app_dir() / "tools"


def logs_dir() -> Path:
    """返回本地日志目录。"""
    return app_dir() / "logs"


def ensure_local_dirs() -> None:
    """确保桌面运行所需目录存在。

    根目录存工具源码、结果文件和本地数据库，只允许当前用户访问；
    这是执行器启动时最先落盘的路径，必须在这里收紧，而不是依赖各子服务各自加固。
    """
    for path in (app_dir(), tools_dir(), logs_dir()):
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        # mkdir 的 mode 只作用于新建目录，且会被 umask 削弱；已存在的旧目录仍需收紧。
        path.chmod(0o700)
