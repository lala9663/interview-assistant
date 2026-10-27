<script setup lang="ts">
import { EyeIcon, LockIcon, Trash2Icon } from '@lucide/vue'
import { computed, ref, watch } from 'vue'
import { toast } from 'vue-sonner'

import { useRoundMutations } from '@/api/queries'
import type { RoundSummary, SessionMode } from '@/api/types'
import RoundBadge from '@/components/common/RoundBadge.vue'
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
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Segmented, SegmentedItem } from '@/components/ui/segmented'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { SESSION_MODE_LABEL } from '@/lib/labels'
import { toastError } from '@/lib/toast'

/** One round's settings: name, default mode, recommended panel size, whether earlier scores show. */
const props = defineProps<{ round: RoundSummary; postingId: string; only: boolean }>()
const emit = defineEmits<{ deleted: [] }>()

const m = useRoundMutations(() => props.postingId)
const name = ref(props.round.name)
const mode = ref<SessionMode>(props.round.default_mode)
const panel = ref(props.round.recommended_interviewers)
const showScores = ref(props.round.show_previous_scores)
watch(
  () => props.round,
  (r) => {
    name.value = r.name
    mode.value = r.default_mode
    panel.value = r.recommended_interviewers
    showScores.value = r.show_previous_scores
  },
)
const dirty = computed(
  () =>
    name.value.trim() !== props.round.name ||
    mode.value !== props.round.default_mode ||
    panel.value !== props.round.recommended_interviewers ||
    showScores.value !== props.round.show_previous_scores,
)

function save() {
  m.update.mutate(
    {
      id: props.round.id,
      body: { name: name.value.trim(), default_mode: mode.value, recommended_interviewers: panel.value, show_previous_scores: showScores.value },
    },
    { onSuccess: (r) => toast.success(`${r.label} 설정을 저장했습니다`, { description: '변경 내역은 감사 로그에 남습니다.' }), onError: toastError('설정을 저장하지 못했습니다') },
  )
}
const remove = () =>
  m.remove.mutate(props.round.id, {
    onSuccess: () => {
      toast.success(`${props.round.label} ${props.round.name}을 지웠습니다`)
      emit('deleted')
    },
    onError: toastError('차수를 지우지 못했습니다'),
  })
</script>

<template>
  <Card>
    <CardContent class="space-y-4 pt-5">
      <div class="flex flex-wrap items-center gap-2">
        <RoundBadge :round="round" full strong />
        <span v-if="round.is_last" class="text-xs text-muted-foreground">마지막 차수 · 합격하면 최종 합격 후보</span>
        <span v-if="round.locked" class="ml-auto inline-flex items-center gap-1 text-xs text-muted-foreground">
          <LockIcon class="size-3.5" aria-hidden="true" />
          면접 {{ round.sessions }}건 · 순서 고정
        </span>
      </div>
      <form class="grid gap-4 sm:grid-cols-2" @submit.prevent="save">
        <div class="space-y-1.5">
          <Label :for="`round-name-${round.id}`">차수 이름</Label>
          <Input :id="`round-name-${round.id}`" v-model="name" placeholder="예: 직무 면접" class="h-9" />
          <p class="text-[11.5px] text-muted-foreground">화면에는 "{{ round.label }} · {{ name || '이름' }}"으로 보입니다.</p>
        </div>
        <div class="space-y-1.5">
          <Label>기본 진행 방식</Label>
          <Segmented :model-value="mode" aria-label="기본 진행 방식" @update:model-value="(v) => (mode = v as SessionMode)">
            <SegmentedItem value="remote">{{ SESSION_MODE_LABEL.remote }}</SegmentedItem>
            <SegmentedItem value="onsite">{{ SESSION_MODE_LABEL.onsite }}</SegmentedItem>
          </Segmented>
        </div>
        <div class="space-y-1.5">
          <Label>권장 면접관 수</Label>
          <Select :model-value="String(panel)" @update:model-value="(v) => (panel = Number(v))">
            <SelectTrigger class="h-9 w-32" aria-label="권장 면접관 수"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem v-for="n in 6" :key="n" :value="String(n)">{{ n }}명</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div class="space-y-1.5">
          <Label :for="`round-scores-${round.id}`" class="flex items-center gap-1.5">
            <EyeIcon class="size-3.5 text-muted-foreground" aria-hidden="true" />
            이전 차수 점수 공개
          </Label>
          <div class="flex items-center gap-2">
            <Switch :id="`round-scores-${round.id}`" v-model="showScores" :disabled="round.position === 1" />
            <span class="text-[12.5px] text-muted-foreground">
              {{ round.position === 1 ? '1차는 이전 차수가 없습니다' : showScores ? '이 차수 면접관에게 이전 점수를 보여 줍니다' : '숨김 (기본): 확인할 점과 메모만 보여 줍니다' }}
            </span>
          </div>
        </div>
        <div class="flex items-center gap-2 sm:col-span-2">
          <Button type="submit" size="sm" :disabled="!dirty || !name.trim() || m.update.isPending">{{ m.update.isPending ? '저장 중…' : '설정 저장' }}</Button>
          <AlertDialog>
            <AlertDialogTrigger as-child>
              <Button type="button" variant="ghost" size="sm" class="ml-auto text-muted-foreground" :disabled="round.locked || only || m.remove.isPending">
                <Trash2Icon />
                차수 삭제
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>{{ round.label }} {{ round.name }}을 지울까요?</AlertDialogTitle>
                <AlertDialogDescription>역량 사전과 사전 질문이 함께 지워지고, 뒤 차수가 앞으로 당겨집니다.</AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>취소</AlertDialogCancel>
                <AlertDialogAction class="bg-destructive text-destructive-foreground hover:bg-destructive/90" @click="remove">삭제</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </form>
    </CardContent>
  </Card>
</template>
