"""FastAPI + NiceGUI 应用工厂。"""

import datetime

# 扩展 NiceGUI 的 orjson 序列化器，支持 pandas.Timestamp 等非标准类型
import nicegui.json.orjson_wrapper as _orjson_mod
from fastapi import FastAPI
from nicegui import ui

# 导入页面模块以注册路由
from ui import pages as _pages  # noqa: F401
from core.app_info import APP_NAME, APP_VERSION
from core.i18n import language
from core.local_paths import app_dir
from core.styles import apply_app_styles
from api.health_api import router as health_api_router
from api.tool_api import router as tool_api_router
from service.tools.tool_index_watcher import start_tool_index_watcher

STORAGE_SECRET = f"calabash-{app_dir()}"

_original_converter = _orjson_mod._orjson_converter


def _extended_orjson_converter(obj):
    """扩展的 orjson 类型转换器，支持 pandas.Timestamp、datetime 等类型。"""
    if hasattr(obj, "isoformat") and callable(obj.isoformat):
        return obj.isoformat()
    if isinstance(obj, (datetime.date, datetime.time)):
        return obj.isoformat()
    return _original_converter(obj)


_orjson_mod._orjson_converter = _extended_orjson_converter


def create_app() -> FastAPI:
    """创建并配置 FastAPI + NiceGUI 应用。"""
    project_path = ""
    fapp = FastAPI(
        title=APP_NAME,
        description="本地 AI 工具桌面",
        version=APP_VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    fapp.include_router(health_api_router, prefix=project_path)
    fapp.include_router(tool_api_router, prefix=project_path)

    apply_app_styles()
    from service.capabilities.capability_packs import recover_existing
    from service.files.conversation_files import cleanup_uploads
    cleanup_uploads()
    recover_existing()
    start_tool_index_watcher()
    ui.run_with(
        fapp,
        storage_secret=STORAGE_SECRET,
        language="en-US" if language() == "en" else "zh-CN",
        mount_path="/",
    )

    return fapp
