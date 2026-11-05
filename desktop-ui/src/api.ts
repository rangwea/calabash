import { requestMessage } from './request_errors.mjs'

export async function api<T = any>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  headers.set('X-Calabash-Request', 'workspace')
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  let response: Response
  try { response = await fetch('/api/workspace' + path, { ...options, headers }) }
  catch { throw new Error('连接暂时中断，请稍后重试') }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(requestMessage(response.status, body.detail))
  }
  try { return await response.json() }
  catch { throw new Error('暂时未能完成操作，请稍后重试') }
}

export const json = (method: string, value?: unknown): RequestInit => ({ method, ...(value === undefined ? {} : { body: JSON.stringify(value) }) })
