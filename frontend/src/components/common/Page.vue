<script setup lang="ts">
import type { HTMLAttributes } from 'vue'

import { cn } from '@/lib/utils'

const props = defineProps<{ class?: HTMLAttributes['class'] }>()
</script>

<template>
  <div :class="cn('mx-auto w-full max-w-[1360px] px-5 pt-6 pb-16 lg:px-8', props.class)"><slot /></div>
</template>
