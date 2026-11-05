/** Host-owned JSON transport. Generated API methods supply request/response types. */
export interface RequestOptions {
  params?: Record<string, string | number>
  query?: Record<string, string | number | boolean | null | undefined>
  body?: unknown
  signal?: AbortSignal
}

export async function request<T>(method: string, path: string, options: RequestOptions): Promise<T> {
  const route = path.replace(/\{([^}]+)\}/g, (_, name: string) => {
    const value = options.params?.[name]
    if (value === undefined) throw new Error('请补全所需内容后重试 / Please complete the required entries.')
    return encodeURIComponent(String(value))
  })
  const url = new URL(route, window.location.origin)
  for (const [name, value] of Object.entries(options.query ?? {})) {
    if (value !== undefined && value !== null) url.searchParams.set(name, String(value))
  }
  const response = await fetch(url.pathname + url.search, {
    method, signal: options.signal,
    headers: options.body === undefined ? undefined : {'Content-Type': 'application/json'},
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })
  // The injected runtime guard translates unsuccessful responses and reports
  // failures to the host. Preserve its safe, localized error message.
  if (!response.ok) throw new Error('工具未能完成操作，请重试 / The tool could not complete this action. Please retry.')
  if (response.status === 204) return undefined as T
  try {
    return await response.json() as T
  } catch {
    window.parent.postMessage({kind: 'calabash-tool-issue'}, '*')
    throw new Error('工具返回的结果暂时无法使用，请让 AI 帮你修复 / The result is unavailable. Ask AI to fix this tool.')
  }
}
