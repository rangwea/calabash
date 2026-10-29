import os
import re
from typing import Any, Optional

from core.local_paths import tools_dir
from core.logger import get_logger, get_tool_logger
from service.capabilities.tool_capabilities import ToolCapabilityError
from service.tools.tool_runtime import load_tool_entrypoint

# 获取日志器
logger = get_logger(__name__)

_TOOL_IDENTITY_PATTERN = re.compile(r"^[a-z0-9_-]+$")


def _validate_tool_identity(project_name: str, tool_name: str) -> None:
    """拒绝可能逃逸工具根目录的项目名和工具名。"""
    if not _TOOL_IDENTITY_PATTERN.fullmatch(project_name or ""):
        raise ValueError(f"项目名称不合法: {project_name!r}")
    if not _TOOL_IDENTITY_PATTERN.fullmatch(tool_name or ""):
        raise ValueError(f"工具名称不合法: {tool_name!r}")


def load_and_execute_project_tool(
    project_name: str, tool_name: str, *, module_name: str | None = None
) -> Optional[callable]:
    """动态加载并执行指定项目的工具"""
    _validate_tool_identity(project_name, tool_name)
    tool_logger = get_tool_logger(project_name, tool_name)
    try:
        project_dir = os.path.join(os.path.abspath(tools_dir()), project_name)

        if not os.path.exists(project_dir):
            tool_logger.warning(f"项目目录不存在: {project_dir}")
            raise Exception(
                f"项目不存在: 未找到项目 '{project_name}'，请检查项目是否已正确配置。"
            )

        # 查找工具文件
        tool_file = None
        for filename in os.listdir(project_dir):
            if filename.endswith(".py") and filename != "__init__.py":
                name_without_ext = filename.replace(".py", "")
                if name_without_ext == tool_name:
                    tool_file = filename
                    break

        if not tool_file:
            tool_logger.warning(f"项目工具文件不存在: {project_name}/{tool_name}")
            raise Exception(
                f"工具不存在: 在项目 '{project_name}' 中未找到工具 '{tool_name}'。"
            )

        filepath = os.path.join(project_dir, tool_file)

        tool_logger.info(f"Loading main function from {project_name}/{tool_file}")
        return load_tool_entrypoint(module_name or f"tools_{project_name}_{tool_name}", filepath)

    except ToolCapabilityError:
        raise
    except Exception as e:
        if (
            "工具不存在" in str(e)
            or "工具目录不存在" in str(e)
        ):
            raise
        tool_logger.exception(
            f"Error loading project tool {project_name}/{tool_name}: {e}"
        )
        raise Exception(f"工具加载失败: {project_name}/{tool_name} - {str(e)}")


def get_tool_by_name(
    tool_name: str, project_name: Optional[str] = None
) -> Optional[dict[str, Any]]:
    """根据名称获取工具信息"""
    try:
        from service.tools.tool_manage_service import list_tools

        tools = list_tools(project=project_name)

        for tool in tools:
            if tool.get("name") == tool_name:
                if project_name is None or tool.get("project") == project_name:
                    return tool

        return None

    except Exception as e:
        logger.error(f"获取工具信息失败: {e}")
        return None
