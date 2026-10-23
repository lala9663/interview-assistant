<script setup lang="ts">
import { XIcon } from '@lucide/vue'
import { DialogClose, DialogContent, DialogOverlay, DialogPortal } from 'reka-ui'
import type { HTMLAttributes } from 'vue'

import { overlayClass } from '@/components/ui/dialog/overlay'
import { cn } from '@/lib/utils'

defineOptions({ inheritAttrs: false })
const props = withDefaults(defineProps<{ side?: 'left' | 'right'; class?: HTMLAttributes['class'] }>(), { side: 'right' })
</script>

<template>
  <DialogPortal>
    <DialogOverlay :class="cn(overlayClass, 'bg-black/30')" />
    <DialogContent
      v-bind="$attrs"
      :class="
        cn(
          'fixed inset-y-0 z-50 flex h-full w-full max-w-[min(640px,calc(100vw-2rem))] flex-col bg-popover text-popover-foreground shadow-2xl outline-none data-[state=open]:animate-in data-[state=open]:duration-300 data-[state=closed]:animate-out data-[state=closed]:duration-200',
          side === 'right'
            ? 'right-0 border-l data-[state=open]:slide-in-from-right data-[state=closed]:slide-out-to-right'
            : 'left-0 border-r data-[state=open]:slide-in-from-left data-[state=closed]:slide-out-to-left',
          props.class,
        )
      "
    >
      <slot />
      <DialogClose class="absolute top-4 right-4 rounded-md p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
        <XIcon class="size-4" />
        <span class="sr-only">닫기</span>
      </DialogClose>
    </DialogContent>
  </DialogPortal>
</template>
