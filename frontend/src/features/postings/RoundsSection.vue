<script setup lang="ts">
import { ArrowDownIcon, ArrowUpIcon, LockIcon, PlusIcon, RouteIcon } from '@lucide/vue'
import { computed, ref, watch } from 'vue'
import { toast } from 'vue-sonner'

import { useRoundMutations, useRounds, useRoundSets } from '@/api/queries'
import type { SessionMode } from '@/api/types'
import ErrorState from '@/components/common/ErrorState.vue'
import RoundBadge from '@/components/common/RoundBadge.vue'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Segmented, SegmentedItem } from '@/components/ui/segmented'
import { Skeleton } from '@/components/ui/skeleton'
import { toastError } from '@/lib/toast'
import { cn } from '@/lib/utils'

import CompetencySection from './CompetencySection.vue'
import RoundSettings from './RoundSettings.vue'

/**
 * 전형: the posting's rounds in order. Round 1 takes applications that passed screening, each next
 * round those a person passed in the round before. Per round: settings, competency versions and
 * preset questions. A round with interviews or decisions keeps its place.
 */
const props = defineProps<{ postingId: string }>()

const rounds = useRounds(() => props.postingId)
const m = useRoundMutations(() => props.postingId)
const selectedId = ref<string | null>(null)
const list = computed(() => rounds.data ?? [])
const selected = computed(() => list.value.find((r) => r.id === selectedId.value) ?? list.value[0])
watch(list, (l) => {
  if (!l.some((r) => r.id === selectedId.value)) selectedId.value = l[0]?.id ?? null
})

// The earlier round's approved dictionary, offered as a start for a new round.
const previous = computed(() => (selected.value ? list.value.find((r) => r.position === selected.value!.position - 1) : undefined))
const previousSets = useRoundSets(() => previous.value?.id ?? '')
const copyFrom = computed(() => {
  const approved = [...(previousSets.data ?? [])].reverse().find((s) => s.approved_at)
  return previous.value && approved ? { label: previous.value.label, competencies: approved.competencies } : null
})

function move(index: number, by: -1 | 1) {
  const ids = list.value.map((r) => r.id)
  const [id] = ids.splice(index, 1)
  ids.splice(index + by, 0, id!)
  m.reorder.mutate(ids, { onError: toastError('순서를 바꾸지 못했습니다') })
}
const movable = (i: number, by: -1 | 1) => {
  const a = list.value[i]
  const b = list.value[i + by]
  return Boolean(a && b && !a.locked && !b.locked)
}

const adding = ref(false)
const newName = ref('')
const newMode = ref<SessionMode>('onsite')
function add() {
  m.create.mutate(
    { name: newName.value.trim(), default_mode: newMode.value },
    {
      onSuccess: (r) => {
        adding.value = false
        newName.value = ''
        selectedId.value = r.id
        toast.success(`${r.label} ${r.name}을 추가했습니다`, { description: '역량 사전을 만들고 확정하면 이 차수 면접을 잡을 수 있습니다.' })
      },
      onError: toastError('차수를 추가하지 못했습니다'),
    },
  )
}
</script>

<template>
  <ErrorState v-if="rounds.isError" :error="rounds.error" @retry="rounds.refetch()" />
  <Skeleton v-else-if="!rounds.data" class="h-96" />
  <div v-else class="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
    <aside class="space-y-3">
      <Card class="overflow-hidden">
        <div class="flex items-center justify-between border-b px-4 py-3">
          <h2 class="flex items-center gap-1.5 text-[13px] font-semibold">
            <RouteIcon class="size-4 text-muted-foreground" aria-hidden="true" />
            전형 차수
          </h2>
          <span class="text-xs text-muted-foreground tabular">{{ list.length }}개</span>
        </div>
        <ol class="space-y-1 p-2" aria-label="차수 순서">
          <li v-for="(r, i) in list" :key="r.id">
            <div
              :class="
                cn(
                  'flex items-center gap-1 rounded-lg border px-2 py-2 transition-colors',
                  selected?.id === r.id ? 'border-ring bg-brand-soft' : 'border-transparent hover:bg-subtle',
                )
              "
            >
              <button type="button" class="min-w-0 flex-1 text-left" :aria-current="selected?.id === r.id" @click="selectedId = r.id">
                <span class="flex items-center gap-1.5">
                  <RoundBadge :round="r" />
                  <span class="truncate text-[13px] font-medium">{{ r.name }}</span>
                  <LockIcon v-if="r.locked" class="size-3 shrink-0 text-muted-foreground" aria-label="면접이 있어 순서 고정" />
                </span>
                <span class="mt-0.5 block truncate text-[11.5px] text-muted-foreground">
                  {{ r.approved_competency_set ? `역량 v${r.approved_competency_set.version} 확정` : '확정본 없음' }} · 질문 {{ r.preset_count }} · 면접
                  {{ r.sessions }}
                </span>
              </button>
              <div class="flex flex-col">
                <Button variant="ghost" size="icon-xs" class="size-5" :disabled="!movable(i, -1) || m.reorder.isPending" :aria-label="`${r.label} 위로`" @click="move(i, -1)">
                  <ArrowUpIcon class="size-3" />
                </Button>
                <Button variant="ghost" size="icon-xs" class="size-5" :disabled="!movable(i, 1) || m.reorder.isPending" :aria-label="`${r.label} 아래로`" @click="move(i, 1)">
                  <ArrowDownIcon class="size-3" />
                </Button>
              </div>
            </div>
          </li>
        </ol>
        <div class="border-t p-2">
          <Button variant="outline" size="sm" class="w-full" :disabled="list.length >= 6" @click="adding = true">
            <PlusIcon />
            차수 추가
          </Button>
        </div>
      </Card>
      <p class="px-1 text-[12px] leading-relaxed text-muted-foreground">
        1차는 서류 통과자, 다음 차수는 이전 차수 합격자만 대상입니다. 마지막 차수 합격자는 최종 합격 후보가 되고, 공식 결과는 채용 사이트에 기록합니다.
      </p>
    </aside>

    <div v-if="selected" class="min-w-0 space-y-4">
      <RoundSettings :key="selected.id" :round="selected" :posting-id="postingId" :only="list.length === 1" @deleted="selectedId = null" />
      <CompetencySection :round-id="selected.id" :round-label="selected.label" :copy-from="copyFrom" />
    </div>

    <Dialog :open="adding" @update:open="(o) => (adding = o)">
      <DialogContent>
        <DialogHeader>
          <DialogTitle>차수 추가</DialogTitle>
          <DialogDescription>{{ list.length + 1 }}차로 마지막 뒤에 붙습니다. 이전 차수 합격자가 대상입니다.</DialogDescription>
        </DialogHeader>
        <form class="space-y-4" @submit.prevent="add">
          <div class="space-y-1.5">
            <Label for="new-round-name">차수 이름</Label>
            <Input id="new-round-name" v-model="newName" placeholder="예: 임원 면접" />
          </div>
          <div class="space-y-1.5">
            <Label>기본 진행 방식</Label>
            <Segmented :model-value="newMode" aria-label="기본 진행 방식" @update:model-value="(v) => (newMode = v as SessionMode)">
              <SegmentedItem value="remote">비대면</SegmentedItem>
              <SegmentedItem value="onsite">대면</SegmentedItem>
            </Segmented>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" @click="adding = false">취소</Button>
            <Button type="submit" :disabled="!newName.trim() || m.create.isPending">{{ m.create.isPending ? '추가하는 중…' : '추가' }}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  </div>
</template>
