from standard_knowledge_service_v2.domain import ClauseKnowledgeUnit, Constraint, Rule, ScenarioContext
from standard_knowledge_service_v2.instruction_engine import InstructionGenerationService, SemanticExtractor
from standard_knowledge_service_v2.instruction_engine.ilr_compiler import ILRCompiler
from standard_knowledge_service_v2.instruction_engine.swrl_compiler import SwrlCompiler


def _semantic():
    unit = ClauseKnowledgeUnit("c1", "DL/T 1", "2025", "5.1", "集电线路发生过流时应跳闸")
    rule = Rule("r1", "集电线路", "trip", "电流 >= 额定值", [Constraint("电流", ">=", 100, "A")])
    return SemanticExtractor().extract_rule(rule, unit)


def test_rule_is_extracted_to_semantic_tuple_with_evidence() -> None:
    semantic = _semantic()
    assert semantic.action == "trip"
    assert semantic.constraints[0]["unit"] == "A"
    assert semantic.evidence[0].clause_id == "c1"


def test_semantic_tuple_compiles_to_traceable_ilr_and_swrl() -> None:
    semantic = _semantic()
    program = ILRCompiler().compile(semantic)
    assert program.source_rule_ids == ["r1"]
    assert program.actions[0]["action"] == "trip"
    assert program.dynamic_behaviors[0].action == "trip"
    assert program.constraint_rules[0]["then"]["action"] == "trip"
    assert program.swrl_rules and "RequiresAction" in program.swrl_rules[0]
    assert "trip" in SwrlCompiler().compile(semantic)
    assert SwrlCompiler().compile_if_then(semantic).startswith("IF ")


def test_missing_protocol_configuration_never_generates_control_frame() -> None:
    context = ScenarioContext("offshore_wind", "集电线路")
    candidate = InstructionGenerationService().generate(_semantic(), context, {}, "IEC61850")
    assert {"device_id", "logical_node", "data_object"} <= set(candidate.missing_fields)
    assert not candidate.payload and not candidate.dispatch_allowed


def test_complete_iec61850_config_generates_candidate_only() -> None:
    context = ScenarioContext("offshore_wind", "集电线路")
    config = {"device_id": "CB-01", "logical_node": "PTRC1", "data_object": "Tr.general", "protocol": "IEC61850"}
    candidate = InstructionGenerationService().generate(_semantic(), context, config)
    assert candidate.payload["service"] == "MMS"
    assert candidate.target == "CB-01"
    assert candidate.dispatch_allowed is False


def test_modbus_candidate_requires_mapping_and_is_not_dispatchable() -> None:
    context = ScenarioContext("offshore_wind", "集电线路")
    config = {"device_id": "CB-01", "slave_id": 1, "coil_address": 12}
    candidate = InstructionGenerationService().generate(_semantic(), context, config, "Modbus")
    assert candidate.payload["function_code"] == 5
    assert candidate.dispatch_allowed is False
