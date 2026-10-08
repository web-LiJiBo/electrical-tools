"""电力术语、动作、数值单位和比较符的确定性规范化。"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from .models import DecompositionResult


ACTION_ALIASES = {
    "跳开": "trip", "跳闸": "trip", "断开": "trip", "合上": "close", "合闸": "close",
    "隔离": "isolate", "告警": "alarm", "报警": "alarm", "闭锁": "lockout", "复归": "reset",
    "复位": "reset", "巡检": "inspect", "巡视": "inspect", "试验": "test", "检修": "maintain",
    "同期": "synchronize", "并网": "connect_grid", "解列": "disconnect_grid", "限功率": "limit_power",
    "有功调节": "adjust_active_power", "调有功": "adjust_active_power",
    "无功调节": "adjust_reactive_power", "调无功": "adjust_reactive_power",
    "调压": "regulate_voltage", "启动": "start", "停止": "stop", "停机": "stop",
    "减载": "load_shedding", "切负荷": "load_shedding", "恢复负荷": "restore_load",
    "恢复供电": "restore_power", "调度指令": "issue_dispatch_order",
    "温升异常": "alarm", "温度异常": "alarm", "过温": "alarm", "异常处理": "alarm",
    "故障切除": "trip", "切除故障": "trip", "保护动作": "trip", "断路器跳闸": "trip",
    "投入运行": "start", "退出运行": "stop", "功率限制": "limit_power", "检测": "inspect",
}
ENTITY_ALIASES = {"变压器": "电力变压器", "主变": "电力变压器", "集电线": "集电线路", "集电线路": "集电线路"}
OPERATORS = {"不大于": "<=", "不得大于": "<=", "小于等于": "<=", "≤": "<=", "不小于": ">=", "不得小于": ">=", "大于等于": ">=", "≥": ">=", "等于": "=", "为": "="}
UNIT_FACTORS = {"kv": ("V", 1000.0), "v": ("V", 1.0), "mw": ("W", 1_000_000.0), "kw": ("W", 1000.0), "w": ("W", 1.0)}


class DomainTermNormalizer:
    def normalize(self, result: DecompositionResult) -> DecompositionResult:
        output = deepcopy(result)
        output.actions = [canonicalize_action(item) for item in output.actions if item.strip()]
        output.actions = list(dict.fromkeys(output.actions))
        for entity in output.entities:
            name = str(entity.get("name", "")).strip()
            entity["name"] = ENTITY_ALIASES.get(name, name)
        device_type = str(output.scenario.get("device_type", "")).strip()
        if device_type:
            output.scenario["device_type"] = ENTITY_ALIASES.get(device_type, device_type)
        for item in output.constraints:
            raw_operator = str(item.get("operator", "")).strip()
            item["operator"] = OPERATORS.get(raw_operator, raw_operator)
            unit = str(item.get("unit", "")).strip()
            value = item.get("value")
            factor = UNIT_FACTORS.get(unit.lower())
            if factor:
                try:
                    item["value"] = float(value) * factor[1]
                    item["unit"] = factor[0]
                except (TypeError, ValueError):
                    pass
        output.keywords = list(dict.fromkeys([item for item in output.keywords if item]))
        return output


def canonicalize_action(action: str) -> str:
    text = str(action or "").strip()
    if not text:
        return ""
    if text in ACTION_ALIASES.values():
        return text
    if text in ACTION_ALIASES:
        return ACTION_ALIASES[text]
    for alias in sorted(ACTION_ALIASES, key=len, reverse=True):
        if alias in text:
            return ACTION_ALIASES[alias]
    return text


def extract_standard_refs(text: str) -> list[dict[str, str]]:
    # 中文前缀属于 Unicode 单词字符，不能依赖 \b 作为标准号前界。
    pattern = re.compile(r"(?:GB/?T|DL/?T|NB/?T|IEC)\s*\d+(?:\.\d+)?(?:[-—]\d{4})?", re.I)
    return [{"standard_id": match.group(0).replace(" ", ""), "version": ""} for match in pattern.finditer(text)]
