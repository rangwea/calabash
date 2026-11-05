<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ChatLineRound, Folder, Fold, Expand, Setting, Plus, MoreFilled, Download, Delete, Top, ArrowLeft, Close, Paperclip, Refresh, FolderAdd, Upload, Search, MagicStick, View } from '@element-plus/icons-vue'
import { api, json } from './api'
import logo from '../../component/assets/calabash.png'
import { displayError } from './request_errors.mjs'
import { shouldSend } from './composer.mjs'
import { markdown } from './markdown'

type Message = { role: string; content?: string; tool_calls?: unknown[]; attachments?: string[] }
type Chat = { id: string; title: string; running: boolean }
type Tool = { project: string; name: string; title: string; description: string; revision: string }
const nativeHost = Boolean((window as any).__TAURI_INTERNALS__)
const clock = () => performance.now()
const ready = ref(false), failed = ref(''), collapsed = ref(false), page = ref('tools')
type UIPreset = {id: string; version: number; title: string; mention: string; description: string; color: string}
const uiPresets = ref<UIPreset[]>([]), defaultUI = ref('office')
const uiMatches = computed(() => {
  const match = draft.value.match(/(?:^|\s)@([^@\s]*)$/)
  if (!match || composing.value) return []
  const query = match[1].toLowerCase()
  return uiPresets.value.filter(p => [p.id,p.title,p.mention].some(text => text.toLowerCase().includes(query)))
})
function insertUI(preset: UIPreset) {
  const mention = language.value === 'en' ? preset.mention : preset.title
  if (/(?:^|\s)@([^@\s]*)$/.test(draft.value)) draft.value = draft.value.replace(/@[^@\s]*$/, '@' + mention + ' ')
  else draft.value = '@' + mention + ' ' + draft.value
}
async function setDefaultUI(value: string) { await api('/settings', json('PATCH', {default_ui: value})); defaultUI.value = value }
const language = ref('zh-CN'), translations = ref<Record<string, string>>({})
const t = (value: string) => language.value === 'en' ? translations.value[value] || value : value
const chats = ref<Chat[]>([]), tools = ref<Tool[]>([]), chatId = ref(''), messages = ref<Message[]>([])
const draft = ref(''), liveText = ref(''), activity = ref<string[]>([]), error = ref(''), running = ref(false)
const activityLabels: Record<string,string> = {read_ui_preset: '选择工具风格', read_task_context: '了解当前任务', set_task_brief: '整理需求与验收条件', read_tool: '了解工具当前内容', read_tool_file: '了解工具当前内容', search_code: '查找需要调整的地方', patch_tool_file: '调整工具', write_tool: '创建工具', stage_tool: '准备调整工具', deliver_draft: '保存工具草稿', validate_tool: '检查工具', check_tool_build: '检查工具是否可以保存', read_build_diagnostics: '查看工具的问题记录', read_tool_logs: '查看工具的问题记录', inspect_preview: '检查工具界面', verify_preview: '确认使用效果', interact_preview: '检查工具操作', resuming: '继续处理'}
const uploads = ref(new Set<string>())
const sending = ref(new Set<string>())
const submitting = computed(() => sending.value.has(chatId.value))
const uploading = computed(() => uploads.value.has(chatId.value))
const composing = ref(false), compositionEnded = ref<number>()
const attachments = ref<any[]>([]), models = ref<Record<string, string>>({}), model = ref('')
const chatFiles = ref<any[]>([])
const preview = ref(''), previewShown = ref(false), previewRevision = ref(0), search = ref('')
const previewRuntime = ref('')
const runtimeProblems = ref(new Set<string>())
const previewProblem = computed(() => Boolean(previewRuntime.value && runtimeProblems.value.has(new URL(previewRuntime.value).origin)))
const manualPreviewPending = ref(false)
type BuildCheck = {revision: string; state: 'checking' | 'passed' | 'failed'}
const buildCheck = ref<BuildCheck>(), checkError = ref(''), publishing = ref(false)
let checkTimer: ReturnType<typeof setInterval> | undefined
let checkBusy = false
watch([chatId, preview, manualPreviewPending], () => { buildCheck.value = undefined; checkError.value = ''; void pollBuildCheck() })
async function pollBuildCheck(retry = false) {
  if (checkBusy || !preview.value || !previewShown.value || page.value !== 'chat') return
  const id = chatId.value, url = preview.value, ticket = generation
  const parts = new URL(url, location.origin).pathname.split('/')
  if (parts.length !== 4) return
  checkBusy = true
  try {
    const value = await api(`/tools/${parts[2]}/${parts[3]}/preview/check`, json('POST', {chat_id: id, retry}))
    if (id === chatId.value && url === preview.value && ticket === generation) { buildCheck.value = value; checkError.value = '' }
  } catch {
    if (id === chatId.value && url === preview.value && ticket === generation) checkError.value = t('暂时无法确认工具是否准备好，请重试')
  } finally { checkBusy = false }
}

const openTools = ref<(Tool & { url: string })[]>([]), selectedTool = ref('')
const sidebarWidth = ref(Number(localStorage.getItem('sidebar-width')) || 250)
const chatWidth = ref(Number(localStorage.getItem('chat-width')) || 500)
const viewportWidth = ref(innerWidth)
const effectiveChatWidth = computed(() => Math.min(chatWidth.value, Math.max(280, viewportWidth.value - (collapsed.value ? 52 : sidebarWidth.value) - 284)))
const settingsReturnPage = ref('tools'), settingsLoaded = ref(false), settingsSaving = ref(false)
const connections = ref<any>({}), provider = ref('openai')
const connection = ref({ base_url: 'https://api.openai.com/v1', key: '', models: '', vision_models: '' })
const capabilityLabels: Record<string, string> = { ready: '可用', not_installed: '未安装', unavailable: '暂不可用', invalid: '需要重新导入' }
const capabilityState = ref<{configured: boolean; packs: Array<{id?: string; state: string; version?: string}>}>({ configured: false, packs: [] }), importingCapability = ref(false)
let stream: EventSource | undefined
let generation = 0
const drafts = new Map<string, string>()
let diagnosticTimer: ReturnType<typeof setInterval> | undefined
const diagnosticBusy = ref(false)
const filteredTools = computed(() => tools.value.filter(tool => `${tool.title} ${tool.name} ${tool.description}`.toLowerCase().includes(search.value.toLowerCase())))
const toolKey = (tool: Tool) => `${tool.project}/${tool.name}`
const opening = ref(new Set<string>())
const creatingChat = ref(false)
const activeTool = computed(() => openTools.value.find(tool => toolKey(tool) === selectedTool.value))
const activeProblem = computed(() => Boolean(activeTool.value && runtimeProblems.value.has(new URL(activeTool.value.url).origin)))
function navigateToolTab(event: KeyboardEvent, tool: Tool) {
  const keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End']
  if (!keys.includes(event.key)) return
  event.preventDefault()
  const count = openTools.value.length, current = openTools.value.findIndex(item => toolKey(item) === toolKey(tool))
  if (!count) return
  const index = event.key === 'Home' ? 0 : event.key === 'End' ? count - 1 : (current + (event.key === 'ArrowRight' ? 1 : -1) + count) % count
  selectedTool.value = toolKey(openTools.value[index])
  document.getElementById('tool-tab-' + selectedTool.value)?.focus()
}

