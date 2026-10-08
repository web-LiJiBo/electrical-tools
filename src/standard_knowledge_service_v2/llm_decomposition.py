"""使用本地 Qwen-7B-Chat 进行在线查询结构化分解。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .retrieval import LLMDecompositionInput, LLMDecompositionOutput


DEFAULT_MODEL_PATH = (
    Path(__file__).resolve().parents[2]
    / "models"
    / "llm"
    / "qwen--Qwen-7B-Chat"
    / "snapshots"
    / "master"
)


SYSTEM_PROMPT = """你是专业的电力标准查询分析专家。请把用户问题分解为机器可检索的结构化对象。
只能输出一个JSON对象，不要输出解释、Markdown或推理过程。不得补造原文中不存在的标准编号、版本、设备、数值或单位。

JSON字段：
{
  "intent": "search|consistency|compliance|difference|instruction",
  "entities": [{"name": "实体名称", "type": "实体类型", "desc": "简短描述"}],
  "actions": ["标准动作码"],
  "constraints": [{"parameter": "参数", "operator": "比较符", "value": "数值或原文值", "unit": "单位", "condition": "适用条件"}],
  "standard_refs": [{"standard_id": "标准编号", "version": "版本"}],
  "scenario": {"scenario_type": "场景", "device_type": "设备", "voltage_level": "电压等级", "operating_condition": "运行工况", "operation_type": "操作类型"},
  "keywords": ["检索关键词"],
  "confidence": 0.0
}

