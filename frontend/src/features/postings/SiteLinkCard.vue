<script setup lang="ts">
import { GlobeIcon, Link2OffIcon } from '@lucide/vue'
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { toast } from 'vue-sonner'

import { useMe, useUpdatePosting } from '@/api/queries'
import type { PostingDetail } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { toastError } from '@/lib/toast'

/**
 * 채용 사이트 공고 번호: site events name their posting by this number. Until it is set, the site's
 * applications for this posting wait as "모르는 공고 번호" on 연동 현황 and can be processed again after.
 */
const props = defineProps<{ posting: PostingDetail }>()

const me = useMe()
const update = useUpdatePosting(() => props.posting.id)
const value = ref(props.posting.site_posting_no ?? '')
watch(
  () => props.posting.site_posting_no,
  (v) => (value.value = v ?? ''),
)
const dirty = computed(() => value.value.trim() !== (props.posting.site_posting_no ?? ''))
const valid = computed(() => value.value.trim() === '' || /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/.test(value.value.trim()))

function save() {
  const next = value.value.trim() || null
  update.mutate(next, {
    onSuccess: (d) =>
      toast.success(d.site_posting_no ? `채용 사이트 공고 ${d.site_posting_no}에 연결했습니다` : '채용 사이트 연결을 해제했습니다', {
        description: d.site_posting_no ? '이 번호로 실패했던 지원서는 연동 현황에서 다시 처리하세요.' : undefined,
      }),
    onError: toastError('공고 번호를 저장하지 못했습니다'),
  })
}
</script>

<template>
  <Card class="mb-4 flex flex-wrap items-end gap-x-6 gap-y-3 px-4 py-3.5" data-testid="site-link-card">
    <div class="min-w-0 flex-1 space-y-1">
      <p class="flex items-center gap-1.5 text-[13px] font-medium">
        <GlobeIcon class="size-4 text-brand" aria-hidden="true" />
        채용 사이트 연동
      </p>
      <p class="text-xs text-muted-foreground">
        사이트에서 이 공고로 들어온 지원서는 공고 번호로 이 공고에 붙습니다. 한 방향 연동이라 사이트의 상태는 바꾸지 않습니다.
        <RouterLink v-if="me.data?.is_admin" to="/admin/intake" class="text-brand underline-offset-4 hover:underline">연동 현황</RouterLink>
      </p>
    </div>
    <form class="flex items-end gap-2" @submit.prevent="save">
      <div class="space-y-1">
        <Label for="site-posting-no" class="text-xs">채용 사이트 공고 번호</Label>
        <Input
          id="site-posting-no"
          v-model="value"
          class="h-8 w-48 font-mono text-[13px]"
          placeholder="연결 안 됨"
          autocomplete="off"
          :aria-invalid="!valid"
        />
      </div>
      <Button type="submit" size="sm" variant="outline" :disabled="!dirty || !valid || update.isPending">
        {{ update.isPending ? '저장 중…' : value.trim() || !posting.site_posting_no ? '저장' : '연결 해제' }}
        <Link2OffIcon v-if="!value.trim() && posting.site_posting_no" aria-hidden="true" />
      </Button>
    </form>
    <p v-if="!valid" class="w-full text-xs text-danger">영문·숫자와 . _ : - 만 쓸 수 있습니다 (64자 이하).</p>
  </Card>
</template>
