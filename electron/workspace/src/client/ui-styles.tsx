/** Calabash styles use DSH's native @ menu, chips, clipboard and draft codec. */
import type { Context } from '@deepseek-ai/cordis'
import type { InputTriggerSource } from '@deepseek-ai/dsh-client-ui-input-trigger/client'
import type { UIPreset } from '../types.ts'
export function registerUIStyles(ctx: Context, readCatalog: () => Promise<UIPreset[]>): void {
  let catalog: UIPreset[] | undefined, pending: Promise<UIPreset[]> | undefined
  const listeners = new Set<() => void>()
  const aliases = (preset: UIPreset) => [preset.id, preset.title, preset.mention, ...preset.aliases ?? []]
  const find = (ref: string) => {
    const name = ref.replace(/^@(?:ui:)?/i, '').toLowerCase()
    return catalog?.find(preset => aliases(preset).some(alias => alias.toLowerCase() === name))
  }
  const load = () => pending ??= readCatalog().then(value => {
    catalog = value
    for (const listener of listeners) listener()
    return value
  }).catch(error => { pending = undefined; throw error })
  const zh = () => ctx.locale.getSnapshot().active === 'zh'
  const source: InputTriggerSource = {
    trigger: '@', name: 'calabash-ui', order: -50, showGroupTitle: false,
    warm() { void load().catch(() => undefined) },
    async candidates(_session, request) {
      if (request.quoted || request.drilled) return []
      const presets = await load()
      if (request.signal.aborted) return []
      const raw = request.query.toLowerCase()
      const query = ['ui', '样式', '风格', '界面'].includes(raw) ? '' : raw.replace(/^ui:/, '')
      return presets.filter(preset => aliases(preset).some(alias => alias.toLowerCase().includes(query))).map(preset => ({
        name: `ui:${preset.id}`, label: zh() ? preset.title : preset.title_en ?? preset.mention,
        description: zh() ? preset.description : preset.description_en ?? preset.description,
        section: zh() ? '界面风格' : 'UI styles', value: preset.id,
        icon: ({ size = 16 }: { size?: number | undefined }) => <span aria-hidden="true" style={{ width: size, height: size, display: 'inline-block', borderRadius: 4, background: preset.color }} />,
      }))
    },
    onPick({ candidate }) {
      const preset = catalog?.find(value => value.id === candidate.value)
      if (!preset) return undefined
      return { insert: { source: 'calabash-ui', ref: `@ui:${preset.id}`, label: zh() ? preset.title : preset.title_en ?? preset.mention, clipboardText: `@ui:${preset.id}` } }
    },
    lexicon() { return catalog?.flatMap(preset => [...aliases(preset), `ui:${preset.id}`]) },
    subscribeLexicon(_session, listener) { listeners.add(listener); return () => { listeners.delete(listener) } },
    codec: {
      clipboardText: ref => ref,
      async serialize(ref, signal) {
        await load(); signal.throwIfAborted()
        const preset = find(ref)
        if (!preset) throw new Error('Style is unavailable. Select a style again.')
        return `@ui:${preset.id}`
      },
    },
  }
  ctx.effect(() => ctx.inputTriggers.registerSource(source))
}
