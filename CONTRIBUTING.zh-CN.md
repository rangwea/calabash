# 开发与贡献

[English](CONTRIBUTING.md) | 中文

v1.3 使用 DSH Electron + React/TypeScript 宿主，工具为 React + Ant Design + Python/FastAPI。旧宿主保留在 v1.2 分支，不在当前版本维护兼容。

需要 Python 3.13+、uv 和 Node >=24.9。

```bash
uv sync --frozen
npm ci
npm run electron:prepare
npm run electron:build
npm run electron:dev
```

检查：`uvx --offline ruff check`、`.venv/bin/python3 -m unittest discover -s tests`、`npm run test:harness`。测试使用临时 HOME 和合成文件，不调用真实模型额度。

宿主在 electron/workspace，Python 入口为 backend/harness_bridge.py 和 backend/tool_worker.py；业务服务位于 service/tools、service/files、service/capabilities。Skill 正式源在 agent/skills/calabash，网站独立位于 website。

提交前遵循 AGENTS.md，更新受影响的文案、测试及 Skill；不提交用户数据、密钥、日志或构建产物。DSH 插件管理可用；额外能力由用户明确启用，Calabash 默认工具创建会话保持受限。

构建状态见 [发布说明](RELEASING.zh-CN.md)，许可见 [LICENSE](LICENSE)。
