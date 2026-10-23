<script setup lang="ts">
import { DropdownMenuItemIndicator, DropdownMenuRadioItem } from 'reka-ui'
import type { HTMLAttributes } from 'vue'

import { cn } from '@/lib/utils'

const props = defineProps<{ value: string; class?: HTMLAttributes['class'] }>()
</script>

<template>
  <DropdownMenuRadioItem
    :value="value"
    :class="
      cn(
        'relative flex cursor-default items-center gap-2 rounded-md px-2 py-1.5 pr-8 text-sm outline-none select-none data-[disabled]:pointer-events-none data-[disabled]:opacity-50 data-[highlighted]:bg-accent [&_svg:not([class*=size-])]:size-4 [&_svg]:text-muted-foreground',
        props.class,
      )
    "
  >
    <slot />
    <DropdownMenuItemIndicator class="absolute right-2 flex size-3.5 items-center justify-center">
      <span class="size-1.5 rounded-full bg-foreground"></span>
    </DropdownMenuItemIndicator>
  </DropdownMenuRadioItem>
</template>
