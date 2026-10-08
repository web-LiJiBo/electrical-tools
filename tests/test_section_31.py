from standard_knowledge_service_v2.contracts import AnalysisRequest
from standard_knowledge_service_v2.decomposition import DomainTermNormalizer, LocalQwenDecomposer, RawTextFallback
from standard_knowledge_service_v2.decomposition.models import DecompositionResult
from standard_knowledge_service_v2.scenarios import ScenarioContextBuilder


def test_analysis_request_requires_non_empty_query() -> None:
    try:
        AnalysisRequest("  ")
    except ValueError:
        return
    raise AssertionError("空查询必须被拒绝")


def test_fallback_only_extracts_explicit_facts() -> None:
    result = RawTextFallback().decompose("海上风电35kV集电线路跳闸，依据DL/T 1234-2025")
    assert result.source == "raw_text_fallback"
    assert any(item["standard_id"] == "DL/T1234-2025" for item in result.standard_refs)
    assert "trip" in result.actions
    assert any(item.name == "设备控制配置" for item in result.missing_fields)


def test_normalizer_normalizes_action_entity_and_unit() -> None:
    raw = DecompositionResult(
        entities=[{"name": "主变", "type": "设备", "desc": ""}], actions=["跳闸"],
        constraints=[{"parameter": "电压", "operator": "不大于", "value": "35", "unit": "kV"}], valid=True,
    )
    result = DomainTermNormalizer().normalize(raw)
    assert result.entities[0]["name"] == "电力变压器"
    assert result.actions == ["trip"]
    assert result.constraints[0]["value"] == 35000.0 and result.constraints[0]["unit"] == "V"


def test_offshore_wind_context_reports_required_parameters() -> None:
    parsed = RawTextFallback().decompose("海上风电集电线路跳闸")
    built = ScenarioContextBuilder().build(parsed)
    assert built.context.scenario == "offshore_wind"
    assert {item.name for item in built.missing_fields} >= {"device_id", "operating_state"}


def test_local_qwen_failure_uses_safe_fallback() -> None:
    result = LocalQwenDecomposer().decompose("变压器温升不大于65K")
    assert result.source == "raw_text_fallback"
    assert result.valid
