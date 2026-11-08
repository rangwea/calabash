/** Calabash host plugin: authenticated UI Remote and bounded model tools. */
import { Context } from '@deepseek-ai/cordis'
import { Remote, TypertRemoteService } from '@deepseek-ai/dsh-typert-protocol'
import { z } from 'zod'
import type { Session } from '@deepseek-ai/dsh-session'
import type {} from '@deepseek-ai/dsh-session-projection'
import { requestedStyle } from './style-selection.ts'
import { defineTool } from '@deepseek-ai/dsh-tools'
import type {} from '@deepseek-ai/dsh-agent'
import type {} from '@deepseek-ai/dsh-session'
import { PythonBridge } from './bridge.ts'
import type { AgentArguments } from './types.ts'
export type { ToolEntry, ToolTarget, Preview, AgentArguments } from './types.ts'

declare module '@deepseek-ai/dsh-session-projection' { interface SessionProjectionMap { calabashStyle: string | null } }
declare module '@deepseek-ai/cordis' { interface Context { calabashWorkspace: CalabashWorkspace } }
const operations = ['instructions', 'list_tools', 'read_ui_reference', 'read_component_api', 'read_ui_preset', 'read_tool_template', 'read_tool', 'read_tool_file', 'write_tool_file', 'patch_tool_file', 'check_tool_build', 'read_build_diagnostics', 'read_api_contract']
export default class CalabashWorkspace extends TypertRemoteService {
  static inject = ['tools', 'sessionProjections']
  private styleReady: Promise<unknown>
  private bridge = new PythonBridge()
  constructor(ctx: Context) {
    super(ctx, 'calabashWorkspace')
    this.styleReady = ctx.sessionProjections.register<'calabashStyle', string | null>({
      key: 'calabashStyle', stateSchema: z.string().nullable(), init: () => null, stateVersion: 1,
      apply: (current, event) => event.type === 'user/message' && event.data.source?.kind === 'user'
        ? requestedStyle(event.data.content.flatMap(block => block.type === 'text' ? [block.text] : []).join('\n'))
        : current,
      wire: { viewSchema: z.string().nullable(), view: current => current, summary: false },
    })
    ctx.effect(() => () => this.bridge.stop())
    ctx.on('session/event', (session, event) => {
      if (event.type === 'turn/end') void this.bridge.call('agent.release', { session: session.id }).catch(() => undefined)
    })
    ctx.tools.register(defineTool({
      name: 'calabash_tool',
      description: 'Create and edit Calabash local office tools (Vue + Element Plus + Python). FIRST call instructions; use read_tool_template for a new tool. Read current source before editing. Use check_tool_build before finishing. Source is saved as a draft; user manually previews and saves to tool list. Never execute, publish, install dependencies or access arbitrary files. One tool per conversation.',
      parameters: {
        operation: { type: 'string', required: true, enum: operations, description: 'Bounded Calabash operation.' },
        reference: { type: 'string', description: 'One built-in reference: vue-tool.md, design.md, api-contract.md, file-workflow.md, lifecycle.md, quality-gate.md, frontend-debug.md.' },
        component: { type: 'string', description: 'Element Plus component, such as el-table.' },
        property_name: { type: 'string', description: 'One component prop or event.' },
        preset: { type: 'string', description: 'Built-in style pack identity, or omit for default.' },
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
      presentCall: args => ({ card: 'generic', title: `Calabash · ${args.operation}`, kind: 'other' }),
    }))
  }
  /** Execute one model operation using the owning Agent's session, never model-supplied session metadata. */
  async styleFor(session: Session): Promise<string | null> {
    await this.styleReady
    return this.ctx.sessionProjections.snapshot(session, ['calabashStyle']).values.calabashStyle ?? null
  }
  async agent(operation: string, args: AgentArguments, session: string, callId: string, requestedPreset: string | null = null): Promise<string> {
    return JSON.stringify(await this.bridge.call('agent.call', { session, call_id: callId, operation, arguments: args, requested_preset: requestedPreset }))
  }
  /** Host quit inspection includes long-running Python tool jobs. */
  async activeTasks(): Promise<boolean> { if (!this.bridge.started) return false; return await this.bridge.call('app.active_tasks', {}) === true }
  /** Bilingual style catalog for the composer; no user paths or source. */
  @Remote
  async uiPresets(): Promise<string> { return JSON.stringify(await this.bridge.call('ui.presets', {})) }
  /** Host UI only: inert ZIP transfers, confirmed library operations and conversation binding. */
  @Remote
  async library(operation: string, input: string): Promise<string> {
    if (input.length > 300000) throw new Error('Library request too large')
    return JSON.stringify(await this.bridge.call('library.action', { operation, arguments: JSON.parse(input) }))
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
  /** Build and manually open the current conversation draft. */
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
