<script setup lang="ts">
import { CircleDotIcon } from '@lucide/vue'
import { computed } from 'vue'

import type { ApplicationStage } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { STAGE_LABEL } from '@/lib/labels'

const props = defineProps<{ stage: ApplicationStage }>()
const variant = computed(() =>
  props.stage === 'interviewing' ? 'live' : props.stage === 'evaluated' ? 'success' : props.stage === 'screening' ? 'outline' : 'brand',
)
</script>

<template>
  <Badge :variant="variant">
    <span v-if="stage === 'interviewing'" class="size-1.5 rounded-full bg-live" aria-hidden="true"></span>
    <CircleDotIcon v-else aria-hidden="true" />
    {{ STAGE_LABEL[stage] }}
  </Badge>
</template>
