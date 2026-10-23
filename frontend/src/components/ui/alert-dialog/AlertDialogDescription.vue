<script setup lang="ts">
import { AlertDialogDescription } from 'reka-ui'
import type { HTMLAttributes } from 'vue'

import { cn } from '@/lib/utils'

const props = defineProps<{ class?: HTMLAttributes['class'] }>()
</script>

<template>
  <AlertDialogDescription :class="cn('text-sm leading-relaxed text-muted-foreground', props.class)"><slot /></AlertDialogDescription>
</template>
