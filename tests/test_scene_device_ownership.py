"""A device has one business owner and one state across business/aggregate views."""
from types import SimpleNamespace
import pytest

from standard_knowledge_service_v2.application.simulation_access import simulation_runtime
from standard_knowledge_service_v2.application.simulation_query import answer_simulation_query
from standard_knowledge_service_v2.contracts import AnalysisRequest
from standard_knowledge_service_v2.instruction_engine.simulation_catalog import SimulationCatalog
from standard_knowledge_service_v2.instruction_engine.simulation_runtime import SimulationRuntime

BUSINESS = ('substation_maintenance', 'grid_fault_isolation',
            'renewable_grid_integration', 'power_grid_operation')


def test_business_devices_have_disjoint_ids_names_and_aggregate_is_exact_union():
    catalog = SimulationCatalog()
    identifiers, names = set(), set()
    for name in BUSINESS:
        profile = catalog.scenarios[name]
        current = set(profile['device_ids'])
        labels = {catalog.devices[key]['display_name'] for key in current}
        assert len(labels) == len(current)
        assert identifiers.isdisjoint(current), name
        assert names.isdisjoint(labels), name
        identifiers.update(current)
        names.update(labels)
    assert set(catalog.scenarios['all_devices']['device_ids']) == identifiers
    assert len(identifiers) == 23
    assert 'offshore_wind' not in catalog.scenarios


def setup_world():
    pipeline = SimpleNamespace()
    runtime = SimulationRuntime()
    pipeline.simulation_runtime = runtime
    snapshot = runtime.create_session(scenario_id='all_devices')
    return pipeline, runtime, snapshot['session_id']


def query(pipeline, sid, scene, text):
    return answer_simulation_query(pipeline, AnalysisRequest(text, parameters={
        'simulation_mode': True, 'simulation_session_id': sid, 'simulation_scenario_id': scene}))


@pytest.mark.parametrize(('scene', 'text', 'status', 'expected_ids'), [
    ('all_devices', '分闸模拟断路器1', 'generated', ['SIM-IEC-BREAKER-01']),
    ('substation_maintenance', '分闸模拟断路器1', 'generated', ['SIM-IEC-BREAKER-01']),
    ('all_devices', '比较模拟断路器1和断路器2的状态', 'answered',
     ['SIM-IEC-BREAKER-01', 'SIM-MB-BREAKER-01']),
])
def test_full_device_name_excludes_nested_foreign_aliases_but_keeps_separate_mentions(
        scene, text, status, expected_ids):
    pipeline, runtime, sid = setup_world()
    before = runtime.snapshot(sid)
    result = query(pipeline, sid, scene, text)
    assert result[0] == status
    assert [d['device_id'] for d in result[1]['devices']] == expected_ids
    if status == 'generated':
        assert result[1]['candidate_instruction']['payload']['scenario'] == 'substation_maintenance'
    assert runtime.snapshot(sid) == before


def test_starting_in_substation_is_visible_in_aggregate_and_preview_does_not_execute():
    pipeline, runtime, sid = setup_world()
    before = runtime.snapshot(sid)
    result = query(pipeline, sid, 'substation_maintenance', '启动主变1的冷却风机')
    assert result[0] == 'generated'
    preview = result[1]['simulation_preview']
    assert runtime.snapshot(sid) == before
    outcome = runtime.execute(sid, preview['command_id'], preview['expected_version'])
    assert outcome['status'] == 'succeeded'
    for scene in ('all_devices', 'substation_maintenance'):
        answer = query(pipeline, sid, scene, 'SIM-IEC-FAN-01现在状态如何？')[1]
        assert answer['devices'][0]['state']['running'] is True
    answer = query(pipeline, sid, 'renewable_grid_integration', 'SIM-IEC-FAN-01现在状态如何？')
    assert answer[0] == 'uncertain'
    assert answer[1]['candidate_instruction'] is None


