from __future__ import annotations

from ..instruction_engine.models import CandidateInstruction, SemanticTuple
from .validation_models import ValidationStatus


class ClauseInstructionValidator:
    def validate(self, semantic: SemanticTuple, instruction: CandidateInstruction) -> tuple[ValidationStatus, list[str]]:
        issues: list[str] = []
        requested = str(instruction.payload.get("requested_action", ""))
        if instruction.missing_fields:
            return ValidationStatus.UNCERTAIN, [f"缺少指令配置: {', '.join(instruction.missing_fields)}"]
        if requested != semantic.action:
            issues.append("协议候选动作与条款规则动作不一致")
        if not instruction.evidence:
            issues.append("候选指令缺少条款证据")
        return (ValidationStatus.FAIL if issues else ValidationStatus.PASS), issues
