<script setup lang="ts">
import { TabsList } from 'reka-ui'
import type { HTMLAttributes } from 'vue'

import { cn } from '@/lib/utils'

const props = defineProps<{ class?: HTMLAttributes['class'] }>()
</script>

<template>
  <TabsList :class="cn('inline-flex h-9 items-center gap-0.5 rounded-lg bg-muted p-[3px] text-muted-foreground', props.class)">
    <slot />
  </TabsList>
</template>
