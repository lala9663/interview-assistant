<script setup lang="ts">
import { PenLineIcon } from '@lucide/vue'
import { ref } from 'vue'

import type { QAItem } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'

import { submitOnModEnter } from './transcript-utils'

const props = defineProps<{ qa: QAItem; pending: boolean }>()
const emit = defineEmits<{ save: [answer: string] }>()

const text = ref('')
const save = () => {
  const t = text.value.trim()
  if (!t || props.pending) return
  emit('save', t)
  text.value = ''
}
</script>

<template>
  <div class="border-t bg-[color-mix(in_oklch,var(--warning)_5%,transparent)] px-3 pt-3">
    <p class="mb-1.5 flex items-center gap-1.5 text-xs font-medium">
      <PenLineIcon class="size-3.5 text-warning" aria-hidden="true" />
      Q{{ qa.seq }} 답변 수기 기록
      <span class="font-normal text-muted-foreground">· 저장하면 비식별화 후 꼬리질문 제안에 쓰입니다</span>
    </p>
    <Textarea
      v-model="text"
      placeholder="지원자 답변의 요지를 입력하세요 (Ctrl+Enter 저장)"
      :aria-label="`Q${qa.seq} 답변 입력`"
      class="min-h-20 bg-card"
      @keydown="(e: KeyboardEvent) => submitOnModEnter(e, save)"
    />
    <div class="flex justify-end py-2">
      <Button size="sm" variant="secondary" :disabled="pending || !text.trim()" @click="save">답변 저장</Button>
    </div>
  </div>
</template>
