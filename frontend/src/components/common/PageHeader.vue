<script setup lang="ts">
import type { HTMLAttributes } from 'vue'

import { cn } from '@/lib/utils'

/** Page title block. Rich parts go in the `eyebrow`, `title`, `description` and `actions` slots. */
const props = defineProps<{ title?: string; description?: string; eyebrow?: string; class?: HTMLAttributes['class'] }>()
const slots = defineSlots<{ eyebrow?(): unknown; title?(): unknown; description?(): unknown; actions?(): unknown }>()
</script>

<template>
  <div :class="cn('mb-6 flex flex-wrap items-end justify-between gap-x-6 gap-y-3', props.class)">
    <div class="min-w-0 space-y-1">
      <div v-if="slots.eyebrow || eyebrow" class="text-xs font-medium text-muted-foreground">
        <slot name="eyebrow">{{ eyebrow }}</slot>
      </div>
      <h1 class="text-[22px] leading-tight font-semibold tracking-tight">
        <slot name="title">{{ title }}</slot>
      </h1>
      <div v-if="slots.description || description" class="text-sm text-muted-foreground">
        <slot name="description">{{ description }}</slot>
      </div>
    </div>
    <div v-if="slots.actions" class="flex shrink-0 flex-wrap items-center gap-2">
      <slot name="actions" />
    </div>
  </div>
</template>
