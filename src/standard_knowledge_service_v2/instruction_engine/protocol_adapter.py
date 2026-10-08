from __future__ import annotations

from typing import Protocol

from .models import CandidateInstruction, ILRProgram


class ProtocolAdapter(Protocol):
    protocol: str
    def generate(self, program: ILRProgram, config: dict) -> CandidateInstruction: ...


class ProtocolRouter:
    def __init__(self, adapters: list[ProtocolAdapter]) -> None:
        self._adapters = {item.protocol.lower(): item for item in adapters}

    def generate(self, protocol: str, program: ILRProgram, config: dict) -> CandidateInstruction:
        adapter = self._adapters.get(protocol.lower())
        if not adapter:
            return CandidateInstruction(protocol=protocol, missing_fields=["supported_protocol"], evidence=program.evidence, explanation="未配置该协议适配器")
        return adapter.generate(program, config)
