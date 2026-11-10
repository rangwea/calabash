# Office Action protocol v1

Prefer a built-in action over regenerating Excel/Word processing code. Query `read_action_api` without action_id for the catalog, then with one exact ID for its input/output JSON Schema and limits. Discovery never reads user files or executes business work. Agent cannot execute actions through calabash_tool. Do not invent third-party action packages or installation operations. ai.text is available only through explicit host confirmation; the authoring Agent cannot approve or execute it.

## Shared execution contract

- Stable action ID, action_version=1 and protocol_version=1. Unknown versions/actions fail explicitly; no aliases or fallback execution.
- Input references are current ToolSDK selected file IDs only, never arbitrary filesystem paths. Action output_name is a plain filename. Source files are immutable; all actions create new results via the existing output store.
- Built-in file actions declare read_selected_files/create_result_files permissions, no network and no input overwrites. ai.text has the separate confirmation boundary described below. This is the built-in execution policy, not a sandbox for arbitrary Python tools or third-party plugins.
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

For Word batches, a Python tool route may call sdk.actions.start_batch('office.word.fill_template', [{"template_id": template_id, "values": row} for row in records]) using explicit template IDs and values derived from user-confirmed data. Do not read arbitrary attachments or automatically execute a document batch during tool creation. Verify outputs with synthetic fixtures; compilation is not business acceptance. AI processing uses the separate ai.text authorization flow below.

## ai.text

Use officeActions.start('ai.text', parameters) only from a user business operation. task is summarize, classify, extract, translate or generate; text is the exact bounded content to propose sending (up to 20,000 characters). translate requires language; classify requires 2–30 distinct labels; extract requires fields mapping up to 20 names to string/number/boolean. Other tasks must not include unrelated language/labels/fields. output_name is a plain stem, not a path. No model ID, URL, API key, arbitrary tool list or system prompt is accepted from tools.

The trusted host shows a compact confirmation card outside the iframe, with source, expandable exact text/requirements and a DSH model picker. It remembers only the selected provider/model identity, never consent or request content. Every request still requires an explicit Confirm and process click. Every request requires separate confirmation. The tool cannot approve by sending confirmed=true. Model connections remain in DSH. The first version accepts one AI request per batch, with a 2,048 output-token and 120-second host limit. Text is removed from live job parameters after completion or cancellation. No chat history, attachments or logs are appended. No external model call is made before confirmation. A local-model connection may remain local; do not claim all models are cloud services.

Progress and stop use CalabashJobStatus. Text results are .txt, validated classification/extraction results are .json, delivered through CalabashResults. Mount CalabashResults in AI tools: it automatically displays the current successful ai.text output inline as plain text or scalar fields, with Copy and Download. Do not require users to download a file before reading the result; do not duplicate result fetching or render model HTML. Older files remain downloadable. A submitted request is not a completed result. JSON must have exactly the expected keys and scalar types; invalid/truncated/tool-call outputs fail, with no silent repair call or automatic retry. Stop revokes late output before publication. Refresh/source changes and ten-minute expiry invalidate approval. Results may be fetched through the tool's own result IDs for escaped text display; never render model text as HTML or executable instructions.

Built-in file actions remain offline. AI requests declare send_confirmed_text_to_selected_model permission and model-dependent network access; this is not a permission grant to arbitrary tool code or third-party plugins. User-enabled DSH extensions remain trusted code. Tests use synthetic models only.
