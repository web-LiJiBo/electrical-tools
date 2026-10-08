from __future__ import annotations

from .models import CandidateInstruction, ILRProgram


class ModbusAdapter:
    protocol = "Modbus"
    required = ("device_id", "slave_id", "coil_address")

    def generate(self, program: ILRProgram, config: dict) -> CandidateInstruction:
        missing = [item for item in self.required if config.get(item) in (None, "")]
        action = program.actions[0] if program.actions else {}
        if missing:
            return CandidateInstruction(protocol=self.protocol, target=str(config.get("device_id", "")), missing_fields=missing, evidence=program.evidence, explanation="Modbus配置不完整，仅返回待补充信息")
        payload = {"function_code": 5, "slave_id": config["slave_id"], "coil_address": config["coil_address"], "value": bool(config.get("value", True)), "requested_action": action.get("action", ""), "ilr_program_id": program.program_id}
        return CandidateInstruction(protocol=self.protocol, target=str(config["device_id"]), payload=payload, evidence=program.evidence, explanation="Modbus候选帧，需通过验证和人工确认", dispatch_allowed=False)
