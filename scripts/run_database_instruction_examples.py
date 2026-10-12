"""Run source-grounded examples without remote API calls or simulated dispatch."""
from __future__ import annotations

import json
import os
from pathlib import Path

from standard_knowledge_service_v2.bootstrap import build_application
from standard_knowledge_service_v2.contracts import AnalysisRequest
from standard_knowledge_service_v2.data_ingestion.supplemental_excel import _write_json


ROOT = Path(__file__).resolve().parents[1]
CASES = [
    {"name": "补充条款知识查询", "query": "空气压缩机能效试验的吸气温度应在什么范围内？",
     "scenario_hint": "substation_maintenance", "parameters": {},
     "expectation": "引用GB 19153-2019第6.2条；不生成设备控制载荷"},
    {"name": "异常模拟设备状态询问", "query": "模拟变压器1目前的温升状态是否正常？",
     "scenario_hint": "substation_maintenance", "parameters": {"simulation_mode": True},
     "expectation": "原库温升条款支持局部参数越限判定；不因越限擅自生成跳闸指令"},
    {"name": "正常模拟设备状态询问", "query": "模拟变压器2目前的温升状态是否正常？",
     "scenario_hint": "substation_maintenance", "parameters": {"simulation_mode": True},
     "expectation": "原库温升条款支持三个模拟参数未越限判定；不生成控制载荷"},
    {"name": "请求跳闸但条件表达式不可执行", "query": "阀厅出现火情，请生成阀厅火灾报警系统跳闸的候选指令，仅用于模拟测试。",
     "scenario_hint": "grid_fault_isolation", "target_protocol": "IEC61850",
     "parameters": {"阀厅出现火情": True, "device_id": "SIM-IEC-BREAKER-01", "device_type": "断路器",
                    "device_config": {"device_id": "SIM-IEC-BREAKER-01", "logical_node": "XCBR1", "data_object": "Pos"}},
     "expectation": "检索火情动作条款；中文条件不能直接用布尔事实代替，控制载荷必须为空"},
    {"name": "仅能耗计量依据不能授权停机", "query": "请依据能耗数据采集要求生成空气压缩机的停机控制指令，仅用于模拟测试。",
     "scenario_hint": "power_grid_operation", "target_protocol": "IEC61850",
     "parameters": {"device_id": "SIM-IEC-BREAKER-01", "device_type": "空气压缩机",
                    "device_config": {"device_id": "SIM-IEC-BREAKER-01", "logical_node": "XCBR1", "data_object": "Pos"}},
     "expectation": "计量条款没有停机授权；其他召回结果不得凭相似性授权，载荷为空"},
]


def main():
    # The offline config's unused key is forcibly absent for this isolated run.
    name = 'ELECTRICAL_TOOLS_OFFLINE_UNUSED_KEY'
    previous = os.environ.pop(name, None)
    try:
        app = build_application(ROOT / 'configs/settings.offline.yaml')
        pipeline = app.facade
        pipeline.audit_store = None  # Store test results separately from user audits.
        results = []
        for case in CASES:
            request = {key: case[key] for key in ('query', 'scenario_hint', 'parameters', 'target_protocol') if key in case}
            response = pipeline.analyze(AnalysisRequest(**request)).to_dict()
            candidate = response['data'].get('candidate_instruction')
            payload = (candidate or {}).get('payload', {})
            results.append({**case, 'request': request,
                            'checks': {'no_control_payload': not bool(payload),
                                       'no_real_dispatch': not bool((candidate or {}).get('dispatch_allowed'))},
                            'response': response})
            print(case['name'], response['status'], 'payload_empty=', not bool(payload))
        path = ROOT.parent / '补充标准条款' / '测试样例' / '当前数据库指令生成样例及结果.json'
        _write_json(path, {'database_units': len(pipeline.retriever.repository.units),
                          'mode': 'offline_no_dispatch',
                          'known_issues': ['补充条款查询命中，但SemanticValidator仍要求action，ILR校验仍要求前置条件，非控制查询因此可能返回fail；本次不实施修复'],
                          'positive_control_example_available': False,
                          'cases': results})
        if not all(all(item['checks'].values()) for item in results):
            raise AssertionError('当前负例出现控制载荷或自动下发许可，需要检查')
        print(path)
    finally:
        if previous is not None:
            os.environ[name] = previous


if __name__ == '__main__':
    main()
