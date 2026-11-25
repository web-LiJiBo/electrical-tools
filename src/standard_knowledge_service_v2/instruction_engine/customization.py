"""Normalized local device/instruction bindings and transactional publication."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from . import manual_device_config as manual
from .customization_wire import extract_wire, apply_wire
from .device_import import _encode, _replace, _identity
from .simulation import DEFAULT_PROFILES, SimulationInstructionService
from .simulation_catalog import SimulationCatalog

CUSTOM_PATH = DEFAULT_PROFILES.parents[1] / 'data' / 'simulation' / 'customization.json'
EMPTY = {'devices': [], 'instructions': [], 'bindings': []}
MAX_SIZE = 1024 * 1024


def _read():
    path = Path(CUSTOM_PATH)
    if not path.exists():
        return deepcopy(EMPTY)
    content = path.read_bytes()
    if len(content) > MAX_SIZE:
        raise ValueError('自定义配置文件过大，未覆盖原文件。')
    data = json.loads(content)
    if (not isinstance(data, dict) or data.get('schema_version') != 1
            or data.get('simulation_only') is not True or not isinstance(data.get('state'), dict)):
        raise ValueError('自定义配置文件结构无效，未覆盖原文件。')
    return data['state']


def _base():
    from .device_import import load_imported
    from .template_editor import load_custom
    service = SimulationInstructionService()
    load_imported(service)
    load_custom(service, strict=False)
    if getattr(service, 'import_load_error', ''):
        raise ValueError(service.import_load_error)
    return service


def device_fields(device):
    fields = []
    for section, values, metadata in [('state', 'initial_state', 'state_fields'),
                                      ('runtime_facts', 'runtime_facts', 'runtime_fact_fields')]:
        for key, value in device.get(values, {}).items():
            spec = device.get(metadata, {}).get(key, {})
            kind = spec.get('type') or ('boolean' if type(value) is bool else 'integer' if type(value) is int else 'number' if type(value) is float else 'enum')
            fields.append(dict(key=key, label=spec.get('display_name', key), section=section,
                               type=kind, unit=spec.get('unit', '') or '', value=value))
    return fields


def _compile(device, actions):
    return manual.compile_device(dict(device, template_id='manual_iec61850', actions=actions))


def _presets(catalog):
    result = []
    for key, device in catalog.devices.items():
        if device.get('source') == 'customization':
            continue
        kind = device['device_type']
        if kind not in manual.DEVICE_TYPES:
            continue
        fields = device_fields(device)
        specs = {f['key']: f for f in fields}
        for name, action in device['actions'].items():
            if name not in manual.ACTIONS[kind]:
                continue
            try:
                effects = action['simulation_effects']
                section = 'state' if effects.get('state') else 'runtime_facts'
                field = next(iter(effects[section]))
                conditions = []
                expressions = [action['condition']]
                for rule in action.get('constraints', []):
                    if rule.get('role') != 'precondition':
                        raise ValueError('不支持复用的联锁')
                    expressions.append(f"{rule['parameter']} {rule['operator']} {rule['value']}")
                for expression in expressions:
                    match = re.fullmatch(r'([a-z][a-z0-9_]*)\s*(==|!=|<=|>=|<|>)\s*(.+)', expression.strip())
                    if not match:
                        raise ValueError('复杂条件保留原目录查看')
                    f, op, value = match.groups()
                    spec = specs[f]
                    if spec['type'] == 'boolean':
                        if value.lower() not in ('true', 'false', '0', '1'):
                            raise ValueError('条件值无效')
                        wanted = value.lower() in ('true', '1')
                    elif spec['type'] == 'integer':
                        wanted = int(value)
                    else:
                        wanted = float(value)
                    conditions.append(dict(field=f, operator=op, value=wanted))
                needed = {field, *(r['field'] for r in conditions)}
                required = [deepcopy(f) for f in fields if f['key'] in needed]
                row = dict(action=name, result_field=field, minimum=action.get('minimum'), maximum=action.get('maximum'), conditions=conditions)
                _compile(dict(device_id=key, display_name=device['display_name'], scenario_id=device.get('scenario'), device_type=kind, fields=required), [row])
                result.append(dict(instruction_id=f'PRESET:{key}:{name}', display_name=f"{device['display_name']} · {manual.ACTIONS[kind][name]}",
                    device_type=kind, fields=required, action=row, readonly=True, source_device_id=key, wire=extract_wire(device, name)))
            except (KeyError, TypeError, ValueError, StopIteration):
                continue
    return result


def _revision(state, catalog):
    # Include legacy imports/templates: an editor cannot confirm against stale references.
    return hashlib.sha256(_encode([state, catalog.devices])).hexdigest()


def snapshot(session, runtime):
    with session.lock:
        state = _read()
        base = SimulationCatalog(legacy_service=_base())
        devices = []
        for key, device in runtime.catalog.devices.items():
            devices.append(dict(deepcopy(device), scenario_id=device.get('business_scenario', device.get('scenario')),
                                fields=device_fields(device), readonly=key not in {d['device_id'] for d in state['devices']}))
        return dict(state=deepcopy(state), base_revision=_revision(state, base), devices=devices,
                    instructions=[*deepcopy(state['instructions']), *_presets(base)], options={**manual.options(), 'wire_presets': [dict(device_id=k, action=a, wire=extract_wire(d, a)) for k, d in base.devices.items() for a in d['actions']], 'wire_schema': {'protocols': ['IEC61850', 'Modbus'], 'sections': ['communication', 'command', 'feedback']}},
                    load_error=getattr(session.service, 'customization_load_error', ''), load_warning=getattr(session.service, 'customization_load_warning', ''), incomplete_bindings=[deepcopy(r) for r in state['bindings'] if 'wire' not in r])


def _keys(row, expected, message):
    if not isinstance(row, dict) or set(row) != set(expected.split()):
        raise ValueError(message)


def _prepare(state, previous, *, base_service=None, strict=True):
    _keys(state, 'devices instructions bindings', '配置须包含 devices、instructions、bindings。')
    if any(not isinstance(state[k], list) or len(state[k]) > 500 for k in EMPTY):
        raise ValueError('每类配置必须是最多500条的数组。')
    # Legacy template publication supplies its prospective, old-only service:
    # rebuilding from disk here would discard that not-yet-published template.
    service = deepcopy(base_service) if base_service is not None else _base()
    base = SimulationCatalog(legacy_service=service)
    presets = {r['instruction_id']: r for r in _presets(base)}
    custom, instructions, bound = {}, {}, {}
    wires = {}
    used_instructions = set()
    names = {_identity(n) for d in base.devices.values() for n in [d['device_id'], d['display_name'], *d.get('aliases', [])]}
    for row in state['devices']:
        _keys(row, 'device_id display_name scenario_id device_type fields', '设备字段不完整或含未知字段。')
        key, name = row['device_id'], row['display_name']
        if (not isinstance(key, str) or len(key) > 48 or not re.fullmatch(r'SIM-[A-Z0-9]+(?:-[A-Z0-9]+)*', key)
                or key in custom or key in base.devices or _identity(key) in names):
            raise ValueError('新设备编号必须唯一，以SIM-开头，最多48个大写字母、数字或连字符。')
        if (not isinstance(name, str) or not 2 <= len(name) <= 40 or name != name.strip()
                or any(ord(c) < 32 for c in name) or _identity(name) in names or _identity(name).startswith('sim-')):
            raise ValueError('设备名称须为2至40字符且不能与已有设备或别名重复。')
        names.update((_identity(name), _identity(key)))
        custom[key] = row
    if {r['device_id'] for r in previous['devices']} - custom.keys():
        raise ValueError('已发布设备不能在本次编辑中删除；请保留设备以保持运行状态。')
    for old in previous['devices']:
        updated = custom[old['device_id']]
        if any(old[k] != updated[k] for k in ('scenario_id', 'device_type')):
            raise ValueError('已发布设备归属场景和类型不能更换，请为其他场景建立独立实例。')
        specs = {f['key']: f for f in updated['fields']}
        for field in old['fields']:
            if field['key'] not in specs or any(field[k] != specs[field['key']][k] for k in ('section', 'type', 'unit')):
                raise ValueError('已发布设备的现有字段不能删除或更改分区、类型、单位，以保留当前状态。')
    for row in state['instructions']:
        _keys(row, 'instruction_id display_name device_type fields action', '指令字段不完整或含未知字段。')
        key = row['instruction_id']
        if (not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}', key)
                or key.startswith('PRESET:') or key in instructions):
            raise ValueError('指令编号须唯一，不能使用PRESET:保留前缀。')
        if not isinstance(row['display_name'], str) or not 1 <= len(row['display_name'].strip()) <= 80:
            raise ValueError('请填写有效的指令名称。')
        _compile(dict(device_id='SIM-VALIDATE', display_name='校验设备', scenario_id='substation_maintenance',
                      device_type=row['device_type'], fields=row['fields']), [row['action']])
        instructions[key] = row
    library = {**presets, **instructions}
    seen = set()
    for row in state['bindings']:
        if not isinstance(row, dict) or set(row) not in ({'device_id', 'instruction_id'}, {'device_id', 'instruction_id', 'wire'}):
            raise ValueError('关联须包含device_id、instruction_id和wire。')
        key, identifier = row['device_id'], row['instruction_id']
        if not isinstance(key, str) or not isinstance(identifier, str) or key not in custom and key not in base.devices or identifier not in library:
            raise ValueError('关联引用了不存在的设备或指令。')
        instruction = library[identifier]
        action = instruction['action']
        identity = (key, action['action'])
        if identity in seen:
            raise ValueError('同一设备同一动作不能关联多个指令或重复关联。')
        seen.add(identity)
        target = custom.get(key) or base.devices[key]
        if target['device_type'] != instruction['device_type']:
            raise ValueError(f'{key}：设备类型与指令不兼容。')
        fields = target['fields'] if key in custom else device_fields(target)
        specs = {f['key']: f for f in fields}
        required = {action['result_field'], *(r['field'] for r in action['conditions'])}
        declared = {f['key']: f for f in instruction['fields']}
        for field in required:
            if field not in specs or field not in declared or any(specs[field][part] != declared[field][part] for part in ('section', 'type', 'unit')):
                raise ValueError(f'{key}：字段 {field} 的分区、类型或单位与指令不兼容。')
        wire = row.get('wire')
        if wire is None and identifier in presets and presets[identifier]['source_device_id'] == key:
            wire = presets[identifier]['wire']
        if strict and wire is None:
            raise ValueError(f'{key}：指令须同时配置完整通信、写入及读回报文。')
        if wire is not None:
            if not isinstance(wire, dict):
                raise ValueError('wire必须为完整对象。')
            prior_protocols = {r['wire']['protocol'] for r in previous['bindings'] if r['device_id'] == key and isinstance(r.get('wire'), dict) and 'protocol' in r['wire']}
            if strict and prior_protocols and wire.get('protocol') not in prior_protocols:
                raise ValueError(f'{key}：已发布设备不能更换协议。')
            if key in base.devices and wire.get('protocol') != base.devices[key]['protocol']:
                raise ValueError(f'{key}：已有设备不能更换协议。')
            for prior in wires.get(key, {}).values():
                if prior is not None and (prior.get('protocol') != wire.get('protocol') or prior.get('communication') != wire.get('communication')):
                    raise ValueError(f'{key}：各动作必须共用相同协议及通信配置。')
        wires.setdefault(key, {})[action['action']] = wire
        used_instructions.add(identifier)
        bound.setdefault(key, []).append(action)
    if strict and instructions.keys() - used_instructions:
        raise ValueError('自定义指令至少关联一个设备并补齐完整报文。')
    overlays = {}
    for key in custom.keys() | bound.keys():
        row = custom.get(key)
        target = base.devices.get(key)
        if row is None:
            row = dict(device_id=key, display_name=target['display_name'], scenario_id=target.get('business_scenario', target['scenario']),
                       device_type=target['device_type'], fields=device_fields(target))
        actions = bound.get(key, [])
        if not actions:
            raise ValueError(f'{key}：新设备至少关联一个指令。')
        compiled = _compile(row, actions)
        for action_name, wire in wires.get(key, {}).items():
            if wire is not None:
                apply_wire(compiled, action_name, wire, strict=strict)
            else:
                compiled['actions'][action_name]['wire_profile_missing_fields'] = ['legacy_wire_configuration']
        if target is None:
            compiled['source'] = 'customization'
            service.devices[key] = compiled
            service.states[key] = deepcopy(compiled['initial_state'])
        else:
            device = deepcopy(target)
            for action_name, generated in compiled['actions'].items():
                original = target['actions'].get(action_name)
                if original:
                    if generated.get('custom_action'):
                        raise ValueError(f'{key}：该动作编号已被现有设备使用，请为新增动作填写独立编号。')
                    original_effects = original.get('simulation_effects', {})
                    result = next(r['result_field'] for r in actions if r['action'] == action_name)
                    section = next(f['section'] for f in row['fields'] if f['key'] == result)
                    if result not in original_effects.get(section, {}):
                        raise ValueError(f'{key}：修改已有动作不能改变结果字段，以保留原协议反馈。')
                    merged = deepcopy(original)
                    for field in ('condition', 'constraints', 'minimum', 'maximum'):
                        if field in generated:
                            merged[field] = deepcopy(generated[field])
                    device['actions'][action_name] = merged
                else:
                    device['actions'][action_name] = generated
                wire = wires.get(key, {}).get(action_name)
                if wire is not None:
                    apply_wire(device, action_name, wire, strict=strict)
            overlays[key] = device
            if key in service.devices:
                service.devices[key] = deepcopy(device)
    service.customization_overrides = overlays
    catalog = SimulationCatalog(legacy_service=service)
    return service, catalog, sorted(custom.keys() | bound.keys())


def load_customization(service):
    """Load after both legacy files; quarantine a bad file as a complete unit."""
    try:
        state = _read()
        if state == EMPTY:
            return
        staged, _, _ = _prepare(state, deepcopy(EMPTY), base_service=service, strict=False)
        service.devices, service.states = staged.devices, staged.states
        service.customization_overrides = staged.customization_overrides
        service.customization_load_error = ''
        service.customization_load_warning = ('旧配置缺少报文，请补齐后重新发布。' if any('wire' not in r for r in state['bindings']) else '')
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
        service.customization_load_error = f'自定义配置未加载：{exc}'


def process(session, runtime, payload, *, publish=False):
    with session.lock:
        try:
            previous = _read()
            base = SimulationCatalog(legacy_service=_base())
            baseline = _revision(previous, base)
            if payload.get('base_revision') != baseline:
                raise ValueError('配置已变化，请重新加载后校验；未覆盖现有数据。')
            state = deepcopy(payload.get('state'))
            staged, catalog, affected = _prepare(state, previous)
            token = hashlib.sha256(_encode([baseline, state, catalog.devices])).hexdigest()
            result = dict(status='validated', revision=token, affected_devices=affected, errors=[])
            if not publish:
                return result
            if payload.get('revision') != token:
                raise ValueError('发布确认已失效，请重新校验当前配置。')
            if state == previous:
                return dict(result, status='published', changed=False, requires_reanalysis=False,
                            configuration_revision=runtime.configuration_revision, base_revision=baseline)
            path = Path(CUSTOM_PATH)
            old = path.read_bytes() if path.exists() else None
            content = _encode(dict(schema_version=1, simulation_only=True, state=state))
            if len(content) > MAX_SIZE:
                raise ValueError('自定义配置超过文件大小限制。')
            # Keep all already running state; initial values only seed new instances.
            for key in staged.states.keys() & session.service.states.keys():
                staged.states[key].update(deepcopy(session.service.states[key]))
            facts = {key: {**deepcopy(device.get('runtime_facts', {})), **deepcopy(session.facts.get(key, {}))}
                     for key, device in staged.devices.items()}
            _replace(path, content)
            try:
                runtime.refresh_catalog(catalog)
            except Exception as exc:
                if old is None:
                    path.unlink(missing_ok=True)
                else:
                    _replace(path, old)
                raise ValueError(f'运行目录刷新失败，已回滚：{exc}') from exc
            session.service.devices, session.service.states = staged.devices, staged.states
            session.service.customization_overrides = staged.customization_overrides
            session.service.customization_load_error = ''
            session.service.customization_load_warning = ''
            session.facts = facts
            return dict(result, status='published', changed=True, base_revision=_revision(state, base))
        except (OSError, ValueError, TypeError, KeyError, RecursionError, RuntimeError) as exc:
            return dict(status='invalid', errors=[dict(message=str(exc))], affected_devices=[])
