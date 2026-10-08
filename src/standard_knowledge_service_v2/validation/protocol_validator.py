from __future__ import annotations

from ..instruction_engine.models import CandidateInstruction
from .validation_models import ValidationStatus


class ProtocolValidator:
    def validate(self, instruction: CandidateInstruction) -> tuple[ValidationStatus, list[str]]:
        if instruction.missing_fields:
            return ValidationStatus.UNCERTAIN, ["协议映射字段不完整"]
        if instruction.protocol == "IEC61850":
            needed = {"service", "logical_node", "data_object"}
        elif instruction.protocol == "Modbus":
            needed = {"function_code", "slave_id", "coil_address"}
        else:
            return ValidationStatus.FAIL, [f"不支持的协议: {instruction.protocol}"]
        missing = [name for name in needed if name not in instruction.payload]
        return (ValidationStatus.FAIL if missing else ValidationStatus.PASS), ([f"协议帧字段缺失: {', '.join(missing)}"] if missing else [])