async function attempt(action: () => Promise<unknown>) {
  try { await action() } catch (failure) { if (failure !== 'cancel' && failure !== 'close') ElMessage.error(failure instanceof Error ? t(displayError(failure.message)) : t('操作失败')) }
}
async function refreshNavigation() {
  const [chatList, toolList] = await Promise.all([api('/chats'), api('/tools')])
  chats.value = chatList; tools.value = toolList
}
async function bootstrap() {
  const data = await api('/bootstrap')
  language.value = data.language; translations.value = data.translations
  uiPresets.value = data.ui_presets; defaultUI.value = data.default_ui
  models.value = data.models; model.value = data.selected_model || ''
  await refreshNavigation(); ready.value = true
}
async function newChat() {
  if (creatingChat.value) return
  if (chatId.value && !messages.value.length && !running.value) { page.value = 'chat'; return }
  creatingChat.value = true
  try {
    const data = await api('/chats', json('POST'))
    await enterChat(data.id); await refreshNavigation()
  } finally { creatingChat.value = false }
}

function connectEvents(id: string, after: number, ticket: number) {
  stream?.close()
  stream = new EventSource(`/api/workspace/chats/${id}/events?after=${after}`)
  stream.onmessage = async event => {
    if (ticket !== generation) return
    const data = JSON.parse(event.data)
    if (data.kind === 'text') liveText.value += data.value
    if (data.kind === 'activity' && data.value !== 'generating_tool') activity.value.push(data.value)
    if (['preview', 'manual_preview'].includes(data.kind)) {
      const url = data.value.preview_url || data.value.url
      if (url) { preview.value = url; previewShown.value = true }
      manualPreviewPending.value = data.kind === 'manual_preview'
      if (url && !previewRuntime.value && !manualPreviewPending.value) void attempt(loadPreview)
    }
    if (data.kind === 'error') error.value = data.value
    if (data.kind === 'status') {
      stream?.close(); running.value = false
      await enterChat(id, false, false); await refreshNavigation()
    }
  }
  stream.addEventListener('snapshot', () => { if (ticket === generation) void enterChat(id, false) })
  stream.onerror = () => { /* EventSource reconnects with Last-Event-ID. */ }
}
async function enterChat(id: string, resetPreview = true, navigate = true) {
  if (resetPreview && id !== chatId.value) void detachPreview().catch(() => {})
  if (chatId.value) drafts.set(chatId.value, draft.value)
  const ticket = ++generation
  stream?.close(); const data = await api(`/chats/${id}`)
  if (ticket !== generation) return
  if (navigate) page.value = 'chat'
  chatId.value = id; draft.value = drafts.get(id) || ''; messages.value = data.messages
  attachments.value = data.attachments; chatFiles.value = data.files; error.value = data.failure
  preview.value = data.preview; if (resetPreview) previewShown.value = Boolean(data.preview)
  if (resetPreview) { previewRuntime.value = ''; manualPreviewPending.value = false; if (data.preview) void attempt(loadPreview) }
  liveText.value = ''; activity.value = []; running.value = data.run?.status === 'running'
  if (running.value) {
    for (const event of data.run.events) {
      if (event.kind === 'text') liveText.value += event.value
      if (event.kind === 'activity' && event.value !== 'generating_tool') activity.value.push(event.value)
    }
    connectEvents(id, data.run.sequence, ticket)
  }
}
async function send() {
  if (!draft.value.trim() || running.value || uploading.value || submitting.value) return
  const id = chatId.value, ticket = generation
  const text = draft.value
  sending.value.add(id)
  try {
    await api(`/chats/${id}/runs`, json('POST', { text, attachments: attachments.value.map(item => item.id) }))
    drafts.delete(id)
    if (id === chatId.value && ticket === generation) {
      draft.value = ''; liveText.value = ''; activity.value = []; error.value = ''; attachments.value = []
      messages.value.push({ role: 'user', content: text }); running.value = true
      connectEvents(id, 0, ticket)
    }
    await refreshNavigation()
  } finally { sending.value.delete(id) }
}
async function resumeGeneration() {
  const id = chatId.value
  await api(`/chats/${id}/resume`, json('POST'))
  await enterChat(id, false)
}
function keydown(event: KeyboardEvent) {
  if (shouldSend(event, { composing: composing.value, ended: compositionEnded.value, uploading: uploading.value })) {
    event.preventDefault(); void attempt(send)
  }
}
async function uploadFiles(files: File[]) {
  const id = chatId.value
  if (running.value || uploads.value.has(id)) return
  uploads.value.add(id)
  try {
  for (const file of files) {
    const form = new FormData(); form.append('file', file)
    const item = await api(`/chats/${id}/attachments`, { method: 'POST', body: form })
    if (id === chatId.value) attachments.value.push(item)
  }
  } finally { uploads.value.delete(id) }
}
async function selectFiles() {
  const id = chatId.value
  const bridge = (window as any).__TAURI_INTERNALS__
  if (bridge) {
    uploads.value.add(id)
    try {
    const ticket = await bridge.invoke('select_chat_files')
    if (ticket) {
      await api(`/chats/${id}/selections`, json('POST', { ticket }))
      const attached = (await api(`/chats/${id}`)).attachments
      if (id === chatId.value) attachments.value = attached
    }
    } finally { uploads.value.delete(id) }
  } else {
    const input = document.createElement('input'); input.type = 'file'; input.multiple = true
    input.onchange = () => void attempt(() => uploadFiles(Array.from(input.files || []))); input.click()
  }
}
function paste(event: ClipboardEvent) {
  const files = Array.from(event.clipboardData?.files || [])
  if (files.length) { event.preventDefault(); void attempt(() => uploadFiles(files)) }
}
async function chatAction(action: string, chat: Chat) {
  if (action === 'rename') {
    const result = await ElMessageBox.prompt(t('对话名称'), t('重命名'), { inputValue: chat.title })
    await api(`/chats/${chat.id}`, json('PATCH', { title: result.value }))
  } else {
    await ElMessageBox.confirm(t('确认删除此对话？'), t('删除对话'), { type: 'warning' })
    await api(`/chats/${chat.id}`, json('DELETE'))
    if (chatId.value === chat.id) { stream?.close(); page.value = 'tools' }
  }
  await refreshNavigation()
}
async function openTool(tool: Tool) {
  const key = toolKey(tool)
  if (opening.value.has(key)) return
  opening.value.add(key)
  try {
  if (!openTools.value.some(item => toolKey(item) === key)) {
    const runtime = await api('/tools/open', json('POST', { project: tool.project, name: tool.name }))
    openTools.value.push({ ...tool, url: runtime.url })
  }
  selectedTool.value = key; page.value = 'opened'
  } finally { opening.value.delete(key) }
}
async function importTool() {
  const input = document.createElement('input'); input.type = 'file'; input.accept = '.zip'
  input.onchange = () => void attempt(async () => {
    const file = input.files?.[0]; if (!file) return
    const form = new FormData(); form.append('file', file)
    const inspected = await api('/tools/inspect', { method: 'POST', body: form })
    const meta = inspected.manifest
    const existing = tools.value.find(tool => tool.project === meta.project && tool.name === meta.name)
    await ElMessageBox.confirm(`${meta.title || meta.name}\n${t(existing ? '已有同名工具，确认覆盖？' : '确认导入此工具？')}`, t('导入工具'), { type: 'warning' })
    await api('/tools/import', json('POST', { files: inspected.files, revision: existing?.revision || '', confirmed: true }))
    await refreshNavigation(); ElMessage.success(t('导入成功'))
  })
  input.click()
}
async function publishPreview() {
  if (publishing.value || buildCheck.value?.state !== 'passed' || manualPreviewPending.value || checkError.value || previewProblem.value) return
  publishing.value = true
  try {
    const id = chatId.value
    const path = new URL(preview.value, location.origin).pathname.split('/')
    if (path.length !== 4) throw new Error(t('暂无工具预览'))
    const [project, name] = path.slice(2)
    const source = await api(`/tools/${project}/${name}/source?chat_id=${id}`)
    if (source.revision !== buildCheck.value?.revision) { buildCheck.value = undefined; await pollBuildCheck(); throw new Error(t('工具已更新，正在重新准备，请稍候')) }
    const existing = tools.value.find(tool => tool.project === project && tool.name === name)
    await ElMessageBox.confirm(t(existing ? '已有同名工具，确认覆盖？' : '保存当前预览为正式工具？'), t('保存到工具列表'), { type: 'warning' })
    await api(`/tools/${project}/${name}/publish`, json('POST', { chat_id: id, revision: source.revision, replace_revision: existing?.revision || '', confirmed: true }))
    await refreshNavigation(); ElMessage.success(t('已保存到工具列表'))
  } finally { publishing.value = false }
}

