<template>
  <div class="p-8-12" style="overflow-wrap: anywhere">
    <el-input v-if="manager" v-model="lookupId" :placeholder="$t('workflow.toolRecovery.run')" />
    <el-button text :loading="loading" @click="load">{{ $t('workflow.toolRecovery.title') }}</el-button>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div v-for="run in runs" :key="run.id" class="border-r-6 p-8-12 mb-8">
      <div>{{ run.id }} · {{ run.status }} · {{ $t('workflow.toolRecovery.resumes') }}: {{ run.resumes }}</div>
      <div v-for="step in run.steps" :key="step.node_id" class="mt-8">
        {{ step.node_id }}: {{ step.status }} {{ step.error_type }}
        <div v-for="attempt in step.attempts" :key="attempt.id" class="color-secondary">
          #{{ attempt.id }} · {{ attempt.generation }} · {{ attempt.status }} {{ attempt.error_type }}
          {{ attempt.started_at }} → {{ attempt.ended_at || '…' }}
        </div>
      </div>
      <el-alert v-if="run.status === 'outcome_unknown'" type="warning" :closable="false"
        :title="$t('workflow.toolRecovery.unknownHint')" />
      <el-button v-if="run.can_resume && !manager" :disabled="loading" @click="resume(run)">
        {{ $t('workflow.toolRecovery.resume') }}
      </el-button>
      <template v-if="manager && run.status === 'outcome_unknown'">
        <el-select v-model="conclusion">
          <el-option value="executed" :label="$t('workflow.toolRecovery.executed')" />
          <el-option value="not_executed" :label="$t('workflow.toolRecovery.notExecuted')" />
        </el-select>
        <el-input v-model="evidence" type="textarea" :placeholder="$t('workflow.toolRecovery.evidence')" />
        <el-input v-if="conclusion === 'executed'" v-model="confirmedOutput" type="textarea"
          :placeholder="$t('workflow.toolRecovery.output')" />
        <el-button :disabled="loading || evidence.trim().length < 10" @click="resolve(run)">
          {{ $t('workflow.toolRecovery.confirm') }}
        </el-button>
      </template>
      <div v-if="run.resolution" class="mt-8">{{ run.resolution }}</div>

    </div>
  </div>
</template>
<script setup lang="ts">
import { ref } from 'vue'
import { v4 as uuid } from 'uuid'
import { request } from '@/request/chat'
import { request as adminRequest } from '@/request'
import useStore from '@/stores'
const props = defineProps<{ chatId: string; manager?: boolean; applicationId?: string }>()
const lookupId = ref('')
const conclusion = ref('executed')
const evidence = ref('')
const confirmedOutput = ref('[]')
const managerUrl = (id: string) => `/workspace/${useStore().user.getWorkspaceId()}/application/${props.applicationId}/tool_runs/${id}/resolution`
const runs = ref<any[]>([])
const emit = defineEmits(['recovered'])
const loading = ref(false)
const error = ref('')
const requests: Record<string, { request_id: string; expected_version: number }> = {}
async function load() {
  loading.value = true
  error.value = ''
  try {
    const response = props.manager
      ? await adminRequest({ url: managerUrl(lookupId.value), method: 'get' })
      : await request({ url: `/chat/${props.chatId}/tool_runs`, method: 'get' })
    runs.value = props.manager ? [response.data.data] : response.data.data
    if (!props.manager) runs.value.filter(r => r.status === 'succeeded').forEach(r => emit('recovered', r))
  } catch (e: any) { error.value = e?.message || String(e) }
  finally { loading.value = false }
}
async function resume(run: any) {
  loading.value = true
  error.value = ''
  requests[run.id] ||= { request_id: uuid(), expected_version: run.version }
  try {
    const response = await request({ url: `/tool_runs/${run.id}/resume`, method: 'post', data: requests[run.id] })
    const updated = response.data.data
    runs.value = runs.value.map(r => r.id === run.id ? updated : r)
    if (updated.status === 'succeeded') emit('recovered', updated)
    delete requests[run.id]
  } catch (e: any) {
    error.value = e?.message || String(e)
    if (e?.response?.status === 409) { delete requests[run.id]; await load() }
  } finally { loading.value = false }
}
async function resolve(run: any) {
  loading.value = true
  error.value = ''
  try {
    await adminRequest({ url: managerUrl(run.id), method: 'post', data: {
      request_id: uuid(), expected_version: run.version, conclusion: conclusion.value,
      evidence: evidence.value, ...(conclusion.value === 'executed' ? { output: JSON.parse(confirmedOutput.value) } : {}),
    } })
    await load()
  } catch (e: any) { error.value = e?.message || String(e) }
  finally { loading.value = false }
}
</script>
