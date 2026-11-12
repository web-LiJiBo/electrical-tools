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
        raise ValueError('模板含不支持字段；条款引用由分析结果提供')
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


def _runtime_catalog(service):
    from .simulation_catalog import SimulationCatalog
    return SimulationCatalog(legacy_service=service)


def load_custom(service, path=CUSTOM_PATH, *, strict=True):
    """Load user templates without leaving a half-mutated catalogue.

    Strict mode is used by validation/tests and rejects the complete file.  The
    application session uses non-strict mode so one obsolete or damaged row is
    quarantined instead of preventing every simulated device from starting.
    """
    if not Path(path).exists():
        service.template_load_errors = []
        return []
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        if strict:
            raise ValueError('用户模板文件不是有效JSON') from exc
        service.template_load_errors = ['用户模板文件不是有效JSON']
        return []
    if not isinstance(data, dict) or data.get('simulation_only') is not True:
        if strict:
            raise ValueError('补充模板须标明仅模拟使用')
        service.template_load_errors = ['补充模板未标明仅模拟使用']
        return []
    rows = data.get('items')
    if not isinstance(rows, list):
        if strict:
            raise ValueError('用户模板items必须为JSON数组')
        service.template_load_errors = ['用户模板items必须为JSON数组']
        return []
    loaded, errors, seen = [], [], set()
    staged = deepcopy(service)
    for index, row in enumerate(rows):
        try:
            if not isinstance(row, dict) or not isinstance(row.get('template'), dict):
                raise ValueError('模板记录必须包含template对象')
            raw = {k: v for k, v in row['template'].items() if k not in ('source_rule_ids', 'source_scope', 'expected_feedback', 'state_key', 'state_value')}
            key, action, template = validate_template(staged, dict(row, template=raw))
            identity = (key, action)
            if identity in seen or action in staged.devices[key]['actions']:
                raise ValueError('补充模板不能重复或覆盖已有设备动作')
            candidate = deepcopy(staged)
            candidate.devices[key]['actions'][action] = template
            # Include derived feedback points and all other device instances.
            # Historical conflicts are quarantined one row at a time.
            _runtime_catalog(candidate)
            staged = candidate
            seen.add(identity)
            loaded.append({'device_id': key, 'action': action, 'template': template})
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f'第{index + 1}条: {exc}')
    if errors and strict:
        service.template_load_errors = errors
        raise ValueError('用户模板运行校验失败；' + '；'.join(errors[:3]))
    # Apply only after validation finishes, so strict failure never leaves a
    # partially initialized catalogue.
    for row in loaded:
        service.devices[row['device_id']]['actions'][row['action']] = row['template']
    service.template_load_errors = errors
    return loaded


def save_custom(service, payload, path=CUSTOM_PATH, *, publish=None):
    key, action, template = validate_template(service, payload)
    if action in service.devices[key]['actions']:
        raise ValueError('该设备已存在此动作，请选择其他设备或动作')
    path = Path(path)
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'simulation_only': True, 'items': []}
    if not isinstance(data, dict) or data.get('simulation_only') is not True or not isinstance(data.get('items'), list):
        raise ValueError('现有用户模板文件结构无效，未覆盖原文件')
    if any(isinstance(row, dict) and row.get('device_id') == key and row.get('action') == action
           for row in data['items']):
        raise ValueError('该设备的持久记录已存在此动作，请先修正未加载的历史模板')
    data['items'].append({'device_id': key, 'action': action, 'template': template})
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False, suffix='.tmp') as handle:
        temporary = handle.name
        json.dump(data, handle, ensure_ascii=False, indent=2)
    try:
        # Validate the complete prospective runtime before touching the live
        # service or persistent file. Keep old quarantined rows for inspection.
        validation_service = SimulationInstructionService()
        loaded = load_custom(validation_service, temporary, strict=False)
        if not any(row['device_id'] == key and row['action'] == action for row in loaded):
            raise ValueError('补充模板运行目录校验失败；' + '；'.join(validation_service.template_load_errors))
        catalog = _runtime_catalog(validation_service)
        previous = path.read_bytes() if path.exists() else None
        os.replace(temporary, path)
        try:
            if publish is not None:
                publish(catalog)
        except Exception:
            # A failed publication must not leave a saved-but-reported-failed
            # template behind. The legacy service has not been changed yet.
            if previous is None:
                path.unlink()
            else:
                with tempfile.NamedTemporaryFile(mode='wb', dir=path.parent, delete=False, suffix='.tmp') as backup:
                    backup.write(previous)
                    rollback = backup.name
                try:
                    os.replace(rollback, path)
                finally:
                    if os.path.exists(rollback):
                        os.unlink(rollback)
            raise
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    service.devices[key]['actions'][action] = template
    service.template_load_errors = list(validation_service.template_load_errors)
    return {'status': 'saved', 'device_id': key, 'action': action, 'source_binding_status': 'pending'}


def test_template(service, payload):
    key, action, template = validate_template(service, payload)
    probe = SimulationInstructionService()
    probe.devices = deepcopy(service.devices)
    probe.states = deepcopy(service.states)
    probe.devices[key]['actions'][action] = template
    _runtime_catalog(probe)
    facts, parameters = payload.get('facts', {}), payload.get('parameters', {})
    if not isinstance(facts, dict) or not isinstance(parameters, dict):
        raise ValueError('测试事实和参数必须为JSON对象')
    result = probe.generate(key, action, facts, parameters)
    return {'valid': True, 'candidate': asdict(result), 'status': 'generated' if result.payload else 'blocked'}
