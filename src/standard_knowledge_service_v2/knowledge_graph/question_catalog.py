"""Questions bound to present source records, not invented device thresholds."""
from pathlib import Path


def available_questions(pipeline):
    units = pipeline.retriever.repository.units
    cases = []
    definitions = [
        ("compressor-test-temperature", "空气压缩机能效试验的吸气温度应在什么范围内？", "GB 19153-2019", "6.2", "5", "知识查阅"),
        ("compressor-test-conditions", "空气压缩机能效试验规定工况的吸气压力、温度和湿度是多少？", "GB 19153-2019", "6.1", "0.1", "知识查阅"),
        ("compressor-efficiency-levels", "空气压缩机能效等级分几级，哪一级最高？", "GB 19153-2019", "4.1", "1级", "知识查阅（不判定具体能效等级）"),
        ("greenhouse-data-records", "温室气体数据记录管理体系应记录哪些信息？", "Q/GGW", "8.1.2", "责任人", "新补充数据查阅（标准名称编号不完整，待核验）"),
        ("greenhouse-cross-check", "温室气体排放报告内部审核需要进行哪些数据检查？", "Q/GGW", "8.1.3", "交叉校验", "新补充数据查阅（标准名称编号不完整，待核验）"),
        ("greenhouse-report", "温室气体排放报告应包括哪些内容？", "Q/GGW", "9.1.1", "活动数据", "新补充数据查阅（不提供缺失的附录格式）"),
        ("greenhouse-quality-plan", "哪些单位需要制定和实施温室气体数据质量控制计划？", "Q/GGW", "8.1.4", "质量控制计划", "新补充正文查阅（文号及适用性待复核）"),
        ("greenhouse-report-duty", "哪些单位需要编制温室气体排放报告？", "Q/GGW", "9.1.2", "编制", "新补充正文查阅（不判定具体单位是否纳入碳配额管控）"),
        ("methane-first-inspection", "初次开工设备和管线的密封点应在多久内进行甲烷逸散检测？", "Q/GGW", "6.1.1.1", "30日", "新补充正文查阅（仅检测期限，不自动操作设备）"),
        ("methane-first-repair", "发现泄漏后应在多久内进行首次维修？", "Q/GGW", "10.2.2", "5日", "新补充正文查阅（人工维修要求，不转换为阀门启停指令）"),
        ("methane-deferred-repair", "延迟修复清单中的泄漏点最迟什么时候应完成修复？", "Q/GGW", "10.3.2.2", "2", "新补充正文查阅（不补造延迟修复许可条件）"),
        ("methane-substantive-repair", "首次维修后仍泄漏且不符合延迟修复条件，应多久内完成修复？", "Q/GGW", "10.4.1", "15日", "新补充正文查阅（文号及适用性待复核）"),
        ("methane-reinspection", "泄漏修复后何时复测，满足什么条件才可摘除标识牌？", "Q/GGW", "10.5.1", "复测", "新补充正文查阅（原文未给泄漏控制浓度数值，不补造阈值）"),
    ]
    for case_id, query, standard_id, chapter, term, scope in definitions:
        unit = next((u for u in units if u.standard_id == standard_id and u.chapter_path == chapter and term in u.text), None)
        if unit is None:
            continue  # Do not advertise an absent source.
        cases.append({"case_id": case_id, "name": query, "query": query, "scenario_hint": "",
            "parameters": {"standard_id": standard_id, "chapter_path": chapter, "simulation_mode": False},
            "scope": scope, "expected_status": "answered", "expected_clause_id": unit.clause_id,
            "expected_term": term, "source": {"standard_id": standard_id, "chapter_path": chapter,
            "filename": Path(unit.source_uri).name, "quote": unit.text}, "source_binding": "显式限定标准编号与条款号后执行分解、检索和图谱溯源"})
    for number, status in ((1, "abnormal"), (2, "normal")):
        if any(u.clause_id == "11_clause2" for u in units):
            query = f"模拟变压器{number}目前的温升状态是否正常？"
            cases.append({"case_id": f"transformer-{number}", "name": query, "query": query,
                "scenario_hint": "substation_maintenance", "parameters": {"simulation_mode": True},
                "expected_status": "answered", "expected_assessment": status,
                "expected_clause_id": "11_clause2", "scope": "三个温升参数比对，不等于整体健康，不授权跳闸"})
    cases.append({"case_id": "breaker-no-source", "name": "模拟断路器依据不足测试",
        "query": "SIM-IEC-BREAKER-01目前状态是否正常？", "scenario_hint": "grid_fault_isolation",
        "parameters": {"simulation_mode": True}, "expected_status": "uncertain",
        "scope": "当前没有完整的适用条款绑定，必须返回依据不足且无控制载荷"})
    return {"graph": pipeline.knowledge_graph.summary(), "cases": cases,
            "notice": "示例依据当前已加载JSON。补充条款是待复核初稿；能查阅不等于可控制。"}
