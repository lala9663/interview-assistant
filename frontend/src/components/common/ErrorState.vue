<script setup lang="ts">
import { CircleAlertIcon, RotateCwIcon } from '@lucide/vue'
import { computed, type HTMLAttributes } from 'vue'

import { ApiError } from '@/api/client'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const props = defineProps<{ error: unknown; class?: HTMLAttributes['class'] }>()
const emit = defineEmits<{ retry: [] }>()

const message = computed(() =>
  props.error instanceof ApiError ? props.error.message : props.error instanceof Error ? props.error.message : '알 수 없는 오류입니다.',
)
const status = computed(() => (props.error instanceof ApiError && props.error.status ? ` · ${props.error.status}` : ''))
</script>

<template>
  <div role="alert" :class="cn('flex flex-col items-center justify-center gap-3 py-14 text-center', props.class)">
    <div
      class="flex size-10 items-center justify-center rounded-xl border border-[color-mix(in_oklch,var(--danger)_30%,transparent)] bg-[color-mix(in_oklch,var(--danger)_8%,transparent)]"
    >
      <CircleAlertIcon class="size-[18px] text-danger" aria-hidden="true" />
    </div>
    <div class="space-y-1">
      <p class="text-sm font-medium">불러오지 못했습니다</p>
      <p class="text-[13px] text-muted-foreground">{{ message }}{{ status }}</p>
    </div>
    <Button variant="outline" size="sm" @click="emit('retry')">
      <RotateCwIcon />
      다시 시도
    </Button>
  </div>
</template>
