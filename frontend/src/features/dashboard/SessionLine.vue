<script setup lang="ts">
import { ArrowRightIcon } from '@lucide/vue'
import { RouterLink } from 'vue-router'

import type { SessionSummary } from '@/api/types'
import ModeBadge from '@/components/common/ModeBadge.vue'
import PanelAvatars from '@/components/common/PanelAvatars.vue'
import Pseudonym from '@/components/common/Pseudonym.vue'
import SessionStatusBadge from '@/components/common/SessionStatusBadge.vue'
import { formatTime } from '@/lib/time'
import { cn } from '@/lib/utils'

defineProps<{ s: SessionSummary }>()
</script>

<template>
  <li>
    <RouterLink
      :to="s.status === 'completed' ? `/sessions/${s.id}/evaluation` : `/sessions/${s.id}/live`"
      :class="
        cn(
          'flex items-center gap-3 rounded-lg border border-transparent px-2.5 py-2.5 transition-colors hover:border-border hover:bg-subtle',
          s.status === 'in_progress' && 'border-[color-mix(in_oklch,var(--live)_30%,transparent)] bg-[color-mix(in_oklch,var(--live)_6%,transparent)]',
        )
      "
    >
      <div class="w-12 shrink-0 text-center">
        <div class="text-sm font-semibold tabular">{{ s.scheduled_at ? formatTime(s.scheduled_at) : '–' }}</div>
      </div>
      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-2">
          <Pseudonym :value="s.candidate.pseudonym" size="sm" />
          <SessionStatusBadge :status="s.status" />
        </div>
        <div class="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
          <span class="truncate">{{ s.posting.title }}</span>
          <ModeBadge :mode="s.mode" />
        </div>
      </div>
      <PanelAvatars :panel="s.interviewers" />
      <ArrowRightIcon class="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
    </RouterLink>
  </li>
</template>
