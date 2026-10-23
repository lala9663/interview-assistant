# API 계약 (프론트 ↔ 백엔드)

2026-10-23 · v0.2 · 프론트(`frontend/`)가 모의 API(MSW)로 먼저 쓰던 계약을 백엔드(FastAPI, `src/interview_assistant/api/`)가 그대로 구현했다. 모든 경로가 동작하고, AI는 Provider 인터페이스를 거쳐 fake provider로 돈다(`config/providers.fake.yaml`). 프론트는 `npm run dev:api`로 실제 API에 붙는다. 실제 모델 연결과 품질 검증은 남은 과제다(5장).

- 타입 정의 원본: [`frontend/src/api/types.ts`](../frontend/src/api/types.ts) (모델과 필드 이름·enum 값 동일). 백엔드 응답 스키마: [`api/schemas.py`](../src/interview_assistant/api/schemas.py) (필드 단위로 같다. `tests/test_api_contract.py`가 enum과 이 문서의 경로 목록을 대조한다)
- 모의 구현: [`frontend/src/mocks/handlers.ts`](../frontend/src/mocks/handlers.ts) (요청 검증, 오류 코드, 스트림 이벤트 순서까지 이 문서와 같다)
- 호출부: [`frontend/src/api/endpoints.ts`](../frontend/src/api/endpoints.ts), 스트림 파서 [`frontend/src/api/sse.ts`](../frontend/src/api/sse.ts)

## 1. 공통 규칙

| 항목 | 규칙 |
| --- | --- |
| 경로 | 모든 라우트는 `/api` 아래. 라우터는 기능별(`api/routes/`: dashboard, postings, screening, sessions, live, evaluation, schedule)로 나누고 `/api`로 마운트한다. `/health`는 그대로 둔다 |
| 형식 | JSON, 필드는 snake_case (Pydantic 필드 이름 그대로). 업로드만 multipart/form-data |
| ID | UUID 문자열 (`IdMixin`) |
| 시각 | 응답은 UTC, 밀리초, `Z` (`2026-10-23T05:30:00.000Z`, JavaScript `toISOString`과 같은 모양). 요청의 시각은 오프셋이 있어야 한다(없으면 422). 화면은 항상 KST로 표시한다 |
| enum | 모델 값과 동일: `PostingStatus` draft/open/closed, `ScreeningStatus` passed/hold/rejected, `SessionMode` onsite/remote, `SessionStatus` scheduled/in_progress/completed/cancelled, `InterviewerRole` lead/panel, `QuestionSource` preset/ai_suggested/interviewer, `EvaluatorType` ai/interviewer, `AvailabilitySource` manual/calendar, `ActorType` user/system/ai |
| 오류 | FastAPI 기본 형식 `{"detail": "메시지"}`. 검증 오류는 422 `{"detail": [{"loc": ["body", "field"], "msg": "...", "type": "..."}]}` (Pydantic 기본 메시지도 한국어로 바꿔 보낸다). 없는 자원 404, 상태 충돌(예: 확정본 수정, 진행 중이 아닌 세션에 질문 기록) 409, AI 응답을 쓸 수 없거나 가드가 호출을 막으면 502, 암호화 키가 없어 비식별화를 못 하면 503. 프론트는 `detail` 문자열을 그대로 토스트에 보여 주므로 한국어로 쓴다 |
| 인증 | Phase 1은 IAP + 사내 SSO 예정(남은 과제). 지금은 `IA_DEV_INTERVIEWER`(사번)의 면접관, 없으면 가장 먼저 등록된 면접관이 로그인한 사람이다. 쓰기 요청의 행위자는 서버가 정한다 (본문으로 받지 않음) |
| 감사 로그 | 모든 쓰기 요청과 AI 호출은 `AuditLog`를 남긴다. AI 호출은 성공·실패·가드 거부 모두 한 줄씩(모델, 프롬프트 버전, 토큰 수). 프롬프트와 응답 본문은 남기지 않는다. 프론트는 `GET /api/activity`로 그중 사람이 볼 항목만 읽는다(`api/views.py`의 `FEED_ACTIONS`) |

### 비식별 원칙 (응답에 절대 넣지 않는 필드)

