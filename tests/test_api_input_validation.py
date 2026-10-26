from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException

from standard_knowledge_service_v2.api.routes import register_routes
from standard_knowledge_service_v2.api.schemas import analysis_request_from_json


@pytest.mark.parametrize(
    "payload,message",
    [
        ([], "JSON对象"),
        ({"query": 123}, "query必须是字符串"),
        ({"query": "问题", "parameters": None}, "parameters必须是JSON对象"),
        ({"query": "问题", "conversation_context": {}}, "conversation_context必须是JSON数组"),
        ({"query": "问题", "conversation_context": [{"role": "user", "content": 1}]}, "content必须是字符串"),
    ],
)
def test_analysis_request_rejects_invalid_json_shapes(payload, message):
    with pytest.raises(ValueError, match=message):
        analysis_request_from_json(payload)


def test_analysis_request_normalizes_valid_input():
    request = analysis_request_from_json({
        "query": "  断路器是否正常  ",
        "scenario_hint": "  电网调度运行  ",
        "parameters": {"device_id": "CB-01"},
        "target_protocol": "IEC61850",
        "conversation_context": [{"role": "user", "content": "上一个问题"}],
    })
    assert request.query == "断路器是否正常"
    assert request.scenario_hint == "电网调度运行"
    assert request.parameters == {"device_id": "CB-01"}


@pytest.mark.parametrize("path", ["/analyze", "/generate-instruction", "/validate", "/generate-report"])
def test_analysis_endpoints_translate_bad_parameters_to_422(path):
    app = FastAPI()
    facade = SimpleNamespace(analyze=lambda request: pytest.fail("格式错误时不应进入业务主流程"))
    register_routes(app, SimpleNamespace(facade=facade, audit_store=None))
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", "") == path)
    with pytest.raises(HTTPException) as exc_info:
        endpoint({"query": "问题", "parameters": None})
    assert exc_info.value.status_code == 422
    assert "parameters必须是JSON对象" in exc_info.value.detail


@pytest.mark.parametrize("path", ["/decompose", "/search"])
def test_query_endpoints_reject_non_string_query(path):
    app = FastAPI()
    facade = SimpleNamespace()
    register_routes(app, SimpleNamespace(facade=facade, audit_store=None))
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", "") == path)
    with pytest.raises(HTTPException) as exc_info:
        endpoint({"query": 123})
    assert exc_info.value.status_code == 422
    assert "query必须是字符串" in exc_info.value.detail
