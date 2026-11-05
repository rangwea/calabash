<script setup lang="ts">import {ref} from 'vue';const query=ref('')</script>
<template><main class="tool-page"><el-card shadow="never"><template #header><h2>My office tool</h2></template><el-form label-position="top"><el-form-item label="Search"><el-input v-model="query" /></el-form-item></el-form><el-button type="primary">Run</el-button></el-card></main></template>
<style scoped>h2{font-size:22px;margin:0}.tool-page{display:grid;gap:var(--calabash-gap);color:var(--calabash-text)}</style>
