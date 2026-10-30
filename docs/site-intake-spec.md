# 채용 사이트 → 면접 어시스턴트 지원서 연동 명세

> 다루는 것: 채용 사이트가 지원서를 이 시스템에 보내는 방법(엔드포인트, 필드, 서명, 재시도, 오류 코드, 받지 않는 항목). 채용 시스템 부서와 협의할 요구사항 문서다.
>
> 상태: 수신 쪽 구현됨(가짜 채용 사이트로 검증), 실제 사이트 연결은 계획 · v0.1 초안(2026-10-26, 11장은 2026-10-28 수정) · 확인: 2026-10-30

채용 사이트가 직무별로 받은 지원서를 면접 어시스턴트(이하 "수신 시스템")에 보내는 방법을 정한다. 수신 시스템 쪽은 이 명세대로 구현되어 있고, 가짜 채용 사이트(`scripts/fake_recruiting_site.py`)로 검증했다. 실제 연결은 11장의 확인 사항이 정리된 뒤에 한다.

## 1. 원칙

| 항목 | 내용 |
| --- | --- |
| 방향 | 한 방향. 채용 사이트 → 수신 시스템. 수신 시스템은 채용 사이트의 상태를 바꾸지 않는다 |
| 공식 기록 | 채용 사이트. 수신 시스템은 서류 선별과 면접 진행을 위한 처리용 사본이다. 처리가 끝난 이벤트 원문은 지운다 |
| 단위 | 이벤트 1건 = 지원서 1건의 제출·수정·철회 1회. 지원서 내용 전체를 매번 보낸다(바뀐 칸만 보내지 않는다) |
| 응답 | 받자마자 202(접수)만 돌려주고 처리는 수신 시스템 뒤에서 한다. 처리 결과는 상태 조회 API로 본다 |
| 데이터 최소화 | 받는 항목은 이 명세로 고정한다. 평가에 쓰지 않는 항목(6장)은 보내지 않는다. 오면 거절한다 |
| 신원 | 이름·연락처는 서류 안의 같은 값을 가리는 데(비식별화)만 쓰고 암호화해 둔다. 화면과 AI에는 가명만 간다. 지원자 번호는 저장하지 않는다(키 해시로 같은 사람만 찾는다) |

## 2. 흐름

```
채용 사이트                                   수신 시스템
  지원서 제출/수정/철회 발생
  POST /api/intake/site/events  ──────────▶  서명·시각 확인 → 중복 확인 → 받지 않는 항목·필수 칸 확인
  (서명 헤더 + 이벤트 JSON + 첨부)  ◀──────────  202 접수 (또는 401/409/413/422)
                                              백그라운드: 공고 찾기 → 지원자 찾기/만들기 → 첨부 읽기
                                                         → 비식별화 → 프로필 → AI 선별 (보류로 시작)
  GET /api/intake/site/events/{event_id} ───▶
                                  ◀────────── 처리 상태 (done / skipped / failed + 사유 코드)
```

## 3. 엔드포인트

| 메서드 | 경로 | 용도 |
| --- | --- | --- |
| POST | `/api/intake/site/events` | 지원서 이벤트 1건 보내기 |
| GET | `/api/intake/site/events/{event_id}` | 그 이벤트의 처리 상태 |

- 기준 주소(호스트)는 네트워크 경로가 정해지면 정한다(11장). 전송 구간은 TLS(HTTPS)만.
- 본문 형식: 첨부가 있으면 `multipart/form-data`, 없으면 `application/json`(이벤트 JSON 그대로).
- 요청 하나의 크기: 첨부 5개, 개당 10MB, 전체 52MB 이하.

### 첨부를 같은 요청의 multipart로 보내는 이유

별도 업로드 후 참조 대신 같은 요청에 싣는다.

- 이벤트 1건이 요청 1건이라 원자적이다. 업로드만 되고 이벤트가 안 온(또는 반대) 반쪽 상태와 그 정리 작업이 없다.
- 서명 하나가 이벤트와 첨부의 모든 바이트를 덮는다. 참조 방식이면 업로드와 참조를 각각 지켜야 한다.
- 멱등성(event_id)과 재시도가 요청 하나로 끝난다. 사이트 쪽 구현도 "만들고, 서명하고, 보낸다" 한 단계다.
- 이력서·포트폴리오 크기(10MB 이하)에서는 재전송 비용이 크지 않다. 훨씬 큰 파일(영상 포트폴리오 등)이나 이어 올리기가 필요해지면 그때 별도 업로드를 추가한다.

