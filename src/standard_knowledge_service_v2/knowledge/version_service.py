from __future__ import annotations

import re


class VersionService:
    @staticmethod
    def sort_key(version: str) -> tuple[int, ...]:
        parts = re.findall(r"\d+", version or "")
        return tuple(int(item) for item in parts) or (0,)

    def compare(self, version_a: str, version_b: str) -> int:
        return (self.sort_key(version_a) > self.sort_key(version_b)) - (self.sort_key(version_a) < self.sort_key(version_b))

    def is_current(self, requested: str, available: list[str]) -> bool:
        return bool(requested) and bool(available) and self.compare(requested, max(available, key=self.sort_key)) == 0
