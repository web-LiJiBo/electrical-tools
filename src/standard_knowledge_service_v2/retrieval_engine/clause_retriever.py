"""将已复制的分解 JSON 转为可追溯的条款/规则内存库。"""

from __future__ import annotations

import json
from pathlib import Path

from ..domain import ClauseKnowledgeUnit, Constraint, Entity, Rule
from ..decomposition.normalizer import canonicalize_action
from ..data_ingestion.clause_filenames import supplemental_identity


class JsonClauseRepository:
    def __init__(
        self,
        units: list[ClauseKnowledgeUnit] | None = None,
        load_report: dict | None = None,
    ) -> None:
        self.units = units or []
        self.load_report = load_report or {
            "directory": "",
            "files_seen": len(self.units),
            "loaded": len(self.units),
            "skipped": 0,
            "error_samples": [],
        }

    @classmethod
    def from_directory(cls, directory: Path, limit: int | None = None) -> "JsonClauseRepository":
        units: list[ClauseKnowledgeUnit] = []
        files_seen = 0
        errors: list[dict[str, str]] = []
        for path in sorted(directory.rglob("*.json")):
            if limit is not None and len(units) >= limit:
                break
            files_seen += 1
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload.get("raw_output"), str):
                    payload = json.loads(payload["raw_output"])
                if not isinstance(payload, dict):
                    raise ValueError("JSON顶层必须是对象")
                units.append(cls._from_payload(path, payload))
            except (AttributeError, OSError, TypeError, UnicodeError, ValueError) as exc:
                if len(errors) < 5:
                    try:
                        display_path = str(path.relative_to(directory))
                    except ValueError:
                        display_path = str(path)
                    errors.append({
                        "path": display_path,
                        "error": type(exc).__name__,
                        "message": str(exc)[:300],
                    })
        report = {
            "directory": str(directory),
            "files_seen": files_seen,
            "loaded": len(units),
            "skipped": files_seen - len(units),
            "error_samples": errors,
        }
        if files_seen and not units:
            sample = "; ".join(f"{item['path']}: {item['message']}" for item in errors)
            raise ValueError(f"目录{directory}中的{files_seen}个JSON文件全部加载失败。{sample}")
        return cls(units, report)

    @staticmethod
    def _from_payload(path: Path, payload: dict) -> ClauseKnowledgeUnit:
        identifier = supplemental_identity(payload) or path.stem
        entities = [Entity(f"{identifier}:entity:{idx}", str(item.get("name", "")), str(item.get("type", "")), str(item.get("name", ""))) for idx, item in enumerate(payload.get("entities", [])) if isinstance(item, dict) and item.get("name")]
        rules: list[Rule] = []
        for index, item in enumerate(payload.get("rules", [])):
            if not isinstance(item, dict) or not item.get("content"):
                continue
            constraint_text = str(item.get("constraint", ""))
            rules.append(Rule(
                rule_id=f"{identifier}:rule:{index}", subject=str(item.get("subject", "")), action=canonicalize_action(str(item.get("action", ""))),
                condition=str(item.get("condition", "")), constraints=[Constraint("raw_constraint", "", constraint_text, role=str(item.get("constraint_role", "unspecified")))] if constraint_text else [],
                content=str(item.get("content", "")).strip(),
                operation=str(item.get("operation", "")),
            ))
        text = "\n".join(str(item.get("content", "")) for item in payload.get("rules", []) if isinstance(item, dict))
        return ClauseKnowledgeUnit(
            clause_id=identifier, standard_id=str(payload.get("standard_id", "未标注标准")), version=str(payload.get("version", "")),
            chapter_path=str(payload.get("chapter_path", "")), text=text, entities=entities, rules=rules,
            relations=[item for item in payload.get("relations", []) if isinstance(item, dict)], source_uri=str(path),
            metadata={"dataset": "lunwen_json", **(payload.get("metadata", {}) if isinstance(payload.get("metadata"), dict) else {})},
            standard_name=str(payload.get("standard_name", "")),
        )

    def all_entities(self) -> list[tuple[Entity, ClauseKnowledgeUnit]]:
        return [(entity, unit) for unit in self.units for entity in unit.entities]

    def rules_for_entity_names(self, names: set[str]) -> list[tuple[Rule, ClauseKnowledgeUnit]]:
        matched: list[tuple[Rule, ClauseKnowledgeUnit]] = []
        for unit in self.units:
            unit_names = {entity.normalized_name or entity.name for entity in unit.entities}
            if names & unit_names:
                matched.extend((rule, unit) for rule in unit.rules)
        return matched

    def unit_for_rule(self, rule_id: str) -> ClauseKnowledgeUnit | None:
        return next((unit for unit in self.units if any(rule.rule_id == rule_id for rule in unit.rules)), None)

