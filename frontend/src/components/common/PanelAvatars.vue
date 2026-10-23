<script setup lang="ts">
import { computed, type HTMLAttributes } from 'vue'

import type { SessionInterviewerView } from '@/api/types'
import { Tooltip } from '@/components/ui/tooltip'
import { ROLE_LABEL } from '@/lib/labels'
import { cn } from '@/lib/utils'

const props = defineProps<{ panel: SessionInterviewerView[]; class?: HTMLAttributes['class'] }>()
const tip = computed(() => props.panel.map((p) => `${p.interviewer.name} (${ROLE_LABEL[p.role]})`).join(', '))
const label = computed(() => `면접관 ${props.panel.map((p) => p.interviewer.name).join(', ')}`)
</script>

<template>
  <Tooltip :content="tip">
    <span :class="cn('flex -space-x-1.5', props.class)" tabindex="0" :aria-label="label">
      <span
        v-for="p in panel"
        :key="p.interviewer_id"
        :class="
          cn(
            'flex size-6 shrink-0 items-center justify-center rounded-full border-2 border-card bg-muted text-[10.5px] font-semibold text-foreground',
            p.role === 'lead' && 'ring-1 ring-brand-border',
          )
        "
        >{{ p.interviewer.name.slice(0, 1) }}</span
      >
    </span>
  </Tooltip>
</template>
