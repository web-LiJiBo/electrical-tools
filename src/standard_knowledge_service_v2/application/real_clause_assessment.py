"""以库内来源原文进行有限参数比对；不把越限等同于可控制动作。"""
from dataclasses import asdict
import math
import re
from types import SimpleNamespace

from ..retrieval import LunwenMatchingInput


def assess_real_clause(pipeline, request):
    session = pipeline.simulation_session
    text = request.query.lower()
    ids = [d["device_id"] for d in session.snapshot()["devices"] if d["device_id"].lower() in text]
    ids += [f"SIM-TRANSFORMER-0{i}" for i in (1, 2) if re.search(f"模拟变压器{i}(?![0-9])", text)]
    if request.parameters.get("device_id"):
        ids.append(str(request.parameters["device_id"]))
    ids = list(dict.fromkeys(ids))
    device_id = ids[0] if len(ids) == 1 and ids[0] in session.service.devices else ""
    with session.lock:
        facts = dict(session.facts.get(device_id, {}))
        state = dict(session.service.states.get(device_id, {}))
    device = session.service.devices.get(device_id, {})
    # 执行同一真实分解器及检索器；增加设备参数名称，不注入标准阈值。
    expanded = request.query
    if device.get("device_type") == "transformer":
        expanded += " 变压器绕组热点温升 顶层油温 绕组平均温升 ON冷却方式"
    decomposed = pipeline.decomposer.decompose(expanded, "substation_maintenance", request.conversation_context)
    parsed = decomposed.to_lunwen_parsed_json()
    parsed["context_device_type"] = "变压器" if device.get("device_type") == "transformer" else device.get("device_type", "")
    matched = pipeline.retriever.match(LunwenMatchingInput(expanded, parsed, top_k_rules=30))
    data = {"decomposition": decomposed.to_dict(), "intent_classification": {"intent": "compliance", "reasons": ["状态询问经真实条款检索与原文参数比对，不视为下发授权"]},
            "context": {"scenario": device.get("scenario", ""), "device_type": device.get("device_type", "")},
            "diagnostics": decomposed.errors, "matching": {"rules": [{"rule_id":m.rule.rule_id,"content":m.rule.content,"rank":m.rank,"score":m.combined_score} for m in matched.rules]},
            "candidate_instruction": None, "device_assessment": {"status":"uncertain","device_id":device_id,"state":state,"runtime_facts":facts,"rule":"尚未找到可完整计算的适用条款", "scope":"库内来源原文的实验性参数比对；不等同于整体健康或现场合规"},
            "answer": {"text":"缺少可计算的适用真实条款或目标设备。未使用预设电流100判断，也未生成控制指令。"}}
    if not device_id or device.get("device_type") != "transformer":
        return "uncertain", data, []
    # 实验设备显式绑定来源条款ID，避免把不同标准/版本的阈值混用。
    # 保留全库检索结果，再进行条款ID索引召回；不伪装为语义Top-K命中。
    bound_id = device.get("assessment_clause_id")
    bound = next((unit for unit in pipeline.retriever.repository.units if unit.clause_id == bound_id),None)
    data["retrieval_trace"]={"semantic_candidates":len(matched.rules),"device_bound_clause_id":bound_id,"bound_clause_found":bound is not None}
    if bound is None:
        return "uncertain",data,[]
    candidates = [SimpleNamespace(rule=rule) for rule in bound.rules]
    data["matching"]["rules"] += [{"rule_id":rule.rule_id,"content":rule.content,"rank":None,"score":None,"retrieval_method":"device_clause_id_binding"} for rule in bound.rules if not any(hit.rule.rule_id==rule.rule_id for hit in matched.rules)]
    # 当前只支持这一清楚限定的条款结构，不泛化解析复杂逻辑。
    for hit in candidates:
        unit = pipeline.retriever.repository.unit_for_rule(hit.rule.rule_id)
        if not unit:
            continue
        source = unit.metadata.get("source", {})
        original = source.get("source_text", "")
        normalized = re.sub(r"\s+", "", original).replace("（", "(").replace("）", ")")
        patterns = [r"绕组热点温升(\d+(?:\.\d+)?)K", r"顶层油温(\d+(?:\.\d+)?)K",
                    r"绕组\(平均\)温升(\d+(?:\.\d+)?)K\(ON及OF冷却方式\)或(\d+(?:\.\d+)?)K\(OD冷却方式\)"]
        values = [re.search(pattern, normalized) for pattern in patterns]
        content = re.sub(r"\s+", "", hit.rule.content).replace("（", "(").replace("）", ")")
        if not all(values) or not all(re.search(pattern, content) for pattern in patterns):
            continue
        if unit.metadata.get("audit", {}).get("manual_review_required") is True:
            continue
        mode = facts.get("cooling_mode")
        if mode not in ("ON", "OF", "OD") or state.get("operating_state") != "running":
            break
        fields = ["winding_hotspot_rise_k", "top_oil_rise_k", "winding_average_rise_k"]
        if any(type(facts.get(field)) not in (int, float) or not math.isfinite(facts[field]) or facts[field] < 0 for field in fields):
            break
        limits = [float(values[0][1]),float(values[1][1]),float(values[2][2 if mode=="OD" else 1])]
        checks = [{"parameter":field,"actual":facts[field],"operator":"<=","limit":limit,"unit":"K","passed":facts[field]<=limit} for field,limit in zip(fields,limits)]
        normal = all(check["passed"] for check in checks)
        provenance = {"standard_id":unit.standard_id,"version":unit.version,"clause_id":unit.clause_id,"rule_id":hit.rule.rule_id,"source_uri":unit.source_uri,"source_excel":source,"quote":hit.rule.content}
        data["device_assessment"].update(status="normal" if normal else "abnormal",rule=hit.rule.content,checks=checks)
        data["selected_rule"]={"rule_id":hit.rule.rule_id,"content":hit.rule.content}
        data["real_clause_evidence"]=provenance
        data["semantic"]=asdict(pipeline.extractor.extract_rule(hit.rule,unit))
        data["consistency"]=pipeline.consistency.compare(expanded,hit.rule.content).to_dict()
        data["answer"]["text"]=("按检索到的来源条款比对，这三个模拟温升参数均未越限。" if normal else "按检索到的来源条款比对，模拟温升参数存在越限。") + "该条款只有限值要求，没有明确跳闸或调节动作，因此不生成控制指令。标准编号、版本及完整适用上下文仍需核验。"
        data["control_block_reason"]="限值条款不等于动作授权；缺少明确动作条款及完整适用上下文"
        return "answered",data,[provenance]
    return "uncertain",data,[]
