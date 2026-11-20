import logging
import sys

from loguru import logger

from core.local_paths import logs_dir

# App logs are separate from per-run tool logs managed by core.tool_run_logs.
LOG_BASE_DIR = logs_dir()

# ── 日志格式 ────────────────────────────────────────────────────────────────────
_CONSOLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)
_FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"
)
class InterceptHandler(logging.Handler):
    """Forward standard-library logs; the patcher assigns the active run."""

    def emit(self, record):
        # 获取对应的 loguru level
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # 找到调用者的帧
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        bound_logger = logger
        bound_logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def setup_logger():
    """Configure App logs and route tool logs through per-run sinks."""
    from core.tool_run_logs import add_context
    logger.configure(patcher=add_context)
    # 移除默认处理器
    logger.remove()

    # 控制台输出
    logger.add(
        sys.stdout,
        format=_CONSOLE_FORMAT,
        level="INFO",
        colorize=True,
        backtrace=False,
        diagnose=False,
    )

    # File sinks are best effort: the app must still start when the home directory
    # is read-only (locked-down CI, read-only install, restricted sandbox). Losing
    # local file logs is recoverable; refusing to import this module is not.
    for name, level in (("app.log", "DEBUG"), ("error.log", "ERROR")):
        try:
            LOG_BASE_DIR.mkdir(parents=True, exist_ok=True)
            logger.add(
                LOG_BASE_DIR / name,
                format=_FILE_FORMAT,
                level=level,
                rotation="10 MB",
                retention="30 days",
                compression="zip",
                encoding="utf-8",
                backtrace=False,
                diagnose=False,
            )
        except OSError:
            logger.warning("Local log file {} is unavailable; continuing with console output", name)

    return logger


def setup_third_party_logging():
    """配置第三方库日志拦截"""
    # 拦截标准库 logging
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)


# ── 初始化 ──────────────────────────────────────────────────────────────────────
app_logger = setup_logger()
setup_third_party_logging()


# ── 公开 API ────────────────────────────────────────────────────────────────────


def get_logger(name: str = ""):
    """获取指定名称的日志器。"""
    if name:
        return logger.bind(name=name)
    return logger


def get_tool_logger(tool_type: str, tool_name: str):
    return logger.bind(name=f'tool.{tool_type}.{tool_name}', tool_type=tool_type, tool_name=tool_name)
