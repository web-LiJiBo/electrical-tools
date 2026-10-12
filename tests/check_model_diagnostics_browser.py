"""Result-page browser checks with deterministic intercepted API fixtures, no model calls."""
import json
from copy import deepcopy
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    root = Path(__file__).resolve().parents[1]
    response = {'status': 'partial', 'data': {
        'intent_classification': {'intent': 'search'}, 'context': {'scenario': 'power_grid_operation'},
        'answer': {'text': '条款来源回答'}, 'candidate_instruction': None,
        'processing': {'source_result_status': 'answered', 'decomposition_source': 'raw_text_fallback',
            'advice_status': 'unavailable', 'advice_reason_code': 'network_permission_denied',
            'instruction_status': 'unavailable', 'instruction_reason': '模型联网权限被拒绝（WinError 10013）。'},
        'advice': {'status': 'unavailable', 'source': 'not_generated', 'instruction': None,
            'error_code': 'network_permission_denied', 'notice': '模型联网权限被拒绝（WinError 10013）。', 'suggestions': []}}, 'warnings': []}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={'width': 1280, 'height': 900})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            def api(route):
                payload = response if route.request.url.endswith('/analyze') else {'devices': []}
                route.fulfill(status=200, content_type='application/json',
                    headers={'Access-Control-Allow-Origin': '*'}, body=json.dumps(payload))
            page.route('http://127.0.0.1:8000/**', api)
            page.goto((root / 'frontend/index.html').as_uri())
            page.wait_for_load_state('networkidle')
            assert page.locator('#run').is_visible()
            page.fill('#query', '模拟换流阀1目前的功率回降处理是否符合条款？请给出建议。')
            page.click('#run')
            page.wait_for_function("document.querySelector('#status').textContent === '模型建议未完成'")
            assert 'network_permission_denied' in page.locator('#processing-detail').inner_text()
            page.click('[data-tab="instruction"]')
            assert 'WinError 10013' in page.locator('#output').inner_text()
            assert '这是知识查询，不需要生成' not in page.locator('#output').inner_text()
            generated = deepcopy(response)
            generated['status'] = 'generated'
            generated['data']['candidate_instruction'] = {'protocol': 'IEC61850', 'target': 'SIM-IEC-VALVE-01',
                'payload': {'ctlVal': 80}, 'explanation': '只生成功率回降示例', 'missing_fields': []}
            generated['data']['advice'] = {'status': 'generated', 'source': 'llm', 'instruction': None,
                                          'notice': '测试模型建议', 'suggestions': []}
            generated['data']['processing'].update(advice_status='generated', advice_reason_code='',
                instruction_status='generated', instruction_reason='已生成候选协议字段；不下发')
            response = generated
            page.click('#run')
            page.wait_for_function("document.querySelector('#status').textContent === '指令已生成'")
            assert '条款咨询 → 建议指令' in page.locator('#output').inner_text()
            page.click('[data-tab="instruction"]')
            assert '80' in page.locator('#output').inner_text()
            response = deepcopy(generated)
            response['status'] = 'answered'
            response['data']['candidate_instruction'] = None
            response['data']['processing'].update(instruction_status='blocked', instruction_reason='缺少适用动作条款绑定')
            page.click('#run')
            page.wait_for_function("document.querySelector('#status').textContent === '查询完成'")
            page.click('[data-tab="instruction"]')
            assert '缺少适用动作条款绑定' in page.locator('#output').inner_text()
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            assert not errors, errors
            print('browser_checks=passed: model_failure, search_to_instruction, blocked_reason, mobile_layout, no_page_errors; intercepted_API=true')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
