<template>
  <div v-if="data" class="card-never border-r-6 mb-12">
    <h5 class="p-8-12">动态检索预算</h5>
    <div class="p-8-12 border-t-dashed">
      <p>题型：{{ labels[data.category] || data.category }}；原因：{{ labels[data.reason] || data.reason }}</p>
      <p>检索：{{ data.retrieve ? '开启' : '跳过' }}；候选上限：{{ data.top_n }}；相似度：{{ data.similarity }}；模式：{{ data.search_mode }}</p>
      <p>重排决策：{{ data.rerank === null ? '沿用原配置' : data.rerank ? '开启（需关联重排节点）' : '跳过' }}</p>
      <p v-if="data.status">检索状态：{{ labels[data.status] || data.status }}；原始命中：{{ data.raw_count }}；检索耗时：{{ data.retrieval_ms?.toFixed(2) }} ms</p>
      <p v-if="data.rerank_status">重排执行：{{ labels[data.rerank_status] || data.rerank_status }}；耗时：{{ data.rerank_ms?.toFixed(2) }} ms</p>
      <p v-if="data.rerank_status === 'unavailable'">重排不可用，已保留原始排序并继续上下文处理。</p>
      <el-collapse v-if="raw">
        <el-collapse-item title="原始候选证据">
          <div v-for="(row, index) in raw" :key="index" class="mb-8">
            <p>{{ row.document_id }} / {{ row.id }} · {{ row.similarity }}</p>
            <p>{{ row.title }}</p><p style="white-space: pre-wrap">{{ row.content }}</p>
          </div>
        </el-collapse-item>
      </el-collapse>
      <el-collapse v-if="output !== undefined">
        <el-collapse-item title="节点实际输出文本（供下游引用）">
          <pre style="white-space: pre-wrap">{{ output }}</pre>
        </el-collapse-item>
      </el-collapse>
    </div>
  </div>
</template>
<script setup lang="ts">
defineProps<{ data?: any; raw?: any[]; output?: string }>()
const labels: Record<string, string> = {
  none: '寒暄 / 无需资料', simple: '单事实', complex: '比较 / 多条件', unknown: '无法明确分类',
  exact_greeting: '完整寒暄匹配', ambiguous_or_followup: '空问题或指代不明',
  comparison_or_multiple_conditions: '匹配比较或多条件规则', single_fact: '匹配单事实规则',
  no_explicit_rule: '未匹配明确规则', skipped: '跳过', retrieved: '已检索',
  no_hits: '无命中', empty_scope: '无可用知识库', applied: '已执行', unavailable: '不可用，回退原排序',
  empty_input: '无候选证据',
}
</script>
