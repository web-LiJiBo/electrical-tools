from __future__ import annotations

from ..retrieval import LunwenMatchingInput
from ..retrieval_engine.lunwen_adapter import LocalLunwenRetrievalAdapter


class SearchService:
    def __init__(self, retriever: LocalLunwenRetrievalAdapter) -> None:
        self.retriever = retriever

    def search(self, query: str, parsed_json: dict | None = None):
        parsed = {**(parsed_json or {}), "intent": "search"}
        return self.retriever.match(LunwenMatchingInput(query, parsed))
