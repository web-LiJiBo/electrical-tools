"""Keep the main model API contract while restoring complete device previews."""
import hashlib
import re
from pathlib import Path

import pytest

from standard_knowledge_service_v2.contracts import AnalysisRequest
from test_api_first_analysis import app_for


@pytest.mark.parametrize("query", [
    "启动SIM-IEC-FAN-01和冷却风机2",
    "启动主变1和主变2的冷却风机",
])
def test_main_api_understanding_preserves_every_batch_target(monkeypatch, query):
    app, parameters, before, calls = app_for(monkeypatch, intent="instruction", actions=["start"])
    response = app.analyze(AnalysisRequest(query, parameters=parameters))

    assert response.status == "generated"
    assert response.data["decomposition"]["source"] == "model_api"
    assert {device["device_id"] for device in response.data["devices"]} == {
        "SIM-IEC-FAN-01", "SIM-MB-FAN-01",
    }
    batch = response.data.get("simulation_batch")
    assert batch is not None, "A multi-device request must expose every preview"
    assert {row["device_id"] for row in batch["items"]} == {
        "SIM-IEC-FAN-01", "SIM-MB-FAN-01",
    }
    assert batch["generated_count"] == 2
    assert response.data["candidate_instruction"] is None
    assert len(calls) == 1
    assert app.simulation_runtime.snapshot(before["session_id"]) == before


def test_simulation_script_url_changes_with_the_published_asset():
    root = Path(__file__).resolve().parents[1]
    script = (root / "frontend/original-simulation.js").read_text(encoding="utf-8").encode("utf-8")
    html = (root / "frontend/index.html").read_text(encoding="utf-8")
    version = re.search(r'<script src="original-simulation\.js\?v=([^"]+)"', html)
    assert version is not None
    assert version.group(1) == hashlib.sha256(script).hexdigest()[:12], (
        "The script URL must identify the current asset so cached scripts cannot break the new page"
    )
