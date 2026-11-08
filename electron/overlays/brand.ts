/** Calabash occupies official public branding slots; generated tool UI stays React. */
import type { Context } from '@deepseek-ai/cordis'
import { createElement } from 'react'
import type {} from '@deepseek-ai/dsh-client-ui-renderer/client'
import type {} from '@deepseek-ai/dsh-client-ui-sidebar/client'
export const inject = ['slots']
export function apply(ctx: Context): void {
  ctx.slots.inject('sidebar.brand.mark', () =>
    ctx.slots.inject('sidebar.brand.name', function* () {
      yield ctx.slots.register({ name: 'sidebar.brand.mark' }, ({ size }) => createElement('span', {
        style: { width: size, height: size, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          background: '#253e36', color: 'white', borderRadius: 6, fontWeight: 700 },
        'aria-label': 'Calabash',
      }, 'C'))
      yield ctx.slots.register({ name: 'sidebar.brand.name' }, () => createElement('span', null, 'Calabash'))
    }))
}
