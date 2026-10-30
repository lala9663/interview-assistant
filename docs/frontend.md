# 프론트엔드 (면접관 UI)

> 다루는 것: `frontend/`의 스택, 화면 목록, 모의 API 모드와 백엔드 연결 모드, 검사·빌드, 의존성 규칙.
>
> 상태: 구현됨 · 확인: 2026-10-30

`frontend/`. Vite + Vue 3 + TypeScript(strict, `vue-tsc`), Tailwind CSS v4 + shadcn-vue 방식 컴포넌트(Reka UI), TanStack Query(`@tanstack/vue-query`), Vue Router, MSW, Chart.js(`vue-chartjs`), vue-sonner, lucide 아이콘(`@lucide/vue`). 명령 팔레트는 Reka UI Listbox, 화면 전환 효과는 Vue `<Transition>`과 CSS만 쓴다. 테스트는 Vitest + Testing Library(Vue) + MSW(node), 린트는 eslint-plugin-vue + typescript-eslint. 폰트는 Pretendard(OFL)를 npm 패키지에서 자체 호스팅한다. Node 24 이상. 이전 React 버전은 git 이력(`93a1780`)에 있다.

## 화면

대시보드, 공고·역량 사전(FR-02, 채용 사이트 공고 번호 연결, "전형" 탭: 차수 추가·순서·이름·설정, 차수별 역량 사전과 사전 질문), 서류 선별(FR-01·03, 수신 경로·진행 표시·차수 필터, 다음 차수를 기다리는 지원자는 상세에서 바로 면접 잡기: 차수·지원자 고정, 면접관·길이·기간 → 함께 비는 시간), 면접 목록, 실시간 면접(FR-04~08, 이전 차수 요약·이어 질문), 평가 결과(FR-07·08, N차 결정·확인할 점), 면접관 스케줄(FR-09, 차수부터 고르는 면접 잡기), 질문 은행(직군·역량별 검수 질문과 평점 기준 예시, [question-bank.md](question-bank.md)), 관리자 > 모델 설정(관리자만, [ai-models.md](ai-models.md)), 관리자 > 연동 현황(관리자만, 채용 사이트가 보낸 이벤트와 처리 결과), 관리자 > 꼬리질문 지표(관리자만, 출처별 채택률·첫 후보까지 시간·걸러낸 수). 실시간 면접의 마이크는 [audio-input.md](audio-input.md). 다크 모드 기본(시스템 설정 따름), Ctrl/⌘+K 명령 팔레트.

경로는 `frontend/src/router.ts`: `/`, `/postings`, `/postings/:postingId`, `/screening/:postingId?`, `/sessions`, `/sessions/:sessionId/live`, `/sessions/:sessionId/evaluation`, `/schedule`, `/question-bank`, `/admin/models`, `/admin/intake`, `/admin/follow-up-metrics`.

차수 표기 규칙: 차수는 어느 화면에서나 같은 회색 배지(`RoundBadge`, 짧게 "1차", 헤더는 굵게 "2차 · 임원 면접"), 상태는 색 칩(`StepStatusChip`: 예정 회색, 진행 중 빨간 점, 평가 대기, 결정 대기 파랑, 합격 초록, 보류 노랑, 불합격 빨강)으로 따로. 목록 행의 진행 표시는 `ProgressTrail`("서류 ✓ · 1차 ✓ · 2차 ●"), 지원자 상세는 `RoundStepper`(서류 → 각 차수 → 최종, 단계마다 결과와 날짜). 차수에는 색을 쓰지 않는다.

```
frontend/src/
  api/          # types.ts(모델과 1:1), endpoints, TanStack Query composable, SSE 파서
  mocks/        # 모의 API: 가상 데이터, 핸들러, 실시간 전사·꼬리질문 스트림 흉내, 모델 설정
  features/     # 화면: dashboard, postings, screening, sessions, interview(실시간, audio/ 마이크), evaluation, schedule, bank(질문 은행), admin(모델 설정, 꼬리질문 지표), intake(연동 현황), misc
  components/   # 공통 컴포넌트와 ui/ (shadcn-vue 방식)
```

