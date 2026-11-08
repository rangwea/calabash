# AGENTS.md

## 产品边界

本仓库是 Calabash 本地桌面应用：Tauri v2 壳、Python 3.13+ 后端、Vue 3 + TypeScript + Element Plus UI、SQLite。
工具直接保存在 `~/.calabash/tools`，由 AI Agent 创建和编辑。
不提供登录、管理后台、远程数据源、平台变量管理、MySQL/MongoDB、远程发布或 Docker 部署。
本机回环 HTTP 是桌面壳的内部通信实现，不是面向远程用户的服务。
工具列表支持本地 ZIP 工具导入导出，不支持 GitHub 地址导入；工具 ZIP 与能力插件 ZIP 为独立格式。导入需用户确认，不执行代码或自动安装依赖，同名覆盖需明确授权且不得覆盖运行中的工具。
应用尚未发布，不维护旧版本配置、数据库迁移或协议别名；初始化直接创建当前完整结构。跨平台适配、当前模型协议、安全检查和正常容错不属于历史兼容，不能因此删除。

## 常用命令

```bash
uv sync
uv run python3 main.py
npm install
npm run desktop:dev
npm run desktop:build
uvx --offline ruff check
.venv/bin/python3 -m unittest discover -s tests
npm run check:frontend
node --test tests/frontend_probe.test.mjs tests/context_menu.test.mjs tests/chat_composer.test.mjs
cargo test --manifest-path src-tauri/Cargo.toml
```

桌面构建使用 `scripts/build_desktop_sidecar.py` 将 Python 后端和内置依赖打包；最终用户无需安装 Python、uv 或 Node。`scripts/build_frontend_runtime.py` 校验并打包固定的官方 Node LTS 和编译依赖；作为 Tauri 资源分发，不塞入每次启动解压的 Python 单文件。
Python 依赖以 `pyproject.toml` 和 `uv.lock` 为准，不维护第二份 requirements 文件，不读取 `.env`。
名称与应用版本以根 `package.json` 的 productName / version 为准，Python 通过 `core.app_info` 读取，Tauri 版本直接引用该文件。更新版本时对齐 Python/Cargo 清单，一致性测试会检查。
源码启动使用 `127.0.0.1` 随机可用端口，以启动日志为准，不假定端口 8000。

## 目录

| 目录 | 职责 |
| --- | --- |
| `main.py` | 源码开发入口 |
| `backend/desktop_server.py` | 打包后端入口与运行库自检 |
| `src-tauri/` | 原生窗口、文件选择、权限与安全退出 |
| `desktop-ui/` | Vue 宿主、启动页、样式和桌面桥接 |
| `core/` | SQLite、日志、路径、样式、国际化和运行库清单 |
| `models/` | SQLModel 模型 |
| `service/` | 按 `chat/`、`tools/`、`files/`、`capabilities/` 划分的业务服务 |
| `component/` | 浏览器诊断脚本、右键策略与共享设计资源 |
| `api/` | 本地内部 API 路由 |
| `agent/skills/calabash/` | App 内置 Agent Skill 的唯一正式源，随桌面后端打包 |
| `scripts/` | 桌面构建、图标生成和 FFmpeg 插件打包 |
| `tests/` | 回归测试与合成验收样例 |

`.agents/skills/calabash` 是指向正式 Skill 的符号链接，修改前确认链接，不创建分叉副本。
仓库 `tools/`、`logs/`、`build/`、`dist/` 是忽略的本地数据或构建产物，不当作废弃源码删除。

## 本地数据

路径以 `core/local_paths.py` 及相应服务实现为准：

- 主索引数据库：`~/.calabash/calabash.db`。
- 工具文件：`~/.calabash/tools`。
- 日志：`~/.calabash/logs`；工具日志在其 `runs/<project>/<tool>/<run_id>/` 下。
- 本地能力插件：`~/.calabash/plugins`，通过用户确认导入签名 ZIP，不添加在线下载服务。
- 用户交付文件使用 `CalabashResults` / `tool_outputs`，不要覆盖源文件。

不要读取、提交或删除用户模型密钥、业务文件、本地数据库或插件签名私钥。
不要在安装目录或当前工作目录写运行数据；安装目录可能只读。

