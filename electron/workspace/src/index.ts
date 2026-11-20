/** Calabash host plugin: authenticated UI Remote and bounded model tools. */
import { Context } from '@deepseek-ai/cordis'
import { Remote, TypertRemoteService } from '@deepseek-ai/dsh-typert-protocol'
import { z } from 'zod'
import type { Session } from '@deepseek-ai/dsh-session'
import type {} from '@deepseek-ai/dsh-session-projection'
import { requestedStyle } from './style-selection.ts'
import { operations, callPresentation, resultPresentation } from './tool-presentation.ts'
import { defineTool } from '@deepseek-ai/dsh-tools'
import type {} from '@deepseek-ai/dsh-agent'
import { join } from 'node:path'
import { WorkspaceState } from './workspace-state.ts'
import { HostTasks } from './tasks.ts'
import { PythonBridge } from './bridge.ts'
import { AIActionHost } from './ai-actions.ts'
import type {} from '@deepseek-ai/dsh-llm'
import type { AgentArguments } from './types.ts'
export type { ToolEntry, ToolTarget, Preview, AgentArguments } from './types.ts'

declare module '@deepseek-ai/dsh-session-projection' { interface SessionProjectionMap { calabashStyle: string | null } }
declare module '@deepseek-ai/cordis' { interface Context { calabashWorkspace: CalabashWorkspace } }
export default class CalabashWorkspace extends TypertRemoteService {
  static inject = ['tools', 'sessionProjections']
  private previewListeners = new Map<string, Set<() => void>>()
  private previewChecks = new Map<string, Promise<void>>()
  private ai: AIActionHost
  private styleReady: Promise<unknown>
  private bridge = new PythonBridge()
  private tasks = new HostTasks(process.env.DSH_HOME ? join(process.env.DSH_HOME, 'calabash') : undefined)
  private workspace = new WorkspaceState(process.env.DSH_HOME ? join(process.env.DSH_HOME, 'calabash') : undefined)
  @Remote
  async loadWorkspace(): Promise<string> { return JSON.stringify(this.workspace.read()) }
  @Remote
  async saveWorkspace(input: string): Promise<void> { if (input.length > 10000) throw new Error('Workspace too large'); this.workspace.write(JSON.parse(input)) }
  constructor(ctx: Context) {
    super(ctx, 'calabashWorkspace')
    void this.bridge.call('schedules.action', { operation: 'list', arguments: {} }).catch(() => ctx.logger.warn('Tool schedules unavailable'))
    this.ai = new AIActionHost(this.bridge, () => ctx.get('llm'), Date.now, event => ctx.logger.info('AI Action metadata %j', event))
    ctx.on('llm/adapters-updated', () => this.ai.invalidate())
    this.styleReady = ctx.sessionProjections.register<'calabashStyle', string | null>({
      key: 'calabashStyle', stateSchema: z.string().nullable(), init: () => null, stateVersion: 1,
      apply: (current, event) => event.type === 'user/message' && event.data.source?.kind === 'user'
        ? requestedStyle(event.data.content.flatMap(block => block.type === 'text' ? [block.text] : []).join('\n'))
        : current,
      wire: { viewSchema: z.string().nullable(), view: current => current, summary: false },
    })
    ctx.effect(() => async () => { await this.ai.stop(); await this.tasks.drain(); await this.bridge.stop() })
    ctx.on('session/event', (session, event) => {
      if (event.type === 'turn/end') void this.bridge.call('agent.release', { session: session.id }).then(() => this.notifyPreview(session.id)).catch(() => undefined)
    })
    ctx.tools.register(defineTool({
      name: 'calabash_tool',
      description: 'Create and edit Calabash local office tools (React + Ant Design + Python). Read instructions once before authoring; reuse them while available in this conversation. Use read_tool_template for a new tool. Read current source before editing. Use check_tool_build before finishing; read_preview_diagnostics reports safe current-run page/API evidence without executing business operations. Source is saved as a draft; the visible preview pane opens ready drafts; users confirm saves and business operations. Never execute, publish, install dependencies or access arbitrary files. One tool per conversation.',
      parameters: {
        action_id: { type: 'string', description: 'Built-in AI action identity for read_action_api; omit to list actions. Discovery only, never executes.' },
        operation: { type: 'string', required: true, enum: operations, description: 'Bounded Calabash operation.' },
        reference: { type: 'string', description: 'One built-in reference: react-tool.md, design.md, api-contract.md, file-workflow.md, lifecycle.md, quality-gate.md, frontend-debug.md, ai-actions.md.' },
        component: { type: 'string', description: 'Ant Design component, such as Table.' },
        property_name: { type: 'string', description: 'One component prop or event.' },
        project: { type: 'string', description: 'Tool project, default for new office tools.' },
        name: { type: 'string', description: 'Lowercase tool identity using letters, digits and underscores.' },
        path: { type: 'string', description: 'Source path from read_tool or template, never an absolute path.' },
        content: { type: 'string', description: 'Complete text for write_tool_file.' },
        old: { type: 'string', description: 'One unique literal existing fragment for patch_tool_file.' },
        new: { type: 'string', description: 'Replacement fragment.' },
        offset: { type: 'integer', description: 'Zero-based source line offset.' },
        limit: { type: 'integer', description: 'Source page size, at most 150.' },
      },
      output: { schema: { type: 'string' }, render: (_args, value) => [{ type: 'text', text: value }] },
      async execute(args, exec) {
        if (!exec.agent) throw new Error('Calabash authoring requires a conversation')
        const { operation, ...arguments_ } = args
        const result = await ctx.calabashWorkspace.agent(operation, arguments_, exec.agent.session.id, exec.callId, await ctx.calabashWorkspace.styleFor(exec.agent.session))
        return result
      },
      presentCall: callPresentation,
      presentResult: resultPresentation,
    }))
  }
  @Remote
  async aiPending(): Promise<string> { return JSON.stringify(await this.ai.pending()) }
  @Remote
  async aiModels(): Promise<string> { return JSON.stringify(await this.ai.models()) }
  @Remote
  async aiReview(worker: string, request: string, model: string): Promise<string> { return JSON.stringify(await this.ai.review(worker,request,model)) }
  @Remote
  async aiApprove(review: string): Promise<string> { await this.ai.approve(review); return JSON.stringify({returned:true}) }
  @Remote
  async aiCancel(review: string): Promise<string> { this.ai.cancel(review); return JSON.stringify({stopping:true}) }
  @Remote
  async aiReject(worker: string, request: string): Promise<string> { await this.ai.reject(worker,request); return JSON.stringify({rejected:true}) }
  /** Execute one model operation using the owning Agent's session, never model-supplied session metadata. */
  async styleFor(session: Session): Promise<string | null> {
    await this.styleReady
    return this.ctx.sessionProjections.snapshot(session, ['calabashStyle']).values.calabashStyle ?? null
  }
  async agent(operation: string, args: AgentArguments, session: string, callId: string, requestedPreset: string | null = null): Promise<string> {
    const input = { session, call_id: callId, operation, arguments: args, requested_preset: requestedPreset }
    const resource = args.project && args.name ? `tool:${args.project}/${args.name}` : `session:${session}`
    const id = this.tasks.submit('agent.call', input, resource, `agent:${session}:${callId}`, () => this.bridge.call('agent.call', input))
    const result = await this.tasks.wait(id)
    if (['check_tool_build', 'write_tool_file', 'patch_tool_file'].includes(operation)) this.notifyPreview(session)
    return JSON.stringify(result)
  }
  private notifyPreview(session: string): void { for (const wake of this.previewListeners.get(session) ?? []) wake() }
  private checkExistingPreview(session: string): void {
    if (this.previewChecks.has(session)) return
    const id = this.tasks.submit('workspace.check_preview', {session}, `session:${session}`, `preview-check:${session}:${crypto.randomUUID()}`, () => this.bridge.call('workspace.check_preview', {session}))
    const done = this.tasks.wait(id).then(() => { this.notifyPreview(session) }, () => { this.notifyPreview(session) }).finally(() => { this.previewChecks.delete(session) })
    this.previewChecks.set(session, done)
  }
  /** Push current-version build readiness; the stream never starts or refreshes a worker. */
  @Remote({mode:'stream'})
  async *watchPreview(session: string, signal: AbortSignal): AsyncIterable<string> {
    if (!session || session.length > 200) throw new Error('Invalid session')
    let pending = true, wake: (() => void) | undefined
    const changed = () => { pending = true; wake?.() }
    const listeners = this.previewListeners.get(session) ?? new Set<() => void>()
    listeners.add(changed); this.previewListeners.set(session, listeners)
    signal.addEventListener('abort', changed, {once:true})
    try {
      this.checkExistingPreview(session)
      while (!signal.aborted) {
        if (pending) {
          pending = false
          yield JSON.stringify(await this.bridge.call('workspace.binding', {session}))
          continue
        }
        await new Promise<void>(resolve => { wake = resolve })
        wake = undefined
      }
    } finally {
      listeners.delete(changed); if (!listeners.size) this.previewListeners.delete(session)
      signal.removeEventListener('abort', changed)
    }
  }
  /** UI submits a bounded operation once and can requery it after a disconnect/observer timeout. */
  @Remote
  async schedules(operation: string, input: string): Promise<string> {
    if (input.length > 4096 || !['list','tasks','create','pause','resume','remove','run'].includes(operation)) throw new Error('Invalid schedule operation')
    return JSON.stringify(await this.bridge.call('schedules.action', { operation, arguments: JSON.parse(input) }))
  }
  @Remote
  async startOperation(operation: string, input: string, requestId: string): Promise<string> {
    if (!/^[a-zA-Z0-9-]{1,80}$/.test(requestId) || input.length > 300000) throw new Error('Invalid task request')
    const params = JSON.parse(input) as Record<string, unknown>
    const allowed = ['tools.open', 'tools.close', 'workspace.preview', 'workspace.publish', 'library.action']
    if (!allowed.includes(operation) || operation === 'library.action' && params.operation !== 'import') throw new Error('Unsupported task')
    const resource = params.project && params.name ? `tool:${String(params.project)}/${String(params.name)}` : params.session ? `session:${String(params.session)}` : 'library:import'
    return this.tasks.submit(operation, params, resource, `ui:${requestId}`, () => this.bridge.call(operation, params))
  }
  @Remote
  async listTasks(): Promise<string> { return JSON.stringify(this.tasks.list()) }
  @Remote
  async task(id: string): Promise<string> { return JSON.stringify(this.tasks.inspect(id)) }
  /** Host quit inspection includes long-running Python tool jobs. */
  async activeTasks(): Promise<boolean> { if (this.tasks.busy) return true; if (!this.bridge.started) return false; return await this.bridge.call('app.active_tasks', {}) === true }
  /** Read-only capability discovery; no execution or user data. */
  @Remote
  async actionCatalog(): Promise<string> { return JSON.stringify(await this.bridge.call('actions.catalog', {})) }
  /** Bilingual style catalog for the composer; no user paths or source. */
  @Remote
  async uiPresets(): Promise<string> { return JSON.stringify(await this.bridge.call('ui.presets', {})) }
  /** Host UI only: inert ZIP transfers, confirmed library operations and conversation binding. */
  @Remote
  async library(operation: string, input: string): Promise<string> {
    if (input.length > 300000) throw new Error('Library request too large')
    const args = JSON.parse(input) as Record<string, unknown>
    const value = await this.bridge.call('library.action', { operation, arguments: args })
    if (operation === 'conversation' && typeof args.session === 'string') { this.notifyPreview(args.session); this.checkExistingPreview(args.session) }
    return JSON.stringify(value)
  }
  /** List published tools without source or filesystem paths. */
  @Remote
  async list(): Promise<string> { return JSON.stringify(await this.bridge.call('tools.list', {})) }
  /** Open one published tool after a user click. */
  @Remote
  async open(project: string, name: string): Promise<string> { return JSON.stringify(await this.bridge.call('tools.open', { project, name })) }
  /** Safely stop and close a published tool. A running file is allowed to finish first. */
  @Remote
  async close(project: string, name: string): Promise<string> { return JSON.stringify(await this.bridge.call('tools.close', { project, name })) }
  /** Read the current conversation's target; does not run source. */
  @Remote
  async state(session: string): Promise<string> { return JSON.stringify(await this.bridge.call('workspace.state', { session })) }
  /** Bound editing target and a safe UI recovery hint; no source or credentials. */
  @Remote
  async binding(session: string): Promise<string> { return JSON.stringify(await this.bridge.call('workspace.binding', { session })) }
  @Remote
  async verification(session: string): Promise<string> { return JSON.stringify(await this.bridge.call('workspace.verification', { session })) }
  /** Build and open the current conversation draft. */
  @Remote
  async preview(session: string, refresh: boolean): Promise<string> { return JSON.stringify(await this.bridge.call('workspace.preview', { session, refresh })) }
  /** Close a preview without stopping the conversation. */
  @Remote
  async closePreview(session: string): Promise<string> { return JSON.stringify(await this.bridge.call('workspace.close', { session })) }
  /** Explicitly save a checked preview; caller confirms replacement of the displayed published revision. */
  @Remote
  async publish(session: string, expected: string, replaceRevision: string, confirmed: boolean): Promise<string> {
    return JSON.stringify(await this.bridge.call('workspace.publish', { session, expected, replace_revision: replaceRevision, confirmed }))
  }
}
