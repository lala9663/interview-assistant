<script setup lang="ts">
import { Label } from 'reka-ui'
import type { HTMLAttributes } from 'vue'

import { cn } from '@/lib/utils'

const props = defineProps<{ for?: string; class?: HTMLAttributes['class'] }>()
</script>

<template>
  <Label data-slot="label" :for="props.for" :class="cn('text-[13px] leading-none font-medium select-none peer-disabled:opacity-50', props.class)">
    <slot />
  </Label>
</template>
