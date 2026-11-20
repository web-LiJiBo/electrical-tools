"""Typed, provenance-bearing user inputs for the local simulation world."""
from copy import deepcopy
from decimal import Decimal
import math

from ..application.action_parameters import UNITS, _convert


def fact_schema(profile):
    result = {}
    for section, initial, metadata in [('state', 'initial_state', 'state_fields'),
                                       ('runtime_facts', 'runtime_facts', 'runtime_fact_fields')]:
        fields = {**profile.get(initial, {}), **profile.get(metadata, {})}
        for key in fields:
            spec = deepcopy(profile.get(metadata, {}).get(key, {}))
            value = profile.get(initial, {}).get(key)
            spec.setdefault('type', 'boolean' if type(value) is bool else
                            'integer' if type(value) is int else 'number' if type(value) is float else 'enum')
            spec['section'] = section
            spec.setdefault('unit', '')
            for point in profile.get('points', {}).values():
                if point.get('field') != f'{section}.{key}':
                    continue
                spec['unit'] = point.get('unit') or spec['unit']
                if point.get('data_type') == 'float32':
                    spec['type'] = 'number'
                if point.get('value_encoding'):
                    spec['values'] = list(point['value_encoding'])
            for derived in profile.get('derived_runtime_facts', {}).values():
                if derived.get('field') == f'{section}.{key}':
                    spec['values'] = list(derived['value_encoding'])
            result[f'{section}.{key}'] = spec
    return result


def resolve_field(profile, parameter):
    schema = fact_schema(profile)
    if parameter in schema:
        return parameter, schema[parameter]
    for section in ('runtime_facts', 'state'):
        path = f'{section}.{parameter}'
        if path in schema:
            return path, schema[path]
    return None, None


def normalize_value(value, unit, spec):
    kind = spec['type']
    if kind == 'boolean':
        if type(value) is bool:
            return value
        if type(value) is int and value in (0, 1):
            return bool(value)
        raise ValueError('布尔状态须为true/false或0/1')
    if kind in ('number', 'integer'):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('设备数值须为有限数字')
        target_unit = spec.get('unit', '')
        if unit and unit != target_unit:
            # Reuse the same dimensional conversion rules as action targets.
            current_units = {'A': ('current', '1'), 'kA': ('current', '1000'),
                             'mA': ('current', '0.001')}
            source, target = current_units.get(unit), current_units.get(target_unit)
            if source and target:
                value = float(Decimal(str(value)) * Decimal(source[1]) / Decimal(target[1]))
            elif (unit in UNITS or unit.lower() in UNITS) and target_unit:
                value = float(_convert(value, unit, target_unit))
            else:
                raise ValueError(f'设备状态单位{unit}与配置单位{target_unit or "未登记"}不一致')
        if not math.isfinite(value) or kind == 'integer' and int(value) != value:
            raise ValueError('设备状态数值类型或范围无效')
        return int(value) if kind == 'integer' else value
    if type(value) is not str or not value or spec.get('values') and value not in spec['values']:
        raise ValueError('设备状态枚举值无效：' + '、'.join(spec.get('values', [])))
    return value


