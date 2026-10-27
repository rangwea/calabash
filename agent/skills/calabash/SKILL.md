---
name: calabash
description: 创建、修改、校验和调试本地单文件 Calabash 工具。工具文件直接保存在 ~/.calabash/tools；Calabash 桌面端只负责索引、搜索和运行这些本地工具。
---

# Calabash

## 执行入口

以本次加载的 skill 目录为 `CALABASH_SKILL_ROOT`，使用绝对路径且保持用户工作目录。
不要假定工作区有 `.agents/skills/calabash`。CLI 仅依赖标准库，要求 Python 3.10+；工具运行环境为 Python 3.13+。先确认 `python3 --version`；系统版本过旧时使用项目的 `uv run python3` 或已安装的合适 Python 3，不修改系统 Python。正式工具命令直接操作 `~/.calabash/tools`，只有 `preview` 和 `prelog` 需要正在运行的本地 Calabash 服务。

```bash
python3 "$CALABASH_SKILL_ROOT/scripts/tool-cli.py" --json <command>
python3 "$CALABASH_SKILL_ROOT/scripts/validate-tool.py" <file>
```

命令：`list projects get create preview prelog publish status delete toollog`。
本地桌面版不维护平台变量、远程数据源或管理后台，不提供 `variables`、`databases` 命令。工具列表提供用户确认的本地 ZIP 导入导出；Agent 创建和编辑工具仍直接操作本地文件，不依赖导入流程。`toollog` 读取 `~/.calabash/logs/tools`。

## Agent loop

维护最小任务状态：目标 `project/name`、本地文件、已授权动作、当前阶段及最近错误。
只在目标真正不明时询问；`project` 默认当前目录名，`name` 使用英文 snake_case。

1. **定位**：已有本地文件直接修改；修改目标缺失时才 `get project name --output <file>`。
   新建直接写 `~/.calabash/tools/<project>/<name>.py` 或用本地 `create`，不查询远端、不调用导入接口。
   同名冲突且覆盖意图不明时澄清；明确修改已有目标无需再确认。
2. **编辑 → 校验**：按下表加载所需参考，运行静态校验；根据具体错误修复，再校验。
   内置聊天 Agent 使用组件前调用 `read_component_api` 查询真实构造参数、方法和属性，不猜测 `mount()` 等生命周期接口。该查询只检查受信任的内置组件，不导入用户工具；外部 Agent 没有此查询工具时读取 `references/file-workflow.md` 和对应源码，不把查询工具当作 Python API。
   创建工具先读 [runtime.md](references/runtime.md) 与共享依赖清单，优先使用 App 内置库，不要求用户安装系统工具；规划中的可选能力不能视为已安装。使用可选插件须在模块 docstring 声明 `requires: media.ffmpeg>=9.0.2` 等能力 ID/最低版本，内置库工具留空；由宿主运行前检查并引导本地 ZIP 导入，安装后由用户手动重试。
   校验通过且只要求生成/修改时交付，不强制预览。
   新建或调整 UI 时，必须遵守 `references/design.md` 的桌面端工作区、控件对齐和响应式规则；尤其检查同一控制行的基线、控件密度、可伸缩列和固定操作组，禁止用局部 margin 修齐。
3. **预览 → 观察 → 修复**：要求预览、验证或报告运行错误时，加载
   [lifecycle.md](references/lifecycle.md) 执行闭环。每次修改后先校验再更新预览。
   宿主发起的受限错误修复只授权编辑所引用工具：先读最新代码和 revision，保留凭据占位符，不读取业务附件或完整日志。修复后只保存，不执行或自动打开预览；明确由用户手动重试。预览修复针对当前草稿，不隐式覆盖正式工具。
   耗时单任务用 `ToolTask`，批量用 `ToolJobs`，统一交给 `ToolJobStatus(..., inputs=(inputs,), controls=(start, parameter))` 运行。运行前捕获参数和文件快照，阻塞处理放入 `run.io_bound`，不在 worker 更新 UI；取消只停止后续调度，当前文件结束前不得解锁或显示已取消。宿主负责离开提醒和安全退出，不自行强杀线程或增加 beforeunload 脚本。
4. **正式动作**：发布、保存、部署、上线在桌面版都表示把单文件写入本地工具目录，统一使用 `publish`；删除使用 `delete`。
   执行前加载生命周期参考，沿用会话中针对目标的授权。预览不授权发布或业务写入。
5. **结束**：达到请求的验证阶段即交付；无新证据时不重放相同操作。
   缺配置、权限或外部依赖时报告所需输入。正式写入结果不明时先只读核实，不能盲目重试。

## 按需加载

已读且未变的参考不重复读取；只改逻辑不加载视觉文档，不重套模板。

| 当前工作 | 读取 |
|---|---|
| 所有代码生成/修改 | [quality-gate.md](references/quality-gate.md) |
| 工具依赖、文件/图片/PDF 能力 | [runtime.md](references/runtime.md)、[runtime-libraries.json](references/runtime-libraries.json)；库的导入名、用途及未提供的能力。 |
| 新建或调整 UI | [design.md](references/design.md)；需要选择构图时才读 [design-scenes.md](references/design-scenes.md) 对应章节。桌面端工具必须额外检查控件基线、统一 `dense` 高度、`grid` 列宽策略和窄屏回落。 |
| 新建工具模板 | 简单表单：[simple-tool.py](references/simple-tool.py)；筛选分页详情：[query-tool.py](references/query-tool.py)；处理用户文件或批量导出：[file-tool.py](references/file-tool.py) |
| 用户文件输入、导出、批量处理 | 先读 [file-workflow.md](references/file-workflow.md)：追加去重、移除/清空、状态与执行冻结，以及结果历史、取消和失败重试的真实 API；不是每个工具都需要这些组件。 |
| SQLite 或本地文件访问 | [datasources.md](references/datasources.md) |
| 工具内固定参数 / 选项 | [variables.md](references/variables.md) / [uix.md](references/uix.md) |
| 预览调试、发布、删除 | [lifecycle.md](references/lifecycle.md) |
| 自定义复杂布局/组件 | [design-details.md](references/design-details.md) 对应章节 |
| 技能行为评测 | [forward-tests.md](references/forward-tests.md) |

仅遇到对应 NiceGUI API 问题时加载：
[入口](references/nicegui/01-foundations.md)、[输入事件](references/nicegui/02-inputs-events-validation.md)、
[布局](references/nicegui/03-layout-styling-responsive.md)、[状态刷新](references/nicegui/04-state-binding-refresh.md)、
[表格图表](references/nicegui/05-data-display-charts.md)、[异步隔离](references/nicegui/06-async-tasks-multi-user.md)、
[弹窗文件](references/nicegui/07-feedback-dialogs-files.md)、[互操作测试](references/nicegui/08-security-testing-interop.md)。

## 交付

对用户称 Calabash。只报告已完成的阶段：文件、静态检查、预览链接、页面/交互验证、正式发布。
静态检查不执行源码；预览上传成功不证明页面正常。给出结果、验证和实际阻塞点，不粘贴完整源码或日志。
