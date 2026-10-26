# Calabash 本地选项控件

Calabash 桌面版没有枚举管理后台。工具内选项使用 NiceGUI 原生控件即可：

```python
status_select = (
    ui.select(["全部", "待处理", "已完成"], label="状态", value="全部")
    .props("outlined dense color=primary")
    .classes("min-w-[10rem]")
)
```

## 选择规则

- 少量固定选项：`ui.select`。
- 二选一模式：`ui.toggle` 或 `ui.radio`。
- 多选标签：`ui.select(..., multiple=True)`。
- 布尔开关：`ui.checkbox` 或 `ui.switch`。

不要导入 `core.uix.enums_select`，不要假定存在 `/admin` 枚举管理，也不要为了选项控件虚构远程枚举类型。
