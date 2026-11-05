# Typed local API contracts

Use typed API methods for new JSON business operations. Define Pydantic models in `backend/main.py` or unique-name models under `backend/`. Register normal FastAPI routes inside `setup(app, sdk)` with a literal `operation_id` and `response_model`. The compiler derives `@calabash/api` using Python AST only, without importing or executing backend code. Both preview and production builds use the same generated file outside the source bundle. Source edits regenerate it. Generated declarations and clients are excluded from source exports.

```python
import sqlite3
from contextlib import closing
from pydantic import BaseModel, ConfigDict, Field

class CustomerInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=100)

class Customer(CustomerInput):
    id: int

def setup(app, sdk):
    database = sdk.data_dir / 'customers.sqlite'
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute('CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL)')

    @app.post('/api/customers', operation_id='create_customer', response_model=Customer)
    def create_customer(payload: CustomerInput):
        with closing(sqlite3.connect(database)) as connection, connection:
            cursor = connection.execute('INSERT INTO customers(name) VALUES (?)', (payload.name,))
            return {'id': cursor.lastrowid, 'name': payload.name}
```

```ts
import {api, type Customer} from '@calabash/api'
const customer: Customer = await api.create_customer({body: {name: 'Example'}})
```

Each generated method returns `Promise<ResponseType>`. Supply `params` for named path placeholders, `query` for scalar query values, `body` for one Pydantic input model and optional `signal` for AbortController. Query arguments with Python defaults are optional. Model defaults make input fields optional; nullable fields still require a value unless they have a default. Avoid copying interfaces manually or silencing mismatches with casts, any or ts-ignore.

Supported static annotations are str, int, float, bool, None, optional/union types, list[T], dict[str,T], Literal values, and named Pydantic models with inheritance. Use direct named models for request bodies. Use original Python field names without serialization aliases or exclusions. Scalar query parameters use primitives, nullable primitives or Literal. Request and Response injected arguments are omitted from the client. Unsupported annotations produce a local API_CONTRACT diagnostic rather than guessed types. Keep model names unique across backend files. Complex custom serializers, dynamic routing and dependency-injected models need an explicit typed facade using these supported annotations.

Call read_api_contract(project,name) for a bounded operation summary and operation names. Pass operation to expand model declarations. Build with check_tool_build and fix the reported frontend/backend file. Build success verifies static agreement, not actual business behavior.

Use SQLite transactions for concurrent create/edit/delete and multi-record changes. sdk.write_json atomically replaces one JSON document; a separate read then write is not a cross-process transaction. Keep tool data in sdk.data_dir. Reopening and republishing must preserve it.

FastAPI validates request bodies and declared response models at runtime. The host records an operation ID, templated route, request ID, exception type, backend frames and validation field locations in the current tool run log. Request bodies, query values and validation input values are excluded. Users see a friendly message. On confirmed repair, use read_tool_logs with the current approved run and a literal operation ID or request ID to locate the failure. Saved/static-valid is not runtime-verified. Do not trigger writes, deletes or exports through diagnostic interaction without current user confirmation.

Catch errors in the frontend, display the host-provided message and restore loading state in finally. Disable repeated submissions while pending. Provide clear empty/filter states and reload only the affected data after successful writes. Never automatically retry a mutation. JSON endpoints return their declared response object; delete may return an explicit result model or use HTTP 204 with no response body.
