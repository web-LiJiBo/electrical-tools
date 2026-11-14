"""Explicit, in-memory simulation sessions; no device/network dispatch exists here.

The protocol generator remains pure. Only ``execute`` applies a saved preview,
under a lock, after validating its session version and all current interlocks.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import json
import math
import operator
from pathlib import Path
from threading import RLock
from uuid import uuid4

from .models import CandidateInstruction
from .operation_conditions import compile_conditions, evaluate_conditions


_MISSING = object()
_COMPARISONS = {'==': operator.eq, '!=': operator.ne, '<': operator.lt,
                '<=': operator.le, '>': operator.gt, '>=': operator.ge}


def _read(data, path):
    current = data
    for key in str(path).split('.'):
        if not isinstance(current, dict) or key not in current:
            return _MISSING
        current = current[key]
    return current


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


@dataclass
class _Session:
    session_id: str
    scenario_id: str | None
    condition: str
    profiles: dict
    scenario: dict
    devices: dict
    version: int = 0
    commands: dict = field(default_factory=dict)
    events: list = field(default_factory=list)
    scenario_conditions: dict = field(default_factory=dict)
    plans: dict = field(default_factory=dict)


class SimulationRuntime:
    """Own independent copies of states and server-owned simulation commands."""

    def __init__(self, catalog=None, event_path=None):
        if catalog is None:
            from .simulation_catalog import SimulationCatalog
            catalog = SimulationCatalog()
        self.catalog = catalog
        self._service = catalog.make_service()
        self._sessions = {}
        self._lock = RLock()
        self._event_path = Path(event_path) if event_path is not None else None

    def refresh_catalog(self, catalog):
        """Publish new templates without resetting shared live device state."""
        with self._lock:
            service = catalog.make_service()
            for session in self._sessions.values():
                profiles = {key: deepcopy(catalog.devices[key]) for key in session.profiles}
                if profiles != session.profiles:
                    session.profiles = profiles
                    session.version += 1  # Pending commands must be previewed again.
            self.catalog, self._service = catalog, service

    def create_session(self, scenario_id='substation_maintenance', device_ids=None, condition='normal'):
        with self._lock:
            if scenario_id is not None and (not isinstance(scenario_id, str) or scenario_id not in self.catalog.scenarios):
                raise ValueError('未知模拟场景')
            scenario = deepcopy(self.catalog.scenarios.get(scenario_id, {}))
            if device_ids is None:
                device_ids = scenario.get('device_ids', [])
            if (not isinstance(device_ids, (list, tuple)) or not device_ids
                    or any(not isinstance(key, str) or key not in self.catalog.devices for key in device_ids)
                    or len(device_ids) != len(set(device_ids))):
                raise ValueError('需要非空且唯一的有效模拟设备列表')
            profiles = {key: deepcopy(self.catalog.devices[key]) for key in device_ids}
            session = _Session(f'simulation-{uuid4().hex}', scenario_id, condition, profiles, scenario, {})
            session.devices = self._seed(session, condition)
            session.scenario_conditions = {name: 'normal' for name in scenario.get('business_scenarios', [])}
            self._sessions[session.session_id] = session
            return self._snapshot(session)

    def snapshot(self, session_id):
        with self._lock:
            return self._snapshot(self._session(session_id))

    def preview(self, session_id, device_id, action, parameters=None, *, evidence=None, expected_version=None, conditions=None):
        with self._lock:
            session = self._session(session_id)
            supplied_conditions = deepcopy(conditions if conditions is not None else [])
            compiled, checks, condition_error = self._check_conditions(session, device_id, supplied_conditions)
            if expected_version is not None and (type(expected_version) is not int or expected_version < 0):
                result = self._blocked_preview(session, device_id, '分析状态版本必须是非负整数')
            elif expected_version is not None and expected_version != session.version:
                result = self._blocked_preview(session, device_id, '分析时的状态版本已变化，请重新分析并预览')
            elif condition_error:
                result = self._blocked_preview(session, device_id, condition_error)
            else:
                result = self._prepare(session, device_id, action, parameters)
            result.update(conditions=supplied_conditions, condition_checks=checks)
            if result['status'] == 'blocked':
                result['candidate'].update(payload={}, explanation=result['explanation'])
            self._attach_evidence(result, evidence if evidence is not None else [])
            if result['status'] == 'generated':
                result['command_id'] = f'command-{uuid4().hex}'
                session.commands[result['command_id']] = {
                    'preview': deepcopy(result), 'device_id': device_id, 'action': action,
                    'parameters': deepcopy(parameters if parameters is not None else {}),
                    'evidence': deepcopy(result['analysis_evidence']),
                    'conditions': supplied_conditions, 'compiled_conditions': compiled,
                    'catalog_version': self._catalog_version(), 'result': None,
                }
            return deepcopy(result)

    def execute(self, session_id, command_id, expected_version):
        with self._lock:
            session = self._session(session_id)
            command = session.commands.get(command_id) if isinstance(command_id, str) else None
            if command is None:
                return self._blocked_execution(session, command_id, '未知命令或命令不属于此模拟会话')
            if type(expected_version) is not int or expected_version < 0:
                return self._blocked_execution(session, command_id, '状态版本必须是非负整数')
            if command['result'] is not None:
                return deepcopy(command['result'])
            preview = command['preview']
            if expected_version != preview['expected_version'] or expected_version != session.version:
                result = self._blocked_execution(session, command_id, '状态版本已变化，请重新预览')
            elif command['catalog_version'] != self._catalog_version():
                result = self._blocked_execution(session, command_id, '模拟配置版本已变化，请重新创建会话并预览')
            else:
                _, checks, error = self._check_conditions(session, command['device_id'], command['conditions'])
                plan = session.plans.get(command.get('plan_id'))
                if plan and (plan['status'] != 'active' or plan['next_step'] != command['plan_step']):
                    error = '顺序计划未开放此步骤，须先完成前一步并取得成功反馈'
                refreshed = (self._blocked_preview(session, command['device_id'], error) if error
                             else self._prepare(session, command['device_id'], command['action'], command['parameters']))
                refreshed.update(conditions=deepcopy(command['conditions']), condition_checks=checks)
                self._attach_evidence(refreshed, command['evidence'])
                if refreshed['status'] != 'generated':
                    result = self._blocked_execution(session, command_id, refreshed['explanation'])
                    result['relation_checks'] = refreshed['relation_checks']
                    result['condition_checks'] = checks
                else:
                    result = self._apply(session, command_id, command, refreshed)
            # Each submitted server command has one immutable result, including failures.
            if result.get('event_id') is None:
                result['analysis_evidence'] = deepcopy(command['evidence'])
                self._record(session, result)
            command['result'] = deepcopy(result)
            self._complete_plan_step(session, command, result)
            return deepcopy(result)

    def _check_conditions(self, session, device_id, conditions):
        try:
            compiled = compile_conditions(conditions, session.profiles.get(device_id, {}))
            checks = evaluate_conditions(compiled, session.devices.get(device_id, {}))
            failures = [item['explanation'] for item in checks if item['status'] != 'pass']
            return compiled, checks, '；'.join(failures)
        except (ValueError, TypeError) as exc:
            return [], [], str(exc)

    def create_plan(self, session_id, steps, *, expected_version, evidence=None):
        """Store one reviewed plan and preview its first step, never dispatch."""
        with self._lock:
            session = self._session(session_id)
            if type(expected_version) is not int or expected_version != session.version:
                raise ValueError('分析时的状态版本已变化，请重新分析顺序计划')
            if (type(steps) is not list or not 1 <= len(steps) <= 8
                    or any(type(row) is not dict or type(row.get('parameters', {})) is not dict
                           or row.get('device_id') not in session.profiles
                           or row.get('action') not in session.profiles[row['device_id']]['actions']
                           for row in steps)):
                raise ValueError('顺序计划动作或设备不完整')
            orders = [row.get('order') for row in steps]
            if len(steps) > 1 and all(value is None for value in orders):
                raise ValueError('多步计划必须有明确连续顺序，不能为独立操作擅自添加依赖')
            if any(value is not None for value in orders) and (any(type(value) is not int for value in orders)
                    or sorted(orders) != list(range(1, len(steps) + 1))):
                raise ValueError('仅支持从1开始且连续、唯一的顺序步骤')
            if all(type(value) is int for value in orders):
                steps = sorted(steps, key=lambda row: row['order'])
            # Complete compilation before storing even the first command.
            for row in steps:
                compile_conditions(row.get('conditions', []), session.profiles[row['device_id']])
            identifier = f'plan-{uuid4().hex}'
            plan = {'plan_id': identifier, 'session_id': session_id, 'status': 'active',
                    'next_step': 1, 'expected_version': expected_version,
                    'steps': [{**deepcopy(row), 'step': i + 1, 'preview': None, 'execution': None}
                              for i, row in enumerate(steps)],
                    'execution_mode': 'feedback_gated_confirmation', 'simulation_only': True,
                    'dispatch_allowed': False, 'catalog_version': self._catalog_version(),
                    'evidence': deepcopy(evidence if evidence is not None else [])}
            session.plans[identifier] = plan
            self.preview_plan_step(session_id, identifier, 1, expected_version=expected_version)
            return self.plan_snapshot(session_id, identifier)

    def _plan(self, session, plan_id):
        if type(plan_id) is not str or plan_id not in session.plans:
            raise KeyError('顺序计划不存在或不属于此模拟会话')
        return session.plans[plan_id]

    def plan_snapshot(self, session_id, plan_id):
        with self._lock:
            plan = deepcopy(self._plan(self._session(session_id), plan_id))
            plan.pop('catalog_version', None)
            plan.pop('evidence', None)
            return plan

    def preview_plan_step(self, session_id, plan_id, step, *, expected_version):
        with self._lock:
            session = self._session(session_id)
            plan = self._plan(session, plan_id)
            if type(step) is not int or not 1 <= step <= len(plan['steps']):
                raise ValueError('步骤须为计划中的正整数')
            row = plan['steps'][step - 1]
            blocked = lambda reason: self._blocked_preview(session, row['device_id'], reason)
            if session.version != plan['expected_version'] or plan['catalog_version'] != self._catalog_version():
                plan.update(status='stopped', stop_reason='状态版本或配置版本已变化，请重新分析')
                return blocked(plan['stop_reason'])
            if type(expected_version) is not int or expected_version != plan['expected_version']:
                return blocked('状态版本不符，请读取最新计划与设备状态')
            if plan['status'] != 'active' or step != plan['next_step']:
                return blocked('顺序计划未开放此步骤；前一步须有成功执行及成功反馈，失败后停止')
            if step > 1:
                previous = plan['steps'][step - 2]['execution'] or {}
                if (previous.get('status') != 'succeeded' or previous.get('feedback', {}).get('status') != 'succeeded'
                        or previous.get('after', {}).get('version') != session.version):
                    return blocked('前一步尚无成功执行反馈或最新状态版本')
            if row['preview'] is not None:
                return deepcopy(row['preview'])
            preview = self.preview(session_id, row['device_id'], row['action'], row.get('parameters', {}),
                                   conditions=row.get('conditions', []), expected_version=expected_version,
                                   evidence=plan['evidence'])
            preview.update(plan_id=plan_id, plan_step=step)
            row['preview'] = deepcopy(preview)
            if preview['status'] == 'generated':
                session.commands[preview['command_id']].update(plan_id=plan_id, plan_step=step)
            else:
                plan.update(status='stopped', stop_reason=preview['explanation'])
            return deepcopy(preview)

    def _complete_plan_step(self, session, command, result):
        plan = session.plans.get(command.get('plan_id'))
        if plan is None:
            return
        plan['steps'][command['plan_step'] - 1]['execution'] = deepcopy(result)
        if result['status'] == 'succeeded' and (result.get('feedback') or {}).get('status') == 'succeeded':
            plan['expected_version'] = session.version
            plan['next_step'] += 1
            if plan['next_step'] > len(plan['steps']):
                plan['status'] = 'completed'
        else:
            plan.update(status='stopped', stop_reason=result['explanation'])

    def set_condition(self, session_id, condition, *, scenario_id=None):
        with self._lock:
            session = self._session(session_id)
            conditions = deepcopy(session.scenario_conditions)
            if scenario_id is not None and scenario_id != session.scenario_id:
                if scenario_id not in session.scenario.get('business_scenarios', []):
                    raise ValueError('当前会话不支持该业务场景')
                profile = self.catalog.scenarios[scenario_id]
                selected = {key: session.profiles[key] for key in profile['device_ids']}
                seed = self._seed(replace(session, profiles=selected, scenario=profile), condition)
                devices = deepcopy(session.devices)
                devices.update(seed)
                conditions[scenario_id] = condition
                next_condition = session.condition
            else:
                devices = self._seed(session, condition)
                conditions = {name: 'normal' for name in conditions}
                next_condition = condition
            before = self._snapshot(session)
            result = self._snapshot(replace(session, devices=devices, condition=next_condition,
                                            scenario_conditions=conditions, version=session.version + 1))
            self._record(session, {'status': 'condition_changed', 'condition': condition,
                                   'before': before, 'after': result})
            session.devices = devices
            session.condition = next_condition
            session.scenario_conditions = conditions
            session.version += 1
            return result

    def reset(self, session_id):
        with self._lock:
            session = self._session(session_id)
            before = self._snapshot(session)
            devices = self._seed(session, session.condition)
            conditions = {name: 'normal' for name in session.scenario_conditions}
            result = self._snapshot(replace(session, devices=devices, scenario_conditions=conditions,
                                            version=session.version + 1))
            self._record(session, {'status': 'reset', 'before': before, 'after': result})
            session.devices = devices
            session.scenario_conditions = conditions
            session.version += 1
            return result

    def events(self, session_id):
        with self._lock:
            if isinstance(session_id, str) and session_id in self._sessions:
                return deepcopy(self._sessions[session_id].events)
            # Retain read-only history after restart without recreating sessions
            # or replaying any command/state from disk.
            if isinstance(session_id, str) and self._event_path is not None and self._event_path.is_file():
                history = []
                with self._event_path.open(encoding='utf-8') as handle:
                    for line in handle:
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue  # A partial log tail is not an executed event.
                        if isinstance(event, dict) and event.get('session_id') == session_id:
                            history.append(event)
                if history:
                    return history
            raise KeyError('未知模拟会话或没有可查看的历史事件')

    def _session(self, session_id):
        if not isinstance(session_id, str) or session_id not in self._sessions:
            raise KeyError('未知模拟会话')
        return self._sessions[session_id]

    def _catalog_version(self):
        content = json.dumps({'devices': self.catalog.devices, 'scenarios': self.catalog.scenarios},
                             ensure_ascii=False, sort_keys=True, allow_nan=False)
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    def _seed(self, session, condition):
        conditions = session.scenario.get('conditions', {'normal': {}})
        if not isinstance(condition, str) or condition not in conditions:
            raise ValueError('未知模拟工况')
        result = {}
        for key, profile in session.profiles.items():
            entry = {name: deepcopy(profile.get(name, {})) for name in ('runtime_facts', 'points', 'actions')}
            entry.update({name: profile.get(name, '') for name in ('device_id', 'display_name', 'device_type', 'protocol')})
            entry['display_name'] = entry['display_name'] or key
            entry['state'] = deepcopy(profile.get('initial_state', {}))
            for section in ('state', 'runtime_facts'):
                entry[section].update(deepcopy(conditions[condition].get(key, {}).get(section, {})))
            result[key] = entry
        return result

    def _snapshot(self, session):
        devices = deepcopy(session.devices)
        for entry in devices.values():
            for point in entry['points'].values():
                if isinstance(point, dict) and point.get('field'):
                    value = _read(entry, point['field'])
                    if value is not _MISSING:
                        point['value'] = deepcopy(value)
        result = {'session_id': session.session_id, 'version': session.version,
                'scenario_id': session.scenario_id, 'condition': session.condition,
                'devices': list(devices.values()), 'simulation_only': True, 'dispatch_allowed': False}
        if session.scenario_conditions:
            result['scenario_conditions'] = deepcopy(session.scenario_conditions)
        return result

    def _blocked_preview(self, session, device_id, explanation):
        candidate = asdict(CandidateInstruction(target=device_id if isinstance(device_id, str) else '', dispatch_allowed=False))
        return {'status': 'blocked', 'command_id': None, 'expected_version': session.version,
                'candidate': candidate, 'explanation': explanation, 'expected_changes': {},
                'relation_checks': [], 'simulation_only': True, 'dispatch_allowed': False,
                'simulation_execution_allowed': False}

    @staticmethod
    def _attach_evidence(result, evidence):
        result['candidate']['evidence'] = deepcopy(evidence)
        result['analysis_evidence'] = deepcopy(evidence)

    def _prepare(self, session, device_id, action, parameters):
        result = self._blocked_preview(session, device_id, '')
        profile = session.profiles.get(device_id) if isinstance(device_id, str) else None
        template = profile.get('actions', {}).get(action) if profile and isinstance(action, str) else None
        if template is None:
            result['explanation'] = '设备不在会话中或设备不支持此动作'
            return result
        if parameters is not None and not isinstance(parameters, dict):
            result['explanation'] = '动作参数必须是字段字典'
            return result
        parameters = parameters if parameters is not None else {}
        try:
            # Integer requirements belong to the template, not to an incidental
            # initial value such as 0 in an otherwise fractional measurement.
            if (template.get('parameter_type') == 'integer'
                    and type(parameters.get(template.get('parameter'))) is not int):
                raise ValueError('整数动作参数必须是整数，不能是布尔值或小数')
            service = deepcopy(self._service)
            service.devices = session.profiles
            service.states = {key: deepcopy(entry['state']) for key, entry in session.devices.items()}
            entry = session.devices[device_id]
            facts = {**entry['state'], **entry['runtime_facts']}
            generated = service.generate(device_id, action, facts, parameters,
                                         scenario=profile.get('business_scenario') or profile.get('scenario'))
            result['candidate'] = asdict(generated)
            result['relation_checks'] = self._relations(session, device_id, template)
            if not generated.payload:
                result['explanation'] = generated.explanation or '动作前置条件或协议编码未通过'
                return result
            unsatisfied = [check for check in result['relation_checks'] if check['status'] != 'pass']
            if unsatisfied:
                result['explanation'] = '；'.join(check['explanation'] for check in unsatisfied)
                return result
            staged = deepcopy(session.devices)
            changes = self._effects(staged[device_id], template, parameters)
            self._feedback(staged[device_id], template, generated.payload, validate_only=True)
            result.update(status='generated', expected_changes={device_id: changes},
                          explanation='模拟条件通过；等待明确模拟下发', simulation_execution_allowed=True)
        except (ValueError, TypeError, KeyError, OverflowError) as error:
            result['explanation'] = f'模拟配置或参数校验失败：{error}'
        return result

    def _relations(self, session, device_id, template):
        requirements = template.get('relation_requirements', [])
        if not requirements:
            return []
        groups = [group for group in session.scenario.get('groups', {}).values()
                  if isinstance(group, dict) and device_id in group.values()]
        group = groups[0] if len(groups) == 1 else {}
        checks = []
        for requirement in requirements:
            role, path = requirement.get('role'), requirement.get('field')
            related_id = group.get(role)
            actual = _read(session.devices.get(related_id, {}), path)
            wanted, op = requirement.get('value'), requirement.get('operator', '==')
            status = 'uncertain'
            explanation = f'缺少关联{role}的{path}事实，无法确认模拟联锁'
            if actual is not _MISSING:
                valid = (op in _COMPARISONS and actual is not None and wanted is not None
                         and not isinstance(actual, (dict, list)) and not isinstance(wanted, (dict, list))
                         and (not isinstance(actual, float) or math.isfinite(actual))
                         and (not isinstance(wanted, float) or math.isfinite(wanted))
                         and isinstance(actual, bool) == isinstance(wanted, bool))
                if op in ('<', '<=', '>', '>='):
                    valid = valid and _number(actual) and _number(wanted)
                if valid:
                    try:
                        status = 'pass' if _COMPARISONS[op](actual, wanted) else 'fail'
                    except TypeError:
                        pass
                explanation = (f'模拟联锁{role}.{path}：当前{actual!r}，要求{op} {wanted!r}'
                               if status != 'uncertain' else f'关联{role}.{path}事实类型无效')
            checks.append({**deepcopy(requirement), 'device_id': related_id,
                           'actual': None if actual is _MISSING else deepcopy(actual),
                           'status': status, 'explanation': explanation})
        return checks

    def _effects(self, entry, template, parameters):
        effects = template.get('simulation_effects')
        if not isinstance(effects, dict) or not effects:
            raise ValueError('动作缺少明确的模拟状态效果')
        changed = {}
        for section, updates in effects.items():
            if section not in ('state', 'runtime_facts') or not isinstance(updates, dict):
                raise ValueError('仅允许声明state/runtime_facts模拟效果')
            changed[section] = {}
            for key, expression in updates.items():
                if isinstance(expression, dict):
                    if set(expression) == {'from_parameter'}:
                        if expression['from_parameter'] not in parameters:
                            raise ValueError('模拟效果缺少动作参数')
                        value = parameters[expression['from_parameter']]
                    elif set(expression) == {'increment'}:
                        current, increment = entry[section].get(key), expression['increment']
                        if not _number(current) or not _number(increment):
                            raise ValueError('增量效果需要有效数值')
                        value = current + increment
                    else:
                        raise ValueError('不支持的模拟效果表达式')
                else:
                    value = expression
                if not isinstance(value, (str, bool, int, float)) or (isinstance(value, float) and not math.isfinite(value)):
                    raise ValueError('模拟效果必须是有限数值、布尔值或字符串')
                if entry[section].get(key, _MISSING) != value or type(entry[section].get(key)) is not type(value):
                    changed[section][key] = deepcopy(value)
                entry[section][key] = deepcopy(value)
        return changed

    def _feedback(self, entry, template, payload, validate_only=False):
        mapping = template.get('feedback_mapping')
        if not isinstance(mapping, dict) or not mapping.get('field'):
            raise ValueError('缺少独立的模拟反馈点')
        value = _read(entry, mapping['field'])
        if value is _MISSING:
            raise ValueError('模拟反馈字段缺失')
        protocol = entry['protocol']
        if mapping.get('protocol', protocol) != protocol:
            raise ValueError('反馈点协议与设备不一致')
        encoded = mapping.get('value_encoding', {}).get(str(value), value)
        if protocol == 'IEC61850':
            if not mapping.get('object_reference') or mapping['object_reference'] == payload.get('object_reference'):
                raise ValueError('命令点与反馈点必须分离')
        elif protocol == 'Modbus':
            slave, address = mapping.get('slave_id'), mapping.get('address')
            if (type(slave) is not int or not 1 <= slave <= 247 or type(address) is not int or not 0 <= address <= 65535
                    or (slave, address) == (payload.get('slave_id'), payload.get('address'))):
                raise ValueError('反馈Modbus点位无效或与命令点相同')
            if mapping.get('data_type') == 'bool':
                if type(encoded) is not bool:
                    raise ValueError('布尔反馈不能使用数值替代')
            elif mapping.get('data_type') == 'uint16':
                scale = mapping.get('scale', 1)
                if not _number(encoded) or not _number(scale) or scale <= 0:
                    raise ValueError('反馈倍率或类型无效')
                raw = encoded * scale
                if not math.isfinite(raw) or not 0 <= raw <= 65535 or not math.isclose(raw, round(raw), abs_tol=1e-8, rel_tol=0):
                    raise ValueError('反馈值无法无损编码为uint16')
                encoded = round(raw)
            else:
                raise ValueError('不支持的Modbus反馈类型')
        failed = not validate_only and entry['runtime_facts'].get('feedback_failure', False) is True
        return {'status': 'failed' if failed else 'succeeded', 'simulation_only': True,
                'point': deepcopy(mapping), 'value': deepcopy(value), 'encoded_value': encoded,
                'explanation': '测试预设的反馈失败；状态未提交' if failed else '内存模拟反馈确认，非现场回执'}

    def _apply(self, session, command_id, command, refreshed):
        before = self._snapshot(session)
        staged = deepcopy(session.devices)
        identifier, action = command['device_id'], command['action']
        template = session.profiles[identifier]['actions'][action]
        self._effects(staged[identifier], template, command['parameters'])
        feedback = self._feedback(staged[identifier], template, refreshed['candidate']['payload'])
        status = feedback['status'] if feedback.get('status') in ('succeeded', 'failed', 'unknown') else 'unknown'
        result = {'status': status, 'command_id': command_id, 'target': identifier, 'action': action,
                  'template_ref': template.get('template_ref'), 'candidate': refreshed['candidate'],
                  'analysis_evidence': refreshed['analysis_evidence'],
                  'conditions': deepcopy(command['conditions']),
                  'condition_checks': deepcopy(refreshed.get('condition_checks', [])),
                  'relation_checks': refreshed['relation_checks'], 'before': before, 'after': before,
                  'feedback': feedback, 'simulation_only': True, 'dispatch_allowed': False,
                  'explanation': feedback['explanation']}
        if status == 'succeeded':
            payload = refreshed['candidate']['payload']
            # Write command values only to command points, never to feedback mappings.
            for point in staged[identifier]['points'].values():
                if not isinstance(point, dict) or point.get('field'):
                    continue
                if ((point.get('object_reference') and point.get('object_reference') == payload.get('object_reference'))
                        or (point.get('slave_id') == payload.get('slave_id') and point.get('address') is not None
                            and point.get('address') == payload.get('address'))):
                    point['value'] = deepcopy(payload.get('engineering_value'))
            result['after'] = self._snapshot(replace(session, devices=staged, version=session.version + 1))
        self._record(session, result)
        if status == 'succeeded':
            session.devices = staged
            session.version += 1
        return result

    def _blocked_execution(self, session, command_id, explanation):
        snapshot = self._snapshot(session)
        return {'status': 'blocked', 'command_id': command_id, 'explanation': explanation,
                'before': snapshot, 'after': deepcopy(snapshot), 'feedback': None,
                'event_id': None, 'simulation_only': True, 'dispatch_allowed': False}

    def _record(self, session, result):
        result['event_id'] = f'event-{uuid4().hex}'
        event = {'session_id': session.session_id, 'timestamp': datetime.now(timezone.utc).isoformat(),
                 **deepcopy(result)}
        if self._event_path is not None:
            self._event_path.parent.mkdir(parents=True, exist_ok=True)
            with self._event_path.open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + '\n')
        session.events.append(event)