multipart 구성:

| part 이름 | 내용 |
| --- | --- |
| `event` | 이벤트 JSON (UTF-8, `Content-Type: application/json`) |
| 첨부마다 하나 | `attachments[].part`에 적은 이름. 파일 바이트. part의 파일명은 아무 값이어도 된다(실제 파일명은 JSON의 `attachments[].filename`). 한글 파일명을 multipart 헤더에 싣지 않으려는 것이다 |

## 4. 보내는 쪽 확인: HMAC 서명

모든 요청(POST와 상태 조회 GET 모두)에 아래 두 헤더를 붙인다.

| 헤더 | 값 |
| --- | --- |
| `X-Intake-Timestamp` | 보내는 시각, 유닉스 초 (예 `1793000000`) |
| `X-Intake-Signature` | `v1=` + 소문자 16진 HMAC-SHA256 |

서명할 문자열(줄바꿈 `\n`으로 이음):

```
{X-Intake-Timestamp}
{HTTP 메서드, 대문자}
{경로, 쿼리 없이. 예: /api/intake/site/events}
{본문 바이트의 SHA-256, 소문자 16진. 본문 없는 GET은 빈 바이트의 해시}
```

```
signature = "v1=" + hex(HMAC_SHA256(key = 공유 비밀키, message = 위 문자열의 UTF-8 바이트))
```

- 본문은 실제로 보내는 바이트 그대로 해시한다(multipart 경계 문자열 포함). 서명한 뒤 본문을 바꾸면 안 된다.
- 수신 시스템은 서버 시각과 300초 넘게 차이 나는 요청을 거절한다(`stale_timestamp`). 오래된 요청을 그대로 다시 보내는 공격을 이 창 밖에서 막고, 창 안의 재전송은 event_id 멱등성(5장)이 한 번만 반영되게 막는다. 메서드와 경로를 서명에 넣어 다른 엔드포인트로 돌려 쓰지 못하게 한다.
- 공유 비밀키: 32바이트 이상 무작위 값. 수신 시스템은 환경변수 `IA_SITE_SECRET`(운영에서는 비밀 저장소에서 주입)에서 읽는다. 키 교체 기간에는 이전 키(`IA_SITE_SECRET_PREVIOUS`)도 받는다. 보내는 쪽은 교체 기간 동안 `v1=새서명,v1=옛서명`처럼 두 개를 쉼표로 붙여 보내도 된다.
- 키는 메일·메신저로 주고받지 않는다. 전달 방법은 정보보호와 정한다(11장).

Python 예 (수신 시스템의 `intake/signature.py`와 같다):

```python
import hashlib, hmac, time

def sign(secret: str, method: str, path: str, body: bytes) -> dict[str, str]:
    ts = str(int(time.time()))
    message = f"{ts}\n{method.upper()}\n{path}\n{hashlib.sha256(body).hexdigest()}".encode()
    mac = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return {"X-Intake-Timestamp": ts, "X-Intake-Signature": f"v1={mac}"}
```

Java 예:

```java
String ts = String.valueOf(Instant.now().getEpochSecond());
String bodyHash = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(body));
String message = ts + "\n" + "POST" + "\n" + "/api/intake/site/events" + "\n" + bodyHash;
Mac mac = Mac.getInstance("HmacSHA256");
mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
String signature = "v1=" + HexFormat.of().formatHex(mac.doFinal(message.getBytes(StandardCharsets.UTF_8)));
```

## 5. 멱등성과 순서

