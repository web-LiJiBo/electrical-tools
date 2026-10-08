from __future__ import annotations

from dataclasses import asdict, dataclass
import re


@dataclass(frozen=True, slots=True)
class IntentClassification:
    intent: str
    confidence: float
    reasons: tuple[str, ...]
    model_intent: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["reasons"] = list(self.reasons)
        return data


class IntentClassifier:
    """用确定性业务规则校正模型意图，控制类采用明确授权原则。"""

    _command_patterns = (
        r"请(?:立即|马上)?(?:执行|下发|生成|发送)",
        r"(?:执行|下发|发送|生成)(?:一条|一个|该|此)?(?:控制|操作|调度|跳闸|合闸|隔离)?指令",
        r"(?:执行|下发|发送|生成).+指令",
        r"(?:立即|马上|现在)(?:跳闸|合闸|隔离|停机|启动|解列|并网|切负荷)",
        r"将.+(?:跳闸|合闸|隔离|停机|启动|解列|并网|切除)",
    )
    _query_patterns = (
        r"多少", r"是什么", r"有哪些", r"哪些", r"为何", r"为什么", r"是否", r"如何", r"怎么",
        r"什么情况下", r"应不应",
    )

    def classify(self, query: str, model_intent: str = "", actions: list[str] | None = None) -> IntentClassification:
        text = "".join(str(query).split())
        command_hits = [pattern for pattern in self._command_patterns if re.search(pattern, text)]
        query_hits = [pattern for pattern in self._query_patterns if re.search(pattern, text)]
        if command_hits:
            return IntentClassification("instruction", 0.95, ("检测到明确执行或指令生成语气",), model_intent)
        if query_hits or text.endswith(("?", "？")):
            return IntentClassification("search", 0.92, ("检测到查询问句或标准咨询表达",), model_intent)
        if model_intent in {"consistency", "compliance", "difference"}:
            return IntentClassification(model_intent, 0.85, ("保留模型识别的标准分析意图",), model_intent)
        if model_intent == "instruction" and actions:
            return IntentClassification("search", 0.70, ("存在动作词但没有明确执行授权，按知识查询处理",), model_intent)
        return IntentClassification("search", 0.75, ("未检测到明确控制授权，默认按知识查询处理",), model_intent)