| 모델 필드 | API에서 |
| --- | --- |
| `Candidate.encrypted_identity` | 응답에 없음. 화면은 `pseudonym`(CAND-0007)만 쓴다 |
| `Application.source_file_uri` | 응답에 없음 (원본 영역, `uploads/`) |
| `InterviewSession.recording_uri` | `has_recording: bool`로만 노출 |
| `QAItem.answer_text` | 응답에 없음. `answer_deidentified`만 노출. 수기 답변은 `answer_text`로 받아 서버가 비식별화한다 |
| `DeidMapping` 전체 | 노출하지 않음. 재식별 API는 만들지 않는다 |

프로필(`Application.profile`), 선별 근거, 전사, 꼬리질문, AI 근거 인용은 모두 비식별 텍스트다. 학교·회사는 `[학교-1]`, `[회사-2]` 같은 토큰으로 오고, 프론트는 토큰을 칩으로 그린다.

사람이 API로 보내는 자유 텍스트도 저장 전에 비식별화한다: 직접 입력한 질문(`QAItem.question`), 수기 답변, 메모(`CandidateNote.content`), 면접관 코멘트(`Score.evidence`), 업로드 서류. 면접관이 지원자 이름을 적어도 화면과 AI에는 `[지원자]`로 간다. `tests/test_api_privacy.py`가 이름·연락처·원문 답변·원본 경로·녹음 경로가 어느 응답에도, 어느 프롬프트에도 없는지 검사한다.

### AI 호출 원칙

- 업무 코드는 `ai/gateway.py`의 `AiGateway`만 부른다. 모델은 역할(`primary`, `screening`)로 `config/providers.yaml`에서 고르므로, 실제 모델로 바꾸는 것은 설정 변경이다.
- 프롬프트는 비식별 필드로만 만든다. 그래도 호출 직전에 가드(`ai/guard.py`)가 지원자 텍스트에 그 지원자의 이름·연락처·학교·회사가 남았는지, 전화·이메일·주민번호 모양이 있는지 다시 보고, 남았으면 호출하지 않는다(감사 로그에 거부 사유 범주만).
- 프롬프트는 입력을 태그(`<answer>…</answer>`)로 감싸고, 태그 안 지시문은 따르지 않게 한다. 버전은 `ai/prompts.py`(competency-v0.2, profile-v0.1, screening-v0.4, followup-v0.2, score-v0.3).

## 2. 엔드포인트

구현 단계 열은 [구현 순서](implementation-order.md)의 단계 번호다. 전부 fake provider로 구현되어 있다.

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
| POST | `/api/postings/{id}/competency-sets/generate` | | 201 `CompetencySet` AI 초안 (JD 기반, 최신 버전이 있으면 그것을 다듬음, 감사 로그 actor ai) | 4 |
| PUT | `/api/competency-sets/{id}` | `{competencies}` | `CompetencySet`. 확정본이면 409 | 4 |
| POST | `/api/competency-sets/{id}/approve` | | `CompetencySet` (approved_by = 로그인 면접관 id, approved_at). 이미 확정이면 409. 직전 확정본의 사전 질문 중 역량이 남은 것을 옮겨 붙인다 | 4 |

`Competency` = `{name, description, bars: {"1": "...", ..., "5": "..."}}` (`CompetencySet.competencies` JSON 그대로). 다섯 단계 모두 필수.

### 서류 선별 (FR-01, 03)

| 메서드 | 경로 | 요청 | 응답 | 단계 |
| --- | --- | --- | --- | --- |
| GET | `/api/postings/{id}/applications` | | `ApplicationRow[]` {application_id, candidate{id,pseudonym}, screening, years_experience, top_skills, stage, created_at} | 5 |
| POST | `/api/postings/{id}/applications` | multipart: `file`, `name`(필수), `phone`, `email`, `birthdate`, `aliases`, `addresses`, `schools`, `companies` (여러 값은 줄바꿈) | 201 `UploadResult` {application_id, candidate{id,pseudonym}, screening, document} | 5 |
| GET | `/api/applications/{id}` | | `ApplicationDetail` {application, candidate, posting, screening, sessions[], document} | 5 |
| PATCH | `/api/screenings/{id}` | `{status}` | `Screening`. 사람이 바꾼 상태, 감사 로그 `screening.status_changed` {from, to} | 5 |
| GET | `/api/candidates` | | `CandidateIndexItem[]` (명령 팔레트 검색용) | 5 |
| GET | `/api/applications/schedulable` | | `SchedulableApplication[]` 서류 통과 + 진행·예정·완료 세션 없음 | 6 |

