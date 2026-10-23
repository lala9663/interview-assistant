import { BARS_LEVELS, type Competency } from '@/api/types'

export const LEVEL_HINT: Record<string, string> = { '1': '미흡', '2': '기초', '3': '충족', '4': '우수', '5': '탁월' }

export function emptyCompetency(): Competency {
  return { name: '', description: '', bars: { '1': '', '2': '', '3': '', '4': '', '5': '' } }
}

export function isComplete(c: Competency): boolean {
  return c.name.trim() !== '' && c.description.trim() !== '' && BARS_LEVELS.every((l) => c.bars[l].trim() !== '')
}
