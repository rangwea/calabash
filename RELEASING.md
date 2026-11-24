# v1.3 builds and releases

`npm run electron:package` builds natively for the current machine: macOS
Apple Silicon/x64 as an app plus DMG, and Windows x64 as an NSIS installer. CI runs
all three targets on native runners.

```bash
uv sync --frozen
npm ci
npm run electron:prepare
npm run electron:package
uv run python -m scripts.check_electron_package dist/electron/mac-arm64/Calabash.app
```

Outputs: dist/electron/Calabash-1.3.1-macos-arm64.dmg and dist/electron/mac-arm64/Calabash.app. The app bundles an independent Python executor, office libraries, pinned Node and the React compiler. End users need no Python, Node or uv installation. Compiler resources are separate from Python; running the app does not unpack a Python single-file bundle. Runtime data stays in the user directory, including when application resources are read-only.

Packaging checks the pinned DSH checkout, overlay fingerprint and contained runtime links. `scripts/check_electron_package.py` unpacks the built application into a temporary HOME and verifies the frozen executor, strict builds, preview and Python actions; it does not mount the DMG itself. Application and DSH versions remain independent. Never package the development .venv, source-path dependencies, user credentials or settings. Preserve upstream MIT and dependency licenses.

Local builds have no developer distribution signature or notarization. Do not bypass OS security prompts. A `v*` tag makes CI create or update a draft release only; nothing is published automatically and an already published release is never modified.

## Publish a checked draft

After all three platform jobs pass, open the draft in [GitHub Releases](https://github.com/rangwea/calabash/releases), review its notes, the two DMGs, Windows installer and `SHA256SUMS.txt`, then explicitly publish it. v1.3.1 is already public. Signing and notarization remain pending and must not be described as completed.

Keep both READMEs, the website download entry and bilingual installation guidance consistent with the published assets. Website changes pushed to `main` deploy independently through `.github/workflows/pages.yml` to https://rangwea.github.io/calabash/. Website deployment does not publish an App release.
