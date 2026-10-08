from __future__ import annotations

from ..domain import ClauseKnowledgeUnit, ScenarioContext
from ..instruction_engine.instruction_generator import InstructionGenerationService
from ..instruction_engine.semantic_extractor import SemanticExtractor


class InstructionService:
    def __init__(self, generator: InstructionGenerationService | None = None) -> None:
        self.extractor = SemanticExtractor()
        self.generator = generator or InstructionGenerationService()

    def generate_for_clause(self, unit: ClauseKnowledgeUnit, context: ScenarioContext, device_config: dict, protocol: str = ""):
        if not unit.rules:
            return []
        return [self.generator.generate(self.extractor.extract_rule(rule, unit), context, device_config, protocol) for rule in unit.rules]
