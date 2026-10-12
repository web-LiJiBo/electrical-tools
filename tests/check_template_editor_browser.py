"""Headless UI check with real editor validation and an isolated save file."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
from playwright.sync_api import sync_playwright
from standard_knowledge_service_v2.instruction_engine.simulation import SimulationInstructionService
from standard_knowledge_service_v2.instruction_engine.template_editor import save_custom, test_template

root = Path(__file__).resolve().parents[1]
service = SimulationInstructionService()
with TemporaryDirectory() as temporary, sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1280, 'height': 900})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    def api(route):
        try:
            if route.request.method == 'GET':
                result = {'devices': list(service.devices.values())}
            elif route.request.url.endswith('/test'):
                result = test_template(service, route.request.post_data_json)
            else:
                result = save_custom(service, route.request.post_data_json, Path(temporary) / 'custom.json')
            route.fulfill(status=200, content_type='application/json', headers={'Access-Control-Allow-Origin': '*'}, body=json.dumps(result))
        except ValueError as exc:
            route.fulfill(status=422, content_type='application/json', headers={'Access-Control-Allow-Origin': '*'}, body=json.dumps({'detail': str(exc)}))
    page.route('http://127.0.0.1:8000/**', api)
    page.goto((root / 'frontend/template-editor.html').as_uri())
    page.wait_for_load_state('networkidle')
    assert page.locator('#query-panel').is_visible()
    original_count = sum(len(d['actions']) for d in service.devices.values())
    assert page.locator('#catalog .item').count() == original_count
    page.select_option('#protocol-filter', 'Modbus')
    page.select_option('#device-filter', 'SIM-MB-INVERTER-01')
    page.select_option('#action-filter', 'adjust_reactive_power')
    assert page.locator('#catalog .item').count() == 1
    page.click('#catalog button')
    detail = json.loads(page.locator('#detail-content').inner_text())
    assert detail['有效协议点位']['address'] == 101
    assert detail['动作标识'] == 'adjust_reactive_power'
    page.fill('#keyword', '不存在的模板xyz')
    assert page.locator('#catalog .item').count() == 0
    page.click('#clear-filters')
    assert page.locator('#catalog .item').count() == original_count
    page.select_option('#binding-filter', 'bound')
    assert page.locator('#catalog .item').count() == sum(bool(t.get('source_rule_ids')) for d in service.devices.values() for t in d['actions'].values())
    page.click('#clear-filters')
    page.select_option('#device-filter', 'SIM-MB-BESS-01')
    page.select_option('#action-filter', 'limit_power')
    assert page.locator('#catalog .item').count() == 1
    page.click('#catalog button')
    supplement_detail = json.loads(page.locator('#detail-content').inner_text())
    assert supplement_detail['有效协议点位']['address'] == 411
    assert supplement_detail['参数']['上限'] == 250
    assert not supplement_detail['条款来源']
    page.click('#clear-filters')
    page.click('#add-tab')
    page.select_option('#device', 'SIM-MB-FAN-01')
    page.click('#test')
    page.wait_for_function("document.querySelector('#result').textContent.includes('校验通过')")
    page.click('#save')
    page.wait_for_function("document.querySelector('#result').textContent.includes('已保存')")
    page.click('#save')
    page.wait_for_function("document.querySelector('#result').textContent.includes('已存在')")
    page.fill('#facts', '{"alarm_permission":0}')
    page.click('#test')
    page.wait_for_function("document.querySelector('#result').textContent.includes('阻止生成')")
    page.click('#query-tab')
    assert page.locator('#catalog .item').count() == original_count + 1
    page.select_option('#device-filter', 'SIM-MB-FAN-01')
    page.select_option('#action-filter', 'alarm')
    assert page.locator('#catalog .item').count() == 1
    page.click('#catalog button')
    detail = json.loads(page.locator('#detail-content').inner_text())
    assert detail['来源范围'] == 'user_simulation_template_pending_source_binding'
    page.click('#query-refresh')
    page.wait_for_load_state('networkidle')
    assert page.locator('#catalog .item').count() == 1
    page.set_viewport_size({'width': 390, 'height': 844})
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    page.click('#add-tab')
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    assert not errors, errors
    browser.close()
print('Browser passed: query filters, empty results, source binding, effective mapping detail, save and query, refresh, duplicate rejection, blocked condition, mobile layouts')
