"""Verify every advertised question against the loaded JSON, without API or dispatch."""
import json
from pathlib import Path

from standard_knowledge_service_v2.bootstrap import build_application
from standard_knowledge_service_v2.contracts import AnalysisRequest
from standard_knowledge_service_v2.decomposition import RawTextFallback
from standard_knowledge_service_v2.knowledge_graph.question_catalog import available_questions
from standard_knowledge_service_v2.data_ingestion.supplemental_excel import _write_json


def main():
    root = Path(__file__).resolve().parents[1]
    pipeline = build_application(root / "configs/settings.offline.yaml").facade
    pipeline.decomposer = RawTextFallback()  # Explicitly prohibit remote model calls.
    pipeline.audit_store = None
    catalog = available_questions(pipeline)
    before = pipeline.simulation_session.snapshot()
    results = []
    for case in catalog["cases"]:
        response = pipeline.analyze(AnalysisRequest(case["query"], case["scenario_hint"],
                                                    parameters=case["parameters"]))
        candidate = response.data.get("candidate_instruction")
        source_ids = {e.get("clause_id") for e in response.evidence}
        checks = {"status": response.status == case["expected_status"],
                  "no_control": candidate is None,
                  "source": not case.get("expected_clause_id") or case["expected_clause_id"] in source_ids,
                  "term": not case.get("expected_term") or case["expected_term"] in response.data.get("answer", {}).get("text", ""),
                  "assessment": not case.get("expected_assessment") or response.data.get("device_assessment", {}).get("status") == case["expected_assessment"]}
        results.append({"case": case, "checks": checks, "response": response.to_dict()})
        print(case["case_id"], response.status, checks)
    unchanged = before == pipeline.simulation_session.snapshot()
    passed = unchanged and all(all(r["checks"].values()) for r in results)
    path = root.parent / "补充标准条款/测试样例/最新知识可用问题验证.json"
    _write_json(path, {"mode": "offline_raw_text_no_dispatch", "database_units": len(pipeline.retriever.repository.units),
                      "catalog": catalog, "simulation_state_unchanged": unchanged, "passed": passed,
                      "cases": results, "scope": "来源约束下的问答和局部参数判定；不代表在线模型、真实设备或控制闭环验收"})
    print(json.dumps({"passed": passed, "case_count": len(results), "output": str(path)}, ensure_ascii=False))
    if not passed:
        raise AssertionError("Advertised question did not meet its source-grounded contract")


if __name__ == "__main__":
    main()