def collect_inputs(profiles, facts, business, query, scenario=None):
    """Resolve all sources before mutating anything; user-user conflicts are errors."""
    if not isinstance(business, dict):
        raise ValueError('device_facts须为按设备编号填写的字段对象')
    updates, skipped = {}, []

    def add(device_id, parameter, value, unit, origin, source_text, fact=None):
        profile = profiles.get(device_id)
        if profile is None:
            raise ValueError(f'补充状态的设备不在当前场景：{device_id}')
        if origin == 'question':
            from ..application.semantic_operations import bind_target, _mentions, _explicit_targets
            devices = list(profiles.values())
            evidence = source_text
            if not _mentions(evidence, devices) and _explicit_targets(query, devices, scenario or {}) == {device_id}:
                evidence = query
            owner = fact.get('owner_id', '')
            if not owner:
                from ..application.semantic_operations import _ROLES
                import re
                groups = (scenario or {}).get('groups', {})
                groups = groups.values() if isinstance(groups, dict) else groups
                owners = {group['transformer'] for group in groups
                          if group.get(profile['device_type']) == device_id and group.get('transformer')
                          in _mentions(evidence, devices, nested=True)
                          and re.search(_ROLES.get(profile['device_type'], r'(?!)'), evidence)}
                if len(owners) == 1:
                    owner = next(iter(owners))
            _, reason = bind_target({'device_id': device_id, 'target_text': fact.get('target_text') or evidence,
                'source_text': evidence, 'owner_id': owner}, query, devices, scenario or {})
            if reason:
                raise ValueError('补充状态的设备身份与原文不一致：' + reason)
        path, spec = resolve_field(profile, parameter)
        if path is None:
            if origin == 'question':
                skipped.append({'device_id': device_id, 'parameter': parameter, 'reason': '未匹配设备字段，保留为背景'})
                return
            raise ValueError(f'设备字段未登记：{device_id}.{parameter}')
        value_evidence = None
        if origin == 'question':
            from .fact_evidence import verify_fact_value
            value_evidence = verify_fact_value(fact, profile, spec, normalize_value, profiles.values())
        normalized = normalize_value(value, unit, spec)
        derived = profile.get('derived_runtime_facts', {}).get(path.removeprefix('runtime_facts.'))
        if path.startswith('runtime_facts.') and derived:
            values = [key for key, encoded in derived['value_encoding'].items() if encoded == normalized]
            if len(values) != 1:
                raise ValueError('关联状态值无法确定对应位置')
            path, normalized = derived['field'], values[0]
        if path.startswith('state.'):
            mirror = 'runtime_facts.' + path.split('.')[1]
            mirror_spec = fact_schema(profile).get(mirror)
            if mirror_spec:
                path = mirror
                normalized = normalize_value(int(normalized) if type(normalized) is bool
                                             and mirror_spec['type'] in ('integer', 'number') else normalized,
                                             '', mirror_spec)
        identity = (device_id, path)
        source = {'origin': origin, 'parameter': parameter, 'source_text': source_text,
                  'supplied_value': value, 'supplied_unit': unit}
        if value_evidence:
            source['value_evidence'] = value_evidence
        previous = updates.get(identity)
        if previous and (type(previous['value']) is not type(normalized)
                         and not (type(previous['value']) in (int, float) and type(normalized) in (int, float))
                         or previous['value'] != normalized):
            raise ValueError(f'提问或业务参数对{device_id}.{path}提供了不同值，请明确一个值；未更新模拟状态。')
        if previous:
            previous['sources'].append(source)
        else:
            updates[identity] = {'device_id': device_id, 'field': path, 'value': normalized,
                                 'unit': spec.get('unit', ''), 'sources': [source]}

    compact = lambda text: ''.join(str(text).split()).casefold()
    for fact in facts:
        if fact.get('usage') != 'current' or fact.get('operator') not in ('=', '=='):
            continue
        if not fact.get('source_text') or compact(fact['source_text']) not in compact(query):
            raise ValueError('补充状态缺少提问原文依据')
        add(fact['device_id'], fact['parameter'], fact['value'], fact.get('unit', ''),
            'question', fact['source_text'], fact)
    for device_id, fields in business.items():
        if not isinstance(fields, dict):
            raise ValueError('device_facts每台设备须为字段对象')
        for parameter, value in fields.items():
            unit = ''
            if isinstance(value, dict):
                if set(value) - {'value', 'unit'} or 'value' not in value:
                    raise ValueError('状态参数对象仅支持value和unit')
                unit, value = value.get('unit', ''), value['value']
            add(device_id, parameter, value, unit, 'business_parameters', '')
    return list(updates.values()), skipped