actions只能从以下标准动作码中选择：
trip, close, isolate, alarm, lockout, reset, inspect, test, maintain,
synchronize, connect_grid, disconnect_grid, limit_power, adjust_active_power,
adjust_reactive_power, regulate_voltage, start, stop, load_shedding,
restore_load, restore_power, issue_dispatch_order。
如果原文无法映射到上述动作，actions返回空列表，不得自造动作码。
actions按与用户直接诉求的相关性排序，最多返回3项；不要枚举所有可能处置动作。
"""


@dataclass(slots=True)
class QwenDecompositionConfig:
    model_path: Path = DEFAULT_MODEL_PATH
    adapter_path: Path | None = None
    temperature: float = 0.1
    do_sample: bool = False
    max_new_tokens: int = 1024
    repetition_penalty: float = 1.05
    trust_remote_code: bool = True
    local_files_only: bool = True


def extract_json_object(text: str) -> dict[str, Any]:
    """从纯JSON、Markdown代码块或混合文本中提取首个完整JSON对象。"""
    cleaned = str(text).strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL | re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1)
    else:
        start = cleaned.find("{")
        if start < 0:
            raise ValueError("大模型输出中没有JSON对象")
        decoder = json.JSONDecoder()
        parsed, _ = decoder.raw_decode(cleaned[start:])
        if not isinstance(parsed, dict):
            raise ValueError("大模型输出的顶层JSON不是对象")
        return parsed

    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("大模型输出的顶层JSON不是对象")
    return parsed


def validate_decomposition(data: dict[str, Any], raw_output: str = "") -> LLMDecompositionOutput:
    """校验类型、去重实体并构造论文检索可消费的分解结果。"""
    errors: list[str] = []
    intent = str(data.get("intent", "search")).strip().lower()
    allowed_intents = {"search", "consistency", "compliance", "difference", "instruction"}
    if intent not in allowed_intents:
        errors.append(f"不支持的intent: {intent}")
        intent = "search"

    entities_raw = data.get("entities", [])
    entities: list[dict[str, str]] = []
    seen_entities: set[str] = set()
    if not isinstance(entities_raw, list):
        errors.append("entities必须是列表")
    else:
        for index, entity in enumerate(entities_raw):
            if isinstance(entity, str):
                entity = {"name": entity, "type": "", "desc": ""}
            if not isinstance(entity, dict):
                errors.append(f"entities[{index}]必须是对象或字符串")
                continue
            name = str(entity.get("name", "")).strip()
            if not name:
                errors.append(f"entities[{index}]缺少name")
                continue
            normalized = re.sub(r"\s+", "", name).lower()
            if normalized in seen_entities:
                continue
            seen_entities.add(normalized)
            entities.append(
                {
                    "name": name,
                    "type": str(entity.get("type", "")).strip(),
                    "desc": str(entity.get("desc", "")).strip(),
                }
            )

    actions = _string_list(data.get("actions", []), "actions", errors)
    keywords = _string_list(data.get("keywords", []), "keywords", errors)
    constraints = _dict_list(data.get("constraints", []), "constraints", errors)
    standard_refs = _dict_list(data.get("standard_refs", []), "standard_refs", errors)
    scenario = data.get("scenario", {})
    if not isinstance(scenario, dict):
        errors.append("scenario必须是对象")
        scenario = {}

    try:
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0.0))))
    except (TypeError, ValueError):
        errors.append("confidence必须是0到1之间的数值")
        confidence = 0.0

    if not entities and not keywords and not standard_refs:
        errors.append("未分解出实体、关键词或标准引用")

    return LLMDecompositionOutput(
        intent=intent,
        entities=entities,
        actions=actions,
        constraints=constraints,
        standard_refs=standard_refs,
        scenario={str(key): value for key, value in scenario.items()},
        keywords=keywords,
        confidence=confidence,
        valid=not errors,
        errors=errors,
        raw_output=raw_output,
    )


def _string_list(value: Any, field_name: str, errors: list[str]) -> list[str]:
    if not isinstance(value, list):
        errors.append(f"{field_name}必须是列表")
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _dict_list(value: Any, field_name: str, errors: list[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        errors.append(f"{field_name}必须是列表")
        return []
    result: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(f"{field_name}[{index}]必须是对象")
            continue
        result.append({str(key): val for key, val in item.items()})
    return result


class QwenTextDecomposer:
    """本地Qwen-7B-Chat分解器；首次调用时才加载模型。"""

    def __init__(self, config: QwenDecompositionConfig | None = None) -> None:
        self.config = config or QwenDecompositionConfig()
        self._tokenizer: Any | None = None
        self._model: Any | None = None

    def load(self) -> None:
        model_path = self.config.model_path.resolve()
        if not (model_path / "config.json").is_file():
            raise FileNotFoundError(f"Qwen模型目录无效，缺少config.json: {model_path}")
        model_path_text = str(model_path)

        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, GenerationConfig

        use_cuda = torch.cuda.is_available()
        dtype = torch.float16 if use_cuda else torch.float32
        self._tokenizer = AutoTokenizer.from_pretrained(
            model_path_text,
            trust_remote_code=self.config.trust_remote_code,
            local_files_only=self.config.local_files_only,
        )
        self._model = AutoModelForCausalLM.from_pretrained(
            model_path_text,
            trust_remote_code=self.config.trust_remote_code,
            local_files_only=self.config.local_files_only,
            torch_dtype=dtype,
            low_cpu_mem_usage=True,
        ).eval()
        if self.config.adapter_path is not None:
            adapter_path = self.config.adapter_path.resolve()
            if not (adapter_path / "adapter_config.json").is_file():
                raise FileNotFoundError(f"Qwen微调适配器目录无效，缺少adapter_config.json: {adapter_path}")
            try:
                from peft import PeftModel
            except ImportError as exc:
                raise RuntimeError("加载Qwen LoRA微调适配器需要安装peft") from exc
            self._model = PeftModel.from_pretrained(
                self._model,
                str(adapter_path),
                local_files_only=self.config.local_files_only,
            ).eval()
        # Qwen-7B-Chat 的旧版自定义模型与 Transformers 4.32/新版
        # Accelerate 的 device_map="auto" 组合会遗漏 lm_head.weight，触发
        # KeyError。显式迁移可保留本地加载能力并避免自动映射错误。
        if use_cuda:
            self._model = self._model.to("cuda")

        generation = GenerationConfig.from_pretrained(
            model_path_text,
            trust_remote_code=self.config.trust_remote_code,
            local_files_only=self.config.local_files_only,
        )
        generation.temperature = self.config.temperature
        generation.do_sample = self.config.do_sample
        generation.max_new_tokens = self.config.max_new_tokens
        generation.repetition_penalty = self.config.repetition_penalty
        self._model.generation_config = generation

    def decompose(self, request: LLMDecompositionInput) -> LLMDecompositionOutput:
        query_text = request.query_text.strip()
        if not query_text:
            return LLMDecompositionOutput(
                intent="search",
                valid=False,
                errors=["query_text不能为空"],
            )

        try:
            if self._model is None or self._tokenizer is None:
                self.load()
            prompt = self._build_prompt(request)
            raw_output = self._generate(prompt)
            parsed = extract_json_object(raw_output)
            return validate_decomposition(parsed, raw_output=raw_output)
        except Exception as exc:
            return LLMDecompositionOutput(
                intent="search",
                valid=False,
                errors=[f"大模型分解失败: {exc}"],
            )

    @staticmethod
    def _build_prompt(request: LLMDecompositionInput) -> str:
        context = json.dumps(request.conversation_context[-4:], ensure_ascii=False)
        return (
            f"场景提示：{request.scenario_hint or '无'}\n"
            f"最近上下文：{context}\n"
            f"用户问题：{request.query_text}\n"
            "请输出JSON："
        )

    def _generate(self, prompt: str) -> str:
        if hasattr(self._model, "chat"):
            response, _ = self._model.chat(
                self._tokenizer,
                prompt,
                history=None,
                system=SYSTEM_PROMPT,
                generation_config=self._model.generation_config,
            )
            return str(response)

        import torch

        full_prompt = f"{SYSTEM_PROMPT}\n{prompt}"
        inputs = self._tokenizer(full_prompt, return_tensors="pt").to(self._model.device)
        with torch.no_grad():
            outputs = self._model.generate(**inputs, generation_config=self._model.generation_config)
        generated = outputs[0][inputs["input_ids"].shape[1]:]
        return self._tokenizer.decode(generated, skip_special_tokens=True)
