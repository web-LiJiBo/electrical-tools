from __future__ import annotations

from ..instruction_engine.models import SemanticTuple


class ConflictDetector:
    opposite = {("trip", "close"), ("close", "trip")}

    def detect(self, semantics: list[SemanticTuple]) -> list[dict[str, str]]:
        conflicts = []
        for index, left in enumerate(semantics):
            for right in semantics[index + 1:]:
                if left.target == right.target and (left.action, right.action) in self.opposite:
                    conflicts.append({"target": left.target, "left_action": left.action, "right_action": right.action})
        return conflicts
