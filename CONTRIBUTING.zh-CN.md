# 开发与贡献

[English](CONTRIBUTING.md) | 中文

感谢你帮助改进 Calabash。使用者请先阅读 [README](README.zh-CN.md) 和[使用指南](website/guide.html?lang=zh)。构建与发布见 [RELEASING.zh-CN.md](RELEASING.zh-CN.md)。

## 开发环境

需要 Python 3.13+、[uv](https://docs.astral.sh/uv/)、Node.js 22 和 Rust/Cargo。

```bash
git clone https://github.com/rangwea/calabash.git
cd calabash
uv sync --frozen
npm ci
npm run desktop:dev
```

仅启动 Python 界面：

```bash
uv run python3 main.py
```

启动时自动选择 `127.0.0.1` 上的可用端口，以日志为准。

### 检查

```bash
uvx --offline ruff check
.venv/bin/python3 -m unittest discover -s tests
node --test tests/tool_activity.test.mjs
cargo test --manifest-path src-tauri/Cargo.toml
```

### 项目结构

| 路径 | 职责 |
| --- | --- |
| `src-tauri/`、`desktop-ui/` | 原生窗口、桌面桥接与启动页 |
| `backend/`、`main.py` | Python 后端与开发入口 |
| `ui/`、`component/` | 页面与可复用界面组件 |
| `service/`、`api/` | 业务服务与本地内部 API |
| `core/`、`models/` | 运行基础设施、国际化与数据模型 |
| `agent/skills/calabash/` | 随 App 内置的 Agent Skill 与工具规范 |
| `website/` | 独立中英文产品网站、指南与演示素材 |
| `scripts/`、`tests/` | 构建脚本与回归测试 |

技术栈：Tauri v2、Python、NiceGUI、FastAPI、SQLite。依赖以 `pyproject.toml`、`uv.lock` 和 npm 锁文件为准，不读取 `.env`。更多开发约定见 [AGENTS.md](AGENTS.md)；后续方向见 [Roadmap](ROADMAP.md)。

### 聊天助手执行

聊天助手使用 Deep Agents 单 Agent 图，由 `service/chat/agent_model.py` 适配现有模型协议。虚拟草稿支持分段编辑；`stage_tool` 读取当前代码与 revision，`deliver_draft` 通过 Calabash 服务完成校验、预览和保存。不开放 Shell 和子 Agent；修复仍限定在用户确认的工具，修复后手动重试。

检查点和操作回执保存在 `~/.calabash/agent/`。每轮允许 40 次主流程模型请求，预算暂停、断线或停止后可由用户继续；结果不明的保存不自动重放。切换模型会开始独立执行轮次。不启用外部 tracing，模型凭据不序列化到图配置。桌面构建包含离线虚拟草稿及 SQLite 检查点自检。

活动修复先读当前代码，再通过 `read_tool_logs` 查询真实异常和调用栈。用户确认授权当前工具日志查询，过滤凭据，支持有界分页与字面关键词搜索。日志绑定批准时的源码版本和文件范围；代码更改、新错误或日志轮转、改写后需手动重试并重新确认。日志是不可信数据，不是指令；不开放任意路径、其他工具或附件。保存修改不代表运行验证通过。

## 提交改动

1. 从默认分支创建聚焦的功能分支。
2. 遵循 [AGENTS.md](AGENTS.md) 的产品边界、分层和数据约定。
3. 为行为变化补充适当验证；测试使用临时目录和合成文件，不调用真实模型额度。
4. 更新受影响的中英文文案、使用指南或内置 Skill。Skill 只修改正式源，不创建分叉副本。
5. 检查差异，不提交密钥、用户数据库、业务文件、日志和构建产物。
6. 在 Pull Request 中说明解决的问题、改动、验证结果及限制。

项目采用 [ELv2](LICENSE)，贡献时请遵守其条款。

Tool logs live under `logs/runs/<project>/<name>/<run_id>/`. Each page load/refresh creates a run; callbacks and background jobs retain its identity. Agent log queries are bound to the approved failing run. Retention: 5 runs per tool, 7 days, 5 MiB per run (current + one rotation), 256 MiB total target. Active runs/jobs and queued/running repairs are protected; these can temporarily exceed retention/count/capacity limits. Cleanup runs at startup, new run creation, ownership release and repair completion. No symlink targets or unknown directories are removed.