정렬·필터는 공고당 수십 건이라 지금은 프론트에서 한다. 수백 건이 되면 `?status=&q=&sort=`를 추가한다.

`Screening.rationale`은 줄 단위 텍스트다. `+ `로 시작하면 강점, `- `로 시작하면 확인 필요, 나머지는 요약. 구조화 컬럼이 생기면 이 규칙은 버린다.

`stage` 계산: 진행 중 세션 있으면 `interviewing`, 예정 세션 있으면 `interview_scheduled`, 완료 세션이 없으면 `screening`, 완료 세션이 모두 평가 완료면 `evaluated`, 아니면 `interviewed`. 평가 완료 = AI 채점 completed + 세션 면접관 전원 제출.

**업로드** (`POST /api/postings/{id}/applications`, 프론트 서류 선별 화면의 "서류 업로드"):

1. 파일(최대 10MB)을 형식 판별 후 텍스트 추출(`documents/`, PDF·DOCX·PPTX·HTML). HWP·구형 오피스는 422, 스캔본(텍스트 레이어 없는 쪽)은 OCR이 없어 422로 거부하고 아무것도 남기지 않는다.
2. 양식 값(이름 등)을 `KnownIdentity`로 `Candidate.encrypted_identity`에 봉인하고 새 가명(CAND-0021 …)을 붙인다. 이 값은 비식별화에만 쓰인다.
3. 파일명·속성·본문·표·머리글·노트·링크·숨은 텍스트까지 블록 단위로 비식별화한다. 숨은 텍스트 블록(흰 글씨, 0.5pt, `display:none` 등)은 키워드 채우기·지시문 주입 위험이 있어 선별 프롬프트에서 뺀다. 개수만 `document.hidden_blocks`로 알려 준다.
4. `screening` 역할 모델로 두 번 호출한다: 프로필 구조화(profile-v0.1) → JD·확정 역량 사전 기준 평가(screening-v0.4). 응답은 스키마로 검증하고, 형식이 틀리면 502로 전체를 되돌린다(실패도 감사 로그).
5. 원본 파일은 `uploads/{candidate_id}/{application_id}.{확장자}`에 저장한다(파일 이름에 실명 없음, git 제외, 서빙하지 않음). `Application.source_file_uri`에만 경로가 남는다.
6. 선별 상태는 AI 권고와 관계없이 `hold`로 시작한다. 통과·보류·탈락은 사람이 정하고(PATCH), AI 권고는 근거 첫 줄 끝 `(AI 권고: 통과)`에 적는다.

`document` = `{format, blocks, hidden_blocks, images_dropped, replacements}` (개수만, 텍스트 없음). 시드 지원자는 파일이 없어 `null`이다.

### 면접 세션 (FR-04, 05, 06, 08)

