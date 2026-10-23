<script setup lang="ts">
import { CompassIcon } from '@lucide/vue'
import { RouterLink } from 'vue-router'

import EmptyState from '@/components/common/EmptyState.vue'
import Page from '@/components/common/Page.vue'
import { Button } from '@/components/ui/button'
</script>

<template>
  <Page>
    <EmptyState :icon="CompassIcon" title="페이지를 찾을 수 없습니다" description="주소가 바뀌었거나 삭제된 항목입니다.">
      <template #action>
        <Button as-child variant="outline" size="sm">
          <RouterLink to="/">대시보드로</RouterLink>
        </Button>
      </template>
    </EmptyState>
  </Page>
</template>