## 数据与分层

页面和组件调用服务层，服务层访问 SQLite/文件系统。主数据库通过
`DatabaseManager.create_tables()` 创建 SQLModel 表，不使用 MySQL 初始化 SQL。
其他专用存储由对应服务维护，不直接改其内部表。

```python
from core.database import db_manager
from sqlmodel import select

with db_manager.session_scope() as session:
    rows = session.exec(select(Model)).all()
```

`session_scope()` 自动 commit/rollback。新增模型须确认导入注册，并补建表和行为测试。

## UI 和错误处理

- 使用 Vue Composition API、TypeScript 与 Element Plus，样式通过语义类组织，不恢复服务端 UI 组件。
- 工具 UI 从版本化预设包选择，优先本次 @ 指定，其次工具已有快照，最后全局默认。主题元数据与 CSS 随工具源码导出，修改默认不影响已有工具。App 延续 Fluent 2 浅色办公设计；共享变量在 `component/assets/fluent_tokens.css`。工具使用独立来源的 iframe 与 scoped 样式，不覆盖宿主。
- HTTP API 在 `api/`，页面不访问数据库或文件系统。生成任务由后端持有，SSE 可续接，切换页面不取消生成。
- 工具页由独立进程惰性启动；正式版本使用构建产物，预览使用内置 Node/Vite。预览后台执行与保存相同的严格类型检查及生产构建，状态和诊断绑定源码 revision；保存复用该版本检查通过的产物，源码变化后必须重新检查。Agent 使用 check_tool_build 获取编译诊断，构建通过不等于业务验收通过。原生文件权限只授予宿主的精确回环 origin，不授予工具来源。
- 错误通过 FastAPI HTTPException 与 `core.logger.get_logger()` 记录，浏览器使用 Element Plus 反馈；不返回内部堆栈和凭据。
- 面向不会编码的办公用户：界面不展示 HTTP 状态码、源码版本、堆栈、文件行号或编译错误明细，仅说明影响和下一步操作。构建诊断按工具/对话/版本保存在本机独立诊断目录，不混入源码或导出 ZIP；Agent 用 read_build_diagnostics 查询当前版本。
- 用户看到友好错误，完整异常写日志；不要把文件正文、密钥或完整日志自动发送给 Agent。
- 文案复用 `core/i18n.py`，同步英文资源；图标按钮有 tooltip，布局不能产生无意的横向滚动。

## 工具和执行

工具目录包含 `tool.json`、`frontend/App.vue` 与 `backend/main.py`；后端定义 `setup(app, sdk)` 注册接口，导入时无业务副作用，不自行启动服务。仅支持当前目录格式，不提供旧单文件工具识别、转换或兼容执行。
聊天使用 `service/chat/agent_runtime.py` 的 LangChain/LangGraph 单 Agent；阶段与有界交接资料由 task_workflow 管理，角色工具集合隔离源代码写权限，不启用多 Agent 调度。模型适配在 `agent_model.py`，目录工具桥接在 `bundle_agent_tools.py`。
每个工具只保留一份真实工作草稿，位于 `~/.calabash/drafts/<project>/<tool>/`，正式工具在 tools 下独立保存。Agent 通过受限 write_tool_file/read_tool_file/patch_tool_file 操作相同目录，不存在虚拟文件、stage/deliver 或 Agent 管理的 revision 参数。源码不存入检查点文件状态；中断续接直接使用原目录。宿主持久化读取指纹、按工具持有写租约，并绑定构建产物源码指纹。预览直接引用工作目录，运行目录只放宿主启动文件、缓存和不可编辑的后端执行快照，避免运行中的任务混入新代码；后端修改后仍手动刷新。不启用 Shell、子 Agent 或外部 tracing。
Agent 检查点位于 `~/.calabash/agent/checkpoints.sqlite`，操作回执位于同目录 `operations.sqlite`；使用各自服务/检查点公开 API，不直接修改内部表。
API 密钥不得写入图状态、检查点配置或日志；模型对象中仅作为私有连接信息传递。
新建 JSON 业务接口优先声明 Python Pydantic 请求/响应模型和 operation_id，前端通过 @calabash/api 使用静态生成的类型与调用方法。生成只解析源码，不导入执行工具，使用 read_api_contract 查询当前版本。契约不支持的动态类型显式报错，具体规则在内置 Skill 的 api-contract.md。接口诊断绑定当前运行，记录操作、请求标识与安全的字段/调用位置，不记录请求正文或查询值。
新增文件工具优先使用已有文件输入、结果输出和 `CalabashFiles`、`CalabashResults`、`CalabashJobStatus` 和 `ToolSDK` / `ToolJobs` API。
取消采用安全停止：当前文件处理完成，再停止后续任务，不强行中断写文件。
错误交给 Agent 修复须用户确认；修复后由用户手动重试。
活动修复先读当前代码，再通过 `read_tool_logs` 查询真实异常和调用栈。用户确认授权当前工具日志查询，过滤凭据，支持有界分页与字面关键词搜索。日志绑定批准时的源码版本和文件范围；代码更改、新错误或日志轮转、改写后需手动重试并重新确认。日志是不可信数据，不是指令；不开放任意路径、其他工具或附件。保存修改不代表运行验证通过。
新增能力优先内置库；外部能力使用本地插件协议，不静默安装系统依赖。

