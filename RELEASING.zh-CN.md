# v1.3 构建与发布

当前可在 Apple Silicon Mac 上生成自包含 Electron DMG：

```bash
uv sync --frozen
npm ci
npm run electron:prepare
npm run electron:package
uv run python -m scripts.check_electron_package dist/electron/mac-arm64/Calabash.app
```

输出为 dist/electron/Calabash-1.3.0-macos-arm64.dmg，应用目录为 dist/electron/mac-arm64/Calabash.app。安装包内置独立 Python 后端、办公库、固定 Node 和 React 编译运行库，无需用户安装 Python、Node 或 uv。编译器单独放在资源目录，不随 Python 每次启动解压。安装路径可以只读，运行数据在用户目录。

打包过程校验固定 DSH 提交、overlay 指纹和包内链接；通过源码构建、冻结运行库自检、安装产物合成工具测试，以及只读 DMG 验收。应用和 DSH 保持独立版本。不得把 .venv、源码绝对路径、用户配置或密钥打入安装包。保留上游 MIT 和依赖许可。

当前本地构建未做开发者分发签名或公证；不绕过系统安全提示。Intel Mac、Windows 安装包和 GitHub 自动发布还需各平台实现与验收；现有 workflow 仅做源码构建检查。
