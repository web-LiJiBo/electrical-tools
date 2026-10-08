from __future__ import annotations

from collections import deque
from typing import Protocol


class NeighborGraph(Protocol):
    def neighbors(self, node_name: str, relation_types: set[str] | None = None) -> list[tuple[str, str]]: ...


class SemanticReasoner:
    def __init__(self, graph: NeighborGraph) -> None:
        self.graph = graph

    def infer(self, entity: str, relation_types: set[str] | None = None, max_depth: int = 2) -> list[list[str]]:
        paths: list[list[str]] = []
        queue = deque([(entity, [entity], 0)])
        visited = {entity}
        while queue:
            current, path, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for relation, target in self.graph.neighbors(current, relation_types):
                new_path = path + [relation, target]
                paths.append(new_path)
                if target not in visited:
                    visited.add(target)
                    queue.append((target, new_path, depth + 1))
        return paths
