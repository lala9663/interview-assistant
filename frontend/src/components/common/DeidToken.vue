<script setup lang="ts">
import { Tooltip } from '@/components/ui/tooltip'

/** A de-identification token rendered as a chip. The original value never reaches the browser. */
defineProps<{ token: string }>()
</script>

<template>
  <Tooltip content="비식별 토큰입니다. 원래 값은 원본 영역에만 있고 화면과 AI에는 전달되지 않습니다.">
    <span
      tabindex="0"
      class="mx-px inline-flex items-center rounded border border-dashed border-foreground/20 bg-muted px-1 py-px align-baseline font-mono text-[0.86em] leading-none text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
      >{{ token }}</span
    >
  </Tooltip>
</template>
