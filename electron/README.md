# Calabash on DeepSeek Harness Electron

The migration entry uses the official DSH Electron shell and chat UI, with a local Calabash plugin. Generated tools remain independent React + Ant Design + Python applications. This is the only host in v1.3; the previous implementation lives on the v1.2 branch.

## Development

Development requires Node >=24.9, npm, the existing Calabash Python environment (`uv sync`) and frontend dependencies (`npm install`).

```sh
npm run electron:prepare
npm run electron:build
npm run electron:dev
```

For an existing pinned checkout, set `CALABASH_HARNESS_SOURCE` to its absolute path on **each** command. `CALABASH_HARNESS_HOME` selects an isolated DSH profile; the default is `~/.calabash/harness-development`. Model connections are configured manually in the DSH settings. Existing Calabash credentials are never imported automatically. `CALABASH_PYTHON` can select the development Python executable; otherwise the repository's `.venv` is used.

Preparation fetches the exact commit in `harness.lock.json`, installs its frozen dependency graph and explicitly runs the official Electron binary installer. Other dependency lifecycle scripts are disabled. Build adds only the checked-in local workspace importer to that lockfile, then links dependencies **with the frozen lock**. Registry safety verification may need to fetch missing package metadata; package versions are not resolved or upgraded. The primary runtime builder downloads checksum-verified Node, Python and document dependencies on first build.

Upstream sources and artifacts live in ignored `build/harness/<commit>`. The bounded overlay and `electron/workspace` are the maintained source. Changed upstream integration points fail the build. The build marker fingerprints the plugin and overlays; starting stale artifacts requests a rebuild. The launcher uses official main-process and development-project helpers without automatic macOS re-signing, public inspector ports or automatically opened developer tools.

## Using the workspace

1. Open **My tools** to search and run published local tools. Each row includes conversation, ZIP export and confirmed deletion actions. **Import tool** checks a local ZIP before asking for confirmation; replacing an existing tool requires explicit confirmation. Close the tool before deleting or replacing it. Multiple open tools have tabs. The full library uses compact horizontal rows with tool icons and always-visible conversation/export/delete actions, within a bounded content width. Once a tool is open, the sidebar uses shorter tinted navigation items with no action-button row. Right-click or press Shift+F10 / the Menu key on a sidebar tool for conversation, ZIP export and confirmed deletion; a normal click opens it. Search and collapse stay on one row, with active-tool highlighting and two-line descriptions. The tool-list boundary has a collapse/expand button once a tool is open; collapsing preserves the search, list and running tool frames. Switching those tabs keeps their iframes mounted; close uses the existing safe-stop protocol.
2. Describe a tool in a DSH conversation. The Agent uses `calabash_tool` to read the built-in Skill/template, inspect component and API contracts, edit the real draft and perform strict compilation.
3. Open the right sidebar and choose **Tool preview**. It belongs to the current conversation and recovers its saved target across UI reloads. Click **Open preview**; after backend changes click **Refresh preview** manually.
4. Try the draft, then click **Save to tools**. Saving and replacing require confirmation. A changed draft or published revision is rejected; running published tools cannot be overwritten. Successful compilation or source saving does not imply business verification.

Tool ZIP transfers use bounded chunks and expiring host-only tickets. Inspection returns metadata only; source is never rendered or sent to the model. Import compiles using the built-in frontend dependencies after confirmation, never executes the Python tool or installs packages. Export contains source and theme snapshots only. The conversation button reopens the tool’s linked DSH conversation, or creates and binds one without a model request; saving a published tool records that association.

Tool authoring, build diagnostics and run data continue using the existing Calabash service paths. DSH stores chat/model settings separately in its development home. A conversation is bound to one tool. Tool source is not duplicated into DSH model state or arbitrary web projects.

## @ UI styles

Type `@` in the composer to choose Office, Soft or Compact. The native DSH menu supports Chinese/English filtering, keyboard selection and removable reference chips. Copied/restored drafts use stable tokens such as `@ui:soft`; typed `@Office`, `@Soft`, `@Compact` and the Chinese titles also work.

The Host derives the latest style selection from real user-message events through a DSH Session projection. It survives context compaction and session replay without retaining an extra copy of user text. Model/tool messages cannot change it. A follow-up without a style clears the per-request override and inherits the tool snapshot; it does not reapply the global default.

Selection order is explicit current-message `@` → existing tool metadata/token snapshot → the configured default for a new tool. `read_ui_preset` returns only that selected pack, even when the model requests a different pack. Explicit restyling updates host-owned metadata/tokens on the next source save, including when the model only edits App.tsx. Imported custom snapshots remain intact, and changing the global default never restyles an existing tool.

