"""大纲级契约烟雾测试，不宣称算法能力已实现。"""

from standard_knowledge_service_v2.contracts import APIResponse, SearchRequest
from standard_knowledge_service_v2.domain import ClauseKnowledgeUnit, DecisionStatus
from standard_knowledge_service_v2.retrieval import (
    LLMDecompositionOutput,
    LunwenMatchingInput,
)
from standard_knowledge_service_v2.llm_decomposition import (
    DEFAULT_MODEL_PATH,
    extract_json_object,
    validate_decomposition,
)


def test_search_request_has_trace_id() -> None:
    request = SearchRequest(query="变压器短路能力")
    assert request.meta.request_id


def test_clause_unit_preserves_version_and_source() -> None:
    unit = ClauseKnowledgeUnit(
        clause_id="c1",
        standard_id="GB/T example",
        version="2026",
        chapter_path="5.1",
        text="示例条款",
        source_uri="example.xlsx",
    )
    assert unit.version == "2026"
    assert unit.source_uri


def test_uncertain_is_first_class_status() -> None:
    assert DecisionStatus.UNCERTAIN.value == "uncertain"


def test_api_response_is_json_ready() -> None:
    response = APIResponse(request_id="r1", status="success")
    assert response.to_dict()["request_id"] == "r1"


def test_lunwen_matching_uses_report_parameters() -> None:
    request = LunwenMatchingInput(clause_text="变压器绕组温升不应超过65K")
    assert request.top_k_entities == 26
    assert request.top_k_rules == 22
    assert request.vector_weight == 0.8
    assert request.structural_weight == 0.2


def test_llm_decomposition_maps_to_lunwen_entities() -> None:
    result = LLMDecompositionOutput(
        intent="compliance",
        entities=[{"name": "变压器", "type": "电力设备"}],
        valid=True,
    )
    assert result.to_lunwen_parsed_json()["entities"][0]["name"] == "变压器"


def test_qwen_model_path_points_to_snapshot() -> None:
    assert DEFAULT_MODEL_PATH.name == "master"
    assert (DEFAULT_MODEL_PATH / "config.json").is_file()


def test_qwen_json_is_parsed_and_validated_without_loading_model() -> None:
    parsed = extract_json_object(
        '```json\n{"intent":"search","entities":[{"name":"变压器","type":"设备"}],'
        '"actions":[],"constraints":[],"standard_refs":[],"scenario":{},'
        '"keywords":["变压器"],"confidence":0.9}\n```'
    )
    result = validate_decomposition(parsed)
    assert result.valid
    assert result.entities[0]["name"] == "变压器"


def test_copied_lunwen_matching_models_and_dataset_exist() -> None:
    project_root = DEFAULT_MODEL_PATH.parents[4]
    assert (project_root / "models/embedding/finetuned_sbert/config.json").is_file()
    assert (project_root / "models/embedding/sbert/config.json").is_file()
    assert (project_root / "datasets/lunwen/data/2017.xlsx").is_file()
    assert any((project_root / "datasets/lunwen/output_jsons_new/train").glob("*.json"))
