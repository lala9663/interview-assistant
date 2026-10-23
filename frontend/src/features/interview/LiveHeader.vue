<script setup lang="ts">
import { ArrowLeftIcon, CircleStopIcon, PanelLeftIcon } from '@lucide/vue'
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

import type { SessionDetail, StreamStatus } from '@/api/types'
import ModeBadge from '@/components/common/ModeBadge.vue'
import PanelAvatars from '@/components/common/PanelAvatars.vue'
import Pseudonym from '@/components/common/Pseudonym.vue'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'

import RecordingStatus from './RecordingStatus.vue'
import type { Connection } from './use-transcript'

const props = defineProps<{ detail: SessionDetail; status: StreamStatus | null; connection: Connection; ending: boolean }>()
const emit = defineEmits<{ end: []; openCandidate: [] }>()
const answered = computed(() => props.detail.qa_items.filter((q) => q.answer_deidentified).length)
</script>

<template>
  <div class="flex h-14 shrink-0 items-center gap-3 border-b bg-card/50 px-4">
    <Button as-child variant="ghost" size="icon-sm" aria-label="면접 목록으로">
      <RouterLink to="/sessions"><ArrowLeftIcon /></RouterLink>
    </Button>
    <Button variant="ghost" size="icon-sm" class="xl:hidden" aria-label="지원자 정보와 사전 질문 열기" @click="emit('openCandidate')">
      <PanelLeftIcon />
    </Button>
    <div class="flex min-w-0 items-center gap-2.5">
      <Pseudonym :value="detail.card.candidate.pseudonym" class="whitespace-nowrap" />
      <span class="hidden truncate text-[13px] text-muted-foreground lg:block">{{ detail.posting.title }}</span>
      <ModeBadge :mode="detail.session.mode" />
      <PanelAvatars :panel="detail.interviewers" class="hidden lg:flex" />
    </div>
    <div class="ml-auto flex items-center gap-4">
      <RecordingStatus :detail="detail" :status="status" :connection="connection" />
      <AlertDialog>
        <AlertDialogTrigger as-child>
          <Button variant="destructive" size="sm" :disabled="ending">
            <CircleStopIcon />
            면접 종료
          </Button>
        </AlertDialogTrigger>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>면접을 종료할까요?</AlertDialogTitle>
            <AlertDialogDescription>
              질문 {{ detail.qa_items.length }}개(답변 {{ answered }}개)가 기록되어 있습니다. 종료하면 녹음과 전사가 멈추고 AI 평점이 시작됩니다. AI 평점은
              참고용이며, 면접관 점수는 평가 화면에서 따로 입력합니다.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>계속 진행</AlertDialogCancel>
            <AlertDialogAction class="bg-destructive text-destructive-foreground hover:bg-destructive/90" @click="emit('end')">
              종료하고 평가로
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  </div>
</template>
