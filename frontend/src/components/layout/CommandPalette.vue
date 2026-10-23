<script setup lang="ts">
import { ArrowRightIcon, MicIcon, MonitorIcon, MoonIcon, SearchIcon, SunIcon, UserRoundIcon } from '@lucide/vue'
import { ListboxContent, ListboxFilter, ListboxGroup, ListboxGroupLabel, ListboxItem, ListboxRoot } from 'reka-ui'
import { computed, onScopeDispose, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { useCandidateIndex, usePostings, useSessions } from '@/api/queries'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { Kbd } from '@/components/ui/kbd'
import { SCREENING_STATUS_LABEL, SESSION_STATUS_LABEL } from '@/lib/labels'
import { useTheme, type ThemePreference } from '@/lib/theme'
import { formatDateTime } from '@/lib/time'

import { NAV_ITEMS } from './nav'

const open = defineModel<boolean>('open', { default: false })

const router = useRouter()
const { setPreference } = useTheme()
const candidates = useCandidateIndex(open)
const sessions = useSessions()
const postings = usePostings()
const search = ref('')

const onKey = (e: KeyboardEvent) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    open.value = !open.value
  }
}
window.addEventListener('keydown', onKey)
onScopeDispose(() => window.removeEventListener('keydown', onKey))

watch(open, (o) => {
  if (o) search.value = ''
})

/** Plain substring match: pseudonyms like CAND-0012 should not fuzzy-match CAND-0001. */
function matches(value: string, keywords: readonly string[] = []) {
  const q = search.value.trim().toLowerCase()
  if (!q) return true
  return `${value} ${keywords.join(' ')}`.toLowerCase().includes(q)
}

const navItems = computed(() => NAV_ITEMS.filter((n) => matches(`nav ${n.label}`, [n.keywords ?? '', n.fr ?? ''])))
const sessionItems = computed(() =>
  (sessions.data ?? [])
    .filter((s) => s.status === 'in_progress' || s.status === 'scheduled' || s.status === 'completed')
    .slice(0, 8)
    .filter((s) => matches(`session ${s.candidate.pseudonym} ${s.posting.title} ${s.id}`, [SESSION_STATUS_LABEL[s.status]])),
)
const candidateItems = computed(() => (candidates.data ?? []).filter((c) => matches(`candidate ${c.pseudonym} ${c.posting_title}`)))
const postingItems = computed(() => (postings.data ?? []).filter((p) => matches(`posting ${p.title} ${p.job_family}`)))
const THEMES = [
  { value: 'dark', label: '다크 모드', haystack: 'theme dark 다크', icon: MoonIcon },
  { value: 'light', label: '라이트 모드', haystack: 'theme light 라이트', icon: SunIcon },
  { value: 'system', label: '시스템 설정 따르기', haystack: 'theme system 시스템', icon: MonitorIcon },
] as const
const themeItems = computed(() => THEMES.filter((t) => matches(t.haystack)))
const empty = computed(
  () =>
    navItems.value.length + sessionItems.value.length + candidateItems.value.length + postingItems.value.length + themeItems.value.length ===
    0,
)

function go(to: string) {
  open.value = false
  void router.push(to)
}

function setTheme(p: ThemePreference) {
  setPreference(p)
  open.value = false
}

const itemClass =
  'group flex cursor-default items-center gap-2.5 rounded-md px-2.5 py-2 text-sm outline-none select-none data-[highlighted]:bg-accent [&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-muted-foreground'
