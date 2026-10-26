"""
本地工具文件扫描与 SQLite 索引同步。
"""

import hashlib
import os
import json
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlmodel import select

from core.database import db_manager
from core.local_paths import app_dir, ensure_local_dirs, tools_dir
from core.logger import get_logger
from models.tool import Tool
from service.tools.tool_metadata import parse_tool_metadata
from service.tools.tool_activity import ToolBusyError, is_tool_running
from service.tools.tool_service import _validate_tool_identity

logger = get_logger(__name__)


@dataclass
class ToolMeta:
    """工具元数据"""

    project: str  # 所属项目（目录名）
    name: str  # 工具名（文件名，不含 .py）
    title: str  # 工具标题（从 docstring 的 name 字段）
    description: str  # 工具描述
    creator: str  # 创建者
    created_at: str  # 创建时间
    updated_at: str  # 更新时间
    path: str  # 相对路径
    tags: str = ""  # 工具标签，逗号分隔
    revision: str = ""  # 当前文件内容哈希，用于乐观锁
    requires: str = ""  # 文件声明的可选能力，不写入数据库

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "creator": self.creator,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "path": self.path,
            "tags": self.tags,
            "revision": self.revision,
            "requires": self.requires,
        }


def _get_tools_base_dir() -> str:
    """获取 tools 基础目录的绝对路径"""
    ensure_local_dirs()
    return str(tools_dir())


def _parse_tool_meta(filepath: str, project: str, tool_name: str) -> ToolMeta | None:
    """从文件中解析工具元数据"""
    try:
        content = _read_tool_file(filepath)

        metadata = parse_tool_metadata(content)

        # 默认值
        title = tool_name
        description = ""
        creator = ""
        created_at = ""
        updated_at = ""
        tags = ""

        if metadata:
            title = metadata.get("name", tool_name)
            description = metadata.get("description", "")
            creator = metadata.get("creator", "")
            created_at = metadata.get("created_at", "")
            updated_at = metadata.get("updated_at", "")
            tags = metadata.get("tags", "")

        # 计算相对路径
        tools_dir = _get_tools_base_dir()
        rel_path = os.path.relpath(filepath, os.path.dirname(tools_dir))

        return ToolMeta(
            project=project,
            name=tool_name,
            title=title,
            description=description,
            creator=creator,
            created_at=created_at,
            updated_at=updated_at,
            path=rel_path,
            tags=tags,
            revision=calculate_revision(content),
            requires=metadata.get("requires", ""),
        )

    except Exception as e:
        logger.error(f"解析工具元数据失败 {filepath}: {e}")
        return None


def _sync_tool_index(meta: ToolMeta, filename: str) -> None:
    """将本地工具文件元数据同步到 SQLite 索引。"""
    if not db_manager:
        return

    try:
        file_stat = os.stat(os.path.join(_get_tools_base_dir(), meta.project, filename))
        file_mtime = datetime.fromtimestamp(file_stat.st_mtime)
        with db_manager.session_scope() as session:
            statement = select(Tool).where(
                Tool.project == meta.project,
                Tool.filename == filename,
            )
            tool = session.exec(statement).first()
            if not tool:
                tool = Tool(
                    project=meta.project,
                    filename=filename,
                    created_at=file_mtime,
                )
            tool.display_name = meta.title
            tool.description = meta.description or None
            tool.creator = meta.creator or None
            tool.tags = meta.tags or None
            tool.updated_at = file_mtime
            session.add(tool)
    except Exception as e:
        logger.warning(f"同步工具索引失败 {meta.project}/{filename}: {e}")


def calculate_revision(content: str) -> str:
    """计算工具内容 revision，用于客户端提交时的乐观锁。"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _read_tool_file(filepath: str) -> str:
    """读取工具文件内容。"""
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


# ============================================================================
# 公开 API
# ============================================================================


def list_tools(project: str | None = None) -> list[dict[str, Any]]:
    """
    列出所有工具

    Args:
        project: 可选，按项目过滤

    Returns:
        工具元数据列表
    """
    tools_dir = _get_tools_base_dir()

    if not os.path.exists(tools_dir):
        logger.warning(f"工具目录不存在: {tools_dir}")

    if not os.path.exists(tools_dir):
        return []

    tools = []

    # 确定要扫描的项目目录
    if project:
        project_dirs = (
            [project] if os.path.isdir(os.path.join(tools_dir, project)) else []
        )
    else:
        project_dirs = [
            d
            for d in os.listdir(tools_dir)
            if os.path.isdir(os.path.join(tools_dir, d)) and not d.startswith("_")
        ]

    for project_name in project_dirs:
        project_path = os.path.join(tools_dir, project_name)

        for filename in os.listdir(project_path):
            if filename.endswith(".py") and filename != "__init__.py":
                filepath = os.path.join(project_path, filename)
                tool_name = filename[:-3]  # 去掉 .py

                meta = _parse_tool_meta(filepath, project_name, tool_name)
                if meta:
                    _sync_tool_index(meta, filename)
                    tools.append(meta.to_dict())

    return tools


def delete_tool(project: str, name: str, *, revision: str) -> None:
    """Delete only the selected tool and its sidecar, never user outputs or logs."""
    _validate_tool_identity(project, name)
    if is_tool_running(project, name):
        raise ToolBusyError()
    root = Path(tools_dir()).resolve()
    path = root / project / f"{name}.py"
    sidecar = path.with_name(f"{path.name}.calabash.json")
    if path.parent.is_symlink() or path.is_symlink() or sidecar.is_symlink():
        raise ValueError("unsafe_path")
    if not path.resolve().is_relative_to(root):
        raise ValueError("unsafe_path")
    if path.exists() and calculate_revision(_read_tool_file(str(path))) != revision:
        raise ValueError("changed")
    # Missing files are allowed so a failed cleanup can be safely retried.
    sidecar.unlink(missing_ok=True)
    path.unlink(missing_ok=True)
    with db_manager.session_scope() as session:
        for record in session.exec(
            select(Tool).where(Tool.project == project, Tool.filename == f"{name}.py")
        ).all():
            session.delete(record)
    recent = app_dir() / "recent_tools.json"
    try:
        keys = json.loads(recent.read_text(encoding="utf-8"))
        if isinstance(keys, list):
            recent.write_text(
                json.dumps(
                    [key for key in keys if key != f"{project}/{name}"],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        logger.warning("Unable to clean recent tool record after deletion")
