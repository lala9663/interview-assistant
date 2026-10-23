<script setup lang="ts">
import { BarElement, CategoryScale, Chart as ChartJS, LinearScale, Tooltip, type ChartData, type ChartOptions, type TooltipItem } from 'chart.js'
import { computed } from 'vue'
import { Bar } from 'vue-chartjs'

import type { Evaluation } from '@/api/types'
import { resolveCssColor } from '@/lib/css-color'
import { buildCompetencyRows } from '@/lib/scoring'
import { useTheme } from '@/lib/theme'
import { formatScore } from '@/lib/utils'

import ChartLegend from './ChartLegend.vue'
import { buildSeries } from './series'

ChartJS.register(BarElement, CategoryScale, LinearScale, Tooltip)

/** Grouped horizontal bars per competency: AI and each interviewer side by side, never summed. */
const props = defineProps<{ ev: Evaluation; hideAi: boolean }>()
const { resolved } = useTheme()

const rows = computed(() => buildCompetencyRows(props.ev))
const series = computed(() => buildSeries(props.ev, props.hideAi))
const barSize = computed(() => (series.value.length > 3 ? 7 : 9))
const categoryHeight = computed(() => series.value.length * (barSize.value + 3) + 26)
const height = computed(() => Math.max(220, rows.value.length * categoryHeight.value + 40))

/** Canvas needs concrete colors: re-read the tokens whenever the theme flips. */
const palette = computed(() => {
  void resolved.value
  return {
    grid: resolveCssColor('--chart-grid'),
    axis: resolveCssColor('--chart-axis'),
    label: resolveCssColor('--muted-foreground'),
    text: resolveCssColor('--foreground'),
    popover: resolveCssColor('--popover'),
    border: resolveCssColor('--border'),
    font: typeof document === 'undefined' ? 'sans-serif' : getComputedStyle(document.body).fontFamily,
  }
})

const data = computed<ChartData<'bar', (number | null)[], string>>(() => ({
  labels: rows.value.map((r) => r.competency),
  datasets: series.value.map((s) => {
    const color = resolveCssColor(s.color)
    return {
      label: s.label,
      data: rows.value.map((r) => (s.kind === 'ai' ? r.ai : (r.interviewers[s.key] ?? null))),
      backgroundColor: color,
      hoverBackgroundColor: color,
      borderRadius: 4,
      barThickness: barSize.value,
      // Slot per bar = bar + 3px, the rest of the category is the gap between competencies.
      categoryPercentage: (series.value.length * (barSize.value + 3)) / categoryHeight.value,
      barPercentage: 1,
    }
  }),
}))

const options = computed<ChartOptions<'bar'>>(() => {
  const p = palette.value
  const font = { family: p.font }
  return {
    indexAxis: 'y',
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    layout: { padding: { top: 4, right: 16, bottom: 4, left: 4 } },
    scales: {
      x: {
        min: 0,
        max: 5,
        ticks: { stepSize: 1, color: p.axis, font: { ...font, size: 11 }, callback: (v) => (v === 0 ? '' : v) },
        grid: { color: p.grid, drawTicks: false },
        border: { color: p.grid },
      },
      y: {
        ticks: { color: p.label, font: { ...font, size: 12 } },
        grid: { display: false },
        border: { display: false },
        afterFit: (scale) => {
          scale.width = 128
        },
      },
    },
    plugins: {
      legend: { display: false },
      tooltip: {
        mode: 'index',
        intersect: false,
        backgroundColor: p.popover,
        borderColor: p.border,
        borderWidth: 1,
        titleColor: p.text,
        bodyColor: p.label,
        footerColor: p.label,
        titleFont: { ...font, size: 12, weight: 600 },
        bodyFont: { ...font, size: 12 },
        footerFont: { ...font, size: 11, weight: 400 },
        padding: 10,
        boxWidth: 8,
        boxHeight: 8,
        boxPadding: 4,
        callbacks: {
          label: (item: TooltipItem<'bar'>) => {
            const s = series.value[item.datasetIndex]
            const v = item.parsed.x
            return `${s?.label ?? ''}  ${s?.kind === 'ai' ? formatScore(v ?? 0) : v}`
          },
          // Bars with no score are skipped by Chart.js; list them so the tooltip shows every series.
          afterBody: (items: TooltipItem<'bar'>[]) => {
            const i = items[0]?.dataIndex
            if (i === undefined) return []
            return series.value
              .filter((s) => (s.kind === 'ai' ? rows.value[i]?.ai : rows.value[i]?.interviewers[s.key]) == null)
              .map((s) => `${s.label}  미제출`)
          },
          footer: () => '합산하지 않고 나란히 보여 줍니다',
        },
      },
    },
  }
})
</script>

<template>
  <div class="space-y-3">
    <ChartLegend :series="series" />
    <div :style="{ height: `${height}px` }" role="img" aria-label="역량별 AI 점수와 면접관 점수 비교 차트. 아래 표에 같은 값이 있습니다.">
      <Bar :data="data" :options="options" />
    </div>
  </div>
</template>
