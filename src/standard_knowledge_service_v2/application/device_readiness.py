"""Read-only action precondition diagnostics; never create or encode commands."""
from copy import deepcopy
import json

from ..instruction_engine.preconditions import ActionPreconditionEvaluator

_STATUSES = {'pass': 'ready', 'fail': 'blocked', 'uncertain': 'unknown'}


def evaluate_device_readiness(device, requested_action, *, devices=(), profile=None):
    """Report only facts present in the current snapshot, including missing facts."""
    template = device.get('actions', {}).get(requested_action)
    base = {'device_id': device['device_id'], 'requested_action': requested_action,
            'scope': 'action_preconditions', 'dispatch_allowed': False}
    if not isinstance(template, dict):
        return {**base, 'status': 'unknown', 'checks': [], 'reason': '该设备未配置待判断动作，无法确认前置条件。'}
    facts = {**(device.get('state') or {}), **(device.get('runtime_facts') or {})}
    evaluator = ActionPreconditionEvaluator()
    decision = evaluator.evaluate(template.get('condition', ''), facts, template.get('constraints'))
    expressions = [template.get('condition', '')]
    for constraint in template.get('constraints') or []:
        if constraint.get('role') == 'compliance':
            continue
        expressions.append(f"{constraint['parameter']} {constraint['operator']} {constraint.get('value', '')}{constraint.get('unit', '')}"
            if constraint.get('parameter') and constraint.get('operator') else str(constraint.get('value', '')))
    checks = []
    for step, expression in zip(decision.to_dict()['trace'], expressions):
        evidence = step['evidence']
        field = evidence.get('field')
        expected = evidence.get('expected')
        match = evaluator.engine._pattern.match(expression)
        if match:
            field = field or match.group('field')
            raw = match.group('value')
            expected = evaluator.engine._coerce(facts[raw] if raw in facts else raw)
        checks.append({**deepcopy(evidence), 'actual': deepcopy(facts.get(field)),
                       'field': field, 'expected': expected, 'expression': expression,
                       'status': _STATUSES[step['status']], 'reason': step['message']})
    # Related-device interlocks are also facts, never a preview or inferred permission.
    groups = (profile or {}).get('groups', {})
    groups = groups.values() if isinstance(groups, dict) else groups
    groups = [group for group in groups if isinstance(group, dict) and device['device_id'] in group.values()]
    group = groups[0] if len(groups) == 1 else {}
    by_id = {item['device_id']: item for item in devices}
    for requirement in template.get('relation_requirements', []):
        related_id = group.get(requirement.get('role'))
        field = str(requirement.get('field', ''))
        current = by_id.get(related_id, {})
        for part in field.split('.'):
            current = current.get(part) if isinstance(current, dict) else None
        wanted = requirement.get('value')
        literal = json.dumps(wanted, ensure_ascii=False) if isinstance(wanted, bool) else str(wanted)
        expression = f"related_fact {requirement.get('operator', '==')} {literal}"
        related = evaluator.evaluate(expression, {'related_fact': current})
        trace = related.to_dict()['trace'][0]
        checks.append({'device_id': related_id, 'field': field, 'actual': deepcopy(current),
                       'expected': deepcopy(wanted), 'expression': expression,
                       'status': _STATUSES[trace['status']], 'reason': trace['message']})
    statuses = {check['status'] for check in checks}
    status = 'blocked' if 'blocked' in statuses else 'unknown' if 'unknown' in statuses or not checks else 'ready'
    return {**base, 'status': status, 'checks': checks}