| 메서드 | 경로 | 요청 | 응답 | 단계 |
| --- | --- | --- | --- | --- |
| GET | `/api/sessions?status=` | | `SessionSummary[]` (candidate, posting, interviewers, qa_count, ai_scoring, submitted_interviewer_ids) | 6 |
| POST | `/api/sessions` | `CreateSessionRequest` {application_id, mode, scheduled_at, interviewers[{interviewer_id, role}]} | 201 `SessionSummary`. 주관은 정확히 1명(422), 이미 예정·진행 중이면 409 | 6 |
| GET | `/api/sessions/{id}` | | `SessionDetail` {session, posting, card, interviewers, competency_set(세션에 고정된 확정본), preset_questions, qa_items, notes} | 6 |
| POST | `/api/sessions/{id}/consent` | `{consent_recording: bool}` | `SessionDetail`. scheduled일 때만, 아니면 409. Candidate.consent_recording/consent_at 갱신 | 6 |
| POST | `/api/sessions/{id}/start` | | `SessionDetail`. status in_progress, started_at, 그때의 확정 역량 사전을 세션에 고정, has_recording = 동의 여부. 동의 안 했으면 수기 모드 | 6 |
| POST | `/api/sessions/{id}/end` | | `SessionDetail`. completed, ended_at. 답변 중이던 질문은 그때까지 들은 전사로 닫고, AI 채점을 백그라운드로 시작 | 6, 8 |
| POST | `/api/sessions/{id}/qa-items` | `CreateQARequest` {question, question_source, preset_question_id?, suggestion?{batch_id, suggestion_id, edited, original_question}} | 201 `QAItem` (seq = 마지막+1). in_progress가 아니면 409. 다른 세션의 사전 질문·모르는 제안이면 422, 이미 쓴 제안이면 409 | 6, 7 |
| PATCH | `/api/qa-items/{id}` | `{answer_text}` | `QAItem` (answer_deidentified, answered_at). 수기 모드·STT 장애 시. in_progress가 아니면 409 | 6 |
| POST | `/api/sessions/{id}/notes` | `{content}` | 201 `CandidateNote` (author = 로그인 면접관, 내용은 비식별화) | 6 |
| GET | `/api/sessions/{id}/transcript` | | `{segments: TranscriptSegment[]}` 확정 구간만 | 10, 11 |
| GET | `/api/sessions/{id}/transcript/stream` | | SSE (3장) | 11 |
| POST | `/api/sessions/{id}/follow-ups` | `{qa_item_id}` | SSE (3장) | 7 |

`SessionDetail.card` (FR-04 지원자 요약 카드) = {candidate{id, pseudonym, consent_recording, consent_at}, profile, screening{fit_score, status, rationale}, previous_sessions[]}.

꼬리질문은 제안일 뿐이다 (FR-06). 프론트는 면접관이 "이 질문 사용" 또는 "수정 후 사용"을 눌렀을 때만 `POST qa-items`를 `question_source: ai_suggested`와 `suggestion`으로 보낸다. 고친 경우 `edited: true`, `original_question`은 AI 원문. 직접 입력은 `interviewer`, 사전 질문은 `preset` + `preset_question_id`. 서버는 제안 행에 쓰인 질문과 수정 여부를 기록하고(`FollowUpSuggestion.used_qa_item_id`, `edited`), 질문에 대상 역량(`QAItem.target_competency`)을 붙인다.

### 평가 (FR-07, 08)

| 메서드 | 경로 | 요청 | 응답 | 단계 |
| --- | --- | --- | --- | --- |
| GET | `/api/sessions/{id}/evaluation` | | `Evaluation` {session, candidate, posting, competency_set, qa_items, ai{status, model, prompt_version, samples, scores[], summary[]}, interviewers[{interviewer, role, submitted_at, scores[]}]} | 8 |
| PUT | `/api/sessions/{id}/scores/{interviewer_id}` | `{scores: [{competency, score(1~5 정수), comment}]}` | `Evaluation`. 확정 역량 전부 필요(422), 역량에 없는 이름 422, completed 아니면 409, 패널이 아니면 409. 같은 면접관의 이전 점수는 교체 | 8 |

- AI 점수와 면접관 점수는 같은 `Score` 테이블, `evaluator_type`으로 나눈다. API는 둘을 다른 필드(`ai.scores`, `interviewers[].scores`)로 주고, 둘을 섞은 값(합계, 평균, 가중 평균)은 어디에도 내려보내지 않는다.
- AI 점수는 답변(QA) 단위라 `qa_item_id`가 있고, 면접관 점수는 세션·역량 단위라 `qa_item_id`가 `null`이다(4장).
- `ai.summary[]` = 역량별 AI 항목 점수의 평균(소수 1자리, 반올림)과 그중 가장 낮은 신뢰도, 항목 수. AI 점수만 들어간다. 프론트 `lib/scoring.ts`의 `summarizeAiScores`와 같은 규칙이다.
- AI 채점: 답변마다 같은 프롬프트로 3회(`samples`) 부르고, 역량이 사전에 있고 1~5점이고 근거(`evidence`)가 비식별 답변에서 그대로 복사한 문장인 샘플만 쓴다(근거 없는 점수 거부). 점수는 유효 샘플의 중앙값, 신뢰도는 샘플 자기 신뢰도 평균 × (1 − 점수 폭/4) × (유효 샘플 수/3). 유효 샘플이 없는 답변·역량은 점수가 없고 화면에 "근거 없음"으로 나온다.
- `ai.status`: not_started / running / completed / failed. running이면 프론트가 2초마다 다시 읽는다. 서버가 재시작되면 running인 채점을 다시 돌린다. 목표: 종료 후 10분 이내 completed.
- 면접관 코멘트는 `Score.evidence`에 비식별화해 저장한다 (면접관 점수는 confidence/model 없음).

