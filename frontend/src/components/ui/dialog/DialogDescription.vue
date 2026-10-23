<script setup lang="ts">
import { DialogDescription } from 'reka-ui'
import type { HTMLAttributes } from 'vue'

import { cn } from '@/lib/utils'

const props = defineProps<{ class?: HTMLAttributes['class'] }>()
</script>

<template>
  <DialogDescription :class="cn('text-sm text-muted-foreground', props.class)"><slot /></DialogDescription>
</template>