| 규칙 | 내용 |
| --- | --- |
| `event_id` | 이벤트마다 고유. 재전송할 때는 같은 이벤트를 같은 `event_id`, 같은 내용으로 보낸다. 수신 시스템은 처음 결과를 그대로 돌려주고(`duplicate: true`) 다시 반영하지 않는다 |
| 같은 `event_id`, 다른 내용 | 409 `event_id_conflict`. 내용을 고쳤으면 새 `event_id`로 보낸다 |
| `revision` | 지원서(지원 번호)마다 1부터 시작해 바뀔 때마다 1씩 늘린다. 제출 1, 첫 수정 2, 철회는 그때까지의 마지막 + 1 |
| 순서가 바뀌어 온 경우 | 이미 반영된 revision보다 높은 이벤트만 반영한다. 수정(2)이 제출(1)보다 먼저 오면 수정으로 지원서를 만들고, 늦게 온 제출은 반영하지 않는다(`skipped`, `stale_revision`). 이벤트가 지원서 전체를 담으므로 최종 상태는 같다 |
| 철회 뒤 | 철회가 반영되면 같은 지원 번호의 더 낮은 revision은 `skipped`(`withdrawn`), 더 높은 revision의 제출·수정은 `failed`(`application_withdrawn`). 다시 지원하면 새 지원 번호로 보낸다(같은 공고면 철회된 자리를 다시 쓴다) |
| 철회가 처리 중인 이벤트를 만나면 | 같은 지원 번호의 대기 중인 이전 이벤트는 건너뛰고, 처리 중인 것은 멈춘다(`skipped`, `withdrawn`) |
| 같은 사람 | `applicant.applicant_no`가 같으면 같은 지원자다. 여러 공고에 지원하면 지원서가 공고마다 하나씩 붙는다. 같은 사람이 같은 공고에 활성 지원 번호를 둘 가질 수 없다(`duplicate_application`) |

## 6. 받지 않는 항목

아래 항목은 평가에 쓰지 않으므로 보내지 않는다. 이벤트 어디에든(어느 깊이든) 이 이름의 키가 있으면 수신 시스템은 이벤트 전체를 받지 않고 422 `forbidden_field`로 돌려준다. 값은 저장하지 않고 필드 경로만 기록한다. 항목을 빼고 새 `event_id`로 다시 보낸다.

| 항목 | 이런 키 이름이면 거절 (대소문자, `_`·`-` 무시) | 근거 |
| --- | --- | --- |
| 사진 | photo, photo_url, picture, profile_image, id_photo, portrait, 사진, 증명사진. 첨부의 `kind: photo` | 평가에 쓰지 않음 (블라인드 채용) |
| 주민등록번호 | rrn, resident_no, resident_registration_number, jumin, ssn, national_id, 주민번호 | 개인정보 보호법 제24조의2 |
| 가족 관계·가족의 학력·직업·재산 | family, family_members, parents, father, mother, spouse, siblings, 가족, 가족관계 | 채용절차의 공정화에 관한 법률 제4조의3 |
| 키·체중·용모 등 신체 조건 | height, weight, body_size, appearance, blood_type, 키, 체중, 신장, 혈액형 | 채용절차법 제4조의3 |
| 출신 지역·본적 | birthplace, hometown, place_of_origin, origin, domicile, 본적, 출신지, 출생지 | 채용절차법 제4조의3 |
| 혼인 여부 | marital_status, married, marriage, 혼인여부, 결혼여부 | 채용절차법 제4조의3 |
| 재산 | assets, property, wealth, income, 재산 | 채용절차법 제4조의3 |
| 종교 | religion, 종교 | 개인정보 보호법 제23조 (민감정보) |
| 정치 성향 | political, political_party, 정당 | 개인정보 보호법 제23조 |
| 건강·장애 | health, medical, disability, 건강, 장애, 병력 | 개인정보 보호법 제23조 (우대 대상 여부는 사이트가 처리) |
| 성별 | gender, sex, 성별 | 평가에 쓰지 않음 (편향 방지) |

- 이 명세(7장)에 없는 키는 거절하지 않고 버린다. 버린 키의 경로는 응답의 `dropped_fields`와 수신 기록에 남는다(값은 남기지 않는다). 사이트가 칸을 추가했다면 이 명세를 먼저 고친다.
- 자기소개 답변 같은 자유 텍스트 안에 적힌 내용은 키로 거를 수 없다. 이름·연락처·주민번호 모양은 비식별화가 가리고, 그 밖의 내용은 사이트의 입력 안내 문구로 막는다(11장).
- 생년월일·주소는 받을 수 있지만 선택이다. 평가에는 쓰지 않고 서류 안의 같은 값을 가리는 데만 쓴다. 보내지 않으면 형태 규칙으로만 찾는다.

## 7. 이벤트 JSON

### 7.1 공통 칸

