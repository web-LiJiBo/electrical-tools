from standard_knowledge_service_v2.decomposition import DomainTermNormalizer, RawTextFallback
from standard_knowledge_service_v2.decomposition.models import DecompositionResult
from standard_knowledge_service_v2.domain import ScenarioContext
from standard_knowledge_service_v2.instruction_engine import InstructionGenerationService, SemanticTuple
from standard_knowledge_service_v2.scenarios import ScenarioContextBuilder, ScenarioRegistry


def test_registry_contains_all_typical_scenarios() -> None:
    registry = ScenarioRegistry()
    expected = {
        "海上风电": "offshore_wind",
        "变电站设备运维": "substation_maintenance",
        "电网故障隔离": "grid_fault_isolation",
        "新能源并网": "renewable_grid_integration",
        "电网调度运行": "power_grid_operation",
    }
    assert {label: registry.resolve(label).name for label in expected} == expected


def test_offline_fallback_infers_all_typical_scenarios() -> None:
    cases = {
        "海上风电集电线路发生过流": "offshore_wind",
        "主变压器顶层油温允许是多少": "substation_maintenance",
        "输电线路发生短路后进行故障隔离": "grid_fault_isolation",
        "光伏电站并网需要满足哪些条件": "renewable_grid_integration",
        "电网调度发生频率偏差如何调节有功": "power_grid_operation",
    }
    builder = ScenarioContextBuilder()
    fallback = RawTextFallback()
    for query, expected in cases.items():
        assert builder.build(fallback.decompose(query)).context.scenario == expected


def test_scenario_models_include_operational_and_protocol_details() -> None:
    registry = ScenarioRegistry()
    for name in (
        "offshore_wind", "substation_maintenance", "grid_fault_isolation",
        "renewable_grid_integration", "power_grid_operation",
    ):
        definition = registry.resolve(name)
        assert definition.device_types
        assert definition.parameters
        assert definition.operating_states
        assert definition.trigger_events
        assert definition.state_transitions
        assert {item.protocol for item in definition.protocol_capabilities} == {"IEC61850", "Modbus"}
        assert definition.risk_controls


def test_each_new_scenario_reports_its_required_parameters() -> None:
    cases = [
        ("变电站设备运维", {"device_id", "device_type", "operating_state"}),
        ("电网故障隔离", {"device_id", "fault_type", "fault_location", "operating_state"}),
        ("新能源并网", {"plant_id", "generation_type", "connection_voltage", "operating_state"}),
        ("电网调度运行", {"control_area", "operating_state", "dispatch_target"}),
    ]
    for hint, required in cases:
        parsed = RawTextFallback().decompose(hint, hint)
        built = ScenarioContextBuilder().build(parsed, scenario_hint=hint)
        assert {item.name for item in built.missing_fields} >= required


def test_new_business_actions_are_normalized() -> None:
    raw = DecompositionResult(
        actions=["闭锁", "复归", "并网", "解列", "调有功", "调无功", "调压", "减载", "恢复供电"],
        valid=True,
    )
    assert DomainTermNormalizer().normalize(raw).actions == [
        "lockout", "reset", "connect_grid", "disconnect_grid", "adjust_active_power",
        "adjust_reactive_power", "regulate_voltage", "load_shedding", "restore_power",
    ]


def test_free_text_action_is_mapped_to_standard_action_code() -> None:
    raw = DecompositionResult(
        actions=["处理主变压器温升异常"],
        scenario={"device_type": "主变"},
        valid=True,
    )
    assert DomainTermNormalizer().normalize(raw).actions == ["alarm"]
    assert DomainTermNormalizer().normalize(raw).scenario["device_type"] == "电力变压器"


def test_controllable_actions_have_candidate_protocol_mappings() -> None:
    service = InstructionGenerationService()
    cases = [
        ("substation_maintenance", "lockout"),
        ("grid_fault_isolation", "isolate"),
        ("renewable_grid_integration", "limit_power"),
        ("power_grid_operation", "adjust_active_power"),
    ]
    iec_config = {"device_id": "IED-01", "logical_node": "CSWI1", "data_object": "Pos", "protocol": "IEC61850"}
    for scenario, action in cases:
        candidate = service.generate(SemanticTuple("设备", action, "设备"), ScenarioContext(scenario), iec_config)
        assert candidate.payload["requested_action"] == action
        assert candidate.protocol == "IEC61850"
        assert candidate.dispatch_allowed is False


def test_manual_maintenance_action_does_not_generate_control_frame() -> None:
    candidate = InstructionGenerationService().generate(
        SemanticTuple("变压器", "maintain", "变压器"),
        ScenarioContext("substation_maintenance"),
        {"device_id": "T1", "logical_node": "YPTR1", "data_object": "Health"},
        "IEC61850",
    )
    assert not candidate.payload
    assert candidate.missing_fields == ["instruction_template"]
    assert candidate.dispatch_allowed is False
