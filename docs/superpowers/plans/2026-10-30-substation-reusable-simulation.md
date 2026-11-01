# Substation Reusable Simulation Implementation Plan

> 归档说明（2026-11-01）：以下是2026-10-30实施计划及当时的本地授权范围，保留作开发记录。用户后续要求保持原界面，并已授权功能和详细文档一起发布。当前使用以 [本次更新说明](../../本次更新说明_20261101.md) 为准，原计划中的独立工作台已撤下。

> **For agentic workers:** Use test-driven development for every behavior change; root integrates and runs the complete regression suite. User approved the design and local implementation; do not upload or commit existing local work.

**Goal:** Deliver reusable device/action templates and a local substation simulation with explicit execution and feedback.

**Architecture:** Keep the existing generator pure. A catalog adapts legacy profiles and adds six devices, independent templates and a 14-device scenario. A separate runtime owns isolated sessions, previews, atomic simulated execution and feedback. Query handling reads runtime snapshots independently of standard/action bindings.

**Tech Stack:** Existing Python/FastAPI, JSON and HTML/JavaScript; no new dependencies or real communication.

**Spec:** `docs/superpowers/specs/2026-10-30-substation-reusable-simulation-design.md` (approved 2026-10-30).

## Global Constraints

- Preserve all existing 19 device IDs, 47 actions and 34 examples, including uncommitted feeder additions.
- Device/action templates have no required scenario or source-clause key; instance point mapping remains separate.
- Queries/previews do not execute. Only explicit simulation execution updates simulated state. Real dispatch stays disabled.
- Seven device types and 14 scenario devices; add six devices, at least 25 total; provide four initial conditions.
- New and old clauses remain jointly searchable without bulk modifying their rule fields.
- Work in current local directory, preserve prior modifications, no upload or automatic commits. This follows the user's confirmed local implementation scope.

## Review Focus

1. A valid unbound fan action must execute in different scenario sessions using the same template.
2. Missing relations, stale previews, duplicate execution and feedback failure must not produce partial state changes.
3. General and multi-device questions must return available facts without fixed clause bindings or automatic execution.
4. Commands and feedback points must be distinct; preserve boolean/numeric types, units and encoding ranges.
5. Legacy template editing/generation and all existing configurations must still work.

## Shared Interfaces

`instruction_engine/simulation_catalog.py`: `SimulationCatalog()` exposes `devices` (expanded compatibility profiles indexed by device_id), `device_templates`, `action_templates`, `scenarios` (dict indexed by scenario_id), `describe() -> dict`, `make_service() -> SimulationInstructionService`.

Scenarios use `device_ids`, `groups` (role→device_id maps: transformer, breaker, disconnector, earthing_switch, cooling_fan, oil_pump, tap_changer), and `conditions` (condition name→device_id→state/runtime_facts overrides). Four conditions: normal, high_temperature, cooling_fault, maintenance.

Expanded actions retain the existing generator fields and add `template_ref`, `feedback_mapping`, `simulation_effects` (`state`/`runtime_facts` key→literal or `{"from_parameter": name}` or `{"increment": number}`), and optional `relation_requirements` (role, field dotted state/runtime_facts path, operator, value). No arbitrary code/eval. Catalog supplies mapping, feedback and effects for scenario actions; reusable templates don't include concrete device IDs/addresses.

`instruction_engine/simulation_runtime.py`: `SimulationRuntime(catalog=None, event_path=None)` exposes `create_session(scenario_id='substation_maintenance', device_ids=None, condition='normal')`, `snapshot(session_id)`, `preview(session_id, device_id, action, parameters=None)`, `execute(session_id, command_id, expected_version)`, `set_condition(session_id, condition)`, `reset(session_id)`, `events(session_id)`. Results are JSON dictionaries. Snapshot includes session_id, version, scenario_id, condition, devices (device_id/display_name/device_type/protocol/state/runtime_facts/points/actions), simulation_only=true, dispatch_allowed=false. Preview has status generated/blocked, command_id, expected_version, candidate, explanation, expected_changes. Execution has status succeeded/blocked/failed, before/after, feedback, event_id. Execute uses server-owned command; no caller-supplied address or payload.

