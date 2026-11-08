# v1.3 build and release status

The previous installer pipeline remains on the v1.2 branch. This branch uses Electron/DSH exclusively.

```bash
uv sync --frozen
npm ci
npm run electron:prepare
npm run electron:build
npm run test:harness
npm run electron:dev
```

The upstream commit and package manager are pinned in electron/harness.lock.json. Generated sources/artifacts stay under ignored build/harness. Maintain changes through the Calabash overlay and plugin.

These commands validate a development build, not a distributable installer. GitHub CI checks source builds on three platforms and does not create a Release. Shipping installers still requires wiring Calabash Python/compiler runtimes and resource paths, followed by installation acceptance. Signing and notarization are separate. Do not publish an upstream installer missing the Calabash tool runtime.

Align application versions in package.json, package-lock.json, pyproject.toml, uv.lock and electron/workspace/package.json. Do not change the pinned DSH version to the app version. Publishing requires explicit user authorization.
