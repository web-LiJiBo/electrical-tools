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
        r"^(?:请)?(?:启动|开启|开动|停止|停机|关闭|分闸|合闸|断开)",
        r"^(?:请)?(?:将|把).*(?:设定|设置|调到|调至).+档",
        r"^(?:请)?(?:模拟)?(?:断路器|变压器|主变|风机|油泵|隔离开关|接地开关)\d+(?:分闸|合闸|跳闸|启动|停止|停机)$",
        r"请(?:立即|马上)?(?:将|把)?.*(?:分闸|合闸|跳闸)",
        r"(?:请|将|把).*(?:功率).*(?:设定|设置|调整|调节)",
        r"(?:请|将|把).*(?:设定|设置|调整|调节).*功率",
        r"请(?:立即|马上)?(?:执行|下发|生成|发送)",
        r"(?:执行|下发|发送|生成)(?:一条|一个|该|此)?(?:控制|操作|调度|跳闸|合闸|隔离)?指令",
        r"(?:执行|下发|发送|生成).+指令",
        r"(?:立即|马上|现在)(?:跳闸|合闸|隔离|停机|启动|解列|并网|切负荷)",
        r"将.+(?:跳闸|合闸|隔离|停机|启动|解列|并网|切除)",
    )
    _query_patterns = (
        r"多少", r"是什么", r"有哪些", r"哪些", r"为何", r"为什么", r"是否", r"如何", r"怎么",
        r"什么情况下", r"应不应", r"能否", r"能不能", r"可否", r"吗[？?]?$", r"(?:了没|了么)[？?]?$", r"[？?]$",
    )
    _negated_command_patterns = (
        r"(?:请别|别|不要|请勿|禁止|严禁|不得|不应|不允许|无需|暂缓|暂不|先别|暂时不要).*(?:启动|开启|开动|停止|关闭|分闸|合闸|调节|调整|设定|设置|设为|下发|执行)",
        r"(?:先别|暂缓|暂不|暂时不要|暂停).{0,20}(?:启动|开启|停止|关闭|分闸|合闸|调节|调整|设定|设置|设为|下发|执行)",
        r"(?:禁止|严禁|不得|不应|不允许|不要|请勿|无需).{0,16}(?:启动|开启|开动|打开|停止|关闭|停机|分闸|合闸|跳闸|隔离|解列|并网|下发|生成|发送|执行|调节|设置)",
        r"不(?:执行|启动|开启|停止|下发|生成)",
        r"(?:取消|撤销|作废).{0,10}(?:指令|操作|控制|启动|停机|分闸|合闸)",
    )

    @classmethod
    def action_is_negated(cls, query: str) -> bool:
        text = ''.join(str(query).split())
        return any(re.search(pattern, text) for pattern in cls._negated_command_patterns)

    def classify(self, query: str, model_intent: str = "", actions: list[str] | None = None, *, query_kind: str | None = None) -> IntentClassification:
        text = "".join(str(query).split())
        if self.action_is_negated(text):
            return IntentClassification(
                "search", 0.99,
                ("检测到否定、禁止或撤销语气，明确阻止指令生成",),
                model_intent,
            )
        command_hits = [pattern for pattern in self._command_patterns if re.search(pattern, text)]
        query_hits = [pattern for pattern in self._query_patterns if re.search(pattern, text)]
        if query_hits and not re.search(r"请(?:立即|马上)?(?:执行|下发|生成|发送)", text):
            return IntentClassification("search", 0.92, ("检测到咨询表达，不按设备控制执行",), model_intent)
        if command_hits:
            return IntentClassification("instruction", 0.95, ("检测到明确执行或指令生成语气",), model_intent)
        if query_hits or text.endswith(("?", "？")):
            return IntentClassification("search", 0.92, ("检测到查询问句或标准咨询表达",), model_intent)
        if query_kind == 'operation' and model_intent == 'instruction' and actions:
            return IntentClassification('instruction', 0.85,
                ('采用模型识别的操作意图，目标、条件和执行仍需后端校验',), model_intent)
        if model_intent in {"consistency", "compliance", "difference"}:
            return IntentClassification(model_intent, 0.85, ("保留模型识别的标准分析意图",), model_intent)
        if model_intent == "instruction" and actions:
            return IntentClassification("search", 0.70, ("存在动作词但没有明确执行授权，按知识查询处理",), model_intent)
        return IntentClassification("search", 0.75, ("未检测到明确控制授权，默认按知识查询处理",), model_intent)
