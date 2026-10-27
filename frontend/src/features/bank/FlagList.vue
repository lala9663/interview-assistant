<script setup lang="ts">
import { ShieldAlertIcon, SparklesIcon } from '@lucide/vue'

import type { BankFlag } from '@/api/types'

/** Prohibited-question warnings (채용 면접 금지 질문): what matched, under which rule, and its legal basis. */
defineProps<{ flags: BankFlag[]; compact?: boolean }>()
</script>

<template>
  <ul v-if="flags.length" class="space-y-1" role="list" aria-label="금지 질문 경고" data-testid="bank-flags">
    <li
      v-for="f in flags"
      :key="`${f.source}-${f.category}`"
      class="flex items-start gap-1.5 rounded-md border border-[color-mix(in_oklch,var(--warning)_35%,transparent)] bg-[color-mix(in_oklch,var(--warning)_7%,transparent)] px-2 py-1 text-xs"
    >
      <component :is="f.source === 'ai' ? SparklesIcon : ShieldAlertIcon" class="mt-0.5 size-3.5 shrink-0 text-warning" aria-hidden="true" />
      <span class="min-w-0">
        <span class="font-medium text-warning">{{ f.label }}</span>
        <span class="text-muted-foreground"> · “{{ f.matched }}”{{ f.source === 'ai' ? ' · AI 확인' : '' }}</span>
        <span v-if="!compact" class="block text-[11px] text-muted-foreground">{{ f.note || f.basis }}</span>
      </span>
    </li>
  </ul>
</template>