async function grantDiagnostics() {
  const path = new URL(preview.value, location.origin).pathname.split('/')
  if (path.length !== 4) throw new Error(t('暂无工具预览'))
  await ElMessageBox.confirm(t('Agent 可读取当前预览的可见文字、控件、前端错误和媒体状态，可能涉及业务信息。不会读取输入框值。每次点击或输入另行确认；授权十分钟内有效，刷新或修改后失效。'), t('让 AI 检查界面'), { type: 'warning' })
  await api(`/chats/${chatId.value}/diagnostics`, json('POST', { project: path[2], name: path[3], confirmed: true }))
  ElMessage.success(t('已授权，可在对话中要求 Agent 检查当前预览'))
}
async function repairPreview() {
  if (buildCheck.value?.state === 'failed') {
    const id = chatId.value, url = preview.value
    const parts = new URL(url, location.origin).pathname.split('/')
    if (parts.length !== 4) return
    await ElMessageBox.confirm(t('允许 AI 查看这个工具的问题记录并尝试修复吗？完成后，请你试用并保存。'), t('让 AI 帮我修复'), { type: 'warning' })
    if (id !== chatId.value || url !== preview.value) return
    const text = `${t('请修复这个工具，保留现有界面和功能。先查看问题记录，完成后我会手动试用和保存。')} (${parts[2]}/${parts[3]})`
    await api(`/chats/${id}/runs`, json('POST', {text, attachments: []}))
    await enterChat(id, false)
    return
  }
  const path = new URL(preview.value, location.origin).pathname.split('/')
  if (path.length !== 4) throw new Error(t('暂无工具预览'))
  await ElMessageBox.confirm(t('允许 AI 查看这个工具的问题记录并尝试修复吗？完成后，请你试用并保存。'), t('让 AI 帮我修复'), { type: 'warning' })
  await api(`/chats/${chatId.value}/repair`, json('POST', { project: path[2], name: path[3], confirmed: true }))
  await enterChat(chatId.value, false)
}
async function pollDiagnosticRequests() {
  if (page.value !== 'chat' || !chatId.value || diagnosticBusy.value) return
  const id = chatId.value
  const requests = await api(`/chats/${id}/diagnostics/requests`)
  if (!requests.length || id !== chatId.value) return
  diagnosticBusy.value = true
  const request = requests[0]
  let approved = false
  try {
    await ElMessageBox.confirm(`${request.project}/${request.name}\n${request.action}: ${request.label}\n${request.value || ''}\n${request.reason}\n\n${t('此操作可能触发真实写入、删除或导出。仅允许本次操作，不授权后续操作。')}`, t('确认预览操作'), { confirmButtonText: t('允许本次操作'), cancelButtonText: t('拒绝'), type: 'warning' })
    approved = true
  } catch { /* User declined this individual action. */ }
  try { await api(`/chats/${id}/diagnostics/requests/${request.id}`, json('POST', { approved })) }
  finally { diagnosticBusy.value = false }
}
async function toolAction(action: string, tool: Tool) {
  if (action === 'export') {
    const bridge = (window as any).__TAURI_INTERNALS__
    if (bridge) {
      const result = await api(`/tools/${tool.project}/${tool.name}/export-ticket`, json('POST'))
      if (result.ticket) await bridge.invoke('save_tool_output', { ticket: result.ticket })
      return
    }
    const response = await fetch(`/api/workspace/tools/${tool.project}/${tool.name}/export`)
    if (!response.ok) throw new Error(t('导出失败'))
    const url = URL.createObjectURL(await response.blob()); const link = document.createElement('a')
    link.href = url; link.download = `${tool.name}.zip`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 30000)
  } else if (action === 'delete') {
    await ElMessageBox.confirm(t('确认删除此工具？'), t('删除工具'), { type: 'warning' })
    await api(`/tools/${tool.project}/${tool.name}`, json('DELETE', { revision: tool.revision, confirmed: true }))
    await refreshNavigation()
  }
}
async function closeTool(tool: Tool) {
  const key = toolKey(tool)
  const state = await api(`/tools/${tool.project}/${tool.name}/status`)
  if (state.running) await ElMessageBox.confirm(t('工具正在运行，等待当前项目完成后关闭？'), t('关闭工具'), { type: 'warning' })
  await api(`/tools/${tool.project}/${tool.name}/close`, json('POST'))
  openTools.value = openTools.value.filter(item => toolKey(item) !== key)
  if (selectedTool.value === key) selectedTool.value = openTools.value[0] ? toolKey(openTools.value[0]) : ''
  if (!openTools.value.length) selectedTool.value = ''
}
async function refreshTool(tool: Tool & {url: string}) {
  const runtime = await api(`/tools/${tool.project}/${tool.name}/refresh`, json('POST'))
  tool.url = runtime.url
}
async function loadPreview() {
  const id = chatId.value, url = preview.value
  const parts = new URL(url, location.origin).pathname.split('/')
  if (parts.length !== 4) return
  if (previewRuntime.value) runtimeProblems.value.delete(new URL(previewRuntime.value).origin)
  const runtime = await api(`/tools/${parts[2]}/${parts[3]}/preview/open`, json('POST', { chat_id: id }))
  if (id === chatId.value && url === preview.value) { previewRuntime.value = runtime.url; previewRevision.value++; manualPreviewPending.value = false; void pollBuildCheck() }
}
async function detachPreview() {
  if (!previewRuntime.value || !chatId.value) return
  const parts = new URL(preview.value, location.origin).pathname.split('/')
  const id = chatId.value
  if (parts.length === 4) await api(`/tools/${parts[2]}/${parts[3]}/preview/detach`, json('POST', { chat_id: id }))
}
function togglePreview() {
  if (previewShown.value) {
    previewShown.value = false; void detachPreview().catch(() => {}); previewRuntime.value = ''
  } else {
    previewShown.value = true; if (preview.value) void attempt(loadPreview)
  }
}
function frameTarget(event: MessageEvent) {
  const frames = Array.from(document.querySelectorAll('iframe'))
  const frame = frames.find(item => item.contentWindow === event.source)
  if (!frame || new URL(frame.src).origin !== event.origin) return
  const tool = openTools.value.find(item => new URL(item.url).origin === event.origin)
  if (tool && page.value === 'opened' && selectedTool.value === toolKey(tool)) return { project: tool.project, name: tool.name, chat_id: null }
  if (page.value === 'chat' && previewShown.value && previewRuntime.value && new URL(previewRuntime.value).origin === event.origin) {
    const parts = new URL(preview.value, location.origin).pathname.split('/')
    return { project: parts[2], name: parts[3], chat_id: chatId.value }
  }
}
let fileBridgeBusy = false
async function frameMessage(event: MessageEvent) {
  const target = frameTarget(event), bridge = (window as any).__TAURI_INTERNALS__, data = event.data
  if (!target || !data || typeof data !== 'object') return
  if (data.kind === 'calabash-tool-issue') { runtimeProblems.value.add(event.origin); return }
  if (!bridge || fileBridgeBusy) return
  fileBridgeBusy = true
  try {
    if (data.kind === 'calabash-select-inputs') {
      const ticket = await bridge.invoke('select_chat_files')
      if (ticket) await api(`/tools/${target.project}/${target.name}/inputs/selection`, json('POST', { ticket, chat_id: target.chat_id }))
    } else if (data.kind === 'calabash-result-action' && /^[a-f0-9]{32}$/.test(data.file_id) && ['save', 'open', 'reveal'].includes(data.action)) {
      const result = await api(`/tools/${target.project}/${target.name}/results/${data.file_id}/action`, json('POST', { action: data.action }))
      if (result.ticket) await bridge.invoke('save_tool_output', { ticket: result.ticket })
    }
  } finally { fileBridgeBusy = false }
}
function imageFile(fileId: string) {
  const file = chatFiles.value.find(item => item.id === fileId) || attachments.value.find(item => item.id === fileId)
  return file && /\.(png|jpe?g|webp|gif)$/i.test(file.name)
}
async function nativeFiles(event: Event) {
  const detail = (event as CustomEvent).detail
  if (!detail?.ticket) return
  if (detail.position) {
    const element = document.elementFromPoint(detail.position.x / devicePixelRatio, detail.position.y / devicePixelRatio)
    const frame = element?.closest('iframe')
    if (frame) {
      const tool = openTools.value.find(item => new URL(item.url).origin === new URL(frame.src).origin)
      const parts = previewRuntime.value && new URL(previewRuntime.value).origin === new URL(frame.src).origin ? new URL(preview.value, location.origin).pathname.split('/') : []
      const target = tool ? { project: tool.project, name: tool.name, chat_id: null } : parts.length === 4 ? {project: parts[2], name: parts[3], chat_id: chatId.value} : null
      if (target) await api(`/tools/${target.project}/${target.name}/inputs/selection`, json('POST', { ...target, ticket: detail.ticket }))
      return
    }
  }
  if (page.value !== 'chat' || !chatId.value || running.value) return
  const id = chatId.value
  uploads.value.add(id)
  try {
    await api(`/chats/${id}/selections`, json('POST', { ticket: detail.ticket }))
    const attached = (await api(`/chats/${id}`)).attachments
    if (id === chatId.value) attachments.value = attached
  } finally { uploads.value.delete(id) }
}
async function modifyTool(tool: Tool) {
  const data = await api(`/tools/${tool.project}/${tool.name}/chat`, json('POST'))
  await enterChat(data.id); await refreshNavigation()
}
async function repairTool(tool: Tool) {
  await ElMessageBox.confirm(t('允许 AI 查看这个工具的问题记录并尝试修复吗？完成后，请你试用并保存。'), t('让 AI 帮我修复'), { type: 'warning' })
  const chat = await api(`/tools/${tool.project}/${tool.name}/chat`, json('POST'))
  await api(`/chats/${chat.id}/repair`, json('POST', { project: tool.project, name: tool.name, published: true, confirmed: true }))
  await enterChat(chat.id); await refreshNavigation()
}
async function showSettings() {
  if (page.value === 'settings') return
  if (!settingsLoaded.value) {
    connections.value = (await api('/settings/models')).connections
    capabilityState.value = await api('/settings/capabilities')
    loadProvider(); settingsLoaded.value = true
  }
  settingsReturnPage.value = page.value; page.value = 'settings'
}
async function discoverModels() {
  const names = await api('/settings/models/discover', json('POST', { provider: provider.value, ...connection.value, models: [], vision_models: [] }))
  connection.value.models = names.join('\n')
}
async function importCapability() {
  const input = document.createElement('input'); input.type = 'file'; input.accept = '.zip'
  input.onchange = () => void attempt(async () => {
    const file = input.files?.[0]; if (!file) return
    await ElMessageBox.confirm(`${file.name}\n${t('确认导入此能力插件？将校验签名、平台与文件完整性。')}`, t('能力插件'), { type: 'warning' })
    importingCapability.value = true
    try {
      const form = new FormData(); form.append('file', file)
      await api('/settings/capabilities/import?confirmed=true', { method: 'POST', body: form })
      capabilityState.value = await api('/settings/capabilities'); ElMessage.success(t('导入成功'))
    } finally { importingCapability.value = false }
  })
  input.click()
}
function loadProvider() {
  const saved = connections.value[provider.value]
  connection.value = { base_url: saved?.base_url || 'https://api.openai.com/v1', key: '', models: (saved?.models || []).join('\n'), vision_models: (saved?.vision_models || []).join('\n') }
}
async function saveSettings() {
  if (settingsSaving.value) return
  settingsSaving.value = true
  try {
  await api('/settings/models', json('PUT', { provider: provider.value, ...connection.value,
    models: connection.value.models.split('\n').map(s => s.trim()).filter(Boolean),
    vision_models: connection.value.vision_models.split('\n').map(s => s.trim()).filter(Boolean) }))
  connection.value.key = ''; await bootstrap()
  connections.value = (await api('/settings/models')).connections
  loadProvider(); ElMessage.success(t('设置已保存'))
  } finally { settingsSaving.value = false }
}
async function setLanguage(value: string) { await api('/settings', json('PATCH', { language: value })); language.value = value }
function resize(event: PointerEvent, target: 'sidebar' | 'chat') {
  if (event.button !== 0) return
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
  const start = event.clientX, initial = target === 'sidebar' ? sidebarWidth.value : chatWidth.value
  const move = (next: PointerEvent) => {
    const value = Math.min(target === 'sidebar' ? 360 : innerWidth * .7, Math.max(target === 'sidebar' ? 190 : 320, initial + next.clientX - start))
    if (target === 'sidebar') sidebarWidth.value = value; else chatWidth.value = value
  }
  const end = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', end); localStorage.setItem(`${target}-width`, String(target === 'sidebar' ? sidebarWidth.value : chatWidth.value)) }
  window.addEventListener('pointermove', move); window.addEventListener('pointerup', end)
}
onMounted(() => {
  // The bundled Tauri page waits for Rust to navigate to the ready backend.
  if (!['http:', 'https:'].includes(location.protocol)) return
  void bootstrap().catch(failure => { failed.value = failure.message })
  checkTimer = setInterval(() => { void pollBuildCheck() }, 1500)
  diagnosticTimer = setInterval(() => { void pollDiagnosticRequests().catch(() => {}) }, 1000)
  window.addEventListener('calabash-native-files', onNativeFiles)
  window.addEventListener('resize', onResize)
})
const onResize = () => { viewportWidth.value = innerWidth }
const onNativeFiles = (event: Event) => { void attempt(() => nativeFiles(event)) }
const onFrameMessage = (event: MessageEvent) => { void attempt(() => frameMessage(event)) }
onMounted(() => window.addEventListener('message', onFrameMessage))
onBeforeUnmount(() => { stream?.close(); clearInterval(diagnosticTimer); clearInterval(checkTimer); window.removeEventListener('calabash-native-files', onNativeFiles); window.removeEventListener('message', onFrameMessage); window.removeEventListener('resize', onResize) })
</script>