| 필드 | 형식 | 필수 | 설명 |
| --- | --- | --- | --- |
| `event_id` | 문자열, `[A-Za-z0-9][A-Za-z0-9._:-]{0,63}` | 필수 | 이벤트 고유 id (5장) |
| `event_type` | 코드 | 필수 | `application.submitted` 제출, `application.updated` 수정(마감 전), `application.withdrawn` 철회 |
| `occurred_at` | ISO 8601, 시간대 필수 (`2026-10-26T01:02:03.000Z`) | 필수 | 사이트에서 일어난 시각 |
| `revision` | 정수 1 이상 | 필수 | 지원서 단위 버전 (5장) |
| `posting_no` | 문자열 (event_id와 같은 규칙) | 필수 | 채용 사이트 공고 번호. 수신 시스템 공고 화면에서 이 번호를 공고에 연결한다 |
| `application_no` | 문자열 (같은 규칙) | 필수 | 채용 사이트 지원 번호 |
| `applicant` | 객체 (7.2) | 제출·수정은 필수 | 철회에는 보내지 않는다(와도 버린다) |
| `consent` | 객체 (7.3) | 제출·수정은 필수 | 지원자 동의 기록 |
| `form` | 객체 (7.4) | 선택 | 사이트 입력 칸. `form`이나 `attachments` 중 하나는 있어야 선별할 수 있다 |
| `attachments` | 배열 (7.5), 최대 5 | 선택 | 첨부 파일 설명. 파일 자체는 multipart part로 |

### 7.2 `applicant` (비식별화에만 쓰고 암호화해 둔다)

| 필드 | 형식 | 필수 | 설명 |
| --- | --- | --- | --- |
| `applicant_no` | 문자열 (event_id와 같은 규칙) | 필수 | 채용 사이트 지원자 번호. 같은 번호 = 같은 사람. 수신 시스템은 키 해시만 저장한다 |
| `name` | 1~100자 | 필수 | 이름 |
| `other_names` | 문자열 배열, 최대 3 | 선택 | 영문·한자 표기 |
| `phones` | 문자열 배열, 최대 3 | 선택 | 휴대전화 |
| `emails` | 문자열 배열, 최대 3 | 선택 | 이메일 |
| `birthdate` | `YYYY-MM-DD` | 선택 | 서류 속 같은 날짜를 가리는 데만 쓴다 |
| `address` | 200자 이하 | 선택 | 같은 용도 |

### 7.3 `consent`

| 필드 | 형식 | 필수 | 설명 |
| --- | --- | --- | --- |
| `terms_version` | 1~50자 | 필수 | 지원자가 동의한 안내 문구의 버전 (예 `2026-10-v1`). 문구는 법무와 정한다(11장) |
| `agreed_at` | ISO 8601, 시간대 필수 | 필수 | 동의 시각 |

수신 시스템은 처리 결과에 동의 버전을 남긴다. 동의를 받지 않은 지원서는 보내지 않는다.

### 7.4 `form` (사이트 입력 칸)

이미 정리된 데이터라 수신 시스템은 모델로 다시 구조화하지 않고 비식별화만 거쳐 프로필로 쓴다. 자기소개 답변은 선별 근거 문서가 된다.

| 필드 | 형식 | 설명 |
| --- | --- | --- |
| `education[]` (최대 10) | `school` 필수(100자), `degree` 필수 코드, `major`, `start`·`end` (`YYYY-MM`), `status` 코드 | 학력 |
| `career[]` (최대 30) | `company` 필수, `department`, `title`(직무·직책), `start` 필수 `YYYY-MM`, `end` `YYYY-MM` 또는 `null`(재직 중), `description`(3000자, 담당 업무·성과) | 경력. `end`가 `start`보다 빠르면 422 |
| `certifications[]` (최대 30) | `name` 필수, `issuer`, `acquired` `YYYY-MM`, `score`(20자, 어학 점수·등급) | 자격·어학 |
| `skills[]` (최대 50) | 문자열 50자 | 보유 기술 |
| `projects[]` (최대 20) | `name` 필수, `role`, `description`(3000자), `tech[]`(최대 20) | 프로젝트 |
| `essays[]` (최대 10) | `question` 필수(500자), `answer` 필수(5000자) | 자기소개 항목 |

코드 값:

| 필드 | 값 |
| --- | --- |
| `education[].degree` | `high_school` 고등학교, `associate` 전문학사, `bachelor` 학사, `master` 석사, `doctorate` 박사 |
| `education[].status` | `graduated` 졸업(기본), `expected` 졸업 예정, `enrolled` 재학, `completed` 수료, `left` 중퇴 |

### 7.5 `attachments[]`

