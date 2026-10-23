# API 계약 (프론트 ↔ 백엔드)

2026-10-23 · 초안 v0.1 · 프론트(`frontend/`)가 모의 API(MSW)로 이미 구현해 쓰고 있는 계약이다. 3~8단계 백엔드는 이 계약대로 FastAPI 라우터를 만들고, 프론트는 `npm run dev:api`로 바꿔 붙인다.

- 타입 정의 원본: [`frontend/src/api/types.ts`](../frontend/src/api/types.ts) (모델과 필드 이름·enum 값 동일)
- 모의 구현: [`frontend/src/mocks/handlers.ts`](../frontend/src/mocks/handlers.ts) (요청 검증, 오류 코드, 스트림 이벤트 순서까지 이 문서와 같다)
- 호출부: [`frontend/src/api/endpoints.ts`](../frontend/src/api/endpoints.ts), 스트림 파서 [`frontend/src/api/sse.ts`](../frontend/src/api/sse.ts)

## 1. 공통 규칙

| 항목 | 규칙 |
| --- | --- |
| 경로 | 모든 라우트는 `/api` 아래. FastAPI는 `app.include_router(router, prefix="/api")`로 마운트한다. `/health`는 그대로 둔다 |
| 형식 | JSON, 필드는 snake_case (Pydantic 필드 이름 그대로) |
| ID | UUID 문자열 (`IdMixin`) |
| 시각 | ISO 8601, UTC 오프셋 포함 (`2026-10-23T05:30:00Z`). 화면은 항상 KST로 표시한다 |
| enum | 모델 값과 동일: `PostingStatus` draft/open/closed, `ScreeningStatus` passed/hold/rejected, `SessionMode` onsite/remote, `SessionStatus` scheduled/in_progress/completed/cancelled, `InterviewerRole` lead/panel, `QuestionSource` preset/ai_suggested/interviewer, `EvaluatorType` ai/interviewer, `AvailabilitySource` manual/calendar, `ActorType` user/system/ai |
| 오류 | FastAPI 기본 형식 `{"detail": "메시지"}`. 검증 오류는 422 `{"detail": [{"loc": ["body", "field"], "msg": "...", "type": "..."}]}`. 없는 자원 404, 상태 충돌(예: 확정본 수정, 진행 중이 아닌 세션에 질문 기록) 409. 프론트는 `detail` 문자열을 그대로 토스트에 보여 주므로 한국어로 쓴다 |
| 인증 | Phase 1은 IAP + 사내 SSO 예정. 지금은 `GET /api/me`가 로그인한 면접관을 돌려준다고 가정한다. 쓰기 요청의 행위자는 서버가 세션에서 정한다 (본문으로 받지 않음) |
| 감사 로그 | 모든 쓰기 요청과 AI 호출은 `AuditLog`를 남긴다. 프론트는 `GET /api/activity`로 그중 사람이 볼 항목만 읽는다 |

### 비식별 원칙 (응답에 절대 넣지 않는 필드)

| 모델 필드 | API에서 |
| --- | --- |
| `Candidate.encrypted_identity` | 응답에 없음. 화면은 `pseudonym`(CAND-0007)만 쓴다 |
| `Application.source_file_uri` | 응답에 없음 (원본 영역) |
| `InterviewSession.recording_uri` | `has_recording: bool`로만 노출 |
| `QAItem.answer_text` | 응답에 없음. `answer_deidentified`만 노출. 수기 답변은 `answer_text`로 받아 서버가 비식별화한다 |
| `DeidMapping` 전체 | 노출하지 않음. 재식별 API는 만들지 않는다 |

프로필(`Application.profile`), 선별 근거, 전사, 꼬리질문, AI 근거 인용은 모두 비식별 텍스트다. 학교·회사는 `[학교-1]`, `[회사-2]` 같은 토큰으로 오고, 프론트는 토큰을 칩으로 그린다.

## 2. 엔드포인트

구현 단계 열은 [구현 순서](implementation-order.md)의 단계 번호다.

### 공통·대시보드

| 메서드 | 경로 | 요청 | 응답 | 단계 |
| --- | --- | --- | --- | --- |
| GET | `/api/me` | | `Interviewer` | 6 |
| GET | `/api/dashboard` | | `DashboardSummary` {pipeline[], today_sessions[], pending_my_scores[], hold_count} | 6 |
| GET | `/api/activity?limit=20` | | `ActivityItem[]` (AuditLog + actor_label, target_label), 최신순 | 3 |

