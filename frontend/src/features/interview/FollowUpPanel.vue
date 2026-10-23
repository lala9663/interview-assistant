<script setup lang="ts">
import { RefreshCwIcon, SparklesIcon } from '@lucide/vue'
import { computed } from 'vue'

import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip } from '@/components/ui/tooltip'

import type { FollowUpState, Suggestion } from './follow-ups'
import SuggestionCard from './SuggestionCard.vue'

const props = defineProps<{
  state: FollowUpState
  listening: boolean
  hasAnswer: boolean
  disabled: boolean
  pendingSuggestionId: string | null
}>()
const emit = defineEmits<{ use: [s: Suggestion, text: string, edited: boolean]; retry: [] }>()

const streamingEmpty = computed(() => props.state.status === 'streaming' && props.state.suggestions.length === 0)
const placeholders = computed(() => (props.state.status === 'streaming' ? Math.max(0, 3 - props.state.suggestions.length) : 0))
</script>

<template>
  <section aria-label="꼬리질문 제안" class="flex flex-col">
    <div class="flex items-start justify-between gap-2">
      <div>
        <h3 class="flex items-center gap-1.5 text-[13px] font-semibold">
          <SparklesIcon class="size-4 text-brand" aria-hidden="true" />
          꼬리질문 제안
        </h3>
        <p class="mt-0.5 text-[11.5px] leading-snug text-muted-foreground">AI 제안입니다. 자동으로 묻지 않으며, 면접관이 고르거나 고친 질문만 기록됩니다.</p>
      </div>
      <Tooltip v-if="(state.status === 'done' || state.status === 'error') && hasAnswer" content="같은 답변으로 후보를 다시 받습니다">
        <Button size="icon-xs" variant="ghost" :disabled="disabled" aria-label="다시 제안" @click="emit('retry')">
          <RefreshCwIcon />
        </Button>
      </Tooltip>
    </div>

    <div class="mt-3">
      <div v-if="state.status === 'error'" class="rounded-lg border border-dashed p-3 text-[12.5px]">
        <p class="font-medium">제안을 받지 못했습니다</p>
        <p class="mt-0.5 text-muted-foreground">{{ state.error }} 직접 질문을 입력해 면접을 계속할 수 있습니다.</p>
        <Button size="xs" variant="outline" class="mt-2" :disabled="disabled || !hasAnswer" @click="emit('retry')">다시 시도</Button>
      </div>

      <div v-if="state.status === 'idle'" class="rounded-lg border border-dashed px-3 py-5 text-center text-[12.5px] text-muted-foreground">
        {{ listening ? '지원자 답변을 듣는 중입니다. 답변이 끝나면 후보 2~3개를 제안합니다.' : '답변이 끝나면 그 답변을 근거로 꼬리질문 후보가 나타납니다.' }}
      </div>

      <ul v-if="streamingEmpty" class="space-y-2" aria-busy="true">
        <li v-for="i in 3" :key="i" class="rounded-lg border border-dashed p-3">
          <Skeleton class="h-3 w-20" />
          <Skeleton class="mt-2.5 h-3.5 w-full" />
          <Skeleton class="mt-1.5 h-3.5 w-2/3" />
        </li>
        <li class="text-center text-[11.5px] text-muted-foreground">직전 답변에서 근거를 찾는 중…</li>
      </ul>

      <TransitionGroup
        v-if="state.suggestions.length > 0"
        tag="ul"
        class="space-y-2"
        enter-active-class="transition-[opacity,transform] duration-250 ease-[cubic-bezier(0.22,1,0.36,1)]"
        enter-from-class="opacity-0 translate-y-2"
      >
        <SuggestionCard
          v-for="s in state.suggestions"
          :key="s.id"
          :s="s"
          :used="state.used?.suggestionId === s.id"
          :used-seq="state.used?.suggestionId === s.id ? state.used.seq : null"
          :used-edited="state.used?.suggestionId === s.id ? state.used.edited : false"
          :other-used="Boolean(state.used) && state.used?.suggestionId !== s.id"
          :disabled="disabled"
          :pending="pendingSuggestionId !== null"
          @use="(text, edited) => emit('use', s, text, edited)"
        />
        <li v-for="i in placeholders" :key="`sk-${i}`" class="rounded-lg border border-dashed p-3 opacity-60">
          <Skeleton class="h-3 w-20" />
          <Skeleton class="mt-2.5 h-3.5 w-4/5" />
        </li>
      </TransitionGroup>
      <p v-if="state.used && listening" class="mt-2 text-center text-[11.5px] text-muted-foreground">새 답변이 끝나면 다음 후보를 제안합니다.</p>
      <p v-if="state.model && state.status === 'done'" class="mt-2 text-right font-mono text-[10.5px] text-muted-foreground/70">{{ state.model }}</p>
    </div>
  </section>
</template>
