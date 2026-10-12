"""Browser check for the source-bound question selector; never confirms control."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    output = Path(__file__).resolve().parents[1] / "artifacts/knowledge_graph/current"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            errors = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto("http://127.0.0.1:5500/", wait_until="networkidle")
            page.wait_for_function("document.querySelector('#graph-question').options.length > 1")
            catalog = page.request.get("http://127.0.0.1:8000/knowledge/questions").json()
            before = page.request.get("http://127.0.0.1:8000/simulation/state").json()
            results = []
            for index, case in enumerate(catalog["cases"]):
                page.locator("#graph-question").select_option(str(index))
                assert page.locator("#query").input_value() == case["query"]
                assert page.locator("#simulation-mode").is_checked() == case["parameters"]["simulation_mode"]
                with page.expect_response(lambda r: r.url.endswith("/analyze") and r.request.method == "POST", timeout=90000) as pending:
                    page.locator("#run").click()
                response = pending.value.json()
                page.wait_for_function("!document.querySelector('#run').disabled")
                assert response["status"] == case["expected_status"]
                assert page.locator("#output").inner_text().strip()
                assert page.locator("#confirm-command").count() == 0
                assert not (response["data"].get("candidate_instruction") or {}).get("payload")
                if case.get("expected_term"):
                    assert case["expected_term"] in page.locator("#output").inner_text()
                page.locator('[data-tab="matching"]').click()
                if case.get("expected_clause_id"):
                    assert "本地图谱溯源" in page.locator("#output").inner_text()
                if index == 0:
                    page.screenshot(path=str(output / "question_ui.png"), full_page=True)
                results.append({"case_id": case["case_id"], "status": response["status"], "passed": True})
                print(case["case_id"], "UI PASS", flush=True)
            assert before == page.request.get("http://127.0.0.1:8000/simulation/state").json()
            page.locator("#graph-question").select_option("0")
            page.locator("#query").fill("空气压缩机能效等级分几级？")
            assert page.locator("#graph-question").input_value() == ""
            edited = json.loads(page.locator("#params").input_value())
            assert "standard_id" not in edited and "chapter_path" not in edited
            assert not errors, errors
            (output / "ui_verification.json").write_text(json.dumps({"passed": True,
                "browser_errors": errors, "state_unchanged": True,
                "editing_question_clears_source_binding": True, "cases": results}, ensure_ascii=False, indent=2), encoding="utf-8")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