### 면접관 스케줄 (FR-09)

| 메서드 | 경로 | 요청 | 응답 | 단계 |
| --- | --- | --- | --- | --- |
| GET | `/api/interviewers` | | `Interviewer[]` | 후순위 |
| GET | `/api/availabilities?from=&to=` | | `Availability[]` 구간과 겹치는 것 | 후순위 |
| POST | `/api/availabilities` | `{interviewer_id, start_at, end_at}` | 201 `Availability` (source manual). end ≤ start면 422 | 후순위 |
| DELETE | `/api/availabilities/{id}` | | 204 | 후순위 |
| POST | `/api/schedule/suggestions` | `{interviewer_ids, from, to, duration_minutes, min_interviewers?}` | `ScheduleSuggestion[]` {start_at, end_at, interviewer_ids} 최대 8개, 이른 순 | 후순위 |

후보 계산: 선택한 면접관 중 `min_interviewers`명 이상이 동시에 비는 구간을 구하고, 30분 단위로 맞춘 `duration_minutes` 슬롯을 낸다. 과거 시각은 제외. 프론트 `lib/schedule.ts`의 `commonFreeIntervals`/`suggestSlots`와 같은 규칙이고(`schedule.py`), 그리드의 "공통 빈 시간" 표시는 프론트가 같은 함수로 그린다. 서버는 여기에 더해 예정·진행 중인 면접 시간(시작부터 60분)을 그 면접관의 빈 시간에서 뺀다. 그리드는 가용 시간 원본을 그리므로 잡힌 면접 칸도 비어 보인다(남은 과제).

## 3. 스트리밍: SSE로 정한 이유와 이벤트 형식

실시간 전사와 꼬리질문 둘 다 **SSE (text/event-stream)**로 한다. WebSocket은 쓰지 않는다.

- 방향이 서버 → 브라우저 한쪽뿐이다. 브라우저 → 서버는 질문 기록, 답변 저장 같은 이산 이벤트라 일반 POST가 맞다. 오디오는 11단계에서 LiveKit(WebRTC)으로 따로 흐르므로 앱 서버에 양방향 소켓이 필요 없다.
- 꼬리질문은 요청 1건 = 응답 스트림 1개(LLM 토큰 스트림)라 HTTP 요청-응답 모델과 그대로 맞는다. 요청마다 감사 로그 1건, 요청 단위 인증·타임아웃·취소(AbortController)가 자연스럽다.
- Cloud Run, IAP, 사내 프록시를 일반 HTTP로 통과한다. WebSocket은 업그레이드·유휴 타임아웃·IAP 설정을 따로 챙겨야 한다.
- FastAPI `StreamingResponse`와 모델 스트림을 이벤트로 바꾸기만 하면 된다. 끊기면 `GET /transcript`로 확정 구간을 다시 받고 스트림에 재접속한다.
- 프론트는 EventSource 대신 fetch + ReadableStream 파서(`api/sse.ts`)를 쓴다. POST 본문과 인증 헤더를 실을 수 있고, 모의 API(MSW)와 테스트(jsdom)에서도 같은 코드가 돈다.

응답 헤더: `Content-Type: text/event-stream`, `Cache-Control: no-cache`. 프록시 버퍼링을 끈다(`X-Accel-Buffering: no`). 각 메시지는 `event:`와 JSON 한 줄 `data:`.

### 3.1 전사 스트림 `GET /api/sessions/{id}/transcript/stream`

