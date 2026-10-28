<script setup lang="ts">
import { BookMarkedIcon, CheckIcon, ChevronDownIcon, CopyIcon, PencilLineIcon, QuoteIcon, SparklesIcon } from '@lucide/vue'
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

import DeidText from '@/components/common/DeidText.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Tooltip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

import type { Suggestion } from './follow-ups'
import { submitOnEnter } from './transcript-utils'

/** How long a card taken back as a duplicate stays open (dimmed) before it folds. */
const FOLD_MS = 1200

const props = defineProps<{
  s: Suggestion
  /** 1-based place among the cards still offered (null: taken back as a duplicate) */
  position: number | null
  used: boolean
  usedSeq: number | null
  usedEdited: boolean
  otherUsed: boolean
  disabled: boolean
  pending: boolean
}>()
const emit = defineEmits<{ use: [text: string, edited: boolean] }>()

const editing = ref(false)
const draft = ref(props.s.text)
const box = ref<InstanceType<typeof Textarea>>()

const startEdit = async () => {
  draft.value = props.s.text
  editing.value = true
  await nextTick()
  box.value?.focus()
}
const cancelEdit = () => {
  editing.value = false
  draft.value = props.s.text
}
const submitEdit = () => {
  const t = draft.value.trim()
  if (!t) return
  emit('use', t, t !== props.s.text)
  editing.value = false
}

