<script setup lang="ts">
import { ArrowDownIcon } from '@lucide/vue'
import { computed, ref, watch } from 'vue'

import type { QAItem, TranscriptSegment } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { QUESTION_SOURCE_LABEL } from '@/lib/labels'

import { buildBlocks, buildTurns, type Block } from './transcript-utils'
import TranscriptTurn from './TranscriptTurn.vue'

/** The Q&A of a recorded interview, the one place it shows in the room: what was heard, under each question. */
const props = defineProps<{
  segments: TranscriptSegment[]
  partial: TranscriptSegment | null
  qaItems: QAItem[]
  listening: boolean
  /** questions recorded from an edited suggestion (this page only) */
  editedIds: ReadonlySet<string>
  startedAt: string | null
}>()

const viewport = ref<HTMLDivElement>()
const pinned = ref(true)
const turns = computed(() => buildTurns(props.segments, props.partial))
const blocks = computed(() => buildBlocks(turns.value, props.qaItems))
// Typed answers (transcription down) show where the transcript has none for that question.
const heard = computed(() => new Set(turns.value.filter((t) => t.speaker === 'candidate').map((t) => t.qaId)))

const head = (b: Block) => (b.qa && !b.continued ? b.qa : null)
const unheardQuestion = (b: Block) => head(b) !== null && !b.turns.some((t) => t.speaker === 'interviewer')
const typedAnswer = (b: Block) => {
  const qa = head(b)
  return qa?.answer_deidentified && !heard.value.has(qa.id) ? qa.answer_deidentified : null
}
const sinceStart = (at: string | null) => (at && props.startedAt ? Math.max(0, new Date(at).getTime() - new Date(props.startedAt).getTime()) : null)

const toBottom = () => {
  const el = viewport.value
  if (el) el.scrollTop = el.scrollHeight
}
// Follow new text while the reader is at the bottom; leave them alone once they scroll up.
watch(
  [() => props.segments.length, () => props.partial?.text.length ?? 0, () => props.qaItems.length, pinned],
  () => {
    if (pinned.value) toBottom()
  },
  { flush: 'post', immediate: true },
)

const onScroll = () => {
  const el = viewport.value
  if (el) pinned.value = el.scrollHeight - el.scrollTop - el.clientHeight < 48
}
const jumpToLatest = () => {
  toBottom()
  pinned.value = true
}
</script>

<template>
  <div class="relative min-h-0 flex-1">
    <div ref="viewport" class="h-full overflow-y-auto px-5 py-4 scrollbar-thin" aria-live="polite" aria-label="실시간 트랜스크립트" @scroll="onScroll">
      <div v-if="blocks.length === 0" class="flex h-full flex-col items-center justify-center gap-2 text-center text-[13px] text-muted-foreground">
        <p>아직 전사된 내용이 없습니다.</p>
        <p>사전 질문이나 아래 입력창으로 첫 질문을 기록하세요.</p>
      </div>
      <ol class="space-y-4" aria-label="Q&A 기록">
        <li v-for="b in blocks" :key="b.key" class="space-y-1" :data-qa-seq="head(b)?.seq">
          <div v-if="head(b)" class="mb-1.5 flex items-center gap-2">
            <span class="font-mono text-[11px] font-semibold text-muted-foreground">Q{{ head(b)!.seq }}</span>
            <Badge :variant="head(b)!.question_source === 'ai_suggested' ? 'brand' : 'outline'" class="py-0 text-[10.5px]">
              {{ QUESTION_SOURCE_LABEL[head(b)!.question_source] }}
            </Badge>
            <Badge v-if="editedIds.has(head(b)!.id)" variant="outline" class="py-0 text-[10.5px]">수정함</Badge>
            <span class="h-px flex-1 bg-border" aria-hidden="true"></span>
          </div>
          <TranscriptTurn
            v-if="unheardQuestion(b)"
            speaker="interviewer"
            :parts="[{ id: `q-${head(b)!.id}`, text: head(b)!.question, final: true }]"
            :start-ms="sinceStart(head(b)!.asked_at)"
          />
          <TranscriptTurn v-for="t in b.turns" :key="t.key" :speaker="t.speaker" :parts="t.parts" :start-ms="t.startMs" />
          <TranscriptTurn
            v-if="typedAnswer(b)"
            speaker="candidate"
            :parts="[{ id: `a-${head(b)!.id}`, text: typedAnswer(b)!, final: true }]"
            :start-ms="sinceStart(head(b)!.answered_at)"
            note="수기 기록"
          />
        </li>
      </ol>
      <div v-if="listening && !partial" class="mt-2 flex items-center gap-2 px-3 text-xs text-muted-foreground">
        <span class="flex gap-0.5" aria-hidden="true">
          <span v-for="i in 3" :key="i" class="listening-dot size-1 rounded-full bg-muted-foreground" :style="{ animationDelay: `${(i - 1) * 0.18}s` }"></span>
        </span>
        지원자 답변을 듣는 중
      </div>
    </div>
    <Button v-if="!pinned" size="xs" variant="secondary" class="absolute bottom-3 left-1/2 -translate-x-1/2 shadow-md" @click="jumpToLatest">
      <ArrowDownIcon />
      최신 전사로
    </Button>
  </div>
</template>

<style scoped>
.listening-dot {
  animation: listening 1.2s ease-in-out infinite;
}
@keyframes listening {
  0%,
  100% {
    opacity: 0.25;
  }
  50% {
    opacity: 1;
  }
}
</style>