```
event: status
data: {"recording":"recording","stt":"ok","latency_ms":3}

event: segment.partial
data: {"segment_id":"…","qa_item_id":"…","speaker":"candidate","text":"산포가 커지면 먼저 관리도에서","is_final":false,"start_ms":781000,"end_ms":null}

event: segment.final
data: {"segment_id":"…","qa_item_id":"…","speaker":"candidate","text":"산포가 커지면 먼저 관리도에서 언제부터 바뀌었는지 시간 축으로 확인합니다.","is_final":true,"start_ms":781000,"end_ms":786400}

event: qa.answered
data: {"qa_item_id":"…","answer_deidentified":"…","answered_at":"2026-10-23T00:51:10.000Z"}
```

- `text`는 비식별 텍스트다. 스트리밍 STT 결과를 `Deidentifier`에 통과시킨 뒤 보낸다(`live/hub.py`).
- partial은 같은 `segment_id`의 전체 텍스트를 매번 다시 보낸다 (덮어쓰기). final이 오면 그 구간은 확정이고 `transcript_segments`에 저장된다(partial은 저장하지 않음). 프론트는 partial을 흐리게, final을 진하게 그린다.
- partial은 마지막 어절과, 끝에 붙은 숫자·`@`가 든 어절을 빼고 보낸다. 반쯤 들린 이름("홍길")이나 전화번호("010 1234")는 탐지기가 못 잡기 때문이다. 그래서 partial은 글자 단위가 아니라 어절 단위로 자란다. final은 통째로 비식별화한다.
- `start_ms`/`end_ms`는 세션 시작 기준 경과 ms. `speaker`는 interviewer/candidate (비대면은 참가자 트랙, 대면은 화자분리 결과).
- 면접관이 질문을 기록하면 서버는 그 질문을 interviewer 구간으로 보내고 지원자 답변을 듣기 시작한다. 답변이 끝났다고 판단하면(STT 스트림 종료 = 침묵, 또는 다음 질문 기록, 세션 종료) `qa.answered`로 그 QAItem의 답변을 닫는다. 원문은 `answer_text`(원본 영역), 비식별본은 `answer_deidentified`. 프론트는 `qa.answered`를 받으면 꼬리질문을 요청한다.
- 스트림에 접속할 때 아직 답이 없는 마지막 질문이 있으면(재접속, 서버 재시작) 다시 듣는다.
- `status`는 접속 직후와 주기적으로(5초) 보낸다. `recording`: recording/paused/stopped/off, `stt`: ok/degraded/down/off. `latency_ms`는 STT 결과를 받은 뒤 비식별화해 내보내기까지 걸린 시간. STT가 죽으면 `stt: down`을 보내고, 프론트는 수기 답변 입력을 연다 (비기능 요구: 녹음은 계속, UI는 수기 모드).
- 세션이 끝나면 `status`(stopped)를 보내고 스트림을 닫는다. 진행 중이 아닌 세션에 접속하면 `status` 하나로 끝난다.
- 수기 모드(동의 없음)에서는 프론트가 이 스트림을 열지 않는다.
- 오디오: 11단계(LiveKit) 전까지는 `live/audio.py`의 `ScriptedCandidate`가 지원자 마이크를 흉내 낸다. 데모 데이터의 대본 답변을 문장 단위 텍스트로 보내고, fake STT가 이를 받아 적는다. 실제 STT provider에는 실제 오디오 소스가 필요하다. 속도는 `IA_DEMO_SPEED`(1 = 프론트 모의 모드와 비슷).
- 상태(구독자, 듣는 중인 질문)는 프로세스 메모리에 있다. 워커를 여러 개 띄우려면 공유 버스가 필요하다(남은 과제).

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
- 모델은 후보를 태그 블록(`<suggestion><competency>…</competency><question>…</question><rationale>…</rationale><grounding>…</grounding></suggestion>`)으로 쓰고, 서버가 토큰 스트림을 받는 대로 이벤트로 바꾼다(`ai/followups.py`의 `SuggestionParser`, 태그가 청크 경계에서 잘려도 같은 결과). 역량 이름이 사전에 없으면 질문의 대상 역량으로 바꾼다.
- `grounding`은 비식별 답변에서 그대로 따온 문장이어야 한다 (프론트가 인용으로 표시). 모델이 바꿔 쓴 인용이면 서버가 답변에서 가장 비슷한 문장으로 바꾼다. `rationale`은 생성 근거.
- 다 만든 후보는 쓰이든 안 쓰이든 모두 `follow_up_suggestions`에 저장한다 (FR-06 "선택 여부, 생성 근거 전부 저장").
- 오류는 `event: error` `{"message": "…"}` 후 스트림 종료. 답변이 없는 QA면 바로 error.
- 클라이언트가 연결을 끊으면(새 요청, 화면 이탈) 서버는 모델 스트림을 닫아 호출을 취소한다.
- 프론트는 받은 후보를 자동으로 질문으로 만들지 않는다.

