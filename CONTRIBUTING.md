# Contributing

English | [中文](CONTRIBUTING.zh-CN.md)

Thank you for helping improve Calabash. For everyday use, see the [README](README.md) and [guide](website/guide.html?lang=en). Build and release instructions are in [RELEASING.md](RELEASING.md).

## Development setup

Requires Python 3.13+, [uv](https://docs.astral.sh/uv/), Node.js 22 and Rust/Cargo.

```bash
git clone https://github.com/rangwea/calabash.git
cd calabash
uv sync --frozen
npm ci
npm run desktop:dev
```

To run just the Python interface:

```bash
uv run python3 main.py
```

The backend chooses an available port on `127.0.0.1`. Read the startup log for its URL.

### Checks

```bash
uvx --offline ruff check
.venv/bin/python3 -m unittest discover -s tests
node --test tests/tool_activity.test.mjs
cargo test --manifest-path src-tauri/Cargo.toml
```

### Repository structure

| Path | Purpose |
| --- | --- |
| `src-tauri/`, `desktop-ui/` | Native window, desktop bridge and startup screen |
| `backend/`, `main.py` | Python backend and development entry point |
| `ui/`, `component/` | Pages and reusable UI components |
| `service/`, `api/` | Business services and internal local APIs |
| `core/`, `models/` | Runtime infrastructure, localization and data models |
| `agent/skills/calabash/` | Bundled agent skill and tool conventions |
| `website/` | Independent bilingual website, guide and demo assets |
| `scripts/`, `tests/` | Build scripts and regression tests |

Built with Tauri v2, Python, NiceGUI, FastAPI and SQLite. Dependencies are defined in `pyproject.toml`, `uv.lock` and the npm lockfile. The app does not read `.env`. See [AGENTS.md](AGENTS.md) for development conventions and the [Roadmap](ROADMAP.md) for planned work.

## Submitting changes

1. Create a focused feature branch from the default branch.
2. Follow [AGENTS.md](AGENTS.md) for product scope, layering and data conventions.
3. Add appropriate validation for behavior changes. Use temporary directories and synthetic files; do not spend real model credits in tests.
4. Update affected translations, user guidance or the bundled skill. Edit the skill’s canonical source rather than creating a forked copy.
5. Review the diff. Leave out keys, user databases, business files, logs and build outputs.
6. Explain the problem, changes, validation and limitations in your Pull Request.

The project uses [ELv2](LICENSE); contributions must respect its terms.