### 공고·역량 사전 (FR-02)

| 메서드 | 경로 | 요청 | 응답 | 단계 |
| --- | --- | --- | --- | --- |
| GET | `/api/postings` | | `PostingSummary[]` (jd_text 제외, counts, latest/approved competency set 요약) | 4 |
| GET | `/api/postings/{id}` | | `PostingDetail` (JobPosting + counts) | 4 |
| GET | `/api/postings/{id}/competency-sets` | | `CompetencySet[]` 버전 오름차순 | 4 |
| POST | `/api/postings/{id}/competency-sets` | `{competencies: Competency[]}` | 201 `CompetencySet` (version = 최신+1, 초안) | 4 |
| POST | `/api/postings/{id}/competency-sets/generate` | | 201 `CompetencySet` AI 초안 (JD 기반, 감사 로그 actor ai) | 4 |
| PUT | `/api/competency-sets/{id}` | `{competencies}` | `CompetencySet`. 확정본이면 409 | 4 |
| POST | `/api/competency-sets/{id}/approve` | | `CompetencySet` (approved_by = 로그인 면접관 id, approved_at). 이미 확정이면 409 | 4 |

`Competency` = `{name, description, bars: {"1": "...", ..., "5": "..."}}` (`CompetencySet.competencies` JSON 그대로). 다섯 단계 모두 필수.

### 서류 선별 (FR-01, 03)

| 메서드 | 경로 | 요청 | 응답 | 단계 |
| --- | --- | --- | --- | --- |
| GET | `/api/postings/{id}/applications` | | `ApplicationRow[]` {application_id, candidate{id,pseudonym}, screening, years_experience, top_skills, stage, created_at} | 5 |
| GET | `/api/applications/{id}` | | `ApplicationDetail` {application, candidate, posting, screening, sessions[]} | 5 |
| PATCH | `/api/screenings/{id}` | `{status}` | `Screening`. 사람이 바꾼 상태, 감사 로그 `screening.status_changed` {from, to} | 5 |
| GET | `/api/candidates` | | `CandidateIndexItem[]` (명령 팔레트 검색용) | 5 |
| GET | `/api/applications/schedulable` | | `SchedulableApplication[]` 서류 통과 + 진행·예정·완료 세션 없음 | 6 |

정렬·필터는 공고당 수십 건이라 지금은 프론트에서 한다. 수백 건이 되면 `?status=&q=&sort=`를 추가한다.

`Screening.rationale`은 줄 단위 텍스트다. `+ `로 시작하면 강점, `- `로 시작하면 확인 필요, 나머지는 요약. 구조화 컬럼이 생기면 이 규칙은 버린다.

`stage` 계산: 진행 중 세션 있으면 `interviewing`, 예정 세션 있으면 `interview_scheduled`, 완료 세션이 없으면 `screening`, 완료 세션이 모두 평가 완료면 `evaluated`, 아니면 `interviewed`. 평가 완료 = AI 채점 completed + 세션 면접관 전원 제출.

### 면접 세션 (FR-04, 05, 06, 08)

