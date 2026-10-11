<template>
  <el-form-item :label="$t('workflow.modelRouting.title')">
    <el-switch v-model="value.enabled" />
  </el-form-item>
  <template v-if="value.enabled">
    <el-alert :closable="false" type="info" :title="$t('workflow.modelRouting.hint')" class="mb-12" />
    <el-form-item v-for="role in roles" :key="role" :label="$t(`workflow.modelRouting.${role}`)">
      <ModelSelect v-model="value[role].model_id" :options="options" :teleported="false" model-type="LLM" />
      <div class="mt-8">
        <label>{{ $t('workflow.modelRouting.temperature') }}</label>
        <el-input-number v-model="value[role].params.temperature" :min="0" :max="2" :step="0.1" size="small" />
        <label>{{ $t('workflow.modelRouting.maxTokens') }}</label>
        <el-input-number v-model="value[role].params.max_tokens" :min="1" :max="32768" size="small" />
      </div>
    </el-form-item>
    <el-form-item :label="$t('workflow.modelRouting.timeout')">
      <el-input-number v-model="value.timeout" :min="1" :max="120" />
    </el-form-item>
    <el-form-item :label="$t('workflow.modelRouting.fields')">
      <el-select v-model="value.contract.required_fields" multiple filterable allow-create default-first-option
        :teleported="false" class="w-full" />
    </el-form-item>
    <el-form-item :label="$t('workflow.modelRouting.citations')">
      <el-input v-model="value.contract.citation_field" @input="clearReference" />
    </el-form-item>
    <el-form-item v-if="value.contract.citation_field" :label="$t('workflow.modelRouting.evidence')">
      <NodeCascader v-model="value.contract.evidence_reference" :node-model="nodeModel" class="w-full" />
    </el-form-item>
  </template>
</template>
<script setup lang="ts">
import { computed, watch } from 'vue'
import NodeCascader from '@/workflow/common/NodeCascader.vue'
const props = defineProps<{ modelValue: any; options: any; nodeModel: any }>()
const emit = defineEmits(['update:modelValue'])
const roles = ['low', 'high'] as const
const value = computed({ get: () => props.modelValue, set: (v) => emit('update:modelValue', v) })
watch(() => props.modelValue, (v) => {
  if (!v) return
  for (const role of roles) {
    v[role] ||= { model_id: '', params: {} }
    v[role].params ||= {}
  }
  v.contract ||= { required_fields: [], citation_field: '', evidence_reference: [] }
  v.timeout ??= 60
}, { immediate: true })
function clearReference() {
  if (!value.value.contract.citation_field) value.value.contract.evidence_reference = []
}
</script>
