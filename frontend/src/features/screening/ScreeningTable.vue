<script setup lang="ts">
import { ArrowDownIcon, ArrowUpIcon, ChevronsUpDownIcon, SearchIcon, SearchXIcon } from '@lucide/vue'
import { computed, ref } from 'vue'

import type { ApplicationRow } from '@/api/types'
import EmptyState from '@/components/common/EmptyState.vue'
import FitBar from '@/components/common/FitBar.vue'
import Pseudonym from '@/components/common/Pseudonym.vue'
import ScreeningBadge from '@/components/common/ScreeningBadge.vue'
import StageBadge from '@/components/common/StageBadge.vue'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Segmented, SegmentedItem } from '@/components/ui/segmented'
import { SCREENING_STATUS_LABEL } from '@/lib/labels'
import { formatDateShort } from '@/lib/time'
import { cn } from '@/lib/utils'

import { countByStatus, filterRows, sortRows, type Sort, type SortKey, type StatusFilter } from './table-logic'

const props = defineProps<{ rows: ApplicationRow[]; selectedId: string | null }>()
const emit = defineEmits<{ open: [applicationId: string] }>()

const FILTERS: StatusFilter[] = ['all', 'passed', 'hold', 'rejected']
const status = ref<StatusFilter>('all')
const query = ref('')
const sort = ref<Sort>({ key: 'fit', dir: 'desc' })
const counts = computed(() => countByStatus(props.rows))
const visible = computed(() => sortRows(filterRows(props.rows, status.value, query.value), sort.value))

const onSort = (key: SortKey) => {
  const s = sort.value
  sort.value = s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: key === 'pseudonym' ? 'asc' : 'desc' }
}
const sortIcon = (k: SortKey) => (sort.value.key !== k ? ChevronsUpDownIcon : sort.value.dir === 'asc' ? ArrowUpIcon : ArrowDownIcon)
const ariaSort = (k: SortKey) => (sort.value.key === k ? (sort.value.dir === 'asc' ? 'ascending' : 'descending') : 'none')
const reset = () => {
  status.value = 'all'
  query.value = ''
}
const HEADERS: { label: string; k?: SortKey; class?: string }[] = [
  { label: '지원자', k: 'pseudonym', class: 'pl-4' },
  { label: '적합도', k: 'fit' },
  { label: '상태' },
  { label: '경력', k: 'years' },
  { label: '핵심 기술' },
  { label: '진행' },
  { label: '접수', k: 'created', class: 'pr-4' },
]
</script>

<template>
  <Card class="overflow-hidden">
    <div class="flex flex-wrap items-center gap-3 border-b px-4 py-3">
      <Segmented :model-value="status" aria-label="선별 상태 필터" @update:model-value="(v) => (status = v as StatusFilter)">
        <SegmentedItem v-for="f in FILTERS" :key="f" :value="f">
          {{ f === 'all' ? '전체' : SCREENING_STATUS_LABEL[f] }}
          <span class="text-[11.5px] text-muted-foreground tabular">{{ counts[f] }}</span>
        </SegmentedItem>
      </Segmented>
      <div class="relative ml-auto w-full max-w-64">
        <SearchIcon class="absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
        <Input v-model="query" placeholder="가명 또는 기술 검색" class="h-8 pl-8 text-[13px]" aria-label="지원자 검색" />
      </div>
    </div>
    <div class="overflow-x-auto">
      <table class="w-full min-w-[760px] text-[13px]">
        <thead>
          <tr class="border-b bg-subtle text-left text-xs text-muted-foreground">
            <template v-for="h in HEADERS" :key="h.label">
              <th v-if="h.k" :class="cn('px-3 py-2.5 font-medium', h.class)" :aria-sort="ariaSort(h.k)">
                <button
                  type="button"
                  :class="cn('inline-flex items-center gap-1 hover:text-foreground', sort.key === h.k && 'text-foreground')"
                  @click="onSort(h.k)"
                >
                  {{ h.label }}
                  <component :is="sortIcon(h.k)" class="size-3.5" aria-hidden="true" />
                </button>
              </th>
              <th v-else :class="cn('px-3 py-2.5 font-medium', h.class)">{{ h.label }}</th>
            </template>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="r in visible"
            :key="r.application_id"
            tabindex="0"
            :aria-selected="selectedId === r.application_id"
            :class="
              cn(
                'cursor-pointer border-b transition-colors outline-none last:border-0 hover:bg-subtle focus-visible:bg-accent',
                selectedId === r.application_id && 'bg-accent',
              )
            "
            data-testid="screening-row"
            @click="emit('open', r.application_id)"
            @keydown.enter.space.prevent="emit('open', r.application_id)"
          >
            <td class="py-3 pr-3 pl-4">
              <Pseudonym :value="r.candidate.pseudonym" size="sm" />
            </td>
            <td class="px-3 py-3">
              <FitBar v-if="r.screening" :value="r.screening.fit_score" />
              <span v-else class="text-muted-foreground">선별 전</span>
            </td>
            <td class="px-3 py-3"><ScreeningBadge v-if="r.screening" :status="r.screening.status" /></td>
            <td class="px-3 py-3 tabular">{{ r.years_experience != null ? `${r.years_experience}년` : '–' }}</td>
            <td class="px-3 py-3">
              <div class="flex max-w-64 flex-wrap gap-1">
                <span v-for="s in r.top_skills" :key="s" class="rounded bg-muted px-1.5 py-0.5 text-[11.5px] text-muted-foreground">{{ s }}</span>
              </div>
            </td>
            <td class="px-3 py-3"><StageBadge :stage="r.stage" /></td>
            <td class="py-3 pr-4 pl-3 text-muted-foreground tabular">{{ formatDateShort(r.created_at) }}</td>
          </tr>
        </tbody>
      </table>
      <EmptyState v-if="visible.length === 0" compact :icon="SearchXIcon" title="조건에 맞는 지원자가 없습니다">
        <template #action>
          <Button size="sm" variant="outline" @click="reset">필터 초기화</Button>
        </template>
      </EmptyState>
    </div>
  </Card>
</template>