<template>
  <div v-if="!ready" class="startup">
    <img class="startup-mark" :src="logo" alt="Calabash" /><h1>Calabash</h1>
    <p>{{ failed || '正在准备你的本地工具 / Preparing your workspace' }}</p>
    <el-button v-if="failed" @click="attempt(bootstrap)">{{ t('重试') }}</el-button>
    <el-progress v-else :percentage="60" :indeterminate="true" :show-text="false" />
  </div>
  <div v-else class="workspace">
    <header class="titlebar" data-tauri-drag-region><el-button :icon="Setting" circle text :class="{ selected: page === 'settings' }" :aria-label="t('设置')" :title="t('设置')" @click="attempt(showSettings)" /></header>
    <div class="workspace-body">
      <aside class="sidebar" :class="{ collapsed }" :style="{ width: collapsed ? '52px' : `${sidebarWidth}px` }">
        <div class="brand"><img class="brand-mark" :src="logo" alt="Calabash" /><strong v-if="!collapsed">Calabash</strong><el-button class="sidebar-toggle" :icon="collapsed ? Expand : Fold" text :aria-label="t('切换侧边栏')" :title="t('切换侧边栏')" @click="collapsed = !collapsed" /></div>
        <nav>
          <button class="nav-item" :title="t('新对话')" @click="attempt(newChat)"><el-icon><ChatLineRound /></el-icon><span v-if="!collapsed">{{ t('新对话') }}</span></button>
          <button class="nav-item" :title="t('工具')" :class="{ active: page === 'tools' }" @click="page = 'tools'"><el-icon><Folder /></el-icon><span v-if="!collapsed">{{ t('工具') }}</span></button>
          <button class="nav-item" :title="t('已打开工具')" :class="{ active: page === 'opened' }" @click="page = 'opened'"><el-icon><Expand /></el-icon><span v-if="!collapsed">{{ t('已打开工具') }}<span v-if="openTools.length" class="opened-count">{{ openTools.length }}</span></span></button>
        </nav>
        <div v-if="!collapsed" class="recent-list">
          <h3>{{ t('最近对话') }}</h3>
          <div v-for="chat in chats" :key="chat.id" class="recent-row" :class="{ active: page === 'chat' && chatId === chat.id }">
            <button class="recent-name" @click="attempt(() => enterChat(chat.id))"><span v-if="chat.running" class="running-dot" />{{ chat.title }}</button>
            <el-dropdown trigger="click" @command="(action: string) => attempt(() => chatAction(action, chat))"><el-button text :icon="MoreFilled" :aria-label="t('更多操作')" :title="t('更多操作')" /><template #dropdown><el-dropdown-menu><el-dropdown-item command="rename">{{ t('重命名') }}</el-dropdown-item><el-dropdown-item command="delete" :disabled="chat.running">{{ t('删除对话') }}</el-dropdown-item></el-dropdown-menu></template></el-dropdown>
          </div>
          <h3>{{ t('最近工具') }}</h3>
          <button v-for="tool in tools.slice(0, 10)" :key="toolKey(tool)" class="recent-name tool-shortcut" @click="attempt(() => openTool(tool))">{{ tool.title }}</button>
        </div>
      </aside>
      <div v-if="!collapsed" class="resize-handle" role="separator" :aria-label="t('调整菜单宽度')" :title="t('调整菜单宽度')" @pointerdown.prevent="resize($event, 'sidebar')" />
      <main class="main-workspace">
        <section v-show="page === 'tools'" class="tool-list">
          <div class="tools-heading">
            <div class="tools-heading-title"><h1>{{ t('工具') }}</h1><span class="tool-count">{{ tools.length }}</span></div>
            <div class="tools-heading-actions"><el-button size="small" :icon="Upload" @click="attempt(importTool)">{{ t('导入工具') }}</el-button><el-button size="small" type="primary" :icon="Plus" @click="attempt(newChat)">{{ t('创建工具') }}</el-button></div>
          </div>
          <div class="tools-toolbar"><el-input v-model="search" :prefix-icon="Search" clearable :placeholder="t('搜索工具')" :aria-label="t('搜索工具')" /><span v-if="search" class="tool-count">{{ filteredTools.length }} / {{ tools.length }}</span><span class="spacer" /><el-button :icon="Refresh" text :aria-label="t('刷新列表')" :title="t('刷新列表')" @click="attempt(refreshNavigation)" /></div>
          <el-empty v-if="!filteredTools.length" :description="t(tools.length ? '没有匹配的工具' : '还没有工具，通过对话创建第一个工具')"><el-button v-if="tools.length" size="small" @click="search = ''">{{ t('清空搜索') }}</el-button><el-button v-else size="small" type="primary" :icon="Plus" @click="attempt(newChat)">{{ t('创建工具') }}</el-button></el-empty>
          <div v-for="tool in filteredTools" :key="toolKey(tool)" class="tool-row">
            <div class="tool-tile"><el-icon><Folder /></el-icon></div>
            <div class="tool-description"><div class="tool-title"><h3 :title="tool.title">{{ tool.title }}</h3></div><p :title="tool.description"><span class="tool-project">{{ tool.project }}</span><span v-if="tool.description" class="tool-summary">{{ tool.description }}</span></p></div>
            <div class="tool-row-actions">
              <el-button size="small" :icon="ChatLineRound" text :aria-label="t('对话修改')" :title="t('对话修改')" @click="attempt(() => modifyTool(tool))"><span class="tool-action-label">{{ t('对话修改') }}</span></el-button>
              <el-button size="small" class="tool-open" :title="t('打开工具')" :loading="opening.has(toolKey(tool))" @click="attempt(() => openTool(tool))">{{ t('打开') }}</el-button>
              <el-button size="small" :icon="Download" text :aria-label="t('导出工具')" :title="t('导出工具')" @click="attempt(() => toolAction('export', tool))" />
              <el-button size="small" class="tool-delete" :icon="Delete" text :aria-label="t('删除工具')" :title="t('删除工具')" @click="attempt(() => toolAction('delete', tool))" />
            </div>
          </div>
        </section>
        <section v-show="page === 'opened'" class="opened-workspace">
          <div v-if="openTools.length" class="tool-tabs">
            <div class="tool-tab-list" role="tablist" :aria-label="t('已打开工具')">
              <div v-for="tool in openTools" :key="toolKey(tool)" class="tool-tab" :class="{ selected: selectedTool === toolKey(tool) }" role="presentation">
                <button :id="'tool-tab-' + toolKey(tool)" role="tab" :aria-selected="selectedTool === toolKey(tool)" :aria-controls="'tool-panel-' + toolKey(tool)" :tabindex="selectedTool === toolKey(tool) ? 0 : -1" :title="tool.title" @click="selectedTool = toolKey(tool)" @keydown="navigateToolTab($event, tool)">{{ tool.title }}</button>
                <el-button :icon="Close" text :aria-label="t('关闭工具') + ': ' + tool.title" :title="t('关闭工具')" @click="attempt(() => closeTool(tool))" />
              </div>
            </div>
            <div v-if="activeTool" class="tool-workspace-actions">
              <el-button size="small" :icon="ChatLineRound" text :title="t('通过对话调整这个工具')" @click="attempt(() => modifyTool(activeTool!))">{{ t('对话修改') }}</el-button>
              <el-button :icon="MagicStick" text :aria-label="t('修复工具问题')" :title="t('修复工具问题')" @click="attempt(() => repairTool(activeTool!))" />
              <el-button :icon="Refresh" text :aria-label="t('刷新工具')" :title="t('刷新工具')" @click="attempt(() => refreshTool(activeTool!))" />
            </div>
          </div>
          <el-empty v-if="!openTools.length" class="opened-empty" :description="t('还没有打开工具')"><el-button type="primary" size="small" @click="page = 'tools'">{{ t('去工具列表') }}</el-button></el-empty>
          <div v-if="activeTool && activeProblem" class="preview-check failed" role="alert"><span>{{ t('工具暂时未能完成操作，请重试或让 AI 帮你修复') }}</span><el-button text size="small" @click="attempt(() => repairTool(activeTool!))">{{ t('让 AI 帮我修复') }}</el-button></div>
          <iframe v-for="tool in openTools" v-show="selectedTool === toolKey(tool)" :id="'tool-panel-' + toolKey(tool)" :key="toolKey(tool)" role="tabpanel" :aria-labelledby="'tool-tab-' + toolKey(tool)" :src="tool.url" :title="tool.title" sandbox="allow-scripts allow-same-origin allow-downloads allow-forms" />
        </section>
        <section v-show="page === 'chat'" class="chat-workspace">
          <div class="chat-column" :style="{ width: previewShown ? `${effectiveChatWidth}px` : '100%' }">
            <div class="panel-heading"><span>{{ t('AI 对话') }}</span><el-button :icon="Expand" text :aria-label="t('打开预览')" :title="t('打开预览')" @click="togglePreview" /></div>
            <div class="messages" aria-live="polite">
              <template v-for="(message, index) in messages" :key="index"><div v-if="['user', 'assistant'].includes(message.role) && message.content" class="message" :class="message.role"><div v-if="message.role === 'assistant'" class="markdown" v-html="markdown(message.content)" /><div v-else>{{ message.content }}</div><div v-if="message.attachments?.length" class="message-files"><template v-for="fileId in message.attachments" :key="fileId"><img v-if="imageFile(fileId)" :src="`/api/workspace/chats/${chatId}/images/${fileId}`" :alt="chatFiles.find(item => item.id === fileId)?.name || t('图片')" loading="lazy" /><el-tag v-else>{{ chatFiles.find(item => item.id === fileId)?.name || t('附件') }}</el-tag></template></div></div></template>
              <el-collapse v-if="activity.length"><el-collapse-item :title="`${t('执行过程')} · ${activity.length}`"><div v-for="(step, index) in activity" :key="index" class="activity-step">{{ t(activityLabels[step] || '正在处理工具') }}</div></el-collapse-item></el-collapse>
              <div v-if="liveText" class="message assistant markdown" v-html="markdown(liveText)" /><div v-else-if="running" class="generation-indicator" role="status"><span class="generation-dots" aria-hidden="true"><i /><i /><i /></span><span>{{ t('正在生成…') }}</span></div>
              <el-alert v-if="error" :title="t(displayError(error))" type="error" show-icon :closable="false"><el-button v-if="!running" text @click="attempt(resumeGeneration)">{{ t('继续生成') }}</el-button></el-alert>
            </div>
            <div class="composer" :class="{ 'is-generating': running }" :aria-busy="running" @dragover.prevent @drop.prevent="!nativeHost && attempt(() => uploadFiles(Array.from($event.dataTransfer?.files || [])))">
              <div v-if="attachments.length" class="attachment-list"><el-tag v-for="file in attachments" :key="file.id" closable @close="attempt(async () => { await api(`/chats/${chatId}/attachments/${file.id}`, json('DELETE')); attachments = attachments.filter(item => item.id !== file.id) })">{{ file.name }}</el-tag></div>
              <div v-if="uiMatches.length && !running" class="ui-suggestions" :aria-label="t('选择工具风格')"><button v-for="preset in uiMatches" :key="preset.id" @click="insertUI(preset)"><i :style="{background:preset.color}" /><span>{{ t(preset.title) }}</span><small>{{ t(preset.description) }}</small></button></div>
              <el-input v-model="draft" type="textarea" :autosize="{ minRows: 2, maxRows: 7 }" :aria-label="t('描述你想创建或修改的工具…')" :placeholder="t(running ? '正在处理你的需求…' : '描述你想创建或修改的工具…')" :disabled="running" @keydown="keydown" @compositionstart="composing = true" @compositionend="composing = false; compositionEnded = clock()" @paste="paste" />
              <div class="composer-actions"><el-button :icon="Paperclip" text :disabled="running" :aria-label="t('添加文件')" :title="t('添加文件')" @click="attempt(selectFiles)" /><el-select v-model="model" :disabled="running" :placeholder="t('选择模型')" @change="(value: string) => attempt(() => api('/settings', json('PATCH', { model: value })))"><el-option v-for="(label, key) in models" :key="key" :label="label" :value="key" /></el-select><el-dropdown @command="(id: string) => { const selected = uiPresets.find(p => p.id === id); if (selected) insertUI(selected) }"><el-button class="ui-picker" text :disabled="running" :title="t('默认工具风格') + ': ' + t(uiPresets.find(p => p.id === defaultUI)?.title || '')">{{ t('界面风格') }}</el-button><template #dropdown><el-dropdown-menu><el-dropdown-item v-for="preset in uiPresets" :key="preset.id" :command="preset.id">{{ t(preset.title) }}{{ preset.id === defaultUI ? ' · ' + t('默认') : '' }}</el-dropdown-item></el-dropdown-menu></template></el-dropdown><span class="spacer" /><span v-if="running" class="composer-status"><span class="status-pulse" aria-hidden="true" /><span>{{ t('正在生成…') }}</span></span><el-button v-if="running" class="composer-stop" :aria-label="t('停止生成')" :title="t('停止生成')" @click="attempt(() => api(`/chats/${chatId}/cancel`, json('POST')))"><span class="stop-glyph" aria-hidden="true" /></el-button><el-button v-else class="composer-submit" type="primary" :icon="Top" :loading="submitting" :disabled="!draft.trim() || uploading || submitting" :aria-label="t('发送')" :title="t('发送')" @click="attempt(send)" /></div>
              <p class="composer-hint">{{ t('可选择、拖入或粘贴图片；发送图片会将图片内容提交给所选模型服务') }}</p>
            </div>
          </div>
          <div v-if="previewShown" class="resize-handle" role="separator" :aria-label="t('调整预览宽度')" :title="t('调整预览宽度')" @pointerdown.prevent="resize($event, 'chat')" />
          <div v-if="previewShown" class="preview-column"><div class="panel-heading"><span>{{ t('工具预览') }}</span><div><el-button :icon="MagicStick" text :aria-label="t('让 AI 帮我修复')" :title="t('让 AI 帮我修复')" :disabled="!preview || running" @click="attempt(repairPreview)" /><el-button :icon="View" text :aria-label="t('让 AI 检查界面')" :title="t('让 AI 检查界面')" :disabled="!preview" @click="attempt(grantDiagnostics)" /><el-button :icon="FolderAdd" text :aria-label="t('保存到工具列表')" :title="t('保存到工具列表')" :disabled="!preview || buildCheck?.state !== 'passed' || manualPreviewPending || Boolean(checkError) || previewProblem" :loading="publishing" @click="attempt(publishPreview)" /><el-button :icon="Refresh" text :aria-label="t('刷新预览')" :title="t('刷新预览')" @click="attempt(loadPreview)" /><el-button :icon="Close" text :aria-label="t('关闭预览')" :title="t('关闭预览')" @click="togglePreview" /></div></div><el-alert v-if="manualPreviewPending" :title="t('修改已保存，请手动刷新预览')" type="info" :closable="false"><el-button text @click="attempt(loadPreview)">{{ t('刷新预览') }}</el-button></el-alert><div v-if="preview" class="preview-check" :class="previewProblem ? 'failed' : buildCheck?.state" aria-live="polite">
            <span v-if="checkError">{{ checkError }}</span><span v-else>{{ t(previewProblem ? '试用时遇到问题，请先修复' : buildCheck?.state === 'passed' ? '工具已准备好预览' : buildCheck?.state === 'failed' ? '工具还需要调整，可以让 AI 帮你修复' : '正在准备工具…') }}</span>
            <el-button v-if="buildCheck?.state === 'failed' || previewProblem" text size="small" :disabled="running" @click="attempt(repairPreview)">{{ t('让 AI 帮我修复') }}</el-button>
            <el-button v-if="checkError || buildCheck?.state === 'failed'" text size="small" @click="pollBuildCheck(true)">{{ t('重试') }}</el-button>
            <small v-if="buildCheck?.state === 'passed' && !previewProblem">{{ t('保存前请试用一下，确认符合你的需要') }}</small>
          </div><iframe v-if="previewRuntime" :key="previewRevision" :src="previewRuntime" :title="t('工具预览')" sandbox="allow-scripts allow-same-origin allow-downloads allow-forms" /><el-empty v-else :description="t('暂无工具预览')" /></div>
        </section>
        <section v-show="page === 'settings'" class="settings-page" :aria-label="t('设置')">
          <div class="settings-content">
            <header class="settings-heading"><div><h1>{{ t('设置') }}</h1><p>{{ t('管理你的工作区、模型连接和本地能力。') }}</p></div><el-button :icon="ArrowLeft" text @click="page = settingsReturnPage">{{ t('返回') }}</el-button></header>
            <section class="settings-section">
              <div class="settings-section-intro"><h2>{{ t('通用') }}</h2><p>{{ t('让工作区更符合你的使用习惯。') }}</p></div>
              <el-form label-position="top" class="settings-fields"><el-form-item :label="t('界面语言')"><el-select class="language-select" :model-value="language" @change="(value: string) => attempt(() => setLanguage(value))"><el-option label="简体中文" value="zh-CN" /><el-option label="English" value="en" /></el-select></el-form-item><el-form-item :label="t('默认工具风格')"><el-select :model-value="defaultUI" @change="(value: string) => attempt(() => setDefaultUI(value))"><el-option v-for="preset in uiPresets" :key="preset.id" :value="preset.id" :label="t(preset.title)" /></el-select><p class="setting-hint">{{ t('仅用于新工具；已有工具保留原来的风格。创建时输入 @ 可单独选择。') }}</p></el-form-item></el-form>
            </section>
            <section class="settings-section">
              <div class="settings-section-intro"><h2>{{ t('模型连接') }}</h2><p>{{ t('使用你自己的模型服务，密钥仅保存在本机。') }}</p></div>
              <el-form label-position="top" class="settings-fields" @submit.prevent="attempt(saveSettings)">
                <el-form-item :label="t('模型服务')"><el-select v-model="provider" @change="loadProvider"><el-option v-for="name in ['openai', 'deepseek', 'anthropic', 'qwen']" :key="name" :value="name" :label="name" /></el-select></el-form-item>
                <el-form-item label="API URL"><el-input v-model="connection.base_url" placeholder="https://" /></el-form-item>
                <el-form-item label="API Key"><el-input v-model="connection.key" type="password" show-password :placeholder="connections[provider]?.configured ? t('已配置，留空保持不变') : ''" autocomplete="off" /></el-form-item>
                <div class="settings-model-grid">
                  <el-form-item :label="t('模型 ID，每行一个')"><el-input v-model="connection.models" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }" /><el-button class="discover-models" text :icon="Refresh" @click="attempt(discoverModels)">{{ t('获取模型') }}</el-button></el-form-item>
                  <el-form-item :label="t('支持图片的自定义模型 ID，每行一个')"><el-input v-model="connection.vision_models" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }" /></el-form-item>
                </div>
                <div class="settings-save"><el-button type="primary" native-type="submit" :loading="settingsSaving">{{ t('保存连接') }}</el-button></div>
              </el-form>
            </section>
            <section class="settings-section">
              <div class="settings-section-intro"><h2>{{ t('能力插件') }}</h2><p>{{ t('从本地 ZIP 导入，扩展工具的处理能力。') }}</p></div>
              <div class="settings-fields"><div class="capability-list"><div v-for="(pack, index) in capabilityState.packs" :key="index" class="capability-row"><span>{{ (pack.id || ['media.ffmpeg', 'document.ocr'][index]) === 'media.ffmpeg' ? 'FFmpeg' : t('文字识别（OCR）') }}</span><el-tag size="small" :type="pack.state === 'ready' ? 'success' : pack.state === 'invalid' ? 'danger' : 'info'">{{ t(capabilityLabels[pack.state] || '暂不可用') }}</el-tag><span v-if="pack.version" class="capability-version">{{ pack.version }}</span></div></div><el-button :icon="Upload" :loading="importingCapability" :disabled="!capabilityState.configured" @click="attempt(importCapability)">{{ t('导入 ZIP') }}</el-button></div>
            </section>
          </div>
        </section>
      </main>
    </div>

  </div>
</template>
