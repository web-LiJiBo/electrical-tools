from standard_knowledge_service_v2.decomposition.intent_classifier import IntentClassifier


def test_parameter_and_advisory_questions_are_search() -> None:
    classifier = IntentClassifier()
    assert classifier.classify("主变压器顶层油温允许是多少？", "search", []).intent == "search"
    assert classifier.classify("线路过流时应如何处理？", "instruction", ["trip"]).intent == "search"
    assert classifier.classify("什么情况下保护装置应跳闸？", "instruction", ["trip"]).intent == "search"


def test_only_explicit_operation_requests_are_instruction() -> None:
    classifier = IntentClassifier()
    assert classifier.classify("请生成故障线路跳闸候选指令", "search", ["trip"]).intent == "instruction"
    assert classifier.classify("立即将断路器跳闸", "search", ["trip"]).intent == "instruction"
    assert classifier.classify("下发切负荷指令", "search", ["load_shedding"]).intent == "instruction"
