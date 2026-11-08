# Contributing

English | [中文](CONTRIBUTING.zh-CN.md)

v1.3 uses DSH Electron with a React/TypeScript host. Tools use React, Ant Design and Python/FastAPI. The previous host lives on the v1.2 branch; this branch has no compatibility executor.

Requires Python 3.13+, uv and Node >=24.9.

```bash
uv sync --frozen
npm ci
npm run electron:prepare
npm run electron:build
npm run electron:dev
```

Run `uvx --offline ruff check`, `.venv/bin/python3 -m unittest discover -s tests`, and `npm run test:harness`. Use temporary HOME directories and synthetic files; never spend real model credits in tests.

The host lives in electron/workspace. Python entry points are backend/harness_bridge.py and backend/tool_worker.py. Tool, file and capability services live under service/. The canonical Skill is agent/skills/calabash; website/ is independent.

Follow AGENTS.md, update affected tests, guidance and translations, and keep credentials, user data, logs and build artifacts out of commits. DSH plugin management remains available. Users explicitly enable extra capabilities; the default Calabash authoring agent remains restricted.

See [release guidance](RELEASING.md) and [LICENSE](LICENSE).
