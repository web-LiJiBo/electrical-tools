"""条款语义→ILR→协议候选指令；所有输出均不可直接下发。"""

from .instruction_generator import InstructionGenerationService
from .models import CandidateInstruction, SemanticTuple
from .semantic_extractor import SemanticExtractor

__all__ = ["CandidateInstruction", "InstructionGenerationService", "SemanticExtractor", "SemanticTuple"]
