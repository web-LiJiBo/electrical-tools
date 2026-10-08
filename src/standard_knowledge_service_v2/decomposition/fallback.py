"""无需加载模型的保守回退：只提取原文明确出现的信息。"""

from __future__ import annotations

import re

from .models import DecompositionResult, MissingField
from .normalizer import ACTION_ALIASES, extract_standard_refs


class RawTextFallback:
    def decompose(self, query: str, scenario_hint: str = "", errors: list[str] | None = None) -> DecompositionResult:
        text = query.strip()
        actions = [canonical for alias, canonical in ACTION_ALIASES.items() if alias in text]
        entity_terms = (
            "主变压器", "变压器", "集电线路", "输电线路", "配电线路", "线路", "断路器", "隔离开关",
            "母线", "继电保护", "风电机组", "风电场", "光伏电站", "储能电站", "逆变器", "并网点",
            "发电机组", "变电站", "负荷", "场站控制器", "AGC", "AVC",
        )
        entities = [{"name": value, "type": "设备", "desc": "原文提取"} for value in entity_terms if value in text]
        numbers = re.findall(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>kV|V|MW|kW|W|ms|s|K|℃|%)", text, re.I)
        constraints = [{"parameter": "", "operator": "", "value": value, "unit": unit, "condition": "原文提取"} for value, unit in numbers]
        domain_terms = (
            "温升", "油温", "过流", "短路", "接地故障", "故障隔离", "并网", "解列", "同期",
            "电压", "频率", "有功", "无功", "功率因数", "电网调度", "调度", "限功率", "切负荷", "检修", "巡视",
        )
        keywords = list(dict.fromkeys([item["name"] for item in entities] + actions + [term for term in domain_terms if term in text] + [match[0] for match in numbers]))
        missing = []
        if actions and not any(key in text for key in ("定值", "地址", "逻辑节点", "寄存器")):
            missing.append(MissingField("设备控制配置", "原文未提供定值或协议映射", "候选指令生成"))
        return DecompositionResult(
            entities=entities,
            actions=list(dict.fromkeys(actions)),
            constraints=constraints,
            standard_refs=extract_standard_refs(text),
            scenario={"scenario_type": scenario_hint} if scenario_hint else {},
            keywords=keywords or [text],
            confidence=0.35,
            valid=bool(entities or keywords or text),
            source="raw_text_fallback",
            errors=list(errors or []),
            missing_fields=missing,
        )
