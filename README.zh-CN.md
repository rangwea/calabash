<p align="center">
  <img src="src-tauri/icons/icon.png" alt="Calabash 标志" width="88" height="88">
</p>

<h1 align="center">Calabash</h1>

<p align="center">
  <a href="package.json"><img src="https://img.shields.io/github/package-json/v/rangwea/calabash?style=flat-square&amp;label=version&amp;color=367767" alt="应用版本"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Elastic--2.0-526b80?style=flat-square" alt="许可证：Elastic License 2.0"></a>
  <a href="https://github.com/rangwea/calabash/actions/workflows/release.yml"><img src="https://github.com/rangwea/calabash/actions/workflows/release.yml/badge.svg" alt="桌面构建"></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/Python-3.13%2B-3776ab?style=flat-square&amp;logo=python&amp;logoColor=white" alt="Python 3.13 及以上"></a>
  <a href="src-tauri/Cargo.toml"><img src="https://img.shields.io/badge/Tauri-2-24a7b8?style=flat-square&amp;logo=tauri&amp;logoColor=white" alt="Tauri 2"></a>
</p>

**让每个人，都能创造自己的 App。**

[English](README.md) | 中文

Calabash turns your ideas into interactive tools with AI—built for you, running on your desktop.

## 从一句话，到一件可以继续用的工具

![在聊天中描述需求，在右侧预览并操作生成的工具](website/assets/demos/ledger-zh.gif)

*聊天生成部分为流程示意，等待已加速；预览中的工具操作为真实录制，使用合成数据。*

1. **说出来。** 描述需求、输入和希望得到的结果。
2. **试一试。** 在工具界面中填写参数、查看结果，继续对话调整。
3. **留下来。** 工具保存在本机，可以反复使用，也可以通过 ZIP 导出分享。

你可以从一个很小的想法开始。它不需要是宏大的产品，也不需要和别人一样。

更多场景见[产品介绍](website/index.html)与[使用指南](website/guide.html)。演示中的工具是可创建的示例，不是 App 的固定功能边界。

## 现在可以做什么

- **对话创建和修改工具**：选择自己配置的外部模型，在聊天中迭代本地工具。
- **有界面的操作**：表单、表格、图表与交互预览，让工具可以被直接使用。
- **本地文件处理**：选择文件，执行单项或批量任务，查看进度与结果历史，交付新的结果文件。
- **可控的执行过程**：防重复提交、安全取消；出错后可确认发送必要摘要给 Agent 修复，再手动重试。
- **本地保存与分享**：按项目整理工具，支持本地 ZIP 导入、导出。
- **扩展运行能力**：常用文档、表格和图片库随 App 打包；FFmpeg 等可选能力通过本地签名插件 ZIP 导入。
- **中英文界面**：按习惯使用中文或英文。

具体工具能做什么，取决于需求、生成的代码、所选模型和可用运行能力；生成后仍应检查行为与结果。

## 开始使用

