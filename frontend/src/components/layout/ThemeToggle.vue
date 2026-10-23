<script setup lang="ts">
import { MonitorIcon, MoonIcon, SunIcon } from '@lucide/vue'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useTheme, type ThemePreference } from '@/lib/theme'

const { preference, resolved, setPreference } = useTheme()
</script>

<template>
  <DropdownMenu>
    <DropdownMenuTrigger as-child>
      <Button variant="ghost" size="icon-sm" aria-label="테마 바꾸기">
        <MoonIcon v-if="resolved === 'dark'" />
        <SunIcon v-else />
      </Button>
    </DropdownMenuTrigger>
    <DropdownMenuContent align="end" class="w-44">
      <DropdownMenuLabel>테마</DropdownMenuLabel>
      <DropdownMenuRadioGroup :model-value="preference" @update:model-value="(v) => setPreference(v as ThemePreference)">
        <DropdownMenuRadioItem value="dark">
          <MoonIcon />
          다크
        </DropdownMenuRadioItem>
        <DropdownMenuRadioItem value="light">
          <SunIcon />
          라이트
        </DropdownMenuRadioItem>
        <DropdownMenuRadioItem value="system">
          <MonitorIcon />
          시스템 설정
        </DropdownMenuRadioItem>
      </DropdownMenuRadioGroup>
    </DropdownMenuContent>
  </DropdownMenu>
</template>
