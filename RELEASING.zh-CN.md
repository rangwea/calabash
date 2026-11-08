# v1.3 构建与发布状态

旧安装包构建保留在 v1.2 分支。v1.3 仅使用 Electron/DSH，不再构建旧宿主。

```bash
uv sync --frozen
npm ci
npm run electron:prepare
npm run electron:build
npm run test:harness
npm run electron:dev
```

上游版本和包管理器由 electron/harness.lock.json 固定。源码与产物在 build/harness 下，不能提交；通过 Calabash overlay 和插件维护修改。

当前命令完成 Electron 开发构建与运行验证，不代表可分发安装包。GitHub workflow 验证三平台源码构建，不自动创建 Release。正式安装包还需接入 Calabash Python 运行库、编译运行库和资源路径，并完成实际安装验收；签名、公证另行处理。禁止把缺少工具运行库的上游安装包作为 Calabash 发布。

应用版本统一更新 package.json、package-lock.json、pyproject.toml、uv.lock 和 electron/workspace/package.json；DSH 固定版本不随应用版本改写。发布需用户明确授权。
