/** Inert Action references: discovery and selection never execute an Action. */
import type { Context } from '@deepseek-ai/cordis'
import type { InputTriggerSource } from '@deepseek-ai/dsh-client-ui-input-trigger/client'
import type { ActionSummary } from '../types.ts'
export function registerActionMentions(ctx: Context, readCatalog: () => Promise<ActionSummary[]>): void {
  let catalog: ActionSummary[] = [], pending: Promise<ActionSummary[]> | undefined
  const listeners = new Set<() => void>()
  const load = () => pending ??= readCatalog().then(value => {
    const changed = JSON.stringify(catalog) !== JSON.stringify(value)
    catalog = value
    if (changed) for (const listener of listeners) listener()
    return value
  }).catch(error => { pending = undefined; throw error })
  const zh = () => ctx.locale.getSnapshot().active === 'zh'
  const source: InputTriggerSource = {
    trigger: '@', name: 'calabash-action', order: -40, showGroupTitle: false,
    warm() { void load().catch(() => undefined) },
    async candidates(_session, request) {
      if (request.quoted || request.drilled) return []
      // Refresh discovery so newly registered capabilities do not require UI changes.
      pending = undefined
      const actions = await load()
      if (request.signal.aborted) return []
      const raw = request.query.toLowerCase()
      const query = ['action', '能力', '可用能力'].includes(raw) ? '' : raw.replace(/^action:/, '')
      return actions.filter(action => [action.id, action.title, action.title_en, action.description, action.description_en].some(text => text.toLowerCase().includes(query))).map(action => ({
        name: `action:${action.id}`, label: zh() ? action.title : action.title_en,
        description: zh() ? action.description : action.description_en,
        section: zh() ? '可用能力' : 'Available actions', value: action.id,
      }))
    },
    onPick({ candidate }) {
      const action = catalog.find(value => value.id === candidate.value)
      if (!action) return undefined
      const ref = `@action:${action.id}`
      return { insert: { source: 'calabash-action', ref, label: zh() ? action.title : action.title_en, clipboardText: ref } }
    },
    lexicon() { return catalog.map(action => `action:${action.id}`) },
    subscribeLexicon(_session, listener) { listeners.add(listener); return () => { listeners.delete(listener) } },
    codec: {
      clipboardText: ref => ref,
      async serialize(ref, signal) {
        pending = undefined
        await load(); signal.throwIfAborted()
        const action = catalog.find(value => ref === `@action:${value.id}`)
        if (!action) throw new Error(zh() ? '此能力已不可用，请重新选择。' : 'This action is unavailable. Select an action again.')
        return `@action:${action.id}`
      },
    },
  }
  ctx.effect(() => ctx.inputTriggers.registerSource(source))
}
