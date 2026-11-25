"""Declared scenario help survives expansion of its actual device instances."""
import json
import shutil
import pytest

from standard_knowledge_service_v2.instruction_engine.simulation_catalog import CONFIG_ROOT, SimulationCatalog


def test_business_profile_preserves_declared_examples_without_copying_instances(tmp_path):
    root = tmp_path / 'configs'
    shutil.copytree(CONFIG_ROOT, root)
    path = root / 'scenario_profiles.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    data['scenario_profiles'] = [row for row in data['scenario_profiles']
                                 if row['scenario_id'] != 'renewable_grid_integration']
    examples = ['新能源设备的示例问法，仅用于输入提示']
    data['scenario_profiles'].append(dict(scenario_id='renewable_grid_integration',
        display_name='新能源并网', description='逆变器与储能设备的说明', question_examples=examples,
        device_ids=[], groups={}, conditions={'normal': {}}, condition_labels={'normal': '正常运行'}))
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    catalog = SimulationCatalog(config_dir=root)
    scene = catalog.scenarios['renewable_grid_integration']
    assert scene['question_examples'] == examples
    assert scene['description'] == '逆变器与储能设备的说明'
    assert set(scene['device_ids']) == {'SIM-MB-INVERTER-01', 'SIM-IEC-INVERTER-01',
                                        'SIM-MB-BESS-01', 'SIM-IEC-BESS-01'}
    aggregate = catalog.scenarios['all_devices']['device_ids']
    assert all(aggregate.count(key) == 1 for key in scene['device_ids'])


@pytest.mark.parametrize('protocol', ['IEC', 'MB'])
def test_bess_stopping_clears_simulated_output_after_discharge(protocol):
    from standard_knowledge_service_v2.instruction_engine.simulation_runtime import SimulationRuntime
    runtime = SimulationRuntime()
    session = runtime.create_session('renewable_grid_integration')
    identifier = f'SIM-{protocol}-BESS-01'
    for action, parameters in [('start', {}), ('adjust_active_power', {'power_kw': 180}), ('stop', {})]:
        preview = runtime.preview(session['session_id'], identifier, action, parameters)
        assert preview['status'] == 'generated'
        result = runtime.execute(session['session_id'], preview['command_id'], preview['expected_version'])
        assert result['status'] == 'succeeded'
    device = next(d for d in runtime.snapshot(session['session_id'])['devices'] if d['device_id'] == identifier)
    assert device['state']['running'] is False
    assert device['state']['active_power_kw'] == 0
