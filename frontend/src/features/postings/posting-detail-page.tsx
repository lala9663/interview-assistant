import { ArrowLeftIcon, BookCheckIcon, CopyPlusIcon, FileSearchIcon, FileTextIcon, LockIcon, PencilIcon, SparklesIcon } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { toast } from 'sonner'

import { ApiError } from '@/api/client'
import {
  useApproveCompetencySet,
  useCompetencySets,
  useCreateCompetencySet,
  useGenerateCompetencySet,
  useInterviewers,
  usePosting,
  useUpdateCompetencySet,
} from '@/api/queries'
import type { Competency, CompetencySet } from '@/api/types'
import { Page, PageHeader } from '@/components/common/page'
import { EmptyState, ErrorState } from '@/components/common/states'
import { Badge, Card, CardContent, Skeleton } from '@/components/ui/basic'
import { Button } from '@/components/ui/button'
import { Segmented, SegmentedItem, Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/form'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/overlay'
import { POSTING_STATUS_LABEL } from '@/lib/labels'
import { formatDateTime, formatFullDate } from '@/lib/time'

import { CompetencyEditor, CompetencyRubric } from './competency-editor'
import { isComplete } from './competency-utils'

const fail = (title: string) => (e: unknown) => toast.error(title, { description: e instanceof ApiError ? e.message : undefined })

function CompetencySection({ postingId }: { postingId: string }) {
  const sets = useCompetencySets(postingId)
  const interviewers = useInterviewers()
  const [picked, setPicked] = useState<number | null>(null)
  const [draft, setDraft] = useState<Competency[] | null>(null)
  const create = useCreateCompetencySet(postingId)
  const update = useUpdateCompetencySet(postingId)
  const approve = useApproveCompetencySet(postingId)
  const generate = useGenerateCompetencySet(postingId)

  if (sets.isError) return <ErrorState error={sets.error} onRetry={() => void sets.refetch()} />
  if (sets.isPending) return <Skeleton className="h-96" />

  const list = sets.data
  const latest = list[list.length - 1]
  const current: CompetencySet | undefined = list.find((s) => s.version === picked) ?? latest
  const approvedLatest = [...list].reverse().find((s) => s.approved_at)
  const newNames = current && approvedLatest && current.id !== approvedLatest.id
    ? new Set(current.competencies.map((c) => c.name).filter((n) => !approvedLatest.competencies.some((a) => a.name === n)))
    : undefined
  const approverName = (id: string | null) => interviewers.data?.find((i) => i.id === id)?.name ?? id ?? ''
  const editing = draft !== null

  const onGenerate = () =>
    generate.mutate(undefined, {
      onSuccess: (s) => {
        setPicked(s.version)
        toast.success(`AI가 v${s.version} 초안을 만들었습니다`, { description: '검토하고 수정한 뒤 확정하세요.' })
      },
      onError: fail('초안을 만들지 못했습니다'),
    })

  const onNewDraft = () =>
    current &&
    create.mutate(current.competencies, {
      onSuccess: (s) => {
        setPicked(s.version)
        setDraft(structuredClone(s.competencies))
      },
      onError: fail('새 버전을 만들지 못했습니다'),
    })

  const onSave = () =>
    current &&
    draft &&
    update.mutate(
      { id: current.id, competencies: draft },
      { onSuccess: () => (setDraft(null), toast.success(`v${current.version} 초안을 저장했습니다`)), onError: fail('저장하지 못했습니다') },
    )

  const onApprove = () =>
    current &&
    approve.mutate(current.id, {
      onSuccess: () => toast.success(`v${current.version}을 확정했습니다`, { description: '이후 선별과 평가는 이 버전을 기준으로 합니다.' }),
      onError: fail('확정하지 못했습니다'),
    })

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        {list.length > 0 && (
          <Segmented
            type="single"
            value={current ? String(current.version) : ''}
            onValueChange={(v) => v && !editing && setPicked(Number(v))}
            aria-label="버전 선택"
          >
            {list.map((s) => (
              <SegmentedItem key={s.id} value={String(s.version)} disabled={editing}>
                v{s.version}
                {s.approved_at ? <LockIcon className="size-3" aria-label="확정" /> : <span className="text-[11px] text-muted-foreground">초안</span>}
              </SegmentedItem>
            ))}
          </Segmented>
        )}
        <div className="ml-auto flex flex-wrap gap-2">
          {editing ? (
            <>
              <Button variant="ghost" size="sm" onClick={() => setDraft(null)}>
                취소
              </Button>
              <Button size="sm" onClick={onSave} disabled={update.isPending || draft.length === 0 || !draft.every(isComplete)}>
                {update.isPending ? '저장 중…' : '초안 저장'}
              </Button>
            </>
          ) : (
            <>
              <Button variant="brand" size="sm" onClick={onGenerate} disabled={generate.isPending}>
                <SparklesIcon className={generate.isPending ? 'animate-pulse' : undefined} />
                {generate.isPending ? 'JD로 초안 만드는 중…' : 'AI 초안 생성'}
              </Button>
              {current?.approved_at ? (
                <Button variant="outline" size="sm" onClick={onNewDraft} disabled={create.isPending}>
                  <CopyPlusIcon />이 버전으로 새 초안
                </Button>
              ) : (
                current && (
                  <>
                    <Button variant="outline" size="sm" onClick={() => setDraft(structuredClone(current.competencies))}>
                      <PencilIcon />
                      편집
                    </Button>
                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <Button size="sm" disabled={approve.isPending}>
                          <BookCheckIcon />
                          확정
                        </Button>
                      </AlertDialogTrigger>
                      <AlertDialogContent>
                        <AlertDialogHeader>
                          <AlertDialogTitle>v{current.version}을 확정할까요?</AlertDialogTitle>
                          <AlertDialogDescription>
                            확정한 버전은 수정할 수 없고, 이후 서류 선별과 면접 평가(AI·면접관 모두)의 기준이 됩니다. 이미 진행된 평가는 당시 버전을 유지합니다.
                          </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>취소</AlertDialogCancel>
                          <AlertDialogAction onClick={onApprove}>확정</AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  </>
                )
              )}
            </>
          )}
        </div>
      </div>

      {current && (
        <div className="flex flex-wrap items-center gap-2 text-[13px] text-muted-foreground">
          {current.approved_at ? (
            <Badge variant="success">
              <LockIcon />
              확정
            </Badge>
          ) : (
            <Badge variant="warning">초안</Badge>
          )}
          <span>
            v{current.version} · 역량 {current.competencies.length}개 · {formatFullDate(current.created_at)} 생성
            {current.approved_at && ` · ${approverName(current.approved_by)} 확정 (${formatDateTime(current.approved_at)})`}
          </span>
          {!current.approved_at && <span>· 확정 전까지 수정할 수 있습니다</span>}
        </div>
      )}

      {list.length === 0 ? (
        <Card>
          <EmptyState
            icon={SparklesIcon}
            title="역량 사전이 없습니다"
            description="JD를 바탕으로 AI가 역량 목록과 1~5점 행동 기준 초안을 만들고, 담당자가 검토해 확정합니다."
            action={
              <Button variant="brand" size="sm" onClick={onGenerate} disabled={generate.isPending}>
                <SparklesIcon />
                AI 초안 생성
              </Button>
            }
          />
        </Card>
      ) : editing ? (
        <CompetencyEditor value={draft} onChange={setDraft} />
      ) : (
        current && <CompetencyRubric competencies={current.competencies} newNames={newNames} />
      )}
    </div>
  )
}

