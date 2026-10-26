<script setup lang="ts">
import type { DataLocation } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Tooltip } from '@/components/ui/tooltip'

import { DATA_LOCATION } from './labels'

const props = defineProps<{ location: DataLocation }>()
</script>

<template>
  <Tooltip :content="DATA_LOCATION[props.location].hint">
    <Badge :variant="DATA_LOCATION[props.location].variant" data-testid="data-location">
      <component :is="DATA_LOCATION[props.location].icon" aria-hidden="true" />
      {{ DATA_LOCATION[props.location].label }}
    </Badge>
  </Tooltip>
</template>
