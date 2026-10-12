"""回归：前置条件失败/未知必须在协议载荷生成前阻断，并保留证据与审计。"""

from types import SimpleNamespace

import pytest

from standard_knowledge_service_v2.application import AnalysisPipeline
from standard_knowledge_service_v2.audit import JsonlAuditStore
from standard_knowledge_service_v2.contracts import AnalysisRequest
from standard_knowledge_service_v2.decomposition.fallback import RawTextFallback
from standard_knowledge_service_v2.domain import ClauseKnowledgeUnit, Constraint, Entity, Rule, ScenarioContext
from standard_knowledge_service_v2.instruction_engine import InstructionGenerationService, SemanticTuple
from standard_knowledge_service_v2.instruction_engine.preconditions import ActionPreconditionEvaluator
from standard_knowledge_service_v2.retrieval import RuleMatch
from standard_knowledge_service_v2.retrieval_engine import JsonClauseRepository, LocalLunwenRetrievalAdapter

CONFIG = {"device_id": "CB-01", "logical_node": "PTRC1", "data_object": "Tr.general", "protocol": "IEC61850"}
QUERY = "请生成海上风电线路跳闸候选指令"


def _pipeline(tmp_path, rules=None):
    rules = rules or [Rule("r1", "线路", "trip", "电流 >= 100", content="线路电流不小于100时应跳闸")]
    unit = ClauseKnowledgeUnit("case", "TEST", "1", "1", rules[0].content,
                               entities=[Entity("e1", "线路", "设备")], rules=rules)
    fallback = RawTextFallback()
    return AnalysisPipeline(
        LocalLunwenRetrievalAdapter(JsonClauseRepository([unit])),
        JsonlAuditStore(tmp_path / "audit.jsonl"),
        decomposer=SimpleNamespace(decompose=lambda q, s, c: fallback.decompose(q, s)),
    )


def _request(facts=None, query=QUERY):
    parameters = {"device_id": "CB-01", "device_type": "线路", "operating_state": "运行", "device_config": dict(CONFIG)}
    parameters.update(facts or {})
    return AnalysisRequest(query, "海上风电", parameters=parameters, target_protocol="IEC61850")


@pytest.mark.parametrize("facts,status,has_payload", [
    ({"电流": 120}, "generated", True),
    ({"电流": 20}, "fail", False),
    ({}, "uncertain", False),
    ({"电流": "未知"}, "uncertain", False),
    ({"电流": True}, "uncertain", False),
    ({"电流": float("nan")}, "uncertain", False),
    ({"电流": float("inf")}, "uncertain", False),
    ({"电流": "120A"}, "uncertain", False),
])
def test_pipeline_checks_actual_facts_before_payload_and_keeps_audit(tmp_path, facts, status, has_payload):
    pipeline = _pipeline(tmp_path)
    request = _request(facts)
    response = pipeline.analyze(request)
    candidate = response.data["candidate_instruction"]
    assert response.status == status
    assert bool(candidate["payload"]) is has_payload
    assert candidate["dispatch_allowed"] is False
    assert response.data["validation"]["checks"]["action_preconditions"] == candidate["precondition_status"]
    assert candidate["precondition_trace"]
    assert response.evidence[0]["quote"] == response.data["selected_rule"]["content"]
    assert candidate["explanation"] in response.data["report"]["markdown"]
    record = pipeline.audit_store.get(request.meta.request_id)
    assert record is not None
    if not has_payload:
        assert "未生成控制载荷" in candidate["explanation"]
        assert not response.data["candidate_assessments"][0]["control_eligible"]


@pytest.mark.parametrize("condition", ["", "true", "过流且保护条件满足", "电流 >= 100A"])
def test_unknown_precondition_never_generates_payload(condition):
    candidate = InstructionGenerationService().generate(
        SemanticTuple("线路", "trip", "线路", condition=condition),
        ScenarioContext("offshore_wind", "线路"), CONFIG, facts={"电流": 120},
    )
    assert not candidate.payload
    assert candidate.precondition_status == "uncertain"


def test_device_configuration_cannot_substitute_for_runtime_facts():
    candidate = InstructionGenerationService().generate(
        SemanticTuple("线路", "trip", "线路", condition="电流 >= 100"),
        ScenarioContext("offshore_wind", "线路"), {**CONFIG, "电流": 120},
    )
    assert not candidate.payload
    assert candidate.precondition_status == "uncertain"


