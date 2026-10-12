"""Exercise advertised inputs against the latest repository without LLM calls."""
import json
import os
from pathlib import Path

from standard_knowledge_service_v2.bootstrap import build_application
from standard_knowledge_service_v2.contracts import AnalysisRequest
from standard_knowledge_service_v2.knowledge_graph.current_graph import export_current_graph
from standard_knowledge_service_v2.knowledge_graph.question_catalog import available_questions


def main():
    root = Path(__file__).resolve().parents[1]
    name = "ELECTRICAL_TOOLS_OFFLINE_UNUSED_KEY"
    previous = os.environ.pop(name, None)
    try:
        pipeline = build_application(root / "configs/settings.offline.yaml")
        pipeline.facade.audit_store = None
        output = root / "artifacts/knowledge_graph/current"
        summary = export_current_graph(pipeline, output)
        files = sum(len(list(Path(d).glob("*.json"))) for d in summary["source_directories"])
        if files != summary["documents"]:
            raise AssertionError("Some source files were skipped by the repository loader")
        catalog = available_questions(pipeline.facade)
        before = pipeline.facade.simulation_session.snapshot()
        results = []
        for case in catalog["cases"]:
            response = pipeline.facade.analyze(AnalysisRequest(case["query"], case["scenario_hint"], parameters=case["parameters"])).to_dict()
            candidate = response["data"].get("candidate_instruction")
            checks = {"expected_status": response["status"] == case["expected_status"],
                "no_control_payload": not (candidate or {}).get("payload"),
                "no_dispatch": not (candidate or {}).get("dispatch_allowed"),
                "state_unchanged": before == pipeline.facade.simulation_session.snapshot()}
            if case.get("expected_clause_id"):
                path = response["data"].get("knowledge_graph_evidence", {})
                checks["graph_source"] = bool(path) and case["expected_clause_id"] in path["path"][0]
            if case.get("expected_term"):
                checks["answer_contains_source_term"] = case["expected_term"] in response["data"].get("answer", {}).get("text", "")
            if case.get("expected_assessment"):
                checks["expected_assessment"] = response["data"].get("device_assessment", {}).get("status") == case["expected_assessment"]
            passed = all(checks.values())
            results.append({"case": case, "checks": checks, "passed": passed, "response": response})
            print(case["case_id"], response["status"], "PASS" if passed else "FAIL", flush=True)
        report = {"graph": summary, "mode": "offline_no_external_model_no_dispatch",
                  "passed": all(r["passed"] for r in results), "cases": results}
        for filename, value in (("question_catalog.json", catalog), ("question_verification.json", report)):
            (output / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        if not report["passed"]:
            raise AssertionError("Advertised questions failed: inspect question_verification.json")
        print(json.dumps(summary, ensure_ascii=False), flush=True)
    finally:
        if previous is not None:
            os.environ[name] = previous


if __name__ == "__main__":
    main()
