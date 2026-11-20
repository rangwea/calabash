<p align="center">
  <img src="component/assets/calabash.png" alt="Calabash logo" width="88" height="88">
</p>

<h1 align="center">Calabash</h1>

<p align="center">
  <a href="https://github.com/rangwea/calabash/releases"><img src="https://img.shields.io/badge/version-v1.3.1-367767?style=flat-square" alt="App version"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Elastic--2.0-526b80?style=flat-square" alt="License: Elastic License 2.0"></a>
  <a href="https://github.com/rangwea/calabash/actions/workflows/release.yml"><img src="https://github.com/rangwea/calabash/actions/workflows/release.yml/badge.svg" alt="Desktop builds"></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/Python-3.13%2B-3776ab?style=flat-square&amp;logo=python&amp;logoColor=white" alt="Python 3.13 or newer"></a>
  <a href="electron/README.md"><img src="https://img.shields.io/badge/Electron-DSH-47848f?style=flat-square&amp;logo=electron&amp;logoColor=white" alt="Electron + DSH"></a>
</p>

**Everyone should be able to create their own app.**

English | [中文](README.zh-CN.md)

Calabash turns your ideas into interactive tools with AI—built for you, running on your desktop.

## From a request to a tool you can keep using

![Describe a request in chat, then preview and operate the resulting tool](website/assets/demos/ledger-en.gif)

*The chat generation sequence is an illustration with accelerated waiting. Tool interactions are real recordings using synthetic data.*

1. **Describe it.** Explain your inputs, requirements and intended result.
2. **Try it.** Adjust parameters, inspect results and keep chatting to refine the tool.
3. **Keep it.** Save it locally, use it again, or share it as a tool ZIP.

Start with a small idea. It does not need to become a large product, or look like anyone else’s.

Explore the [product website](website/index.html?lang=en) and [guide](website/guide.html?lang=en). The demonstrations show examples you can create, rather than a fixed boundary for the app.

## What it offers today

- **Create and edit tools in chat:** configure an external model and iterate on local tools through conversation.
- **Interfaces you can use:** forms, tables, charts and interactive previews.
- **Local file workflows:** choose files, run individual or batch jobs, follow progress and result history, and deliver new output files.
- **Controlled execution:** duplicate-submission prevention and safe cancellation. With your confirmation, send a necessary error summary to the agent for repair, then retry manually.
- **Local storage and sharing:** organize tools by project and import or export local tool ZIPs.
- **Extensible runtime capabilities:** common document, spreadsheet and image libraries are bundled. Optional capabilities such as FFmpeg are imported as local signed plugin ZIPs.
- **Chinese and English UI.**

What a particular tool can do depends on its requirements, generated code, selected model and available runtime capabilities. Check generated behavior and results before relying on them.

## Getting started

Calabash is in preview and has no public download yet. The website will add a download entry once a signed, notarized release is available. For running from source, see the [contributor guide](CONTRIBUTING.md).

Desktop packages include the Python backend and built-in runtime libraries. End users do not need Python or uv. Configure your model API and key in Settings, select a model, and start a conversation. No Calabash account is required.

CI builds and verifies installers natively on macOS Apple Silicon, macOS Intel and Windows x64. A version tag only creates a draft release; nothing is published automatically. Developer distribution signing and Apple notarization are still missing, so no public download is offered yet.

### Files and data

Tool source lives in `~/.calabash/tools`. Indexes, conversations and execution records are stored locally using SQLite. Loopback HTTP is internal communication between the desktop shell and local backend, not a remote administration service.

**Local execution does not mean offline AI.** Conversation messages and relevant file contents read by the agent may be sent to your selected external model provider. Review these boundaries before working with sensitive files.

Tool ZIPs contain executable source. Import only trusted tools, and check for keys or business data before sharing. ZIP validation is not a security sandbox.

## Feedback and ideas

Share a tool idea or report a problem through [Issues](https://github.com/rangwea/calabash/issues). Use synthetic examples and leave out model keys and sensitive files.

Want to contribute? See the [contributor guide](CONTRIBUTING.md).

## License

Calabash is source-available under the [Elastic License 2.0 (ELv2)](LICENSE). It is not OSI-approved open source.

Personal use, internal business use, modification and redistribution are permitted subject to the license. You may not offer Calabash as a hosted or managed service that gives third parties access to a substantial set of its features. This restriction is not limited to paid services. You must not circumvent license-key functionality or remove licensing, copyright or other licensor notices.

ELv2 does not impose a blanket ban on selling redistributed desktop copies. Third-party components retain their own licenses. See [NOTICE](NOTICE); the full license text controls.

## Why Calabash exists

I want everyone to be able to create their own app.

Not everyone wants to become a programmer. But everyone has their own way of working, a problem to solve, or a moment of thinking, “I wish there were a tool for this.” For a long time, the effort of building software kept many of those ideas from becoming real. I found the closest available product and learned to work around it.

General-purpose AI agents have opened another possibility. They can process files, operate browsers and write code. You can describe what you need and get help doing it, without first learning a programming language.

Then next week, the same task comes around again.

You bring new input, explain the rules again, repeat the details you clarified last time, and wait for the agent to understand, plan and execute. More tokens are spent, and the result may differ. A problem you already solved often needs solving all over again.

If you can explain the task, and AI has found a way to do it, why not keep that method as an app of your own?

**The first time, build it through conversation. Next time, just open it.**

That is where Calabash starts. Describe an idea in chat, let AI create a tool, and try it in the preview beside the conversation. Keep refining the fields, buttons and results until they fit. Then keep it on your computer as a tool you can use again.

Next time, change the input and run it. Logic captured in code can be reused without generating it again. Operations that do not call a model consume no model tokens. When your needs change, come back and edit it. Tools still need testing, and steps that depend on models or external services can still vary. But your experience and the rules you have checked now live in an implementation you can inspect, keep and improve.

It might solve one small problem for one person. Or it might grow into something you share with colleagues and friends, who build on your idea in turn. Software does not have to serve everyone from day one. A need should not require a large market before it deserves a tool.

I want Calabash to help more people move from finding an app that works to making an app that fits. Fewer repeated prompts and fewer tokens spent are practical benefits. Giving more people a way to turn their ideas into software is the larger ambition.

**I hope for an era of apps made by everyone—where anyone can be a creator of software, as well as a user.**

Starting with an idea, a conversation and a tool of your own.

Calabash means “gourd,” or *hulu* in Chinese. In Chinese tradition, its many seeds and trailing vines carry wishes for flourishing generations and abundant blessings. In mythology, a gourd can also be a magical vessel, holding a world within it and possessing extraordinary powers. I chose the name with those images in mind: a small vessel with room for a vast world, where every idea can grow into another tool. I hope Calabash becomes a personal treasure for anyone who creates with it—holding limitless imagination and gaining new abilities as their ideas take shape.
