<script setup lang="ts">
import type { SessionMode } from '@/api/types'
import { SESSION_MODE_LABEL } from '@/lib/labels'

import { MODE_ICON } from './status'

defineProps<{ mode: SessionMode }>()
</script>

<template>
  <span class="inline-flex items-center gap-1 text-xs text-muted-foreground">
    <component :is="MODE_ICON[mode]" class="size-3.5" aria-hidden="true" />
    {{ SESSION_MODE_LABEL[mode] }}
  </span>
</template>
