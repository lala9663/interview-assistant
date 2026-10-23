<script setup lang="ts">
import { AlertDialogCancel } from 'reka-ui'
import type { HTMLAttributes } from 'vue'

import { buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const props = defineProps<{ class?: HTMLAttributes['class'] }>()
</script>

<template>
  <AlertDialogCancel :class="cn(buttonVariants({ variant: 'outline' }), props.class)"><slot /></AlertDialogCancel>
</template>
