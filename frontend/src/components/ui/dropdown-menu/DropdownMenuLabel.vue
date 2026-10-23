<script setup lang="ts">
import { DropdownMenuLabel } from 'reka-ui'
import type { HTMLAttributes } from 'vue'

import { cn } from '@/lib/utils'

const props = defineProps<{ class?: HTMLAttributes['class'] }>()
</script>

<template>
  <DropdownMenuLabel :class="cn('px-2 py-1.5 text-xs font-medium text-muted-foreground', props.class)"><slot /></DropdownMenuLabel>
</template>