## 4. 모델 결정 (Alembic 0003)

프론트 계약이 요구했지만 1단계 모델에 자리가 없던 항목을 `migrations/versions/0003_api_support.py`로 채웠다. 모델은 17개(업무정의서 6장 13개 + 비식별 역매핑 + 아래 3개)다.

| 항목 | 결정 | 이유 |
| --- | --- | --- |
| 사전 질문 세트 | `preset_questions` 테이블 (competency_set_id FK, position, competency, question, intent) | 질문은 특정 버전의 역량을 겨냥해 쓰므로 버전에 묶는다. CompetencySet JSON에 넣으면 질문 id가 없어 QA와 연결할 수 없다. 새 버전을 확정하면 역량이 남은 질문을 옮겨 붙인다 |
| 꼬리질문 후보(채택·미채택)와 생성 근거 | `follow_up_suggestions` 테이블 (id = suggestion_id, batch_id, qa_item_id, position, competency, question, rationale, grounding, model, prompt_version, used_qa_item_id, edited, used_at) | FR-06은 선택 여부와 생성 근거를 모두 남기라고 한다. 배치 테이블을 따로 두지 않고 행마다 batch_id·모델·버전을 둔다(배치 단위 조회만 필요). 선택 기록은 제안 쪽(`used_qa_item_id`)에 두어 QA ↔ 제안 순환 FK를 피한다. 수정 사용이면 AI 원문은 제안에, 고친 문장은 QA에 남는다 |
| QAItem의 출처 연결 | `QAItem.preset_question_id` (FK, SET NULL), `QAItem.target_competency` | 채점과 꼬리질문이 "이 질문이 겨냥한 역량"을 알아야 한다. 제안에서 온 질문은 위의 `used_qa_item_id`로 거꾸로 찾는다 |
| 전사 구간 | `transcript_segments` 테이블 (session_id, qa_item_id, speaker, text_deidentified, start_ms, end_ms). 확정 구간만, 비식별 텍스트만 | 재접속 시 확정 구간을 다시 줘야 한다. 원문은 저장하지 않는다(녹음 파일과 `QAItem.answer_text`가 원본 영역). 컬럼 이름에 비식별임을 드러냈다 |
| 면접관 세션 단위 역량 점수 | `Score.session_id` 추가(NOT NULL, 기존 행은 답변의 세션으로 채움), `Score.qa_item_id`는 nullable. 면접관 점수는 `qa_item_id` NULL, AI 점수는 CHECK `ai_requires_answer`로 답변 필수 | 면접관은 세션 전체를 보고 역량마다 한 번 점수를 준다. 모의 API처럼 "그 역량을 다룬 첫 QA"에 붙이면 사실과 다른 연결이 생기고, 그 QA가 지워지면 점수도 사라진다. AI 점수는 근거 인용이 답변에서 나와야 하므로 답변에 묶어 둔다. 같은 테이블·`evaluator_type` 구분은 그대로라 합산하지 않는 원칙도 그대로다. 응답의 `Score.qa_item_id`는 `string \| null`이 되었다(types.ts 반영) |
| 면접관 제출 시각 | `SessionInterviewer.submitted_at` | 제출 여부·시각은 세션-면접관 관계의 속성이다 |
| AI 채점 상태 | `InterviewSession.ai_scoring_status` (not_started/running/completed/failed) + `ai_scoring_started_at`, `ai_scoring_finished_at` | 세션당 채점은 한 번이고 목록마다 상태가 필요해서 작업 테이블보다 컬럼이 단순하다. 재시도 이력이 필요해지면 작업 테이블로 옮긴다. 0003은 AI 점수가 있는 기존 세션을 completed로 채운다 |
| 세션이 쓰는 역량 사전 | `InterviewSession.competency_set_id` (시작할 때 그 시점 확정본으로 고정) | 면접 중이나 끝난 뒤에 새 버전이 확정되어도 그 면접의 사전 질문·채점·평가 역량이 바뀌면 안 된다. 시작 전 세션은 현재 확정본을 쓴다 |
| `CompetencySet.approved_by` 의미 | 확정한 면접관 id (SSO 도입 후 SSO 사용자 id) | 프론트가 이름으로 바꿔 표시한다 |
| 숨은 텍스트·지시문 | `Application.document_info` JSON (format, blocks, hidden_blocks, images_dropped, replacements, 개수만). `ApplicationDetail.document`로 노출 | 숨은 텍스트는 비식별화는 하되(토큰 일관성) 선별 프롬프트에서는 뺀다. 화면에는 개수만 알린다 |
| 예약된 면접과 가용 시간 | 스케줄 후보 계산에서 예정·진행 중 면접 60분을 뺀다 | 세션에는 종료 예정 시각이 없어 60분으로 둔다. 가용 시간 원본은 바꾸지 않는다 |

