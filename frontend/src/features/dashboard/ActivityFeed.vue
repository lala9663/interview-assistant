<script setup lang="ts">
import { computed } from 'vue'

import type { ActivityItem } from '@/api/types'
import { formatRelative } from '@/lib/time'
import { cn } from '@/lib/utils'

import { describeActivity, HIDDEN_ACTIONS } from './activity'

const props = defineProps<{ items: ActivityItem[] }>()
const visible = computed(() => props.items.filter((a) => !HIDDEN_ACTIONS.has(a.action)).map((a) => ({ a, ...describeActivity(a) })))
const PART_CLASS = {
  text: '',
  strong: 'font-medium text-foreground',
  pseudo: 'font-mono text-[12.5px] font-semibold text-foreground',
  muted: 'text-muted-foreground',
}
</script>

<template>
  <ol class="relative">
    <li v-for="(v, i) in visible" :key="v.a.id" class="relative flex gap-3 pb-4 last:pb-0">
      <span v-if="i < visible.length - 1" class="absolute top-7 bottom-0 left-[13px] w-px bg-border" aria-hidden="true"></span>
      <span :class="cn('relative flex size-7 shrink-0 items-center justify-center rounded-full border bg-card', v.ai && 'border-brand-border bg-brand-soft')">
        <component :is="v.icon" :class="cn('size-3.5', v.ai ? 'text-brand' : 'text-muted-foreground')" aria-hidden="true" />
      </span>
      <div class="min-w-0 pt-1">
        <p class="text-[13px] leading-snug text-muted-foreground"
          ><span v-for="(p, j) in v.parts" :key="j" :class="PART_CLASS[p.kind] || undefined">{{ p.text }}</span></p
        >
        <p class="mt-0.5 text-[11.5px] text-muted-foreground/80">{{ formatRelative(v.a.occurred_at) }}</p>
      </div>
    </li>
  </ol>
</template>
