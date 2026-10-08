from __future__ import annotations

import json
from pathlib import Path

from .models import AuditRecord


class JsonlAuditStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, record: AuditRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")

    def get(self, request_id: str) -> AuditRecord | None:
        if not self.path.exists():
            return None
        for line in reversed(self.path.read_text(encoding="utf-8").splitlines()):
            data = json.loads(line)
            if data.get("request_id") == request_id:
                return AuditRecord(**data)
        return None