SQLite 마이그레이션 주의: batch 모드는 테이블을 복사한 뒤 원본을 지우는데, 외래 키가 켜져 있으면 그 DROP이 자식 행을 연쇄 삭제한다. `migrations/env.py`는 마이그레이션 동안 외래 키를 끄고 끝나면 `PRAGMA foreign_key_check`로 확인한다.

## 5. 구현 상태와 남은 과제

구현됨 (2026-10-23, fake provider): 위 35개 엔드포인트 전부(SSE 2종, 업로드 포함), 시드(`scripts/seed_demo.py`), 테스트(`tests/test_api_*.py`, `test_live.py`, `test_ai_tasks.py`, `test_seed.py`, `test_schedule.py`, 외부 네트워크 없음). 프론트 7개 화면과 업로드가 `npm run dev:api`로 실제 API에서 동작한다.

남은 과제:

- **실제 모델 연결 (3단계)**: `anthropic_vertex` LLM provider(구조화 출력, 스트리밍, 토큰 집계, 프롬프트 캐싱). 지금 fake LLM은 규칙으로 그럴듯한 모양만 만든다(`providers/fake_tasks.py`). 연결 뒤 프롬프트별 품질 검증(역량 사전 초안, 프로필 구조화 정확도, 선별 근거, 꼬리질문 적합성, 채점 일치도)이 필요하다. 스트림 provider가 토큰 수를 돌려주게 인터페이스를 넓힐 것.
- **실제 GCP 호출**: Vertex AI, Speech-to-Text v2(10단계 배치, 11단계 스트리밍), 임베딩. GCP 프로젝트가 아직 없다.
- **로그인·SSO**: IAP + 사내 SSO, `GET /api/me`를 세션에서. 지금은 `IA_DEV_INTERVIEWER`. 면접관 점수는 본인 것만 쓰게 막기(지금은 패널이면 누구 것이든 가능).
- **실제 오디오·WebRTC (11단계)**: LiveKit 통화, 참가자 트랙 → 스트리밍 STT. `live/audio.py`의 `AudioSource` 구현으로 붙인다. 녹음 파일 저장(지금 `recording_uri`는 저장 예정 위치만 가리킨다), 대면 면접 화자분리.
- **여러 워커**: 전사 허브 상태가 프로세스 메모리에 있다. Cloud Run 여러 인스턴스면 Redis Pub/Sub 같은 공유 버스와 듣기 작업 소유권이 필요하다. AI 채점도 백그라운드 태스크라 작업 큐로 옮길 것.
- **OCR**: 스캔본 업로드는 지금 거부한다.
- **업로드 보완**: 같은 사람의 재지원 식별(지금은 업로드마다 새 지원자), 바이러스 검사, 원본 파일 보존 기간·삭제.
- **사전 질문 편집·AI 생성 API**: 지금은 시드와 확정 시 이월뿐이다.
- **스케줄 그리드**: 잡힌 면접 시간을 그리드에서도 빼서 그리기.
- **DB**: PostgreSQL/MySQL 확정 후 같은 마이그레이션으로 검증.
