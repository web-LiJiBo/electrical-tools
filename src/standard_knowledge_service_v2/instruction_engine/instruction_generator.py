from __future__ import annotations

from ..domain import ScenarioContext
from .iec61850_adapter import IEC61850Adapter
from .ilr_compiler import ILRCompiler
from .modbus_adapter import ModbusAdapter
from .models import CandidateInstruction, SemanticTuple
from .protocol_adapter import ProtocolRouter
from .template_library import TemplateLibrary


class InstructionGenerationService:
    def __init__(self, templates: TemplateLibrary | None = None, compiler: ILRCompiler | None = None) -> None:
        self.templates = templates or TemplateLibrary()
        self.compiler = compiler or ILRCompiler()
        self.router = ProtocolRouter([IEC61850Adapter(), ModbusAdapter()])

    def generate(self, semantic: SemanticTuple, context: ScenarioContext, device_config: dict, target_protocol: str = "") -> CandidateInstruction:
        protocol = target_protocol or str(device_config.get("protocol", "")) or "IEC61850"
        matches = self.templates.find(context.scenario, semantic.action, context.device_type, protocol)
        if not matches:
            return CandidateInstruction(protocol=protocol, evidence=semantic.evidence, missing_fields=["instruction_template"], explanation="未找到场景—动作—协议模板，禁止生成控制帧")
        program = self.compiler.compile(semantic)
        return self.router.generate(protocol, program, device_config)
