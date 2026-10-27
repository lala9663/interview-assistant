/**
 * Mock AI drafts for the 전형 tab, shaped like the fake model's (providers/fake_tasks.py): a later
 * round's dictionary looks at what earlier rounds did not, and preset questions never repeat a
 * question an earlier round (or the draft itself) already has.
 */
import type { Competency } from '@/api/types'

const bars = (...levels: string[]) => Object.fromEntries(levels.map((text, i) => [String(i + 1), text])) as Competency['bars']

const INITIATIVE: Competency = {
  name: '주도성',
  description: '맡은 범위를 넘어서는 문제를 스스로 정의하고 끝까지 해결한다.',
  bars: bars('지시받은 일만 수행한다.', '문제를 발견하면 보고한다.', '문제를 스스로 정의하고 해결안을 실행했다.', '여러 팀이 걸친 문제를 주도해 해결했다.', '조직의 우선순위를 바꾸는 개선을 주도했다.'),
}

const ORG_FIT: Competency = {
  name: '조직 적합과 성장 의지',
  description: '조직의 일하는 방식과 가치에 맞춰 일하고, 스스로 성장 목표를 세워 실행한다.',
  bars: bars(
    '지원 동기와 성장 목표가 막연하다.',
    '회사와 직무에 대한 기대를 일반론으로 설명한다.',
    '경험에 근거해 지원 동기와 성장 계획을 구체적으로 설명한다.',
    '조직의 우선순위와 자신의 강점을 연결해 기여 방식을 제시한다.',
    '장기적 기여 계획을 실행 근거와 함께 제시하고 주변의 성장까지 이끈다.',
  ),
}

const COLLABORATION: Competency = {
  name: '협업과 커뮤니케이션',
  description: '유관 부서와 이해관계를 조율하고 결과를 명확히 전달한다.',
  bars: bars(
    '담당 범위 밖 협업 경험이 거의 없다.',
    '요청받은 범위에서 정보를 공유한다.',
    '유관 부서와 목표를 맞추고 이견을 조정한 경험이 있다.',
    '이견이 있는 상황에서 근거로 합의를 이끌어냈다.',
    '조직 간 협업 구조를 새로 만들어 반복 문제를 줄였다.',
  ),
}

/** A round's AI draft: the current version plus 주도성, or for a later round what earlier rounds miss. */
export function draftRoundCompetencies(current: Competency[], earlierNames: string[]): Competency[] {
  if (current.length > 0) {
    const out = structuredClone(current)
    if (!out.some((c) => c.name === INITIATIVE.name)) out.push(structuredClone(INITIATIVE))
    return out
  }
  if (earlierNames.length > 0) {
    const seen = new Set(earlierNames)
    const picked = [INITIATIVE, ORG_FIT, COLLABORATION].filter((c) => !seen.has(c.name))
    return structuredClone(picked.length > 0 ? picked : [INITIATIVE, ORG_FIT])
  }
  return structuredClone([INITIATIVE, COLLABORATION])
}

// (competency keywords, questions, deeper questions for a later round)
const PRESETS: [string[], [string, string][], [string, string][]][] = [
  [
    ['문제'],
    [
      ['가장 어려웠던 문제를 하나 골라, 원인을 어떻게 좁혀 갔는지 설명해 주세요.', '가설 수립과 검증'],
      ['해결책이 기대만큼 효과가 없었던 경험과 그 뒤의 대응을 말씀해 주세요.', '실패 대응과 재검증'],
    ],
    [
      ['같은 문제가 다른 조건에서 다시 생긴다면 무엇부터 다르게 하시겠어요?', '학습과 일반화'],
      ['해결 방법을 팀의 표준으로 만든 경험이 있나요? 무엇이 어려웠나요?', '확산과 표준화'],
    ],
  ],
  [
    ['데이터', '분석'],
    [
      ['데이터로 판단을 바꾼 사례를 하나 설명해 주세요. 어떤 데이터를 어떤 순서로 보셨나요?', '분석 절차'],
      ['분석 결과가 현장의 직감과 달랐던 경험과 그때의 결론을 말씀해 주세요.', '데이터 근거 설득'],
    ],
    [
      ['데이터가 불완전한 상황에서 결정해야 했던 경험과 그 기준을 말씀해 주세요.', '불확실성 아래 판단'],
      ['분석 체계를 다른 사람도 쓸 수 있게 만든 경험이 있나요?', '분석의 확산'],
    ],
  ],
  [
    ['협업', '커뮤니케이션', '영향'],
    [
      ['유관 부서와 의견이 갈렸던 사례와 합의에 이른 과정을 말씀해 주세요.', '이견 조율'],
      ['외부 협력사와 일하며 어려웠던 점과 해결 방법은 무엇이었나요?', '외부 협업'],
    ],
    [
      ['권한이 없는 상대를 설득해 일정을 바꾼 경험을 말씀해 주세요.', '영향력'],
      ['협업이 실패했던 경험에서 본인이 바꾼 일하는 방식은 무엇인가요?', '회고와 변화'],
    ],
  ],
  [
    ['주도', '리더', '책임'],
    [
      ['맡은 범위를 넘어 스스로 문제를 정의하고 끝까지 해결한 경험을 말씀해 주세요.', '주도성'],
      ['팀의 우선순위를 바꾸자고 제안한 경험과 결과를 말씀해 주세요.', '변화 주도'],
    ],
    [
      ['결정이 틀렸다고 드러났을 때 책임을 어떻게 지셨나요?', '책임감'],
      ['후배나 동료의 성장을 이끈 구체적 사례를 말씀해 주세요.', '사람의 성장'],
    ],
  ],
  [
    ['조직', '성장', '적합'],
    [
      ['이 직무를 고른 이유와, 지난 경력과 어떻게 이어지는지 말씀해 주세요.', '지원 동기'],
      ['앞으로 3년 동안 이루고 싶은 성장 목표와 그 근거는 무엇인가요?', '성장 계획'],
    ],
    [
      ['조직의 방향과 본인의 판단이 달랐던 경험과 그때의 선택을 말씀해 주세요.', '가치 판단'],
      ['입사 후 첫해에 회사에 기여할 방법을 구체적으로 말씀해 주세요.', '기여 방식'],
    ],
  ],
]
const DEFAULT_PRESETS: [string, string][] = [
  ['이 역량이 드러난 최근 경험을 하나 골라 상황, 행동, 결과 순으로 설명해 주세요.', '행동 사례'],
  ['그 경험에서 다시 한다면 무엇을 바꾸시겠어요?', '회고'],
]

/** Two questions per competency that none of `taken` already has; a later round digs deeper. */
export function draftPresets(competencies: string[], taken: string[], laterRound: boolean): { competency: string; question: string; intent: string }[] {
  const used = new Set(taken)
  const out: { competency: string; question: string; intent: string }[] = []
  for (const name of competencies) {
    const [, base, deeper] = PRESETS.find(([keys]) => keys.some((k) => name.includes(k))) ?? [[], DEFAULT_PRESETS, DEFAULT_PRESETS]
    const pool = laterRound ? [...deeper, ...base] : [...base, ...deeper]
    for (const [question, intent] of pool.filter(([q]) => !used.has(q)).slice(0, 2)) {
      used.add(question)
      out.push({ competency: name, question, intent })
    }
  }
  return out
}
