# Calabash Quality Gate

## Before Writing Tool Code

- Read `runtime.md` and `runtime-libraries.json`. Use bundled libraries; do not install packages or assume system executables. Planned extension packs are unavailable until implemented and installed.
- Declare optional plugin capabilities in the module docstring, e.g. `requires: media.ffmpeg>=9.0.2`. Leave empty for bundled-only tools. Missing capabilities are handled by the host before import; never auto-install packages or auto-run tasks after an import.

- Read `references/design.md` before implementing UI layout.
- Read `references/uix.md` when tool-local option controls need guidance.
- Read `references/variables.md` when the tool needs local constants or per-tool configuration.
- Read only the task-oriented `references/nicegui/` files routed by `SKILL.md`.
- Choose `references/simple-tool.py` for simple form/table tools.
- Choose `references/query-tool.py` for filter, pagination, or detail workflows.
- For user files, exports or batches, read `file-workflow.md` and use `file-tool.py` as the starting point. Do not graft file controls onto unrelated tools.

## Entrypoint

- `main` must be a top-level function.
- Do not decorate or dynamically generate `main`.
- Calabash owns execution. Define main() only; do not add ui.run() or a standalone run guard.

## UI Rules

- Follow `design.md`: Fluent-inspired office defaults, with tool-local themes and task-specific layouts. User reference images and explicit style requirements take priority.
- Scope CSS to the tool root. Use local --tool-* variables and --q-primary; never change App-wide colors, default_* or global component selectors from generated tools.
- Use form, list/detail, file, analytics or media skeletons as appropriate. Do not force all tools into a monochrome compact form.
- Pick density deliberately. External labels with 36px controls are the default; dense tables and larger media controls are valid choices.
- Show meaningful states, keyboard focus and readable contrast. Icon-only actions have tooltips.
- Keep the built-in file selector, results and job lifecycle rather than reimplementing them.
- Prevent page overflow; tables and editors may have their own scroll area.

## Runtime Robustness

- Use the documented component APIs, not guessed lifecycle methods. `ToolResults()` renders immediately in the current UI container; it has no `mount()`. Call `results.refresh()` after publishing outputs. `ui.echart(...).options` is a read-only property: mutate the options dictionary in place and call `chart.update()` instead of assigning a new dictionary.
- During repairs, read current tool code/revision first, then query read_tool_logs for the approved failure’s actual exception message and traceback; paginate/search logs and query component APIs only as needed. An exception type alone does not identify the root cause; do not claim a cause that the evidence does not establish.

- Use type annotations for helper functions and classes.
- Add docstrings where they clarify non-obvious behavior.
- Wrap data access and user-triggered operations with friendly `ui.notify` errors.
- Use pagination for large datasets.
- Move blocking I/O to `run.io_bound` and CPU-heavy work to `run.cpu_bound`.
- Keep mutable filters, rows, selections, and busy state private to the tool instance.
- Implement initial/loading, empty, success, and failure states where applicable.
- Log technical exceptions; never expose raw exception text to users.
- Keep tool configuration local to the tool file or its own files under `~/.calabash`; validate string conversions and never log secret values.
- Complex tools may use classes for business state, but `main` remains a top-level function.

## File Workflow Contracts

- Instantiate `ToolFileInput`, `ToolResults`, `ToolJobs` and `ToolJobStatus` per tool page, never as module globals. UI components must not be created inside I/O workers.
- File selection appends and deduplicates; remove/clear only detach draft references. Show unavailable states and allow explicit reselect without rewriting historical attachments. Capture `inputs.freeze()` once per new run, unlock in finally including initialization errors, and bind input/parameter locking to `jobs.running` for retries too. Retry the original snapshot, never later draft edits; cancelled work stays locked until the active handler finishes.
- `inputs.paths` contains strings. Capture the validated list in the start callback, then pass `Path(path)` values to business I/O. Do not hardcode a user's attachment paths.
- Call `results.start_run()` once per new execution, not in each item or on failed-item retry. Use `await run.io_bound(results.outputs.write, filename, writer)` and refresh results back in the UI callback.
- Writer receives a private Path and writes only there; do not overwrite sources or build a custom arbitrary-path download route. History ownership comes from the page shell, not the tool's own SQL queries.
- Use async per-item handlers with `ToolJobStatus.run`. Guard new starts with `jobs.running`, including while the component's failed-item retry is active.
- Cancellation stops further scheduling, not an in-flight blocking writer. Result history survives refresh/restart; task progress and arbitrary form state do not.

## Pre-Preview Checklist

- Icon-only buttons have tooltips; shared component controls are preserved.
- Root layout is shell-compatible and appropriate for the task.
- Control density and hierarchy match the task; labels and actions are aligned without clipping.
- Theme and chart colors are intentional, readable, and scoped to the tool.
- Tool-local choices use `ui.select` or similar ordinary NiceGUI controls.
- Local configuration is handled deliberately and is not read during module import when failure would prevent the tool page from rendering.
- Blocking operations do not run on the NiceGUI event loop.
- Controls recover after failure and duplicate submissions are prevented.
- The selected tool skeleton matches the requested workflow.
- `main` is top-level, with no standalone run guard or ui.run().
- Error handling and user-facing notifications are present.
- Large data views are paginated.
- For file tools: check a failed sibling, failed-only retry, cancellation, history restoration and unchanged source files using synthetic data.
- `validate-tool.py` rejects recognized page helpers instantiated at import time, including imported aliases. It does not prove all execution paths, worker/UI separation or native permissions are correct; a static pass is not runtime validation.
