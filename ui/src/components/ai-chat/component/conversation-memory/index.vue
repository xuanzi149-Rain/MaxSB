<template>
  <el-button text size="small" @click="open">{{ t('aiChat.memory.title') }}</el-button>
  <el-drawer v-model="visible" :title="t('aiChat.memory.title')" size="min(520px, 100vw)" append-to-body>
    <el-alert v-if="debug" :title="t('aiChat.memory.temporary')" type="info" :closable="false" />
    <el-alert :title="t('aiChat.memory.scope')" type="info" :closable="false" class="mb-12" />
    <el-button :loading="loading" @click="refresh">{{ t('aiChat.memory.refresh') }}</el-button>
    <el-button :disabled="loading || !state" type="danger" plain @click="clearMemory">{{ t('aiChat.memory.clear') }}</el-button>
    <el-empty v-if="state && !state.facts.length" :description="t('aiChat.memory.empty')" />
    <div v-for="fact in state?.facts || []" :key="fact.id" class="memory-fact border border-r-6 p-12 mt-12">
      <strong>{{ fact.entity }} · {{ fact.attribute }}</strong>
      <el-tag class="ml-8" :type="fact.status === 'pending' ? 'warning' : 'success'">{{ t(`aiChat.memory.${fact.status}`) }}</el-tag>
      <p>{{ fact.value }}</p>
      <small>{{ fact.updated_at }}</small>
      <details class="mt-8">
        <summary>{{ t('aiChat.memory.source') }}</summary>
        <p>{{ source(fact.source)?.question || fact.quote }}</p>
        <small>{{ source(fact.source)?.record_id || t('aiChat.memory.manual') }}</small>
      </details>
      <el-button text :disabled="loading" @click="correct(fact)">{{ t('aiChat.memory.correct') }}</el-button>
      <el-button v-if="fact.status === 'pending'" text :disabled="loading" @click="mutate(fact, 'confirm')">{{ t('aiChat.memory.confirm') }}</el-button>
      <el-button text type="danger" :disabled="loading" @click="mutate(fact, 'revoke')">{{ t('aiChat.memory.revoke') }}</el-button>
    </div>
  </el-drawer>
</template>
<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { memoryRequest } from '@/api/chat/chat-memory'
const props = defineProps<{ chatId: string; debug: boolean; applicationId: string }>()
const { t } = useI18n()
const visible = ref(false)
const loading = ref(false)
const state = ref<any>(null)
let epoch = 0
watch(() => props.chatId, () => { epoch++; state.value = null; visible.value = false })
function source(id: string) { return state.value?.sources.find((s: any) => s.id === id) }
async function refresh() {
  const current = ++epoch
  loading.value = true
  try {
    const value = await memoryRequest(props.chatId, props.debug, props.applicationId, 'get')
    if (current === epoch) state.value = value
  } finally { if (current === epoch) loading.value = false }
}
async function open() { visible.value = true; await refresh() }
async function mutate(fact: any, operation: string, value?: string) {
  const current = ++epoch
  loading.value = true
  try {
    const updated = await memoryRequest(props.chatId, props.debug, props.applicationId, 'patch', {
      expected_version: state.value.version, request_id: crypto.randomUUID(), operation, value: value ?? fact.value,
    }, fact.id)
    if (current === epoch) state.value = updated
  } catch { if (current === epoch) await refresh() }
  finally { if (current === epoch) loading.value = false }
}
async function correct(fact: any) {
  try {
    const { value } = await ElMessageBox.prompt(t('aiChat.memory.correct'), fact.attribute, { inputValue: fact.value, inputValidator: (s) => !!s?.trim() && s.length <= 2048 })
    await mutate(fact, 'replace', value)
  } catch { /* Dialog cancelled. */ }
}
async function clearMemory() {
  try { await ElMessageBox.confirm(t('aiChat.memory.scope'), t('aiChat.memory.clear')) } catch { return }
  const current = ++epoch
  loading.value = true
  try {
    const updated = await memoryRequest(props.chatId, props.debug, props.applicationId, 'delete', {
      expected_version: state.value.version, request_id: crypto.randomUUID(),
    })
    if (current === epoch) state.value = updated
  } catch { if (current === epoch) await refresh() }
  finally { if (current === epoch) loading.value = false }
}
</script>
<style scoped>
.memory-fact { overflow-wrap: anywhere; }
</style>
