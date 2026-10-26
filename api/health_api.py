"""健康检查 API。"""

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from core.app_info import APP_NAME, APP_VERSION

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_class=PlainTextResponse)
async def health():
    """健康检查。"""
    return "OK"


@router.get("/info")
async def health_info():
    """结构化健康检查。"""
    return {
        "status": "ok",
        "mode": "desktop",
        "name": APP_NAME,
        "version": APP_VERSION,
    }
