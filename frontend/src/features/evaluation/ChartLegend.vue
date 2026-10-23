<script setup lang="ts">
import type { Series } from './series'

defineProps<{ series: Series[] }>()
</script>

<template>
  <ul class="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-muted-foreground" aria-label="범례">
    <li v-for="s in series" :key="s.key" class="flex items-center gap-1.5">
      <span class="size-2.5 rounded-[3px]" :style="{ background: s.color }" aria-hidden="true"></span>
      {{ s.label }}
      <span v-if="s.kind === 'ai'" class="sr-only">AI 점수는 참고용</span>
    </li>
  </ul>
</template>