const headingClass = 'px-2.5 pt-3 pb-1.5 text-[11px] font-medium text-muted-foreground'
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent hide-close class="top-[14vh] max-w-xl translate-y-0 gap-0 overflow-hidden p-0 data-[state=open]:zoom-in-[0.98]">
      <DialogTitle class="sr-only">명령 팔레트</DialogTitle>
      <DialogDescription class="sr-only">화면, 지원자, 면접으로 이동합니다.</DialogDescription>
      <ListboxRoot highlight-on-hover loop aria-label="명령 팔레트">
        <div class="flex items-center gap-2 border-b px-3.5">
          <SearchIcon class="size-4 text-muted-foreground" aria-hidden="true" />
          <ListboxFilter
            v-model="search"
            auto-focus
            placeholder="화면, 지원자(CAND-…), 면접 검색"
            class="h-12 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          />
          <Kbd>Esc</Kbd>
        </div>
        <ListboxContent class="max-h-[min(440px,60vh)] scroll-py-2 overflow-y-auto p-1.5 scrollbar-thin">
          <div v-if="empty" class="py-10 text-center text-sm text-muted-foreground">결과가 없습니다.</div>

          <ListboxGroup v-if="navItems.length > 0">
            <ListboxGroupLabel :class="headingClass">이동</ListboxGroupLabel>
            <ListboxItem v-for="n in navItems" :key="n.to" :value="`nav:${n.to}`" :class="itemClass" @select="go(n.to)">
              <component :is="n.icon" />
              <span class="flex-1">{{ n.label }}</span>
              <span v-if="n.fr" class="text-[11px] text-muted-foreground">{{ n.fr }}</span>
            </ListboxItem>
          </ListboxGroup>

          <ListboxGroup v-if="sessionItems.length > 0">
            <ListboxGroupLabel :class="headingClass">면접</ListboxGroupLabel>
            <ListboxItem
              v-for="s in sessionItems"
              :key="s.id"
              :value="`session:${s.id}`"
              :class="itemClass"
              @select="go(s.status === 'completed' ? `/sessions/${s.id}/evaluation` : `/sessions/${s.id}/live`)"
            >
              <MicIcon />
              <span class="font-mono text-[13px] font-semibold">{{ s.candidate.pseudonym }}</span>
              <span class="truncate text-muted-foreground">{{ s.posting.title }}</span>
              <span class="ml-auto shrink-0 text-xs text-muted-foreground">
                <span v-if="s.status === 'in_progress'" class="font-medium text-live">진행 중</span>
                <template v-else-if="s.status === 'completed'">평가</template>
                <template v-else-if="s.scheduled_at">{{ formatDateTime(s.scheduled_at) }}</template>
              </span>
            </ListboxItem>
          </ListboxGroup>

          <ListboxGroup v-if="candidateItems.length > 0">
            <ListboxGroupLabel :class="headingClass">지원자</ListboxGroupLabel>
            <ListboxItem
              v-for="c in candidateItems"
              :key="c.application_id"
              :value="`candidate:${c.application_id}`"
              :class="itemClass"
              @select="go(`/screening/${c.posting_id}?app=${c.application_id}`)"
            >
              <UserRoundIcon />
              <span class="font-mono text-[13px] font-semibold">{{ c.pseudonym }}</span>
              <span class="truncate text-muted-foreground">{{ c.posting_title }}</span>
              <span class="ml-auto shrink-0 text-xs text-muted-foreground tabular">
                {{ c.screening_status ? `${SCREENING_STATUS_LABEL[c.screening_status]} · ${c.fit_score}` : '선별 전' }}
              </span>
            </ListboxItem>
          </ListboxGroup>

          <ListboxGroup v-if="postingItems.length > 0">
            <ListboxGroupLabel :class="headingClass">공고</ListboxGroupLabel>
            <ListboxItem v-for="p in postingItems" :key="p.id" :value="`posting:${p.id}`" :class="itemClass" @select="go(`/postings/${p.id}`)">
              <ArrowRightIcon />
              <span class="truncate">{{ p.title }}</span>
              <span class="ml-auto text-xs text-muted-foreground">{{ p.job_family }}</span>
            </ListboxItem>
          </ListboxGroup>

          <ListboxGroup v-if="themeItems.length > 0">
            <ListboxGroupLabel :class="headingClass">테마</ListboxGroupLabel>
            <ListboxItem v-for="t in themeItems" :key="t.value" :value="`theme:${t.value}`" :class="itemClass" @select="setTheme(t.value)">
              <component :is="t.icon" />
              {{ t.label }}
            </ListboxItem>
          </ListboxGroup>
        </ListboxContent>
      </ListboxRoot>
      <div class="flex items-center gap-3 border-t px-3.5 py-2 text-[11px] text-muted-foreground">
        <span class="flex items-center gap-1"><Kbd>↑</Kbd><Kbd>↓</Kbd> 이동</span>
        <span class="flex items-center gap-1"><Kbd>↵</Kbd> 열기</span>
      </div>
    </DialogContent>
  </Dialog>
</template>
