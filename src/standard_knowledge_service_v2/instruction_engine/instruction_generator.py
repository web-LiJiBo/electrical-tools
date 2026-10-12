from __future__ import annotations

from ..domain import ScenarioContext
from .iec61850_adapter import IEC61850Adapter
from .ilr_compiler import ILRCompiler
from .modbus_adapter import ModbusAdapter
from .models import CandidateInstruction, SemanticTuple
from .preconditions import ActionPreconditionEvaluator
from ..hybrid_reasoning.models import ReasoningStatus
from .protocol_adapter import ProtocolRouter
from .template_library import TemplateLibrary


class InstructionGenerationService:
    def __init__(self, templates: TemplateLibrary | None = None, compiler: ILRCompiler | None = None) -> None:
        self.templates = templates or TemplateLibrary()
        self.compiler = compiler or ILRCompiler()
        self.router = ProtocolRouter([IEC61850Adapter(), ModbusAdapter()])
        self.preconditions = ActionPreconditionEvaluator()

    def generate(self, semantic: SemanticTuple, context: ScenarioContext, device_config: dict, target_protocol: str = "", *, facts: dict | None = None) -> CandidateInstruction:
        protocol = target_protocol or str(device_config.get("protocol", "")) or "IEC61850"
        matches = self.templates.find(context.scenario, semantic.action, context.device_type, protocol)
        if not matches:
            return CandidateInstruction(protocol=protocol, evidence=semantic.evidence, missing_fields=["instruction_template"], explanation="未找到场景—动作—协议模板，禁止生成控制帧")
        program = self.compiler.compile(semantic)
        decision = self.preconditions.evaluate(semantic.condition, facts, semantic.constraints)
        trace = decision.to_dict()["trace"]
        if decision.status is not ReasoningStatus.PASS:
            candidate = CandidateInstruction(
                protocol=protocol, target=str(device_config.get("device_id", "")),
                evidence=semantic.evidence,
                explanation="动作前置条件不满足，未生成控制载荷" if decision.status is ReasoningStatus.FAIL else "动作前置条件无法确认，请补充有效业务事实；未生成控制载荷",
                missing_fields=["action_preconditions"] if decision.status is ReasoningStatus.UNCERTAIN else [],
                precondition_status=decision.status.value, precondition_trace=trace,
            )
            # 保留协议缺失项供用户补充，但不调用适配器生成载荷。
            required = {"IEC61850": ("device_id", "logical_node", "data_object"), "Modbus": ("device_id", "slave_id", "coil_address")}.get(protocol, ())
            candidate.missing_fields.extend(name for name in required if device_config.get(name) in (None, ""))
            return candidate
        candidate = self.router.generate(protocol, program, device_config)
        candidate.precondition_status = decision.status.value
        candidate.precondition_trace = trace
        return candidate

