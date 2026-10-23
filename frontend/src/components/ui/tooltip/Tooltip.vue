<script setup lang="ts">
import { TooltipContent, TooltipPortal, TooltipRoot, TooltipTrigger } from 'reka-ui'
import type { HTMLAttributes } from 'vue'

import { cn } from '@/lib/utils'

/** Tooltip around a single focusable child; text via the `content` prop or the `content` slot. */
const props = withDefaults(
  defineProps<{ content?: string; side?: 'top' | 'bottom' | 'left' | 'right'; class?: HTMLAttributes['class'] }>(),
  { content: '', side: 'top' },
)
</script>

<template>
  <TooltipRoot>
    <TooltipTrigger as-child><slot /></TooltipTrigger>
    <TooltipPortal>
      <TooltipContent
        :side="side"
        :side-offset="6"
        :class="
          cn(
            'z-50 max-w-72 rounded-md bg-foreground px-2.5 py-1.5 text-xs leading-relaxed text-background shadow-lg data-[state=delayed-open]:animate-in data-[state=delayed-open]:fade-in-0 data-[state=closed]:animate-out data-[state=closed]:fade-out-0',
            props.class,
          )
        "
      >
        <slot name="content">{{ content }}</slot>
      </TooltipContent>
    </TooltipPortal>
  </TooltipRoot>
</template>
