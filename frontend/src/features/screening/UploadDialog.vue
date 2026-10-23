<script setup lang="ts">
import { ref } from 'vue'
import { toast } from 'vue-sonner'

import { useUploadApplication } from '@/api/queries'
import type { UploadResult } from '@/api/types'
import PrivacyNote from '@/components/common/PrivacyNote.vue'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { toastError } from '@/lib/toast'

/**
 * 서류 업로드 (FR-01): one application file plus what the application form says about the candidate.
 * The server uses name and contact details only to find and mask them; the screen shows the pseudonym.
 */
const props = defineProps<{ open: boolean; postingId: string; postingTitle: string }>()
const emit = defineEmits<{ close: []; uploaded: [result: UploadResult] }>()

const ACCEPT = '.pdf,.docx,.pptx,.html,.htm'
const upload = useUploadApplication(() => props.postingId)
const fileInput = ref<HTMLInputElement | null>(null)
const file = ref<File | null>(null)
const name = ref('')
const aliases = ref('')
const phone = ref('')
const email = ref('')

function reset() {
  file.value = null
  name.value = ''
  aliases.value = ''
  phone.value = ''
  email.value = ''
  if (fileInput.value) fileInput.value.value = ''
}

function close() {
  if (upload.isPending) return
  reset()
  emit('close')
}

function pick(e: Event) {
  file.value = (e.target as HTMLInputElement).files?.[0] ?? null
}

function submit() {
  if (!file.value || !name.value.trim()) return
  upload.mutate(
    { file: file.value, name: name.value.trim(), aliases: aliases.value.trim(), phone: phone.value.trim(), email: email.value.trim() },
    {
      onSuccess: (r) => {
        const hidden = r.document.hidden_blocks ? ` 숨은 텍스트 ${r.document.hidden_blocks}곳은 선별에서 뺐습니다.` : ''
        toast.success(`${r.candidate.pseudonym} 서류를 선별했습니다`, {
          description: `적합도 ${r.screening.fit_score} · 보류로 시작합니다. 통과·탈락은 직접 정하세요.${hidden}`,
        })
        reset()
        emit('uploaded', r)
      },
      onError: toastError('서류를 올리지 못했습니다'),
    },
  )
}
</script>

<template>
  <Dialog :open="open" @update:open="(o) => !o && close()">
    <DialogContent>
      <DialogHeader>
        <DialogTitle>서류 업로드</DialogTitle>
        <DialogDescription>{{ postingTitle }} · PDF, DOCX, PPTX, HTML (최대 10MB). 스캔본은 아직 읽지 못합니다.</DialogDescription>
      </DialogHeader>
      <form id="upload-form" class="space-y-4" @submit.prevent="submit">
        <div class="space-y-1.5">
          <Label for="upload-file">지원 서류</Label>
          <input
            id="upload-file"
            ref="fileInput"
            type="file"
            :accept="ACCEPT"
            class="flex h-9 w-full min-w-0 cursor-pointer rounded-md border border-input bg-card px-3 py-1.5 text-sm text-muted-foreground outline-none file:mr-3 file:cursor-pointer file:border-0 file:bg-transparent file:p-0 file:text-sm file:font-medium file:text-foreground focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30"
            @change="pick"
          />
        </div>
        <div class="grid gap-3 sm:grid-cols-2">
          <div class="space-y-1.5">
            <Label for="upload-name">이름</Label>
            <Input id="upload-name" v-model="name" autocomplete="off" />
          </div>
          <div class="space-y-1.5">
            <Label for="upload-aliases">영문·다른 표기 <span class="font-normal text-muted-foreground">(선택)</span></Label>
            <Input id="upload-aliases" v-model="aliases" autocomplete="off" placeholder="Gildong Hong" />
          </div>
          <div class="space-y-1.5">
            <Label for="upload-phone">전화 <span class="font-normal text-muted-foreground">(선택)</span></Label>
            <Input id="upload-phone" v-model="phone" autocomplete="off" inputmode="tel" />
          </div>
          <div class="space-y-1.5">
            <Label for="upload-email">이메일 <span class="font-normal text-muted-foreground">(선택)</span></Label>
            <Input id="upload-email" v-model="email" autocomplete="off" inputmode="email" />
          </div>
        </div>
        <PrivacyNote>
          이름과 연락처는 서류 안의 같은 값을 찾아 가리는 데만 씁니다. 암호화해 원본 영역에 두고, 화면과 AI에는 가명만 갑니다.
        </PrivacyNote>
      </form>
      <DialogFooter>
        <Button variant="outline" :disabled="upload.isPending" @click="close">취소</Button>
        <Button type="submit" form="upload-form" :disabled="!file || !name.trim() || upload.isPending">
          {{ upload.isPending ? '선별 중…' : '올리고 선별' }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
