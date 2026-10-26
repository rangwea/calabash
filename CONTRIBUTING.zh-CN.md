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

## 提交改动

1. 从默认分支创建聚焦的功能分支。
2. 遵循 [AGENTS.md](AGENTS.md) 的产品边界、分层和数据约定。
3. 为行为变化补充适当验证；测试使用临时目录和合成文件，不调用真实模型额度。
4. 更新受影响的中英文文案、使用指南或内置 Skill。Skill 只修改正式源，不创建分叉副本。
5. 检查差异，不提交密钥、用户数据库、业务文件、日志和构建产物。
6. 在 Pull Request 中说明解决的问题、改动、验证结果及限制。

项目采用 [ELv2](LICENSE)，贡献时请遵守其条款。