def test_direct_service_does_not_route_blocked_instruction(monkeypatch):
    service = InstructionGenerationService()
    monkeypatch.setattr(service.router, "generate", lambda *args: pytest.fail("条件失败不应调用协议适配器"))
    candidate = service.generate(
        SemanticTuple("线路", "trip", "线路", condition="电流 >= 100"),
        ScenarioContext("offshore_wind", "线路"), CONFIG, facts={"电流": 20},
    )
    assert not candidate.payload
    assert candidate.precondition_status == "fail"


def test_symbolic_threshold_requires_actual_fact():
    evaluator = ActionPreconditionEvaluator()
    assert evaluator.evaluate("电流 >= 额定值", {"电流": 120, "额定值": 100}).status.value == "pass"
    assert evaluator.evaluate("电流 >= 额定值", {"电流": 120}).status.value == "uncertain"
    assert evaluator.evaluate("电流 >= 额定值", {"电流": 120, "额定值": None}).status.value == "uncertain"


def test_boolean_enable_condition_is_supported_but_not_numeric_boolean():
    evaluator = ActionPreconditionEvaluator()
    assert evaluator.evaluate("使能 == true", {"使能": True}).status.value == "pass"
    assert evaluator.evaluate("使能 == true", {"使能": False}).status.value == "fail"
    assert evaluator.evaluate("电流 == 1", {"电流": True}).status.value == "uncertain"


def test_lower_rank_applicable_rule_is_preferred_over_failed_trigger(tmp_path):
    pipeline = _pipeline(tmp_path)
    blocked = Rule("r1", "线路", "trip", "电流 >= 200", content="线路电流不小于200时应跳闸")
    allowed = Rule("r2", "线路", "trip", "电流 >= 100", content="线路电流不小于100时应跳闸")
    matches = [RuleMatch(blocked, rank=1, combined_score=1.0), RuleMatch(allowed, rank=2, combined_score=0.4)]
    request = _request({"电流": 120})
    if hasattr(pipeline, "intent_classifier"):
        selected, assessments = pipeline._select_rule(request, matches, ["trip"], for_control=True)
    else:
        selected, assessments = pipeline._select_rule(request, matches)
    assert selected.rule.rule_id == "r2"
    assert next(item for item in assessments if item["rule_id"] == "r1")["control_eligible"] is False


def test_constraint_violation_can_trigger_alarm_without_becoming_a_block(tmp_path):
    rule = Rule("r1", "线路", "alarm", "温升 > 65",
                constraints=[Constraint("raw_constraint", "", "温升 <= 65", role="compliance")],

                content="线路温升超过65时应告警")
    pipeline = _pipeline(tmp_path, [rule])
    response = pipeline.analyze(_request({"温升": 70}, query="请生成海上风电线路温升告警候选指令"))
    assert response.status == "generated"
    assert response.data["candidate_instruction"]["payload"]["requested_action"] == "alarm"
    assert response.data["candidate_instruction"]["precondition_status"] == "pass"
    assert response.data["candidate_assessments"][0]["reasoning"]["status"] == "fail"
    assert response.data["candidate_instruction"]["dispatch_allowed"] is False


@pytest.mark.parametrize("role,enabled,status", [
    ("precondition", False, "fail"),
    ("precondition", True, "generated"),
    ("unspecified", True, "uncertain"),
    ("compliance", False, "generated"),
])
def test_constraint_role_determines_action_eligibility(tmp_path, role, enabled, status):
    rule = Rule("r1", "线路", "trip", "电流 >= 100",
                constraints=[Constraint("raw_constraint", "", "允许跳闸 == true", role=role)],
                content="线路电流不小于100且允许操作时跳闸")
    response = _pipeline(tmp_path, [rule]).analyze(_request({"电流": 120, "允许跳闸": enabled}))
    assert response.status == status
    assert bool(response.data["candidate_instruction"]["payload"]) is (status == "generated")


def test_json_constraint_role_is_preserved(tmp_path):
    import json
    data = {"entities": [{"name": "线路"}], "rules": [{
        "content": "线路发生过流且允许操作时跳闸", "subject": "线路", "action": "trip",
        "condition": "电流 >= 100", "constraint": "允许跳闸 == true", "constraint_role": "precondition",
    }]}
    (tmp_path / "rule.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    adapter = LocalLunwenRetrievalAdapter.from_dataset(tmp_path)
    assert adapter.repository.units[0].rules[0].constraints[0].role == "precondition"
    pipeline = AnalysisPipeline(adapter)
    assert pipeline.extractor.extract_rule(adapter.repository.units[0].rules[0]).constraints[0]["role"] == "precondition"
