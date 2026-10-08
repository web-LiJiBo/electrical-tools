from standard_knowledge_service_v2.hybrid_reasoning import HybridReasoningEngine, ReasoningStatus, SafeRuleEngine


def test_safe_rule_engine_pass_and_fail() -> None:
    engine = SafeRuleEngine()
    assert engine.evaluate(["温升 <= 65"], {"温升": 60})[0] is ReasoningStatus.PASS
    assert engine.evaluate(["温升 <= 65"], {"温升": 70})[0] is ReasoningStatus.FAIL


def test_unknown_expression_never_defaults_to_pass() -> None:
    result = HybridReasoningEngine().decide(["执行任意Python代码()"], {})
    assert result.status is ReasoningStatus.UNCERTAIN


def test_missing_fact_is_uncertain() -> None:
    assert HybridReasoningEngine().decide(["温升 <= 65"], {}).status is ReasoningStatus.UNCERTAIN
