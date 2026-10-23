<script setup lang="ts">
import type { ScreeningStatus } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { SCREENING_STATUS_LABEL } from '@/lib/labels'

import { SCREENING_LOOK } from './status'

defineProps<{ status: ScreeningStatus }>()
</script>

<template>
  <Badge :variant="SCREENING_LOOK[status].variant">
    <component :is="SCREENING_LOOK[status].icon" aria-hidden="true" />
    {{ SCREENING_STATUS_LABEL[status] }}
  </Badge>
</template>
