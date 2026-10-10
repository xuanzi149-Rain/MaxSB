<template>
  <div class="evaluation-page">
    <header>
      <div><h2>Agent 评测</h2><p>固定考卷 · 逐题证据 · 可追溯对照</p></div>
      <div class="actions">
        <el-select v-model="dataset" aria-label="题集" style="width: 180px">
          <el-option label="开发集 · 20 题" value="dev-v1" />
          <el-option label="冻结集 · 80 题" value="frozen-v1" />
        </el-select>
        <el-button v-if="canEdit" type="primary" :loading="creating" @click="create">创建评测</el-button>
        <el-button @click="refresh">刷新</el-button>
      </div>
    </header>
    <el-alert title="正确率以人工复核为准；未知计量不计为零。冻结集须先完成判分规则审核。" type="info" :closable="false" />
    <div class="selectors">
      <el-select v-model="left" placeholder="选择基准运行" aria-label="基准运行" @change="loadDetail">
        <el-option v-for="run in runs" :key="run.run_id" :value="run.run_id" :label="runLabel(run)" />
      </el-select>
      <el-select v-model="right" placeholder="选择对照运行" aria-label="对照运行" clearable>
        <el-option v-for="run in completed" :key="run.run_id" :value="run.run_id" :label="runLabel(run)" />
      </el-select>
      <el-button :disabled="!left || !right" @click="compare">比较运行</el-button>
    </div>
    <el-card class="mb-12" shadow="never">
      <h4>模型路由三组评测</h4>
      <p>选择已启用路由的应用。三组共享题集、消息和输出契约；固定低成本组不升级。</p>
      <el-select v-model="routingStrategy" aria-label="新建运行的模型策略" style="width: 220px">
        <el-option label="沿用应用策略" value="" /><el-option label="固定低成本模型" value="low" />
        <el-option label="始终高能力模型" value="high" /><el-option label="路由策略" value="routing" />
      </el-select>
      <p>上方基准选择低成本运行，对照选择高能力运行，下方选择路由运行。</p>
      <el-select v-model="routedRun" aria-label="路由运行" style="width: 320px">
        <el-option v-for="run in completed" :key="run.run_id" :value="run.run_id" :label="runLabel(run)" />
      </el-select>
      <el-button :disabled="!left || !right || !routedRun" @click="compareRouting">比较三组</el-button>
      <template v-if="routingComparison">
        <el-alert :closable="false" :type="routingComparison.cost_optimized ? 'success' : 'info'"
          :title="routingComparison.cost_optimized ? '质量与实际费用门槛均通过' : '尚不能证明成本优化；核对人工评分、引用和完整费用'" />
        <p v-if="routingComparison.reasons?.length">不可比较原因：{{ routingComparison.reasons.join('、') }}</p>
        <el-table :data="routingRows" size="small">
          <el-table-column prop="scenario" label="题型" /><el-table-column prop="role" label="策略" />
          <el-table-column prop="accuracy" label="正确率" /><el-table-column prop="cost" label="每成功任务实际费用" />
          <el-table-column prop="p95" label="P95（秒）" />
        </el-table>
        <p>升级率：{{ routingComparison.upgrade_rate ?? '未知' }}；未知计量不会按零处理。</p>
      </template>
    </el-card>
    <el-empty v-if="!runs.length" description="尚无评测运行。创建开发集运行，建立第一份基线。" />
    <template v-if="detail">
      <div class="metadata">
        <el-tag>{{ detail.status }}</el-tag><span>{{ detail.progress }} / {{ detail.total }} 题</span>
        <span>题集 {{ detail.dataset_version }}</span><span>运行 {{ detail.run_id }}</span>
        <span>代码 {{ detail.snapshot?.code_sha }}</span><span>{{ detail.created_at }}</span>
        <details><summary>模型与运行快照</summary><pre>{{ JSON.stringify(detail.snapshot, null, 2) }}</pre></details>
      </div>
      <el-alert v-if="comparison && !comparison.comparable" type="warning" :closable="false"
        :title="`配置不一致，不可作严格对照：${comparison.reasons.join('、')}`" />
      <el-table :data="metricRows" border class="metrics">
        <el-table-column prop="label" label="指标" />
        <el-table-column prop="left" label="基准运行" />
        <el-table-column v-if="comparison" prop="right" label="对照运行" />
      </el-table>
      <div class="case-header"><h3>逐题分析</h3>
        <el-select v-model="filter" aria-label="结果筛选" style="width: 170px">
          <el-option label="全部题目" value="all" /><el-option label="运行失败" value="failed" />
          <el-option label="待人工复核" value="pending" /><el-option label="人工判错" value="incorrect" />
        </el-select>
      </div>
      <el-table :data="caseRows" row-key="case_id" border>
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="case-detail">
              <h4>题目与判分依据</h4><pre>{{ questionFor(row.case_id) }}</pre>
              <div class="answer-columns"><div><h4>基准答案</h4><pre>{{ row.left?.answer || '无答案' }}</pre></div>
                <div v-if="comparison"><h4>对照答案</h4><pre>{{ row.right?.answer || '无答案或缺题' }}</pre></div></div>
              <h4>检索证据 / 引用</h4><pre>{{ row.left?.retrieved_evidence_ids }} / {{ row.left?.citations }}</pre>
              <details><summary>展开节点轨迹与错误</summary><pre>{{ JSON.stringify({ error: row.left?.error, trace: row.left?.trace, score: row.left?.score }, null, 2) }}</pre></details>
              <div v-if="canEdit && row.left" class="review">
                <el-select v-model="reviewCorrect" aria-label="人工判分" style="width: 130px"><el-option label="正确" :value="true" /><el-option label="错误" :value="false" /></el-select>
                <el-input v-model="reviewReason" placeholder="按规则记录依据与失败原因" aria-label="评分依据" />
                <el-input-number v-model="citationTotal" :min="0" aria-label="引用总数" placeholder="引用总数" />
                <el-input-number v-model="citationSupported" :min="0" :max="citationTotal" aria-label="支持主张的引用数" placeholder="支持数" />
                <el-button @click="saveReview(row.case_id)">保存人工复核</el-button>
              </div>
              <small>复核人：{{ row.left?.review?.reviewer || '待复核' }} · {{ row.left?.review?.reviewed_at || '' }}</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="case_id" label="题目" width="140" />
        <el-table-column label="场景"><template #default="{ row }">{{ row.left?.scenario || row.right?.scenario }}</template></el-table-column>
        <el-table-column label="运行状态"><template #default="{ row }">{{ row.left?.status || '缺题' }}</template></el-table-column>
        <el-table-column label="人工复核"><template #default="{ row }">{{ reviewLabel(row.left) }}</template></el-table-column>
        <el-table-column label="失败原因"><template #default="{ row }">{{ row.left?.error || row.left?.review?.reason || '—' }}</template></el-table-column>
        <el-table-column v-if="comparison" label="对照复核"><template #default="{ row }">{{ reviewLabel(row.right) }}</template></el-table-column>
      </el-table>
    </template>
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import api from '@/api/application/evaluation'
import { hasPermission } from '@/utils/permission'
import { PermissionConst, RoleConst } from '@/utils/permission/data'
const route = useRoute()
const id = computed(() => String(route.params.id))
const canEdit = computed(() => hasPermission([
  PermissionConst.APPLICATION_EDIT.getApplicationWorkspaceResourcePermission(id.value),
  PermissionConst.APPLICATION_EDIT.getWorkspacePermissionWorkspaceManageRole(),
  RoleConst.WORKSPACE_MANAGE.getWorkspaceRole(), RoleConst.ADMIN,
], 'OR'))
const routedRun = ref(''), routingStrategy = ref(''), routingComparison = ref<any>(null)
const routingRows = computed(() => Object.entries(routingComparison.value?.by_scenario || {}).flatMap(([scenario, groups]) => Object.entries(groups as Record<string, any>).map(([role, summary]) => ({ scenario, role, accuracy: summary.accuracy ?? '未知', cost: summary.cost_per_success ?? '未知', p95: summary.p95_seconds ?? '未知' }))))
async function compareRouting() { routingComparison.value = (await api.compareRouting(id.value, left.value, right.value, routedRun.value)).data }
const runs = ref<any[]>([]), detail = ref<any>(null), comparison = ref<any>(null)
const left = ref(''), right = ref(''), dataset = ref('dev-v1'), creating = ref(false), filter = ref('all')
const citationTotal = ref<number | undefined>(undefined), citationSupported = ref<number | undefined>(undefined)
const reviewCorrect = ref(false), reviewReason = ref('')
const terminal = ['completed', 'configuration_drift', 'interrupted', 'dispatch_failed']
const completed = computed(() => runs.value.filter(r => terminal.includes(r.status)))
const runLabel = (r: any) => `${r.created_at?.slice(0, 16)} · ${r.dataset_version} · ${r.status} · ${r.run_id.slice(0, 8)}`
const reviewLabel = (r: any) => typeof r?.review?.correct === 'boolean' ? (r.review.correct ? '正确' : '错误') : '待复核'
async function refresh() { runs.value = (await api.list(id.value)).data; if (left.value) await loadDetail() }
async function loadDetail() { comparison.value = null; if (left.value) detail.value = (await api.detail(id.value, left.value)).data }
async function create() { creating.value = true; try { const r = await api.create(id.value, dataset.value, routingStrategy.value); left.value = r.data.run_id; await refresh() } finally { creating.value = false } }
async function compare() { comparison.value = (await api.compare(id.value, left.value, right.value)).data }
async function saveReview(caseId: string) {
  if (!reviewReason.value.trim()) return
  await api.review(id.value, left.value, caseId, { correct: reviewCorrect.value, reason: reviewReason.value, citation_total: citationTotal.value, citation_supported: citationSupported.value })
  reviewReason.value = ''; await loadDetail()
}
const metrics = [
  ['accuracy', '正确率（完成复核后）'], ['review_coverage', '人工复核覆盖率'], ['evidence_recall', '证据召回率'],
  ['citation_accuracy', '引用准确率'], ['tool_complete', '受控工具工作流完成率'], ['average_input_tokens', '平均输入 token'],
  ['average_output_tokens', '平均输出 token'], ['input_token_coverage', '输入计量覆盖率'],
  ['output_token_coverage', '输出计量覆盖率'], ['cost_per_success', '每成功任务实际费用'],
  ['cost_coverage', '实际费用覆盖率'], ['p95_seconds', 'P95 耗时（秒）'],
]
const display = (value: any) => value === null || value === undefined ? '未知 / 不适用' : typeof value === 'number' ? Number(value.toFixed(4)) : value
const metricRows = computed(() => metrics.map(([key, label]) => ({ label,
  left: display((comparison.value?.left_summary || detail.value?.summary)?.[key]),
  right: display(comparison.value?.right_summary?.[key]),
})))
const caseRows = computed(() => {
  const rows = comparison.value?.cases || detail.value?.cases?.map((r: any) => ({ case_id: r.case_id, left: r })) || []
  return rows.filter((r: any) => filter.value === 'all' || (filter.value === 'failed' && r.left?.status === 'failed') ||
    (filter.value === 'pending' && typeof r.left?.review?.correct !== 'boolean') ||
    (filter.value === 'incorrect' && r.left?.review?.correct === false))
})
const questionFor = (caseId: string) => JSON.stringify(detail.value?.questions?.find((q: any) => q.case_id === caseId), null, 2)
let timer: ReturnType<typeof setInterval> | undefined
onMounted(async () => { await refresh(); timer = setInterval(() => {
  if (runs.value.some(r => !terminal.includes(r.status))) void refresh()
}, 5000) })
onUnmounted(() => clearInterval(timer))
</script>
<style scoped>
.evaluation-page { padding: 24px; overflow: auto; height: 100%; }
header, .actions, .selectors, .metadata, .case-header, .review { display: flex; align-items: center; gap: 12px; }
header, .case-header { justify-content: space-between; }
h2 { margin: 0; } header p { color: var(--el-text-color-secondary); margin: 8px 0 20px; }
.selectors { margin: 20px 0; } .selectors .el-select { width: 38%; }
.metadata { flex-wrap: wrap; font-size: 12px; margin-bottom: 16px; color: var(--el-text-color-secondary); }
.case-detail { padding: 16px 24px; background: var(--el-fill-color-light); }
pre { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; line-height: 1.6; }
.answer-columns { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 24px; }
.review { margin: 16px 0; flex-wrap: wrap; } .review .el-input { flex: 1; }
</style>
