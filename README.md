# Calabash

Calabash 是一个本地运行的个人 AI 工具桌面。它以 FastAPI 和 NiceGUI 提供本地界面，工具文件保存在用户目录 `~/.calabash/tools`，本地 SQLite 负责索引和运行状态。应用版本以根目录 `package.json` 为准。

## 核心能力

- 工具桌面：按项目浏览和运行本地工具；
- 本地存储：工具文件保存在 `~/.calabash/tools`；
- 本地数据库：使用 SQLite 保存索引、版本和运行状态；
- 生命周期：本地创建、编辑、临时预览、状态查询和删除；
- Agent 集成：通过 Skill 直接读写本地工具目录。

## 本地运行

### 环境要求

- Python 3.13 或更高版本；
- [uv](https://docs.astral.sh/uv/)；

### 本地部署

```bash
git clone https://github.com/OWNER/REPOSITORY.git
cd REPOSITORY
uv sync
```

启动本地应用：

```bash
uv run python3 main.py
```

应用启动时会自动选择可用端口，并在 `~/.calabash/calabash.db` 创建本地 SQLite 数据库。

### 桌面壳开发与打包

项目包含 Tauri v2 桌面壳。开发期由 Tauri 主进程拉起本地 Python 后端，
等待随机端口可连接后将窗口导航到 NiceGUI 首页：

```bash
npm install
npm run desktop:dev
```

开发机需要 Node.js、npm、Rust/Cargo、Python 3.13 和 uv。开发模式仍依赖本机
`uv run python3 -m backend.desktop_server --print-ready` 启动后端；关闭桌面窗口时
Tauri 会同步结束这个后端进程。

构建桌面应用：

```bash
npm run desktop:build
```

构建流程会先用 PyInstaller 生成 `calabash-backend` sidecar，再由 Tauri 将它打进
`.app`。发布后的应用直接启动内置后端，不要求用户安装 Python 或 uv。

默认构建产物位于：

```text
src-tauri/target/release/bundle/macos/Calabash.app
src-tauri/target/release/bundle/dmg/Calabash_0.2.0_aarch64.dmg
```

当前 macOS 构建会产出 `.app` 和 `.dmg`。DMG 内包含 `Calabash.app` 和
`/Applications` 快捷方式；正式对外分发前还需要接入 Apple Developer 签名和公证流程。

### GitHub Actions 构建与 Release

工作流为 `.github/workflows/release.yml`，使用各平台原生 runner 构建
macOS Apple Silicon、macOS Intel 的 DMG，以及 Windows x64 的 NSIS 安装包。
构建包含 Python sidecar 和运行库自检；FFmpeg 等可选插件不随 App 打包。

- 在 GitHub Actions 中手动运行 **Build release app**，只生成安装包 Artifacts，保留 14 天。
- 推送 `v<版本号>` 标签后，全部平台构建成功才创建 **Release 草稿**并上传三个安装包。
- 标签必须与 `package.json` 版本完全一致，并通过现有清单版本一致性检查。
- 同一标签重跑可更新草稿附件，不覆盖已经正式发布的 Release。

例如当前版本为 `0.2.0`：

```bash
git tag v0.2.0
git push origin v0.2.0
```

工作流不需要额外的模型密钥或发布令牌，使用 GitHub 自动提供的 `GITHUB_TOKEN`；
只有创建草稿的 job 获得 `contents: write` 权限。签名与公证尚未接入，
下载各平台安装包完成验收后，再手动发布草稿。首次 CI 构建结果仍需在 GitHub 上确认。

### 使用入口

应用仅监听本机 `127.0.0.1`，端口由启动时自动选择，以启动日志为准：

| 地址 | 用途 |
|------|------|
| `/` | 首页 |
| `/tools/{project}/{name}` | 工具运行页 |
| `/preview/{key}` | 临时工具预览 |
| `/preview/{project}/{name}` | 固定工具预览 |
| `/health` | 健康检查 |

## 内置 Agent Skill

Calabash Skill 包含工具生成规范、生命周期规则、参考模板和轻量 CLI。桌面版 CLI
直接读写 `~/.calabash/tools`；只有 `preview` 和 `prelog` 需要正在运行的本地服务。
工具列表支持本地 ZIP 导入和单工具 ZIP 导出，不提供 GitHub 地址导入、工具管理后台、远程发布、平台变量或远程数据源配置。

工具 ZIP 固定包含 `manifest.json`（格式 `calabash-tool`、版本 `1`、项目和工具标识）与 `tool.py`（UTF-8 单文件源码），不包含聊天、结果、日志或应用配置。ZIP 最大 2 MB、源码最大 1 MB；能力插件 ZIP 与工具 ZIP 不能互相导入。
导入只做结构和语法检查，不执行代码或安装依赖；静态校验不是安全沙箱，请仅导入可信来源。同名工具须重命名或明确确认覆盖，运行中的工具不可覆盖。导出会包含完整源码，分享前应检查是否写入了密钥或业务数据。

`agent/skills/calabash` 是 App 内置 Skill 的唯一正式源，随桌面后端打包，无需用户安装；`.agents/skills/calabash` 是供仓库内开发和测试使用的符号链接。

工具创建与修改规范见 [Calabash Skill](agent/skills/calabash/SKILL.md)，其 references 目录包含本地文件处理、运行库和 UI 模板说明。

只读统计、图表、仪表盘与 Excel 导出同样由 Calabash Skill 承接。

内置 Skill 与可选能力插件相互独立。FFmpeg 等能力插件仍通过本地 ZIP 导入，安装到 `~/.calabash/plugins`。

### 开发生命周期示例

```bash
CALABASH_CLI=.agents/skills/calabash/scripts/tool-cli.py

# 本地创建到 ~/.calabash/tools
python3 "$CALABASH_CLI" create demo order_query

# 固定预览，不修改正式工具，需要本地服务地址
python3 "$CALABASH_CLI" --server http://127.0.0.1:56141 \
  preview demo order_query --file ~/.calabash/tools/demo/order_query.py

# 查看预览日志
python3 "$CALABASH_CLI" --server http://127.0.0.1:56141 prelog demo order_query

# 保存到正式工具文件，执行前必须确认目标
python3 "$CALABASH_CLI" publish demo order_query --yes

# 核对本地状态
python3 "$CALABASH_CLI" status demo order_query
```

`create` 只创建本地文件，`preview` 只创建临时运行环境，`publish` 会覆盖写入本地正式工具文件并更新 sidecar 版本。Agent 在执行 `publish` 或 `delete` 前必须获得用户明确确认。

## 开发贡献

### 项目结构

```text
├── main.py              # FastAPI + NiceGUI 应用入口
├── core/                # 数据库、配置、样式和运行时能力
├── models/              # SQLModel 数据模型
├── service/             # chat、tools、files、capabilities 业务服务
├── ui/                  # 页面入口、侧栏、工具列表和设置视图
├── api/                 # 本地内部 API
├── component/           # 可复用 UI 组件
├── scripts/             # 桌面构建、图标及插件打包脚本
├── .agents/skills/      # 项目级 Skills
└── agent/skills/        # App 内置 Agent Skill 与工具参考规范
```

Calabash 使用分层结构：

```text
页面层 -> API 层 -> Service 层 -> 数据访问层 -> SQLite
```

数据库操作应使用 `db_manager.session_scope()`；页面样式优先使用 NiceGUI `.classes()` 和 `.props()`。

### 开发命令

```bash
# 安装或同步依赖
uv sync

# 启动开发服务
uv run main.py

# 代码检查
ruff check

# 自动修复可安全修复的问题
ruff check --fix

# 格式化
ruff format
```

### 提交流程

1. 从最新默认分支创建功能分支；
2. 保持改动聚焦，并为行为变化补充测试或验证步骤；
3. 同步更新 README、详细文档、Skill 和 Plugin 中受影响的说明；
4. 运行 `ruff check` 和相关测试；
5. 检查 diff，确保没有提交 `.env`、Token、日志或业务数据；
6. 提交 Pull Request，说明问题、方案、验证结果和兼容性影响。

修改工具生命周期、数据库 Schema 或生产发布行为时，请同时说明迁移和回滚方法。修改 Calabash Skill 时直接编辑 `agent/skills/calabash`，项目级入口使用符号链接，不维护分发副本。

Python 依赖统一由 `pyproject.toml` 和 `uv.lock` 管理，应用不读取 `.env`。
SQLite 表由应用启动时自动创建，无需手工执行 SQL 或部署数据库。
当前不维护 Docker 部署；运行与开发说明以本 README、AGENTS.md 和 Skill 内参考规范为准。

## 技术栈

| 组件 | 技术 |
|------|------|
| Python | 3.13+ |
| Web UI | NiceGUI 3.11+ |
| API | FastAPI + Uvicorn |
| ORM | SQLModel + SQLAlchemy |
| Database | SQLite |
| Package manager | uv |
| Desktop shell | Tauri v2 |
| Code quality | Ruff |

## License

请根据仓库实际发布策略补充许可证文件。在许可证明确前，不应假定仓库代码可以被复制、修改或再分发。
