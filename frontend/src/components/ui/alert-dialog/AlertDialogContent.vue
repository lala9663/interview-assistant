<script setup lang="ts">
import { AlertDialogContent, AlertDialogOverlay, AlertDialogPortal } from 'reka-ui'
import type { HTMLAttributes } from 'vue'

import { overlayClass } from '@/components/ui/dialog/overlay'
import { cn } from '@/lib/utils'

defineOptions({ inheritAttrs: false })
const props = defineProps<{ class?: HTMLAttributes['class'] }>()
</script>

<template>
  <AlertDialogPortal>
    <AlertDialogOverlay :class="overlayClass" />
    <AlertDialogContent
      v-bind="$attrs"
      :class="
        cn(
          'fixed top-1/2 left-1/2 z-50 grid w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 gap-4 rounded-xl border bg-popover p-6 text-popover-foreground shadow-2xl data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-[0.97] data-[state=closed]:animate-out data-[state=closed]:fade-out-0',
          props.class,
        )
      "
    >
      <slot />
    </AlertDialogContent>
  </AlertDialogPortal>
</template>
