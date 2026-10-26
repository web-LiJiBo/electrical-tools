import json

import pytest

from standard_knowledge_service_v2.retrieval_engine.clause_retriever import JsonClauseRepository


def _valid_payload():
    return {
        "standard_id": "TEST-2026",
        "chapter_path": "1.1",
        "entities": [{"name": "断路器", "type": "设备"}],
        "rules": [{"content": "断路器应定期检查。"}],
    }


def test_repository_reports_loaded_and_skipped_files(tmp_path):
    (tmp_path / "good.json").write_text(json.dumps(_valid_payload(), ensure_ascii=False), encoding="utf-8")
    (tmp_path / "bad.json").write_text("{not-json", encoding="utf-8")

    repository = JsonClauseRepository.from_directory(tmp_path)

    assert len(repository.units) == 1
    assert repository.load_report["files_seen"] == 2
    assert repository.load_report["loaded"] == 1
    assert repository.load_report["skipped"] == 1
    assert repository.load_report["error_samples"][0]["path"] == "bad.json"


def test_repository_fails_when_every_json_is_invalid(tmp_path):
    (tmp_path / "broken.json").write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="JSON文件全部加载失败"):
        JsonClauseRepository.from_directory(tmp_path)
