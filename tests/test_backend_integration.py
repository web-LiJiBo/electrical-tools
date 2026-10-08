import json

from standard_knowledge_service_v2.consistency_evaluation import ConsistencyEvaluationService
from standard_knowledge_service_v2.hybrid_reasoning import HybridReasoningEngine, ReasoningStatus


def test_clause_consistency_flows_into_hybrid_decision() -> None:
    consistency = ConsistencyEvaluationService().compare("温升不大于65K", "温升不得大于65K")
    result = HybridReasoningEngine().decide(["温升 <= 65"], {"温升": 60}, consistency=consistency)
    assert result.status is ReasoningStatus.PASS
    json.dumps(result.to_dict(), ensure_ascii=False)
