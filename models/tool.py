"""
Tool 模型
元数据从文件 header 注释解析，SQLite 仅作为本地索引。
"""

from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class ToolBase(SQLModel):
    """Tool 基础模型"""

    project: str = Field(
        description="所属项目（工具分组名）",
        max_length=100,
        index=True,
    )
    filename: str = Field(
        description="文件名（如 tool_query.py）",
        max_length=200,
    )
    display_name: str = Field(
        default="",
        description="显示标题（从 header 注释解析）",
        max_length=200,
    )
    description: str | None = Field(
        default=None,
        description="工具描述（从 header 注释解析）",
        max_length=1000,
    )
    tags: str | None = Field(
        default=None,
        description="工具标签，逗号分隔（如 data,export,finance）",
        max_length=500,
    )


class Tool(ToolBase, table=True):
    """Tool 数据库模型"""

    __tablename__ = "tools"
    __table_args__ = (
        UniqueConstraint("project", "filename", name="uq_tool_project_filename"),
    )

    id: int | None = Field(default=None, primary_key=True, description="Tool ID")
    creator: str | None = Field(
        default=None,
        description="创建者（从 header 注释解析）",
        max_length=100,
    )
    created_at: datetime | None = Field(
        default_factory=datetime.now,
        description="创建时间",
    )
    updated_at: datetime | None = Field(
        default_factory=datetime.now,
        description="更新时间",
    )
