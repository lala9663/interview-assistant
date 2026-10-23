<script setup lang="ts">
import { ToggleGroupRoot } from 'reka-ui'
import { computed, provide, type HTMLAttributes } from 'vue'

import { cn } from '@/lib/utils'

import { SEGMENTED_VALUE } from './context'

/**
 * Single-choice segmented control (Reka ToggleGroup) exposed as a radio group, like Radix's single
 * ToggleGroup: arrow keys move focus only, and clicking the selected item never clears the value.
 */
const props = defineProps<{ modelValue?: string; disabled?: boolean; class?: HTMLAttributes['class'] }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

provide(
  SEGMENTED_VALUE,
  computed(() => props.modelValue),
)

function onUpdate(v: unknown) {
  if (typeof v === 'string' && v) emit('update:modelValue', v)
}
</script>

<template>
  <!-- as-child: the div's own role wins over Reka's role="group" (a fallthrough attribute would not). -->
  <ToggleGroupRoot as-child type="single" :model-value="modelValue" :disabled="disabled" @update:model-value="onUpdate">
    <div role="radiogroup" :class="cn('inline-flex items-center gap-0.5 rounded-lg bg-muted p-[3px]', props.class)">
      <slot />
    </div>
  </ToggleGroupRoot>
</template>
