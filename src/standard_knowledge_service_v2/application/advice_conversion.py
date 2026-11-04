"""Separate dynamically cited analysis from trusted device-template conversion."""
from copy import deepcopy
import re

from ..domain import ScenarioContext
from ..validation.applicability_validator import ApplicabilityValidator
from .simulation_access import default_session, simulation_runtime, view_snapshot
from .simulation_query import _targets


def advice_context(pipeline, request, *, entities=()):
    runtime = simulation_runtime(pipeline)
    explicit_session = request.parameters.get('simulation_session_id')
    try:
        snapshot = runtime.snapshot(explicit_session) if explicit_session else default_session(pipeline)
    except (KeyError, ValueError):
        return runtime, None, None, {}, '模拟会话不存在，请重新选择会话'
    snapshot = view_snapshot(pipeline, request, snapshot)
    parameters = dict(request.parameters)
    # Preserve historical names exactly; a feeder breaker must not become a
    # second match for the base device's name.
    if not re.search(r'SIM-[A-Z0-9-]+', request.query, re.I) and not parameters.get('device_id') and not parameters.get('device_ids'):
        legacy = []
        for kind, prefix in [('变压器', 'TRANSFORMER'), ('断路器', 'BREAKER'), ('逆变器', 'INVERTER')]:
            for number in re.findall(r'模拟' + kind + r'(\d+)(?!\d)', request.query):
                if prefix == 'TRANSFORMER':
                    legacy.append(f'SIM-TRANSFORMER-{int(number):02}')
                elif number in ('1', '2'):
                    legacy.append(f'SIM-{"IEC" if number == "1" else "MB"}-{prefix}-01')
                else:
                    legacy.append('SIM-UNREGISTERED-' + number)
        if re.search(r'模拟换流阀1(?!\d)', request.query):
            legacy.append('SIM-IEC-VALVE-01')
        if legacy:
            parameters['device_ids'] = legacy
    devices = [{**runtime.catalog.devices[d['device_id']], **d} for d in snapshot['devices']]
    scenario = runtime.catalog.scenarios.get(snapshot.get('scenario_id'), {})
    try:
        names = [e['name'] for e in entities if isinstance(e, dict) and isinstance(e.get('name'), str)]
        ids = _targets(request.query, parameters, devices, scenario, entity_names=names)
    except ValueError:
        return runtime, snapshot, None, {}, '设备编号格式无效'
    current_ids = {d['device_id'] for d in snapshot['devices']}
    # Legacy callers without a session can still analyze a registered device
    # outside the first scenario. Return the new session so the caller can reuse it.
    if (not explicit_session and not request.parameters.get('simulation_scenario_id')
            and len(ids) == 1 and ids[0] in runtime.catalog.devices and ids[0] not in current_ids):
        snapshot = runtime.create_session(scenario_id=None, device_ids=ids)
        current_ids = set(ids)
    if len(ids) != 1 or ids[0] not in current_ids or re.search(r'真实|实际设备', request.query):
        return runtime, snapshot, None, {}, '设备不唯一、未登记或不属于当前模拟会话'
    profile = runtime.catalog.devices[ids[0]]
    entry = next(d for d in snapshot['devices'] if d['device_id'] == ids[0])
    device = {key: deepcopy(entry.get(key)) for key in
              ('device_id', 'display_name', 'protocol', 'device_type', 'state', 'runtime_facts')}
    return runtime, snapshot, device, profile, ''


def dynamic_evidence(sources, rule_ids, snapshot, profile):
    names = {'breaker': '断路器', 'transformer': '变压器', 'cooling_fan': '冷却风机',
             'oil_pump': '油泵', 'tap_changer': '有载调压装置', 'pole_controller': '极控系统'}
    scenario = snapshot.get('scenario_id') or profile.get('scenario') or 'general'
    if scenario == 'all_devices':
        scenario = profile.get('business_scenario') or profile.get('scenario') or 'general'
    context = ScenarioContext(scenario, names.get(profile['device_type'], profile['device_type']))
    evidence, warnings, conflicts = [], [], []
    validator = ApplicabilityValidator()
    for rid in dict.fromkeys(rule_ids):
        unit, rule = sources[rid]
        status, notes = validator.validate(unit, context)
        scope = unit.metadata.get('scenario', '')
        conflict = bool(scope and scope not in (scenario, 'general'))
        if conflict:
            conflicts.append(f'{rid}的场景范围与当前会话不符')
        review = unit.metadata.get('audit', {}).get('manual_review_required') is True
        if review:
            warnings.append(f'{rid}为待复核来源，本次仅作为模拟建议的分析引用')
        warnings.extend(notes)
        evidence.append({'rule_id': rid, 'standard_id': unit.standard_id, 'version': unit.version,
                         'clause_id': unit.clause_id, 'chapter_path': unit.chapter_path,
                         'quote': rule.content, 'source_uri': unit.source_uri,
                         'support_status': 'pending_review' if review else 'analysis_reference',
                         'manual_review_required': review,
                         'applicability_status': 'fail' if conflict else status.value,
                         'applicability_notes': notes})
    return evidence, list(dict.fromkeys(warnings)), conflicts


def convert_advice(runtime, snapshot, device, profile, instruction, sources):
    evidence, warnings, conflicts = dynamic_evidence(sources, instruction['rule_ids'], snapshot, profile)
    if conflicts:
        return None, evidence, warnings, '；'.join(conflicts)
    preview = runtime.preview(snapshot['session_id'], device['device_id'], instruction['action'],
                              instruction['parameters'], evidence=evidence, expected_version=snapshot['version'])
    return preview, evidence, warnings, ''
