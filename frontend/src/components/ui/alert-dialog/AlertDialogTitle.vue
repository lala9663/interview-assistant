<script setup lang="ts">
import { AlertDialogTitle } from 'reka-ui'
import type { HTMLAttributes } from 'vue'

import { cn } from '@/lib/utils'

const props = defineProps<{ class?: HTMLAttributes['class'] }>()
</script>

<template>
  <AlertDialogTitle :class="cn('text-base font-semibold tracking-tight', props.class)"><slot /></AlertDialogTitle>
</template>
