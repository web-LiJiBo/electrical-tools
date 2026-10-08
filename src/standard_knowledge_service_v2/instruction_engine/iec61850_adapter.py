from __future__ import annotations

from .models import CandidateInstruction, ILRProgram


class IEC61850Adapter:
    protocol = "IEC61850"
    required = ("device_id", "logical_node", "data_object")

    def generate(self, program: ILRProgram, config: dict) -> CandidateInstruction:
        missing = [item for item in self.required if not config.get(item)]
        action = program.actions[0] if program.actions else {}
        if missing:
            return CandidateInstruction(protocol=self.protocol, target=str(config.get("device_id", "")), missing_fields=missing, evidence=program.evidence, explanation="IEC 61850配置不完整，仅返回待补充信息")
        payload = {"service": "MMS", "logical_node": config["logical_node"], "data_object": config["data_object"], "requested_action": action.get("action", ""), "ilr_program_id": program.program_id}
        return CandidateInstruction(protocol=self.protocol, target=str(config["device_id"]), payload=payload, evidence=program.evidence, explanation="IEC 61850候选指令，需通过验证和人工确认", dispatch_allowed=False)
