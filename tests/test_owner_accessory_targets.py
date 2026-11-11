"""An owner mentioned independently must survive accessory target resolution."""
import pytest

from standard_knowledge_service_v2.application.simulation_query import _targets
from standard_knowledge_service_v2.instruction_engine.simulation_catalog import SimulationCatalog


@pytest.mark.parametrize('scene', ['substation_maintenance', 'all_devices'])
@pytest.mark.parametrize('query,expected', [
    ('比较主变1和主变1的冷却风机的当前状态', {'SIM-TRANSFORMER-01', 'SIM-IEC-FAN-01'}),
    ('比较主变1的冷却风机和主变1的状态', {'SIM-TRANSFORMER-01', 'SIM-IEC-FAN-01'}),
    ('比较主变1及其冷却风机的当前状态', {'SIM-TRANSFORMER-01', 'SIM-IEC-FAN-01'}),
    ('比较主变1与其风机的当前状态', {'SIM-TRANSFORMER-01', 'SIM-IEC-FAN-01'}),
    ('比较主变1和它的油泵的状态', {'SIM-TRANSFORMER-01', 'SIM-IEC-PUMP-01'}),
    ('比较主变1和主变2的冷却风机状态', {'SIM-IEC-FAN-01', 'SIM-MB-FAN-01'}),
    ('比较主变1和断路器2的当前状态', {'SIM-TRANSFORMER-01', 'SIM-MB-BREAKER-01'}),
    ('启动主变1的冷却风机', {'SIM-IEC-FAN-01'}),
    ('主变1的冷却风机当前状态', {'SIM-IEC-FAN-01'}),
    ('主变1的油泵当前状态', {'SIM-IEC-PUMP-01'}),
    ('比较主变1及其风机和主变2及其风机的状态',
     {'SIM-TRANSFORMER-01', 'SIM-IEC-FAN-01', 'SIM-TRANSFORMER-02', 'SIM-MB-FAN-01'}),
    ('比较SIM-TRANSFORMER-01及其风机的状态', {'SIM-TRANSFORMER-01', 'SIM-IEC-FAN-01'}),
    ('比较主变1和主变99的风机状态', {'主变99'}),
])
def test_owner_and_accessory_mentions(scene, query, expected):
    catalog = SimulationCatalog()
    profile = catalog.scenarios[scene]
    devices = [catalog.devices[key] for key in profile['device_ids']]
    assert set(_targets(query, {}, devices, profile)) == expected


@pytest.mark.parametrize('scene', ['substation_maintenance', 'all_devices'])
@pytest.mark.parametrize('query', [
    '比较主变1和主变1的冷却风机的当前状态',
    '比较主变1及其冷却风机的当前状态',
    '比较主变1与其风机的当前状态',
])
def test_comparison_returns_both_snapshot_devices_without_preview_or_state_change(scene, query):
    from standard_knowledge_service_v2.application.analysis_pipeline import AnalysisPipeline
    from standard_knowledge_service_v2.contracts import AnalysisRequest
    from standard_knowledge_service_v2.decomposition import RawTextFallback
    from standard_knowledge_service_v2.instruction_engine.simulation_runtime import SimulationRuntime
    from standard_knowledge_service_v2.retrieval_engine import JsonClauseRepository, LocalLunwenRetrievalAdapter

    app = AnalysisPipeline(LocalLunwenRetrievalAdapter(JsonClauseRepository([])), decomposer=RawTextFallback())
    app.simulation_runtime = SimulationRuntime(event_path=None)
    before = app.simulation_runtime.create_session('all_devices')
    result = app.analyze(AnalysisRequest(query, parameters={
        'simulation_mode': True, 'simulation_scenario_id': scene,
        'simulation_session_id': before['session_id']}))
    assert result.status == 'answered'
    expected = {'SIM-TRANSFORMER-01', 'SIM-IEC-FAN-01'}
    assert {d['device_id'] for d in result.data['devices']} == expected
    for device in result.data['devices']:
        source = next(d for d in before['devices'] if d['device_id'] == device['device_id'])
        assert device['state'] == source['state']
        assert device['runtime_facts'] == source['runtime_facts']
        assert device['device_id'] in result.data['answer']['text']
    assert result.data['candidate_instruction'] is None
    assert 'simulation_preview' not in result.data
    assert 'simulation_batch' not in result.data
    assert app.simulation_runtime.snapshot(before['session_id']) == before
