<script setup lang="ts">
import { CircleCheckIcon, CircleXIcon } from '@lucide/vue'

import type { ModelRequirement } from '@/api/types'

/** What this machine has and lacks for a provider. Credentials appear as present/absent only. */
defineProps<{ requirements: ModelRequirement[] }>()
</script>

<template>
  <ul class="divide-y rounded-lg border bg-card text-[13px]">
    <li v-for="r in requirements" :key="r.key" class="flex items-start gap-2.5 px-3 py-2.5" :data-ok="r.ok">
      <CircleCheckIcon v-if="r.ok" class="mt-px size-4 shrink-0 text-success" aria-label="충족" />
      <CircleXIcon v-else class="mt-px size-4 shrink-0 text-danger" aria-label="미충족" />
      <div class="min-w-0 flex-1">
        <p>
          <span class="font-medium">{{ r.label }}</span>
          <span class="text-muted-foreground"> · {{ r.detail }}</span>
        </p>
        <p v-if="!r.ok && r.fix" class="mt-0.5 text-xs text-muted-foreground">해결: {{ r.fix }}</p>
      </div>
    </li>
  </ul>
</template>
