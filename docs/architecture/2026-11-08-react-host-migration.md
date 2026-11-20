# Calabash v1.3 host and React tools

Approved direction: Electron/DSH/TypeScript owns host orchestration, task admission and workspace presentation; tools use React + Ant Design + TypeScript with Python/FastAPI/ToolSDK business processing. v1.2 remains the Tauri snapshot. Existing user tools are never automatically rewritten or deleted.

## Implementation sequence

1. Replace the tool bundle format, compiler, built-in runtime components, style packs, templates and component API lookup with React equivalents. Keep generated typed Python API contracts and strict static builds. Do not run source during import/inspection or install user dependencies.
2. Move host task scheduling to TypeScript. Correlated concurrent stdio requests, bounded queues, per-resource serialization, queryable task identities and late-result recovery replace the single blocking request loop. Python executes bounded tool services; existing source fingerprints and leases remain authoritative.
3. Move workspace state out of transient React components. Host owns persisted tab identities; renderer owns mounted frames and display. Remounts reconnect to existing processes. Restart restores identities without running tools or replaying business actions.
4. Strengthen process supervision and safe exit. Stop admission before drain, preserve current-file completion, inspect child process failures and reclaim owned compiler/preview processes. Runtime state and protocol errors must not disclose keys, raw source or logs.
5. Update Skill/reference resources, packaging inputs and meaningful regression fixtures. Validate actual DSH loop with simulated models, React preview, publication, ZIP roundtrip, concurrency, disconnect/timeout recovery and shutdown.

## Invariants

- Fixed bundled React/Ant Design and host compiler; no user package.json/Vite plugins or shell.
- App.tsx and backend/main.py are required; React tool bundles have a distinct format. No Vue compatibility executor in the new tool path.
- Explicit @ style > saved snapshot > default. Style presets map to Ant Design theme tokens.
- Build success does not imply business acceptance. Preview, publication, overwrite and repair log sharing require the existing user actions and confirmations.
- Independent tool origins receive no native preload or host-only SDK token.
- Python SDK remains responsible for business file IO, safe batch cancellation, result history, capability checks and structured exceptions.

## Verification

Use synthetic source and temporary HOME/profile directories. Never call a real model or change user business files. Desktop release packaging remains a separately verified artifact; do not claim a distributable build based on source-mode tests.

## Implemented and verified

- React 18.3.1, Ant Design 6.7.0 and Vite React plugin 5.2.0 are locked in npm. Strict tool compilation, SDK UI components, style snapshots, component declaration lookup and typed Python contracts are migrated.
- TypeScript task queue and metadata-only journal are active; conflicting resources serialize, other tools can progress, and UI retries query an existing operation identity.
- Python requests are correlated/concurrent with resource locks. Source leases, fingerprints and receipts remain authoritative tool-domain services.
- Shell-owned workspace frames survive conversation navigation. Host state restores tool identities after actual host restart without running them. Browser acceptance confirmed form input retention and a React form calling the Python starter contract.
- Host tracks trusted lifecycle packets over private fd 3. Executor signals are isolated, so host SIGINT closes its pipes instead of killing the executor before cleanup. A real crash simulation verified worker listener reclamation. Supervisor signals require matching process identity (POSIX start/command identity or a fixed Windows CIM query); unknown/reused identities are never force-stopped.
- Full Python suite: 167 tests, successful with 6 environment-dependent skips. DSH/React synthetic Agent loop, ZIP import/export, queue/late-result recovery, safe-current-file orphan cleanup and the host SIGINT test passed.

## Remaining delivery acceptance

The current implementation is source-mode validated on macOS. Native mouse/keyboard acceptance was limited by the locked Mac; browser form and workspace checks passed. Windows CIM identity queries and taskkill tree reclamation are implemented but still require native Windows acceptance, along with final signed/installed Electron artifacts. The old host and Python chat entry have been removed from v1.3; DSH is the only chat runtime. Installer integration is still pending. No user Vue tool, key or business file was converted/read/deleted, and no real model was called.
