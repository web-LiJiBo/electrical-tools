"""User observations are provenance-bound context, never executable conditions."""
import re


def context_error(understanding, query, devices):
    compact = lambda value: re.sub(r'\s+', '', str(value)).casefold()
    ids = {row['device_id'] for row in devices}
    for fact in understanding.context_facts:
        if fact['device_id'] not in ids or compact(fact['source_text']) not in compact(query):
            return '背景事实缺少当前设备或原文依据，请明确其来源。'
    if understanding.scenario.get('context_kind') == 'uncertain':
        return '尚不能区分背景说明与执行前提，请明确哪些条件必须在操作前满足。'
    return ''


def background_only(understanding):
    return understanding.scenario.get('context_kind') == 'background' and bool(understanding.context_facts)


def describes_observation(constraint, understanding):
    return background_only(understanding) and any(
        all(constraint.get(key, '') == fact.get(key, '') for key in ('parameter', 'operator', 'value', 'unit'))
        for fact in understanding.context_facts)


def annotate_context(data):
    facts = data.get('decomposition', {}).get('context_facts') or []
    if not facts:
        return
    devices = {row['device_id']: row for row in data.get('devices', [])}
    rows = []
    for fact in facts:
        device = devices.get(fact['device_id'], {})
        current = {**device.get('state', {}), **device.get('runtime_facts', {})}
        rows.append({**fact, 'origin': 'user_statement', 'current_value': current.get(fact['parameter']),
                     'field_status': ('not_matched' if fact['parameter'] not in current
                         else 'unavailable' if current[fact['parameter']] is None else 'unverified'),
                     'comparison': 'not_verified', 'notice': '用户陈述与设备快照分列，单位和测量时点尚未核验；未覆盖设备状态。'})
    data['context_fact_comparison'] = rows
    data.setdefault('answer', {}).setdefault('text', '')
    notice = '背景数据尚未完成核验，详情见“系统理解”。'
    if notice not in data['answer']['text']:
        data['answer']['text'] += '\n' + notice