| 메서드 | 경로 | 요청 | 응답 | 단계 |
| --- | --- | --- | --- | --- |
| GET | `/api/sessions?status=` | | `SessionSummary[]` (candidate, posting, interviewers, qa_count, ai_scoring, submitted_interviewer_ids) | 6 |
| POST | `/api/sessions` | `CreateSessionRequest` {application_id, mode, scheduled_at, interviewers[{interviewer_id, role}]} | 201 `SessionSummary`. 주관은 정확히 1명(422), 이미 예정·진행 중이면 409 | 6 |
| GET | `/api/sessions/{id}` | | `SessionDetail` {session, posting, card, interviewers, competency_set(확정본), preset_questions, qa_items, notes} | 6 |
| POST | `/api/sessions/{id}/consent` | `{consent_recording: bool}` | `SessionDetail`. scheduled일 때만, 아니면 409. Candidate.consent_recording/consent_at 갱신 | 6 |
| POST | `/api/sessions/{id}/start` | | `SessionDetail`. status in_progress, started_at, has_recording = 동의 여부. 동의 안 했으면 수기 모드 | 6 |
| POST | `/api/sessions/{id}/end` | | `SessionDetail`. completed, ended_at. 답변 중이던 질문은 그때까지 들은 전사로 닫고, AI 채점을 비동기로 시작 | 6, 8 |
| POST | `/api/sessions/{id}/qa-items` | `CreateQARequest` {question, question_source, preset_question_id?, suggestion?{batch_id, suggestion_id, edited, original_question}} | 201 `QAItem` (seq = 마지막+1). in_progress가 아니면 409 | 6, 7 |
| PATCH | `/api/qa-items/{id}` | `{answer_text}` | `QAItem` (answer_deidentified, answered_at). 수기 모드·STT 장애 시 | 6 |
| POST | `/api/sessions/{id}/notes` | `{content}` | 201 `CandidateNote` (author = 로그인 면접관) | 6 |
| GET | `/api/sessions/{id}/transcript` | | `{segments: TranscriptSegment[]}` 확정 구간만 | 10, 11 |
| GET | `/api/sessions/{id}/transcript/stream` | | SSE (3장) | 11 |
| POST | `/api/sessions/{id}/follow-ups` | `{qa_item_id}` | SSE (3장) | 7 |

`SessionDetail.card` (FR-04 지원자 요약 카드) = {candidate{id, pseudonym, consent_recording, consent_at}, profile, screening{fit_score, status, rationale}, previous_sessions[]}.

꼬리질문은 제안일 뿐이다 (FR-06). 프론트는 면접관이 "이 질문 사용" 또는 "수정 후 사용"을 눌렀을 때만 `POST qa-items`를 `question_source: ai_suggested`와 `suggestion`으로 보낸다. 고친 경우 `edited: true`, `original_question`은 AI 원문. 직접 입력은 `interviewer`, 사전 질문은 `preset` + `preset_question_id`.

### 평가 (FR-07, 08)

| 메서드 | 경로 | 요청 | 응답 | 단계 |
| --- | --- | --- | --- | --- |
| GET | `/api/sessions/{id}/evaluation` | | `Evaluation` {session, candidate, posting, competency_set, qa_items, ai{status, model, prompt_version, samples, scores[], summary[]}, interviewers[{interviewer, role, submitted_at, scores[]}]} | 8 |
| PUT | `/api/sessions/{id}/scores/{interviewer_id}` | `{scores: [{competency, score(1~5 정수), comment}]}` | `Evaluation`. 확정 역량 전부 필요(422), completed 아니면 409, 패널이 아니면 409. 같은 면접관의 이전 점수는 교체 | 8 |

- AI 점수와 면접관 점수는 같은 `Score` 테이블, `evaluator_type`으로 나눈다. API는 둘을 다른 필드(`ai.scores`, `interviewers[].scores`)로 주고, 둘을 섞은 값(합계, 평균, 가중 평균)은 어디에도 내려보내지 않는다.
- `ai.summary[]` = 역량별 AI 항목 점수의 평균(소수 1자리)과 그중 가장 낮은 신뢰도, 항목 수. AI 점수만 들어간다. 프론트 `lib/scoring.ts`의 `summarizeAiScores`와 같은 규칙이다.
- AI 점수는 `evidence`(비식별 답변에서 그대로 인용한 문장)와 `confidence`가 반드시 있다. 근거가 없는 역량은 summary에서 빠지고 화면에 "근거 없음"으로 나온다.
- `ai.status`: not_started / running / completed / failed. running이면 프론트가 2초마다 다시 읽는다. 목표: 종료 후 10분 이내 completed.
- 면접관 코멘트는 `Score.evidence`에 저장한다 (면접관 점수는 confidence/model 없음).

### 면접관 스케줄 (FR-09)

| 메서드 | 경로 | 요청 | 응답 | 단계 |
| --- | --- | --- | --- | --- |
| GET | `/api/interviewers` | | `Interviewer[]` | 후순위 |
| GET | `/api/availabilities?from=&to=` | | `Availability[]` 구간과 겹치는 것 | 후순위 |
| POST | `/api/availabilities` | `{interviewer_id, start_at, end_at}` | 201 `Availability` (source manual). end ≤ start면 422 | 후순위 |
| DELETE | `/api/availabilities/{id}` | | 204 | 후순위 |
| POST | `/api/schedule/suggestions` | `{interviewer_ids, from, to, duration_minutes, min_interviewers?}` | `ScheduleSuggestion[]` {start_at, end_at, interviewer_ids} 최대 8개, 이른 순 | 후순위 |

