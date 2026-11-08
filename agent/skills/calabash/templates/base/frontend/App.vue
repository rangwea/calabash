<script setup lang="ts">
import { ref } from 'vue'
import { api } from '@calabash/api'

const text = ref('你好')
const message = ref('')
const error = ref('')
const pending = ref(false)

async function submit(): Promise<void> {
  if (pending.value || !text.value.trim()) return
  pending.value = true
  error.value = ''
  try {
    const result = await api.create_message({ body: { text: text.value.trim() } })
    message.value = result.message
  } catch (cause: unknown) {
    error.value = cause instanceof Error ? cause.message : '暂时无法完成，请重试或让 AI 帮你修复'
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <main class="tool-page">
    <header><h1>办公工具</h1><p>输入内容，开始使用。</p></header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <el-card shadow="never">
      <form class="tool-form" @submit.prevent="submit">
        <label for="tool-message">内容</label>
        <el-input id="tool-message" v-model="text" maxlength="200" :disabled="pending" />
        <el-button native-type="submit" type="primary" :loading="pending" :disabled="!text.trim()">确认</el-button>
      </form>
    </el-card>
    <el-card v-if="message" shadow="never"><p role="status">{{ message }}</p></el-card>
    <el-empty v-else description="还没有结果" :image-size="64" />
  </main>
</template>

<style scoped>
.tool-page { display: grid; gap: 16px; padding: 24px; min-width: 0; }
h1 { margin: 0; font-size: 22px; }
header p { margin-bottom: 0; }
.tool-form { display: grid; gap: 12px; min-width: 0; }
p { overflow-wrap: anywhere; }
</style>
