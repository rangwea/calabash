# Office Action protocol v1

Prefer a built-in action over regenerating Excel/Word processing code. Query `read_action_api` without action_id for the catalog, then with one exact ID for its input/output JSON Schema and limits. Discovery never reads user files or executes business work. Agent cannot execute actions through calabash_tool. Do not invent AI/network actions, third-party action packages or installation operations.

## Shared execution contract

- Stable action ID, action_version=1 and protocol_version=1. Unknown versions/actions fail explicitly; no aliases or fallback execution.
- Input references are current ToolSDK selected file IDs only, never arbitrary filesystem paths. Action output_name is a plain filename. Source files are immutable; all actions create new results via the existing output store.
- All current actions declare read_selected_files/create_result_files permissions, no network, no input overwrites. This is the built-in execution policy, not a sandbox for arbitrary Python tools or third-party plugins.
- User triggers the business operation in the tool. `sdk.actions.start(id, parameters)` or `sdk.actions.start_batch(id, [parameters, ...])` validates and submits to the SAME ToolJobs queue. Use CalabashJobStatus for progress and safe cancellation, CalabashResults for outputs. Cancellation finishes the current action/output before stopping later items, never interrupts a file writer. Do not automatically retry a mutation. At most 20 requests in a batch; only one batch per tool.
- No public synchronous bypass. For custom typed API wrappers, define Pydantic request/response models as usual and call sdk.actions.start inside the route. Do not claim submission equals completion.
- SDK HTTP: GET /api/sdk/actions; GET /api/sdk/actions/{id}; POST /api/sdk/actions/{id} with {protocol_version:1, action_version:1, parameters:{...}}. GET /api/sdk/action-runs returns current batch IDs, states, safe results/errors. These endpoints are authenticated by the same tool origin/session policy; they are not host authoring endpoints.
- Each completed result contains invocation_id, action_id, versions, output file IDs/names and numeric counts. Failures have a bounded error category and friendly message. Local run logs record identity, timing, category and exception type, not parameter values, filenames or document contents. Current batch state is in-memory; generated file history persists through ToolSDK. Restart does not rerun accepted actions or restore interrupted work automatically.

## office.excel.process

.xlsx only; first sheet by default or one named sheet in every input. First row must have unique nonempty text headers. Merges column union; optional strip_text/drop_empty_rows, rename_columns, columns (AFTER rename), deduplicate_by (AFTER selection, first row wins). No deduplication if keys are empty. Returns read_rows, written_rows, empty_rows, duplicate_rows. Creates a data-only workbook, not a formatting-preserving or formula-calculation engine. Formula/error cells fail explicitly instead of silently using missing cached values. Literal text beginning with '=' is written as text. Limits are returned by discovery; large files must not silently truncate.

## office.word.fill_template

.docx only. Replaces literal {{field}} or {{ field }} using values:dict[str,str]. Field names permit letters/numbers/underscore/dot/hyphen (including Chinese). Values are bounded single-line plain text, never evaluated. Handles placeholders split across text runs, body paragraphs, nested tables and existing headers/footers. Preserves surrounding run formatting; inserted value inherits the starting text run's formatting. Every placeholder must have a value, extra values are allowed. No expressions, loops, images, rich text or repeating table rows. Reject malformed templates/missing values before result delivery. Values containing braces remain literal, never trigger recursive expansion.

## Tool integration

Use the typed `officeActions` helper from @calabash/ui for built-in actions; do not duplicate its parameter types. Example:

```tsx
import { officeActions, CalabashFiles, CalabashJobStatus, CalabashResults } from '@calabash/ui'
// In a user-click handler, with pending/error guards:
await officeActions.start('office.excel.process', {input_ids: files.map(file => file.id), deduplicate_by: ['编号']})
```

For Word batches, a Python tool route may call sdk.actions.start_batch('office.word.fill_template', [{"template_id": template_id, "values": row} for row in records]) using explicit template IDs and values derived from user-confirmed data. Do not read arbitrary attachments or automatically execute a document batch during tool creation. Verify outputs with synthetic fixtures; compilation is not business acceptance. Future AI Actions must declare outbound-content authorization and model connection ownership separately; v1 has no model action.