export default function PostingDetailPage() {
  const { postingId = '' } = useParams()
  const q = usePosting(postingId)

  if (q.isError) {
    return (
      <Page>
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      </Page>
    )
  }
  if (q.isPending) {
    return (
      <Page>
        <Skeleton className="mb-2 h-3 w-24" />
        <Skeleton className="mb-6 h-7 w-80" />
        <Skeleton className="h-96" />
      </Page>
    )
  }
  const p = q.data
  return (
    <Page>
      <PageHeader
        eyebrow={
          <Link to="/postings" className="inline-flex items-center gap-1 hover:text-foreground">
            <ArrowLeftIcon className="size-3.5" aria-hidden />
            공고·역량 사전
          </Link>
        }
        title={p.title}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <span>{p.job_family}</span>
            <Badge variant={p.status === 'open' ? 'success' : 'outline'}>{POSTING_STATUS_LABEL[p.status]}</Badge>
            <span>
              지원 {p.counts.applications} · 통과 {p.counts.passed} · 면접 {p.counts.interviewing + p.counts.interviewed}
            </span>
          </span>
        }
        actions={
          <Button asChild variant="outline" size="sm">
            <Link to={`/screening/${p.id}`}>
              <FileSearchIcon />
              서류 선별 보기
            </Link>
          </Button>
        }
      />
      <Tabs defaultValue="competency">
        <TabsList>
          <TabsTrigger value="competency">
            <BookCheckIcon />
            역량 사전
          </TabsTrigger>
          <TabsTrigger value="jd">
            <FileTextIcon />
            JD 원문
          </TabsTrigger>
        </TabsList>
        <TabsContent value="competency" className="mt-4">
          <CompetencySection postingId={p.id} />
        </TabsContent>
        <TabsContent value="jd" className="mt-4">
          <Card>
            <CardContent className="pt-5">
              <pre className="font-sans text-[14px] leading-[1.8] whitespace-pre-wrap">{p.jd_text}</pre>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </Page>
  )
}
