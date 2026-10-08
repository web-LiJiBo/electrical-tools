from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..decomposition.models import DecompositionResult, MissingField
from ..domain import ScenarioContext
from .models import ScenarioDefinition
from .registry import ScenarioRegistry


@dataclass(slots=True)
class ScenarioContextBuildResult:
    context: ScenarioContext
    definition: ScenarioDefinition | None
    missing_fields: list[MissingField] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class ScenarioContextBuilder:
    def __init__(self, registry: ScenarioRegistry | None = None) -> None:
        self.registry = registry or ScenarioRegistry()

    def build(self, decomposition: DecompositionResult, parameters: dict[str, Any] | None = None, scenario_hint: str = "", caller: str = "") -> ScenarioContextBuildResult:
        values = dict(parameters or {})
        scenario_data = decomposition.scenario
        scenario_name = str(scenario_data.get("scenario_type") or scenario_hint or "").strip()
        inference_text = " ".join(decomposition.keywords + [str(item.get("name", "")) for item in decomposition.entities] + [str(scenario_data.get("device_type", "")), str(values.get("device_type", "")), str(values.get("generation_type", "")), str(values.get("dispatch_target", "")), scenario_name])
        definition = self.registry.infer(inference_text, scenario_hint)
        if definition:
            scenario_name = definition.name
        context = ScenarioContext(
            scenario=scenario_name or "general",
            device_type=str(scenario_data.get("device_type") or values.get("device_type") or ""),
            voltage_level=str(scenario_data.get("voltage_level") or values.get("voltage_level") or ""),
            operating_condition=str(scenario_data.get("operating_condition") or values.get("operating_condition") or ""),
            operation_type=str((decomposition.actions[0] if decomposition.actions else "") or scenario_data.get("operation_type") or ""),
            parameters=values,
            caller=caller,
        )
        missing = list(decomposition.missing_fields)
        warnings: list[str] = []
        if definition:
            for name in definition.required_parameters:
                if values.get(name) in (None, ""):
                    missing.append(MissingField(name, f"{definition.name}场景必填参数缺失", "场景适用性和候选指令生成"))
            if context.operation_type and context.operation_type not in definition.allowed_actions:
                warnings.append(f"动作{context.operation_type}不在{definition.name}场景允许动作集内")
            device_text = context.device_type.replace("设备", "")
            device_match = any(context.device_type in item or item in context.device_type for item in definition.device_types)
            # 允许“电力变压器—换流变压器—主变压器”等上位类与具体设备兼容。
            if not device_match and "变压器" in device_text:
                device_match = any("变压器" in item for item in definition.device_types)
            if context.device_type and definition.device_types and not device_match:
                warnings.append(f"设备类型{context.device_type}不在{definition.name}场景设备范围内")
            operating_state = str(values.get("operating_state", "")).strip()
            if operating_state and definition.operating_states and operating_state not in definition.operating_states:
                warnings.append(f"运行状态{operating_state}不在{definition.name}场景状态集中")
        else:
            warnings.append("未匹配到已注册业务场景，按通用检索上下文处理")
        return ScenarioContextBuildResult(context, definition, self._deduplicate(missing), warnings)

    @staticmethod
    def _deduplicate(items: list[MissingField]) -> list[MissingField]:
        result: list[MissingField] = []
        seen: set[str] = set()
        for item in items:
            if item.name not in seen:
                seen.add(item.name)
                result.append(item)
        return result