API paths: GET /simulation/catalog, POST /simulation/sessions, GET /simulation/sessions/{session_id}, POST /simulation/sessions/{session_id}/preview, POST /simulation/sessions/{session_id}/execute, POST /simulation/sessions/{session_id}/condition, POST /simulation/sessions/{session_id}/reset, GET /simulation/sessions/{session_id}/events. JSON preview fields device_id/action/parameters; execute command_id/expected_version; condition field condition. Existing endpoints retain pure generation behavior.

## Task 1: Catalog, templates and scenario (catalog agent)

Files: four new `configs/{device_templates,action_templates,device_instances,scenario_profiles}.json`; new catalog module; minimal `simulation.py` and `template_library.py` compatibility changes; `tests/test_simulation_catalog.py`.

- [x] Write and run failing behavior tests for preserved counts, six new devices, 14-device scenario, 4 conditions and cross-scenario action generation.
- [x] Implement independent templates, legacy adapter, concrete logical point mappings and relation/effect declarations.
- [x] Remove scenario equality as a required key in legacy generator and template finder without weakening device/protocol compatibility.
- [x] Run catalog and existing simulation/template generation tests. Record results; do not commit.

## Task 2: Isolated simulation runtime (runtime agent)

Files: new runtime module and focused helpers if needed; `tests/test_simulation_runtime.py`. Consume catalog contract above.

- [x] Write/run failing tests for fan start/stop feedback, independent sessions, stale and duplicate commands, relation gates, failure rollback and reset.
- [x] Implement server-owned previews, locked atomic updates, point/feedback simulation, condition switching and event logging. Keep encoder pure.
- [x] Cover both protocols and numeric tap changes; reject invalid IDs/types/parameters/missing dependencies and old previews after reset.
- [x] Run runtime tests once catalog is available. Record results; do not commit.

## Task 3: Simulation page (frontend agent)

Files: new `frontend/simulation.html`, optional `frontend/simulation.js/css`; add entry links to index and template editor without replacing existing tools.

- [x] Build scenario/condition selection, session state and device capability selection, point details, preview, explicit simulated execution and event result UI against shared API.
- [x] Display actual names/units and per-device supported actions; leave arbitrary JSON in optional details.
- [x] Disable execution for missing/blocked/stale preview and refresh after state/condition changes; show errors plainly.
- [x] Run JavaScript syntax checks and focused browser verification if available. Do not change shared backend files or commit.

## Task 4: Query and API integration (root)

Files: API routes plus separate simulation routes module; new simulation query application module; minimal analysis pipeline/advice integration; template editor catalog integration; tests for APIs and query routing.

- [x] Write/run failing tests for catalog/session APIs and state/capability/multi-device questions without clause/action bindings.
- [x] Lazily initialize runtime on pipeline/session, add validated APIs with clear 422/404 handling.
- [x] Route explicit simulation preview requests and factual device queries separately; retain dynamic original-text standard retrieval and optional source assessment.
- [x] Ensure suggestions don't auto-execute and source-less template simulations don't go through mandatory source binding.
- [x] Expose independent templates in management; preserve legacy custom template editing and pure generator behavior.

## Task 5: Integrated verification and documentation (root + fresh review)

- [x] Run focused catalog/runtime/API/query and existing knowledge/generation regressions.
- [x] Run complete pytest suite with workspace temp paths, report any remaining failures by name.
- [x] Exercise browser session creation, preview, execution, feedback, conditions, reset and queries, including a second template consumer.
- [x] Obtain fresh implementation review, fix substantive findings, rerun affected checks.
- [x] Record how to start/use it and verification results, mark plan items; leave all changes local.
