# Calabash 本地参数

Calabash 桌面版不再提供后台变量管理。工具需要参数时，按以下顺序处理：

1. 工具内固定选项：写成单文件常量或普通 `ui.select` 选项。
2. 用户每次运行都会调整的值：放在工具 UI 控件中。
3. 需要跨次运行保存的值：由工具自行保存到 `~/.calabash/tool-data/<project>/<name>`。
4. 敏感值：除非用户明确要求，不主动持久化；必须持久化时不要写入日志或页面输出。

CLI 不提供平台变量命令。不要生成依赖
`core.variable_manager.variables`、管理后台变量或远程配置中心的工具代码。

## 本地配置示例

```python
import json
from pathlib import Path
from typing import Any


CONFIG_PATH = Path.home() / ".calabash" / "tool-data" / "demo" / "sample" / "config.json"


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.is_file():
        return {}
    with CONFIG_PATH.open("r", encoding="utf-8") as source:
        return json.load(source)


def save_config(data: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w", encoding="utf-8") as target:
        json.dump(data, target, ensure_ascii=False, indent=2)
```

- 读取配置时显式校验类型和范围。
- 配置缺失时提供默认值或明确告诉用户需要填写什么。
- 不在模块导入阶段读取可能失败的配置；在 `main` 或用户触发动作中读取。