| 필드 | 형식 | 필수 | 설명 |
| --- | --- | --- | --- |
| `part` | `[A-Za-z0-9_-]{1,40}`, 요청 안에서 겹치지 않게 | 필수 | 파일을 담은 multipart part 이름 |
| `kind` | `resume` 이력서(기본), `portfolio` 포트폴리오, `certificate` 증빙, `other` 기타 | 선택 | `photo`는 받지 않는다(6장) |
| `filename` | 200자 이하 | 필수 | 원래 파일명. 파일명 안의 이름도 비식별화한다. 저장 파일명에는 쓰지 않는다 |

받는 파일 형식(형식은 확장자가 아니라 내용으로 판별한다):

| 형식 | 읽는 방법 |
| --- | --- |
| PDF | 텍스트 층이 있는 쪽은 그대로, 스캔한 쪽과 글자가 깨진 쪽은 OCR. 텍스트와 스캔이 섞인 파일도 된다 |
| DOCX, PPTX, HTML | 본문·표·노트 등 텍스트. 안에 붙인 그림(자격증 캡처 등)은 수신 쪽 설정에 따라 OCR |
| HWP(5.0), HWPX | 한글 문서. 본문·표·머리글·각주·메모·숨은 설명까지 |
| 구형 .doc, .ppt | 수신 쪽에서 LibreOffice로 .docx·.pptx로 바꾼 뒤 읽는다 |
| JPG, PNG | 휴대폰 사진·화면 캡처. OCR |

- 스프레드시트(.xlsx·.xls), GIF, HEIC 등 나머지는 `unsupported_attachment`.
- 증명사진으로 보이는 그림은 읽지 않고 버린다. 그래도 사진은 첨부로 보내지 않는다(6장).
- 암호가 걸린 파일은 `encrypted_attachment`, 손상된 파일은 `unreadable_attachment`.
- 아래 실패는 수신 쪽 설정·설치 문제라 수신 시스템이 원문을 남겨 두고, 고친 뒤 수신 쪽에서 다시 처리한다. 사이트가 다시 보낼 필요는 없다: `ocr_required`(읽기 방식이 "텍스트만"인데 스캔한 쪽이 있음), `ocr_unavailable`(OCR 엔진이나 모델 파일이 없거나 읽지 못함), `converter_missing`(.doc·.ppt인데 변환기가 없음), `reader_unavailable`(그 형식의 읽기 도구를 쓸 수 없음).

### 7.6 예

```json
{
  "event_id": "EVT-000123",
  "event_type": "application.submitted",
  "occurred_at": "2026-10-26T01:02:03.000Z",
  "revision": 1,
  "posting_no": "DS-2026-0101",
  "application_no": "A200123",
  "applicant": {
    "applicant_no": "U100123",
    "name": "홍길동",
    "other_names": ["Gildong Hong"],
    "phones": ["010-0000-0000"],
    "emails": ["gildong@example.com"]
  },
  "consent": { "terms_version": "2026-10-v1", "agreed_at": "2026-10-26T00:58:00.000Z" },
  "form": {
    "education": [{ "school": "한빛대학교", "degree": "bachelor", "major": "재료공학", "start": "2014-03", "end": "2018-02" }],
    "career": [{ "company": "새솔전자", "title": "공정 엔지니어", "start": "2018-03", "end": null, "description": "식각 공정 조건 최적화와 산포 관리." }],
    "certifications": [{ "name": "TOEIC", "score": "900", "acquired": "2017-11" }],
    "skills": ["SPC", "DOE", "Python"],
    "essays": [{ "question": "지원 동기와 입사 후 포부를 적어 주세요.", "answer": "..." }]
  },
  "attachments": [{ "part": "resume", "kind": "resume", "filename": "이력서_홍길동.pdf" }]
}
```

철회:

```json
{ "event_id": "EVT-000140", "event_type": "application.withdrawn", "occurred_at": "2026-10-27T09:00:00.000Z",
  "revision": 3, "posting_no": "DS-2026-0101", "application_no": "A200123" }
```

## 8. 응답과 오류 코드

### 8.1 접수 응답 (202, 그리고 상태 조회 200)

```json
{
  "event_id": "EVT-000123",
  "status": "queued",
  "event_type": "application.submitted",
  "revision": 1,
  "received_at": "2026-10-26T01:02:04.120Z",
  "finished_at": null,
  "dropped_fields": [],
  "duplicate": false,
  "status_url": "/api/intake/site/events/EVT-000123"
}
```