## Boundaries

The Host's authenticated, generated Typert Remote exposes listing, opening, closing, conversation target, manual preview and confirmed publication. The private Python stdio transport is never given to tool frames. The model cannot choose its session/call identity, launch or publish tools, delete data, install packages, use Shell, or read arbitrary files. Source edits retain the existing write leases, read fingerprints, credential redaction, operation receipts, theme snapshots and revision-bound compiler checks. Working source lives in the real draft directory; backend workers retain their execution snapshots.

Both root composition **and Agent presets** are restricted. The standard preset retains context compaction, questions and a sequential task list. Generic filesystem/Shell/browser/subagent/workflow/plugin-installation tools and alternate coding presets are disabled by default. Plugin management and inventory UI remain available. Optional Skill/MCP/browser/Shell tools are disabled by default and may be explicitly enabled by the user through DSH profiles. Third-party host plugins execute trusted code; the authoring-tool allowlist is not a plugin sandbox. Calabash is a required startup plugin, so import failure cannot silently produce an incomplete workspace.

Tool iframes have independent loopback origins and no native preload. Electron embedding uses HttpOnly Secure partitioned session cookies; existing worker origin checks and token validation stay enabled. The Host-only SDK token is not returned to the renderer. Tool jobs participate in quit inspection, and stdio shutdown waits for the current file before process cleanup.

This is a development migration, not a distributable release. Native file-dialog/result-delivery bridges, attachment parity, consent-based runtime repair diagnostics and final installer packaging still use the original desktop entry until separately migrated. Do not claim those old-host-only capabilities are available in this Electron entry yet. Application source in an approved tool process is not a security sandbox.

## Verification

After building:

```sh
npm run test:harness
```

The Node test mounts real Cordis services and the production DSH AgentLoop with a synthetic streaming model. It executes six model tool calls through Python stdio, writes a draft and passes strict compilation, without contacting a provider or spending tokens. Python tests cover read leases, stale edits, idempotency, denied operations, partitioned-cookie auth, real preview/backend calls, confirmation/version-bound publication and cleanup. Tests use synthetic source and temporary homes.

Desktop acceptance additionally verifies the actual Electron buttons: list → open/interact; conversation → preview/interact → confirm save → tool appears in the list. This was verified on macOS arm64; Windows packaging and final installed-artifact acceptance remain release work.

## Attribution

DeepSeek Harness is MIT licensed, Copyright (c) 2026 DeepSeek. Its unchanged license is in `DSH-LICENSE.txt`. Preserve upstream notices and transitive dependency licenses in distributable artifacts. Calabash is independently developed and is not an official DeepSeek application.

## Host orchestration and React tool runtime

TypeScript owns bounded host tasks, durable metadata-only task journals, presentation-state persistence and private child-process supervision. Requeries retain operation identity; a UI observer disconnect does not cancel or replay a write. Python executes bounded source/build/SDK services concurrently, serializing conflicting tool operations. Business file processing remains Python.

New tools use calabash-react-tool / frontend/App.tsx, strict tsc + Vite React builds and bundled Ant Design. @calabash/ui exposes React file-input, results, job-status and chart components. The existing @calabash/api contract generator remains authoritative for Python request/response types. Existing user Vue tools are neither converted nor deleted.

The persistent shell workspace keeps frames mounted while navigating to conversations. Restart restores tool identities without executing them; click Open tool to launch. Native release/Windows installer acceptance and complete original-host feature parity remain separately verified release work.

## v1.3 cleanup

Only Electron/DSH remains as the host. Tauri, the Vue workspace, old Python chat/model/SSE APIs, LangGraph and SQLModel have been removed. Tool source observations and idempotent receipts live in service/tools/operation_store.py. Result history uses its own tool-results.sqlite instead of a chat database. User tools, credentials and historical databases are not migrated or deleted.

Calabash overlay defaults apply before explicit user profile/home patches. The real DSH composer is tested for both defaults and user overrides. Plugin manager and inventory are visible; optional tools remain off unless enabled by the user. This is profile-level configuration, not a new per-session permission editor or a plugin sandbox. The model's plugin installer remains disabled by default.

The current DSH adapter exposes static build diagnostics but not the removed host's runtime-log/preview-interaction consent flow. The Skill names only available operations. Runtime events remain local in ToolSDK logs.

CI now validates Electron sources rather than generating obsolete installers. Complete Electron installer runtime wiring and platform installation acceptance remain release work; no automated Release is produced by this workflow.
