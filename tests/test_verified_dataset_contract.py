"""核验数据集的发布门禁：防止文件丢失、空规则和审计基线漂移。"""

import json
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERIFIED_ROOT = PROJECT_ROOT / "datasets" / "lunwen" / "verified_json"
pytestmark = pytest.mark.data


def test_verified_dataset_count_matches_audit_summary() -> None:
    summary = json.loads((VERIFIED_ROOT / "audit_summary.json").read_text(encoding="utf-8"))
    files = list((VERIFIED_ROOT / "json").glob("*.json"))
    assert summary["expected_json_files"] == 6674
    assert summary["generated_json_files"] == len(files) == 6674
    assert summary["split_content_mismatch_count"] == 0
    assert sum(summary["status_counts"].values()) == summary["source_clause_cells"]


def test_every_verified_json_has_nonempty_original_rule_content() -> None:
    failures: list[str] = []
    for path in (VERIFIED_ROOT / "json").glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        rules = payload.get("rules", [])
        if not rules or any(not isinstance(rule, dict) or not str(rule.get("content", "")).strip() for rule in rules):
            failures.append(path.name)
    assert not failures, f"规则正文为空或缺失: {failures[:20]}"


def test_manual_review_records_are_explicitly_counted() -> None:
    summary = json.loads((VERIFIED_ROOT / "audit_summary.json").read_text(encoding="utf-8"))
    assert summary["manual_review_count"] == 961
    assert summary["status_counts"]["needs_manual_review"] == 622
    assert summary["status_counts"]["created_missing_decomposition"] == 330
    assert summary["status_counts"]["corrected_to_source_faithful_rule"] == 43
