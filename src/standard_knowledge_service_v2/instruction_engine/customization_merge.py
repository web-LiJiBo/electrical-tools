"""Merge a partial import into a draft; never publishes or guesses conflicts."""
from copy import deepcopy
import json

KINDS = ('devices', 'instructions', 'bindings')


def _identity(kind, row):
    keys = {'bindings': ('device_id', 'instruction_id'), 'devices': ('device_id',),
            'instructions': ('instruction_id',), 'device_types': ('code',), 'units': ('symbol',)}[kind]
    if not isinstance(row, dict) or any(not isinstance(row.get(k), str) or not row[k] for k in keys):
        raise ValueError(f'{kind}缺少有效编号。')
    return ':'.join(row[k] for k in keys)


def _same(a, b):
    return json.dumps(a, sort_keys=True, allow_nan=False) == json.dumps(b, sort_keys=True, allow_nan=False)


def preview(current, incoming, resolutions=None, instruction_library=()):
    """Conflicts are stable keys for explicit current/incoming user choices."""
    original = deepcopy(current)
    try:
        if not isinstance(current, dict) or set(current) - {*KINDS, 'definitions'} or not set(KINDS) <= set(current):
            raise ValueError('当前草稿结构不完整。')
        if isinstance(incoming, dict) and 'state' in incoming:
            incoming = incoming['state']
        if not isinstance(incoming, dict) or not incoming or set(incoming) - {*KINDS, 'definitions'}:
            raise ValueError('导入须包含devices、instructions、bindings中的至少一个数组。')
        if resolutions is None: resolutions = {}
        if not isinstance(resolutions, dict) or any(v not in ('current', 'incoming') for v in resolutions.values()):
            raise ValueError('冲突选择须为保留当前或采用导入。')
        kinds = KINDS
        if 'definitions' in current or 'definitions' in incoming:
            current, incoming = deepcopy(current), deepcopy(incoming)
            for data in (current, incoming):
                definitions = data.get('definitions', {})
                if not isinstance(definitions, dict) or set(definitions) - {'device_types', 'units'}:
                    raise ValueError('类型与单位登记格式无效。')
                for kind in ('device_types', 'units'): data[kind] = definitions.get(kind, [])
            kinds = (*KINDS, 'device_types', 'units')
        merged, conflicts = {}, []
        counts = dict(added=0, unchanged=0, replaced=0, conflicts=0)
        def choose(kind, identifier, old, new):
            key = kind + ':' + identifier
            resolution = resolutions.get(key, '')
            conflicts.append(dict(key=key, kind=kind, id=identifier, current=deepcopy(old),
                                  incoming=deepcopy(new), resolution=resolution))
            if resolution == 'incoming': counts['replaced'] += 1
            return deepcopy(new if resolution == 'incoming' else old)
        indexes = {}
        for kind in kinds:
            previous, additions = current.get(kind, []), incoming.get(kind, [])
            if not isinstance(previous, list) or not isinstance(additions, list) or len(additions) > 500:
                raise ValueError('每类导入须为最多500条的数组。')
            indexed = {}
            for row in previous:
                key = _identity(kind, row)
                if key in indexed: raise ValueError('当前草稿存在重复编号。')
                indexed[key] = deepcopy(row)
            seen = set()
            for row in additions:
                key = _identity(kind, row)
                if key in seen: raise ValueError(f'导入的{kind}存在重复编号：{key}。')
                seen.add(key)
                if key not in indexed:
                    indexed[key] = deepcopy(row); counts['added'] += 1
                elif _same(indexed[key], row): counts['unchanged'] += 1
                else: indexed[key] = choose(kind, key, indexed[key], row)
            if len(indexed) > 500: raise ValueError('合并后每类配置不能超过500条。')
            merged[kind] = list(indexed.values()); indexes[kind] = seen
        library = {r['instruction_id']: r for r in [*instruction_library, *merged['instructions']]}
        incoming_definitions = {r['instruction_id']: r for r in incoming.get('instructions', [])}
        current_definitions = {r['instruction_id']: r for r in current['instructions']}
        groups = {}
        for row in merged['bindings']:
            definition = library.get(row['instruction_id'], {})
            action = definition.get('action', {}).get('action')
            if action: groups.setdefault((row['device_id'], action), []).append(row)
        removed = set()
        for (device, action), bindings in groups.items():
            if len(bindings) < 2: continue
            def from_import(row):
                identifier = row['instruction_id']
                return (_identity('bindings', row) in indexes['bindings']
                        or identifier in incoming_definitions and identifier in current_definitions
                        and not _same(incoming_definitions[identifier], current_definitions[identifier])
                        and _same(library[identifier], incoming_definitions[identifier]))
            old = [r for r in bindings if not from_import(r)]
            new = [r for r in bindings if from_import(r)]
            if not old or not new or len(old) != 1 or len(new) != 1:
                raise ValueError(f'{device}的{action}有多个同侧关联，请先修正当前或导入文件的重复动作。')
            kept = choose('action', device + ':' + action, old, new)
            removed.update(_identity('bindings', r) for r in bindings if r not in kept)
        merged['bindings'] = [r for r in merged['bindings'] if _identity('bindings', r) not in removed]
        # Only definitions made unused by an explicit action-conflict choice are
        # omitted. Preserve intentionally unbound inputs for strict validation.
        affected = {r['instruction_id'] for rows in groups.values() for r in rows
                    if _identity('bindings', r) in removed}
        used = {r['instruction_id'] for r in merged['bindings']}
        skipped = sorted(affected - used)
        merged['instructions'] = [r for r in merged['instructions'] if r['instruction_id'] not in skipped]
        counts['conflicts'] = len(conflicts)
        unresolved = any(not c['resolution'] for c in conflicts)
        if 'device_types' in merged:
            merged['definitions'] = {kind: merged.pop(kind) for kind in ('device_types', 'units')}
        return dict(status='conflicts' if unresolved else 'merged', state=merged, counts=counts,
                    conflicts=conflicts, skipped_instructions=skipped, errors=[])
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        return dict(status='invalid', state=original, counts={}, conflicts=[],
                    skipped_instructions=[], errors=[dict(message=str(exc))])
