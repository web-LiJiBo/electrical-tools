from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ScenarioParameter:
    name: str
    label: str
    value_type: str = "string"
    unit: str = ""
    required: bool = False
    description: str = ""


@dataclass(frozen=True, slots=True)
class StateTransition:
    source: str
    trigger: str
    target: str
    action: str
    requires_confirmation: bool = True


@dataclass(frozen=True, slots=True)
class ProtocolCapability:
    protocol: str
    actions: tuple[str, ...]
    required_fields: tuple[str, ...]
    logical_nodes: tuple[str, ...] = ()


@dataclass(slots=True)
class ScenarioDefinition:
    name: str
    aliases: list[str]
    required_parameters: list[str]
    allowed_actions: list[str]
    safety_level: str
    standard_topics: list[str] = field(default_factory=list)
    device_types: list[str] = field(default_factory=list)
    parameters: list[ScenarioParameter] = field(default_factory=list)
    operating_states: list[str] = field(default_factory=list)
    trigger_events: list[str] = field(default_factory=list)
    state_transitions: list[StateTransition] = field(default_factory=list)
    protocol_capabilities: list[ProtocolCapability] = field(default_factory=list)
    risk_controls: list[str] = field(default_factory=list)
