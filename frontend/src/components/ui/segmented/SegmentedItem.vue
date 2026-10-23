<script setup lang="ts">
import { ToggleGroupItem } from 'reka-ui'
import { computed, inject, type HTMLAttributes } from 'vue'

import { cn } from '@/lib/utils'

import { SEGMENTED_VALUE } from './context'

const props = defineProps<{ value: string; disabled?: boolean; class?: HTMLAttributes['class'] }>()
const selected = inject(SEGMENTED_VALUE, undefined)
const checked = computed(() => selected?.value === props.value)
</script>

<template>
  <!-- Selected state via aria-checked: a wrapping Tooltip trigger overwrites data-state. -->
  <ToggleGroupItem
    :value="value"
    :disabled="disabled"
    role="radio"
    :aria-checked="checked"
    :aria-pressed="undefined"
    :class="
      cn(
        'inline-flex h-7 items-center justify-center gap-1.5 rounded-md px-2.5 text-[13px] font-medium text-muted-foreground transition-[color,background-color,box-shadow] outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-50 aria-checked:bg-card aria-checked:text-foreground aria-checked:shadow-sm dark:aria-checked:bg-accent [&_svg:not([class*=size-])]:size-3.5',
        props.class,
      )
    "
  >
    <slot />
  </ToggleGroupItem>
</template>
