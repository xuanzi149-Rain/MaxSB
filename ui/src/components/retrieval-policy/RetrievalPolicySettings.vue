<template>
  <el-form-item label="动态检索预算">
    <el-switch :model-value="policy.enabled" @update:model-value="updateEnabled" />
    <el-text class="ml-8" type="info">默认关闭；未识别的问题沿用固定检索与重排设置</el-text>
  </el-form-item>
  <template v-if="policy.enabled">
    <el-form-item v-for="item in categories" :key="item.key" :label="item.label">
      <div class="flex align-center" style="gap: 8px; flex-wrap: wrap">
        <el-checkbox :model-value="policy[item.key].retrieve" @update:model-value="update(item.key, 'retrieve', $event)">
          检索
        </el-checkbox>
        <el-input-number
          :model-value="policy[item.key].top_n"
          :disabled="!policy[item.key].retrieve"
          :min="1" :max="10000" :precision="0" :value-on-clear="1"
          aria-label="候选段落上限"
          @update:model-value="update(item.key, 'top_n', $event)"
        />
        <el-checkbox
          :model-value="policy[item.key].rerank" :disabled="!policy[item.key].retrieve"
          @update:model-value="update(item.key, 'rerank', $event)"
        >重排</el-checkbox>
      </div>
    </el-form-item>
    <el-text type="info">
      仅完整寒暄匹配可跳过检索；指代不明时回退。相似度阈值及检索模式沿用下方设置。
      重排策略需在下游重排节点关联此节点的“检索预算决策”，并选择同节点“原始检索候选”作为唯一输入。
      请在重排节点配置最终上下文去重与预算；未接重排节点时使用当前节点的上下文处理。
      候选数减少可能丢失证据，请按题型评测。
    </el-text>
  </template>
</template>
<script setup lang="ts">
import { computed } from 'vue'
type Category = 'none' | 'simple' | 'complex'
interface Profile { retrieve: boolean; top_n: number; rerank: boolean }
interface Policy { enabled: boolean; none: Profile; simple: Profile; complex: Profile }
const props = defineProps<{ modelValue?: Partial<Policy> }>()
const emit = defineEmits<{ 'update:modelValue': [value: Policy] }>()
const categories: { key: Category; label: string }[] = [
  { key: 'none', label: '寒暄 / 无需资料' },
  { key: 'simple', label: '单事实问题' },
  { key: 'complex', label: '比较 / 多条件问题' },
]
const policy = computed<Policy>(() => ({
  enabled: props.modelValue?.enabled ?? false,
  none: { retrieve: false, top_n: 1, rerank: false, ...props.modelValue?.none },
  simple: { retrieve: true, top_n: 3, rerank: false, ...props.modelValue?.simple },
  complex: { retrieve: true, top_n: 8, rerank: true, ...props.modelValue?.complex },
}))
function updateEnabled(value: unknown) {
  emit('update:modelValue', { ...policy.value, enabled: Boolean(value) })
}
function update(category: Category, key: keyof Profile, value: unknown) {
  emit('update:modelValue', { ...policy.value, [category]: { ...policy.value[category], [key]: value } })
}
</script>
