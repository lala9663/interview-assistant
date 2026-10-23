<script setup lang="ts">
import type { Component } from 'vue'
import { RouterLink } from 'vue-router'

import FadeIn from '@/components/common/FadeIn.vue'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'

defineProps<{ label: string; value: number | string; hint: string; icon: Component; to?: string; live?: boolean; delay: number }>()
</script>

<template>
  <FadeIn :delay="delay">
    <component
      :is="to ? RouterLink : 'div'"
      v-bind="to ? { to, class: 'block rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-ring/50' } : {}"
    >
      <Card :class="cn('group h-full px-4 py-3.5 transition-colors', to && 'hover:border-foreground/15')">
        <div class="flex items-center justify-between">
          <span class="text-[13px] text-muted-foreground">{{ label }}</span>
          <component :is="icon" class="size-4 text-muted-foreground/70" aria-hidden="true" />
        </div>
        <div class="mt-2 flex items-baseline gap-2">
          <span class="text-[28px] leading-none font-semibold tracking-tight">{{ value }}</span>
          <span v-if="live" class="size-2 animate-live rounded-full bg-live" aria-label="진행 중"></span>
        </div>
        <p class="mt-1.5 truncate text-xs text-muted-foreground">{{ hint }}</p>
      </Card>
    </component>
  </FadeIn>
</template>
