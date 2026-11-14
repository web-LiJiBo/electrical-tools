"""Withdraw adopted knowledge consistently after an explicit unsupported decision."""

from ..reporting.grounded_generator import GroundedReportGenerator


def invalidate_answer(data: dict, reason: str) -> None:
    """Keep retrieval diagnostics, never an adopted conclusion or executable artifact.

    The caller owns the response's external evidence list and final status. Only
    explicitly unsupported child answers are withdrawn; successful facts survive.
    """
    answer = data.setdefault('answer', {})
    advice = data.get('advice') or {}
    analysis = ([advice.get('summary'), *[item.get('text') for item in advice.get('suggestions', [])]]
                if advice.get('answer_supported') is False else [])
    # Never retain the original answer text: it may still assert the withdrawn
    # conclusion when a later response layer performs the invalidation.
    answer['text'] = '\n'.join(dict.fromkeys(str(part) for part in [*analysis, reason] if part))
    for key in ('conclusion', 'source_rule_id', 'rule_ids', 'sources', 'evidence'):
        answer.pop(key, None)
    answer.update(support_status='unsupported', adopted=False)
    for key in ('selected_rule', 'knowledge_graph_evidence', 'real_clause_evidence', 'consistency', 'semantic', 'three_layer_semantics',
                'if_then', 'swrl', 'ilr', 'simulation_preview', 'simulation_batch',
                'simulation_plan', 'instruction_generation', 'operation_plan', 'adopted_sources', 'adopted_rule_ids'):
        data.pop(key, None)
    if 'evidence' in data:
        data['evidence'] = []
    data['candidate_instruction'] = None
    data['control_block_reason'] = reason
    if isinstance(data.get('matching'), dict):
        data['matching'].update(adopted=False, usage='retrieval_diagnostics_only')
    data['validation'] = {'status': 'uncertain', 'dispatch_allowed': False, 'adopted': False,
                          'layers': {'source_support': 'unsupported'}, 'errors': [reason], 'warnings': []}
    if isinstance(data.get('device_assessment'), dict):
        assessment = data['device_assessment']
        for field in ('checks', 'current_snapshot_assessment', 'hypothetical_assessment', 'assessment_basis'):
            assessment.pop(field, None)
        assessment.update(status='uncertain', rule=reason, adopted=False)
    if isinstance(data.get('advice'), dict):
        advice_status = 'unavailable' if data['advice'].get('status') == 'unavailable' else 'unsupported'
        data['advice'].update(status=advice_status, answer_supported=False, instruction=None, rule_ids=[], sources=[],
                             conversion={'status': 'not_proposed', 'reason': reason})
        data['advice'].pop('evidence', None)
        for suggestion in data['advice'].get('suggestions', []):
            if suggestion.get('purpose') != 'limitation':
                suggestion['rule_ids'] = []
    for item in data.get('query_results', []):
        child = item.get('data', {})
        if child.get('advice', {}).get('answer_supported') is False:
            invalidate_answer(child, child['advice'].get('unable_reason') or reason)
            item.update(status='uncertain', evidence=[])
    if 'report' in data:
        data['report'] = GroundedReportGenerator().generate({
            'context': data.get('context', {}), 'clauses': [], 'instruction': None,
            'advice': data.get('advice'), 'validation': data['validation'], 'warnings': [reason]}).to_dict()
