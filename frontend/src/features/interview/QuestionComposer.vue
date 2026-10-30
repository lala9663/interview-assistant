<script setup lang="ts">
import { CornerDownLeftIcon } from '@lucide/vue'
import { ref } from 'vue'

import { Button } from '@/components/ui/button'
import { Kbd } from '@/components/ui/kbd'

import { roomShortcut, useWindowKeys } from './room-keys'
import { blurOnEscape, submitOnEnter } from './transcript-utils'

const props = defineProps<{ disabled: boolean; pending: boolean }>()
const emit = defineEmits<{ submit: [text: string] }>()

const text = ref('')
const box = ref<HTMLTextAreaElement>()
const submit = () => {
  const t = text.value.trim()
  if (!t || props.disabled || props.pending) return
  emit('submit', t)
  text.value = ''
}
const onKey = (e: KeyboardEvent) => {
  blurOnEscape(e)
  submitOnEnter(e, submit)
}
// "/" from anywhere in the room jumps here; Esc goes back to the number keys.
useWindowKeys((e) => {
  if (e.key !== '/' || !roomShortcut(e)) return
  e.preventDefault()
  box.value?.focus()
})
</script>

<template>
  <div class="border-t bg-card/60 p-3">
    <div class="flex items-end gap-2 rounded-lg border bg-card p-1.5 pl-3 focus-within:border-ring focus-within:ring-2 focus-within:ring-ring/25">
      <textarea
        ref="box"
        v-model="text"
        rows="1"
        :disabled="disabled"
        placeholder="직접 질문 입력 — Enter 기록, Shift+Enter 줄바꿈, Esc 나가기"
        aria-label="직접 질문 입력"
        aria-keyshortcuts="/"
        class="max-h-32 min-h-8 flex-1 resize-none bg-transparent py-1.5 text-sm outline-none placeholder:text-muted-foreground disabled:opacity-50 [field-sizing:content]"
        @keydown="onKey"
      ></textarea>
      <Kbd class="mb-2 hidden sm:inline-flex" aria-hidden="true">/</Kbd>
      <Button size="sm" :disabled="disabled || pending || !text.trim()" @click="submit">
        <CornerDownLeftIcon />
        질문 기록
      </Button>
    </div>
  </div>
</template>
