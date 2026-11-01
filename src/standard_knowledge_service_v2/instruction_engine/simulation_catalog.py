"""Reusable simulation templates, instance points and scenario seed configuration.

This catalog never owns live state or performs communication. Legacy profiles are
copied through an adapter so local/custom actions keep their original contracts.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from .simulation import DEFAULT_PROFILES, SimulationInstructionService


CONFIG_ROOT = DEFAULT_PROFILES.parent
ACTION_LABELS = {
    'start': '启动', 'stop': '停止', 'trip': '分闸', 'close': '合闸',
    'open': '分闸', 'raise': '升一档', 'lower': '降一档', 'set_tap': '设定档位',
    'alarm': '发出模拟告警', 'runback_power': '功率回降', 'limit_power': '设定功率上限',
    'adjust_active_power': '调整有功功率', 'adjust_reactive_power': '调整无功功率',
    'regulate_voltage': '调整电压',
}


class SimulationCatalog:
    """Expand four independent configuration layers into encoder-compatible devices."""

    def __init__(self, legacy_service: SimulationInstructionService | None = None,
                 config_dir: str | Path | None = None) -> None:
        root = Path(config_dir) if config_dir is not None else CONFIG_ROOT
        self.device_templates = self._load(root, 'device_templates', 'template_id')
        self.action_templates = self._load(root, 'action_templates', 'template_id')
        self.scenarios = self._load(root, 'scenario_profiles', 'scenario_id')
        instances = self._load(root, 'device_instances', 'device_id')
        self.devices = deepcopy((legacy_service or SimulationInstructionService()).devices)
        for device in self.devices.values():
            self._adapt_legacy(device)
        for identifier, instance in instances.items():
            if identifier in self.devices:
                raise ValueError(f'显式实例与兼容设备ID冲突: {identifier}')
            self.devices[identifier] = self._expand_instance(instance)
        self._validate()

    @staticmethod
    def _load(root: Path, name: str, identifier: str) -> dict:
        data = json.loads((root / f'{name}.json').read_text(encoding='utf-8'))
        if data.get('simulation_only') is not True:
            raise ValueError('只允许加载simulation_only=true的模拟目录')
        indexed = {}
        for row in data[name]:
            key = row[identifier]
            if not isinstance(key, str) or not key or key in indexed:
                raise ValueError(f'重复或无效的{identifier}: {key}')
            indexed[key] = row
        return indexed

    def _metadata(self, device: dict) -> None:
        kind = device['device_type']
        if kind not in self.device_templates:
            self.device_templates[kind] = {
                'template_id': kind, 'device_type': kind, 'display_name': kind,
                'state_fields': {}, 'runtime_fact_fields': {},
                'capabilities': ['query_state', 'query_measurements', 'query_alarms'],
                'point_specs': {}, 'action_refs': [],
            }
        template = self.device_templates[kind]
        device.setdefault('device_template_ref', kind)
        device.setdefault('state_fields', deepcopy(template['state_fields']))
        device.setdefault('runtime_fact_fields', deepcopy(template['runtime_fact_fields']))
        device['capabilities'] = list(dict.fromkeys([
            *template['capabilities'], *device.get('actions', {}),
        ]))
        for section, metadata in [('initial_state', 'state_fields'), ('runtime_facts', 'runtime_fact_fields')]:
            for key, value in device.get(section, {}).items():
                inferred = 'boolean' if type(value) is bool else 'integer' if type(value) is int else 'number' if type(value) is float else 'enum'
                device[metadata].setdefault(key, {'display_name': key, 'unit': '', 'type': inferred,
                                                'source': 'synthetic_test_fixture'})

    def _adapt_legacy(self, device: dict) -> None:
        identifier, kind = device['device_id'], device['device_type']
        index = '2' if identifier in {'SIM-TRANSFORMER-02', 'SIM-MB-FAN-01', 'SIM-MB-PUMP-01', 'SIM-MB-BREAKER-01'} else '1'
        labels = {'transformer': '变压器', 'breaker': '断路器', 'cooling_fan': '冷却风机', 'oil_pump': '冷却油泵'}
        label = labels.get(kind, kind)
        device.setdefault('display_name', f'模拟{label}{index}')
        aliases = device.setdefault('aliases', [])
        aliases.extend(x for x in [device['display_name'], f'{label}{index}'] if x not in aliases)
        if kind == 'transformer':
            aliases.extend(x for x in [f'主变{index}', f'模拟变压器{index}'] if x not in aliases)
            device['runtime_facts'].setdefault('load_percent', 70 if index == '1' else 55)
            device['runtime_facts'].setdefault('alarm_active', False)
        if kind == 'cooling_fan':
            aliases.extend(x for x in [f'模拟风机{index}', f'冷却风机{index}'] if x not in aliases)
            device['runtime_facts'].setdefault('control_mode', 'remote')
        if kind == 'breaker':
            device['runtime_facts'].setdefault('voltage_present', 1 if device['initial_state'].get('position') == 'closed' else 0)
        self._metadata(device)
        device.setdefault('points', {})
        for action_name, action in device['actions'].items():
            ref = f'{kind}.{action_name}'
            if ref not in self.action_templates:
                # Source metadata and concrete addresses remain on the legacy
                # expanded action; an independent reusable definition is exposed.
                generic = {k: deepcopy(v) for k, v in action.items() if k not in {
                    'mapping', 'source_rule_ids', 'source_scope', 'scenario', 'device_id',
                    'feedback_mapping', 'simulation_effects', 'relation_requirements',
                }}
                digest = hashlib.sha256(json.dumps(generic, sort_keys=True).encode()).hexdigest()[:10]
                ref = f'legacy.{kind}.{action_name}.{digest}'
                self.action_templates.setdefault(ref, {
                    **generic, 'template_id': ref, 'device_type': kind, 'action': action_name,
                    'display_name': ACTION_LABELS.get(action_name, action_name),
                    'command_point': f'{action_name}_command',
                })
            action.setdefault('template_ref', ref)
            action.setdefault('display_name', ACTION_LABELS.get(action_name, action_name))
            effects = self._legacy_effects(device, action_name, action)
            action.setdefault('simulation_effects', effects)
            generic = self.action_templates[ref]
            if generic.get('relation_requirements'):
                action.setdefault('relation_requirements', deepcopy(generic['relation_requirements']))
            command_point = f'{action_name}_command'
            mapping = {**device['mapping'], **action.get('mapping', {})}
            device['points'][command_point] = {**mapping, 'protocol': device['protocol'],
                                                'direction': 'write', 'unit': action.get('unit', '')}
            section = 'state' if effects.get('state') else 'runtime_facts'
            state_key = next(iter(effects[section]))
            feedback_name = f'{state_key}_feedback'
            feedback = self._legacy_feedback(device, feedback_name, section, state_key, action)
            device['points'].setdefault(feedback_name, feedback)
            action.setdefault('feedback_mapping', deepcopy(device['points'][feedback_name]))
        # Transformer observations are read points; there are no invented body
        # start, stop or trip commands.
        for section, metadata in [('state', 'state_fields'), ('runtime_facts', 'runtime_fact_fields')]:
            for field, spec in device[metadata].items():
                name = f'{field}_feedback' if section == 'state' else f'{field}_measurement'
                if name not in device['points']:
                    device['points'][name] = {
                        'protocol': device['protocol'], 'direction': 'read', 'field': f'{section}.{field}',
                        'object_reference': f'LOCAL_{identifier.replace("-", "_")}/STATUS/GGIO1.{field}',
                        **deepcopy(spec),
                    } if device['protocol'] == 'IEC61850' else {
                        'protocol': 'Modbus', 'direction': 'read', 'field': f'{section}.{field}',
                        'transport': 'SIMULATED', 'slave_id': device['mapping']['slave_id'],
                        'address': 2000 + len(device['points']), 'function_code': 3,
                        'data_type': 'uint16', 'scale': 1, **deepcopy(spec),
                    }

    @staticmethod
    def _legacy_effects(device: dict, name: str, action: dict) -> dict:
        if name in {'trip', 'close'}:
            return {'state': {'position': 'open' if name == 'trip' else 'closed'},
                    'runtime_facts': {'current': 0, 'breaker_closed': 0, 'voltage_present': 0} if name == 'trip'
                    else {'breaker_closed': 1, 'voltage_present': 1}}
        if action.get('parameter'):
            key = action.get('current_state_key') or {
                'limit_power': 'power_limit_kw', 'runback_power': 'active_power_mw',
            }.get(name, action['parameter'])
            return {'state': {key: {'from_parameter': action['parameter']}}}
        if name == 'alarm':
            return {'state': {'alarm_active': bool(action.get('value', True))}}
        if 'running' in device['initial_state']:
            return {'state': {'running': bool(action.get('value'))}}
        return {'state': {f'{name}_active': action.get('value')}}

    @staticmethod
    def _legacy_feedback(device: dict, point: str, section: str, field: str, action: dict) -> dict:
        value = device['initial_state'].get(field) if section == 'state' else device['runtime_facts'].get(field)
        position = field == 'position'
        boolean = type(value) is bool or position
        mapping = {**device['mapping'], **action.get('mapping', {})}
        feedback = {'protocol': device['protocol'], 'point': point, 'direction': 'read',
                    'field': f'{section}.{field}', 'unit': action.get('unit', '')}
        if device['protocol'] == 'IEC61850':
            feedback.update(object_reference=mapping['object_reference'].replace('/CTRL/', '/STATUS/') + '.' + field,
                            data_type='enum' if position else 'bool' if boolean else 'uint16', scale=1)
        else:
            feedback.update(transport='SIMULATED', slave_id=mapping['slave_id'], address=mapping['address'] + 1000,
                            function_code=1 if boolean else 3, data_type='bool' if boolean else 'uint16',
                            scale=1 if boolean else mapping.get('scale', 1))
        if position:
            feedback['value_encoding'] = {'open': 1, 'closed': 2} if device['protocol'] == 'IEC61850' else {'open': False, 'closed': True}
        return feedback

    def _expand_instance(self, instance: dict) -> dict:
        ref = instance['device_template_ref']
        if ref not in self.device_templates:
            raise ValueError(f'未知设备模板: {ref}')
        template = self.device_templates[ref]
        device = deepcopy(instance)
        device['device_type'] = template['device_type']
        if device['protocol'] not in template['protocols']:
            raise ValueError('设备协议与模板不兼容')
        device['actions'] = {}
        device['mapping'] = {}
        self._metadata(device)
        for action_ref in template['action_refs']:
            if action_ref not in self.action_templates:
                raise ValueError(f'未知动作模板: {action_ref}')
            action = deepcopy(self.action_templates[action_ref])
            if action['device_type'] != device['device_type'] or device['protocol'] not in action['protocols']:
                raise ValueError('动作类型或协议与设备不兼容')
            try:
                action['mapping'] = deepcopy(device['points'][action['command_point']])
                action['feedback_mapping'] = deepcopy(device['points'][action['feedback_point']])
            except KeyError as exc:
                raise ValueError(f'实例缺少命令或反馈点: {instance["device_id"]}') from exc
            action['feedback_mapping']['point'] = action['feedback_point']
            action['template_ref'] = action_ref
            action['source_scope'] = 'synthetic_test_fixture'
            device['actions'][action['action']] = action
        return device

    def _validate(self) -> None:
        addresses = {}
        for identifier, device in self.devices.items():
            if not identifier.startswith('SIM-'):
                raise ValueError('模拟设备ID必须以SIM-开头')
            for point in device['points'].values():
                if point.get('protocol') == 'Modbus':
                    slave, address = point.get('slave_id'), point.get('address')
                    if type(slave) is not int or not 1 <= slave <= 247 or type(address) is not int or not 0 <= address <= 65535:
                        raise ValueError('模拟Modbus点位地址无效')
                    # Coil/register spaces are distinct in Modbus.
                    space = 'coil' if point.get('function_code') in {1, 5} else 'register'
                    key = ('Modbus', slave, space, address)
                elif point.get('protocol') == 'IEC61850' and point.get('object_reference'):
                    key = ('IEC61850', point['object_reference'])
                else:
                    raise ValueError(f'模拟点位缺少协议或地址: {identifier}')
                if key in addresses and addresses[key] != identifier:
                    raise ValueError(f'模拟总线点位冲突: {identifier} / {addresses[key]}')
                addresses[key] = identifier
            for action in device['actions'].values():
                command = {**device['mapping'], **action.get('mapping', {})}
                feedback = action['feedback_mapping']
                field = 'address' if device['protocol'] == 'Modbus' else 'object_reference'
                if command.get(field) == feedback.get(field):
                    raise ValueError('命令点与反馈点必须分开')
        for scenario in self.scenarios.values():
            ids = scenario['device_ids']
            if len(ids) != len(set(ids)) or not set(ids) <= self.devices.keys():
                raise ValueError('场景引用了重复或未知设备')
            for group in scenario['groups'].values():
                if not set(group.values()) <= set(ids):
                    raise ValueError('场景关系引用了场景外设备')
                for role, identifier in group.items():
                    if role != self.devices[identifier]['device_type']:
                        raise ValueError('场景关系角色与设备类型不匹配')
            for overrides in scenario['conditions'].values():
                if not set(overrides) <= set(ids):
                    raise ValueError('工况引用了场景外设备')

    def make_service(self) -> SimulationInstructionService:
        # Build the legacy encoder first: it does not construct a catalog, so
        # neither path can recurse through the other.
        service = SimulationInstructionService()
        service.devices = deepcopy(self.devices)
        service.states = {key: deepcopy(device['initial_state']) for key, device in service.devices.items()}
        return service

    def describe(self) -> dict:
        return deepcopy({
            'simulation_only': True, 'dispatch_allowed': False,
            'devices': list(self.devices.values()), 'device_templates': list(self.device_templates.values()),
            'action_templates': list(self.action_templates.values()), 'scenarios': list(self.scenarios.values()),
        })