후보 계산: 선택한 면접관 중 `min_interviewers`명 이상이 동시에 비는 구간을 구하고, 30분 단위로 맞춘 `duration_minutes` 슬롯을 낸다. 과거 시각은 제외. 프론트 `lib/schedule.ts`의 `commonFreeIntervals`/`suggestSlots`와 같은 규칙이고, 그리드의 "공통 빈 시간" 표시는 프론트가 같은 함수로 그린다.

## 3. 스트리밍: SSE로 정한 이유와 이벤트 형식

실시간 전사와 꼬리질문 둘 다 **SSE (text/event-stream)**로 한다. WebSocket은 쓰지 않는다.

- 방향이 서버 → 브라우저 한쪽뿐이다. 브라우저 → 서버는 질문 기록, 답변 저장 같은 이산 이벤트라 일반 POST가 맞다. 오디오는 11단계에서 LiveKit(WebRTC)으로 따로 흐르므로 앱 서버에 양방향 소켓이 필요 없다.
- 꼬리질문은 요청 1건 = 응답 스트림 1개(LLM 토큰 스트림)라 HTTP 요청-응답 모델과 그대로 맞는다. 요청마다 감사 로그 1건, 요청 단위 인증·타임아웃·취소(AbortController)가 자연스럽다.
- Cloud Run, IAP, 사내 프록시를 일반 HTTP로 통과한다. WebSocket은 업그레이드·유휴 타임아웃·IAP 설정을 따로 챙겨야 한다.
- FastAPI `StreamingResponse`(또는 sse-starlette)와 Anthropic SDK 스트림을 이벤트로 바꾸기만 하면 된다. 끊기면 `GET /transcript`로 확정 구간을 다시 받고 스트림에 재접속한다.
- 프론트는 EventSource 대신 fetch + ReadableStream 파서(`api/sse.ts`)를 쓴다. POST 본문과 인증 헤더를 실을 수 있고, 모의 API(MSW)와 테스트(jsdom)에서도 같은 코드가 돈다.

응답 헤더: `Content-Type: text/event-stream`, `Cache-Control: no-cache`. 프록시 버퍼링을 끈다(`X-Accel-Buffering: no`). 각 메시지는 `event:`와 JSON 한 줄 `data:`.

### 3.1 전사 스트림 `GET /api/sessions/{id}/transcript/stream`

```
event: status
data: {"recording":"recording","stt":"ok","latency_ms":320}

event: segment.partial
data: {"segment_id":"…","qa_item_id":"…","speaker":"candidate","text":"산포가 커지면 먼저 관리도","is_final":false,"start_ms":781000,"end_ms":null}

event: segment.final
data: {"segment_id":"…","qa_item_id":"…","speaker":"candidate","text":"산포가 커지면 먼저 관리도에서 언제부터 바뀌었는지 시간 축으로 확인합니다.","is_final":true,"start_ms":781000,"end_ms":786400}

event: qa.answered
data: {"qa_item_id":"…","answer_deidentified":"…","answered_at":"2026-10-23T00:51:10Z"}
```

- `text`는 비식별 텍스트다 (스트리밍 STT 결과를 `Deidentifier`에 통과시킨 뒤 보낸다).
- partial은 같은 `segment_id`의 전체 텍스트를 매번 다시 보낸다 (덮어쓰기). final이 오면 그 구간은 확정이다. 프론트는 partial을 흐리게, final을 진하게 그린다.
- `start_ms`/`end_ms`는 세션 시작 기준 경과 ms. `speaker`는 interviewer/candidate (비대면은 참가자 트랙, 대면은 화자분리 결과).
- 면접관이 질문을 기록하면 서버는 그 질문을 interviewer 구간으로 보내고, 지원자 답변이 끝났다고 판단하면(침묵 감지 또는 다음 질문 기록) `qa.answered`로 그 QAItem의 답변을 닫는다. 프론트는 `qa.answered`를 받으면 꼬리질문을 요청한다.
- `status`는 접속 직후와 주기적으로(약 5초) 보낸다. `recording`: recording/paused/stopped/off, `stt`: ok/degraded/down/off. STT가 죽으면 `stt: down`을 보내고, 프론트는 수기 답변 입력을 연다 (비기능 요구: 녹음은 계속, UI는 수기 모드).
- 수기 모드(동의 없음)에서는 프론트가 이 스트림을 열지 않는다.

