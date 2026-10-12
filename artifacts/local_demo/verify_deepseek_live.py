"""Explicit live API verification, isolated synthetic source, never real dispatch."""
import json
from pathlib import Path
from urllib.error import HTTPError

from standard_knowledge_service_v2.application.analysis_pipeline import AnalysisPipeline
from standard_knowledge_service_v2.application.grounded_advice import GroundedAdviceService
from standard_knowledge_service_v2.config import load_config
from standard_knowledge_service_v2.contracts import AnalysisRequest
from standard_knowledge_service_v2.decomposition.deepseek_decomposer import DeepSeekConfig, DeepSeekDecomposer
from standard_knowledge_service_v2.domain import ClauseKnowledgeUnit, Entity, Rule
from standard_knowledge_service_v2.retrieval_engine.clause_retriever import JsonClauseRepository
from standard_knowledge_service_v2.retrieval_engine.lunwen_adapter import LocalLunwenRetrievalAdapter

root = Path(__file__).resolve().parents[2]
case = json.loads((root / 'tests/fixtures/instruction_question.json').read_text(encoding='utf-8'))
config = load_config(root / 'configs/settings.example.yaml', root)


class ObservedDeepSeek(DeepSeekDecomposer):
    def __init__(self, settings):
        super().__init__(settings)
        self.calls = []

    def complete(self, system_prompt, user_prompt):
        try:
            result = super().complete(system_prompt, user_prompt)
        except Exception as error:
            self.calls.append({'success': False, 'error_type': type(error).__name__,
                               'http_status': error.code if isinstance(error, HTTPError) else None})
            raise
        self.calls.append({'success': True})
        return result


client = ObservedDeepSeek(DeepSeekConfig(api_base=config.llm.api_base,
    model=config.llm.remote_model, api_key_env=config.llm.api_key_env,
    timeout_seconds=config.llm.timeout_seconds, temperature=config.llm.temperature,
    max_tokens=config.llm.max_new_tokens))
source = case['source']
unit = ClauseKnowledgeUnit(source['clause_id'], source['standard_id'], 'TEST', 'TEST-1', source['text'],
    entities=[Entity('TEST-breaker', '断路器', '设备')],
    rules=[Rule(source['rule_id'], '断路器', source['action'], source['condition'], content=source['text'])],
    metadata={'audit': {'manual_review_required': False}, 'synthetic_test_only': True})
pipeline = AnalysisPipeline(LocalLunwenRetrievalAdapter(JsonClauseRepository([unit])), decomposer=client)
session = pipeline.simulation_session
session.service.devices[case['device_id']]['actions']['trip']['source_rule_ids'] = [source['rule_id']]
pipeline.advisor = GroundedAdviceService(client)
response = pipeline.analyze(AnalysisRequest(case['question'], parameters=case['parameters']))
record = {'question': case['question'], 'model': config.llm.remote_model,
    'api_calls': client.calls, 'decomposition_source': response.data.get('decomposition', {}).get('source'),
    'source_scope': 'synthetic_test_not_real_standard', 'status': response.status,
    'advice': response.data.get('advice'), 'candidate': response.data.get('candidate_instruction'),
    'input_position': session.service.states[case['device_id']]['position']}
record['generation_only'] = True
print(json.dumps(record, ensure_ascii=False, default=str))
