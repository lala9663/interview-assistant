<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { toast } from 'vue-sonner'

import { useCreateSession, useSchedulable } from '@/api/queries'
import type { Interviewer, ScheduleSuggestion, SessionMode } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Segmented, SegmentedItem } from '@/components/ui/segmented'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { formatDate, formatTime } from '@/lib/time'
import { toastError } from '@/lib/toast'

/** Turn a suggested slot into a scheduled session (확정 일정). */
const props = defineProps<{ suggestion: ScheduleSuggestion | null; interviewers: Interviewer[] }>()
const emit = defineEmits<{ close: [] }>()

const router = useRouter()
const apps = useSchedulable(() => props.suggestion !== null)
const create = useCreateSession()
const appId = ref('')
const mode = ref<SessionMode>('remote')
const lead = ref('')
const panel = computed(() => (props.suggestion ? props.interviewers.filter((i) => props.suggestion!.interviewer_ids.includes(i.id)) : []))
const leadId = computed(() => lead.value || panel.value[0]?.id || '')
const description = computed(() =>
  props.suggestion
    ? `${formatDate(props.suggestion.start_at)} ${formatTime(props.suggestion.start_at)}–${formatTime(props.suggestion.end_at)} · 면접관 ${panel.value.map((p) => p.name).join(', ')}`
    : '',
)

function submit() {
  const slot = props.suggestion
  if (!slot || !appId.value) return
  create.mutate(
    {
      application_id: appId.value,
      mode: mode.value,
      scheduled_at: slot.start_at,
      interviewers: panel.value.map((i) => ({ interviewer_id: i.id, role: i.id === leadId.value ? 'lead' : 'panel' })),
    },
    {
      onSuccess: (s) => {
        toast.success(`${s.candidate.pseudonym} 면접을 잡았습니다`, {
          description: `${formatDate(slot.start_at)} ${formatTime(slot.start_at)}`,
          action: { label: '보기', onClick: () => void router.push('/sessions') },
        })
        emit('close')
      },
      onError: toastError('일정을 잡지 못했습니다'),
    },
  )
}

const asString = (v: unknown) => (typeof v === 'string' ? v : '')
</script>

<template>
  <Dialog :open="suggestion !== null" @update:open="(o) => !o && emit('close')">
    <DialogContent>
      <DialogHeader>
        <DialogTitle>면접 잡기</DialogTitle>
        <DialogDescription>{{ description }}</DialogDescription>
      </DialogHeader>
      <div class="space-y-4">
        <div class="space-y-1.5">
          <Label>지원자</Label>
          <Select :model-value="appId" @update:model-value="(v) => (appId = asString(v))">
            <SelectTrigger aria-label="지원자 선택">
              <SelectValue :placeholder="!apps.data ? '불러오는 중…' : '서류 통과 지원자 선택'" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem v-for="a in apps.data ?? []" :key="a.application_id" :value="a.application_id">
                {{ a.candidate.pseudonym }} · {{ a.posting.title }} · 적합도 {{ a.fit_score }}
              </SelectItem>
            </SelectContent>
          </Select>
          <p v-if="apps.data?.length === 0" class="text-xs text-muted-foreground">면접을 잡을 수 있는 서류 통과 지원자가 없습니다.</p>
        </div>
        <div class="flex flex-wrap gap-6">
          <div class="space-y-1.5">
            <Label>방식</Label>
            <Segmented :model-value="mode" aria-label="면접 방식" @update:model-value="(v) => (mode = v as SessionMode)">
              <SegmentedItem value="remote">비대면</SegmentedItem>
              <SegmentedItem value="onsite">대면</SegmentedItem>
            </Segmented>
          </div>
          <div class="min-w-48 flex-1 space-y-1.5">
            <Label>주관 면접관</Label>
            <Select :model-value="leadId" @update:model-value="(v) => (lead = asString(v))">
              <SelectTrigger aria-label="주관 면접관">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-for="i in panel" :key="i.id" :value="i.id">{{ i.name }}</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>
      <DialogFooter>
        <Button variant="outline" @click="emit('close')">취소</Button>
        <Button :disabled="!appId || create.isPending" @click="submit">{{ create.isPending ? '잡는 중…' : '일정 확정' }}</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
