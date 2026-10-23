<script setup lang="ts">
import { DialogTitle } from 'reka-ui'
import type { HTMLAttributes } from 'vue'

import { cn } from '@/lib/utils'

const props = defineProps<{ asChild?: boolean; class?: HTMLAttributes['class'] }>()
</script>

<template>
  <DialogTitle :as-child="asChild" :class="cn('text-base font-semibold tracking-tight', props.class)"><slot /></DialogTitle>
</template>
