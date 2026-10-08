from __future__ import annotations

import json

from ..llm_decomposition import SYSTEM_PROMPT


def build_decomposition_prompt(query: str, scenario_hint: str, conversation_context: list[dict[str, str]]) -> str:
    """将有限上下文传给模型；系统提示由调用器作为 system 字段传递。"""
    return (
        f"场景提示：{scenario_hint or '无'}\n"
        f"最近上下文：{json.dumps(conversation_context[-4:], ensure_ascii=False)}\n"
        f"用户问题：{query.strip()}\n"
        "请严格按系统提示输出一个 JSON 对象。"
    )


__all__ = ["SYSTEM_PROMPT", "build_decomposition_prompt"]
