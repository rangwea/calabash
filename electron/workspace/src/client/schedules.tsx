import { useEffect, useRef, useState } from 'react'
import type { ToolEntry } from '../types.ts'
import css from './schedules.module.css'

export interface Schedule {
  id: string; project: string; name: string; task: string; title: string
  interval: number; next_run: number; enabled: number; status: string
}
interface Task { name: string; title: string }
type Copy = (zh: string, en: string) => string
export type ScheduleCall = (operation: string, args: Record<string, unknown>) => Promise<unknown>
export const toolKey = (value: {project:string; name:string}) => `${value.project}/${value.name}`
export const scheduleTime = (time: number, t: Copy) => new Intl.DateTimeFormat(t('zh-CN', 'en-US'), {
  month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', hour12:false,
}).format(new Date(time * 1000))
export function scheduleStatus(status: string, t: Copy) {
  const states: Record<string,string> = {
    ready:t('等待执行','Ready'), running:t('排队或执行中','Queued or running'), succeeded:t('最近已完成','Last run completed'),
    failed:t('执行失败，请检查工具','Failed; check the tool'), changed:t('工具已更新，请重新创建','Tool changed; recreate schedule'),
    interrupted:t('上次执行中断','Last run interrupted'), cancelled:t('已停止','Stopped'),
  }
  return states[status] || t('等待执行','Ready')
}
export function useSchedules(call: ScheduleCall) {
  const [rows, setRows] = useState<Schedule[]>([])
  const [failed, setFailed] = useState(false)
  const alive = useRef(false), pending = useRef(false)
  const refresh = async () => {
    if (pending.current) return
    pending.current = true
    try {
      const value = await call('list', {}) as Schedule[]
      if (alive.current) { setRows(value); setFailed(false) }
    } catch { if (alive.current) setFailed(true) }
    finally { pending.current = false }
  }
  useEffect(() => {
    alive.current = true
    void refresh()
    const timer = setInterval(() => { if (!document.hidden) void refresh() }, 5000)
    return () => { alive.current = false; clearInterval(timer) }
  }, [call])
  return { rows, failed, refresh }
}
export function Schedules({ tools, call, t, rows, failed, refresh, focus }: {
  tools: ToolEntry[]; call: ScheduleCall; t: Copy; rows: Schedule[]; failed: boolean
  refresh: () => Promise<void>; focus: {tool:string; create:boolean} | null
}) {
  const [filter, setFilter] = useState(focus?.tool ?? '')
  const [editing, setEditing] = useState(focus?.create ?? false)
  const [tool, setTool] = useState(focus?.tool ?? '')
  const [tasks, setTasks] = useState<Task[]>([]), [task, setTask] = useState('')
  const [minutes, setMinutes] = useState(60)
  const [loading, setLoading] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('')
  const actionLock = useRef(false)
  useEffect(() => {
    if (focus) { setFilter(focus.tool); setTool(focus.tool); setEditing(focus.create) }
  }, [focus])
  useEffect(() => {
    let alive = true
    setTasks([]); setTask(''); setLoading(false)
    if (editing && tool) {
      setLoading(true); setError('')
      const [project, name] = tool.split('/')
      void call('tasks', { project, name }).then(value => {
        if (alive) { const choices = value as Task[]; setTasks(choices); setTask(choices[0]?.name ?? '') }
      }).catch(() => { if (alive) setError(t('暂时无法读取工具任务，请检查工具后重试。', 'Unable to load saved tool tasks.')) })
        .finally(() => { if (alive) setLoading(false) })
    }
    return () => { alive = false }
  }, [tool, editing, call])
  const act = async (operation: string, args: Record<string, unknown>) => {
    if (actionLock.current) return
    actionLock.current = true; setBusy(true); setError('')
    try { await call(operation, args); await refresh(); if (operation === 'create') setEditing(false) }
    catch { setError(t('操作未完成；如果工具已更新，请重新创建计划。', 'Unable to complete. If the tool changed, create a new schedule.')) }
    finally { actionLock.current = false; setBusy(false) }
  }
  const create = () => {
    const [project, name] = tool.split('/')
    const title = tasks.find(value => value.name === task)?.title ?? ''
    if (window.confirm(t(`确认每 ${minutes} 分钟自动执行“${title}”？可能写入工具数据或生成文件，仅在 App 运行时执行。工具更新后暂停，模型调用仍需确认。`, `Automatically run “${title}” every ${minutes} minutes? This may write tool data or create files while the app is running. Tool updates pause the plan; model calls still require confirmation.`))) {
      void act('create', { project, name, task, minutes, confirmed:true })
    }
  }
  const filtered = rows.filter(value => !filter || toolKey(value) === filter)
  const options = tools.map(value => <option key={toolKey(value)} value={toolKey(value)}>{value.title || value.name}</option>)
  return <section className={css.pane} aria-label={t('定时任务','Scheduled tasks')}>
    <header className={css.header}><div><h2>{t('定时任务','Scheduled tasks')}</h2><p>{t('让工具按计划自动处理固定任务。','Let your tools run recurring tasks.')}</p></div>
      <button className={css.primary} onClick={() => { setTool(filter); setEditing(true) }} disabled={busy}>{t('＋ 新建计划','＋ New plan')}</button></header>
    <div className={css.content}>
      <div className={css.hint}>{t('仅在 App 运行时执行 · 错过不补跑 · 模型调用仍需确认','Runs while the app is open · No catch-up runs · Model calls require confirmation')}</div>
      {editing && <form className={css.creator} onSubmit={event => { event.preventDefault(); create() }}>
        <div className={css.formHeading}><strong>{t('新建计划','New plan')}</strong><button type="button" disabled={busy} onClick={() => setEditing(false)}>{t('取消','Cancel')}</button></div>
        <div className={css.form}>
          <label>{t('工具','Tool')}<select value={tool} disabled={busy} onChange={event => setTool(event.target.value)}><option value="">{t('选择已保存工具','Select a saved tool')}</option>{options}</select></label>
          <label>{t('固定任务','Registered task')}<select value={task} disabled={busy || loading || !tasks.length} onChange={event => setTask(event.target.value)}><option value="">{loading?t('正在读取…','Loading…'):t('选择任务','Select a task')}</option>{tasks.map(value => <option key={value.name} value={value.name}>{value.title}</option>)}</select></label>
          <label>{t('每隔（分钟）','Every (minutes)')}<input type="number" min={1} max={10080} value={minutes} disabled={busy} onChange={event => setMinutes(Number(event.target.value))}/></label>
          <button type="submit" className={css.primary} disabled={busy || loading || !task || !Number.isInteger(minutes) || minutes < 1 || minutes > 10080}>{busy?t('正在创建…','Creating…'):t('创建计划','Create plan')}</button>
        </div>
        {tool && !loading && !tasks.length && <p>{t('此工具尚未提供固定任务，可在工具对话中让 AI 添加。','This tool has no registered tasks. Ask its authoring Agent to add one.')}</p>}
      </form>}
      {(error || failed) && <div role="alert" className={css.error}>{error || t('计划暂时无法更新，请重试。','Unable to update schedules. Please retry.')}<button onClick={() => void refresh()}>{t('重试','Retry')}</button></div>}
      <div className={css.filter}><strong>{t('计划列表','Plans')} <span>{filtered.length}</span></strong><select aria-label={t('筛选工具','Filter by tool')} value={filter} onChange={event => setFilter(event.target.value)}><option value="">{t('全部工具','All tools')}</option>{options}</select></div>
      {!filtered.length ? <div className={css.empty}><strong>{t('还没有定时计划','No plans yet')}</strong><p>{t('新建计划并确认授权后，工具就能按时执行。','Create and authorize a plan to start scheduled work.')}</p><button onClick={() => { setTool(filter); setEditing(true) }}>{t('新建计划','New plan')}</button></div> : <div className={css.list}>{filtered.map(value => <article key={value.id} className={css.item}>
        <div className={css.identity}><strong>{value.title}</strong><span>{tools.find(tool => toolKey(tool) === toolKey(value))?.title || value.name}</span></div>
        <div className={css.timing}><strong>{t('每','Every')} {value.interval/60} {t('分钟','minutes')}</strong><span>{value.enabled?t('下次 ','Next ') + scheduleTime(value.next_run,t):t('已暂停','Paused')}</span></div>
        <span className={css.badge} data-state={value.status} role="status">{scheduleStatus(value.status,t)}</span>
        <div className={css.actions}><button disabled={busy || value.status === 'changed'} onClick={() => void act(value.enabled?'pause':'resume',{id:value.id,confirmed:true})}>{value.enabled?t('暂停','Pause'):t('恢复','Resume')}</button><button disabled={busy || ['running','changed'].includes(value.status)} onClick={() => { if (window.confirm(t('确认立即执行此固定任务？','Run this registered task now?'))) void act('run',{id:value.id,confirmed:true}) }}>{t('立即执行','Run now')}</button>
          <details><summary aria-label={t('更多操作','More actions')} title={t('更多操作','More actions')}>•••</summary><div className={css.more}><button disabled={busy} onClick={event => { event.currentTarget.closest('details')?.removeAttribute('open'); if (window.confirm(t('删除计划？已受理的任务会继续完成。','Remove this plan? Accepted work will finish.'))) void act('remove',{id:value.id,confirmed:true}) }}>{t('删除计划','Remove plan')}</button></div></details>
        </div>
      </article>)}</div>}
    </div>
  </section>
}
