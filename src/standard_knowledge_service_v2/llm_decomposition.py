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

强制类型与来源示例（不是用户请求，不照搬设备身份）：
operations.conditions必须是字符串数组，例如["device_fault == 0","power_available == 1"]，绝不能把constraints中的parameter/operator/value对象放入conditions。
并列“设备甲和设备乙各自的风机”查询，两项target_text均引用原文完整“设备甲和设备乙各自的风机”，分别填写对应owner_id；不要仅引用主设备名称来绑定附属风机。
同句“设备甲的记录值……，并与系统当前数据分开说明”，当前数据查询source_text必须使用从“设备甲”到“分开说明”的完整连续原文，target_text用其中“设备甲”；不能仅把后半句作为source_text却从前半句引用target_text。

JSON字段：
{
  "intent": "search|consistency|compliance|difference|instruction",
  "entities": [{"name": "实体名称", "type": "实体类型", "desc": "简短描述"}],
  "actions": ["标准动作码"],
  "constraints": [{"parameter": "参数", "operator": "比较符", "value": "数值或原文值", "unit": "单位", "condition": "适用条件"}],
  "standard_refs": [{"standard_id": "标准编号", "version": "版本"}],
  "scenario": {"scenario_type": "场景", "device_type": "设备", "voltage_level": "电压等级", "operating_condition": "运行工况", "operation_type": "操作类型", "query_kind": "device_status|device_capability|device_readiness|standard_query|assessment|operation|other"},
  "keywords": ["检索关键词"],
  "operations": [{"device_id":"目录唯一编号", "target_text":"原文目标片段", "owner_id":"所属主设备编号或空字符串", "action":"该设备目录动作码", "parameters":{}, "source_text":"完整保留本项诉求的原文片段", "negated":false, "conditions":[], "order":null, "clarification":"需澄清的问题或空字符串"}],
  "queries": [{"device_id":"目录唯一编号，标准咨询可留空", "target_text":"原文目标片段", "owner_id":"所属主设备编号或空字符串", "query_kind":"device_status|device_capability|device_readiness|standard_query|assessment|other", "requested_action":"仅device_readiness必填的待判断目录动作码", "source_text":"本项原文", "clarification":"需澄清的问题或空字符串"}],
  "request_controls": {"analysis_only": false, "source_text":"仅分析、不要生成指令等全局限制的原文片段，无限制时空字符串"},
  "confidence": 0.0
}

