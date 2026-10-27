<script setup lang="ts">
import { BotIcon, FlagIcon, QuoteIcon, Trash2Icon } from '@lucide/vue'
import { computed, ref } from 'vue'

import { useCheckPointMutations, useMe } from '@/api/queries'
import type { Evaluation } from '@/api/types'
import DeidText from '@/components/common/DeidText.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { toastError } from '@/lib/toast'

/**
 * 확인이 필요한 점: what a later round should check. Interviewers write them here; AI adds its own
 * after scoring, each with the answer it rests on. They carry no scores, so the next round sees
 * them whatever its score setting.
 */
const props = defineProps<{ ev: Evaluation }>()

const me = useMe()
const m = useCheckPointMutations(props.ev.session.id)
const text = ref('')
const competency = ref('none')
const names = computed(() => props.ev.competency_set?.competencies.map((c) => c.name) ?? [])
const title = computed(() => (props.ev.decision.next_round ? `${props.ev.decision.next_round.label}에서 확인할 점` : '확인이 필요한 점'))

function add() {
  m.create.mutate(
    { text: text.value.trim(), competency: competency.value === 'none' ? null : competency.value },
    {
      onSuccess: () => {
        text.value = ''
        competency.value = 'none'
      },
      onError: toastError('확인할 점을 남기지 못했습니다'),
    },
  )
}
const asString = (v: unknown) => (typeof v === 'string' ? v : 'none')
</script>

<template>
  <Card data-testid="check-points">
    <CardHeader>
      <div>
        <CardTitle class="flex items-center gap-1.5">
          <FlagIcon class="size-4 text-muted-foreground" aria-hidden="true" />
          {{ title }}
        </CardTitle>
        <CardDescription>점수 없이 다음 차수 지원자 카드에 넘어갑니다. AI가 뽑은 것은 답변 근거와 함께 보입니다.</CardDescription>
      </div>
    </CardHeader>
    <CardContent class="space-y-3">
      <p v-if="ev.check_points.length === 0" class="text-[13px] text-muted-foreground">
        {{ ev.ai.status === 'running' ? 'AI 채점이 끝나면 AI가 뽑은 점이 여기에 더해집니다.' : '아직 남긴 점이 없습니다.' }}
      </p>
      <ul class="divide-y">
        <li v-for="p in ev.check_points" :key="p.id" class="py-2.5 first:pt-0 last:pb-0">
          <div class="flex items-start gap-2">
            <div class="min-w-0 flex-1 text-[13px] leading-snug">
              <div class="mb-1 flex flex-wrap items-center gap-1.5">
                <Badge v-if="p.source === 'ai'" variant="brand" class="py-0 text-[10.5px]"><BotIcon aria-hidden="true" />AI · 참고</Badge>
                <Badge v-else variant="outline" class="py-0 text-[10.5px]">{{ p.author_name }}</Badge>
                <span v-if="p.competency" class="text-[11.5px] text-muted-foreground">{{ p.competency }}</span>
              </div>
              <DeidText :text="p.text" />
              <p v-if="p.evidence" class="mt-1 flex gap-1 border-l-2 pl-2 text-[12px] text-muted-foreground">
                <QuoteIcon class="mt-0.5 size-3 shrink-0" aria-label="근거" />
                <DeidText :text="p.evidence" />
              </p>
            </div>
            <Button
              v-if="p.source === 'interviewer' && p.author_id === me.data?.id"
              variant="ghost"
              size="icon-xs"
              :aria-label="`확인할 점 삭제: ${p.text}`"
              :disabled="m.remove.isPending"
              @click="m.remove.mutate(p.id)"
            >
              <Trash2Icon />
            </Button>
          </div>
        </li>
      </ul>
      <form class="space-y-2 border-t pt-3" @submit.prevent="add">
        <Textarea v-model="text" rows="2" placeholder="다음 차수에서 확인할 점 (예: 리더 경험의 범위를 구체적으로)" aria-label="확인할 점" class="text-[13px]" />
        <div class="flex items-center gap-2">
          <Select :model-value="competency" @update:model-value="(v) => (competency = asString(v))">
            <SelectTrigger class="h-8 flex-1 text-[13px]" aria-label="역량 (선택)"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="none">역량 지정 안 함</SelectItem>
              <SelectItem v-for="n in names" :key="n" :value="n">{{ n }}</SelectItem>
            </SelectContent>
          </Select>
          <Button type="submit" size="sm" :disabled="!text.trim() || m.create.isPending">남기기</Button>
        </div>
      </form>
    </CardContent>
  </Card>
</template>