실패·거절·건너뜀이면 `code`, `detail`(한국어 설명, 값은 담지 않음), `fields`(필드 경로)가 더 붙는다. 응답에는 수신 시스템의 가명·내부 id가 없다.

`status` 값: `queued` 대기, `processing` 처리 중, `done` 반영, `skipped` 의도적으로 반영 안 함, `failed` 반영 못 함(수신 쪽에서 고쳐 다시 처리할 수 있음), `rejected` 접수 거절(아무것도 저장 안 함).

### 8.2 접수 단계 오류 (요청에 대한 HTTP 응답)

| HTTP | `code` | 뜻 | 사이트의 대응 |
| --- | --- | --- | --- |
| 400 | `malformed` | JSON·multipart를 읽을 수 없음, `event_id` 없음 | 고쳐서 보냄 |
| 401 | `missing_signature` | 서명 헤더 없음 | 서명해서 보냄 |
| 401 | `invalid_signature` | 서명 불일치(키, 경로, 본문) | 키·서명 구현 확인 |
| 401 | `stale_timestamp` | 서버 시각과 300초 넘게 차이 | 새 시각으로 다시 서명해 재시도. 서버 시계(NTP) 확인 |
| 409 | `event_id_conflict` | 같은 event_id에 다른 내용 | 새 event_id로 |
| 413 | `too_large` | 요청이 너무 큼 | 첨부를 줄임 |
| 415 | `malformed` | 본문 형식이 multipart·JSON이 아님 | 형식 확인 |
| 422 | `forbidden_field` | 받지 않는 항목(6장) | 항목을 빼고 새 event_id로 |
| 422 | `missing_field` | 필수 칸 없음 (`fields`에 경로) | 채워서 새 event_id로 |
| 422 | `invalid_field` | 형식이 맞지 않음, 첨부 part 없음, 첨부 10MB 초과 | 고쳐서 새 event_id로 |
| 503 | `not_configured` | 수신 쪽 키 미설정 등 | 재시도 (수신 쪽 담당자에게 알림) |
| 5xx·시간 초과 | | 수신 쪽 장애 | 같은 event_id로 재시도 (9장) |

422로 거절된 이벤트는 `rejected`로 기록되고, 같은 event_id·같은 내용을 다시 보내면 같은 422가 다시 온다.

### 8.3 처리 단계 결과 (상태 조회의 `status`·`code`)

| `status` | `code` | 뜻 | 누가 무엇을 |
| --- | --- | --- | --- |
| `done` | | 반영됨 | |
| `skipped` | `stale_revision` | 더 새 버전이 이미 반영됨 | 없음 |
| `skipped` | `withdrawn` | 철회된 지원서라 반영 안 함, 또는 처리 중 철회로 멈춤 | 없음 |
| `failed` | `unknown_posting` | 이 공고 번호가 수신 시스템 공고에 연결되지 않음 | 수신 쪽이 공고 화면에서 번호를 연결하고 "다시 처리" |
| `failed` | `posting_closed` | 수신 시스템에서 마감된 공고 | 수신 쪽 판단 (공고를 열고 다시 처리) |
| `failed` | `unsupported_attachment` | 받지 않는 파일 형식(스프레드시트 등) | 사이트가 PDF·DOCX 등으로 새 이벤트(revision+1) |
| `failed` | `encrypted_attachment` | 암호가 걸린 파일 | 사이트가 암호 없는 파일로 새 이벤트 |
| `failed` | `unreadable_attachment` | 손상된 파일 | 사이트가 정상 파일로 새 이벤트 |
| `failed` | `ocr_required` | 스캔한 쪽이 있는데 수신 쪽 읽기 방식이 "텍스트만" | 수신 쪽이 읽기 방식을 바꾸고 다시 처리 |
| `failed` | `ocr_unavailable` | OCR로 읽지 못함(엔진·모델 파일 없음, 오류) | 수신 쪽이 OCR 엔진을 고치고 다시 처리 |
| `failed` | `converter_missing` | .doc·.ppt인데 수신 쪽에 변환기가 없음 | 수신 쪽이 LibreOffice를 설치하고 다시 처리, 또는 사이트가 .docx·.pptx·PDF로 |
| `failed` | `reader_unavailable` | 그 형식의 읽기 도구를 쓸 수 없음(설정 문제) | 수신 쪽이 고치고 다시 처리 |
| `failed` | `duplicate_application` | 같은 사람이 같은 공고에 다른 지원 번호로 이미 활성 지원 | 사이트 데이터 확인 |
| `failed` | `application_withdrawn` | 철회된 지원 번호의 새 버전 | 재지원이면 새 지원 번호로 |
| `failed` | `invalid_field` | 지원 번호가 다른 공고·다른 지원자의 것 | 사이트 데이터 확인 |
| `failed` | `ai_failed` | AI 선별 실패 | 수신 쪽 다시 처리 |
| `failed` | `internal_error` | 수신 쪽 오류 | 수신 쪽 다시 처리 |

