from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from datetime import datetime, timedelta, timezone
from threading import RLock

from .models import AuditRecord


class JsonlAuditStore:
    def __init__(self, path: Path, retention_days: int = 365) -> None:
        self.path = path
        self.retention_days = retention_days
        self._lock = RLock()
        self.prune_expired()

    def append(self, record: AuditRecord) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")

    def get(self, request_id: str) -> AuditRecord | None:
        with self._lock:
            if not self.path.exists():
                return None
            for line in reversed(self.path.read_text(encoding="utf-8").splitlines()):
                try:
                    data = json.loads(line)
                    if data.get("request_id") == request_id:
                        return AuditRecord(**data)
                except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
                    continue
        return None

    def prune_expired(self, now: datetime | None = None) -> int:
        """删除超过保留期的可解析记录；损坏行保留，避免静默丢失审计数据。"""
        with self._lock:
            if not self.path.exists():
                return 0
            current = now or datetime.now(timezone.utc)
            if current.tzinfo is None:
                current = current.replace(tzinfo=timezone.utc)
            cutoff = current.astimezone(timezone.utc) - timedelta(days=self.retention_days)
            original_lines = self.path.read_text(encoding="utf-8").splitlines()
            kept: list[str] = []
            removed = 0
            for line in original_lines:
                try:
                    payload = json.loads(line)
                    created_at = datetime.fromisoformat(str(payload["created_at"]).replace("Z", "+00:00"))
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=timezone.utc)
                    if created_at.astimezone(timezone.utc) < cutoff:
                        removed += 1
                        continue
                except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                    pass
                kept.append(line)
            if removed:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=self.path.parent, delete=False, suffix=".tmp"
                ) as stream:
                    temporary = Path(stream.name)
                    if kept:
                        stream.write("\n".join(kept) + "\n")
                try:
                    os.replace(temporary, self.path)
                finally:
                    temporary.unlink(missing_ok=True)
            return removed
