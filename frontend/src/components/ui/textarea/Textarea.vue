<script setup lang="ts">
import { ref, type HTMLAttributes } from 'vue'

import { cn } from '@/lib/utils'

const props = defineProps<{ class?: HTMLAttributes['class'] }>()
const model = defineModel<string>({ default: '' })

const el = ref<HTMLTextAreaElement>()
defineExpose({ focus: () => el.value?.focus() })
</script>

<template>
  <textarea
    ref="el"
    v-model="model"
    data-slot="textarea"
    :class="
      cn(
        'flex min-h-16 w-full rounded-md border border-input bg-card px-3 py-2 text-sm leading-relaxed transition-[border-color,box-shadow] outline-none placeholder:text-muted-foreground/80 focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-50',
        props.class,
      )
    "
  ></textarea>
</template>
