<script setup lang="ts">
import { LockKeyholeIcon } from '@lucide/vue'
import type { HTMLAttributes } from 'vue'

import { cn } from '@/lib/utils'

const props = defineProps<{ class?: HTMLAttributes['class'] }>()
</script>

<template>
  <p :class="cn('flex items-start gap-1.5 text-xs text-muted-foreground', props.class)">
    <LockKeyholeIcon class="mt-px size-3.5 shrink-0" aria-hidden="true" />
    <span><slot>실명과 연락처는 원본 영역에만 있습니다. 화면에는 가명과 비식별 정보만 표시합니다.</slot></span>
  </p>
</template>
