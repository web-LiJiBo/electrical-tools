"""后台服务可识别、可恢复的业务异常。"""

from __future__ import annotations


class KnowledgeServiceError(Exception):
    code = "knowledge_service_error"


class ModelLoadError(KnowledgeServiceError):
    code = "model_load_error"


class DecompositionError(KnowledgeServiceError):
    code = "decomposition_error"


class MissingParameterError(KnowledgeServiceError):
    code = "missing_parameter"


class UnsupportedScenarioError(KnowledgeServiceError):
    code = "unsupported_scenario"

