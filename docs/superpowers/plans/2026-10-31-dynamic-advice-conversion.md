# Dynamic Advice Conversion Implementation Plan

> 归档说明（2026-11-01）：下文记录2026-10-31实施时的“不上传”约束。用户后续已授权功能和详细文档一起发布。当前行为和验证范围见 [本次更新说明](../../本次更新说明_20261101.md) 及 [动态转换文档](../../指令转换取消固定绑定_20261031.md)。

**Goal:** Convert suggestions through shared device templates without predefined clause/template bindings.

**Approved scope:** The user's four-point request: retain clause analysis and dynamic citations; remove fixed-ID/action/condition equality; use the existing simulation preview; retain validation and explicit execution. Preserve the original UI and all local changes; no upload or automatic commit.

**Architecture:** `GroundedAdviceService` reads one runtime snapshot and resolves the target through the catalog. Its model emits device/action/parameters plus retrieved references. Analysis evidence and applicability annotations stay separate from executable template conditions. The same `SimulationRuntime.preview` handles both explicit commands and model advice.

**Tech stack:** Existing Python/FastAPI/JSON and original frontend. No new dependency or external call for verification.

## Contracts

- `SimulationRuntime.preview(..., *, evidence=None, expected_version=None)` preserves old positional callers. Evidence is deep-copied into the saved command and restored when executing/rebuilding candidates and writing events.
- The expected analysis snapshot version is checked under the runtime lock. Stale analysis yields no executable payload or command.
- Evidence records include actual quote, rule/clause IDs, standard/version, source and review/applicability notes; they are not protocol conditions.
- Clause action/condition fields may be empty or natural language; multiple references are allowed. Unknown references remain invalid.
- An explicitly conflicting scenario in evidence is reported and blocked for that advice; uncertain entity/review status is annotated rather than claimed verified.
- Protocol encoding, device/action availability, numeric ranges, interlocks, cancellation, simulation mode and uniqueness remain mandatory.
- Existing `generate_grounded` is removed after all active callers are migrated; no second conversion path retains a binding requirement. Existing source metadata remains unchanged.

## Tasks

- [x] Write/run failing tests for unbound advice, empty/natural clause fields, multiple citations, catalog actions, version changes, evidence retention and original UI two-step integration.
- [x] Extend runtime preview for snapshot version and dynamic evidence; prove unchanged direct-preview behavior.
- [x] Refactor advice context/target handling and replace fixed-binding generation with runtime preview, preserving diagnostics and response compatibility.
- [x] Update old tests that intentionally required binding; retain negative tests for malformed output, false citations, unsupported targets/actions, parameters, interlocks, source conflicts and no execution.
- [x] Remove the unused legacy source-bound generator and update wording; leave templates/standards/UI layout unchanged.
- [x] Run focused and full regressions, obtain independent review, verify original UI behavior and document actual results.

## Review Focus

- An action proposal must use the same session snapshot that its model saw.
- Dynamic evidence must survive preview return edits and execution reconstruction.
- Conditions are evaluated from trusted template/device facts, not model-authored expressions or raw clause fragments.
- No model text or citation ID can supply protocol addresses, make a real target, or invoke execute.
- Failure/model errors must clear both old candidate payloads and old previews.
