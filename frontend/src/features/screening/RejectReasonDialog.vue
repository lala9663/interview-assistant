<script setup lang="ts">
import { ref, watch } from 'vue'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'

/** 탈락 needs a short reason. It is de-identified, kept on the screening and in the audit log.
 * `editing`: the application is already 탈락 and only the reason changes. */
const props = defineProps<{ open: boolean; pseudonym: string; initial?: string | null; editing?: boolean; pending?: boolean }>()
const emit = defineEmits<{ close: []; submit: [reason: string] }>()

const MAX = 500
const reason = ref('')
// Taken when the dialog opens: saving flips the status to 탈락 while the dialog is still fading out.
const editingNow = ref(false)
watch(
  () => props.open,
  (open) => {
    if (!open) return
    reason.value = props.initial ?? ''
    editingNow.value = props.editing ?? false
  },
  { immediate: true },
)
const submit = () => {
  const text = reason.value.trim()
  if (text && text.length <= MAX) emit('submit', text)
}
</script>

<template>
  <Dialog :open="open" @update:open="(o) => !o && emit('close')">
    <DialogContent>
      <DialogHeader>
        <DialogTitle>{{ pseudonym }} 탈락 사유</DialogTitle>
        <DialogDescription>왜 탈락인지 한두 문장으로 남겨 주세요. 지원자 상세와 감사 로그에 남고, 개인정보는 비식별 처리됩니다.</DialogDescription>
      </DialogHeader>
      <form id="reject-form" class="space-y-1.5" @submit.prevent="submit">
        <Label for="reject-reason">사유</Label>
        <Textarea id="reject-reason" v-model="reason" rows="3" :maxlength="MAX" placeholder="예: 필수 요건인 단위공정 경력 3년에 못 미칩니다." />
        <p class="text-right text-[11px] text-muted-foreground tabular">{{ reason.trim().length }} / {{ MAX }}</p>
      </form>
      <DialogFooter>
        <Button variant="outline" @click="emit('close')">취소</Button>
        <Button type="submit" form="reject-form" variant="destructive" :disabled="!reason.trim() || pending">{{ editingNow ? '사유 저장' : '탈락 처리' }}</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