无设备目录时，actions从以下标准动作码中选择：
trip, close, isolate, alarm, lockout, reset, inspect, test, maintain,
synchronize, connect_grid, disconnect_grid, limit_power, adjust_active_power,
adjust_reactive_power, regulate_voltage, start, stop, load_shedding,
restore_load, restore_power, issue_dispatch_order。
提供设备目录时可使用对应目录中的raise、lower、set_tap、open等实际动作码；actions应为operations实际动作码按出现顺序去重后的摘要，不得以start等不相关旧码替换升档动作。没有操作时actions只保留与咨询目标直接相关的动作；不要枚举所有可能处置动作。
如果原文无法映射到上述动作或所提供目录的实际动作，actions返回空列表，不得自造动作码。
scenario.query_kind必须选择一个值：device_status为当前设备事实或数据查询；device_capability为可用动作查询；
device_readiness为判断某设备当前是否具备启动等动作前置条件，queries中必须指定requested_action；它是只读诊断，operations必须为空，不应误归入标准合规或设备控制。
standard_query为标准、条款、依据或要求咨询；assessment为正常与否、合规或假设工况评估；
operation为用户提出的具体操作；other为其他问题。按整句目的判断，不因出现动作词就视为操作。
intent仍只使用search、consistency、compliance、difference、instruction；评估类intent用compliance，assessment仅用于query_kind。
否定、疑问和条件必须保留在intent、constraints及operating_condition中；实体保留编号、并列对象和所属关系。
operating_condition只填写用户明确限定的工况或前置条件；未限定时返回空字符串，不补推测的当前状态。
操作目标数值用constraints的等值赋值表达，parameter写目标参数、operator写=、condition留空；
执行前提另列约束，不能将“当前档位大于10档”等前提误写为目标档位赋值。
必须一次理解整句，始终返回operations和queries两个列表（无对应诉求时为空）。不要把逗号、礼貌语当新操作，不要把“已经启动”等状态修饰误作动作。
operations每项只包含一个设备和一个动作；同设备多个动作、多个设备分别列项，完整保留每项来源、否定、执行前提及顺序要求。
request_controls只记录对整次请求无条件生效的控制限制：“只分析”“只做检查”“不要生成控制指令”等在未受其他条件限定时须analysis_only=true并引用真实原文；此时operations必须为空，保留要分析的queries。没有此类全局限制时analysis_only=false、source_text为空，不得虚构限制证据。
必须区分全局禁止和条件不成立时的停止策略。“只有满足条件才允许动作；条件不满足不要生成指令”描述同一项条件操作，analysis_only=false，operations保留动作、conditions保留全部前提，negated=false；“先核对条件”是预览前核验要求，不新增inspect操作或虚构order。条件当前不满足时由后台阻断，不能提前把整项操作改成无条件只读诊断。
“前一步成功后才执行后一步；前一步失败就不执行后一步”是顺序计划的失败停止策略，以order保留依赖，不等于撤销所请求的步骤，不据此设置全局analysis_only或将步骤negated=true。真正无条件的“不要启动”“取消后续动作”仍须保留否定/全局禁止；不能借条件或顺序忽略真实取消。不能确定其作用范围时保留原话并clarification，不猜测授权。
优先使用提供的设备目录及ownership关系和各设备actions。具体动作码可使用目录中的set_tap/open等，不受整句actions摘要的旧码表限制。
编号空格不改变设备身份；“那台”“各自的”等归属需根据目录解析；编号与归属冲突、多个候选或无法确定时填写clarification，不增加猜测目标。
每项parameters使用对应动作模板的parameter字段名及模板单位，数值必须来自该项原文；source_text保留原始数值与单位和所有否定/条件/顺序，不得省略许可或阈值。
承接同一设备的多步请求，每步source_text可以重复采用包含明确设备及所属关系的完整原句；不能只引用“再升一档”等孤立后半句而让target_text/owner_id失去原文依据。target_text引用完整source_text中的明确设备跨度，保留后续承接和失败停止要求。完整原文中的任务性结尾也必须被来源跨度覆盖，不要丢掉“请给出方案”等诉求；可用完整原句作为各项source_text，不硬删未覆盖内容。
目录actions的condition/constraints只描述已有可核验字段；用户明确提出的conditions应使用这些字段的安全比较表达式，例如device_fault == 0、maintenance_lockout == 0、power_available == 1。不能因模板已有条件就声称用户提出该条件，不得补造用户未提及的条件、字段或授权；无法准确表达的条件保留原文以便后端明确阻断。
明确的“先…再…”顺序使用每项order=1、2、…、N的连续整数；无顺序时null。每步source_text完整保留该步限制；只有前步真实成功反馈后才能预览下一步，并逐步确认。分支、延时和未知授权条件不能伪装成可执行比较表达式。
“从当前档位升一档”是动作raise及其正常状态语义，不应写入conditions；“成功后再执行下一步”的真实反馈依赖由order承载，不当作额外自然语言条件。仅明确的外部前提才列入conditions，不压缩更复杂分支为普通order步骤。
owner_id在用户说出所属关系时填写对应主设备，直接用设备自身编号或名称时可留空。target_text必须引用原文目标，不能自造新名称。
并列共享后缀如“启动主变1和主变2各自的冷却风机”时，两项target_text都引用该完整原文跨度，分别用owner_id关联主变1、主变2；不要改写成原文不存在的连续词组。
queries逐一保留事实/能力/评估/标准咨询目标。未请求操作时operations必须为空，不能把状态描述或标准建议变成操作。
当用户要求把巡检记录/假设值与“系统当前数据”分开说明时，若同一句或最近上下文已经唯一指明设备和物理量，当前数据沿用该设备及对应物理量，不要求用户重复指定测点。用户给出的记录值只作assessment输入，不能当成当前实测值；另列device_status查询由后台读取当前事实，不编造当前值。当前数据查询的source_text保留包含前文明确设备和对比诉求的完整连续原文，target_text引用其中明确设备名，不把“系统当前数据”孤立成新设备或无依据泛称。只有真实存在设备/物理量歧义时才clarification。
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
    if 'operations' in data or 'queries' in data or 'request_controls' in data:
        errors.extend(validate_semantic_plan(data))
    intent = str(data.get("intent", "search")).strip().lower()
    intent = {'device_status':'search', 'device_capability':'search', 'standard_query':'search',
              'device_readiness':'search', 'assessment':'compliance', 'operation':'instruction', 'other':'search'}.get(intent, intent)
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
    kind = scenario.get('query_kind')
    if kind is not None and kind not in ('device_status', 'device_capability', 'device_readiness', 'standard_query', 'assessment', 'operation', 'other'):
        errors.append('scenario.query_kind不是受支持的问题类型')

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


