from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class AuditRecord:
    request_id: str
    service: str
    input_snapshot: dict[str, Any]
    result_snapshot: dict[str, Any]
    scenario: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    model_fingerprint: str = ""
    config_fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
