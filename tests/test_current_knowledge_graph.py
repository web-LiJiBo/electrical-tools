import json
from pathlib import Path
from types import SimpleNamespace

from standard_knowledge_service_v2.domain import ClauseKnowledgeUnit, Entity, Rule
from standard_knowledge_service_v2.knowledge_graph.current_graph import CurrentKnowledgeGraph, export_current_graph
from standard_knowledge_service_v2.knowledge_graph.question_catalog import available_questions
from standard_knowledge_service_v2.application.analysis_pipeline import AnalysisPipeline
from standard_knowledge_service_v2.contracts import AnalysisRequest
from standard_knowledge_service_v2.decomposition import RawTextFallback
from standard_knowledge_service_v2.retrieval_engine.clause_retriever import JsonClauseRepository
from standard_knowledge_service_v2.retrieval_engine.lunwen_adapter import LocalLunwenRetrievalAdapter


def test_graph_source_path_and_metadata_not_entities(tmp_path):
    source = tmp_path / "source.json"
    source.write_text('{"metadata":{"secret":"not a rule"}}', encoding="utf-8")
    unit = ClauseKnowledgeUnit("c1", "GB 1", "2020", "6.2", "5到40度",
        [Entity("e1", "空气压缩机", "设备")], [Rule("r1", "空气压缩机", "", "", content="5到40度")],
        source_uri=str(source), metadata={"secret": "not a rule"})
    graph = CurrentKnowledgeGraph([unit])
    path = graph.evidence_path("r1")
    assert path["quote"] == "5到40度" and path["chapter_path"] == "6.2"
    assert path["grants_control_permission"] is False
    assert graph.neighbors("空气压缩机") == [("HAS_RULE", "5到40度")]
    app = SimpleNamespace(facade=SimpleNamespace(knowledge_graph=graph,
        retriever=SimpleNamespace(repository=SimpleNamespace(units=[unit]))))
    summary = export_current_graph(app, tmp_path / "export")
    assert summary["source_file_count"] == 1 and summary["neo4j_imported"] is False
    exported = json.loads((tmp_path / "export/graph.json").read_text(encoding="utf-8"))
    assert "secret" not in json.dumps(exported)


def test_missing_catalog_sources_not_advertised():
    pipeline = SimpleNamespace(knowledge_graph=CurrentKnowledgeGraph([]),
        retriever=SimpleNamespace(repository=SimpleNamespace(units=[])))
    assert [c["case_id"] for c in available_questions(pipeline)["cases"]] == ["breaker-no-source"]


def test_informational_query_not_control_and_explicit_filter(tmp_path):
    payload = {"standard_id": "GB 19153-2019", "chapter_path": "6.2",
        "entities": [{"name": "空气压缩机", "type": "设备"}],
        "rules": [{"content": "空气压缩机能效试验吸气温度5 ℃~40 ℃", "subject": "空气压缩机",
                   "action": "", "condition": "", "constraint_role": "informational"}]}
    (tmp_path / "c.json").write_text(json.dumps(payload), encoding="utf-8")
    retriever = LocalLunwenRetrievalAdapter(JsonClauseRepository.from_directory(tmp_path))
    pipeline = AnalysisPipeline(retriever, decomposer=RawTextFallback())
    pipeline.knowledge_graph = CurrentKnowledgeGraph(retriever.repository.units)
    result = pipeline.analyze(AnalysisRequest("空气压缩机能效试验吸气温度范围是多少？",
        parameters={"standard_id": "GB 19153-2019", "chapter_path": "6.2"}))
    assert result.status == "answered"
    assert result.data["candidate_instruction"] is None
    assert result.data["knowledge_graph_evidence"]["quote"] == payload["rules"][0]["content"]
    absent = pipeline.analyze(AnalysisRequest("空气压缩机能效试验吸气温度范围是多少？",
        parameters={"standard_id": "NOT-PRESENT"}))
    assert absent.status == "uncertain" and not absent.evidence


def test_title_cannot_be_selected_as_answer(tmp_path):
    payload = {"entities": [{"name": "温室排放", "type": "对象"}],
               "rules": [{"subject": "温室排放", "content": "9.1 温室排放", "operation": "仅标题"}]}
    (tmp_path / "c.json").write_text(json.dumps(payload), encoding="utf-8")
    pipeline = AnalysisPipeline(LocalLunwenRetrievalAdapter(JsonClauseRepository.from_directory(tmp_path)),
                                decomposer=RawTextFallback())
    assert pipeline.analyze(AnalysisRequest("温室排放有哪些要求？")).status == "uncertain"
