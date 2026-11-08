/** Pure user-message projection: no model/tool text or whole prompt is retained. */
import { presetCatalog } from './presets.ts'
export function requestedStyle(text: string): string | null {
  let last = -1, selected: string | null = null
  for (const preset of presetCatalog) {
    for (const alias of [preset.id, preset.title, preset.mention, ...preset.aliases ?? []]) {
      const escaped = [...alias].map(char => '^$.*+?()[]{}|'.includes(char) || char === "\\" ? "\\" + char : char).join('')
      const pattern = new RegExp(`(^|\\s)@(?:ui:)?${escaped}(?=\\s|$|[，。,:：])`, 'gi')
      for (const match of text.matchAll(pattern)) {
        const position = (match.index ?? 0) + (match[1]?.length ?? 0)
        if (position >= last) { last = position; selected = preset.id }
      }
    }
  }
  return selected
}
