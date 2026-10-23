// Copies the frontend mock dataset (frontend/src/mocks/data/*.ts) into the backend seed data
// (src/interview_assistant/demo/mock_data.json), so `scripts/seed_demo.py` loads exactly the same
// fictional postings, candidates, interviewers and scripted answers as the mock API.
//
//   node scripts/export_mock_data.mjs
//
// Needs Node 24+ (runs the .ts data files directly; they only have type imports).
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const data = (name) => new URL(`../frontend/src/mocks/data/${name}`, import.meta.url).href

const { INTERVIEWERS, ME_KEY, CANDIDATES } = await import(data('people.ts'))
const { POSTING_SEEDS } = await import(data('postings.ts'))
const { ANSWER_BANK, GENERIC_BANK } = await import(data('banks.ts'))

const postings = POSTING_SEEDS.map((p, i) => ({ key: `P${i + 1}`, ...p }))
const out = {
  source: 'frontend/src/mocks/data (scripts/export_mock_data.mjs). Fictional; no real people.',
  me: ME_KEY,
  interviewers: INTERVIEWERS,
  postings,
  candidates: CANDIDATES,
  answer_bank: ANSWER_BANK,
  generic_bank: GENERIC_BANK,
}
const target = fileURLToPath(new URL('../src/interview_assistant/demo/mock_data.json', import.meta.url))
writeFileSync(target, JSON.stringify(out, null, 1) + '\n', 'utf8')
console.log(`wrote ${target}`)