// A duplicate found after the card was shown: dim it with the reason, then fold it to one line.
const folded = ref(props.s.duplicateOf !== null)
const opened = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined
watch(
  () => props.s.duplicateOf,
  (same) => {
    if (same === null || folded.value) return
    editing.value = false
    timer = setTimeout(() => (folded.value = true), FOLD_MS)
  },
)
onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <li
    v-if="s.duplicateOf !== null && folded && !opened"
    class="rounded-lg border border-dashed px-3 py-1.5 text-[11.5px] text-muted-foreground"
    aria-label="꼬리질문 후보 (이미 한 질문과 비슷해 접음)"
    :data-source="s.source"
    data-discarded="true"
  >
    <div class="flex items-center gap-1.5">
      <CopyIcon class="size-3 shrink-0" aria-hidden="true" />
      <Tooltip :content="`이미 한 질문과 뜻이 같아 접었습니다. 한 질문: ${s.duplicateOf}`">
        <span tabindex="0" class="shrink-0 font-medium outline-none">이미 한 질문과 비슷함</span>
      </Tooltip>
      <span class="min-w-0 truncate line-through decoration-muted-foreground/40">{{ s.text }}</span>
      <Button size="xs" variant="ghost" class="ml-auto h-5 shrink-0 px-1.5 text-[11px]" aria-label="접은 후보 보기" @click="opened = true">
        <ChevronDownIcon />
        보기
      </Button>
    </div>
  </li>
  <li
    v-else
    :class="
      cn(
        'rounded-lg border p-3 transition-[opacity,background-color,border-color] duration-300',
        used
          ? 'border-[color-mix(in_oklch,var(--success)_40%,transparent)] bg-[color-mix(in_oklch,var(--success)_6%,transparent)]'
          : s.source === 'bank'
            ? 'border-brand-border bg-[color-mix(in_oklch,var(--brand)_4%,transparent)]'
            : 'ai-dashed',
        (otherUsed || s.duplicateOf !== null) && 'opacity-55',
      )
    "
    :aria-label="
      s.duplicateOf !== null ? '꼬리질문 후보 (이미 한 질문과 비슷함)' : `꼬리질문 후보 ${position} (${s.source === 'bank' ? '질문 은행' : 'AI 생성'})`
    "
    :data-source="s.source"
    :data-discarded="s.duplicateOf !== null ? 'true' : undefined"
  >
    <div class="mb-1.5 flex items-center gap-1.5">
      <span v-if="position !== null" class="font-mono text-[10.5px] font-semibold text-muted-foreground">후보 {{ position }}</span>
      <Tooltip :content="s.source === 'bank' ? '채용 담당자가 검수·승인한 질문 은행에서 이 답변과 가까운 질문입니다.' : 'AI가 이 답변을 읽고 만든 질문입니다.'">
        <Badge :variant="s.source === 'bank' ? 'brand' : 'outline'" class="py-0 text-[10.5px]" data-testid="suggestion-source">
          <BookMarkedIcon v-if="s.source === 'bank'" aria-hidden="true" />
          <SparklesIcon v-else aria-hidden="true" />
          {{ s.source === 'bank' ? '질문 은행' : 'AI 생성' }}
        </Badge>
      </Tooltip>
      <Badge variant="outline" class="py-0 text-[10.5px]">{{ s.competency }}</Badge>
      <Badge v-if="used" variant="success" class="ml-auto py-0 text-[10.5px]">
        <CheckIcon />
        기록됨 · Q{{ usedSeq }}{{ usedEdited ? ' · 수정함' : '' }}
      </Badge>
      <Badge v-if="s.duplicateOf !== null" variant="outline" class="ml-auto py-0 text-[10.5px]" data-testid="duplicate-badge">
        <CopyIcon aria-hidden="true" />
        이미 한 질문과 비슷함
      </Badge>
      <span v-else-if="otherUsed" class="ml-auto text-[10.5px] text-muted-foreground">미채택</span>
    </div>

    <div v-if="editing" class="space-y-2">
      <Textarea ref="box" v-model="draft" aria-label="꼬리질문 수정" class="min-h-20 text-[13px]" @keydown="(e: KeyboardEvent) => submitOnEnter(e, submitEdit)" />
      <div class="flex justify-end gap-1.5">
        <Button size="xs" variant="ghost" @click="cancelEdit">취소</Button>
        <Button size="xs" :disabled="pending || !draft.trim()" @click="submitEdit">수정한 질문 사용</Button>
      </div>
    </div>
    <p v-else class="text-[13.5px] leading-relaxed font-medium">
      {{ s.text }}<span v-if="!s.done" class="ml-0.5 inline-block h-[1em] w-[2px] translate-y-[2px] animate-caret bg-brand" aria-hidden="true"></span>
    </p>

    <template v-if="s.done && !editing">
      <Tooltip v-if="s.grounding" :content="s.rationale ?? ''" side="left">
        <p tabindex="0" class="mt-2 flex gap-1.5 border-l-2 border-brand-border pl-2 text-[12px] leading-snug text-muted-foreground outline-none">
          <QuoteIcon class="mt-0.5 size-3 shrink-0" aria-hidden="true" />
          <span class="line-clamp-2"><DeidText :text="s.grounding" /></span>
        </p>
      </Tooltip>
      <p v-if="s.rationale" class="mt-1.5 text-[11.5px] text-muted-foreground">{{ s.rationale }}</p>
      <template v-if="s.duplicateOf !== null">
        <p class="mt-1.5 text-[11.5px] text-muted-foreground">이미 한 질문과 뜻이 같아 쓰지 않습니다. 한 질문: {{ s.duplicateOf }}</p>
        <Button v-if="opened" size="xs" variant="ghost" class="mt-1.5 h-5 px-1.5 text-[11px] text-muted-foreground" @click="opened = false">
          접기
        </Button>
      </template>
      <div v-else-if="!used && !otherUsed" class="mt-2.5 flex items-center gap-1.5" :aria-busy="s.checking">
        <Button size="xs" :disabled="disabled || pending || s.checking" @click="emit('use', s.text, false)">이 질문 사용</Button>
        <Button size="xs" variant="ghost" :disabled="disabled || pending || s.checking" @click="startEdit">
          <PencilLineIcon />
          수정 후 사용
        </Button>
        <!-- Only if the check takes a while (the model busy reindexing): a quick one never flickers. -->
        <span v-if="s.checking" class="animate-appear-late text-[11px] text-muted-foreground">이미 한 질문과 겹치는지 확인 중…</span>
      </div>
    </template>
  </li>
</template>