Calabash 目前处于预览阶段。可在 [Releases](https://github.com/rangwea/calabash/releases) 查看已公开的版本；源码运行请参考[开发指南](CONTRIBUTING.zh-CN.md)。

桌面安装包包含 Python 后端和内置运行库，最终用户不需要安装 Python 或 uv。首次使用需在设置中配置模型 API 和密钥，再选择模型开始对话；不需要 Calabash 账号。

macOS Apple Silicon、Intel 与 Windows x64 安装包的可用情况以发布页面为准。目前的预览安装包尚未接入开发者分发签名与 Apple 公证。

### 文件和数据

工具源码位于 `~/.calabash/tools`，本地索引、对话及运行记录使用 SQLite 保存。回环 HTTP 仅用于桌面壳与本地后端通信，不提供远程管理服务。

**本地运行不代表模型离线运行。** 对话消息和 Agent 读取的相关文件内容可能发送给你选择的外部模型服务商。处理敏感文件前，请确认数据边界。

工具 ZIP 包含可执行源码。只导入可信来源，分享前检查密钥和业务数据；ZIP 导入检查不等于安全沙箱。

## 反馈与交流

欢迎通过 [Issues](https://github.com/rangwea/calabash/issues) 分享工具想法或反馈使用问题。请使用合成样例，不附带模型密钥或敏感文件。

想参与开发？请阅读[开发与贡献指南](CONTRIBUTING.zh-CN.md)。

## 许可证

Calabash 采用 [Elastic License 2.0（ELv2）](LICENSE)，属于源码可用项目，不属于 OSI 认可的标准开源项目。

在遵守许可证的前提下，允许个人使用、企业内部使用、修改和再分发。不得将 Calabash 作为托管或管理服务提供给第三方，让第三方访问其重要功能；这项限制不限于收费服务。不得绕过许可证密钥功能，也不得移除许可、版权或其他许可方声明。

ELv2 并不全面禁止售卖再分发的桌面版本。第三方组件仍遵循各自许可证。版权信息见 [NOTICE](NOTICE)，具体权利和限制以英文许可证全文为准。

## 为什么会有 Calabash

我希望，每个人都能写出属于自己的 App。

不是每个人都想成为程序员，但每个人都有自己的工作习惯、想解决的问题，和一句“要是有个这样的工具就好了”。过去，做一款软件的门槛，让很多这样的想法停在了脑海里。我只能寻找最接近的产品，再慢慢适应它。

通用 AI Agent 让这件事有了新的可能。它能处理文件、操作浏览器、编写代码。你不必先学会一门编程语言，就可以描述需求，让它帮你完成工作。

但到了下周，同样的事情又来了。

你换了一份输入，重新解释规则，补充上次强调过的细节，再等它理解、规划、执行。又消耗了一轮 Token，结果也可能和上次不同。一个已经解决过的问题，往往还得再解决一遍。

我想，既然你已经能把需求讲清楚，AI 也已经找到了处理方法，为什么不把它留下来，变成你自己的 App？

**第一次，用对话把想法做出来；下一次，直接打开它。**

这就是 Calabash 的出发点。你在聊天里描述想法，让 AI 创建工具，在旁边的预览中试用。字段怎么排、按钮做什么、结果如何呈现，都可以继续对话调整。满意之后，把它留在自己的电脑上，成为一件可以反复使用的工具。

下一次，换一份输入，点击运行。已经写进代码的流程可以直接复用，无需每次重新生成；不调用模型的操作，也不消耗模型 Token。需求变了，再回来修改。工具仍然需要测试，依赖模型或外部服务的步骤也仍可能变化，但你的经验和确认过的规则，有了一份可以检查、保留和持续改进的实现。

它可以只解决一个很小的问题，只适合你一个人。也可以慢慢丰富起来，分享给同事、朋友，让别人在你的想法上继续创造。软件不必一开始就面向所有人，值得被做出来的需求，也不必先有一个足够大的市场。

我希望，Calabash 让更多人从“找一个能用的 App”，走向“做一个适合自己的 App”。减少重复提问和 Token 消耗，是这件事带来的实际价值；让普通人也能把自己的想法变成软件，是我更长远的愿望。

**我期待一个全民 App 的时代：人人都可以是软件的使用者，也可以是创造者。**

从一个念头、一段对话、一件自己的工具开始。

Calabash 的中文意思是“葫芦”。在中国传统文化中，葫芦多籽、藤蔓绵延，寄托着子孙兴旺、多子多福的祝愿；在神话故事里，它又常是藏有乾坤、各具神通的法宝。我喜欢这些意象，也把自己的期待放进这个名字里：小小的葫芦，可以装下大千世界；每一个想法，都可以生长出新的工具。我希望 Calabash 像一件属于每个人的法宝，容纳无限想象，随着你的创造，拥有越来越丰富的本领。
