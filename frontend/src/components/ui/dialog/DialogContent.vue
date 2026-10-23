<script setup lang="ts">
import { XIcon } from '@lucide/vue'
import { DialogClose, DialogContent, DialogOverlay, DialogPortal } from 'reka-ui'
import type { HTMLAttributes } from 'vue'

import { cn } from '@/lib/utils'

import { overlayClass } from './overlay'

defineOptions({ inheritAttrs: false })
const props = defineProps<{ hideClose?: boolean; class?: HTMLAttributes['class'] }>()
</script>

<template>
  <DialogPortal>
    <DialogOverlay :class="overlayClass" />
    <DialogContent
      v-bind="$attrs"
      :class="
        cn(
          'fixed top-1/2 left-1/2 z-50 grid max-h-[calc(100vh-2rem)] w-[calc(100%-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 gap-4 overflow-y-auto rounded-xl border bg-popover p-6 text-popover-foreground shadow-2xl outline-none data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-[0.97] data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-[0.97]',
          props.class,
        )
      "
    >
      <slot />
      <DialogClose
        v-if="!hideClose"
        class="absolute top-4 right-4 rounded-md p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
      >
        <XIcon class="size-4" />
        <span class="sr-only">닫기</span>
      </DialogClose>
    </DialogContent>
  </DialogPortal>
</template>
