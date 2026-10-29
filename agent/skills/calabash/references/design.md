# Calabash UI 设计系统

## 目录

1. [设计目标](#设计目标)
2. [设计决策流程](#设计决策流程)
3. [平台与视觉基线](#平台与视觉基线)
4. [页面叙事与构图](#页面叙事与构图)
5. [视觉语法](#视觉语法)
6. [核心组件](#核心组件)
7. [状态与反馈](#状态与反馈)
8. [响应式与可访问性](#响应式与可访问性)
9. [实现约束](#实现约束)
10. [验收标准](#验收标准)

---

## 设计目标

Calabash 页面应像成熟后台产品中的一个专注工作区：用户进入后能迅速理解当前对象、完成主要任务，并确认结果。美感来自清楚的阅读顺序、稳定的视觉节奏和恰当的信息密度，不来自装饰堆叠。

每个页面同时满足以下五点：

| 目标 | 可观察结果 |
|---|---|
| 一眼可懂 | 第一屏说明“在处理什么、当前怎样、下一步做什么” |
| 有主有次 | 页面只有一个视觉焦点和一个主要动作 |
| 紧凑舒展 | 高频区域密度高，语义分组之间有呼吸感 |
| 状态完整 | 初始、加载、空、成功、失败均有明确界面 |
| 平台一致 | 使用现有主题色、页面壳、圆角和轻边框，不另造品牌 |

### 设计边界

- Calabash 是业务工具，不是营销落地页、数据大屏或作品集。
- 默认使用浅色、低对比表面；主题色用于焦点和关键操作，不承担大面积装饰。
- 不使用渐变、玻璃拟态、发光、悬浮大阴影、装饰性大图标或彩虹色卡片。
- 不追求“所有地方都有内容”；有意留白用于建立层级。
- 不把“好看”等同于“大标题 + 多指标卡 + 多图标”。

---

## 设计决策流程

写 UI 代码前，依次完成四个判断。不要从选择组件或颜色开始。

### 1. 写出任务句

用一句话描述用户的动作与结果：

```text
用户通过 [输入/筛选/选择]，完成 [核心动作]，得到 [可验证结果]。
```

示例：用户上传合同 Excel，执行批量匹配，得到异常摘要和可下载结果。

任务句无法写清时，先澄清业务，不要开始排版。

### 2. 选择唯一焦点

从以下三类中只选一个作为第一视觉焦点：

- **动作焦点**：创建、运行、提交、上传等操作型工具。
- **数据焦点**：查询结果、待办列表、异常明细等列表型工具。
- **结论焦点**：核心指标、风险判断、对比结果等分析型工具。

其余内容降为辅助区。不要让主按钮、指标卡和大表格同时争夺注意力。

### 3. 列出三层信息

| 层级 | 内容 | 表现 |
|---|---|---|
| Primary | 当前任务、关键结果、主操作 | 靠前、字号或主题色突出 |
| Supporting | 筛选、解释、摘要、关联信息 | 常规字号、默认表面 |
| Tertiary | 时间、来源、低频动作、口径 | 小字号、弱色或折叠 |

若同一层内容超过 5–7 项，继续分组或折叠。

### 4. 画状态流

至少明确：

```text
初始 → 执行中 → 成功
              ↘ 失败
查询 → 有结果 / 空结果
```

界面布局应随状态改变焦点：执行前突出输入，执行中突出进度，完成后突出结果和下一步。

---

## 平台与视觉基线

### 平台页面壳

`component/tool_shell.render_tool_shell` 已提供：

- 浅灰页面画布；
- 固定顶栏和返回入口；
- `max-w-screen-2xl mx-auto px-4 sm:px-6 py-4` 内容容器；
- 工具名、项目名和预览标识。

工具根节点默认使用：

```python
with ui.column().classes("w-full gap-3"):
    ...
```

复杂详情、分析或多步骤页面可提升为 `gap-4`。禁止再次添加整页 `max-w-*`、`mx-auto`、`px-6` 或重复工具壳标题。

### 桌面端工作区基线

Calabash 运行在 Calabash 桌面窗口中，工具页面是一个稳定的工作区，不是自适应营销页面。设计时优先保证控件在常见桌面宽度下可扫描、可操作，再为窄窗口回落到单列。

- 内容默认使用平台工具壳提供的宽度；不要用全屏横向铺开的装饰区，也不要再嵌套一层页面 header。
- main() 在工具壳的 Column 内调用，不拥有 NiceGUI 页面根节点。禁止 ui.left_drawer/ui.right_drawer/ui.header/ui.footer，即使 fixed=False 也不允许；菜单、顶部控制区和底部播放器通过局部 ui.row()/ui.column() 组合，不移出宿主 slot。
- 第一屏只保留当前任务、主要输入和唯一主操作；说明文字控制在一到两行。
- 表单、结果和状态区使用明确的上下顺序，避免用“左边一个控件、右边另一个控件”的自由定位制造视觉断裂。
- 常见桌面宽度下，主表单优先使用可伸缩网格；短字段可以并列，长字段和主输入独占一行。
- 使用 `min-w-0`、`flex-1` 或 `minmax(0, 1fr)` 允许长文本收缩；按钮和操作组使用 `shrink-0` 保持尺寸稳定。
- 不依赖浏览器自然高度或默认 margin 对齐；同一控制行必须显式设置 `items-end` 或 `items-center`。

推荐的桌面表单骨架：

```python
with ui.card().classes("w-full").props("flat"):
    with ui.card_section().classes("w-full p-3 sm:p-4"):
        with ui.grid().classes(
            "w-full grid-cols-1 md:grid-cols-[minmax(0,1fr)_minmax(12rem,0.7fr)_auto] gap-3 items-end"
        ):
            ui.input("名称").props("outlined dense clearable color=primary").classes("w-full min-w-0")
            ui.select(["全部", "启用"], label="类型").props("outlined dense color=primary").classes("w-full min-w-0")
            with ui.row().classes("gap-2 shrink-0 items-center"):
                ui.button("重置", on_click=reset).props("outline dense color=grey-7")
                ui.button("提交", on_click=submit).props("dense color=primary")
```

`ui.row()` 适合一组横向操作，`ui.grid()` 适合多个字段的稳定列对齐。不要通过 `ml-auto`、空白占位元素或不同的 `margin-top` 人工“推”控件到同一条基线。

### 平台视觉语言

平台卡片已经具备 8px 圆角、无阴影和浅边框。工具页应复用而非覆盖：

- 主表面：`ui.card().classes("w-full").props("flat")`
- 次表面：卡片内部使用 `bg-gray-50 rounded-lg` 的轻量区块
- 主操作强调：`app-text-primary`、`app-bg-primary-light`、`app-border-primary`
- 辅助主题强调：`app-text-secondary`、`app-bg-secondary-light`、`app-border-secondary`
- 状态色：Quasar `positive / warning / negative / info`
- 默认正文：`text-gray-700`；辅助文字：`text-gray-500`

不要给所有卡片加 shadow，也不要用 `bordered` 反复加重平台已有边框。

### 主题角色，而非“一个颜色走到底”

Calabash 使用一套有职责分工的主题系统。不要默认 `primary` 一定是蓝色；不同平台主题中，它可能接近深灰。先看变量在实际页面中的效果，再选择角色。

| 色彩角色 | 用途 | 推荐令牌 | 禁止用途 |
|---|---|---|---|
| Primary | 唯一主操作、任务标题、关键控制 | `--app-primary` / `--app-primary-light` | 大面积铺底、每张卡描边 |
| Secondary | 当前选择、配置关系、条件与规则 | `--app-secondary` / `--app-secondary-light` | 与 Primary 争夺主按钮 |
| Semantic | 成功、提醒、错误、处理中 | `positive / warning / negative / info` | 装饰角色卡、区分类目 |
| Neutral | 画布、正文、普通表面和分隔 | `gray-50` 至 `gray-900` | 承担唯一选中态 |

推荐近似比例：75% 中性色、18% 浅主题表面、7% 实色主题与状态。比例用于视觉收敛，不要求机械计算。

### 一套主题的组合规则

一个页面最多使用两种非语义主题角色：Primary 与 Secondary。二者必须分工，不按组件轮流上色。

```text
Primary   = “我要做什么”    主按钮、任务标题、关键输入焦点
Secondary = “我正在看什么” 选中项、关系配置、规则、条件标签
Semantic  = “结果怎么样”    已启用、成功、警告、失败
```

- 页面只有 Primary 时：用于简单查询、录入和单动作工具。
- 引入 Secondary 时：必须存在持续选择、配置关系、流程条件或左右联动。
- `positive` 只表示“已启用/已完成”，不可拿绿色装饰普通卡片。
- 选中态不能只有灰底或只有文字变色；至少同时使用底色、边线、字重中的两项。
- 若 Primary 在实际主题中接近黑灰，选中态与关系型信息优先使用 Secondary，避免整页发灰。

### 浅色主题表面的生成

优先使用平台 light 令牌。需要更细层级时，使用局部命名空间和 `color-mix`，不得写死十六进制色值：

```python
ui.add_css("""
    .contract-tool .selected-surface {
        color: var(--app-secondary);
        background: var(--app-secondary-light);
        border-color: color-mix(in srgb, var(--app-secondary) 35%, transparent);
        border-left: 3px solid var(--app-secondary);
    }
    .contract-tool .related-chip {
        color: var(--app-secondary);
        background: color-mix(in srgb, var(--app-secondary) 12%, white);
    }
""")
```

同一区域的浅底、边框和文字应来自同一主题变量，形成色相一致、明度不同的一套颜色，而不是拼接多个现成状态色。

---

## 页面叙事与构图

页面通常由四个角色组成，按需组合，不必全部出现：

```text
Context  当前对象、范围或结果摘要
Control  输入、筛选、动作
Focus    主数据、主表单或主结论
Support  说明、关联、历史、口径
```

### 1. 查询与列表：结果优先

```text
上下文行：结果数 / 当前范围                         新增或刷新
筛选表面：2–3 个高频条件                  重置  查询
主数据表：工具栏 / 表格 / 分页
```

规则：

- 数据表是焦点，筛选区不应比结果区更抢眼。
- 首次进入可直接加载时，不显示空洞的“请查询”占位。
- 复杂筛选默认只展示高频项，其余放入“更多筛选”。
- 结果摘要写“128 条 · 3 个条件 · 更新于 10:32”，不要再加一排统计卡。

### 2. 表单与录入：分段完成

```text
上下文行：当前对象 / 一句话说明 / 状态
主表单：基础信息 ─ 业务配置 ─ 影响范围
辅助区：预览、风险或提交影响
动作栏：取消 / 保存草稿                         提交
```

规则：

- 按用户决策顺序分组，不照搬数据库字段顺序。
- 8 个以上字段分为 2–4 个语义区；短字段使用响应式两列。
- 长表单使用页底动作栏；关键提交按钮在滚动后仍容易找到。
- 危险或不可逆影响在提交前展示，不藏在成功通知里。

### 3. 详情与审阅：结论先于字段

```text
身份摘要：名称 / 编号 / 状态                         主操作
关键信息带：3–5 个最重要字段或判断
主体：分组详情 / 明细 / 时间线
辅助：关联对象、来源、备注
```

规则：

- 先回答“这是什么、现在怎样、需要我做什么”。
- 不把详情做成一列几十行键值对。
- 审批、核对、差异场景优先展示差异和风险，再展示完整原始数据。

### 4. 操作型工具：状态接力

```text
输入表面：文件 / 参数 / 范围                         运行
状态带：校验结果 / 进度 / 当前步骤
结果区：摘要 + 异常 + 下载或后续动作
```

规则：

- 初始状态突出输入；完成后降低输入权重并突出结果。
- 长任务显示当前步骤，禁用重复运行。
- 成功结果至少包含数量、异常数和下一步；不要只弹 toast。
- 结果下载与重新运行分主次，不能出现两个同权实心按钮。
- 用户文件工具优先复用 `ToolFileInput`、`ToolResults` 和 `ToolJobStatus`，不要再画一套路径输入、结果下载或假进度。文件/批量模板和 API 见 [file-workflow.md](file-workflow.md)。

### 5. 统计与分析：问题驱动

```text
范围与口径
核心结论 / 2–4 个指标
主图表或对比表
明细与口径说明
```

规则：

- 先定义分析问题，再选择图表。
- 单页通常 1 个主图和最多 2 个辅助图；没有趋势或比较问题时用表格。
- 指标卡只展示能改变判断的指标，不展示容易从表格数出的数字。

### 6. 双栏工作区：选择影响预览

当左侧选择会持续改变右侧内容时，使用双栏：

```python
with ui.grid().classes("w-full grid-cols-1 lg:grid-cols-[minmax(18rem,0.8fr)_minmax(0,2fr)] gap-4"):
    with ui.card().classes("w-full").props("flat"):
        ...  # 选择、配置、目录
    with ui.card().classes("w-full min-w-0").props("flat"):
        ...  # 预览、详情、结果
```

不要用双栏展示两个互不相关的任务。移动端必须自然回落为单列。

---

## 视觉语法

### 字体层级

| 角色 | 推荐类 | 使用原则 |
|---|---|---|
| 页面任务标题 | `text-lg font-semibold app-text-primary` | 页面最多一个 |
| 对象或关键结论 | `text-base font-semibold text-gray-900` | 摘要区焦点 |
| 分区标题 | `text-sm font-semibold text-gray-800` | 有真实分组时才用 |
| 正文 | `text-sm text-gray-700` | 默认业务信息 |
| 辅助信息 | `text-xs text-gray-500` | 时间、来源、口径 |
| 核心数字 | `text-2xl font-semibold text-gray-900` | 仅指标或结果摘要 |

- 不使用 `text-3xl` 及以上标题。
- 一个局部区域最多一个最高字重；不要把标签和值全部加粗。
- 副标题最多一行，必须补充范围、状态或用途，不重复标题。
- 长标识不静默截断；允许换行、复制或 tooltip。

### 间距节奏

使用 2 / 3 / 4 三级节奏：

| 关系 | 推荐间距 |
|---|---|
| 同组紧密元素 | `gap-1` / `gap-2` |
| 同一区块元素 | `gap-3` |
| 不同语义区块 | `gap-4` 或分隔线 |

Card 内容默认 `py-3 px-3 sm:px-4`。表格容器可去掉多余内边距。组间距必须明显大于组内间距。

### 表面层级

单页通常只需要三层：

1. **画布**：平台浅灰背景，不自行绘制。
2. **主表面**：表单、表格、结果等核心 card。
3. **内嵌表面**：摘要、提示、关联信息，使用 `bg-gray-50 rounded-lg px-3 py-2`。

禁止 card 内再套同样的 card。需要分组时使用 `ui.card_section()`、浅分隔线或内嵌表面。

### 视觉锚点

每个页面至少建立一个、最多两个视觉锚点：

- 主题色主按钮；
- 左侧主题色细边的当前状态块；
- 核心结果数字；
- 主数据表的对象列。

不要同时使用大色块、彩色指标、多个实心按钮和高饱和 badge。

### 可交互表面的四态

列表项、目录项、流程类型等可选择表面必须至少定义 default、hover、selected、disabled 四态：

| 状态 | 表现 |
|---|---|
| Default | 白色或极浅中性表面，边框透明 |
| Hover | 浅 Secondary 表面，不改变布局尺寸 |
| Selected | Secondary 浅底 + 左侧 3–4px 实色边 + 强化标题 |
| Disabled | 降低透明度并保留状态文字，不只变灰 |

避免选中项仍像普通灰卡。选中态是导航信息，不是装饰，必须能在一秒内定位。

### 图标

图标用于导航、状态识别和紧凑操作，不用于“让按钮更好看”。

- 普通按钮默认纯文字。
- 表格窄操作列可使用图标按钮，必须配 tooltip。
- 空状态可使用一个低对比图标。
- 页面标题、指标卡和每个输入框前不要机械加图标。

---

## 核心组件

### 任务页头

平台已有工具名时，内页头表达当前任务或对象：

```python
with ui.row().classes("w-full justify-between items-start gap-3 flex-wrap"):
    with ui.column().classes("gap-0.5 min-w-0"):
        ui.label("待处理合同").classes("text-lg font-semibold app-text-primary")
        ui.label("128 条 · 更新于 10:32").classes("text-xs text-gray-500")
    with ui.row().classes("gap-2 shrink-0"):
        ui.button("导出", on_click=export).props("outline dense color=grey-7")
        ui.button("新增合同", on_click=create).props("dense color=primary")
```

无对象、范围或页面级动作时，省略内页头。

### 筛选表面

```python
with ui.card().classes("w-full").props("flat"):
    with ui.card_section().classes("w-full py-3 px-3 sm:px-4"):
        with ui.row().classes("w-full gap-2 items-center flex-wrap"):
            ui.input(placeholder="合同号或名称").props(
                "outlined dense clearable color=primary"
            ).classes("min-w-[14rem] flex-1")
            # enums_select(...).classes("min-w-[10rem]")
            with ui.row().classes("gap-2 ml-auto shrink-0"):
                ui.button("重置", on_click=reset).props("flat dense color=grey-7")
                ui.button("查询", on_click=search).props("dense color=primary")
```

- 1–3 个高频条件保持单行；4 个以上折叠低频项。
- 简单字段使用 placeholder，复杂或必填字段使用 label。
- 生效条件数量放在结果摘要，不堆彩色 chips。

### 控件对齐与尺寸

截图中常见的错位通常来自输入框带 label、无 label 控件和按钮混在一个 `items-center` 行中。生成工具时必须先决定每一行的对齐基线，再放入控件。

- 同一行的输入、选择器和按钮统一使用 `outlined dense`；不要混用 `dense` 与非 `dense`，也不要混用 `filled`、`outlined`。
- 带浮动 label 的控件与按钮放在 `items-end` 的网格行中；纯 placeholder 输入也按同一网格列处理，不用额外 margin 修正。
- 操作按钮放在独立的 `shrink-0` 操作组中，按钮组与字段底部对齐；不要让按钮参与字段的 `flex-1` 分配。
- 每列必须有明确的宽度策略：可伸缩字段用 `minmax(0, 1fr)`/`flex-1`，短枚举用 `minmax(10rem, 0.7fr)`，操作组用 `auto`。
- 同一控制行的字段不能依赖内容自然宽度；至少给窄屏回落规则：`grid-cols-1 md:grid-cols-[...]` 或 `flex-wrap`。
- 输入、选择器、按钮之间使用统一 `gap-2` 或 `gap-3`，不要单独写负 margin、`mt-*`、`translate-y-*` 来修齐。
- 多行说明、错误文本和帮助文本必须占据自己的布局行，不能插入字段行后把右侧按钮顶下去。

对齐验收可以用下面的结构判断：

```python
with ui.grid().classes("w-full grid-cols-1 md:grid-cols-[minmax(0,1fr)_auto] gap-3 items-end"):
    ui.input(label="关键词").props("outlined dense").classes("w-full min-w-0")
    ui.button("查询").props("dense color=primary").classes("shrink-0")
```

禁止以下写法：在一个 `ui.row()` 中直接混放不同高度控件；用 `justify-between` 把字段和按钮推到两端；给单个控件追加 `mt-*`、`mb-*` 或 `.style("margin...")` 解决局部错位；让按钮自动拉伸填满字段列。

### 数据表

```python
table = (
    ui.table(columns=columns, rows=rows, row_key="id")
    .props("flat dense separator=horizontal color=primary")
    .classes("w-full")
)
```

- 第一列优先放可识别对象，最后一列放操作。
- 名称、描述左对齐；数字右对齐；状态和短枚举可居中。
- 列超过 8 个时隐藏低频列或提供详情，不依赖横向滚动展示全部字段。
- 仅状态、风险、版本使用 badge；普通枚举和文本使用纯文字。
- 表格上方工具栏只放真实功能：结果数、排序、列显示、导出。
- 分页同时显示范围与总数，例如“第 21–40 条，共 128 条”。
- 多选后才出现批量操作条，不长期占据页面。

### 表单

- 输入统一 `outlined dense color=primary`，禁止 `filled`。
- 必填、格式和跨字段错误靠近字段显示；提交失败同时给概要通知。
- 单行短字段使用两列网格，描述、备注、JSON 等长字段独占一行。
- 对话框适合不超过 6 个字段的短任务；复杂编辑使用完整页面。
- 表单底部保持“取消/重置”在左或弱化，“保存/提交”在右且唯一实心。

### 摘要带

当 3–5 个关键值需要快速扫描时，使用一条轻量摘要带，而不是多张卡：

```python
with ui.element("div").classes(
    "w-full grid grid-cols-2 lg:grid-cols-4 gap-px bg-gray-200 rounded-lg overflow-hidden"
):
    for label, value in summary:
        with ui.column().classes("bg-white px-3 py-2 gap-0"):
            ui.label(label).classes("text-xs text-gray-500")
            ui.label(value).classes("text-sm font-semibold text-gray-900")
```

只有核心数字需要独立强调时才使用指标卡。指标最多 4 个，结构和高度保持一致。

### 配置组带

人员组、角色组、权限组等“多个同类配置共同影响下方内容”的场景，使用连续配置带，而不是若干悬浮卡片：

```python
with ui.element("div").classes(
    "role-band w-full grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-px rounded-lg overflow-hidden"
):
    for group in groups:
        with ui.column().classes("role-tile px-3 py-3 gap-2 min-w-0"):
            ...
```

局部主题样式：

```css
.approval-tool .role-band {
    background: color-mix(in srgb, var(--app-secondary) 20%, transparent);
}
.approval-tool .role-tile {
    background: color-mix(in srgb, var(--app-secondary) 7%, white);
    border-top: 3px solid var(--app-secondary);
}
.approval-tool .member-chip {
    color: var(--app-secondary);
    background: color-mix(in srgb, var(--app-secondary) 13%, white);
}
```

- 整组只使用一个主题色，通过明度区分层级；不要给每个角色分配一种颜色。
- 成员适合轻量 chip；职责说明保持中性辅助文字。
- 编辑仍是文字按钮，不给每张配置项加图标。
- 当配置组超过 6 个时，优先换行、分页或折叠，不无限压缩单元格。

### 条件与规则

流程条件、匹配规则、跳过逻辑属于关系信息，默认使用 Secondary 浅色标签或左边线说明块：

- 条件标签表达“何时进入”，不使用 `warning`，除非条件本身存在风险。
- 规则说明与条件标签使用同一色系，使用户建立稳定关联。
- 标签只包裹短条件；长规则换成说明块，避免整行大胶囊。
- 颜色之外保留“进入条件”“规则说明”等文字标签。

### 提示与风险

- 中性说明：浅灰内嵌表面，不使用 badge。
- 操作提示：`ui.banner()` 或左侧主题色细边块，控制在 1–3 行。
- 风险警告：`warning`；阻断错误：`negative`；不要用红色表达普通注意事项。
- 可关闭提示只用于临时信息；关键业务限制必须持续可见。

### 空状态

空状态应解释原因并给一个下一步：

```python
with ui.column().classes("w-full items-center py-10 gap-1.5"):
    ui.icon("inbox").classes("text-4xl text-gray-300")
    ui.label("暂无匹配结果").classes("text-sm font-medium text-gray-700")
    ui.label("调整筛选条件后重试").classes("text-xs text-gray-500")
    ui.button("清除筛选", on_click=reset).props("flat dense color=primary")
```

不要同时提供多个空状态按钮。

---

## 状态与反馈

### 状态必须改变界面

Toast 只做即时反馈，不能代替页面状态。

| 状态 | 页面表现 |
|---|---|
| 初始 | 说明输入要求和主动作 |
| 加载 | 禁用重复动作，显示当前步骤或骨架 |
| 空 | 解释没有结果的原因和下一步 |
| 成功 | 展示结果摘要、异常和可继续动作 |
| 失败 | 保留输入，说明原因，并提供重试或修正路径 |

### 文案规则

- 成功：“已回填 128 行，3 行需人工确认”。
- 失败：“处理失败：未找到‘合同号’列，请使用模板文件”。
- 进行中：“正在查询合同 42/128”。
- 禁止只写“成功”“失败”“处理中”。

### 长任务

- 使用 `run.io_bound` 或异步任务，避免阻塞事件循环。
- 运行期间禁用触发按钮并防止重复提交。
- 超过数秒的任务显示阶段或进度；完成后保留摘要，不立即清空。
- 可恢复错误保留用户输入；不可恢复错误说明如何修复。

### 危险操作

- 删除、覆盖、批量更新、正式发布必须确认影响范围。
- 确认按钮使用明确动词，如“删除 12 条记录”，不用“确定”。
- 危险操作不与主操作并列成同等权重；放入次级菜单或独立确认流程。

---

## 响应式与可访问性

- 所有操作行使用 `flex-wrap`；主要动作在窄屏仍可见。
- 网格从 `grid-cols-1` 起步，再使用 `sm:`、`lg:` 扩展。
- 双栏工作区在 `lg` 以下回落为单列。
- 触控目标保持可点击，不用极小文字模拟按钮。
- 状态不只依赖颜色，同时显示文字、数值或符号。
- 图标按钮必须有 tooltip；输入必须有 label、placeholder 或邻近说明。
- 正文对比度不低于 `text-gray-500`；`text-gray-300/400` 仅用于图标或极弱占位。
- 键盘操作顺序遵循视觉顺序；对话框打开后主任务清晰，关闭路径明确。
- 长文本允许换行或查看详情，不用固定窄宽度强制截断。

---

## 实现约束

### 样式优先级

```text
.props() → .classes() → 局部 scoped CSS → .style()
```

- 优先使用组件 props 和平台/Tailwind 类。
- scoped CSS 仅解决平台类无法表达的局部结构，例如流程连线或固定表格列。
- CSS 必须限定在工具命名空间内，不能全局覆盖 `.q-card`、`.q-btn` 或平台壳。
- 避免逐元素 `.style()`、原始十六进制颜色和 `!important`。
- 不重新定义平台已有圆角、阴影、主题色和页面宽度。
- 使用 `color-mix` 时，混合源必须来自 `--app-primary` 或 `--app-secondary`，并提供 white/transparent 作为明度或透明度基底。
- 一个工具只创建一个根命名空间，例如 `.approval-tool`；所有自定义 CSS 均从该命名空间开始。

### 组件与数据

- `main` 保持顶层函数，不装饰、不动态生成。
- SQLite 和本地文件延迟访问，禁止模块顶层打开可能失败的外部资源。
- 工具内固定选项使用普通 NiceGUI 控件；桌面端不提供托管枚举 API。
- 大数据集分页；局部状态优先用 `@ui.refreshable` 更新，不重建整页。
- 普通按钮默认文字按钮且 `dense`；表格行多操作才使用图标按钮。

### 推荐根结构

```python
def main() -> None:
    ui.page_title("工具标题")
    with ui.column().classes("w-full gap-3"):
        render_context()
        render_controls()
        render_focus()
        render_support()
```

按需省略区块。不要为了对齐模板创建空区块或重复标题。

---

## 验收标准

生成或修改 UI 后，按以下顺序检查。任一红线命中都应返工。

### 任务与结构

- [ ] 第一屏能说清对象、状态和下一步。
- [ ] 已选择唯一视觉焦点，其他区域没有争抢注意力。
- [ ] 页面骨架匹配任务类型，不是机械的“标题 + 卡片 + 表格”。
- [ ] 主操作唯一，位置稳定，危险操作已降级和确认。
- [ ] 详情先给结论，表单按决策顺序，结果区包含可验证摘要。

### 视觉与密度

- [ ] 使用平台壳、主题色、轻边框和现有圆角。
- [ ] 表面不超过三层，没有 card 套 card 或卡片墙。
- [ ] 组间距大于组内间距，页面紧凑但不拥挤。
- [ ] 主题色只用于焦点，状态色只表达业务语义。
- [ ] Primary、Secondary、Semantic 的职责明确，没有用状态色装饰类别。
- [ ] 若 Primary 偏中性，当前选择与关系信息已使用 Secondary 建立色彩层级。
- [ ] 选中态同时具备底色、边线、字重中的至少两项，并覆盖 hover/disabled。
- [ ] 同一配置带内色相一致，只通过明度区分表面、边框和标签。
- [ ] 没有渐变、发光、大阴影、大图标、徽章墙和彩虹色。
- [ ] 标题、正文、辅助文字层级稳定，没有全页加粗。

### 数据与交互

- [ ] 覆盖初始、加载、空、成功、失败状态。
- [ ] 长任务不阻塞，运行中禁止重复提交，完成后保留结果。
- [ ] 错误说明原因和下一步，不只依赖 toast。
- [ ] 表格列、对齐、分页和操作符合扫描习惯。
- [ ] 本地数据访问、共享文件组件和刷新方式符合平台规范。

### 响应式与实现

- [ ] 窄屏下筛选、按钮、网格和双栏可以自然回落。
- [ ] 常见桌面宽度下，控件列、按钮组和结果区有稳定基线，没有依赖 margin 的局部修正。
- [ ] 同一行字段统一控件密度，带 label 的字段、无 label 字段和操作按钮没有上下错位。
- [ ] 关键状态不只依赖颜色；图标按钮有 tooltip。
- [ ] 未重复页面容器、未全局覆盖平台组件样式。
- [ ] `main` 为顶层函数，数据源延迟访问。
- [ ] 只执行用户授权的生命周期动作；preview 不等于 publish。

### 红线

以下任一项直接判为不合格：

- 同屏出现两个以上同权实心主按钮；
- 页面由大量同样白卡或彩色指标卡组成；
- 为装饰给标题、按钮、输入框逐个添加图标；
- 只有成功界面，没有加载、空和失败处理；
- 表格展示 9 列以上仍不做信息降级；
- 使用大面积主题色、渐变、玻璃拟态或高饱和背景；
- 用灰色浅底作为唯一选中反馈，导致当前项无法快速定位；
- 为区分财务、法务、GM 等普通类别而逐项使用不同状态色；
- 重复平台顶栏、整页宽度或外边距；
- 用静态 `disable` prop 后再依赖运行时 `enable()`；
- 在模块顶层访问数据库或执行外部请求。

**执行口诀**：先任务，后焦点；先层级，后组件；先状态，后装饰；最后做响应式和视觉收敛。
