<script setup lang="ts">
import { HistoryIcon, TriangleAlertIcon, Undo2Icon } from '@lucide/vue'
import { computed, ref } from 'vue'
import { toast } from 'vue-sonner'

import { useRevertModel } from '@/api/queries'
import type { ModelChange, ModelImpl } from '@/api/types'
import { leavesCompany } from '@/api/types'
import EmptyState from '@/components/common/EmptyState.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { formatDateTime } from '@/lib/time'
import { toastError } from '@/lib/toast'

import { CHANGE_KIND_LABEL, kindOf, withObjectParticle } from './labels'

/** 변경 이력 and 되돌리기: a rollback puts the role back to what it was before that change (a new entry). */
const props = defineProps<{ changes: ModelChange[]; catalog: ModelImpl[] }>()

const revert = useRevertModel()
const target = ref<ModelChange | null>(null)
const reason = ref('')
const confirmExternal = ref(false)

const targetExternal = computed(() => {
  const t = target.value
  if (!t?.previous) return false
  return leavesCompany(props.catalog.find((i) => i.kind === kindOf(t.role) && i.impl === t.previous!.impl)?.data_location)
})

function open(change: ModelChange) {
  target.value = change
  reason.value = ''
  confirmExternal.value = false
}

function submit() {
  const t = target.value
  if (!t || !reason.value.trim()) return
  revert.mutate(
    { changeId: t.id, body: { reason: reason.value.trim(), confirm_external: confirmExternal.value } },
    {
      onSuccess: (s) => {
        toast.success(`${withObjectParticle(s.label)} 되돌렸습니다`, { description: `${s.impl_label} · ${s.model}` })
        target.value = null
      },
      onError: toastError('되돌리지 못했습니다'),
    },
  )
}

const kindVariant = (k: ModelChange['kind']) => (k === 'apply' ? 'brand' : k === 'rollback' ? 'warning' : 'outline')
</script>

<template>
  <EmptyState v-if="changes.length === 0" :icon="HistoryIcon" title="변경 이력이 없습니다" compact />
  <div v-else class="overflow-x-auto">
    <table class="w-full min-w-[880px] text-[13px]">
      <thead>
        <tr class="border-b bg-subtle text-left text-xs text-muted-foreground">
          <th class="py-2.5 pr-3 pl-4 font-medium">시각</th>
          <th class="px-3 py-2.5 font-medium">역할</th>
          <th class="px-3 py-2.5 font-medium">구분</th>
          <th class="px-3 py-2.5 font-medium">이전 → 새 설정</th>
          <th class="px-3 py-2.5 font-medium">변경한 사람</th>
          <th class="px-3 py-2.5 font-medium">사유</th>
          <th class="py-2.5 pr-4 pl-3"></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="c in changes" :key="c.id" class="border-b align-top last:border-0" data-testid="history-row">
          <td class="py-2.5 pr-3 pl-4 whitespace-nowrap tabular">
            {{ formatDateTime(c.occurred_at) }}
            <span class="block text-[11px] text-muted-foreground">rev {{ c.revision }}</span>
          </td>
          <td class="px-3 py-2.5 whitespace-nowrap">{{ c.role_label }}</td>
          <td class="px-3 py-2.5"><Badge :variant="kindVariant(c.kind)">{{ CHANGE_KIND_LABEL[c.kind] }}</Badge></td>
          <td class="px-3 py-2.5">
            <span v-if="c.previous_label" class="text-muted-foreground">{{ c.previous_label }} → </span>
            <span class="font-medium">{{ c.new_label }}</span>
          </td>
          <td class="px-3 py-2.5 whitespace-nowrap">{{ c.actor?.name ?? '시스템' }}</td>
          <td class="max-w-72 px-3 py-2.5 text-muted-foreground">{{ c.reason ?? '–' }}</td>
          <td class="py-2.5 pr-4 pl-3 text-right">
            <Button v-if="c.previous" size="xs" variant="outline" :aria-label="`rev ${c.revision} 되돌리기`" @click="open(c)">
              <Undo2Icon />
              되돌리기
            </Button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>

  <Dialog :open="target !== null" @update:open="(o) => !o && !revert.isPending && (target = null)">
    <DialogContent>
      <DialogHeader>
        <DialogTitle>되돌리기</DialogTitle>
        <DialogDescription>{{ withObjectParticle(target?.role_label ?? '') }} rev {{ target?.revision }} 이전 설정({{ target?.previous_label }})으로 되돌립니다.</DialogDescription>
      </DialogHeader>
      <div class="space-y-3">
        <div v-if="targetExternal" class="flex items-start gap-2 rounded-lg border border-[color-mix(in_oklch,var(--warning)_40%,transparent)] bg-[color-mix(in_oklch,var(--warning)_8%,transparent)] p-3 text-[13px]">
          <TriangleAlertIcon class="mt-0.5 size-4 shrink-0 text-warning" aria-hidden="true" />
          회사 밖 API로 데이터를 보내는 설정으로 돌아갑니다.
        </div>
        <label v-if="targetExternal" class="flex items-center gap-2 text-[13px]">
          <Checkbox v-model="confirmExternal" />
          외부 전송을 확인했습니다.
        </label>
        <div class="space-y-1.5">
          <Label for="revert-reason">사유</Label>
          <Textarea id="revert-reason" v-model="reason" rows="2" :maxlength="500" placeholder="예: 새 모델의 전사 품질이 낮아 원래대로" />
        </div>
        <p class="text-xs text-muted-foreground">요구 조건(패키지, 모델 파일)이 지금도 충족되어야 되돌릴 수 있습니다. 진행 중인 면접은 영향받지 않습니다.</p>
      </div>
      <DialogFooter>
        <Button variant="outline" :disabled="revert.isPending" @click="target = null">취소</Button>
        <Button :disabled="!reason.trim() || (targetExternal && !confirmExternal) || revert.isPending" data-testid="confirm-revert" @click="submit">
          {{ revert.isPending ? '되돌리는 중…' : '되돌리기' }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
