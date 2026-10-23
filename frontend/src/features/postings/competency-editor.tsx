import { PlusIcon, Trash2Icon } from 'lucide-react'

import { BARS_LEVELS, type Competency } from '@/api/types'
import { Input, Label, Textarea } from '@/components/ui/basic'
import { Button } from '@/components/ui/button'

import { emptyCompetency, LEVEL_HINT } from './competency-utils'

/** Read-only rubric: one card per competency, BARS levels 1-5 as columns on wide screens. */
export function CompetencyRubric({ competencies, newNames }: { competencies: Competency[]; newNames?: Set<string> }) {
  return (
    <div className="space-y-3">
      {competencies.map((c) => (
        <div key={c.name} className="rounded-xl border bg-card">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b px-4 py-3">
            <h3 className="text-sm font-semibold">{c.name}</h3>
            {newNames?.has(c.name) && <span className="rounded bg-brand-soft px-1.5 py-0.5 text-[11px] font-medium text-brand">확정본 대비 추가</span>}
            <p className="text-[13px] text-muted-foreground">{c.description}</p>
          </div>
          <ol className="grid grid-cols-1 divide-y md:grid-cols-5 md:divide-x md:divide-y-0">
            {BARS_LEVELS.map((l) => (
              <li key={l} className="px-4 py-3">
                <p className="mb-1 flex items-baseline gap-1.5">
                  <span className="text-[15px] font-semibold tabular">{l}</span>
                  <span className="text-[11px] text-muted-foreground">{LEVEL_HINT[l]}</span>
                </p>
                <p className="text-[12.5px] leading-relaxed text-muted-foreground">{c.bars[l]}</p>
              </li>
            ))}
          </ol>
        </div>
      ))}
    </div>
  )
}

/** Editable rubric for draft versions. */
export function CompetencyEditor({ value, onChange }: { value: Competency[]; onChange: (v: Competency[]) => void }) {
  const patch = (i: number, c: Competency) => onChange(value.map((x, j) => (j === i ? c : x)))
  return (
    <div className="space-y-3">
      {value.map((c, i) => (
        <div key={i} className="rounded-xl border bg-card p-4">
          <div className="grid gap-3 md:grid-cols-[220px_1fr_auto] md:items-end">
            <div className="space-y-1.5">
              <Label htmlFor={`cname-${i}`}>역량 이름</Label>
              <Input id={`cname-${i}`} value={c.name} onChange={(e) => patch(i, { ...c, name: e.target.value })} placeholder="예: 공정 문제 해결" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor={`cdesc-${i}`}>정의</Label>
              <Input id={`cdesc-${i}`} value={c.description} onChange={(e) => patch(i, { ...c, description: e.target.value })} placeholder="관찰 가능한 행동으로 정의" />
            </div>
            <Button variant="ghost" size="icon-sm" onClick={() => onChange(value.filter((_, j) => j !== i))} aria-label={`${c.name || '역량'} 삭제`}>
              <Trash2Icon />
            </Button>
          </div>
          <div className="mt-3 grid gap-2 md:grid-cols-5">
            {BARS_LEVELS.map((l) => (
              <div key={l} className="space-y-1">
                <Label htmlFor={`bars-${i}-${l}`} className="text-xs text-muted-foreground">
                  {l}점 · {LEVEL_HINT[l]}
                </Label>
                <Textarea
                  id={`bars-${i}-${l}`}
                  value={c.bars[l]}
                  onChange={(e) => patch(i, { ...c, bars: { ...c.bars, [l]: e.target.value } })}
                  className="min-h-24 text-[12.5px]"
                  aria-invalid={c.bars[l].trim() === ''}
                />
              </div>
            ))}
          </div>
        </div>
      ))}
      <Button variant="outline" size="sm" onClick={() => onChange([...value, emptyCompetency()])}>
        <PlusIcon />
        역량 추가
      </Button>
    </div>
  )
}
