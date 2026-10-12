import json
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from unittest.mock import patch

import pytest

from test_grounded_advice import Client, setup
from standard_knowledge_service_v2.application.grounded_advice import GroundedAdviceService
from standard_knowledge_service_v2.application.analysis_pipeline import AnalysisPipeline
from standard_knowledge_service_v2.decomposition import RawTextFallback, DeepSeekConfig, DeepSeekDecomposer
from standard_knowledge_service_v2.decomposition.check_remote import check_remote
from standard_knowledge_service_v2.decomposition.model_errors import ModelCallError, model_error_code


@pytest.mark.parametrize('error,code', [
    (URLError(PermissionError(13, 'private-secret')), 'network_permission_denied'),
    (URLError('[WinError 10013] private-secret'), 'network_permission_denied'),
    (OSError(10013, 'private-secret'), 'network_permission_denied'),
    (URLError(TimeoutError('private-secret')), 'network_timeout'),
    (URLError('private-secret'), 'network_error'),
    (HTTPError('https://example.test', 401, 'private-secret', {}, None), 'authentication_failed'),
    (HTTPError('https://example.test', 429, 'private-secret', {}, None), 'rate_limited'),
    (HTTPError('https://example.test', 503, 'private-secret', {}, None), 'provider_unavailable'),
    (RuntimeError('private-secret'), 'model_error'),
])
def test_error_codes_do_not_expose_exception_text(error, code):
    assert model_error_code(error) == code
    assert 'private-secret' not in str(ModelCallError(code))
    assert 'private-secret' not in DeepSeekDecomposer()._safe_error(error)


class FailingClient:
    def complete(self, *args):
        raise URLError(PermissionError(13, 'private-secret'))


def test_model_failure_records_reason_and_clears_old_candidate():
    pipeline, data, _, request = setup()
    data['candidate_instruction'] = {'payload': {'unsafe_old': True}}
    before = pipeline.simulation_session.snapshot()
    GroundedAdviceService(FailingClient()).enrich(pipeline, request, data)
    assert data['advice']['error_code'] == 'network_permission_denied'
    assert data['candidate_instruction']['payload'] == {}
    assert 'private-secret' not in json.dumps(data)
    assert before == pipeline.simulation_session.snapshot()


def responding_pipeline(client):
    base, data, proposal, request = setup()
    pipeline = AnalysisPipeline(base.retriever, decomposer=RawTextFallback())
    pipeline.simulation_session = base.simulation_session
    pipeline.advisor = GroundedAdviceService(client)
    data['intent_classification'] = {'intent': 'search'}
    return pipeline, data, proposal, request


def test_query_failure_not_presented_as_completed_generation():
    pipeline, data, _, request = responding_pipeline(FailingClient())
    response = pipeline._respond(request, 'answered', data, [], [])
    assert response.status == 'partial'
    assert response.data['processing']['source_result_status'] == 'answered'
    assert response.data['processing']['instruction_status'] == 'unavailable'
    assert 'WinError 10013' in response.data['processing']['instruction_reason']
    assert response.warnings


def test_query_can_produce_instruction_without_changing_initial_intent():
    _, _, proposal, _ = setup()
    pipeline, data, _, request = responding_pipeline(Client(proposal))
    before = pipeline.simulation_session.snapshot()
    response = pipeline._respond(request, 'answered', data, [], [])
    assert response.status == 'generated'
    assert response.data['processing']['query_intent'] == 'search'
    assert response.data['processing']['instruction_status'] == 'generated'
    assert response.data['candidate_instruction']['payload']
    assert before == pipeline.simulation_session.snapshot()


def test_empty_model_proposal_never_retains_old_generated_status():
    _, _, proposal, _ = setup()
    proposal['instruction'] = None
    pipeline, data, _, request = responding_pipeline(Client(proposal))
    data['candidate_instruction'] = {'payload': {'old': True}}
    response = pipeline._respond(request, 'generated', data, [], [])
    assert response.status != 'generated'
    assert response.data['processing']['instruction_status'] == 'not_proposed'
    assert not response.data['candidate_instruction']['payload']


