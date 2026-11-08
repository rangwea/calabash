<script setup lang="ts">
import {computed, onBeforeUnmount, ref, watch} from 'vue'
import {api} from './api'
import {createConnectionMonitor, type RuntimeState} from './runtime_connection.mjs'
const props = defineProps<{
  resource: string; url: string; visible: boolean; pending: boolean; failed: boolean; t: (value: string) => string
}>()
defineEmits<{retry: []; repair: []}>()
const state = ref<RuntimeState>({state: 'ready', running: null})
const monitor = createConnectionMonitor(api, value => {state.value = value})
watch(() => [props.resource, props.url, props.visible, props.pending, props.failed], () => {
  monitor.stop()
  state.value = {state: 'ready', running: null}
  if (props.visible && props.url && !props.pending && !props.failed) monitor.start(props.resource, props.url)
}, {immediate: true})
onBeforeUnmount(monitor.stop)
const show = computed(() => props.visible && (props.pending || props.failed || state.value.state !== 'ready'))
const waiting = computed(() => props.pending || state.value.state === 'starting')
const message = computed(() => {
  if (waiting.value) return '正在打开工具…'
  if (props.failed) return '工具暂时未能打开，可以重新打开或让 AI 帮你修复'
  if (state.value.running) return '工具界面暂时断开，后台任务仍在运行，请等待完成后重新打开'
  if (state.value.state === 'unknown') return '暂时无法确认工具连接，请稍后检查或重新打开'
  return '工具连接已中断，可以重新打开；未保存的界面输入可能需要重新填写'
})
</script>
<template>
  <div v-if="show" class="runtime-connection" :class="{waiting}" role="status" aria-live="polite">
    <span>{{ t(message) }}</span>
    <template v-if="!waiting">
      <el-button text size="small" :disabled="state.running === true" @click="$emit('retry')">{{ t('重新打开') }}</el-button>
      <el-button text size="small" @click="$emit('repair')">{{ t('让 AI 帮我修复') }}</el-button>
    </template>
  </div>
</template>
<style scoped>
.runtime-connection{display:flex;align-items:center;flex-wrap:wrap;gap:4px 12px;padding:10px 16px;flex:none;background:#fff8eb;border-bottom:1px solid #e7d9bc;color:#725514;font-size:13px;line-height:1.6}
.runtime-connection.waiting{background:var(--app-primary-light);color:var(--app-muted);border-color:var(--app-border)}
.runtime-connection .el-button{margin:0}
</style>