실패해도 사이트가 같은 event_id로 다시 보낼 필요는 없다(같은 결과가 온다). 수신 쪽 원인은 수신 쪽이 고쳐 다시 처리하고, 사이트 쪽 원인은 사이트가 고친 내용을 새 event_id와 높인 revision으로 보낸다.

## 9. 재시도와 놓친 이벤트 다시 맞추기

### 9.1 재시도

- 재시도 대상: 연결 실패, 시간 초과(30초), HTTP 5xx, 429, 그리고 `stale_timestamp`(새 시각으로 다시 서명).
- 재시도하지 않음: 그 밖의 4xx. 고친 뒤 새 event_id로 보낸다.
- 간격: 지수 백오프 + 무작위 지연. 1초, 2초, 4초 … 최대 5분 간격, 최대 24시간. 그 뒤에는 사이트 쪽 실패 목록에 남겨 운영자가 본다.
- 재시도는 같은 event_id, 같은 내용으로. 한 지원서의 이벤트는 가능하면 순서대로 보내되, 순서가 바뀌어도 revision 규칙(5장)으로 맞는다.
- 동시 전송: 서로 다른 지원서는 병렬로 보내도 된다. 수신 시스템은 같은 지원서·같은 지원자의 이벤트를 차례로 처리한다.

### 9.2 대조 (reconcile, 명세만, 구현 안 함)

이벤트를 보냈는데 수신 쪽에 없거나(사이트 장애로 보내지 못하고 재시도도 끝남) 수신 쪽 상태가 의심스러울 때 다시 맞추는 흐름이다. 채용 사이트에 아래 조회 API가 있다고 가정한다.

```
GET {사이트}/api/applications?posting_no=DS-2026-0101&updated_since=2026-10-25T00:00:00Z
→ [{ "application_no": "A200123", "revision": 2, "status": "submitted" | "withdrawn", "updated_at": "..." }, ...]
```

1. 수신 시스템이 공고별로 하루 한 번(마감 직후에도 한 번) 위 목록을 가져온다(사이트 → 수신이 아니라 수신 → 사이트 방향의 읽기 호출. 같은 HMAC 방식으로 서명).
2. 지원 번호마다 사이트의 최신 revision과 수신 쪽에 반영된 최신 revision을 비교한다.
3. 수신 쪽이 낮거나 없으면 사이트에 그 지원서의 최신 이벤트를 다시 보내 달라고 요청한다(`POST {사이트}/api/applications/{application_no}/resend`, 새 event_id). 사이트에 있고 수신 쪽에서 철회되지 않았는데 사이트가 `withdrawn`이면 같은 방식으로 철회 이벤트를 요청한다.
4. 결과(맞음, 다시 요청함, 사이트에 없음)를 연동 현황에 남긴다.

이 흐름에 필요한 것: 사이트 쪽 목록·재전송 API, 수신 → 사이트 방향 네트워크 경로와 인증. 협의 사항(11장).

## 10. 수신 시스템 쪽에서 하는 일 (참고)

- 공고 연결: 공고 화면에서 채용 사이트 공고 번호를 넣는다. 연결 전 이벤트는 `unknown_posting`으로 실패했다가 연결 후 "다시 처리"로 들어온다.
- 연동 현황(관리자): 받은 이벤트, 상태, 실패 사유, 공고별 건수, 처리 시간, 실패 다시 처리. 실명과 지원자 번호는 보이지 않는다.
- 처리: 입력 칸 → 프로필(비식별화), 자기소개·첨부 → 비식별 서류 텍스트, AI 선별은 "보류"로 시작하고 통과·탈락은 사람이 정한다. 수정이 오면 선별을 다시 하고, 사람이 이미 정한 지원서는 보류로 되돌린다(근거가 바뀌었으므로).
- 철회: 지원서를 목록에서 빼고 잡힌 면접을 취소한다. 공식 기록은 사이트에 있다.
- 보존: 처리 끝난 이벤트의 원문은 지운다. 실패한 이벤트 원문(암호화)과 첨부 원본은 남는다. 보존 기간은 정보보호와 정한다(11장).

