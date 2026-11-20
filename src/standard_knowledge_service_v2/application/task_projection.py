"""Derive routing summaries from model-authored tasks, without parsing verbs again."""


def project_tasks(result):
    operations, queries = result.operations, result.queries
    if operations is None or queries is None:
        return
    previous = (result.intent, result.scenario.get('query_kind'), result.scenario.get('context_kind'), result.actions)
    if operations:
        result.actions = list(dict.fromkeys(row['action'] for row in operations))
        result.intent, kind = 'instruction', 'operation'
    elif queries:
        kinds = [row['query_kind'] for row in queries]
        kind = next((name for name in ('assessment', 'standard_query', 'device_readiness',
                                      'device_status', 'device_capability') if name in kinds), 'other')
        if kind == 'assessment':
            result.intent = 'compliance'
        elif result.intent not in ('consistency', 'difference') or kind != 'standard_query':
            result.intent = 'search'
        if not any(name in ('assessment', 'standard_query') for name in kinds):
            result.actions = list(dict.fromkeys(row['requested_action'] for row in queries if row.get('requested_action')))
    elif result.prohibitions:
        result.intent, kind, result.actions = 'search', 'other', []
    else:
        return  # Keep genuine unresolved requests for the clarification path.
    result.scenario['query_kind'] = kind
    if any(row.get('conditions') for row in operations):
        result.scenario['context_kind'] = 'precondition'
    elif result.scenario.get('context_kind') != 'uncertain':
        result.scenario['context_kind'] = 'background' if result.context_facts else 'none'
    current = (result.intent, kind, result.scenario.get('context_kind'), result.actions)
    if current != previous:
        result.normalization_notes.append('问题类型与动作摘要由逐项任务统一推导，执行前提按每项操作保留')
