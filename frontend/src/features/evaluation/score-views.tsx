import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import type { Evaluation } from '@/api/types'
import { buildCompetencyRows, confidenceLabel, LOW_CONFIDENCE, type CompetencyRow } from '@/lib/scoring'
import { cn, formatScore } from '@/lib/utils'

import { buildSeries, type Series } from './series'

export function Legend({ series }: { series: Series[] }) {
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-muted-foreground" aria-label="범례">
      {series.map((s) => (
        <li key={s.key} className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-[3px]" style={{ background: s.color }} aria-hidden />
          {s.label}
          {s.kind === 'ai' && <span className="sr-only">AI 점수는 참고용</span>}
        </li>
      ))}
    </ul>
  )
}

type ChartDatum = { competency: string } & Record<string, number | string | null>

function toChartData(rows: CompetencyRow[]): ChartDatum[] {
  return rows.map((r) => ({ competency: r.competency, ai: r.ai, ...r.interviewers }))
}

function ChartTooltip({ active, payload, label, series }: { active?: boolean; payload?: readonly { dataKey?: unknown; value?: unknown }[]; label?: unknown; series: Series[] }) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-lg border bg-popover px-3 py-2 text-xs shadow-xl">
      <p className="mb-1.5 font-semibold text-foreground">{String(label)}</p>
      <ul className="space-y-1">
        {series.map((s) => {
          const v = payload.find((p) => p.dataKey === s.key)?.value
          return (
            <li key={s.key} className="flex items-center gap-2">
              <span className="size-2 rounded-[2px]" style={{ background: s.color }} aria-hidden />
              <span className="text-muted-foreground">{s.label}</span>
              <span className="ml-auto pl-4 font-semibold text-foreground tabular">
                {typeof v === 'number' ? (s.kind === 'ai' ? formatScore(v) : v) : '미제출'}
              </span>
            </li>
          )
        })}
      </ul>
      <p className="mt-1.5 border-t pt-1.5 text-[11px] text-muted-foreground">합산하지 않고 나란히 보여 줍니다</p>
    </div>
  )
}

/** Grouped horizontal bars per competency: AI and each interviewer side by side, never summed. */
export function ScoreChart({ ev, hideAi }: { ev: Evaluation; hideAi: boolean }) {
  const rows = buildCompetencyRows(ev)
  const series = buildSeries(ev, hideAi)
  const data = toChartData(rows)
  const barSize = series.length > 3 ? 7 : 9
  const height = Math.max(220, rows.length * (series.length * (barSize + 3) + 26) + 40)
  return (
    <div className="space-y-3">
      <Legend series={series} />
      <div style={{ height }} role="img" aria-label="역량별 AI 점수와 면접관 점수 비교 차트. 아래 표에 같은 값이 있습니다.">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 4 }} barGap={2} barCategoryGap={14}>
            <CartesianGrid horizontal={false} stroke="var(--chart-grid)" />
            <XAxis
              type="number"
              domain={[0, 5]}
              ticks={[1, 2, 3, 4, 5]}
              tickLine={false}
              axisLine={{ stroke: 'var(--chart-grid)' }}
              tick={{ fill: 'var(--chart-axis)', fontSize: 11 }}
            />
            <YAxis
              type="category"
              dataKey="competency"
              width={128}
              tickLine={false}
              axisLine={false}
              tick={{ fill: 'var(--muted-foreground)', fontSize: 12 }}
            />
            <Tooltip cursor={{ fill: 'var(--muted)', opacity: 0.5 }} content={(p) => <ChartTooltip {...p} series={series} />} />
            {series.map((s) => (
              <Bar key={s.key} dataKey={s.key} name={s.label} fill={s.color} barSize={barSize} radius={[0, 4, 4, 0]} isAnimationActive={false} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

/** Table view of the same numbers. Deliberately no total/average column (FR-07). */
export function ScoreTable({ ev, hideAi }: { ev: Evaluation; hideAi: boolean }) {
  const rows = buildCompetencyRows(ev)
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[13px]" aria-label="역량별 점수 표">
        <thead>
          <tr className="border-b text-left text-xs text-muted-foreground">
            <th className="py-2 pr-3 font-medium">역량</th>
            {!hideAi && (
              <>
                <th className="px-3 py-2 text-right font-medium">AI (참고)</th>
                <th className="px-3 py-2 font-medium">신뢰도</th>
              </>
            )}
            {ev.interviewers.map((iv) => (
              <th key={iv.interviewer.id} className="px-3 py-2 text-right font-medium">
                {iv.interviewer.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.competency} className="border-b last:border-0" data-testid={`score-row-${r.competency}`}>
              <td className="py-2.5 pr-3 font-medium">{r.competency}</td>
              {!hideAi && (
                <>
                  <td className="px-3 py-2.5 text-right font-semibold tabular" data-testid="ai-score">
                    {r.ai == null ? <span className="font-normal text-muted-foreground">근거 없음</span> : formatScore(r.ai)}
                  </td>
                  <td className="px-3 py-2.5 text-xs">
                    {r.aiConfidence == null ? (
                      '–'
                    ) : (
                      <span className={cn('tabular', r.aiConfidence < LOW_CONFIDENCE ? 'font-medium text-warning' : 'text-muted-foreground')}>
                        {confidenceLabel(r.aiConfidence)} · {r.aiConfidence.toFixed(2)}
                      </span>
                    )}
                  </td>
                </>
              )}
              {ev.interviewers.map((iv) => {
                const v = r.interviewers[iv.interviewer.id]
                return (
                  <td key={iv.interviewer.id} className="px-3 py-2.5 text-right font-semibold tabular" data-testid="interviewer-score">
                    {v == null ? <span className="font-normal text-muted-foreground">미제출</span> : v}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-[11.5px] text-muted-foreground">합계·평균 열은 두지 않습니다. AI 점수와 면접관 점수는 따로 저장하고 합산하지 않습니다.</p>
    </div>
  )
}
