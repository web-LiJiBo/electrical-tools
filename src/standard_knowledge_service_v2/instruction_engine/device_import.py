"""Validate and publish additive, simulation-only device batches."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import unicodedata

from .simulation import DEFAULT_PROFILES
from .simulation_catalog import SimulationCatalog
from . import manual_device_config


IMPORT_PATH = DEFAULT_PROFILES.parents[1] / 'data' / 'simulation' / 'imported_devices.json'
MAX_BATCH = 50
MAX_DEVICES = 500
MAX_FILE_SIZE = 512 * 1024
BLUEPRINT = 'SIM-IEC-FAN-01'
SCENARIO = 'substation_maintenance'
FACT_LABELS = {
    'running': '风机运行中',
    'start_permission': '启动许可',
    'stop_permission': '停止许可',
    'power_available': '电源可用',
    'maintenance_lockout': '检修闭锁',
    'device_fault': '设备故障',
    'redundant_cooling_available': '备用冷却可用',
}
ACTION_LABELS = {'start': '启动', 'stop': '停止'}


def _encode(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True).encode('utf-8')


def _sample(service):
    device = service.devices[BLUEPRINT]
    initial = {**device['initial_state'], **device['runtime_facts']}
    return {
        'device_id': 'SIM-IMPORT-FAN-01', 'display_name': '演示冷却风机01',
        'scenario_id': SCENARIO, 'template_id': BLUEPRINT,
        'initial_values': {key: bool(initial[key]) for key in FACT_LABELS},
        'actions': list(ACTION_LABELS),
    }


def options(service):
    blueprint = service.devices[BLUEPRINT]
    return {
        'max_batch': MAX_BATCH, 'max_file_size': MAX_FILE_SIZE, 'sample': _sample(service),
        'fact_labels': FACT_LABELS, 'action_labels': ACTION_LABELS,
        'conditions': {key: {'condition': blueprint['actions'][key]['condition'],
                             'constraints': blueprint['actions'][key]['constraints']} for key in ACTION_LABELS},
        'load_error': getattr(service, 'import_load_error', ''),
        'manual_configuration': manual_device_config.options(),
    }


def _identity(value):
    return ''.join(unicodedata.normalize('NFKC', value).split()).casefold()


def _prepare(service, rows, catalog=None):
    staged = deepcopy(service)
    blueprint = service.devices[BLUEPRINT]
    existing = (catalog or SimulationCatalog(legacy_service=service)).devices
    names = {_identity(name) for device in existing.values() for name in
             [device['device_id'], device.get('display_name', ''), *device.get('aliases', [])]}
    ids = set(existing)
    errors, preview = [], []
    for index, row in enumerate(rows, 1):
        manual = isinstance(row, dict) and row.get('template_id') == 'manual_iec61850'
        fields = {'device_id', 'display_name', 'scenario_id', 'template_id', 'actions'}
        fields.update({'device_type', 'fields'} if manual else {'initial_values'})
        if not isinstance(row, dict) or set(row) != fields:
            errors.append({'row': index, 'field': '', 'message': '设备记录字段不完整或包含未知字段，请对照示例。'})
            continue
        identifier, name = row['device_id'], row['display_name']
        state, actions = row.get('initial_values'), row['actions']
        issues = {}
        pattern = r'SIM-[A-Z0-9]+(?:-[A-Z0-9]+)*' if manual else r'SIM-IMPORT-FAN-[A-Z0-9]{1,16}'
        if not isinstance(identifier, str) or len(identifier) > 48 or not re.fullmatch(pattern, identifier):
            issues['device_id'] = ('编号须以 SIM- 开头，使用大写字母、数字和连字符，最多 48 个字符。' if manual
                                   else '编号须以 SIM-IMPORT-FAN- 开头，后接 1 至 16 位大写字母或数字。')
        elif identifier in ids or _identity(identifier) in names:
            issues['device_id'] = '设备编号已存在或与另一台设备的名称冲突。'
        if (not isinstance(name, str) or not 2 <= len(name) <= 40 or name != name.strip()
                or not name.strip() or any(unicodedata.category(c)[0] == 'C' for c in name)
                or _identity(name).startswith('sim-')):
            issues['display_name'] = '名称须为 2 至 40 个字符，不能含控制字符、首尾空白或使用 SIM- 前缀。'
        elif _identity(name) in names:
            issues['display_name'] = '设备名称与现有设备、别名或本批次名称重复。'
        if manual:
            if not issues:
                try:
                    device = manual_device_config.compile_device(row)
                except ValueError as exc:
                    issues['配置'] = str(exc)
            if issues:
                errors.extend({'row': index, 'field': field, 'message': message} for field, message in issues.items())
                continue
            ids.add(identifier)
            names.add(_identity(name))
            staged.devices[identifier] = device
            staged.states[identifier] = deepcopy(device['initial_state'])
            preview.append({'row': index, 'device_id': identifier, 'display_name': name,
                            'scenario_id': row['scenario_id'], 'actions': list(device['actions']),
                            'fields': deepcopy(row['fields'])})
            continue
        if row['scenario_id'] != SCENARIO or row['template_id'] != BLUEPRINT:
            issues['template_id'] = '当前支持变电站设备运维场景的 IEC61850 冷却风机模板。'
        if (not isinstance(state, dict) or set(state) != FACT_LABELS.keys()
                or any(type(value) is not bool for value in state.values())):
            issues['initial_values'] = '所有初始状态都须填写，且值只能是 true 或 false。'
        if (not isinstance(actions, list) or not 1 <= len(actions) <= len(ACTION_LABELS)
                or any(not isinstance(action, str) or action not in ACTION_LABELS for action in actions)
                or len(set(actions)) != len(actions)):
            issues['actions'] = '至少选择一个动作，仅支持启动和停止，且不能重复。'
        if issues:
            errors.extend({'row': index, 'field': field, 'message': message} for field, message in issues.items())
            continue
        ids.add(identifier)
        names.add(_identity(name))
        device = deepcopy(blueprint)
        device.update(device_id=identifier, display_name=name, aliases=[], source='synthetic_device_import')
        device['initial_state']['running'] = state['running']
        device['runtime_facts'].update({key: int(value) for key, value in state.items() if key != 'running'})
        device['actions'] = {key: device['actions'][key] for key in actions}
        device['mapping']['object_reference'] = f'{identifier.replace("-", "_")}/CTRL/GGIO1.SPCSO1'
        staged.devices[identifier] = device
        staged.states[identifier] = deepcopy(device['initial_state'])
        preview.append({'row': index, 'device_id': identifier, 'display_name': name, 'actions': actions,
                        'initial_values': state,
                        'protocol_profile': 'pending'})
    if errors:
        return errors, preview, None, None
    try:
        next_catalog = SimulationCatalog(legacy_service=staged)
    except ValueError as exc:
        return [{'row': None, 'field': '', 'message': str(exc)}], preview, None, None
    return [], preview, staged, next_catalog


def _read(path):
    if not path.exists():
        return []
    with path.open('rb') as handle:
        content = handle.read(MAX_FILE_SIZE + 1)
    if len(content) > MAX_FILE_SIZE:
        raise ValueError('已导入设备文件超出大小限制。')
    data = json.loads(content)
    if (not isinstance(data, dict) or data.get('simulation_only') is not True or data.get('schema_version') != 1
            or not isinstance(data.get('devices'), list) or len(data['devices']) > MAX_DEVICES):
        raise ValueError('已导入设备文件格式无效。')
    return data['devices']


def load_imported(service, path=None):
    path = Path(path or IMPORT_PATH)
    try:
        rows = _read(path)
        if rows:
            errors, _, staged, _ = _prepare(service, rows)
            if errors:
                raise ValueError(errors[0]['message'])
            service.devices, service.states = staged.devices, staged.states
    except (OSError, ValueError, RecursionError):
        service.import_load_error = '已发布的导入数据无法加载，请修复数据文件后重启；内置模拟设备仍可使用。'


def _replace(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.tmp', delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with temporary.open('wb') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def process(session, runtime, rows, *, publish=False, revision=None, path=None):
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_BATCH:
        raise ValueError(f'每批须包含 1 至 {MAX_BATCH} 台设备。')
    path = Path(path or IMPORT_PATH)
    with session.lock:
        service = session.service
        if getattr(service, 'import_load_error', ''):
            raise ValueError(service.import_load_error)
        published = _read(path)
        if len(published) + len(rows) > MAX_DEVICES:
            raise ValueError(f'导入设备总数不能超过 {MAX_DEVICES} 台。')
        errors, preview, staged, catalog = _prepare(service, rows, runtime.catalog)
        if errors:
            return {'status': 'invalid', 'errors': errors, 'devices': preview}
        token = hashlib.sha256(_encode([published, rows])).hexdigest()
        if not publish:
            return {'status': 'validated', 'revision': token, 'errors': [], 'devices': preview}
        if revision != token:
            raise ValueError('数据或导入记录已变化，请重新校验后发布。')
        previous = _encode({'schema_version': 1, 'simulation_only': True, 'devices': published}) if path.exists() else None
        content = _encode({'schema_version': 1, 'simulation_only': True, 'devices': published + rows})
        if len(content) > MAX_FILE_SIZE:
            raise ValueError('导入数据总大小超出限制。')
        facts = {**session.facts, **{row['device_id']: deepcopy(staged.devices[row['device_id']]['runtime_facts'])
                                    for row in rows}}
        _replace(path, content)
        try:
            runtime.refresh_catalog(catalog)
        except Exception:
            if previous is None:
                path.unlink()
            else:
                _replace(path, previous)
            raise
        service.devices, service.states, session.facts = staged.devices, staged.states, facts
        return {'status': 'published', 'errors': [], 'devices': preview}
