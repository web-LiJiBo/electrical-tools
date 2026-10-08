from standard_knowledge_service_v2.consistency_evaluation import ConsistencyEvaluationService
from standard_knowledge_service_v2.consistency_evaluation.numeric_constraints import numeric_constraint_similarity


def test_equivalent_units_and_constraints_match() -> None:
    assert numeric_constraint_similarity("电压不大于1kV", "电压不得大于1000V") == 1.0


def test_conflicting_numeric_constraints_are_reported() -> None:
    result = ConsistencyEvaluationService().compare("温升不大于65K", "温升不小于80K")
    assert not result.consistent
    assert any(item["type"] == "numeric_constraint" for item in result.conflicts)


def test_same_clause_is_consistent() -> None:
    result = ConsistencyEvaluationService().compare("设备接地电阻不大于4Ω", "设备接地电阻不大于4Ω")
    assert result.consistent