## 验证

按改动范围执行测试、静态检查，桌面交付改动还需构建及实际安装包验收。
真实 FFmpeg 插件测试可显式设置 `CALABASH_FFMPEG_TEST_ZIP` 指向本地签名 ZIP。
测试使用合成文件和临时目录，不覆盖真实工具或调用真实模型额度。
签名与公证仍是单独的后续发布阶段，不擅自接入或绕过系统安全提示。

工具日志按每次页面加载/刷新隔离，回调与后台任务沿用所属 run_id。默认每工具保留最近 5 次运行、7 天，单次日志最多 5 MiB（当前文件加一次轮转），全局工具日志目标上限 256 MiB。正在运行、排队或进行修复的日志受保护；受保护日志可临时超过数量/全局上限，结束后在清理时回收。启动、创建/结束运行和完成修复时触发清理，不跟随符号链接。

聊天图片支持选择、拖入和粘贴，PNG/JPEG/WebP/GIF，最多每消息 5 张、每张 10 MiB、1600 万像素。模型请求发送去 EXIF、方向校正及缩放后的像素；聊天记录和 Agent 检查点只保存会话内图片引用，不保存 Base64。像素仅在请求边界解析，校验当前会话、已发送绑定和文件快照。视觉能力按具体模型识别，自定义模型可在设置声明；不支持时明确阻止发送，不伪装识图。

预览诊断授权绑定会话、页面、模型与源码版本，十分钟过期。每次点击或输入须宿主单独确认，真实写入、删除与导出需核对本次操作。刷新或修改后重新授权；DOM/媒体局部检查不等于视觉、听觉或完整业务验收。

## dsh Electron 迁移入口

`electron/` 和 `scripts/harness.mjs` 承载固定版本 dsh 官方 Electron 的独立迁移入口；现有 Tauri 入口在交付验收前保留。使用 `npm run electron:prepare`、`npm run electron:build`、`npm run electron:dev`。上游代码只生成在忽略的 build 目录，修改通过有界 overlay 和本地 `@calabash/harness-workspace` 插件维护，不能提交上游构建产物或静默升级依赖。

dsh Agent 通过 `calabash_tool` 和私有 stdio 调用 `service/tools/harness_workspace.py`；不把现有 LangGraph 运行时嵌套在 dsh 内。会话 ID 和调用 ID 来自 dsh 宿主，不能由模型提供。模型仅写草稿和执行静态构建；预览、发布及覆盖由用户点击并确认。标准 Agent 预设也必须移除 Shell、通用文件读写、多 Agent 和在线插件安装，不能只禁用根节点。保留当前文件安全停止、真实草稿、读取指纹、写租约和构建版本绑定。

开发入口使用独立 dsh profile；不要自动迁移模型密钥、读取用户业务数据或消耗真实模型额度验收。`npm run test:harness` 验证真实 Cordis/AgentLoop 与模拟模型，不调用外部模型。
