<script setup lang="ts">
import { ref, watch } from 'vue'
import { toast } from 'vue-sonner'

import { useBankMutations } from '@/api/queries'
import type { ImportResult } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { toastError } from '@/lib/toast'

/**
 * CSV 가져오기: first a dry run that reports what would be added, skipped (already in the bank) or refused,
 * and which rows carry prohibited-question warnings; then the import. Everything comes in as drafts.
 */
defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()

const m = useBankMutations()
const file = ref<File | null>(null)
const preview = ref<ImportResult | null>(null)
const input = ref<HTMLInputElement | null>(null)

const EXAMPLE = '직군,역량,차수,질문,의도,꼬리질문 예시\n공정개발,데이터 기반 분석,1차,FDC 알람이 잦을 때 실제 이상과 오탐을 어떻게 가렸나요?,알람 품질,알람 기준은 누가 정했나요? | 오탐을 줄인 뒤 결과는?'

function reset() {
  file.value = null
  preview.value = null
  if (input.value) input.value.value = ''
}

watch(file, () => (preview.value = null))

function pick(e: Event) {
  file.value = (e.target as HTMLInputElement).files?.[0] ?? null
}

function run(dryRun: boolean) {
  if (!file.value) return
  m.importCsv.mutate(
    { file: file.value, dryRun },
    {
      onSuccess: (r) => {
        if (dryRun) {
          preview.value = r
          return
        }
        toast.success(`초안 ${r.created}개를 가져왔습니다`, { description: r.skipped ? `이미 있는 질문 ${r.skipped}개는 건너뛰었습니다.` : undefined })
        reset()
        emit('close')
      },
      onError: toastError('CSV를 가져오지 못했습니다'),
    },
  )
}
</script>

<template>
  <Dialog :open="open" @update:open="(o) => !o && (reset(), emit('close'))">
    <DialogContent class="sm:max-w-2xl">
      <DialogHeader>
        <DialogTitle>CSV 가져오기</DialogTitle>
        <DialogDescription>
          첫 줄은 열 이름(직군, 역량, 차수, 질문, 의도, 꼬리질문 예시)입니다. 꼬리질문 예시는 | 로 나눕니다. UTF-8과 엑셀 한글(CP949) 모두 읽습니다. 모두
          초안으로 들어오고, 승인은 하나씩 합니다.
        </DialogDescription>
      </DialogHeader>
      <div class="space-y-3">
        <pre class="overflow-x-auto rounded-md bg-subtle px-3 py-2 text-[11.5px] leading-relaxed">{{ EXAMPLE }}</pre>
        <div class="space-y-1.5">
          <Label for="bank-csv">CSV 파일 (2MB 이하)</Label>
          <input
            id="bank-csv"
            ref="input"
            type="file"
            accept=".csv,text/csv"
            class="flex h-9 w-full min-w-0 cursor-pointer rounded-md border border-input bg-card px-3 py-1.5 text-sm text-muted-foreground outline-none file:mr-3 file:cursor-pointer file:border-0 file:bg-transparent file:p-0 file:text-sm file:font-medium file:text-foreground"
            @change="pick"
          />
        </div>
        <div v-if="preview" class="space-y-2 rounded-lg border p-3 text-[13px]" data-testid="import-preview">
          <p>
            {{ preview.rows }}행 중 <strong>{{ preview.created }}개</strong>를 초안으로 추가합니다.
            <span v-if="preview.skipped" class="text-muted-foreground">이미 있는 질문 {{ preview.skipped }}개는 건너뜁니다.</span>
          </p>
          <ul v-if="preview.errors.length" class="space-y-0.5 text-xs text-danger">
            <li v-for="e in preview.errors" :key="`e${e.row}`">{{ e.row }}행: {{ e.message }}</li>
          </ul>
          <ul v-if="preview.warnings.length" class="space-y-0.5 text-xs text-warning">
            <li v-for="w in preview.warnings" :key="`w${w.row}`">{{ w.row }}행: {{ w.message }}</li>
          </ul>
        </div>
      </div>
      <DialogFooter>
        <Button variant="outline" :disabled="m.importCsv.isPending" @click="(reset(), emit('close'))">취소</Button>
        <Button v-if="!preview" :disabled="!file || m.importCsv.isPending" @click="run(true)">미리 보기</Button>
        <Button v-else :disabled="!preview.created || m.importCsv.isPending" @click="run(false)">초안 {{ preview.created }}개 가져오기</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
