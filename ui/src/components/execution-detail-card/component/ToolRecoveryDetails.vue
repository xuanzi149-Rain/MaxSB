<template>
  <div v-if="data" class="p-8-12 mb-8 border-r-6 layout-bg">
    <strong>{{ $t('workflow.toolRecovery.title') }}</strong>
    <div>{{ $t('workflow.toolRecovery.run') }}: {{ data.run_id }}</div>
    <div>{{ $t('workflow.toolRecovery.generation') }}: {{ data.generation }}</div>
  </div>
</template>
<script setup lang="ts">
defineProps<{ data?: { run_id: string; generation: number } }>()
</script>
