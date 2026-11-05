import assert from 'node:assert/strict'
import { requestMessage, displayError } from '../desktop-ui/src/request_errors.mjs'
for (const status of [400, 401, 403, 404, 409, 422, 429, 500, 503]) {
  const text = requestMessage(status, 'Traceback /private/secret.py:42 HTTP 500 TS2322 password=secret')
  assert(!/HTTP|Traceback|secret|TS2322|\d{3}/.test(text))
  assert(text.length > 0)
}
assert.match(requestMessage(409, 'Stop the running tool before replacing it'), /任务/)
assert.match(requestMessage(409, 'Preview changed during build'), /刷新预览/)
assert.match(requestMessage(500, {message: 'secret'}), /重试/)
console.log('Friendly request errors never expose server diagnostics')

const {readFileSync} = await import('node:fs')
const app = readFileSync(new URL('../desktop-ui/src/App.vue', import.meta.url), 'utf8')
const banner = app.slice(app.indexOf('class="preview-check"'), app.indexOf('<iframe v-if="previewRuntime"'))
assert(!/查看具体错误|check-revision|issue\.file|issue\.code|slice\(0, 8\)/.test(banner))
assert(banner.includes('让 AI 帮我修复'))
assert(!app.includes(':title="error"'))

assert(!displayError('请求失败（HTTP 500）').includes('500'))
assert(!displayError('frontend/App.vue:10 TS2322').includes('TS2322'))
assert.equal(displayError('工具正在处理任务，请完成后再保存'), '工具正在处理任务，请完成后再保存')
