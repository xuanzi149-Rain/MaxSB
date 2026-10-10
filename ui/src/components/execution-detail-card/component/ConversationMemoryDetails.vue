<template>
  <div v-if="data?.enabled" class="card-never border-r-6 mb-8">
    <h5 class="p-8-12">{{ t('aiChat.memory.title') }} · {{ data.status }}</h5>
    <div class="p-8-12">
      <p>{{ t('aiChat.memory.usage') }}: {{ data.total_usage?.input_tokens ?? '?' }} / {{ data.total_usage?.output_tokens ?? '?' }}</p>
      <p>{{ t('aiChat.memory.estimated') }}: {{ data.tokens }} ({{ data.counting }})</p>
      <details><summary>{{ t('aiChat.memory.source') }}</summary><pre class="memory-trace">{{ JSON.stringify(data, null, 2) }}</pre></details>
    </div>
  </div>
</template>
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
defineProps<{ data?: any }>()
const { t } = useI18n()
</script>
<style scoped>.memory-trace { white-space: pre-wrap; overflow-wrap: anywhere; }</style>
