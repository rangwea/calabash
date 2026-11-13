# Typed local API contracts

Use typed API methods for new JSON business operations. Define Pydantic models in `backend/main.py` or unique-name models under `backend/`. Register normal FastAPI routes inside `setup(app, sdk)` with a literal `operation_id` and `response_model`. The compiler derives `@calabash/api` using Python AST only, without importing or executing backend code. Both preview and production builds use the same generated file outside the source bundle. Source edits regenerate it. Generated declarations and clients are excluded from source exports.

```python
from pydantic import BaseModel, ConfigDict, Field

class CustomerInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=100)

class Customer(CustomerInput):
    id: int

def setup(app, sdk):
    with sdk.database(write=True) as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL)')

    @app.post('/api/customers', operation_id='create_customer', response_model=Customer)
    def create_customer(payload: CustomerInput):
        with sdk.database(write=True) as connection:
            cursor = connection.execute('INSERT INTO customers(name) VALUES (?)', (payload.name,))
            return {'id': cursor.lastrowid, 'name': payload.name}
```

```ts
import {api, type Customer} from '@calabash/api'
const customer: Customer = await api.create_customer({body: {name: 'Example'}})
```

Each generated method returns `Promise<ResponseType>`. Supply `params` for named path placeholders, `query` for scalar query values, `body` for one Pydantic input model and optional `signal` for AbortController. Query arguments with Python defaults are optional. Model defaults make input fields optional; nullable fields still require a value unless they have a default. Avoid copying interfaces manually or silencing mismatches with casts, any or ts-ignore.

Supported static annotations are str, int, float, bool, None, optional/union types, list[T], dict[str,T], Literal values, and named Pydantic models with inheritance. Use direct named models for request bodies. Use original Python field names without serialization aliases or exclusions. Scalar query parameters use primitives, nullable primitives or Literal. Request and Response injected arguments are omitted from the client. Unsupported annotations produce a local API_CONTRACT diagnostic rather than guessed types. Keep model names unique across backend files. Complex custom serializers, dynamic routing and dependency-injected models need an explicit typed facade using these supported annotations.

Call read_api_contract(project,name) for a bounded summary of the current operation names and declarations. It returns the full current contract and has no per-operation expansion argument. Build with check_tool_build and fix the reported frontend/backend file. Build success verifies static agreement, not actual business behavior.

Store structured business data in real tables in the tool-owned tools/<project>/<tool>/data.sqlite under sdk.data_dir. Use `with sdk.database(write=True) as db:` for schema initialization and writes, and `with sdk.database() as db:` for read-only queries. The SDK opens one connection per context, enables foreign keys, waits up to 15 seconds for locks, uses BEGIN IMMEDIATE for writes, commits on success, rolls back on exceptions and always closes. Rows support column-name access. Bind SQL values with placeholders, never interpolate user values. Complete a read-modify-write operation in the SAME write context; separate contexts are not one transaction. Keep transactions short; process documents, await models and do network IO outside the transaction. Do not share connections between threads/processes, await inside a context, nest contexts or manually commit/rollback/executescript. Run blocking database helpers through sdk.io from async routes; synchronous FastAPI routes can use the context directly.

Initialize current tables using CREATE TABLE IF NOT EXISTS inside setup; do not drop tables, add historical migration machinery or reset data on refresh/save. Reserve `_calabash_` tables for the SDK. Settings use `sdk.get_setting(key, default)` and `sdk.set_setting(key, value)` with JSON-compatible values in the same SQLite database; settings are not a substitute for business tables. Do not place connections in module globals, persist credentials in settings, open databases by frontend-supplied paths or expose SQL over HTTP. Old JSON data is left untouched, never imported or deleted automatically. There are no read_json/write_json compatibility methods. Files and results still use ToolSDK file APIs, not database blobs. Draft and published versions share the same tool data directory: preview writes affect real tool data, so tests and schema experiments must use synthetic tool identities. Reopening and republishing preserve stored data. The host-owned data.sqlite, its journal/WAL/SHM sidecars and inputs/outputs directories are excluded from source reads, source revisions, builds and exported tool ZIPs; never write them through authoring operations.

FastAPI validates request bodies and declared response models at runtime. The host records an operation ID, templated route, request ID, exception type, backend frames and validation field locations in the current tool run log. Request bodies, query values and validation input values are excluded. Users see a friendly message. The current DSH adapter does not expose runtime-log queries; ask the user for the observed failure rather than inventing a tool call. Saved/static-valid is not runtime-verified. Do not trigger writes, deletes or exports through diagnostic interaction without current user confirmation.

Catch errors in the frontend, display the host-provided message and restore loading state in finally. Disable repeated submissions while pending. Provide clear empty/filter states and reload only the affected data after successful writes. Never automatically retry a mutation. JSON endpoints return their declared response object; delete may return an explicit result model or use HTTP 204 with no response body.
