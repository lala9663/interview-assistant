/**
 * The prohibited-question rules of `ai/question_rules.py`, ported for the mock API (same categories,
 * labels, legal basis and patterns). A match is a warning for a person to read, not a verdict.
 */
import type { BankFlag } from '@/api/types'

interface Rule {
  category: string
  label: string
  basis: string
  patterns: RegExp[]
}

const FAMILY = '(부모|부모님|아버지|어머니|아버님|어머님|아빠|엄마|형제|자매|남매|형님|오빠|언니|누나|남동생|여동생|배우자|남편|아내|자녀|아들|딸|가족)'

export const RULES: Rule[] = [
  {
    category: 'family',
    label: '가족 사항',
    basis: '채용절차법 제4조의3 (직계 존비속·형제자매의 학력·직업·재산)',
    patterns: [
      // a family member and their job, schooling or wealth in the same sentence
      new RegExp(`${FAMILY}[^.?!\\n]{0,20}?(직업|직장|학력|학교|재산|회사|직위|무슨\\s*일|어떤\\s*일|뭐\\s*하|하시는\\s*일|일하시)`),
      /가족\s*(관계|구성|사항|형태|상황|중에|분들)/,
      /(아버지|어머니|부모님)\s*(는|은|께서는)?\s*(뭐|무엇|어디)/,
      /(형제|자매|남매)\s*(관계|가\s*(몇|있)|는\s*몇)/,
      /(외동|장남|장녀|막내|몇\s*남\s*몇\s*녀)/,
      /(한부모|편부|편모|이혼\s*가정)/,
    ],
  },
  {
    category: 'origin',
    label: '출신 지역·국가·민족',
    basis: '채용절차법 제4조의3, 국가인권위원회법 제2조',
    patterns: [/(고향|본적|출신\s*(지역|지|도|국가|나라|민족)|어디\s*출신|어느\s*지역\s*(사람|출신)|본관)/, /(사투리|억양)\s*(이|가|을|를)?\s*(있|쓰|들리)/, /(국적|민족|인종|피부색)/],
  },
  {
    category: 'marriage',
    label: '혼인·연애',
    basis: '채용절차법 제4조의3, 남녀고용평등법 제7조',
    patterns: [/(결혼|혼인|기혼|미혼|이혼|재혼|사실혼|약혼|배우자|(?<!장)애인|연애|남자\s*친구|여자\s*친구|남친|여친)/],
  },
  {
    category: 'pregnancy',
    label: '임신·출산·육아 계획',
    basis: '남녀고용평등법 제7조, 국가인권위원회법 제2조',
    patterns: [/(임신|출산|산후|아이를\s*(낳|가질)|자녀\s*(계획|를\s*가질|가\s*있|는\s*몇)|아이\s*계획|육아\s*(휴직|때문)|아이가\s*(있|몇))/],
  },
  {
    category: 'religion',
    label: '종교',
    basis: '국가인권위원회법 제2조',
    patterns: [/(종교|신앙|교회|성당|사찰|절에\s*다|기독교|불교|천주교|이슬람|무교)/],
  },
  {
    category: 'appearance',
    label: '외모·신체 조건',
    basis: '채용절차법 제4조의3, 남녀고용평등법 제7조',
    patterns: [/(외모|용모|생김새|얼굴|인상이|키가|키는|키\s*몇|신장|몸무게|체중|체격|살을\s*빼|뚱뚱|날씬|문신)/],
  },
  { category: 'age', label: '나이', basis: '국가인권위원회법 제2조 (직무와 무관한 나이)', patterns: [/(나이|몇\s*살|연세|연령|몇\s*년생|출생\s*연도|무슨\s*띠|띠가)/] },
  {
    category: 'wealth',
    label: '재산·경제 사정',
    basis: '채용절차법 제4조의3',
    patterns: [/(재산|자가|전세|월세|집이\s*있|부채|빚이|대출이\s*있|생활\s*형편|경제\s*사정)/],
  },
  {
    category: 'politics',
    label: '정치 성향·사상',
    basis: '국가인권위원회법 제2조',
    patterns: [/(정치\s*성향|지지\s*(하는\s*)?정당|정당\s*(가입|활동)|투표|진보|보수\s*(성향|정당)|노조\s*(가입|활동))/],
  },
  {
    category: 'health',
    label: '건강·병력·장애',
    basis: '국가인권위원회법 제2조, 장애인차별금지법 (직무와 무관한 건강 정보)',
    patterns: [
      /(병력|지병|질병|투병|수술\s*(받|한)|건강\s*(상태|문제)|정신과|우울증|복용\s*(하는|중인)\s*약)/,
      /(장애인|장애\s*(여부|등급|판정)|장애(가|를)\s*(있으신|있으세요|있나요|가지고))/,
    ],
  },
  {
    category: 'orientation',
    label: '성별 고정관념·성적 지향',
    basis: '남녀고용평등법 제7조, 국가인권위원회법 제2조',
    patterns: [/(성적\s*지향|동성애|성\s*정체성)/, /(여자|여성|남자|남성)(라서|이라서|이니까|인데)\s*/, /(여자|여성)\s*(가|이|로서)?\s*(야근|출장|체력|버틸)/],
  },
  {
    category: 'school',
    label: '출신 학교 (블라인드)',
    basis: '블라인드 채용 지침 (출신 학교·학벌로 판단하지 않음)',
    patterns: [/(출신\s*(학교|대학|고교|고등학교)|어느\s*(학교|대학)\s*(나오|나왔|졸업|출신|다니)|학벌|명문대|지방대)/],
  },
]

const SAFE = [
  /가족\s*같은/g,
  /팀\s*분위기/g,
  /(장비|설정|키|API|암호화|기본|외래|고유)\s*키/g,
  /키\s*(값|를\s*(돌|바꾸|관리)|관리|회전|발급)/g,
  /(나이테|나이브)/g,
  /(얼굴|안면)\s*인식/g,
  /(투표|다수결)로\s*(정|결정)/g,
  /(성장|진보)\s*(했|하는|과정)/g,
  /보수적(으로|인)/g,
  /경제\s*(성|적|효과)/g,
]

export function checkQuestion(...texts: string[]): BankFlag[] {
  const found = new Map<string, BankFlag>()
  for (const text of texts) {
    let clean = text ?? ''
    for (const safe of SAFE) clean = clean.replace(safe, (m) => ' '.repeat(m.length))
    for (const rule of RULES) {
      if (found.has(rule.category)) continue
      for (const pattern of rule.patterns) {
        const m = pattern.exec(clean)
        if (m) {
          found.set(rule.category, { category: rule.category, label: rule.label, basis: rule.basis, matched: m[0].trim(), source: 'rule', note: '' })
          break
        }
      }
    }
  }
  return RULES.filter((r) => found.has(r.category)).map((r) => found.get(r.category)!)
}