def validate_semantic_plan(data: dict[str, Any]) -> list[str]:
    """Validate the whole-request plan without repairing missing control claims."""
    errors = []
    if 'request_controls' in data:
        controls = data['request_controls']
        if (not isinstance(controls, dict) or type(controls.get('analysis_only')) is not bool
                or not isinstance(controls.get('source_text'), str)
                or controls.get('analysis_only') and not controls.get('source_text', '').strip()):
            errors.append('request_controls须包含布尔analysis_only和对应原文source_text')
    for name in ('operations', 'queries'):
        rows = data.get(name)
        if not isinstance(rows, list) or len(rows) > 16:
            errors.append(f'{name}须为最多16项的列表')
            continue
        for index, row in enumerate(rows):
            prefix = f'{name}[{index}]'
            if not isinstance(row, dict):
                errors.append(f'{prefix}须为对象')
                continue
            strings = ('device_id', 'target_text', 'owner_id', 'source_text', 'clarification')
            strings += ('action',) if name == 'operations' else ('query_kind',)
            if any(not isinstance(row.get(key), str) for key in strings):
                errors.append(f'{prefix}缺少文本字段')
            if name == 'queries' and row.get('query_kind') not in ('device_status', 'device_capability', 'device_readiness', 'standard_query', 'assessment', 'other'):
                errors.append(f'{prefix}查询类型无效')
            if name == 'queries' and row.get('query_kind') == 'device_readiness':
                if not isinstance(row.get('requested_action'), str) or not row['requested_action'].strip():
                    errors.append(f'{prefix}缺少待判断的requested_action')
            if name == 'operations':
                if not isinstance(row.get('parameters'), dict) or type(row.get('negated')) is not bool:
                    errors.append(f'{prefix}缺少动作参数或否定标记')
                if (not isinstance(row.get('conditions'), list)
                        or any(not isinstance(value, str) for value in row.get('conditions', []))):
                    errors.append(f'{prefix}缺少条件列表')
                if 'order' not in row or row['order'] is not None and type(row['order']) not in (str, int):
                    errors.append(f'{prefix}缺少顺序标记')
    return errors


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

    def _generate(self, prompt: str, system_prompt: str = SYSTEM_PROMPT) -> str:
        if hasattr(self._model, "chat"):
            response, _ = self._model.chat(
                self._tokenizer,
                prompt,
                history=None,
                system=system_prompt,
                generation_config=self._model.generation_config,
            )
            return str(response)

        import torch

        full_prompt = f"{system_prompt}\n{prompt}"
        inputs = self._tokenizer(full_prompt, return_tensors="pt").to(self._model.device)
        with torch.no_grad():
            outputs = self._model.generate(**inputs, generation_config=self._model.generation_config)
        generated = outputs[0][inputs["input_ids"].shape[1]:]
        return self._tokenizer.decode(generated, skip_special_tokens=True)
