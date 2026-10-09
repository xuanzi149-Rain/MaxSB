<template>
  <el-form-item label="检索上下文去重">
    <el-switch :model-value="policy.enabled" @update:model-value="update('enabled', $event)" />
    <el-text class="ml-8" type="info">默认关闭；开启后保留整段证据及来源映射</el-text>
  </el-form-item>
  <template v-if="policy.enabled">
    <el-form-item label="已审核同义去重">
      <el-switch :model-value="policy.semantic_enabled" @update:model-value="update('semantic_enabled', $event)" />
      <el-text class="ml-8" type="info">仅使用服务器已审核缓存；未命中、过期或版本变化保留原文，不在线付费判断</el-text>
    </el-form-item>
    <el-form-item label="上下文预算（估计 token）">
      <el-input-number
        :model-value="policy.token_budget"
        :min="1"
        :max="100000"
        :precision="0"
        :value-on-clear="2048"
        @update:model-value="update('token_budget', $event)"
      />
    </el-form-item>
    <el-form-item label="格式近重复阈值">
      <el-input-number
        :model-value="policy.similarity_threshold"
        :min="0.8"
        :max="1"
        :step="0.01"
        :precision="2"
        :value-on-clear="0.95"
        @update:model-value="update('similarity_threshold', $event)"
      />
    </el-form-item>
    <el-text type="info">
      同时受原字符上限约束。比较时统一常见排版与全角字符，保留原文；相同主体的结构化数值事实被另一段完整覆盖时可省略。
      阈值不是语义相似度。不同标题范围、条件及不确定的改写保留，输出维持原顺序。
      预算不足可能排除关键证据，请结合执行详情和评测检查。估计值不是供应商计费用量。
    </el-text>
  </template>
</template>
<script setup lang="ts">
import { computed } from 'vue'
interface Policy {
  enabled: boolean
  semantic_enabled: boolean
  token_budget: number
  similarity_threshold: number
}
const props = defineProps<{ modelValue?: Partial<Policy> }>()
const emit = defineEmits<{ 'update:modelValue': [value: Policy] }>()
const policy = computed(() => ({ enabled: false, semantic_enabled: false, token_budget: 2048, similarity_threshold: 0.95, ...props.modelValue }))
function update(key: keyof Policy, value: unknown) {
  emit('update:modelValue', { ...policy.value, [key]: value })
}
</script>
