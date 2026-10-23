<script setup lang="ts">
import { ArrowDownIcon } from '@lucide/vue'
import { computed, ref, watch } from 'vue'

import type { QAItem, TranscriptSegment } from '@/api/types'
import DeidText from '@/components/common/DeidText.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { QUESTION_SOURCE_LABEL } from '@/lib/labels'
import { formatElapsed } from '@/lib/time'
import { cn } from '@/lib/utils'

import { buildTurns } from './transcript-utils'

const props = defineProps<{ segments: TranscriptSegment[]; partial: TranscriptSegment | null; qaItems: QAItem[]; listening: boolean }>()

const viewport = ref<HTMLDivElement>()
const pinned = ref(true)
const turns = computed(() => buildTurns(props.segments, props.partial))
const qaById = computed(() => new Map(props.qaItems.map((q) => [q.id, q])))

const toBottom = () => {
  const el = viewport.value
  if (el) el.scrollTop = el.scrollHeight
}
// Follow new text while the reader is at the bottom; leave them alone once they scroll up.
watch(
  [() => props.segments.length, () => props.partial?.text.length ?? 0, pinned],
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
      <div v-if="turns.length === 0" class="flex h-full flex-col items-center justify-center gap-2 text-center text-[13px] text-muted-foreground">
        <p>아직 전사된 내용이 없습니다.</p>
        <p>왼쪽 사전 질문이나 아래 입력창으로 첫 질문을 기록하세요.</p>
      </div>
      <ol class="space-y-1">
        <li v-for="t in turns" :key="t.key">
          <div
            v-if="t.speaker === 'interviewer' && t.qaId && qaById.get(t.qaId)"
            class="mt-4 mb-1.5 flex items-center gap-2 first:mt-0"
          >
            <span class="font-mono text-[11px] font-semibold text-muted-foreground">Q{{ qaById.get(t.qaId)!.seq }}</span>
            <Badge :variant="qaById.get(t.qaId)!.question_source === 'ai_suggested' ? 'brand' : 'outline'" class="py-0 text-[10.5px]">
              {{ QUESTION_SOURCE_LABEL[qaById.get(t.qaId)!.question_source] }}
            </Badge>
            <span class="h-px flex-1 bg-border" aria-hidden="true"></span>
          </div>
          <div :class="cn('flex gap-3 rounded-lg px-3 py-2.5', t.speaker === 'interviewer' && 'bg-subtle')">
            <div class="w-[68px] shrink-0 pt-0.5">
              <div :class="cn('text-[12px] font-semibold', t.speaker === 'interviewer' ? 'text-brand' : 'text-foreground')">
                {{ t.speaker === 'interviewer' ? '면접관' : '지원자' }}
              </div>
              <div class="text-[11px] text-muted-foreground tabular">{{ formatElapsed(t.startMs) }}</div>
            </div>
            <p :class="cn('min-w-0 flex-1 text-[14px] leading-[1.75]', t.speaker === 'interviewer' && 'font-medium')"
              ><span v-for="(p, i) in t.parts" :key="p.id" :class="cn('transition-colors duration-300', !p.final && 'text-muted-foreground/70')"
                >{{ i > 0 ? ' ' : '' }}<DeidText :text="p.text" /><span
                  v-if="!p.final"
                  class="ml-0.5 inline-block h-[1.05em] w-[2px] translate-y-[3px] animate-caret bg-foreground/50"
                  aria-hidden="true"
                ></span></span
            ></p>
          </div>
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
