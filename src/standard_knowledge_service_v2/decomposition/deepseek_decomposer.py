"""DeepSeek兼容接口查询分解器；密钥仅从环境变量读取。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..llm_decomposition import SYSTEM_PROMPT, extract_json_object, validate_decomposition
from .fallback import RawTextFallback
from .models import DecompositionResult, MissingField
from .normalizer import DomainTermNormalizer


@dataclass(frozen=True, slots=True)
class DeepSeekConfig:
    api_base: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    api_key_env: str = "DEEPSEEK_API_KEY"
    timeout_seconds: float = 30.0
    temperature: float = 0.1
    max_tokens: int = 1024


class DeepSeekDecomposer:
    def __init__(self, config: DeepSeekConfig | None = None, fallback: RawTextFallback | None = None) -> None:
        self.config = config or DeepSeekConfig()
        self._fallback = fallback or RawTextFallback()
        self._normalizer = DomainTermNormalizer()

    def decompose(self, query: str, scenario_hint: str = "", conversation_context: list[dict[str, str]] | None = None) -> DecompositionResult:
        try:
            raw_output = self._request(query, scenario_hint, conversation_context or [])
            output = validate_decomposition(extract_json_object(raw_output), raw_output=raw_output)
            if not output.valid:
                raise ValueError("; ".join(output.errors))
            missing = []
            if not output.scenario.get("device_type"):
                missing.append(MissingField("device_type", "模型和原文均未明确设备类型", "场景匹配"))
            result = DecompositionResult(
                intent=output.intent, entities=output.entities, actions=output.actions,
                constraints=output.constraints, standard_refs=output.standard_refs,
                scenario=output.scenario, keywords=output.keywords, confidence=output.confidence,
                valid=True, source="deepseek_api", errors=output.errors,
                missing_fields=missing, raw_output=output.raw_output,
            )
            return self._normalizer.normalize(result)
        except Exception as exc:
            return self._normalizer.normalize(
                self._fallback.decompose(query, scenario_hint, [f"DeepSeek分解失败: {self._safe_error(exc)}"])
            )

    def _request(self, query: str, scenario_hint: str, conversation_context: list[dict[str, str]]) -> str:
        api_key = os.getenv(self.config.api_key_env, "").strip()
        if not api_key:
            raise RuntimeError(f"环境变量{self.config.api_key_env}未配置")
        context = json.dumps(conversation_context[-4:], ensure_ascii=False)
        user_prompt = (
            f"场景提示：{scenario_hint or '无'}\n最近上下文：{context}\n"
            f"用户问题：{query.strip()}\n请严格输出一个JSON对象。"
        )
        body = json.dumps({
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "response_format": {"type": "json_object"},
            "stream": False,
        }, ensure_ascii=False).encode("utf-8")
        request = Request(
            f"{self.config.api_base.rstrip('/')}/chat/completions",
            data=body,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self.config.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        try:
            return str(payload["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("DeepSeek响应缺少choices[0].message.content") from exc

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        if isinstance(exc, HTTPError):
            return f"HTTP {exc.code}"
        if isinstance(exc, URLError):
            return f"网络错误: {exc.reason}"
        return str(exc)
