from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .models import ErrorCategory, FeedbackRecord


class JsonlFeedbackStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, record: FeedbackRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existing = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
        content = existing + json.dumps(record.to_dict(), ensure_ascii=False) + "\n"
        fd, temporary = tempfile.mkstemp(dir=self.path.parent, prefix=self.path.name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def list(self) -> list[FeedbackRecord]:
        if not self.path.exists():
            return []
        records = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            data["category"] = ErrorCategory(data.get("category", "other"))
            records.append(FeedbackRecord(**data))
        return records
