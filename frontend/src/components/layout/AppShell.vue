<script setup lang="ts">
import { FlaskConicalIcon, SearchIcon, TriangleAlertIcon } from '@lucide/vue'
import { computed, onErrorCaptured, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'

import { useMe, useSessions } from '@/api/queries'
import EmptyState from '@/components/common/EmptyState.vue'
import { Button } from '@/components/ui/button'
import { Kbd } from '@/components/ui/kbd'
import { Tooltip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

import CommandPalette from './CommandPalette.vue'
import { NAV_ITEMS } from './nav'
import ThemeToggle from './ThemeToggle.vue'

const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true'
const IS_MAC = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.userAgent)

const route = useRoute()
const me = useMe()
const live = useSessions('in_progress')
const liveSession = computed(() => {
  const s = live.data?.[0]
  return s && !route.path.endsWith(`${s.id}/live`) ? s : null
})
const paletteOpen = ref(false)

const isActive = (to: string) => (to === '/' ? route.path === '/' : route.path === to || route.path.startsWith(`${to}/`))

// A page that throws while rendering shows a full-screen error instead of a blank shell.
const renderError = ref<unknown>(null)
onErrorCaptured((err) => {
  renderError.value = err
  return false
})
watch(
  () => route.fullPath,
  () => (renderError.value = null),
)
const goHome = () => window.location.assign('/')
const errorMessage = computed(() => (renderError.value instanceof Error ? renderError.value.message : '예상하지 못한 오류가 발생했습니다.'))
</script>

<template>
  <div v-if="renderError" class="flex min-h-screen items-center justify-center p-6">
    <EmptyState :icon="TriangleAlertIcon" title="화면을 그리지 못했습니다" :description="errorMessage">
      <template #action>
        <Button variant="outline" size="sm" @click="goHome">처음으로</Button>
      </template>
    </EmptyState>
  </div>
  <div v-else class="flex min-h-screen">
    <aside class="sticky top-0 flex h-screen w-14 shrink-0 flex-col border-r bg-sidebar lg:w-60">
      <div class="flex h-14 items-center px-3.5 lg:px-4">
        <RouterLink to="/" class="flex items-center gap-2.5 rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
          <span class="flex size-7 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
            <svg viewBox="0 0 24 24" class="size-4" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linejoin="round" aria-hidden="true">
              <path d="M5 8a3 3 0 0 1 3-3h8a3 3 0 0 1 3 3v6a3 3 0 0 1-3 3h-4l-4 3v-3a3 3 0 0 1-3-3z" />
            </svg>
          </span>
          <span class="hidden text-[14px] leading-tight font-semibold tracking-tight lg:block">
            면접 어시스턴트
            <span class="block text-[11px] font-normal text-muted-foreground">Interview Assistant</span>
          </span>
        </RouterLink>
      </div>
      <nav class="flex flex-1 flex-col gap-0.5 px-2 pt-2" aria-label="주요 메뉴">
        <RouterLink
          v-for="item in NAV_ITEMS"
          :key="item.to"
          :to="item.to"
          :aria-current="isActive(item.to) ? 'page' : undefined"
          :class="
            cn(
              'group flex h-9 items-center gap-2.5 rounded-md px-2.5 text-[13.5px] font-medium text-muted-foreground transition-colors outline-none hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50',
              isActive(item.to) && 'bg-accent text-foreground',
            )
          "
        >
          <component :is="item.icon" :class="cn('size-[17px] shrink-0', isActive(item.to) && 'text-brand')" aria-hidden="true" />
          <span class="hidden truncate lg:block">{{ item.label }}</span>
          <span v-if="item.fr" class="ml-auto hidden text-[10.5px] font-normal text-muted-foreground/70 lg:block">{{ item.fr }}</span>
        </RouterLink>
      </nav>
      <Tooltip v-if="liveSession" content="진행 중인 면접으로 돌아가기" side="right">
        <RouterLink
          :to="`/sessions/${liveSession.id}/live`"
          class="mx-2 mb-2 flex items-center gap-2 rounded-lg border border-[color-mix(in_oklch,var(--live)_35%,transparent)] bg-[color-mix(in_oklch,var(--live)_9%,transparent)] px-2.5 py-2 text-xs transition-colors hover:bg-[color-mix(in_oklch,var(--live)_14%,transparent)]"
        >
          <span class="size-2 shrink-0 animate-live rounded-full bg-live" aria-hidden="true"></span>
          <span class="hidden min-w-0 lg:block">
            <span class="block font-medium text-live">진행 중 면접</span>
            <span class="block truncate font-mono text-muted-foreground">{{ liveSession.candidate.pseudonym }}</span>
          </span>
        </RouterLink>
      </Tooltip>
      <div class="border-t p-2">
        <Tooltip v-if="USE_MOCKS" content="백엔드 없이 모의 API(MSW)로 동작 중입니다. 데이터는 새로고침하면 초기화됩니다." side="right">
          <div class="mb-1 flex items-center gap-2 rounded-md px-2.5 py-1.5 text-xs text-muted-foreground">
            <FlaskConicalIcon class="size-3.5 shrink-0" aria-hidden="true" />
            <span class="hidden lg:block">모의 API 모드</span>
          </div>
        </Tooltip>
        <div class="flex items-center gap-2.5 rounded-md px-2 py-1.5">
          <span class="flex size-7 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold">
            {{ me.data?.name.slice(0, 1) ?? '' }}
          </span>
          <span class="hidden min-w-0 lg:block">
            <span class="block truncate text-[13px] font-medium">{{ me.data?.name ?? '…' }}</span>
            <span class="block truncate text-[11px] text-muted-foreground">{{ me.data?.department ?? '' }}</span>
          </span>
        </div>
      </div>
    </aside>
    <div class="flex min-w-0 flex-1 flex-col">
      <header class="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-3 border-b bg-background/80 px-4 backdrop-blur-md lg:px-6">
        <button
          type="button"
          class="flex h-8 w-full max-w-80 items-center gap-2 rounded-md border bg-card px-2.5 text-[13px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          @click="paletteOpen = true"
        >
          <SearchIcon class="size-3.5" aria-hidden="true" />
          <span class="flex-1 text-left">검색 또는 이동…</span>
          <Kbd>{{ IS_MAC ? '⌘K' : 'Ctrl K' }}</Kbd>
        </button>
        <div class="ml-auto flex items-center gap-1">
          <ThemeToggle />
        </div>
      </header>
      <main class="flex-1">
        <RouterView />
      </main>
    </div>
    <CommandPalette v-model:open="paletteOpen" />
  </div>
</template>
