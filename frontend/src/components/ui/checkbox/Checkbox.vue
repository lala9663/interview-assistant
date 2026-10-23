<script setup lang="ts">
import { CheckIcon } from '@lucide/vue'
import { CheckboxIndicator, CheckboxRoot } from 'reka-ui'
import type { HTMLAttributes } from 'vue'

import { cn } from '@/lib/utils'

const props = defineProps<{ disabled?: boolean; class?: HTMLAttributes['class'] }>()
const checked = defineModel<boolean>({ default: false })
</script>

<template>
  <CheckboxRoot
    v-model="checked"
    :disabled="disabled"
    :class="
      cn(
        'peer size-4 shrink-0 rounded-[4px] border border-input bg-card transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-50 data-[state=checked]:border-primary data-[state=checked]:bg-primary data-[state=checked]:text-primary-foreground',
        props.class,
      )
    "
  >
    <CheckboxIndicator class="flex items-center justify-center">
      <CheckIcon class="size-3" :stroke-width="3" />
    </CheckboxIndicator>
  </CheckboxRoot>
</template>