### 3.2 꼬리질문 스트림 `POST /api/sessions/{id}/follow-ups` `{qa_item_id}`

```
event: batch.start
data: {"batch_id":"…","qa_item_id":"…","model":"claude-opus-5-5","prompt_version":"followup-v0.2"}

event: suggestion.start
data: {"batch_id":"…","suggestion_id":"…","index":0,"competency":"데이터 기반 분석"}

event: suggestion.delta
data: {"batch_id":"…","suggestion_id":"…","text":"상단 슬롯 "}

event: suggestion.done
data: {"batch_id":"…","suggestion_id":"…","index":0,"competency":"데이터 기반 분석","question":"…","rationale":"원인 확정 과정의 검증 깊이를 확인합니다.","grounding":"상단 존 온도 편차가 커져 있었고, 히터 보정 후 산포가 원래 수준으로 돌아왔습니다"}

event: batch.done
data: {"batch_id":"…"}
```

- 한 배치에 후보 2~3개. 후보마다 start → delta 여러 개 → done 순서. 첫 delta는 요청 후 2초 안(성능 목표).
- `grounding`은 비식별 답변에서 그대로 따온 문장이어야 한다 (프론트가 인용으로 표시). `rationale`은 생성 근거(FR-06 저장 대상).
- 오류는 `event: error` `{"message": "…"}` 후 스트림 종료. 답변이 없는 QA면 바로 error.
- 클라이언트가 연결을 끊으면(새 요청, 화면 이탈) 서버는 LLM 호출을 취소한다.
- 프론트는 받은 후보를 자동으로 질문으로 만들지 않는다.

## 4. 모델에 아직 없는 것 (백엔드 단계에서 결정)

프론트 계약이 요구하지만 현재 `models/`에 자리가 없는 항목이다. 마이그레이션으로 추가하거나 저장 방식을 정해야 한다.

| 항목 | 계약에서 | 제안 | 단계 |
| --- | --- | --- | --- |
| 사전 질문 세트 | `SessionDetail.preset_questions[]` {id, competency, question, intent} | `preset_questions` 테이블(competency_set_id FK) 또는 CompetencySet JSON에 포함 | 7 |
| 꼬리질문 후보(채택·미채택)와 생성 근거 | follow-ups 스트림, `CreateQARequest.suggestion` | `follow_up_suggestions` 테이블(batch_id, qa_item_id, competency, question, rationale, grounding, used_qa_item_id, edited). FR-06 "선택 여부, 생성 근거 전부 저장" | 7 |
| QAItem의 출처 연결 | `preset_question_id`, `suggestion_id`, `edited`, 대상 역량 | QAItem에 `preset_question_id`, `suggestion_id`, `target_competency` 컬럼 | 7 |
| 전사 구간 | `TranscriptSegment` (speaker, start_ms, end_ms, 비식별 text) | `transcript_segments` 테이블. 원문 구간은 원본 영역, 비식별 구간만 API로 | 10, 11 |
| 면접관 세션 단위 역량 점수 | `PUT scores/{interviewer_id}` 역량별 1개 | `Score.qa_item_id`가 NOT NULL이라 모의 API는 그 역량을 다룬 첫 QA에 붙인다. `qa_item_id` nullable + `session_id` 추가 검토 | 8 |
| 면접관 제출 시각 | `InterviewerEvaluation.submitted_at` | `SessionInterviewer.submitted_at` 컬럼 | 8 |
| AI 채점 상태 | `Evaluation.ai.status` | 작업 테이블 또는 `InterviewSession.ai_scoring_status` | 8 |
| `CompetencySet.approved_by` 의미 | 확정한 면접관 id (프론트가 이름으로 바꿔 표시) | SSO 사용자 id로 통일 | 4 |
| 예약된 면접과 가용 시간 | 스케줄 후보 | 확정된 세션 시간은 가용 시간에서 빼야 한다 (모의 API는 빼지 않음) | 후순위 |
| 숨은 텍스트·지시문 플래그 | 선별 근거 화면 | 5단계에서 hidden 블록 처리 결정 후 `ApplicationDetail`에 플래그 추가 | 5 |