def test_invalid_model_output_distinguished_from_transport_failure():
    pipeline, data, _, request = responding_pipeline(Client({'bad': 'private-secret'}))
    response = pipeline._respond(request, 'answered', data, [], [])
    assert response.status == 'partial'
    assert response.data['advice']['error_code'] == 'invalid_model_output'
    assert 'private-secret' not in json.dumps(response.to_dict())


class Response:
    def __init__(self, payload):
        self.payload = payload
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return json.dumps(self.payload).encode()


def remote_config():
    return SimpleNamespace(backend='deepseek_api', api_base='https://example.test',
                           api_key_env='TEST_PREFLIGHT_KEY', timeout_seconds=1, remote_model='deepseek-chat')


def test_preflight_missing_key_never_opens_network(monkeypatch):
    monkeypatch.delenv('TEST_PREFLIGHT_KEY', raising=False)
    with patch('standard_knowledge_service_v2.decomposition.check_remote.urlopen') as call:
        assert check_remote(remote_config())['error_code'] == 'missing_api_key'
        call.assert_not_called()


def test_preflight_gets_models_not_generating_text(monkeypatch):
    monkeypatch.setenv('TEST_PREFLIGHT_KEY', 'private-secret')
    with patch('standard_knowledge_service_v2.decomposition.check_remote.urlopen', return_value=Response({'data': [{'id': 'deepseek-chat'}]})) as call:
        result = check_remote(remote_config())
    assert result['status'] == 'reachable'
    request = call.call_args.args[0]
    assert request.get_method() == 'GET'
    assert request.full_url == 'https://example.test/models'
    assert request.data is None
    assert 'private-secret' not in json.dumps(result)


def test_preflight_does_not_reject_unlisted_alias_or_change_config(monkeypatch):
    monkeypatch.setenv('TEST_PREFLIGHT_KEY', 'private-secret')
    config = remote_config()
    with patch('standard_knowledge_service_v2.decomposition.check_remote.urlopen', return_value=Response({'data': [{'id': 'other-model'}]})):
        result = check_remote(config)
    assert result['status'] == 'reachable'
    assert result['configured_model_listed'] is False
    assert config.remote_model == 'deepseek-chat'


def test_preflight_permissions_are_reported_without_secret(monkeypatch):
    monkeypatch.setenv('TEST_PREFLIGHT_KEY', 'private-secret')
    with patch('standard_knowledge_service_v2.decomposition.check_remote.urlopen', side_effect=URLError(PermissionError(13, 'private-secret'))):
        result = check_remote(remote_config())
    assert result['status'] == 'unavailable'
    assert result['error_code'] == 'network_permission_denied'
    assert 'private-secret' not in json.dumps(result)


def test_transport_invalid_response_is_classified(monkeypatch):
    monkeypatch.setenv('TEST_TRANSPORT_KEY', 'private-secret')
    with patch('standard_knowledge_service_v2.decomposition.deepseek_decomposer.urlopen', return_value=Response({'unexpected': 'private-secret'})):
        with pytest.raises(ModelCallError, match='返回结构') as caught:
            DeepSeekDecomposer(DeepSeekConfig(api_key_env='TEST_TRANSPORT_KEY')).complete('system', 'question')
    assert caught.value.code == 'invalid_response'
    assert 'private-secret' not in str(caught.value)


def test_instruction_endpoint_returns_processing_failure_reason():
    from fastapi import FastAPI
    from standard_knowledge_service_v2.api.routes import register_routes
    pipeline, data, _, request = responding_pipeline(FailingClient())
    response = pipeline._respond(request, 'answered', data, [], [])
    app = FastAPI()
    register_routes(app, SimpleNamespace(facade=SimpleNamespace(analyze=lambda _: response)))
    endpoint = next(route.endpoint for route in app.routes if route.path == '/generate-instruction')
    result = endpoint({'query': request.query})
    assert result['status'] == 'partial'
    assert result['processing']['instruction_status'] == 'unavailable'
    assert result['advice']['error_code'] == 'network_permission_denied'
    assert not result['candidate_instruction']
