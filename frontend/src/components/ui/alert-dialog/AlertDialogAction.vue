<script setup lang="ts">
import { AlertDialogAction } from 'reka-ui'
import type { HTMLAttributes } from 'vue'

import { buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const props = defineProps<{ class?: HTMLAttributes['class'] }>()
</script>

<template>
  <AlertDialogAction :class="cn(buttonVariants(), props.class)"><slot /></AlertDialogAction>
</template>
