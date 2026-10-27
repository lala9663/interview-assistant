<script setup lang="ts">
import { CheckIcon, ListChecksIcon, LockIcon, PencilIcon, PlusIcon, SparklesIcon, Trash2Icon, XIcon } from '@lucide/vue'
import { computed, ref } from 'vue'
import { toast } from 'vue-sonner'

import { usePresetMutations, usePresetQuestions } from '@/api/queries'
import type { CompetencySet, PresetQuestion } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { toastError } from '@/lib/toast'

/**
 * 사전 질문 of one competency version (FR-06). Drafts can be edited and AI can add questions (two
 * per competency, none an earlier round already asks); an approved version is read-only, like
 * its competencies. A new draft starts with the approved version's questions.
 */
const props = defineProps<{ set: CompetencySet; roundLabel: string }>()

const q = usePresetQuestions(() => props.set.id)
const m = usePresetMutations(() => props.set.id)
const locked = computed(() => props.set.approved_at !== null)
const names = computed(() => props.set.competencies.map((c) => c.name))
const groups = computed(() => {
  const list = q.data ?? []
  return names.value.map((name) => ({ name, items: list.filter((x) => x.competency === name) }))
})

const editing = ref<string | null>(null)
const form = ref({ competency: '', question: '', intent: '' })
const startAdd = (competency: string) => {
  editing.value = 'new'
  form.value = { competency, question: '', intent: '' }
}
const startEdit = (p: PresetQuestion) => {
  editing.value = p.id
  form.value = { competency: p.competency, question: p.question, intent: p.intent }
}
const cancel = () => (editing.value = null)
const canSave = computed(() => form.value.question.trim() !== '' && names.value.includes(form.value.competency))

function save() {
  const body = { competency: form.value.competency, question: form.value.question.trim(), intent: form.value.intent.trim() }
  const done = { onSuccess: () => (editing.value = null), onError: toastError('사전 질문을 저장하지 못했습니다') }
  if (editing.value === 'new') m.create.mutate(body, done)
  else if (editing.value) m.update.mutate({ id: editing.value, body }, done)
}
const remove = (p: PresetQuestion) => m.remove.mutate(p.id, { onError: toastError('사전 질문을 지우지 못했습니다') })
const generate = () =>
  m.generate.mutate(undefined, {
    onSuccess: (list) => toast.success(`AI가 사전 질문을 더했습니다 (모두 ${list.length}개)`, { description: '이전 차수 질문과 겹치지 않게 만들었습니다. 검토한 뒤 확정하세요.' }),
    onError: toastError('사전 질문 초안을 만들지 못했습니다'),
  })
const asString = (v: unknown) => (typeof v === 'string' ? v : '')
</script>

<template>
  <Card class="overflow-hidden" data-testid="preset-editor">
    <div class="flex flex-wrap items-center gap-3 border-b px-4 py-3">
      <h3 class="flex items-center gap-1.5 text-sm font-semibold">
        <ListChecksIcon class="size-4 text-muted-foreground" aria-hidden="true" />
        {{ roundLabel }} 사전 질문
        <span class="text-xs font-normal text-muted-foreground tabular">{{ q.data?.length ?? 0 }}개 · v{{ set.version }}</span>
      </h3>
      <span v-if="locked" class="inline-flex items-center gap-1 text-xs text-muted-foreground">
        <LockIcon class="size-3.5" aria-hidden="true" />
        확정된 버전이라 바꿀 수 없습니다. 새 초안을 만들면 질문도 함께 옮겨집니다.
      </span>
      <Button v-else variant="brand" size="sm" class="ml-auto" :disabled="m.generate.isPending || names.length === 0" @click="generate">
        <SparklesIcon :class="m.generate.isPending ? 'animate-pulse' : undefined" />
        {{ m.generate.isPending ? '질문 만드는 중…' : 'AI 질문 초안' }}
      </Button>
    </div>
    <Skeleton v-if="!q.data" class="m-4 h-32" />
    <div v-else class="divide-y">
      <section v-for="g in groups" :key="g.name" class="px-4 py-3" :aria-label="`${g.name} 사전 질문`">
        <div class="mb-2 flex items-center justify-between gap-2">
          <p class="text-[12px] font-medium text-muted-foreground">{{ g.name }}</p>
          <Button v-if="!locked && editing === null" variant="ghost" size="xs" @click="startAdd(g.name)">
            <PlusIcon />
            질문 추가
          </Button>
        </div>
        <p v-if="g.items.length === 0 && editing !== 'new'" class="text-[12.5px] text-muted-foreground/80">이 역량의 질문이 없습니다.</p>
        <ul class="space-y-1.5">
          <li v-for="p in g.items" :key="p.id" class="group rounded-lg border bg-card px-3 py-2">
            <template v-if="editing !== p.id">
              <div class="flex items-start gap-2">
                <div class="min-w-0 flex-1">
                  <p class="text-[13px] leading-snug">{{ p.question }}</p>
                  <p v-if="p.intent" class="mt-0.5 text-[11.5px] text-muted-foreground">{{ p.intent }}</p>
                </div>
                <div v-if="!locked && editing === null" class="flex shrink-0 gap-0.5 opacity-70 group-hover:opacity-100">
                  <Button variant="ghost" size="icon-xs" :aria-label="`질문 수정: ${p.question}`" @click="startEdit(p)"><PencilIcon /></Button>
                  <Button variant="ghost" size="icon-xs" :aria-label="`질문 삭제: ${p.question}`" :disabled="m.remove.isPending" @click="remove(p)">
                    <Trash2Icon />
                  </Button>
                </div>
              </div>
            </template>
            <form v-else class="space-y-2" @submit.prevent="save">
              <Textarea v-model="form.question" rows="2" aria-label="질문" class="text-[13px]" />
              <Input v-model="form.intent" placeholder="확인하려는 것 (선택)" aria-label="확인하려는 것" class="h-8 text-[13px]" />
              <div class="flex justify-end gap-1.5">
                <Button type="button" variant="ghost" size="xs" @click="cancel"><XIcon />취소</Button>
                <Button type="submit" size="xs" :disabled="!canSave || m.update.isPending"><CheckIcon />저장</Button>
              </div>
            </form>
          </li>
          <li v-if="editing === 'new' && form.competency === g.name" class="rounded-lg border border-ring/40 bg-card px-3 py-2">
            <form class="space-y-2" @submit.prevent="save">
              <Select :model-value="form.competency" @update:model-value="(v) => (form.competency = asString(v))">
                <SelectTrigger class="h-8 text-[13px]" aria-label="역량"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem v-for="n in names" :key="n" :value="n">{{ n }}</SelectItem>
                </SelectContent>
              </Select>
              <Textarea v-model="form.question" rows="2" placeholder="행동 사례를 묻는 질문" aria-label="새 질문" class="text-[13px]" />
              <Input v-model="form.intent" placeholder="확인하려는 것 (선택)" aria-label="확인하려는 것" class="h-8 text-[13px]" />
              <div class="flex justify-end gap-1.5">
                <Button type="button" variant="ghost" size="xs" @click="cancel"><XIcon />취소</Button>
                <Button type="submit" size="xs" :disabled="!canSave || m.create.isPending"><CheckIcon />추가</Button>
              </div>
            </form>
          </li>
        </ul>
      </section>
    </div>
  </Card>
</template>
