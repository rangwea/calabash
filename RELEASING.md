# v1.3 builds and releases

Self-contained Electron DMGs are currently supported on Apple Silicon Macs:

```bash
uv sync --frozen
npm ci
npm run electron:prepare
npm run electron:package
uv run python -m scripts.check_electron_package dist/electron/mac-arm64/Calabash.app
```

Outputs: dist/electron/Calabash-1.3.0-macos-arm64.dmg and dist/electron/mac-arm64/Calabash.app. The app bundles an independent Python executor, office libraries, pinned Node and the React compiler. End users need no Python, Node or uv installation. Compiler resources are separate from Python; running the app does not unpack a Python single-file bundle. Runtime data stays in the user directory, including when application resources are read-only.

Packaging checks the pinned DSH checkout, overlay fingerprint and contained runtime links. Acceptance covers source builds, frozen-library self-checks, synthetic tool compilation/action tests and a read-only mounted DMG. Application and DSH versions remain independent. Never package the development .venv, source-path dependencies, user credentials or settings. Preserve upstream MIT and dependency licenses.

Local builds have no developer distribution signature or notarization. Do not bypass OS security prompts. Intel Mac/Windows installers and automated GitHub Releases still require platform implementation and acceptance; current CI validates sources only.
