# 构建与发布

[English](RELEASING.md) | 中文

构建者需要先按[开发与贡献指南](CONTRIBUTING.zh-CN.md)安装开发环境。最终用户无需这些工具。

## 本地构建

```bash
npm run desktop:build
```

构建先用 PyInstaller 打包后端并检查内置运行库，再由 Tauri 生成安装包。默认 macOS 产物位于 `src-tauri/target/release/bundle/`。

[GitHub Release 工作流](.github/workflows/release.yml)支持：

- 手动运行 **Build release app**，生成三个平台的安装包 Artifacts，保留 14 天。
- 推送与 `package.json` 版本一致的 `v<版本号>` 标签，全部构建成功后创建 Release 草稿并上传安装包。
- 同一标签重跑只更新草稿，不覆盖已发布的 Release；验收各平台安装包后再手动发布。

使用 GitHub 自动提供的 `GITHUB_TOKEN`，无需额外发布令牌。可选能力插件独立分发，不打进主 App。

## 发布前检查

1. 将版本同步到根 package.json、package-lock.json、pyproject.toml、uv.lock、src-tauri/Cargo.toml 和 Cargo.lock。Tauri 配置直接读取根 package.json。
2. 运行相关检查并提交，确认远程分支包含 Release 工作流和版本改动。
3. 创建与应用版本完全一致的标签，再推送触发构建：

```bash
# 将 X.Y.Z 替换为 package.json 中的版本
git tag -a vX.Y.Z -m "Calabash vX.Y.Z"
git push origin main refs/tags/vX.Y.Z
```

4. 在 GitHub Actions 确认全部原生构建成功。下载并验收各平台安装包，验证启动、窗口行为、工具运行与结果交付。
5. 核对 Release 草稿附件和说明，再手动发布。不要覆盖或移动已发布标签。

开发者分发签名与 Apple 公证仍属于后续发布工作，当前工作流未接入；不得绕过系统安全提示。
