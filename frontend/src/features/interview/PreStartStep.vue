<script setup lang="ts">
import { CheckIcon } from '@lucide/vue'

import { cn } from '@/lib/utils'

defineProps<{ n: number; title: string; done: boolean }>()
</script>

<template>
  <li class="relative flex gap-4 pb-6 last:pb-0">
    <span
      :class="
        cn(
          'relative z-10 flex size-7 shrink-0 items-center justify-center rounded-full border text-xs font-semibold',
          done ? 'border-transparent bg-success text-white' : 'bg-card',
        )
      "
    >
      <CheckIcon v-if="done" class="size-3.5" :stroke-width="3" aria-hidden="true" />
      <template v-else>{{ n }}</template>
    </span>
    <div class="min-w-0 flex-1 pt-0.5">
      <p class="text-sm font-semibold">{{ title }}</p>
      <div class="mt-2"><slot /></div>
    </div>
  </li>
</template>
