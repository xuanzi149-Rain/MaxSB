<template>
  <div v-if="data" class="card-never border-r-6 mb-12 p-8-12">
    <h5>检索上下文处理</h5>
    <p>片段：{{ data.original_count }} → {{ data.retained_count }}；估计节省 {{ data.estimated_saved_tokens }} token</p>
    <p class="color-secondary">预算 {{ data.token_budget }}；估计用量 {{ data.estimated_retained_tokens }}。不代表实际计费或质量提升。</p>
    <p v-if="data.semantic">同义去重：{{ semanticStatus[data.semantic.status] || data.semantic.status }}；
      替代 {{ data.semantic.actual_removed_count }} 段；在线判断调用 {{ data.semantic.judge_calls }} 次</p>
    <el-collapse>
      <el-collapse-item title="证据保留与排除原因" name="mapping">
        <el-table :data="data.mapping" size="small">
          <el-table-column prop="original_id" label="原段落 ID" min-width="160" />
          <el-table-column prop="document_id" label="原文档 ID" min-width="160" />
          <el-table-column prop="retained_id" label="对应保留段落 ID" min-width="160" />
          <el-table-column label="原因" min-width="110">
            <template #default="{ row }">{{ reasons[row.reason] || row.reason }}</template>
          </el-table-column>
        </el-table>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>
<script setup lang="ts">
defineProps<{ data?: any }>()
const semanticStatus: Record<string, string> = {
  matched: '命中已审核关系', no_approved_match: '无有效已审核关系',
  registry_unavailable: '审核缓存未配置或不可用', model_version_changed: '模型版本变化，保留原文',
  registry_invalid: '审核缓存无效',
}
const reasons: Record<string, string> = {
  semantic_duplicate: '已审核同义替代', retained: '保留', duplicate: '重复', near_duplicate: '近重复', contained: '完整条款已被覆盖', budget: '超出预算', empty: '空内容',
}
</script>
