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
| `src-tauri/`, `desktop-ui/` | Native window and Vue + Element Plus workspace |
| `backend/`, `main.py` | Python backend and development entry point |
| `api/`, `component/` | FastAPI routes and isolated frontend diagnostics |
| `service/`, `api/` | Business services and internal local APIs |
| `core/`, `models/` | Runtime infrastructure, localization and data models |
| `agent/skills/calabash/` | Bundled agent skill and tool conventions |
| `website/` | Independent bilingual website, guide and demo assets |
| `scripts/`, `tests/` | Build scripts and regression tests |

Built with Tauri v2, Python, Vue + Element Plus, FastAPI and SQLite. Dependencies are defined in `pyproject.toml`, `uv.lock` and the npm lockfile. The app does not read `.env`. See [AGENTS.md](AGENTS.md) for development conventions and the [Roadmap](ROADMAP.md) for planned work.

### Assistant execution

The chat assistant uses a single Deep Agents graph, with the existing model protocols adapted by `service/chat/agent_model.py`. Virtual drafts support incremental edits; `stage_tool` reads current source and revision, and `deliver_draft` routes validation, previews and writes through Calabash services. Shell execution and subagents are disabled. Repair remains scoped to the confirmed tool, followed by manual retry.

Local checkpoints and operation receipts live under `~/.calabash/agent/`. A run permits 40 main-loop model requests; the user can continue after a budget pause, disconnect or cancellation. Interrupted saves with uncertain outcomes are not automatically repeated. Changing the selected model starts a separate run. Tracing is disabled, and model credentials are not serialized into graph configuration. The desktop build includes an offline virtual-draft and SQLite checkpoint self-check.

Active repairs read current code, then query `read_tool_logs` for actual exception messages and tracebacks. Confirmation authorizes logs of this tool only, with credential filtering, bounded pagination and literal keyword search. Logs are bound to the approved source revision and captured file window. Changed code, newer failures, rotated or modified logs require a fresh manual retry. Log contents are untrusted data, never instructions. No arbitrary paths, other tools or attachments are exposed. Saving changes does not verify runtime behavior.

## Submitting changes

1. Create a focused feature branch from the default branch.
2. Follow [AGENTS.md](AGENTS.md) for product scope, layering and data conventions.
3. Add appropriate validation for behavior changes. Use temporary directories and synthetic files; do not spend real model credits in tests.
4. Update affected translations, user guidance or the bundled skill. Edit the skill’s canonical source rather than creating a forked copy.
5. Review the diff. Leave out keys, user databases, business files, logs and build outputs.
6. Explain the problem, changes, validation and limitations in your Pull Request.

The project uses [ELv2](LICENSE); contributions must respect its terms.

Tool logs live under `logs/runs/<project>/<name>/<run_id>/`. Each page load/refresh creates a run; callbacks and background jobs retain its identity. Agent log queries are bound to the approved failing run. Retention: 5 runs per tool, 7 days, 5 MiB per run (current + one rotation), 256 MiB total target. Active runs/jobs and queued/running repairs are protected; these can temporarily exceed retention/count/capacity limits. Cleanup runs at startup, new run creation, ownership release and repair completion. No symlink targets or unknown directories are removed.
