"""AI tasks (FR-02 역량 사전 초안, FR-01·03 서류 선별, FR-06 꼬리질문, FR-07 평점).

Every call goes through `gateway.AiGateway`: the guard re-checks candidate text for identifiers,
the provider is picked by role from config/providers.yaml, and an AuditLog row is written.
"""


class AiOutputInvalid(RuntimeError):
    """The model answered, but not in the shape the task needs."""
