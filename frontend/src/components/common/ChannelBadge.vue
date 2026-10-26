<script setup lang="ts">
import { GlobeIcon, UploadIcon } from '@lucide/vue'

import type { ApplicationChannel } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { CHANNEL_LABEL } from '@/lib/labels'

/** 수신 경로: from the recruiting site, or uploaded on the screening screen. */
defineProps<{ channel: ApplicationChannel }>()
</script>

<template>
  <Badge :variant="channel === 'site' ? 'brand' : 'outline'" data-testid="channel-badge">
    <GlobeIcon v-if="channel === 'site'" aria-hidden="true" />
    <UploadIcon v-else aria-hidden="true" />
    {{ CHANNEL_LABEL[channel] }}
  </Badge>
</template>