def test_identically_typed_breakers_from_two_scenes_are_independent_in_one_world():
    pipeline, runtime, sid = setup_world()
    fault_id = next(key for key in runtime.catalog.scenarios['grid_fault_isolation']['device_ids']
                    if 'FEEDER' not in key and runtime.catalog.devices[key]['protocol'] == 'IEC61850')
    assert fault_id != 'SIM-IEC-BREAKER-01'
    preview = runtime.preview(sid, fault_id, 'trip')
    assert preview['status'] == 'generated'
    runtime.execute(sid, preview['command_id'], preview['expected_version'])
    current = {d['device_id']: d for d in runtime.snapshot(sid)['devices']}
    assert current[fault_id]['state']['position'] == 'open'
    assert current['SIM-IEC-BREAKER-01']['state']['position'] == 'closed'


def test_condition_change_only_resets_selected_scene_and_updates_aggregate():
    _, runtime, sid = setup_world()
    inverter = 'SIM-MB-INVERTER-01'
    preview = runtime.preview(sid, inverter, 'adjust_active_power', {'power_kw': 400})
    assert preview['status'] == 'generated'
    runtime.execute(sid, preview['command_id'], preview['expected_version'])
    before = {d['device_id']: d for d in runtime.snapshot(sid)['devices']}
    changed = runtime.set_condition(sid, 'high_temperature', scenario_id='substation_maintenance')
    after = {d['device_id']: d for d in changed['devices']}
    assert after[inverter] == before[inverter]
    assert after['SIM-TRANSFORMER-01']['runtime_facts']['winding_hotspot_rise_k'] == 85
    assert changed['scenario_conditions']['substation_maintenance'] == 'high_temperature'
    pipeline = SimpleNamespace(simulation_runtime=runtime)
    assert query(pipeline, sid, 'all_devices', 'SIM-MB-INVERTER-01现在状态如何？')[1]['devices'][0]['state']['active_power_kw'] == 400


def test_scoped_condition_invalidates_existing_previews_and_other_world_is_isolated():
    _, runtime, sid = setup_world()
    other = runtime.create_session(scenario_id='all_devices')
    preview = runtime.preview(sid, 'SIM-IEC-FAN-01', 'start')
    runtime.set_condition(sid, 'cooling_fault', scenario_id='substation_maintenance')
    assert runtime.execute(sid, preview['command_id'], preview['expected_version'])['status'] == 'blocked'
    assert runtime.snapshot(other['session_id']) == other


def test_invalid_view_does_not_fall_back_to_other_devices():
    pipeline, runtime, sid = setup_world()
    before = runtime.snapshot(sid)
    for scene in ('offshore_wind', 'invented_scene'):
        with pytest.raises(ValueError):
            query(pipeline, sid, scene, '启动主变1的冷却风机')
    with pytest.raises(ValueError):
        runtime.set_condition(sid, 'high_temperature', scenario_id='renewable_grid_integration')
    assert runtime.snapshot(sid) == before


def test_failed_feedback_keeps_the_same_unchanged_state_in_both_views():
    catalog = SimulationCatalog()
    catalog.devices['SIM-IEC-FAN-01']['runtime_facts']['feedback_failure'] = True
    runtime = SimulationRuntime(catalog)
    pipeline = SimpleNamespace(simulation_runtime=runtime)
    before = runtime.create_session(scenario_id='all_devices')
    sid = before['session_id']
    preview = query(pipeline, sid, 'substation_maintenance', '启动主变1的冷却风机')[1]['simulation_preview']
    assert runtime.execute(sid, preview['command_id'], preview['expected_version'])['status'] == 'failed'
    assert runtime.snapshot(sid) == before
    for scene in ('all_devices', 'substation_maintenance'):
        assert query(pipeline, sid, scene, 'SIM-IEC-FAN-01现在状态如何？')[1]['devices'][0]['state']['running'] is False


def test_scoped_condition_event_failure_does_not_commit_shared_state(tmp_path):
    runtime = SimulationRuntime(event_path=tmp_path)
    before = runtime.create_session(scenario_id='all_devices')
    with pytest.raises(OSError):
        runtime.set_condition(before['session_id'], 'high_temperature', scenario_id='substation_maintenance')
    assert runtime.snapshot(before['session_id']) == before
