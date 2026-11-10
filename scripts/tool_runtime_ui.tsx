/** Bundled tool components. Business IO stays behind ToolSDK, never the host bridge. */
import { Component, type ReactNode, useCallback, useEffect, useRef, useState } from 'react'
import { Alert, Button, Progress, Space, Tag } from 'antd'
import type { EChartsOption } from 'echarts'
import { readAIResult, resultFields } from './runtime-ai-result'
export interface ToolFile { id: string; name: string; status?: string }
interface JobState { status: string; progress: number; running: boolean }
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch('/api/sdk' + path, options)
  if (!response.ok) throw new Error('暂时无法完成，请重试 · Unable to complete. Please retry.')
  return response.json() as Promise<T>
}
function usePolling<T>(load: () => Promise<T>, initial: T) {
  const [value, setValue] = useState(initial), [error, setError] = useState('')
  const current = useRef(load); current.current = load
  const refresh = useRef<() => Promise<void>>(async () => {})
  useEffect(() => {
    let disposed = false, pending = false
    const update = async () => {
      if (pending || disposed) return
      pending = true
      try { const result = await current.current(); if (!disposed) { setValue(result); setError('') } }
      catch { if (!disposed) setError('状态暂时不可用，请重试 · Unable to refresh status.') }
      finally { pending = false }
    }
    refresh.current = update; void update()
    const timer = setInterval(() => { void update() }, 1000)
    return () => { disposed = true; clearInterval(timer) }
  }, [])
  return { value, error, refresh: useCallback(() => refresh.current(), []) }
}
export function themeTokens() {
  const css = getComputedStyle(document.documentElement)
  return { colorPrimary: css.getPropertyValue('--calabash-primary').trim() || '#0f6cbd', colorBgLayout: css.getPropertyValue('--calabash-background').trim() || '#f5f7fa', colorText: css.getPropertyValue('--calabash-text').trim() || '#263445', borderRadius: parseInt(css.getPropertyValue('--calabash-radius')) || 8, fontSize: 14 }
}
export function CalabashFiles({ onChange }: { onChange?: (files: ToolFile[]) => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [pending, setPending] = useState(false), [error, setError] = useState('')
  const state = usePolling(async () => ({ files: await request<ToolFile[]>('/inputs'), job: await request<JobState>('/status') }), { files: [] as ToolFile[], job: { running: false, status: 'idle', progress: 0 } })
  const frozen = pending || state.value.job.running
  const act = async (action: () => Promise<unknown>) => {
    if (frozen) return
    setPending(true); setError('')
    try { await action(); const files = await request<ToolFile[]>('/inputs'); onChange?.(files); await state.refresh() }
    catch { setError('无法更新文件，请重试 · Unable to update files.') }
    finally { setPending(false) }
  }
  return <section style={{ display: 'grid', gap: 10, marginBlock: 12 }}>
    <input ref={input} type="file" multiple hidden disabled={frozen} onChange={event => { const files = Array.from(event.target.files || []); event.target.value = ''; void act(async () => { for (const file of files) { const form = new FormData(); form.append('file', file); await request('/inputs', { method: 'POST', body: form }) } }) }} />
    <Space><Button disabled={frozen} onClick={() => input.current?.click()}>选择 / 追加文件 · Add files</Button><Button disabled={frozen || !state.value.files.length} onClick={() => { void act(async () => { for (const file of state.value.files) await request('/inputs/' + encodeURIComponent(file.id), { method: 'DELETE' }) }) }}>清空 · Clear</Button></Space>
    <Space wrap>{state.value.files.map(file => <Tag key={file.id} closable={!frozen} onClose={event => { event.preventDefault(); void act(() => request('/inputs/' + encodeURIComponent(file.id), { method: 'DELETE' })) }}>{file.name}{file.status ? ' · ' + file.status : ''}</Tag>)}</Space>
    {(error || state.error) && <Alert type="error" title={error || state.error} showIcon />}
  </section>
}
/** Automatically shows current AI Action outputs; ordinary files remain compact. */
export function CalabashResults() {
  const { value } = usePolling(async () => {
    const [files, runs] = await Promise.all([request<ToolFile[]>('/results'), officeActions.runs()])
    const ai = runs.filter(run => run.action_id === 'ai.text' && run.status === 'succeeded').flatMap(run => run.result?.outputs || [])
    return { files, ai }
  }, { files: [] as ToolFile[], ai: [] as ToolFile[] })
  const others = value.files.filter(file => !value.ai.some(result => result.id === file.id))
  return <section className="calabash-results" style={{ minWidth: 0 }}>
    {value.ai.map(file => <CalabashAIResult key={file.id} file={file} />)}
    {others.length > 0 && <details style={{ marginBlock: 12, fontSize: 13 }}><summary>结果文件 · Results ({others.length})</summary>{others.map(file => <div key={file.id} style={{ paddingBlock: 6 }}><a href={'/api/sdk/results/' + encodeURIComponent(file.id)} download={file.name}>{file.name}</a></div>)}</details>}
  </section>
}
function CalabashAIResult({ file }: { file: ToolFile }) {
  const [text, setText] = useState<string | null>(null), [error, setError] = useState(''), [copied, setCopied] = useState(false)
  const [retry, setRetry] = useState(0)
  const fallback = useRef<HTMLTextAreaElement>(null)
  useEffect(() => {
    const controller = new AbortController(); setText(null); setError(''); setCopied(false)
    void fetch('/api/sdk/results/' + encodeURIComponent(file.id), { signal: controller.signal }).then(readAIResult).then(value => { if (!controller.signal.aborted) setText(value) }).catch(() => { if (!controller.signal.aborted) setError('暂时无法显示结果，可以重试或下载查看 · Unable to display. Retry or download.') })
    return () => controller.abort()
  }, [file.id, retry])
  const copy = async () => {
    if (text === null) return
    try { await navigator.clipboard.writeText(text); setCopied(true) }
    catch {
      // Cross-origin tool frames may have Clipboard API disabled. User click only;
      // copy never requests clipboard read permission or expands iframe access.
      const field = fallback.current
      if (!field) return
      field.hidden = false; field.focus(); field.select()
      try { if (document.execCommand('copy')) { setCopied(true); field.hidden = true } }
      catch { /* Leave selected plain text available for manual copy. */ }
    }
  }
  const fields = text !== null && file.name.endsWith('.json') ? resultFields(text) : []
  return <section className="calabash-ai-result" aria-label="AI 处理结果 · AI result" style={{ marginBlock: 12, padding: 16, border: '1px solid var(--calabash-border, #dce3e9)', borderRadius: 8, minWidth: 0, overflowWrap: 'anywhere' }}>
    <Space wrap style={{ display: 'flex', justifyContent: 'space-between' }}><strong>处理结果 · Result</strong><Space><Button disabled={text === null} onClick={() => { void copy() }}>{copied ? '已复制 · Copied' : '复制 · Copy'}</Button><Button href={'/api/sdk/results/' + encodeURIComponent(file.id)} download={file.name}>下载 · Download</Button></Space></Space>
    {text === null && !error && <p role="status">正在显示结果… · Loading result…</p>}
    {error && <Alert type="warning" title={error} action={<Button onClick={() => setRetry(value => value + 1)}>重试 · Retry</Button>} />}
    {fields.length ? <dl style={{ display: 'grid', gridTemplateColumns: 'minmax(70px, 1fr) minmax(0, 3fr)', gap: 10, maxHeight: 360, overflow: 'auto' }}>{fields.map(([name,value]) => <div key={name} style={{ display: 'contents' }}><dt style={{ color: '#6b7787' }}>{name}</dt><dd style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{value}</dd></div>)}</dl> : text !== null && <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: 360, overflow: 'auto', font: 'inherit', lineHeight: 1.6 }}>{text}</pre>}
    <textarea ref={fallback} hidden readOnly value={text || ''} aria-label="可选择复制的结果 · Selectable result" style={{ width: '100%', minHeight: 100 }} />
  </section>
}
export function CalabashJobStatus() {
  const { value: job } = usePolling(async () => {
    const [status, runs] = await Promise.all([request<JobState>('/status'), officeActions.runs()])
    return { ...status, actionError: runs.find(run => run.status === 'failed')?.error?.message || '' }
  }, { status: 'idle', running: false, progress: 0, actionError: '' })
  const [error, setError] = useState('')
  if (job.status === 'idle') return null
  return <section style={{ marginBlock: 12 }}><span role="status">{job.status}</span><Progress percent={Math.round(Math.max(0, Math.min(1, job.progress)) * 100)} />{job.running && <Button onClick={() => { void request('/cancel', { method: 'POST' }).catch(() => setError('停止请求未完成，请重试 · Please retry safe stop.')) }}>安全停止 · Stop safely</Button>}{(error || job.actionError) && <Alert type="error" title={error || job.actionError} />}</section>
}
export function CalabashChart({ option, height = '280px' }: { option: EChartsOption; height?: string }) {
  const element = useRef<HTMLDivElement>(null), latest = useRef(option)
  latest.current = option
  const chart = useRef<import('echarts').ECharts | null>(null)
  useEffect(() => {
    let disposed = false, observer: ResizeObserver | undefined
    void import('echarts').then(echarts => {
      if (disposed || !element.current) return
      chart.current = echarts.init(element.current); chart.current.setOption(latest.current)
      observer = new ResizeObserver(() => chart.current?.resize()); observer.observe(element.current)
    })
    return () => { disposed = true; observer?.disconnect(); chart.current?.dispose(); chart.current = null }
  }, [])
  useEffect(() => { chart.current?.setOption(option, true) }, [option])
  return <div ref={element} style={{ height, width: '100%', minWidth: 0 }} />
}

export class ToolErrorBoundary extends Component<{children: ReactNode}, {failed:boolean}> {
  state = {failed:false}
  static getDerivedStateFromError() { return {failed:true} }
  componentDidCatch(error: Error) { window.dispatchEvent(new ErrorEvent('error',{error,message:error.message})) }
  render() { return this.state.failed ? <Alert type="error" showIcon title="工具暂时无法显示 · Unable to display this tool" description="请让 AI 检查工具，修改后手动刷新。 · Ask AI to check the tool, then refresh manually." /> : this.props.children }
}
