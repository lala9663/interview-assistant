"""AI models as an admin setting (관리자 > 모델 설정): which provider serves each role, its history,
connection tests, and switching without a restart.

- store: active spec per role and the change history in the database (YAML seeds the first start)
- manager: provider sets per config revision, session pinning, the atomic swap, eviction
- probe: per-role connection tests (LLM structured output, STT on a voice sample, vector size)

The catalog of choosable implementations and model weights live in `providers/` (catalog.py,
weights.py); the HTTP side is `api/routes/admin.py`.
"""
