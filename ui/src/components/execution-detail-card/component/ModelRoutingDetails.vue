<template>
  <el-collapse v-if="data?.attempts" class="mb-12">
    <el-collapse-item :title="$t('workflow.modelRouting.title')" name="routing">
      <p>{{ data.reason }} · {{ data.status }}</p>
      <p v-if="data.upgrade_reason">{{ $t('workflow.modelRouting.upgrade') }}: {{ data.upgrade_reason }}</p>
      <el-table :data="data.attempts" size="small">
        <el-table-column prop="role" :label="$t('workflow.modelRouting.role')" />
        <el-table-column :label="$t('workflow.modelRouting.model')">
          <template #default="{ row }">{{ row.model_name || row.model_id }}</template>
        </el-table-column>
        <el-table-column prop="status" :label="$t('workflow.modelRouting.status')" />
        <el-table-column prop="error" :label="$t('workflow.modelRouting.upgrade')" />
        <el-table-column label="Input / Output">
          <template #default="{ row }">{{ row.usage?.input_tokens ?? '—' }} / {{ row.usage?.output_tokens ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="参考核算 / 实际费用">
          <template #default="{ row }">{{ row.priced_cost ?? '—' }} / {{ row.actual_cost ?? '—' }} {{ row.currency || '' }}</template>
        </el-table-column>
        <el-table-column label="价格来源">
          <template #default="{ row }">{{ row.price_version || '—' }}<br />{{ row.price_basis || '—' }}</template>
        </el-table-column>
        <el-table-column :label="$t('workflow.modelRouting.seconds')">
          <template #default="{ row }">{{ row.elapsed_seconds?.toFixed(2) ?? '—' }}</template>
        </el-table-column>
      </el-table>
      <p>{{ $t('workflow.modelRouting.unknown') }}</p>
    </el-collapse-item>
  </el-collapse>
</template>
<script setup lang="ts">
defineProps<{ data?: any }>()
</script>
