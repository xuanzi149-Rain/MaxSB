<template>
  <el-collapse class="mb-8">
    <el-collapse-item :title="$t('workflow.toolRecovery.title')">
      <p>{{ $t('workflow.toolRecovery.configHint') }}</p>
      <el-form-item :label="$t('workflow.toolRecovery.mode')">
        <el-select v-model="policy.mode">
          <el-option v-for="mode in modes" :key="mode" :value="mode" :label="$t(`workflow.toolRecovery.${mode}`)" />
        </el-select>
      </el-form-item>
      <el-form-item :label="$t('workflow.toolRecovery.timeout')">
        <el-input-number v-model="policy.timeout" :min="1" :max="120" />
      </el-form-item>
      <el-form-item :label="$t('workflow.toolRecovery.retries')">
        <el-input-number v-model="policy.retries" :min="0" :max="5" />
      </el-form-item>
      <template v-if="policy.mode === 'idempotent_write'">
        <el-form-item :label="$t('workflow.toolRecovery.keyField')"><el-input v-model="policy.key_field" /></el-form-item>
        <el-form-item :label="$t('workflow.toolRecovery.retention')">
          <el-input-number v-model="policy.retention_hours" :min="1" :max="720" />
        </el-form-item>
      </template>
    </el-collapse-item>
  </el-collapse>
</template>
<script setup lang="ts">
import { reactive, watch } from 'vue'
const props = defineProps<{ modelValue?: any }>()
const emit = defineEmits(['update:modelValue'])
const modes = ['unknown', 'read_only', 'idempotent_write', 'unprotected_write']
const policy = reactive({ timeout: 10, retries: 2, mode: 'unknown', key_field: '', retention_hours: 24, ...props.modelValue })
watch(policy, value => emit('update:modelValue', { ...value }))
</script>
