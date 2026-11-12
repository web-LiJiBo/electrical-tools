"""以库内来源原文进行有限参数比对；不把越限等同于可控制动作。"""
from dataclasses import asdict
import math
import re
from types import SimpleNamespace

from ..retrieval import LunwenMatchingInput


PARAMETER_ALIASES = {
    "winding_hotspot_rise_k": ("绕组热点温升", "热点温升", "热点"),
    "top_oil_rise_k": ("顶层油温升", "顶层油温", "顶层油"),
    "winding_average_rise_k": ("绕组平均温升", "平均温升"),
}


def _parameter_field(name):
    name = re.sub(r'\s+', '', str(name or ''))
    return next((key for key, aliases in PARAMETER_ALIASES.items()
                 if name == key or name and any(alias in name or name in alias for alias in aliases)), None)


def _hypothetical_values(request, decomposed):
    """Extract only explicit user-supplied values, never snapshot defaults."""
    result = {}
    modes = set()
    supplied = request.parameters.get("hypothetical_facts", {})
    if isinstance(supplied, dict):
        mode = supplied.get('cooling_mode', supplied.get('冷却方式'))
        if mode is not None:
            modes.add(str(mode).strip().upper())
        for field, aliases in PARAMETER_ALIASES.items():
            value = supplied.get(field)
            if value is None:
                value = next((supplied[name] for name in aliases if name in supplied), None)
            if type(value) in (int, float) and math.isfinite(value) and value >= 0:
                result[field] = float(value)
    for item in decomposed.constraints if decomposed else []:
        if not isinstance(item, dict) or str(item.get("operator", "")).strip() not in ("=", "=="):
            continue
        name = re.sub(r"\s+", "", str(item.get("parameter", "")))
        if name in ('cooling_mode', '冷却方式', '冷却模式'):
            modes.add(str(item.get('value', '')).strip().upper())
            continue
        field = _parameter_field(name)
        try:
            value = float(item.get("value"))
        except (TypeError, ValueError):
            continue
        if field and math.isfinite(value) and value >= 0:
            result[field] = value
    # Keep explicit applicability conditions even when the model omits them.
    modes.update(re.findall(r'(?<![A-Za-z])(ON|OF|OD)\s*冷却', request.query, re.I))
    modes = {mode.upper() for mode in modes}
    if modes:
        result['cooling_mode'] = next(iter(modes)) if len(modes) == 1 else 'conflicting'
    return result


def _checks(values, fields, limits):
    return [{"parameter": field, "actual": values[field], "operator": "<=", "limit": limit,
             "unit": "K", "passed": values[field] <= limit}
            for field, limit in zip(fields, limits) if field in values]


def _hypothesis_checks(values, constraints, fields, limits):
    """Prove each stated interval wholly within/outside the limit; never invent a point."""
    assumptions = {field: [('=', values[field])] for field in fields if field in values}
    for item in constraints:
        field = _parameter_field(item.get('parameter'))
        operator = str(item.get('operator', '')).strip()
        if not field or operator not in ('=', '==', '<', '<=', '>', '>=', '!='):
            continue
        try:
            value = float(item.get('value'))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and value >= 0:
            assumptions.setdefault(field, []).append((operator, value))
    checks = []
    for field, limit in zip(fields, limits):
        terms = list(dict.fromkeys(assumptions.get(field, [])))
        if not terms:
            continue
        lower, upper, lower_closed, upper_closed = 0.0, math.inf, True, False
        excluded = set()
        for operator, value in terms:
            if operator in ('=', '==', '>', '>='):
                closed = operator != '>'
                if value > lower:
                    lower, lower_closed = value, closed
                elif value == lower:
                    lower_closed &= closed
            if operator in ('=', '==', '<', '<='):
                closed = operator != '<'
                if value < upper:
                    upper, upper_closed = value, closed
                elif value == upper:
                    upper_closed &= closed
            if operator == '!=':
                excluded.add(value)
        conflict = lower > upper or lower == upper and (not lower_closed or not upper_closed or lower in excluded)
        passed = (None if conflict else True if upper <= limit else False
                  if lower > limit or lower == limit and (not lower_closed or lower in excluded) else None)
        point = lower == upper and not conflict
        checks.append({'parameter':field, 'actual':lower if point else ' 且 '.join(f'{op} {v:g}' for op,v in terms),
                       'operator':'<=', 'limit':limit, 'unit':'K', 'passed':passed,
                       'assumptions':[{'operator':op,'value':value} for op,value in terms],
                       'conflicting':conflict})
    return checks


