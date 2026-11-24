# v1.3 构建与发布

`npm run electron:package` 按当前机器原生打包：macOS Apple Silicon/x64 生成 App 与 DMG，Windows x64 生成 NSIS 安装程序；CI 在三种原生 runner 上执行。

```bash
uv sync --frozen
npm ci
npm run electron:prepare
npm run electron:package
uv run python -m scripts.check_electron_package dist/electron/mac-arm64/Calabash.app
```

输出为 dist/electron/Calabash-1.3.1-macos-arm64.dmg，应用目录为 dist/electron/mac-arm64/Calabash.app。安装包内置独立 Python 后端、办公库、固定 Node 和 React 编译运行库，无需用户安装 Python、Node 或 uv。编译器单独放在资源目录，不随 Python 每次启动解压。安装路径可以只读，运行数据在用户目录。

打包过程校验固定 DSH 提交、overlay 指纹和包内链接；`scripts/check_electron_package.py` 把构建产物解包到临时 HOME，验证冻结执行器、严格构建、预览和 Python action，它本身不挂载 DMG。应用和 DSH 保持独立版本。不得把 .venv、源码绝对路径、用户配置或密钥打入安装包。保留上游 MIT 和依赖许可。

当前本地构建未做开发者分发签名或公证；不绕过系统安全提示。打 `v*` 标签后 CI 只创建或更新草稿 Release，不自动发布，也不修改已发布的 Release。

## 发布已验收的草稿

三平台任务全部通过后，在 [GitHub Releases](https://github.com/rangwea/calabash/releases) 打开草稿，核对发布说明、两个 DMG、Windows 安装程序和 `SHA256SUMS.txt`，再手动发布。v1.3.1 已公开发布；签名与公证仍未完成，不得描述为已完成。

同步中英文 README、官网下载入口和安装指南，使其与实际发布的安装包一致。`website/` 修改推送到 `main` 后，由 `.github/workflows/pages.yml` 独立部署至 https://rangwea.github.io/calabash/。网站部署不会发布 App Release。
