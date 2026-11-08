/** Public DSH slots: tool workspace plus a conversation-scoped React preview tab. */
import type { Context } from '@deepseek-ai/cordis'
import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react'
import type { CSSProperties } from 'react'
import type { MainPanelId } from '@deepseek-ai/dsh-client-ui-layout/client'
import type {} from '@deepseek-ai/dsh-client-ui-renderer/client'
import type {} from '@deepseek-ai/dsh-client-ui-sidebar/client'
import type {} from '@deepseek-ai/dsh-client-ui-sidebar-right/client'
import type {} from '@deepseek-ai/dsh-client-locale/client'
import type {} from '@deepseek-ai/dsh-api-remotes/client'
import remote from '@calabash/harness-workspace/remote'
import type { RemoteResult } from '@deepseek-ai/dsh-typert-protocol'
import type {} from '@deepseek-ai/dsh-client-ui-input-trigger/client'
import type {} from '@deepseek-ai/dsh-api-session-controller/client'
import type {} from '@deepseek-ai/dsh-api-workspace-controller/client'
import type {} from '@deepseek-ai/dsh-client-ui-workspace/client'
import type { UseContextMenu } from '@deepseek-ai/dsh-client-ui-context-menu/client'
import css from './tools.module.css'
import { createOperations } from './operations.ts'
import { inspectArchive, exportArchive } from './library-transfer.ts'
import { registerUIStyles } from './ui-styles.tsx'
import type { UIPreset, ToolEntry, Preview, ToolTarget } from '../types.ts'
declare module '@deepseek-ai/dsh-client-ui-context-menu/client' { interface ContextMenuTargetMap { calabashTool: ToolEntry } }
const panel = 'calabash-tools' as MainPanelId
const tab = '@calabash/preview'
export const inject = ['slots', 'remote', 'layout', 'sidebarRight', 'sidebarRightTabs', 'locale', 'inputTriggers', 'sessions', 'uiWorkspace', 'workspaces', 'contextMenus']
const button: CSSProperties = { border: '1px solid #dce3e9', borderRadius: 6, padding: '6px 12px', background: '#fff', color: '#46596a', cursor: 'pointer', fontSize: 13 }
const row: CSSProperties = { display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }
type WorkspaceTab = ToolTarget & { url?: string; revision?: string }
const frame: CSSProperties = { width: '100%', height: '100%', minHeight: 0, border: 0, background: '#fff', flex: 1 }
function validPreview(value: Preview): Preview {
  const url = new URL(value.url)
  if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || !url.port || url.username || url.password) throw new Error('Invalid tool origin')
  return value
}
export async function apply(ctx: Context): Promise<void> {
  const dispose = await ctx.remote.$mount(remote)
  ctx.effect(() => () => dispose())
  ctx.inject(['remote.calabashWorkspace'], scope => install(scope))
}
function install(ctx: Context): void {
  const wire = ctx.remote.calabashWorkspace
  const unwrap = (result: RemoteResult<string>): string => { if (!result.ok) throw new Error('Tool operation failed'); return result.value }
  const operation = createOperations(wire, value => unwrap(value as RemoteResult<string>))
  const api = {
    list: async () => unwrap(await wire.list()),
    open: async (project: string, name: string) => operation('tools.open', { project, name }),
    close: async (project: string, name: string) => operation('tools.close', { project, name }),
    state: async (session: string) => unwrap(await wire.state(session)),
    preview: async (session: string, refresh: boolean) => operation('workspace.preview', { session, refresh }),
    publish: async (session: string, expected: string, replace: string, confirmed: boolean) => operation('workspace.publish', { session, expected, replace_revision: replace, confirmed }),
  }
  const library = async (action: string, args: Record<string, unknown>) => action === 'import'
    ? operation('library.action', { operation: action, arguments: args })
    : unwrap(await wire.library(action, JSON.stringify(args)))
  registerUIStyles(ctx, async () => JSON.parse(unwrap(await wire.uiPresets())) as UIPreset[])
  const copy = (zh: string, en: string) => ctx.locale.getSnapshot().active === 'zh' ? zh : en
  function useCopy() {
    useSyncExternalStore(listener => ctx.locale.subscribe(listener), () => ctx.locale.getSnapshot())
    return copy
  }
  function Tools({ useContextMenu }: { useContextMenu: UseContextMenu }) {
    const menus = useContextMenu()
    const t = useCopy()
    const [tools, setTools] = useState<ToolEntry[]>([])
    const [tabs, setTabs] = useState<WorkspaceTab[]>([])
    const [active, setActive] = useState('')
    const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
    const collapsed = tabs.length > 0 && sidebarCollapsed
    const [busy, setBusy] = useState(false)
    const [error, setError] = useState('')
    const [hostPending, setHostPending] = useState(0)
    const [query, setQuery] = useState('')
    const input = useRef<HTMLInputElement>(null)
    const actionLock = useRef(false)
    const [confirmation, setConfirmation] = useState<{ message: string; resolve: (accepted: boolean) => void } | null>(null)
    const ask = (message: string) => new Promise<boolean>(resolve => setConfirmation({ message, resolve }))
    const answer = (accepted: boolean) => { confirmation?.resolve(accepted); setConfirmation(null) }
    const key = (value: ToolTarget) => `${value.project}/${value.name}`
    const load = async () => { try { setTools(JSON.parse(await api.list()) as ToolEntry[]); setError('') } catch { setError(t('工具列表暂时不可用，请重试。', 'Unable to load tools. Please retry.')) } }
    useEffect(() => {
      let disposed = false, pending = false
      const update = async () => {
        if (pending) return
        pending = true
        try { const tasks = JSON.parse(unwrap(await wire.listTasks())) as {state:string}[]; if (!disposed) setHostPending(tasks.filter(task => task.state === 'queued' || task.state === 'running').length) }
        catch { /* A reconnect must not interrupt host work. */ }
        finally { pending = false }
      }
      void update(); const timer = setInterval(() => { void update() },1000)
      return () => { disposed = true; clearInterval(timer) }
    }, [])
    const [restored, setRestored] = useState(false)
    useEffect(() => {
      void load()
      void wire.loadWorkspace().then(result => {
        const saved = JSON.parse(unwrap(result)) as { tabs: ToolTarget[]; active: string; collapsed: boolean; query: string }
        setTabs(saved.tabs); setActive(saved.active); setSidebarCollapsed(saved.collapsed); setQuery(saved.query)
        setRestored(true)
      }).catch(() => { setError(t('工作区暂时无法恢复，请稍后重试。', 'Unable to restore the workspace. Please retry later.')) })
    }, [])
    useEffect(() => {
      if (!restored) return
      const timer = setTimeout(() => { void wire.saveWorkspace(JSON.stringify({ tabs: tabs.map(({project,name}) => ({project,name})), active, collapsed: sidebarCollapsed, query })).then(result => { if (!result.ok) setError(t('工作区暂时未能保存。', 'Unable to save the workspace.')) }).catch(() => {}) }, 200)
      return () => clearTimeout(timer)
    }, [tabs, active, sidebarCollapsed, query, restored])
    const open = async (tool: ToolEntry) => {
      const id = key(tool)
      if (tabs.some(value => key(value) === id && value.url)) { setActive(id); return }
      if (busy) return
      setBusy(true); setError('')
      try { const value = validPreview(JSON.parse(await api.open(tool.project, tool.name)) as Preview); setTabs(previous => previous.some(tab => key(tab) === id) ? previous.map(tab => key(tab) === id ? value : tab) : [...previous, value]); setActive(id) }
      catch { setError(t('工具暂时未能打开，请重试。', 'Unable to open this tool. Please retry.')) }
      finally { setBusy(false) }
    }
    const close = async (tool: WorkspaceTab) => {
      if (busy) return
      setBusy(true)
      try { await api.close(tool.project, tool.name); setTabs(previous => previous.filter(value => key(value) !== key(tool))); if (active === key(tool)) setActive('') }
      catch { setError(t('正在安全停止，请等待当前文件处理完成后再关闭。', 'Safe stop requested. Wait for the current file to finish, then close again.')) }
      finally { setBusy(false) }
    }
    const act = async (action: () => Promise<void>, failure: string) => {
      if (actionLock.current || busy) return
      actionLock.current = true; setBusy(true); setError('')
      try { await action() } catch { setError(failure) }
      finally { actionLock.current = false; setBusy(false) }
    }
    const chat = (tool: ToolEntry) => act(async () => {
      const args = { project: tool.project, name: tool.name }
      const existing = JSON.parse(await library('conversation', { ...args, session: null })) as string | null
      // A new session is created without sending a model request or copying source into chat.
      const destination = ctx.workspaces.list.getSnapshot().items[0] ?? await ctx.workspaces.initializeDefault()
      if (!destination) throw new Error('A workspace is required')
      const session = existing ?? await ctx.sessions.create({ workspaceId: destination.workspaceId })
      await library('conversation', { ...args, session })
      ctx.uiWorkspace.openSession(session as Awaited<ReturnType<typeof ctx.sessions.create>>)
    }, t('暂时无法打开工具对话，请重试。', 'Unable to open the tool conversation. Please retry.'))
    const remove = (tool: ToolEntry) => act(async () => {
      if (!await ask(t(`删除“${tool.title || tool.name}”？工具将从列表移除，对话和交付文件会保留。`, `Delete “${tool.title || tool.name}”? Conversations and result files will be kept.`))) return
      await library('delete', { project: tool.project, name: tool.name, revision: tool.revision, confirmed: true }); await load()
    }, t('无法删除，请先关闭工具，再刷新列表重试。', 'Unable to delete. Close the tool, refresh the list and retry.'))
    const download = (tool: ToolEntry) => act(async () => {
      const result = await exportArchive(library, tool.project, tool.name)
      const url = URL.createObjectURL(result.blob)
      const link = document.createElement('a'); link.href = url; link.download = result.name
      document.body.appendChild(link); link.click(); link.remove()
      setTimeout(() => URL.revokeObjectURL(url), 60000)
    }, t('导出失败，请刷新列表后重试。', 'Unable to export. Refresh the list and retry.'))
    const upload = (file: File) => act(async () => {
      const archive = await inspectArchive(library, file)
      try {
        const title = archive.manifest.title || archive.manifest.name
        const message = archive.revision
          ? t(`已有同名工具“${title}”，确认覆盖？请先关闭该工具。`, `Replace the existing tool “${title}”? Close it first.`)
          : t(`导入工具“${title}”？导入不会运行工具或安装依赖。`, `Import “${title}”? Importing will not run it or install dependencies.`)
        if (!await ask(message)) return
        await library('import', { ticket: archive.ticket, revision: archive.revision, confirmed: true }); await load()
      } finally { await library('discard', { ticket: archive.ticket }).catch(() => undefined) }
    }, t('无法导入。请检查 ZIP 是否为工具包；覆盖前请先关闭同名工具。', 'Unable to import. Check that this ZIP is a tool bundle and close any existing tool before replacing it.'))
    const iconButton = (label: string, glyph: string, action: () => void) => <button type="button" title={label} aria-label={label} disabled={busy} onClick={action} className={css.iconButton}><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={glyph} /></svg></button>
    useEffect(() => ctx.contextMenus.register({
      id: 'calabash.tool-actions', target: 'calabashTool', order: 0,
      resolve: tool => [
        { id: 'conversation', label: t('工具对话', 'Tool conversation'), disabled: busy, run: () => chat(tool) },
        { id: 'export', label: t('导出 ZIP', 'Export ZIP'), disabled: busy, run: () => download(tool) },
        { id: 'delete', label: t('删除工具', 'Delete tool'), disabled: busy, danger: true, separatorBefore: true, run: () => remove(tool) },
      ],
    }), [busy])
    return <section style={{ height: '100%', display: 'flex', flexDirection: 'column', minWidth: 0, overflow: 'hidden' }}>
      <header style={{ ...row, padding: '16px 24px', borderBottom: '1px solid #edf0f4' }}><strong style={{ flex: 1 }}>{t('我的工具', 'My tools')}</strong>{hostPending > 0 && <span role="status" style={{fontSize:12,color:'#738291'}}>{t('正在处理任务…', 'Processing tasks…')}</span>}<input ref={input} type="file" accept=".zip,application/zip" hidden onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) void upload(file) }} /><button style={button} disabled={busy} onClick={() => input.current?.click()}>{t('导入工具', 'Import tool')}</button><button style={button} onClick={() => { void load() }}>{t('刷新列表', 'Refresh')}</button></header>
      {error && <p role="alert" style={{ margin: 12, color: '#a34635' }}>{error}</p>}
      {confirmation && <div style={{ position: 'fixed', inset: 0, background: '#16243540', zIndex: 1000, display: 'grid', placeItems: 'center', padding: 24 }}><div role="alertdialog" aria-modal="true" aria-label={t('确认操作', 'Confirm action')} style={{ background: '#fff', borderRadius: 12, padding: 24, maxWidth: 420, boxShadow: '0 12px 48px #16243526' }}><p style={{ margin: '0 0 20px', lineHeight: 1.6 }}>{confirmation.message}</p><div style={{ ...row, justifyContent: 'flex-end' }}><button autoFocus style={button} onClick={() => answer(false)}>{t('取消', 'Cancel')}</button><button style={button} onClick={() => answer(true)}>{t('确认', 'Confirm')}</button></div></div></div>}

      <div style={{ display: 'flex', flex: 1, minHeight: 0, minWidth: 0 }}>
        <aside className={css.libraryPane} data-mode={tabs.length ? 'sidebar' : 'library'} aria-label={t('工具列表', 'Tool list')} style={{ width: collapsed ? 36 : tabs.length ? 262 : '100%', maxWidth: '100%', boxSizing: 'border-box', flexShrink: 0, minHeight: 0, display: 'flex', flexDirection: 'column', borderRight: tabs.length ? '1px solid #edf0f4' : undefined }}>
          <div className={css.searchRow} data-collapsed={collapsed}>
            <div className={css.searchField} hidden={collapsed}><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></svg><input aria-label={t('搜索工具', 'Search tools')} placeholder={t('搜索工具', 'Search tools')} value={query} onChange={event => setQuery(event.target.value)} /></div>
            {!!tabs.length && <button type="button" className={css.iconButton} title={collapsed ? t('展开工具列表', 'Expand tool list') : t('收起工具列表', 'Collapse tool list')} aria-label={collapsed ? t('展开工具列表', 'Expand tool list') : t('收起工具列表', 'Collapse tool list')} aria-expanded={!collapsed} aria-controls="calabash-tool-list" onClick={() => setSidebarCollapsed(value => !value)}><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={collapsed ? 'm5 6 6 6-6 6m8-12 6 6-6 6' : 'm19 6-6 6 6 6M11 6l-6 6 6 6'} /></svg></button>}
          </div>
          <div id="calabash-tool-list" hidden={collapsed} className={css.list}>
          {!tools.length && <p style={{ color: '#7d8a97' }}>{t('还没有工具，在对话中描述你的想法即可创建。', 'No tools yet. Describe your idea in a conversation to create one.')}</p>}
          {tools.filter(tool => `${tool.title ?? ''} ${tool.name}`.toLowerCase().includes(query.toLowerCase())).map(tool => <div key={key(tool)} className={`${css.tool} ${active === key(tool) ? css.selected : ''}`}>
            <button {...menus.getTriggerProps(tabs.length ? { kind: 'calabashTool', value: tool } : undefined)} type="button" disabled={busy} aria-current={active === key(tool) ? 'true' : undefined} onClick={() => { void open(tool) }} className={css.openTool}>
              {!tabs.length && <span className={css.toolIcon}><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="4" /><path d="m7 9 3 3-3 3m6 0h4" /></svg></span>}
              <span className={css.toolCopy}><strong className={css.toolTitle} title={tool.title || tool.name}>{tool.title || tool.name}</strong>
              <span className={css.description} title={tool.description || tool.project}>{tool.description || tool.project}</span></span>
            </button>
            {!tabs.length && <div className={css.actions}>
              {iconButton(t('工具对话', 'Tool conversation'), 'M21 15a3 3 0 0 1-3 3H7l-4 3V6a3 3 0 0 1 3-3h12a3 3 0 0 1 3 3Z', () => { void chat(tool) })}
              {iconButton(t('导出工具', 'Export tool'), 'M12 3v12m-5-5 5 5 5-5M4 15v5h16v-5', () => { void download(tool) })}
              {iconButton(t('删除工具', 'Delete tool'), 'M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7', () => { void remove(tool) })}
            </div>}
          </div>)}
          </div>
        </aside>
        {!!tabs.length && <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minWidth: 0, minHeight: 0 }}><nav style={{ ...row, padding: 8, borderBottom: '1px solid #edf0f4' }}>{tabs.map(value => <span key={key(value)} style={{ ...row, background: active === key(value) ? '#edf4f1' : 'transparent', borderRadius: 6 }}><button style={{ ...button, border: 0, background: 'transparent' }} onClick={() => setActive(key(value))}>{value.name}</button><button style={{ ...button, border: 0, background: 'transparent' }} title={t('关闭工具', 'Close tool')} disabled={busy} onClick={() => { void close(value) }}>×</button></span>)}</nav>
          {tabs.map(value => value.url ? <iframe key={key(value)} src={value.url} title={value.name} sandbox="allow-scripts allow-same-origin allow-forms allow-downloads" style={{ ...frame, display: active === key(value) ? 'block' : 'none' }} /> : <div key={key(value)} style={{ padding: 24, display: active === key(value) ? 'block' : 'none' }}><p>{t('标签已恢复，工具尚未运行。', 'Tab restored. The tool has not been started.')}</p><button style={button} disabled={busy} onClick={() => { void open(value) }}>{t('打开工具', 'Open tool')}</button></div>)}
        </div>}
      </div>
    </section>
  }
  function Draft({ sessionId }: { sessionId: string }) {
    const t = useCopy()
    const container = useRef<HTMLElement>(null)
    const [target, setTarget] = useState<ToolTarget | null>(null)
    const [preview, setPreview] = useState<Preview | null>(null)
    const [busy, setBusy] = useState(false)
    const [notice, setNotice] = useState('')
    useEffect(() => {
      let disposed = false, pending = false
      const update = async () => {
        if (pending || document.hidden || !container.current?.getClientRects().length) return
        pending = true
        try { const value = JSON.parse(await api.state(sessionId)) as ToolTarget | null; if (!disposed) setTarget(value) }
        catch { /* Retry without stacking banners during generation. */ }
        finally { pending = false }
      }
      void update(); const timer = setInterval(() => { void update() }, 2500)
      return () => { disposed = true; clearInterval(timer) }
    }, [sessionId])
    const open = async () => {
      if (busy) return
      setBusy(true); setNotice('')
      try { setPreview(validPreview(JSON.parse(await api.preview(sessionId, preview !== null)) as Preview)) }
      catch { setNotice(t('预览暂时未能打开，请让 AI 检查工具后再重试。', 'Unable to open the preview. Ask AI to check the tool, then retry.')) }
      finally { setBusy(false) }
    }
    const save = async () => {
      if (!preview || busy) return
      setBusy(true); setNotice('')
      try {
        const all = JSON.parse(await api.list()) as ToolEntry[]
        const existing = all.find(value => value.project === preview.project && value.name === preview.name)
        const message = existing ? t('已有同名工具，确认用当前预览版本覆盖吗？', 'Replace the existing tool with this preview version?') : t('将当前预览保存到工具列表？', 'Save this preview to your tool list?')
        if (!window.confirm(message)) return
        await api.publish(sessionId, preview.revision, existing?.revision ?? '', true)
        setNotice(t('已保存到工具列表。保存不代表业务验证通过，请手动试用。', 'Saved to your tool list. Please test the tool manually.'))
      } catch { setNotice(t('暂时无法保存，请刷新预览，并确认同名工具没有正在运行。', 'Unable to save. Refresh the preview and make sure the existing tool is closed.')) }
      finally { setBusy(false) }
    }
    return <section ref={container} style={{ height: '100%', display: 'flex', flexDirection: 'column', minWidth: 0, overflow: 'hidden' }}>
      <header style={{ ...row, padding: 10, borderBottom: '1px solid #edf0f4' }}><strong style={{ flex: 1, fontSize: 13 }}>{target?.name || t('工具预览', 'Tool preview')}</strong><button style={button} disabled={!target || busy} onClick={() => { void open() }}>{busy ? t('正在处理…', 'Working…') : preview ? t('刷新预览', 'Refresh preview') : t('打开预览', 'Open preview')}</button><button style={button} disabled={!preview || busy} onClick={() => { void save() }}>{t('保存到工具列表', 'Save to tools')}</button></header>
      {notice && <p role="status" style={{ margin: 12, color: '#697b89', fontSize: 13 }}>{notice}</p>}
      {preview ? <iframe src={preview.url} title={t('工具预览', 'Tool preview')} sandbox="allow-scripts allow-same-origin allow-forms allow-downloads" style={frame} /> : <div style={{ padding: 24, color: '#7d8a97', fontSize: 14 }}>{target ? t('草稿已保存。点击打开预览，试用后可保存为正式工具。', 'Draft saved. Open the preview to try it, then save it as a tool.') : t('在对话中描述想创建的工具，草稿会关联到这里。', 'Describe the tool you want in the conversation. Its draft will appear here.')}</div>}
    </section>
  }
  type Bounds = { left: number; top: number; width: number; height: number }
  let bounds: Bounds | null = null
  const listeners = new Set<() => void>()
  function setBounds(value: Bounds | null) {
    if (JSON.stringify(value) === JSON.stringify(bounds)) return
    bounds = value; for (const notify of listeners) notify()
  }
  function WorkspaceSeat() {
    const element = useRef<HTMLDivElement>(null)
    useLayoutEffect(() => {
      const update = () => { if (element.current) { const r = element.current.getBoundingClientRect(); setBounds({ left:r.left, top:r.top, width:r.width, height:r.height }) } }
      const observer = new ResizeObserver(update); if (element.current) observer.observe(element.current)
      window.addEventListener('resize', update); update()
      return () => { observer.disconnect(); window.removeEventListener('resize', update); setBounds(null) }
    }, [])
    return <div ref={element} style={{ width:'100%', height:'100%' }} />
  }
  function WorkspaceLayer(props: { useContextMenu: UseContextMenu }) {
    const rect = useSyncExternalStore(listener => { listeners.add(listener); return () => { listeners.delete(listener) } }, () => bounds)
    return <div style={{ position:'fixed', left:rect?.left ?? 0, top:rect?.top ?? 0, width:rect?.width ?? 0, height:rect?.height ?? 0, display:rect ? 'block' : 'none', pointerEvents:'auto', zIndex:1, background:'#fff' }}><Tools {...props} /></div>
  }
  ctx.effect(() => ctx.slots.inject('main', () => ctx.slots.register({ name: 'main', key: panel }, WorkspaceSeat)))
  ctx.effect(() => ctx.slots.inject('shell.overlay', () => ctx.slots.register({ name:'shell.overlay', id:'calabash.workspace', order:-100 }, WorkspaceLayer)))
  ctx.effect(() => ctx.slots.inject('sidebar.panellist', () => ctx.slots.register({ name: 'sidebar.panellist', id: panel, order: -20, label: () => copy('我的工具', 'My tools') }, ({ size }) => <svg width={size ?? 18} height={size ?? 18} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="3" y="7" width="18" height="14" rx="2.5" /><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 12a25 25 0 0 0 18 0M10 12v3h4v-3" /></svg>)))
  ctx.effect(() => ctx.sidebarRightTabs.register({ id: tab, kind: 'calabash-preview', title: () => copy('工具预览', 'Tool preview'), keepMounted: true, guide: [{ id: 'preview', order: -20, title: () => copy('工具预览', 'Tool preview'), description: () => copy('试用当前对话中的工具', 'Try the tool from this conversation'), icon: () => <span>▦</span> }] }))
  ctx.effect(() => ctx.slots.inject('sidebar.right.pane.tab', () => ctx.slots.register({ name: 'sidebar.right.pane.tab', key: tab, inject: (sessionId) => ({ sessionId }) }, Draft)))
}
