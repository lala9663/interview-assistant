<script setup lang="ts">
import { ScanTextIcon } from '@lucide/vue'

import type { ReadingFile, ReadingInfo } from '@/api/types'

/** How the application's files were read: the 서류 읽기 settings in force when it was processed. */
defineProps<{ reading: ReadingInfo }>()

const MODE: Record<string, string> = { auto: '자동', always_ocr: '항상 OCR', text_only: '텍스트만' }

function facts(f: ReadingFile): string[] {
  const out = [`${f.format.toUpperCase()} ${f.pages}쪽`]
  if (f.converted_from) out.push(`.${f.converted_from}에서 변환`)
  if (f.ocr_pages.length) {
    const confidence = f.ocr_confidence !== null ? `, 최저 신뢰도 ${Math.round(f.ocr_confidence * 100)}%` : ''
    out.push(`OCR ${f.ocr_pages.join('·')}쪽${confidence}`)
  }
  if (f.garbled_pages.length) out.push(`깨진 텍스트 층 ${f.garbled_pages.join('·')}쪽 다시 읽음`)
  if (f.pictures_read) out.push(`그림 ${f.pictures_read}개 OCR`)
  if (f.photos_dropped) out.push(`증명사진 ${f.photos_dropped}개 버림`)
  return out
}
</script>

<template>
  <div class="space-y-1 rounded-lg border bg-subtle px-3 py-2 text-xs" data-testid="reading-summary">
    <p class="flex items-center gap-1.5 font-medium">
      <ScanTextIcon class="size-3.5 text-muted-foreground" aria-hidden="true" />
      서류 읽기 · {{ MODE[reading.mode] ?? reading.mode }}<span v-if="reading.revision !== null" class="font-normal text-muted-foreground">(설정 rev {{ reading.revision }})</span>
    </p>
    <p v-for="(f, i) in reading.files" :key="i" class="text-muted-foreground">{{ facts(f).join(' · ') }}</p>
    <p class="font-mono text-[11px] text-muted-foreground">{{ reading.tools.join(' · ') }}</p>
  </div>
</template>
