from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class MissingField:
    name: str
    reason: str
    required_for: str = ""


@dataclass(slots=True)
class DecompositionResult:
    intent: str = "search"
    entities: list[dict[str, str]] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    constraints: list[dict[str, Any]] = field(default_factory=list)
    standard_refs: list[dict[str, str]] = field(default_factory=list)
    scenario: dict[str, Any] = field(default_factory=dict)
    keywords: list[str] = field(default_factory=list)
    confidence: float = 0.0
    valid: bool = False
    source: str = "fallback"
    errors: list[str] = field(default_factory=list)
    missing_fields: list[MissingField] = field(default_factory=list)
    raw_output: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["missing_fields"] = [asdict(item) for item in self.missing_fields]
        return data

    def to_lunwen_parsed_json(self) -> dict[str, Any]:
        return {
            "entities": self.entities,
            "actions": self.actions,
            "constraints": self.constraints,
            "standard_refs": self.standard_refs,
            "scenario": self.scenario,
            "keywords": self.keywords,
            "rules": [],
            "relations": [],
        }
