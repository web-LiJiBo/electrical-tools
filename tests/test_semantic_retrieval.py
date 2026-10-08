import json

from standard_knowledge_service_v2.retrieval import LunwenMatchingInput
from standard_knowledge_service_v2.retrieval_engine import LocalLunwenRetrievalAdapter


def test_decomposition_focus_terms_improve_rule_ranking_and_normalize_action(tmp_path) -> None:
    neutral = {
        "entities": [{"name": "主变压器", "type": "设备"}],
        "rules": [{
            "content": "主变压器中性点接地部位应增加绝缘防护措施",
            "subject": "主变压器", "action": "增加防护措施", "condition": "中性点接地",
        }],
    }
    relevant = {
        "entities": [{"name": "主变压器", "type": "设备"}, {"name": "温升异常", "type": "故障"}],
        "rules": [{
            "content": "主变压器发生温升异常时应立即告警并开展检查",
            "subject": "主变压器", "action": "发出告警", "condition": "温升异常",
        }],
    }
    (tmp_path / "a.json").write_text(json.dumps(neutral, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps(relevant, ensure_ascii=False), encoding="utf-8")
    adapter = LocalLunwenRetrievalAdapter.from_dataset(tmp_path)
    result = adapter.match(LunwenMatchingInput(
        "主变压器异常时如何处理",
        {
            "entities": [{"name": "主变压器"}],
            "actions": ["alarm"],
            "keywords": ["温升异常", "告警"],
            "scenario": {"scenario_type": "substation_maintenance"},
        },
        top_k_rules=2,
    ))
    assert result.rules[0].rule.content == relevant["rules"][0]["content"]
    assert result.rules[0].rule.action == "alarm"


def test_requested_action_promotes_matching_rule(tmp_path) -> None:
    payload = {
        "entities": [{"name": "线路", "type": "设备"}],
        "rules": [
            {"content": "线路应满足一般运行要求", "subject": "线路", "action": "检查", "condition": "运行中"},
            {"content": "线路过流且保护条件满足时应跳闸", "subject": "线路", "action": "发出跳闸命令", "condition": "过流"},
        ],
    }
    (tmp_path / "rules.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    adapter = LocalLunwenRetrievalAdapter.from_dataset(tmp_path)
    result = adapter.match(LunwenMatchingInput(
        "线路发生过流时应跳闸",
        {"entities": [{"name": "线路", "type": "设备"}], "actions": ["trip"], "keywords": ["过流", "跳闸"]},
    ))
    assert result.rules[0].rule.action == "trip"