## 모의 API 모드

```bash
cd frontend
npm ci
npm run dev          # → http://localhost:5173
```

`VITE_USE_MOCKS=true`(`.env.development`)면 브라우저의 MSW가 `/api` 요청에 답한다. 가상 데이터(공고 3 중 P1은 1차 직무·2차 임원 면접, 지원자 20, 면접관 5, 진행 중 면접 2(1차·2차), 예정 3(2차 1), 완료 9, 차수 결정 합격·보류·보류 뒤 불합격, 최종 합격 후보 1)는 새로고침하면 처음 상태로 돌아간다. 백엔드 시드(`seed_demo.py`)와 같은 배치다. 진행 중 면접 화면을 열면 지원자 답변이 글자 단위로 스트리밍되고, 답변이 끝나면 꼬리질문 후보가 스트리밍된다. 모델 설정 화면도 같은 흐름(다운로드 진행률, 연결 테스트, 외부 전송 경고, 이력·되돌리기)으로 동작한다. 연동 현황은 지어낸 수신 이력(반영, 이전 버전 건너뜀, 모르는 공고 번호·HWP·스캔본 실패, 받지 않는 항목 거절)으로 시작하고, 공고 P3에 `DS-2026-0103`을 연결한 뒤 "모르는 공고 번호 모두 다시 처리"를 누르면 지원서가 들어온다.

모의 모드에서 `/api`가 모두 502로 실패하면 브라우저가 MSW 서비스 워커를 재시작해 등록이 풀린 것이다. 새로고침하면 된다.

## 백엔드 연결 모드

같은 `/api` 경로를 Vite 프록시로 FastAPI(`localhost:8000`)에 보낸다. 대상은 `frontend/.env.api`의 `VITE_API_PROXY_TARGET`. 데이터는 DB에서 오고 새로고침해도 남는다. [setup.md](setup.md)대로 마이그레이션·시드를 한 뒤:

```bash
uv run uvicorn interview_assistant.main:app --reload   # 저장소 루트에서
cd frontend && npm run dev:api                         # → http://localhost:5173
```

서류 선별 화면의 "서류 업로드"로 PDF·DOCX·PPTX·HTML·HWP·HWPX·구형 .doc/.ppt·JPG/PNG를 올리면 읽기 → 비식별화 → 프로필·선별 → 표에 새 가명(CAND-0021 …)으로 들어온다. 스캔본과 사진은 관리자가 정한 읽기 방식대로 OCR로 읽는다([document-reading.md](document-reading.md)). 이름·연락처는 비식별화에만 쓰인다. 테스트용 가상 이력서는 `tests/fixtures/resumes/`에 있다.

## 검사와 빌드

```bash
npm run check        # 타입 검사 + 린트 + 테스트(Vitest) + 빌드
npm run build        # dist/ (실제 API용, VITE_USE_MOCKS=false)
npm run build:mock   # 백엔드 없이 띄우는 데모 빌드
```

## 의존성과 라이선스

- 버전은 `package.json`에 정확히 고정하고 `package-lock.json`을 커밋한다(공개 후 2주 이상 지난 버전). 의존성을 바꿀 때는 `npm install --before=<2주 전 날짜>`로 설치해 전이 의존성까지 같은 기준을 지킨다.
- 번들에 들어가는 라이브러리는 MIT·ISC·Apache-2.0·BSD 계열이고 폰트는 OFL-1.1이다.
- 빌드·테스트에만 쓰고 번들에 들어가지 않는 예외: lightningcss(MPL-2.0, Tailwind v4와 Vite의 CSS 처리), jsdom이 쓰는 mdn-data(CC0-1.0)와 @csstools/*(MIT-0), glob·minimatch·lru-cache 등(BlueOak-1.0.0).
