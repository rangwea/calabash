# Building and releasing

English | [中文](RELEASING.zh-CN.md)

Set up the development environment in [Contributing](CONTRIBUTING.md) first. End users do not need these build tools.

## Local build

```bash
npm run desktop:build
```

PyInstaller packages the backend and checks bundled runtime libraries, then Tauri creates the installer. Default macOS outputs are under `src-tauri/target/release/bundle/`.

The [GitHub Release workflow](.github/workflows/release.yml) supports:

- Manually running **Build release app** to produce installer artifacts for three platforms, retained for 14 days.
- Pushing a `v<version>` tag matching `package.json` to create a draft release with installers after all builds succeed.
- Rerunning a tag to update draft assets only. Published releases are not overwritten. Test each platform’s installer before publishing the draft manually.

It uses the automatically provided `GITHUB_TOKEN`, without an additional publishing token. Optional capability plugins are distributed separately from the main app.

## Before publishing

1. Align the version in root package.json, package-lock.json, pyproject.toml, uv.lock, src-tauri/Cargo.toml and Cargo.lock. Tauri reads the root package.json directly.
2. Run relevant checks and commit. Ensure the remote branch includes the release workflow and version changes.
3. Create a tag matching the app version and push it to trigger builds:

```bash
# Replace X.Y.Z with the version in package.json
git tag -a vX.Y.Z -m "Calabash vX.Y.Z"
git push origin main refs/tags/vX.Y.Z
```

4. Confirm all native builds succeed in GitHub Actions. Download and test each platform’s installer, including startup, window behavior, tools and output delivery.
5. Review draft assets and notes, then publish manually. Do not overwrite or move published tags.

Developer distribution signing and Apple notarization remain separate future release work and are not configured in the current workflow. Do not bypass operating-system security prompts.
