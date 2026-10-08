from __future__ import annotations

from ..domain import ClauseKnowledgeUnit
from ..retrieval_engine.text import text_similarity


class InMemoryStandardRepository:
    def __init__(self, units: list[ClauseKnowledgeUnit] | None = None) -> None:
        self._units: dict[tuple[str, str], ClauseKnowledgeUnit] = {}
        for unit in units or []:
            self.upsert(unit)

    def upsert(self, unit: ClauseKnowledgeUnit) -> None:
        self._units[(unit.clause_id, unit.version)] = unit

    def get_clause(self, clause_id: str, version: str | None = None) -> ClauseKnowledgeUnit | None:
        if version is not None:
            return self._units.get((clause_id, version))
        return next((item for (key, _), item in self._units.items() if key == clause_id), None)

    def search(self, filters: dict, limit: int = 20) -> list[ClauseKnowledgeUnit]:
        query = str(filters.get("query", ""))
        standard_id, version = str(filters.get("standard_id", "")), str(filters.get("version", ""))
        units = [item for item in self._units.values() if (not standard_id or item.standard_id == standard_id) and (not version or item.version == version)]
        return sorted(units, key=lambda item: text_similarity(query, item.text), reverse=True)[:limit]

    def version_history(self, standard_id: str) -> list[str]:
        return sorted({item.version for item in self._units.values() if item.standard_id == standard_id and item.version})
