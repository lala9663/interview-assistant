<script setup lang="ts">
import type { Component, HTMLAttributes } from 'vue'

import { cn } from '@/lib/utils'

/** Empty/zero state: icon, title, optional description (prop or slot) and an `action` slot. */
const props = defineProps<{ icon: Component; title: string; description?: string; compact?: boolean; class?: HTMLAttributes['class'] }>()
const slots = defineSlots<{ description?(): unknown; action?(): unknown }>()
</script>

<template>
  <div :class="cn('flex flex-col items-center justify-center text-center', compact ? 'gap-2 py-8' : 'gap-3 py-14', props.class)">
    <div class="relative">
      <div class="absolute inset-0 -m-3 rounded-full bg-dots opacity-70 [mask-image:radial-gradient(circle,black_40%,transparent_70%)]"></div>
      <div class="relative flex size-10 items-center justify-center rounded-xl border bg-card shadow-soft">
        <component :is="icon" class="size-[18px] text-muted-foreground" aria-hidden="true" />
      </div>
    </div>
    <div class="space-y-1">
      <p class="text-sm font-medium">{{ title }}</p>
      <p v-if="slots.description || description" class="mx-auto max-w-sm text-[13px] leading-relaxed text-muted-foreground">
        <slot name="description">{{ description }}</slot>
      </p>
    </div>
    <slot name="action" />
  </div>
</template>
