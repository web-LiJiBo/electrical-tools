from __future__ import annotations


class InMemoryBusinessDataRepository:
    def __init__(self, equipment: dict[str, dict] | None = None, verification: dict[str, list[dict]] | None = None) -> None:
        self.equipment = equipment or {}
        self.verification = verification or {}

    def get_equipment_context(self, equipment_id: str) -> dict:
        return dict(self.equipment.get(equipment_id, {}))

    def get_runtime_parameters(self, equipment_id: str, names: list[str]) -> dict:
        data = self.equipment.get(equipment_id, {})
        return {name: data[name] for name in names if name in data}

    def get_verification_data(self, clause_id: str) -> list[dict]:
        return list(self.verification.get(clause_id, []))
