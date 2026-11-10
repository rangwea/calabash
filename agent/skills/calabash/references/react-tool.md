# React tool contract

A tool contains tool.json (format calabash-react-tool, version 1), frontend/App.tsx (default-exported React function component), and backend/main.py (setup(app,sdk)). Use the host starter; do not generate package.json, Vite config, index.html or a server bootstrap.

Use React hooks, TypeScript and Ant Design. Import Ant Design from antd, icons from @ant-design/icons, SDK components from @calabash/ui, typed API methods from @calabash/api. Use relative files inside frontend/ for focused components and styles. No network imports or installing dependencies. Only bundled libraries are available. Read read_component_api before using an unfamiliar prop. Do not write Vue templates or Element Plus components.

Use explicit types for table rows, controlled inputs and action results. Keys are stable business identities, not array positions. Use loading/disabled states and prevent duplicate submissions. Each effect cleans timers, event handlers, charts and outstanding observers. Avoid arbitrary async effects without teardown.

Call read_api_contract for Python Pydantic operation_id contracts. Use generated types and api methods; do not mirror backend types by hand. Prefer minimal local component state; persist business state through Python ToolSDK. A UI remount is not business execution authorization.

CalabashFiles exposes onChange(files), CalabashResults shows current AI Action results inline with copy/download, keeps other files compact and shows no empty placeholder, CalabashJobStatus exposes safe stop, CalabashChart accepts ECharts option and height. Import them explicitly from @calabash/ui. A chart is disposed on unmount. Files and outputs use the SDK, never direct host filesystem access.

The host installs ConfigProvider and Ant Design App context. For messages/modal confirmation use App.useApp() inside the tool. Keep styles scoped to a tool root class. Layouts use min-width:0, responsive grids and bounded scroll regions. Never override host/DSH styles. The iframe is an independent origin.

Use check_tool_build after edits and read_build_diagnostics for current-source evidence. Passing TypeScript/build checks is not business verification. User opens preview, refreshes backend changes and explicitly saves to the tool list.
