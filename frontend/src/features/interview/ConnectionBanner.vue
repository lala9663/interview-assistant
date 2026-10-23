<script setup lang="ts">
import { RotateCwIcon, WifiOffIcon } from '@lucide/vue'

import { Button } from '@/components/ui/button'

import type { Connection } from './use-transcript'

defineProps<{ connection: Connection }>()
const emit = defineEmits<{ reconnect: [] }>()
</script>

<template>
  <div
    v-if="connection === 'error' || connection === 'reconnecting'"
    role="status"
    class="mx-4 mt-3 flex items-center gap-2.5 rounded-lg border border-[color-mix(in_oklch,var(--warning)_35%,transparent)] bg-[color-mix(in_oklch,var(--warning)_9%,transparent)] px-3 py-2 text-[12.5px]"
  >
    <WifiOffIcon class="size-4 shrink-0 text-warning" aria-hidden="true" />
    <span class="flex-1">
      {{
        connection === 'reconnecting'
          ? '전사 연결이 끊겨 다시 연결하는 중입니다. 녹음은 계속됩니다.'
          : '전사 연결이 끊겼습니다. 녹음은 계속되며, 답변은 아래에 수기로 기록할 수 있습니다.'
      }}
    </span>
    <Button v-if="connection === 'error'" size="xs" variant="outline" @click="emit('reconnect')">
      <RotateCwIcon />
      다시 연결
    </Button>
  </div>
</template>
