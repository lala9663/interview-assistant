"""How applications come in (수신): channels on one side, one processing service on the other.

    service.py    지원서 1건 처리: posting -> candidate -> application -> profile -> screening.
                  Every channel calls `process_application`; nothing else creates applications.
    forms.py      채용 사이트 입력 칸 (학력·경력·자격·기술·프로젝트·자기소개): de-identified, then the
                  profile as it is (no model call)
    site.py       the recruiting site's event as docs/site-intake-spec.md fixes it: schema, items
                  never received, fields outside the spec
    signature.py  HMAC request signing (both sides)
    events.py     accept an event at the door (idempotency, refusals, 202) and apply it later
                  (revision order, withdrawal, retry)
    worker.py     the background queue, resumed after a restart

Channels today: the upload screen (api/routes/screening.py) and the recruiting site
(api/routes/intake.py). An archive import would be one more channel feeding the same service.
"""
