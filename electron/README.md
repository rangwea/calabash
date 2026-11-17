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
3. Open the right sidebar and choose **Tool preview**. It belongs to the current conversation and recovers its saved target across UI reloads. The first preview opens on a successful current-revision build event; after backend changes click **Refresh preview** manually.
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

Tool iframes have independent loopback origins and no native preload. Electron embedding uses HttpOnly Secure partitioned session cookies; existing worker origin checks and token validation stay enabled. The Host-only SDK token is not returned to the renderer. Tool jobs participate in quit inspection, and stdio shutdown waits for the current file before shared-service cleanup.

This is a development migration, not a distributable release. Native file-dialog/result-delivery bridges, attachment parity, consent-based runtime repair diagnostics and final installer packaging still use the original desktop entry until separately migrated. Do not claim those old-host-only capabilities are available in this Electron entry yet. Tool source in the shared Python service is trusted local code, not a security sandbox.

## Verification

After building:

```sh
npm run test:harness
```

The Node test mounts real Cordis services and the production DSH AgentLoop with a synthetic streaming model. It executes bounded model tool calls, including read-only office Action discovery, through Python stdio, writes a draft and passes strict compilation, without contacting a provider or spending tokens. Python tests cover read leases, stale edits, idempotency, denied operations, partitioned-cookie auth, real preview/backend calls, confirmation/version-bound publication and cleanup. Tests use synthetic source and temporary homes.

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

CI now validates Electron sources rather than generating obsolete installers. Apple Silicon runtime integration and local installation acceptance are available below; Intel/Windows packaging and automated Release remain separate work.

## Local macOS installer

`npm run electron:package` builds a self-contained Apple Silicon app and DMG. Python uses an onedir frozen executor; frontend compiler resources are separate. Packaging materializes the exact installed DSH package graph with internal relative links and registers Calabash as an installation-owned dependency. No installed path refers back to the source tree. `uv run python -m scripts.check_electron_package <App path>` verifies a synthetic draft, strict React build, preview and Python action with a temporary HOME/cwd and no Node in PATH. The generated DMG was also checked read-only before installation.

The installed profile is ~/.calabash/harness, separate from harness-development; no model credentials are migrated automatically. Release signing/notarization and other installer platforms remain separate work. Calabash does not use upstream DSH automatic update or mandatory-policy feeds.

## Agent execution evidence

DSH owns the durable session events (`tool/call`, `tool/result`, `step/end`, `turn/end`), model usage and `sessionStats` projections. Calabash does not mirror them into another database. The tool presenter provides fixed, friendly operation labels and summaries; original structured results remain available to the Agent through DSH, not displayed as source or compiler output in the office-user card. Session records can contain tool arguments/results: presentation filtering is not storage redaction. Do not automatically export sessions or send them to another model.

The synthetic AgentLoop test checks matched calls/results, native statistics and replay after forking. Model token/cache usage depends on provider reports and is not inferred from text length. Build success is recorded independently from manual business acceptance. `HostTasks` remains a separate bounded queue for desktop tool lifecycle and reconnect handling, not a replacement chat runtime.

## Tool AI Actions

`ai.text` submits one frozen text request to the owning tool's ToolJobs batch. The workspace Host exposes an out-of-iframe review/model-selection dialog; a one-use approval binds the worker, request digest, source revision and DSH prepared model call. It never forwards model keys or chat history to tools. The private executor proxies authenticated AI control over existing stdio, separately from fd 3 lifecycle messages. No business payload is added to task journals or DSH chat messages.

The Host permits at most two concurrent one-shot model calls, 2,048 output tokens and a 120-second execution limit. Review expires after ten minutes; malformed/truncated/tool-call output fails without an automatic retry. Python validates structured outputs and atomically publishes text/JSON results using the existing result store. Cancellation revokes late network output before a result write; a started file write finishes safely. Input text is released from job parameters after completion/cancellation.

`electron/tests/ai-actions.test.mjs` verifies real DSH prepared calls with a synthetic adapter. `electron/tests/ai-roundtrip.mjs` exercises the full Host/stdio/worker/result flow and also runs against a built App with CALABASH_INSTALLED_APP. These tests use temporary profiles and no real model credentials or quota. User-enabled DSH plugins remain trusted code, not a sandbox, and can participate in DSH middleware.

AI confirmation remembers only provider/model identity in the host renderer, resolves it against the current catalog, and never persists approval. The compact card requires a fresh explicit click per request. CalabashResults renders current successful ai.text outputs as bounded plain text/scalar fields, with user-triggered copy and download; it does not render HTML or append result contents to chat.

Visible tool libraries refresh from host metadata automatically. Visible draft panes receive successful current-revision build events and immediately open the first preview through the same strict build/task queue. An opened iframe is never automatically refreshed; a failed revision is not automatically replayed. Publication remains explicitly confirmed. Discovery reads metadata without copying drafts, claiming leases or running tools.

Preview verification now checks known host module HTTP loads, real iframe mount/errors, and typed FastAPI route registration without invoking business handlers (including GET). read_preview_diagnostics is scoped to the current conversation, live run and exact revision. It returns only bounded fixed categories and safe locations; no input, page text, response body, secrets or full logs. UI repair sends a fixed message in the same session only after explicit confirmation. A passed loading/registration check is never business acceptance.

## Shared tool service and schedules

One Python executor now owns a shared FastAPI gateway. Each tool keeps an isolated loopback origin, SDK, module namespace, SQLite database and versioned runtime snapshot; opening tools does not spawn Python workers. Preview and saved tools serve the same verified static build. Node/Vite only runs for bounded compilation, not as a per-preview daemon.

The shared async business queue admits at most 32 batches, executes two at a time and serializes each tool. File work uses four shared threads and waits for active writes on cancellation. A host-only schedule panel selects explicitly registered zero-argument tasks from saved tools. Creating a plan authorizes the exact source version; changed tools and interrupted runs pause, missed occurrences are not replayed, and AI sends still require per-request consent. The schedule manager runs independently of tool pages inside the same service and holds a single-host lease. Schedules require the App to be running. This does not add a second chat or model runtime.

Scheduled tasks has a dedicated main-sidebar panel. Its compact plan list supports tool filtering, on-demand plan creation, status, pause/resume and confirmed run/removal. The host toolbar of an open tool shows its associated plan count and next times; Manage plans opens the schedule panel filtered to that tool. Navigation preserves mounted tool iframes. Dates follow the app language.
