"""Turn cited model advice into the same reviewed plan used by direct requests."""
from copy import deepcopy
from dataclasses import fields

from ..decomposition.models import DecompositionResult, MissingField
from ..llm_decomposition import validate_semantic_plan
from .advice_conversion import dynamic_evidence
from .semantic_resolution import normalize_plan


def execute_cited_plan(pipeline, request, data, instruction, sources, snapshot, profile):
    if request.parameters.get('simulation_mode') is not True:
        return None, '指令预览需要开启模拟模式；未执行设备操作。'
    if not snapshot or instruction['device_id'] != profile.get('device_id'):
        return None, '建议设备与当前目录不一致。'
    from .simulation_access import simulation_runtime
    runtime = simulation_runtime(pipeline)
    evidence, notes, conflicts = dynamic_evidence(sources, instruction['rule_ids'], snapshot, profile)
    if conflicts:
        return None, '；'.join(conflicts)
    original = data.get('decomposition', {})
    names = {field.name for field in fields(DecompositionResult)} - {'missing_fields', 'clause_context'}
    plan = DecompositionResult(**{key: deepcopy(value) for key, value in original.items() if key in names})
    plan.missing_fields = [MissingField(**row) for row in original.get('missing_fields', [])]
    metadata = deepcopy(instruction.get('operation') or {})
    if not metadata:
        metadata = next((deepcopy(row) for row in plan.operations or []
                         if row['device_id'] == instruction['device_id'] and row['action'] == instruction['action']), {})
    if not metadata:
        return None, '条款建议缺少原文设备和操作限制清单，不能省略条件生成。'
    operation = {key: deepcopy(metadata.get(key, '' if key == 'order_evidence' else None)) for key in
                 ('target_text', 'owner_id', 'source_text', 'parameter_evidence', 'condition_evidence', 'conditions', 'order', 'order_evidence')}
    operation.update(device_id=instruction['device_id'], action=instruction['action'],
                     parameters=deepcopy(instruction['parameters']), negated=False, clarification='')
    errors = validate_semantic_plan({'operations': [operation], 'queries': plan.queries or []})
    if errors:
        return None, '条款操作清单格式不完整：' + '；'.join(errors)
    plan.operations = [operation]
    if not any(row['query_kind'] in ('standard_query', 'assessment') for row in plan.queries or []):
        plan.queries = [*(plan.queries or []), {'device_id': instruction['device_id'],
            'target_text': operation['target_text'], 'owner_id': operation['owner_id'],
            'source_text': request.query, 'query_kind': 'standard_query', 'requested_action': '',
            'requested_fields': [], 'clarification': ''}]
    plan.scenario['instruction_basis'] = 'direct'
    plan = normalize_plan(plan, request.query, runtime.catalog, request.parameters, request.conversation_context)
    plan.clause_context = {
        'session_id': snapshot['session_id'], 'snapshot_version': snapshot['version'],
        'catalog_version': runtime._catalog_version(), 'evidence': deepcopy(evidence),
        'sources': [{'rule_id': rid, 'quote': sources[rid][1].content,
                     'source_text': sources[rid][0].metadata.get('source', {}).get('source_text', sources[rid][1].content)}
                    for rid in instruction['rule_ids']],
        'device_snapshot': deepcopy(data['advice']['device_snapshot']),
        'scope': 'simulation_candidate_only_not_formal_standard_approval'}
    execution_request = deepcopy(request)
    execution_request.parameters['simulation_session_id'] = snapshot['session_id']
    response = pipeline._analyze_decomposed(execution_request, plan, process_questions=False, emit_audit=False)
    result = response.data
    for key in ('simulation_preview', 'simulation_batch', 'simulation_plan', 'candidate_instruction',
                'operation_review', 'query_results', 'clarification_required', 'clarification_questions',
                'control_block_reason', 'simulation_session_id', 'devices'):
        if key in result:
            data[key] = deepcopy(result[key])
    data['clause_operation_plan'] = plan.to_dict()
    data['advice']['evidence'], data['advice']['analysis_notes'] = evidence, notes
    reason = result.get('control_block_reason') or result.get('answer', {}).get('text', '')
    data['advice']['conversion'] = {'status': 'generated' if response.status == 'generated' else 'blocked',
        'reason': reason, 'rule_ids': instruction['rule_ids'], 'basis': 'cited_unified_operation_plan'}
    if response.status == 'generated':
        data.setdefault('answer', {})['text'] += '\n' + result.get('answer', {}).get('text', '')
    return response.status, ''
