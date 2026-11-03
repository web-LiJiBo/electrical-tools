from pathlib import Path

import pytest

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


def test_project_attention_checkpoint_loads_and_runs() -> None:
    checkpoint = Path("models/consistency/classifier_model/attention_model.pt")
    service = ConsistencyEvaluationService(checkpoint)

    result = service.compare("温升不大于65K", "温升不得大于65K")

    assert service.backend == "TorchAttentionClassifier"
    assert result.model == "lunwen-attention-model"
    assert len(result.attention_weights) == 3


def test_configured_attention_checkpoint_never_silently_falls_back(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="注意力模型文件不存在"):
        ConsistencyEvaluationService(tmp_path / "missing.pt")
