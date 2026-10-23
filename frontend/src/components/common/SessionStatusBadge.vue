<script setup lang="ts">
import type { SessionStatus } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { SESSION_STATUS_LABEL } from '@/lib/labels'

import { SESSION_LOOK } from './status'

defineProps<{ status: SessionStatus }>()
</script>

<template>
  <Badge v-if="status === 'in_progress'" variant="live">
    <span class="size-1.5 animate-live rounded-full bg-live" aria-hidden="true"></span>
    {{ SESSION_STATUS_LABEL[status] }}
  </Badge>
  <Badge v-else :variant="SESSION_LOOK[status].variant">
    <component :is="SESSION_LOOK[status].icon" aria-hidden="true" />
    {{ SESSION_STATUS_LABEL[status] }}
  </Badge>
</template>
