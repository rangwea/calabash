# Calabash 工具 UI：Fluent 2 办公设计规范

本规范参考 Microsoft Fluent 2 的色彩、排版、间距和主题体系，落实到 NiceGUI；不是要求安装 Fluent React，也不是复制 Windows 外观。

官方依据：[原则](https://fluent2.microsoft.design/design-principles)、[色彩](https://fluent2.microsoft.design/color)、[布局](https://fluent2.microsoft.design/layout)、[排版](https://fluent2.microsoft.design/typography)、[设计变量](https://fluent2.microsoft.design/design-tokens)。下面的颜色、尺寸是 Calabash 默认建议，可随任务和参考图调整。

## 先决定工具是什么

先明确主要任务、主要对象和状态，再选择适合它的构图。用户明确要求的参考图、风格、配色与布局优先。不要把播放器、记账、客户管理和文件处理都生成成同一张灰色后台表单。

- 简单输入与结果：`simple-tool.py`。
- 搜索、分页和详情：`query-tool.py`。
- 文件选择、批处理和结果交付：`file-tool.py`，保留现有执行协议。
- 数据分析和办公工作区：`office-workspace.py`，含图表、筛选、表格和状态。
- 媒体或创作工具：`media-workspace.py`，局部深色主题、主内容和独立控制区。
- 更多构图建议见 `design-scenes.md`；复杂交互见 `design-details.md`。

## App 外壳与工具主题分开

App 的导航、聊天和设置由宿主维护。工具 `main()` 在 `.calabash-tool` 容器里运行，默认办公蓝主题。工具可以在自己的根类内选择主题、暗色表面、圆角、字体层级和布局。

仍然不能调用页面根布局 `ui.left_drawer/right_drawer/header/footer` 或 `ui.run()`；菜单、顶栏和底部播放器用工具内部的 row/column/grid 组合。

不要用 `ui.colors()`、`ui.*.default_*`、无作用域 `.q-btn/.q-card` CSS 或修改 `:root/body` 给工具换肤，这会影响宿主或别的工具。CSS 用自己的根类限定；不要依赖全局覆盖和 `!important`。

## 主题变量

宿主提供 `--tool-*` 和工具局部的 Quasar `--q-primary`；生成代码可以覆盖这些变量。基础示例：

```python
ui.add_css('''
.my-tool {
    --tool-accent: #0f766e;
    --tool-accent-soft: #ecf8f5;
    --q-primary: var(--tool-accent);
}
.my-tool .summary { color: var(--tool-accent); }
''')
with ui.column().classes('my-tool w-full gap-4'):
    ...
```

自定义色值集中声明在局部主题变量中，组件复用变量。可以用预设根类 `tool-theme-teal` 或 `tool-theme-violet`。变量覆盖会通过 CSS 级联作用于本工具的控件，不改变 App 品牌。

| 变量 / 类 | 默认 / 用途 |
|---|---|
| `--tool-accent` | `#0F6CBD`，主动作和选中态 |
| `--tool-accent-soft` | `#EFF6FC`，浅强调表面 |
| `--tool-on-accent` | 主色按钮上的文字，默认白色；自定浅色主题需一起调整 |
| `--tool-canvas` / `--tool-surface` | `#F5F7FB` / 白色，画布与内容表面 |
| `--tool-text` / `--tool-muted` | 正文 `#242424` / 辅助文字 `#616B7A` |
| `--tool-control-height` / `--tool-row-height` | 默认 36px / 40px；紧凑工作区可局部调整 |
| `--tool-border` | `#E5E7EB`，分隔和输入边界 |
| `--tool-success/warning/danger` | 状态语义；不要让装饰配色与危险/成功反馈混淆 |
| `tool-title` / `tool-subtitle` | 页面标题 / 分区标题 |
| `tool-panel` / `tool-panel-muted` | 内容面板 / 次级表面 |
| `tool-selected` / `tool-text-accent` | 导航选中反馈 / 强调文字 |

同一工具通常选一个主色，按需要补充辅助色。图表的分类色与状态色单独定义：蓝、青、紫、橙可以区分数据系列，不必把全部数据都画成灰色，也不必为普通分类强套“成功/失败”语义。配上文字、图例和数值。

深色工具同时定义画布、面板、文字、边框和状态色，不是只把背景改黑。弹出到 body 的菜单/弹窗需使用工具专属的内容类设置局部主题，不能依赖父节点变量穿透 portal。选中、hover、focus 和 disabled 都应清晰。

## 排版、尺寸与表面

- 默认系统字体，正文 14px / 20–22px；说明 12–13px；分区标题 16px；工具标题 20–24px。表格、日志、数据金额可用等宽数字。
- 采用 4px 间距体系，常用 8/12/16/24px；组间距应大于组内间距。密集数据和轻量创作界面可以使用不同密度。
- 默认操作高度约 36px，紧凑模式 32px，触控或主要动作可用 40px。浮动 label 的 Quasar 输入保留原生高度，不能硬压导致文字重叠。
- 外置 label 加 `outlined dense hide-bottom-space` 是一种办公表单基线，不是所有控件必须遵守的外观。搜索、编辑器、媒体等可用 filled、borderless 或专用布局。
- 控件约 6px 圆角，面板约 8px；工具可调整。弹窗、菜单和浮层用轻阴影表达层级，普通内容面板默认轻边框。
- 允许与任务相关的插画、封面、有节制的渐变和大尺寸数字；不要让装饰挤占核心工作区。卡片是分组手段，不要求处处加卡片，也不禁止有意义的嵌套。

## 布局与控件

工具壳已经提供边距和可用宽度，根节点通常只需 `w-full min-w-0`；不要重复套 App 顶栏。内容宽度由任务决定：长文阅读适当收窄；表格、图表、媒体工作区充分利用空间。

表单可以用响应式 grid 对齐字段；菜单、列表详情和媒体控制可以用 row/column。不要强制把所有内容排成一列或同一网格。

- 输入与按钮在同一行时使用明确的对齐关系，窄窗口换行。用 `min-w-0`、`minmax(0,1fr)` 允许内容收缩。
- 表格自身允许横向滚动，整页不应因长路径、日志或控件产生意外横向滚动。
- 图标采用一致的线性风格，常用 16–20px；只含图标的操作有 tooltip。
- 主操作突出，其他动作分层；不同独立工作区可以各自有主动作，不机械要求全页只能有一个按钮。
- 使用真实、任务相关的空状态与初始内容。示例数据必须注明“合成数据”；没有真实来源的数据不得冒充业务结果。

## 行为与验收

- 初始、加载、空、成功、失败状态可识别；颜色之外有文字和图标，键盘焦点可见。
- 避免灰字配浅灰底、仅靠 hover 才能发现关键操作。普通文字对比度目标至少 4.5:1。
- 输入不因排版被裁切；窄窗口仍能完成任务。允许合理的区域滚动，不把滚动条一概隐藏。
- UI 从后台更新时进入目标容器；慢操作走已有 ToolTask/ToolJobs，继续保留取消、输入冻结和结果文件协议。
- 参考图优先，按任务调整布局；不以“统一”为由拒绝用户指定的风格。
- CSS 只作用于本工具；验证 App 导航和相邻工具没有被换肤。
- 静态校验只证明代码结构；没有实际运行或观察界面时，不声称视觉验收通过。