## 11. 실제 연동 전에 확인할 것

**채용 시스템 부서**

- [ ] 이벤트를 만들 수 있는 시점: 제출·수정·철회 각각에 훅을 걸 수 있는지, 지원서별 revision을 매길 수 있는지
- [ ] `applicant_no`가 사람 단위로 안정적인 번호인지(로그인 id·수험번호 등), 재가입하면 바뀌는지
- [ ] 입력 칸 매핑: 사이트 실제 칸 ↔ 7.4. 학위·졸업 구분 코드, 경력 기간 형식, 자기소개 문항 수와 글자 수
- [ ] 첨부: 받는 형식(HWP 비율), 크기, 스캔본·휴대폰 사진 비율. 사진 칸이 첨부로 섞여 오지 않게 분리할 수 있는지
- [ ] 보내지 않을 칸(6장)을 사이트 쪽에서 빼고 보낼 수 있는지. 사이트가 이미 모으고 있는 칸 목록
- [ ] 재시도 큐가 있는지, 실패 이벤트를 운영자가 볼 화면이 있는지
- [ ] 대조용 조회 API·재전송 API(9.2)를 만들 수 있는지
- [ ] 개발·테스트 환경(스테이징 사이트 ↔ 수신 시스템 스테이징), 일정, 연락 창구
- [ ] 공고 번호 체계와 공고 생성 시점(수신 쪽 공고와 누가 언제 연결하는지)

**정보보호**

- [ ] 네트워크 경로: 사이트 → 수신 시스템. 수신 시스템을 둘 곳(사내 서버, 사내 클라우드 등)은 아직 정해지지 않았다. 수신 경로는 면접관 로그인 밖이어야 한다. 사내망 안 경로·방화벽 허용·고정 IP 허용 목록 중 무엇으로
- [ ] 공유 키 생성·전달·보관(비밀 저장소)·교체 주기, 키 유출 시 절차
- [ ] 서명·시각 300초 창이 사내 기준에 맞는지, mTLS를 더할지
- [ ] 이름·연락처·생년월일·주소를 받아 암호화해 두는 것(비식별화용)의 허용 여부. 생년월일·주소를 아예 받지 않을지
- [ ] 보존 기간: 실패 이벤트 원문, 첨부 원본, 철회된 지원서, 감사 로그
- [ ] 처리 위탁 여부 판단과 위탁 계약(수신 시스템이나 AI 모델이 회사 밖 서비스를 쓰게 되는 경우)
- [ ] 수신 요청 속도 제한·크기 제한 기준

**법무**

- [ ] 지원자 동의 문구: 수신 시스템으로의 제공(또는 위탁), AI를 이용한 서류 검토(참고용, 최종 판단은 사람), 보존 기간. `consent.terms_version`에 넣을 버전 체계
- [ ] 받지 않는 항목 목록(6장)이 채용절차법·개인정보 보호법 기준에 충분한지
- [ ] 자동화된 결정에 대한 설명·거부권 대응(개인정보 보호법 제37조의2) 필요 여부
- [ ] 철회한 지원자의 데이터 삭제 시점

## 12. 남은 과제 (수신 시스템)

- 실제 채용 사이트 연결: 11장 확인 뒤. 지금은 가짜 채용 사이트로만 검증했다.
- 대조(9.2): 사이트 API가 정해지면 구현.
- 압축 파일 일괄 가져오기: 연동 승인이 늦어질 때의 대안. 채용 담당자가 사이트에서 내려받은 ZIP(첨부)과 목록 CSV(이 명세의 칸)를 올리면 같은 처리 함수로 들어간다(통로만 추가). 구현 안 함.
- 수신 서버 여러 대: 지금 처리 큐는 서버 한 대의 워커다.
- 형식: HWP·HWPX·구형 .doc/.ppt·이미지(OCR)는 2026-10-26에 추가했다. 실제 한글 프로그램으로 저장한 HWP로 다시 확인할 것, HEIC·TIFF·스프레드시트는 받지 않는다.
