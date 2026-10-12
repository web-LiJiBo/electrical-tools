"""Read-only live advice check against the actual combined library, no dispatch."""
import json
from pathlib import Path

from standard_knowledge_service_v2.bootstrap import build_application
from standard_knowledge_service_v2.contracts import AnalysisRequest

root = Path(__file__).resolve().parents[2]
pipeline = build_application(root / 'configs/settings.example.yaml').facade
# Do not append experimental requests to the main application audit file.
pipeline.audit_store = None
question = ('仅作模拟分析：换流阀冷却系统的阀出水温度保护已经动作，'
            '目前尚未向极控系统发送功率回降命令，功率回降定值尚未确定。'
            '目前的处理方式是否符合条款，应采取什么操作？请引用依据，'
            '说明是否宜发直流闭锁命令；不要实际下发。')
response = pipeline.analyze(AnalysisRequest(question, parameters={'simulation_mode': False}))
data = response.data
record = {'question': question, 'library_units': len(pipeline.retriever.repository.units),
    'decomposition_source': data.get('decomposition', {}).get('source'),
    'status': response.status, 'selected_rule': data.get('selected_rule'),
    'top_retrieved_rules': data.get('matching', {}).get('rules', [])[:5],
    'advice': data.get('advice'), 'candidate_instruction': data.get('candidate_instruction'),
    'simulation_tasks_created': len(pipeline.simulation_session.tasks),
    'scope': 'actual_library_live_model_advice_only_no_execution'}
print(json.dumps(record, ensure_ascii=False, default=str))
