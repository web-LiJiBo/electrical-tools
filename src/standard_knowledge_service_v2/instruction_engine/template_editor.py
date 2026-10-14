"""Persistent user templates for isolated simulated devices."""
from copy import deepcopy
from dataclasses import asdict
import json
import math
from pathlib import Path
import tempfile
import os

from .simulation import SimulationInstructionService, DEFAULT_PROFILES

CUSTOM_PATH = DEFAULT_PROFILES.parent / 'custom_instruction_templates.json'
ACTIONS = {'start', 'stop', 'alarm', 'trip', 'close', 'adjust_active_power', 'adjust_reactive_power', 'regulate_voltage', 'limit_power'}


def validate_template(service, payload):
    key, action = payload.get('device_id'), payload.get('action')
    if not isinstance(key, str) or not isinstance(action, str) or key not in service.devices or action not in ACTIONS:
        raise ValueError('请选择已登记模拟设备和支持的动作')
    template = deepcopy(payload.get('template'))
    if not isinstance(template, dict):
        raise ValueError('模板必须为JSON对象')
    allowed = {'function', 'condition', 'constraints', 'parameter', 'unit', 'minimum', 'maximum', 'value', 'mapping', 'source_note'}
    if set(template) - allowed:
        raise ValueError('模板含不支持字段；条款绑定由后端管理')
    for field in ('function', 'condition'):
        if not isinstance(template.get(field), str) or not template[field].strip():
            raise ValueError(f'请填写{field}')
    engine = service.preconditions.engine
    if not engine._pattern.match(template['condition']):
        raise ValueError('条件须为单个可计算比较式，例如start_permission == 1')
    constraints = template.get('constraints', [])
    if not isinstance(constraints, list):
        raise ValueError('联锁须为JSON数组')
    for c in constraints:
        if not isinstance(c, dict) or c.get('role') != 'precondition' or not isinstance(c.get('parameter'), str) or c.get('operator') not in ('==', '!=', '<', '<=', '>', '>='):
            raise ValueError('每个联锁须包含parameter、operator、value和role=precondition')
        if type(c.get('value')) not in (int, float) or not math.isfinite(c['value']):
            raise ValueError('联锁比较值须为有限数值')
    if template.get('parameter'):
        if not isinstance(template['parameter'], str) or not isinstance(template.get('unit'), str) or not template['unit'].strip():
            raise ValueError('数值动作须填写参数名称和单位')
        for f in ('minimum', 'maximum'):
            if type(template.get(f)) not in (int, float) or not math.isfinite(template[f]):
                raise ValueError('参数上下限须为有限数值')
        if template['minimum'] > template['maximum']:
            raise ValueError('参数下限不能大于上限')
    elif type(template.get('value')) is not bool:
        raise ValueError('开关动作值须为true或false')
    if not isinstance(template.get('mapping'), dict):
        raise ValueError('请填写协议点位JSON对象')
    template.update(source_rule_ids=[], source_scope='user_simulation_template_pending_source_binding')
    # Validate encoding independently of current permission facts.
    probe = SimulationInstructionService()
    probe.devices = deepcopy(service.devices)
    probe.states = deepcopy(service.states)
    test = deepcopy(template)
    test.update(condition='editor_probe >= 1', constraints=[])
    probe.devices[key]['actions'][action] = test
    params = {test['parameter']: test['minimum']} if test.get('parameter') else {}
    candidate = probe.generate(key, action, {'editor_probe': 1}, params)
    if not candidate.payload:
        raise ValueError('协议点位或参数编码无效：' + (candidate.explanation or '、'.join(candidate.missing_fields)))
    return key, action, template


def load_custom(service, path=CUSTOM_PATH):
    if not Path(path).exists():
        return []
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('simulation_only') is not True:
        raise ValueError('补充模板须标明仅模拟使用')
    loaded = []
    for row in data['items']:
        raw = {k: v for k, v in row['template'].items() if k not in ('source_rule_ids', 'source_scope', 'expected_feedback', 'state_key', 'state_value')}
        key, action, template = validate_template(service, dict(row, template=raw))
        if action in service.devices[key]['actions']:
            raise ValueError('补充模板不能覆盖已有设备动作')
        service.devices[key]['actions'][action] = template
        loaded.append({'device_id': key, 'action': action, 'template': template})
    return loaded


def save_custom(service, payload, path=CUSTOM_PATH):
    key, action, template = validate_template(service, payload)
    if action in service.devices[key]['actions']:
        raise ValueError('该设备已存在此动作，请选择其他设备或动作')
    path = Path(path)
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'simulation_only': True, 'items': []}
    data['items'].append({'device_id': key, 'action': action, 'template': template})
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False, suffix='.tmp') as handle:
        temporary = handle.name
        json.dump(data, handle, ensure_ascii=False, indent=2)
    try:
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    service.devices[key]['actions'][action] = template
    return {'status': 'saved', 'device_id': key, 'action': action, 'source_binding_status': 'pending'}


def test_template(service, payload):
    key, action, template = validate_template(service, payload)
    probe = SimulationInstructionService()
    probe.devices = deepcopy(service.devices)
    probe.states = deepcopy(service.states)
    probe.devices[key]['actions'][action] = template
    facts, parameters = payload.get('facts', {}), payload.get('parameters', {})
    if not isinstance(facts, dict) or not isinstance(parameters, dict):
        raise ValueError('测试事实和参数必须为JSON对象')
    result = probe.generate(key, action, facts, parameters)
    return {'valid': True, 'candidate': asdict(result), 'status': 'generated' if result.payload else 'blocked'}
