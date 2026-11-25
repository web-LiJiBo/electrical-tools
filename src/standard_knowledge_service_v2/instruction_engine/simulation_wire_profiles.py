"""Apply explicit synthetic wire profiles without replacing custom point edits.

The JSON file owns the configured addresses and types.  This adapter only joins
those maps to copied catalog instances; it never opens a connection or modifies
an action's conditions, effects, identity, or engineering target.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path


DEFAULT_PROTOCOL_PROFILES = (
    Path(__file__).resolve().parents[3] / 'configs' / 'simulation_protocol_profiles.json'
)


def _missing_fields(mapping: dict, protocol: str, *, command: bool) -> list[str]:
    if protocol == 'Modbus':
        required = ('slave_id', 'address', 'function_code', 'data_type', 'scale',
                    'byte_order', 'word_order')
    elif protocol == 'IEC61850':
        required = ('domain_id', 'item_id', 'object_reference', 'data_type')
        if command:
            required += ('control_model', 'service', 'value_shape', 'include_ctl_num',
                         'include_oper_time', 'control_cancel_supported')
    else:
        return ['supported_simulation_protocol']
    # False flags, zero addresses and zero enum codes are explicit values.
    return [key for key in required
            if key not in mapping or mapping[key] is None or mapping[key] == '']


def _same_mapping(current: dict, original: dict | None, configured: dict) -> bool:
    return current == original or current == configured


def _point_names(action_name: str, action: dict) -> tuple[str, str | None]:
    return (action.get('command_point') or f'{action_name}_command',
            action.get('feedback_mapping', {}).get('point') or action.get('feedback_point'))


def apply_simulation_protocol_profiles(devices: dict, config_path=None) -> list[dict]:
    """Enrich copied device dictionaries and return explicit coverage diagnostics.

    Each configured action records the original *merged* device/action mapping.
    Enrichment is allowed only while its command and feedback maps still match
    that source, or already equal the enriched maps.  A changed/custom action
    keeps its point definitions and receives only device communication defaults;
    missing wire fields are reported rather than guessed.  The operation is
    idempotent and never writes the input configuration file.
    """
    path = Path(config_path) if config_path is not None else DEFAULT_PROTOCOL_PROFILES
    config = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(config, dict) or config.get('simulation_only') is not True
            or not isinstance(config.get('devices'), dict)):
        raise ValueError('通信配置必须为simulation_only=true的显式模拟设备目录')

    diagnostics = []
    for identifier, device in devices.items():
        configured = config['devices'].get(identifier)
        missing, preserved = [], []
        if configured is None and device.get('communication'):
            # Explicit customization owns its own instance maps and endpoints.
            for action_name, action in device.get('actions', {}).items():
                fields = _missing_fields(action.get('mapping', {}), device['protocol'], command=True)
                fields += ['feedback_mapping.' + k for k in _missing_fields(action.get('feedback_mapping', {}), device['protocol'], command=False)]
                action['wire_profile_missing_fields'] = fields
                missing.extend(f'actions.{action_name}.{k}' for k in fields)
            device['wire_profile_missing_fields'] = missing
            diagnostics.append({'device_id': identifier, 'status': 'custom_mapping', 'missing_fields': missing, 'preserved_actions': list(device.get('actions', {}))})
            continue
        if configured is None:
            missing.append('simulation_protocol_profile')
            device['wire_profile_missing_fields'] = missing
            diagnostics.append({'device_id': identifier, 'status': 'missing_profile',
                                'missing_fields': deepcopy(missing), 'preserved_actions': []})
            continue
        communication = configured.get('communication', {})
        if (communication.get('simulation_only') is not True
                or not communication.get('host') or not communication.get('port')):
            raise ValueError(f'模拟通信配置缺少明确地址或模拟标记: {identifier}')
        # Existing explicitly supplied communication settings are user settings.
        # The fixture must never erase them or allow its simulation marker off.
        device['communication'] = {
            **deepcopy(communication), **deepcopy(device.get('communication', {})),
            'simulation_only': True,
        }
        device['wire_profile_id'] = communication['profile_id']
        runtime_facts = device.setdefault('runtime_facts', {})
        for name, value in configured.get('initial_runtime_facts', {}).items():
            runtime_facts.setdefault(name, deepcopy(value))
        device['derived_runtime_facts'] = {
            **deepcopy(configured.get('derived_runtime_facts', {})),
            **deepcopy(device.get('derived_runtime_facts', {})),
        }
        for section in ('state_fields', 'runtime_fact_fields'):
            fields = device.setdefault(section, {})
            for name, specification in configured.get(section, {}).items():
                fields.setdefault(name, deepcopy(specification))
        points = device.setdefault('points', {})
        source_points = configured.get('source_points', {})
        configured_points = configured.get('points', {})
        applicable, protected = {}, set()

        for action_name, action in device.get('actions', {}).items():
            entry = configured.get('actions', {}).get(action_name)
            command_name, feedback_name = _point_names(action_name, action)
            current = {**device.get('mapping', {}), **action.get('mapping', {})}
            if entry:
                # Source point comparison also detects edits to device.points
                # that have not yet been copied into the action mapping.
                expected_command = entry['command_point']
                expected_feedback = entry['feedback_point']
                command_unchanged = _same_mapping(
                    points.get(expected_command), source_points.get(expected_command),
                    configured_points[expected_command])
                feedback_unchanged = _same_mapping(
                    points.get(expected_feedback), source_points.get(expected_feedback),
                    configured_points[expected_feedback])
                unchanged = (
                    _same_mapping(current, entry['source_mapping'], entry['mapping'])
                    and _same_mapping(action.get('feedback_mapping', {}),
                                      entry.get('source_feedback_mapping'),
                                      entry['feedback_mapping'])
                    and command_unchanged and feedback_unchanged
                )
            else:
                unchanged = False
            if unchanged:
                applicable[action_name] = entry
            else:
                preserved.append(action_name)
                protected.add(command_name)
                if feedback_name:
                    protected.add(feedback_name)
                if entry:
                    protected.update((entry['command_point'], entry['feedback_point']))

        # Several actions may share one readback point.  If a custom edit owns
        # that point, every action using it must retain the same original map.
        # Otherwise an unchanged sibling could refer to a newly configured
        # feedback address while the actual point still has the custom address.
        changed = True
        while changed:
            changed = False
            for action_name, entry in list(applicable.items()):
                if entry['command_point'] in protected or entry['feedback_point'] in protected:
                    del applicable[action_name]
                    preserved.append(action_name)
                    protected.update((entry['command_point'], entry['feedback_point']))
                    changed = True

        for point_name, point in configured_points.items():
            if point_name in protected:
                continue
            current = points.get(point_name)
            if current is None or _same_mapping(current, source_points.get(point_name), point):
                points[point_name] = deepcopy(point)

        for action_name, action in device.get('actions', {}).items():
            entry = applicable.get(action_name)
            if entry:
                action['mapping'] = deepcopy(entry['mapping'])
                action['feedback_mapping'] = deepcopy(entry['feedback_mapping'])
                action['command_point'] = entry['command_point']
                action['feedback_point'] = entry['feedback_point']
            current = {**device.get('mapping', {}), **action.get('mapping', {})}
            fields = _missing_fields(current, device['protocol'], command=True)
            fields += [f'feedback_mapping.{key}' for key in _missing_fields(
                action.get('feedback_mapping', {}), device['protocol'], command=False)]
            action['wire_profile_missing_fields'] = fields
            missing.extend(f'actions.{action_name}.mapping.{key}' for key in fields)

        for point_name, point in points.items():
            if not isinstance(point, dict):
                missing.append(f'points.{point_name}.mapping')
                continue
            missing.extend(f'points.{point_name}.{key}' for key in _missing_fields(
                point, device['protocol'], command=point.get('direction') == 'write'))
        device['wire_profile_missing_fields'] = list(dict.fromkeys(missing))
        diagnostics.append({
            'device_id': identifier,
            'status': 'custom_mapping' if preserved else 'configured',
            'profile_id': communication['profile_id'],
            'missing_fields': deepcopy(device['wire_profile_missing_fields']),
            'preserved_actions': preserved,
        })
    return diagnostics
