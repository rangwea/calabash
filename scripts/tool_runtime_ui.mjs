import { defineComponent, h, ref, onMounted, onUnmounted, watch } from 'vue'
import { ElButton, ElProgress, ElTag } from 'element-plus'
let chartsLibrary
const loadCharts = () => chartsLibrary ||= import('echarts')
const nativeHost = ref(false)
if (window.parent !== window) void request('/status').then(state => { nativeHost.value = state.native_host === true }).catch(() => {})

export const CalabashChart = defineComponent({
  name: 'CalabashChart', props: { option: { type: Object, required: true }, height: { type: String, default: '280px' } },
  setup(props) {
    const element = ref(); let chart, observer, disposed = false
    onMounted(async () => {
      const echarts = await loadCharts()
      if (disposed) return
      chart = echarts.init(element.value); chart.setOption(props.option)
      observer = new ResizeObserver(() => chart?.resize()); observer.observe(element.value)
    })
    watch(() => props.option, value => chart?.setOption(value, true), { deep: true })
    onUnmounted(() => { disposed = true; observer?.disconnect(); chart?.dispose() })
    return () => h('div', { ref: element, style: { height: props.height, width: '100%', minWidth: 0 } })
  },
})

async function request(path, options) {
  const response = await fetch('/api/sdk' + path, options)
  if (!response.ok) throw new Error((await response.json()).detail || 'Request failed')
  return response.json()
}
function polling(load) {
  let timer
  onMounted(() => { void load(); timer = setInterval(() => { void load() }, 1000) })
  onUnmounted(() => clearInterval(timer))
}
export const CalabashFiles = defineComponent({
  name: 'CalabashFiles', emits: ['change'],
  setup(_, { emit }) {
    const files = ref([]), running = ref(false), error = ref(''), input = ref()
    const load = async () => {
      try { files.value = await request('/inputs'); running.value = (await request('/status')).running } catch (e) { error.value = e.message }
    }
    const remove = async id => { try { await request('/inputs/' + id, { method: 'DELETE' }); await load(); emit('change', files.value) } catch (e) { error.value = e.message } }
    const upload = async event => {
      try {
        for (const file of event.target.files) {
          const form = new FormData(); form.append('file', file)
          await request('/inputs', { method: 'POST', body: form })
        }
        await load(); emit('change', files.value)
      } catch (e) { error.value = e.message }
      finally { event.target.value = '' }
    }
    polling(load)
    return () => h('section', { class: 'calabash-files' }, [
      h('input', { ref: input, type: 'file', multiple: true, hidden: true, onChange: upload }),
      h('div', [h(ElButton, { disabled: running.value, onClick: () => nativeHost.value && window.parent !== window ? window.parent.postMessage({ kind: 'calabash-select-inputs' }, '*') : input.value.click() }, () => '选择 / 追加文件 · Add files'), h(ElButton, { text: true, disabled: running.value || !files.value.length, onClick: async () => { for (const file of [...files.value]) await remove(file.id) } }, () => '清空 · Clear')]),
      ...files.value.map(file => h(ElTag, { closable: !running.value, onClose: () => remove(file.id) }, () => `${file.name} · ${file.status}`)),
      error.value ? h('p', { role: 'alert' }, error.value) : null,
    ])
  },
})
export const CalabashResults = defineComponent({
  name: 'CalabashResults', setup() {
    const files = ref([])
    polling(async () => { try { files.value = await request('/results') } catch {} })
    return () => files.value.length ? h('details', { class: 'calabash-results' }, [
      h('summary', `结果文件 · Results (${files.value.length})`),
      ...files.value.map(file => h('div', {}, [
        nativeHost.value && window.parent !== window ? h('span', file.name) : h('a', { href: '/api/sdk/results/' + file.id, download: file.name }, file.name),
        ...(nativeHost.value && window.parent !== window ? ['save', 'open', 'reveal'].map(action => h(ElButton, { text: true, onClick: () => window.parent.postMessage({ kind: 'calabash-result-action', action, file_id: file.id }, '*') }, () => ({ save: '另存为 · Save as', open: '打开 · Open', reveal: '显示位置 · Reveal' })[action])) : []),
      ])),
    ]) : null
  },
})
export const CalabashJobStatus = defineComponent({
  name: 'CalabashJobStatus', setup() {
    const state = ref({ status: 'idle', progress: 0, running: false })
    polling(async () => { try { state.value = await request('/status') } catch {} })
    return () => state.value.status !== 'idle' ? h('section', { class: 'calabash-job-status' }, [
      h('span', { role: 'status' }, state.value.status), h(ElProgress, { percentage: Math.round(state.value.progress * 100) }),
      state.value.running ? h(ElButton, { onClick: () => request('/cancel', { method: 'POST' }) }, () => '安全停止 · Stop safely') : null,
    ]) : null
  },
})