def assess_real_clause(pipeline, request, *, snapshot=None, device_id=None, decomposed=None):
    session = pipeline.simulation_session
    if snapshot is None and request.parameters.get('simulation_mode') is True:
        from .simulation_access import default_session, simulation_runtime
        identifier = request.parameters.get('simulation_session_id')
        try:
            snapshot = simulation_runtime(pipeline).snapshot(identifier) if identifier else default_session(pipeline)
        except (KeyError, ValueError):
            return 'uncertain', {'answer': {'text': '模拟会话不存在，请重新选择会话'},
                                 'simulation_factual': True, 'candidate_instruction': None}, []
    text = request.query.lower()
    if snapshot is not None:
        from .simulation_access import view_snapshot
        snapshot = view_snapshot(pipeline, request, snapshot)
    profiles = session.service.devices
    if snapshot is not None:
        from .simulation_access import simulation_runtime
        from .simulation_query import _targets
        runtime = simulation_runtime(pipeline)
        profiles = runtime.catalog.devices
        devices = [{**profiles[d['device_id']], **d} for d in snapshot['devices']]
        names = [e['name'] for e in decomposed.entities if isinstance(e, dict) and isinstance(e.get('name'), str)] if decomposed else []
        ids = _targets(request.query, request.parameters, devices,
                       runtime.catalog.scenarios.get(snapshot.get('scenario_id'), {}), entity_names=names)
        available = {d['device_id'] for d in devices}
    else:
        ids = [d['device_id'] for d in session.snapshot()['devices'] if d['device_id'].lower() in text]
        if request.parameters.get('device_id'):
            ids.append(str(request.parameters['device_id']))
        available = set(profiles)
    ids = list(dict.fromkeys(ids))
    device_id = device_id or (ids[0] if len(ids) == 1 and ids[0] in available else "")
    if snapshot is not None:
        current = next((d for d in snapshot['devices'] if d['device_id'] == device_id), {})
        facts, state = dict(current.get('runtime_facts', {})), dict(current.get('state', {}))
    else:
        with session.lock:
            facts = dict(session.facts.get(device_id, {}))
            state = dict(session.service.states.get(device_id, {}))
    device = profiles.get(device_id, {})
    # 执行同一真实分解器及检索器；增加设备参数名称，不注入标准阈值。
    expanded = request.query
    if device.get("device_type") == "transformer":
        expanded += " 变压器绕组热点温升 顶层油温 绕组平均温升 ON冷却方式"
    if decomposed is None:
        decomposed = pipeline.decomposer.decompose(expanded, "substation_maintenance", request.conversation_context)
    parsed = decomposed.to_lunwen_parsed_json()
    parsed["intent"] = "compliance"
    parsed["context_device_type"] = "变压器" if device.get("device_type") == "transformer" else device.get("device_type", "")
    requested_version = pipeline._requested_version(request, decomposed.standard_refs)
    requested_standard = pipeline._requested_standard(request, decomposed.standard_refs)
    if requested_version:
        parsed["requested_version"] = requested_version
    if requested_standard:
        parsed["requested_standard_id"] = requested_standard
    matched = pipeline.retriever.match(LunwenMatchingInput(expanded, parsed, top_k_rules=30))
    data = {"decomposition": decomposed.to_dict(), "intent_classification": {"intent": "compliance", "reasons": ["状态询问经真实条款检索与原文参数比对，不视为下发授权"]},
            "context": {"scenario": device.get("scenario", ""), "device_type": device.get("device_type", "")},
            "diagnostics": decomposed.errors, "matching": {"rules": [{"rule_id":m.rule.rule_id,"content":m.rule.content,"rank":m.rank,"score":m.combined_score} for m in matched.rules]},
            "candidate_instruction": None, "device_assessment": {"status":"uncertain","device_id":device_id,"state":state,"runtime_facts":facts,"rule":"尚未找到可完整计算的适用条款", "scope":"库内来源原文的实验性参数比对；不等同于整体健康或现场合规"},
            "answer": {"text":"缺少可计算的适用真实条款或目标设备。未使用预设电流100判断，也未生成控制指令。"},
            "requested_source": {"standard_id": requested_standard, "version": requested_version}}
    if not device_id or device.get("device_type") != "transformer":
        return "uncertain", data, []
    # 实验设备显式绑定来源条款ID，避免把不同标准/版本的阈值混用。
    # 保留全库检索结果，再进行条款ID索引召回；不伪装为语义Top-K命中。
    bound_id = device.get("assessment_clause_id")
    bound = next((unit for unit in getattr(pipeline.retriever.repository, 'units', []) if unit.clause_id == bound_id),None)
    if bound is not None and (requested_standard and bound.standard_id != requested_standard
            or requested_version and not pipeline.retriever._version_matches(bound, requested_version)):
        bound = None
    data["retrieval_trace"]={"semantic_candidates":len(matched.rules),"device_bound_clause_id":bound_id,"bound_clause_found":bound is not None}
    candidates = list(matched.rules)
    if bound is not None:
        candidates += [SimpleNamespace(rule=rule) for rule in bound.rules if not any(hit.rule.rule_id == rule.rule_id for hit in candidates)]
        data["matching"]["rules"] += [{"rule_id":rule.rule_id,"content":rule.content,"rank":None,"score":None,"retrieval_method":"optional_device_clause_hint"} for rule in bound.rules if not any(hit.rule.rule_id==rule.rule_id for hit in matched.rules)]
    # 当前只支持这一清楚限定的条款结构，不泛化解析复杂逻辑。
    for hit in candidates:
        unit = pipeline.retriever.repository.unit_for_rule(hit.rule.rule_id)
        if not unit:
            continue
        if requested_standard and unit.standard_id != requested_standard:
            continue
        if requested_version and not pipeline.retriever._version_matches(unit, requested_version):
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
        current_checks = _checks(facts, fields, limits)
        current_normal = all(check["passed"] for check in current_checks)
        hypothetical = _hypothetical_values(request, decomposed)
        hypothesis_mode = hypothetical.get('cooling_mode', mode)
        numeric_constraints = [item for item in decomposed.constraints if _parameter_field(item.get('parameter'))]
        has_hypothesis = bool(hypothetical or numeric_constraints or re.search(r'假设|假如|假定', request.query))
        hypothesis_limits = [float(values[0][1]), float(values[1][1]),
                             float(values[2][2 if hypothesis_mode == 'OD' else 1])]
        hypothetical_checks = (_hypothesis_checks(hypothetical, numeric_constraints, fields, hypothesis_limits)
                               if hypothesis_mode in ('ON', 'OF', 'OD') else [])
        if has_hypothesis:
            if any(check.get('conflicting') for check in hypothetical_checks):
                status = "uncertain"
            elif any(check["passed"] is False for check in hypothetical_checks):
                status = "abnormal"
            elif len(hypothetical_checks) == len(fields) and all(check['passed'] is True for check in hypothetical_checks):
                status = "normal"
            else:
                status = "uncertain"
            active_checks = hypothetical_checks
            basis = "user_hypothesis"
        else:
            status = "normal" if current_normal else "abnormal"
            active_checks = current_checks
            basis = "simulation_snapshot"
        provenance = {"standard_id":unit.standard_id,"version":unit.version,"clause_id":unit.clause_id,"rule_id":hit.rule.rule_id,"source_uri":unit.source_uri,"source_excel":source,"quote":hit.rule.content}
        data["device_assessment"].update(status=status, assessment_basis=basis,
            rule=hit.rule.content, checks=active_checks,
            current_snapshot_assessment={"status": "normal" if current_normal else "abnormal",
                                         "runtime_facts": facts, "checks": current_checks})
        if has_hypothesis:
            data["device_assessment"]["hypothetical_assessment"] = {
                "status": status, "provided_facts": hypothetical, "checks": hypothetical_checks,
                "constraints": numeric_constraints,
                "cooling_mode": hypothesis_mode,
                "complete": len(hypothetical_checks) == len(fields)}
        data["selected_rule"]={"rule_id":hit.rule.rule_id,"content":hit.rule.content}
        data["real_clause_evidence"]=provenance
        data["semantic"]=asdict(pipeline.extractor.extract_rule(hit.rule,unit))
        data["consistency"]=pipeline.consistency.compare(expanded,hit.rule.content).to_dict()
        if has_hypothesis:
            hypothesis_text = ("用户假设值中存在越限。" if status == "abnormal" else
                "用户假设值均未越限。" if status == "normal" else
                "用户假设参数不完整、区间跨越限值或条件存在冲突，无法确定整体是否越限。")
            if hypothesis_mode not in ('ON', 'OF', 'OD'):
                hypothesis_text = '用户假设的冷却方式不明确或存在冲突，无法比对假设工况。'
            data["answer"]["text"] = (hypothesis_text + "该结论仅针对用户假设工况；"
                + ("当前模拟快照另行比对为未越限。" if current_normal else "当前模拟快照另行比对为存在越限。"))
        else:
            data["answer"]["text"] = ("按检索到的来源条款比对，这三个当前模拟温升参数均未越限。" if current_normal else "按检索到的来源条款比对，当前模拟温升参数存在越限。")
        data["answer"]["text"] += "该条款只有限值要求，没有明确跳闸或调节动作，因此不生成控制指令。标准编号、版本及完整适用上下文仍需核验。"
        data["control_block_reason"]="限值条款不等于动作授权；缺少明确动作条款及完整适用上下文"
        return ("uncertain" if status == "uncertain" else "answered"),data,[provenance]
    if requested_standard or requested_version:
        data["answer"]["text"] = f"未找到同时满足指定标准{requested_standard or '（未指定编号）'}和版本{requested_version or '（未指定版本）'}的可计算条款，未降级使用其他来源。"
    return "uncertain",data,[]
