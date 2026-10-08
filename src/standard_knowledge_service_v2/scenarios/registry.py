from __future__ import annotations

from ..exceptions import UnsupportedScenarioError
from .grid_fault_isolation import GridFaultIsolationScenario
from .models import ScenarioDefinition
from .offshore_wind import OffshoreWindScenario
from .power_grid_operation import PowerGridOperationScenario
from .renewable_grid_integration import RenewableGridIntegrationScenario
from .substation_maintenance import SubstationMaintenanceScenario


class ScenarioRegistry:
    def __init__(self) -> None:
        self._items: dict[str, ScenarioDefinition] = {}
        self.register(OffshoreWindScenario().definition)
        self.register(SubstationMaintenanceScenario().definition)
        self.register(GridFaultIsolationScenario().definition)
        self.register(RenewableGridIntegrationScenario().definition)
        self.register(PowerGridOperationScenario().definition)

    def register(self, definition: ScenarioDefinition) -> None:
        self._items[definition.name] = definition

    def resolve(self, name: str) -> ScenarioDefinition:
        normalized = (name or "").strip().lower()
        if normalized in self._items:
            return self._items[normalized]
        for item in self._items.values():
            if normalized and any(alias.lower() in normalized or normalized in alias.lower() for alias in item.aliases):
                return item
        raise UnsupportedScenarioError(f"不支持的场景: {name}")

    def infer(self, text: str, hint: str = "") -> ScenarioDefinition | None:
        combined = f"{hint} {text}".lower().strip()
        if hint:
            try:
                return self.resolve(hint)
            except UnsupportedScenarioError:
                pass
        scored: list[tuple[int, ScenarioDefinition]] = []
        for item in self._items.values():
            terms = [item.name, *item.aliases, *item.device_types, *item.standard_topics, *item.trigger_events]
            score = sum(max(1, len(term)) for term in terms if term.lower() in combined)
            if score:
                scored.append((score, item))
        return max(scored, key=lambda pair: pair[0])[1] if scored else None
