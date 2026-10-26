# Calabash 本地数据访问

Calabash 桌面版只支持本地运行。工具需要持久化或读取数据时，优先使用：

- Python 标准库文件 API，路径位于 `~/.calabash` 下；
- SQLite，数据库文件由工具自己定义，或读取 Calabash 的本地 SQLite 索引；
- 用户明确提供的本地文件路径。

不要在工具中假定存在平台 MySQL、MongoDB、远程数据源管理、管理员后台或数据源导入界面。
CLI 不提供数据源查询命令，直接使用本地文件或 SQLite API。

## 路径约定

```python
from pathlib import Path


def calabash_home() -> Path:
    return Path.home() / ".calabash"


def tool_data_dir(project: str, name: str) -> Path:
    path = calabash_home() / "tool-data" / project / name
    path.mkdir(parents=True, exist_ok=True)
    return path
```

- 工具自己的缓存、偏好和状态文件放在 `~/.calabash/tool-data/<project>/<name>`；用户交付文件使用 `ToolResults.outputs.write`，由平台登记到 outputs 并恢复历史，详见 [file-workflow.md](file-workflow.md)。
- 不把运行时数据写回 `~/.calabash/tools`，工具目录只放 `.py` 工具文件和 sidecar 元数据。
- 接收用户输入路径时使用 `Path.expanduser()`，并在执行写入前给出清楚提示。
- 用户文件优先通过 `ToolFileInput` 选择或承接会话默认附件；不要把当前机器路径写死进工具。不要直接写入 conversations.db 的附件、上下文或结果历史表。

## SQLite

```python
import sqlite3
from pathlib import Path


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn
```

- 使用参数绑定，不拼接用户输入到 SQL。
- 大结果集使用分页，不先全量读取再切片。
- 阻塞文件和 SQLite 操作放到 `run.io_bound` 中执行，避免卡住 NiceGUI 事件循环。
- 异常写日志，界面展示可行动的友好错误，不把 SQL、绝对敏感路径或 traceback 直接显示给用户。
