<script setup lang="ts">
import { LoaderIcon } from '@lucide/vue'

import type { AiScoringStatus } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { AI_SCORING_LABEL } from '@/lib/labels'

defineProps<{ status: AiScoringStatus }>()
</script>

<template>
  <Badge v-if="status === 'running'" variant="brand">
    <LoaderIcon class="animate-spin" aria-hidden="true" />
    AI {{ AI_SCORING_LABEL[status] }}
  </Badge>
  <Badge v-else-if="status === 'failed'" variant="danger">AI {{ AI_SCORING_LABEL[status] }}</Badge>
  <Badge v-else-if="status === 'completed'" variant="outline">AI 채점 완료</Badge>
  <Badge v-else variant="outline">AI 채점 전</Badge>
</template>
