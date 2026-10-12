"""Real library + live DeepSeek + template generation; no execution."""
import json
from pathlib import Path
from standard_knowledge_service_v2.bootstrap import build_application
from standard_knowledge_service_v2.contracts import AnalysisRequest

root = Path(__file__).resolve().parents[2]
pipeline = build_application(root / 'configs/settings.example.yaml').facade
pipeline.audit_store = None
before = pipeline.simulation_session.snapshot()
question = '模拟换流阀1的阀出水温度保护动作后，目前的功率回降处理是否符合条款？请依据当前设备状态给出操作建议。'
response = pipeline.analyze(AnalysisRequest(question, parameters={'simulation_mode': True}))
session = pipeline.simulation_session
data = response.data
record = {'question': question, 'library_units': len(pipeline.retriever.repository.units),
    'decomposition_source': data.get('decomposition', {}).get('source'), 'status': response.status,
    'selected_rule_id': data.get('selected_rule', {}).get('rule_id'),
    'advice': {k: v for k, v in data.get('advice', {}).items() if k != 'sources'},
    'candidate_instruction': data.get('candidate_instruction'),
    'input_state': dict(session.service.states['SIM-IEC-VALVE-01'])}
record['generation_only'] = True
record['device_inputs_unchanged'] = before == session.snapshot()
assert record['device_inputs_unchanged']
print(json.dumps(record, ensure_ascii=False, default=str))
