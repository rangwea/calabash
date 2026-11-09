/** Bundled tool components. Business IO stays behind ToolSDK, never the host bridge. */
import { Component, type ReactNode, useCallback, useEffect, useRef, useState } from 'react'
import { Alert, Button, Progress, Space, Tag } from 'antd'
import type { EChartsOption } from 'echarts'
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
export function CalabashResults() {
  const { value: files } = usePolling(() => request<ToolFile[]>('/results'), [] as ToolFile[])
  if (!files.length) return null
  return <details style={{ marginBlock: 12, fontSize: 13 }}><summary>结果文件 · Results ({files.length})</summary>{files.map(file => <div key={file.id} style={{ paddingBlock: 6 }}><a href={'/api/sdk/results/' + encodeURIComponent(file.id)} download={file.name}>{file.name}</a></div>)}</details>
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
