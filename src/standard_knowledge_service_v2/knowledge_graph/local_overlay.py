"""Stage additive local knowledge without mutating an active or external graph."""
from copy import copy
from .current_graph import CurrentKnowledgeGraph
from .create_graph import normalize_name


def merge_memory(base, delta):
    result = copy(base)
    result.nodes = {**base.nodes}
    for key, node in delta.nodes.items():
        result.nodes[key] = {**base.nodes.get(key, {}), **node}
    result.relations = base.relations | delta.relations
    result.rule_nodes = {**base.rule_nodes, **delta.rule_nodes}
    result.document_nodes = {**base.document_nodes, **delta.document_nodes}
    result.by_name = dict(base.by_name)
    for key, nodes in delta.by_name.items():
        result.by_name[key] = list(dict.fromkeys([*base.by_name.get(key, []), *nodes]))
    result.outgoing = dict(base.outgoing)
    for key, edges in delta.outgoing.items():
        result.outgoing[key] = sorted(set(base.outgoing.get(key, [])) | set(edges))
    return result


class LocalClauseGraph:
    def __init__(self, base, local, base_entities):
        self.base, self.local, self.base_entities = base, local, base_entities

    def close(self):
        close = getattr(self.base, 'close', None)
        if close is not None:
            close()

    def neighbors(self, name, relation_types=None):
        return list(dict.fromkeys([*self.base.neighbors(name, relation_types), *self.local.neighbors(name, relation_types)]))[:50]

    def evidence_path(self, rule_id):
        return self.local.evidence_path(rule_id) or self.base.evidence_path(rule_id)

    def summary(self):
        base, local = self.base.summary(), self.local.summary()
        entities = {normalize_name(n.get('name', '')) for n in self.local.nodes.values() if n['label']=='Entity'}
        extra_entities = len(entities - self.base_entities)
        labels = dict(base.get('node_labels', {}))
        for name, value in [('Document', local['documents']), ('Rule', local['rules']), ('Entity', extra_entities)]:
            labels[name] = labels.get(name, 0) + value
        return {**base, 'documents': base.get('documents', 0)+local['documents'],
                'rules': base.get('rules', 0)+local['rules'], 'node_labels': labels,
                'unique_nodes': base.get('unique_nodes', 0)+local['documents']+local['rules']+extra_entities,
                'unique_relations': base.get('unique_relations', 0)+local['unique_relations'],
                'local_import_backend': 'local_memory', 'local_import_documents': local['documents']}


def add_local_units(graph, units, existing_units):
    delta = CurrentKnowledgeGraph(units)
    if isinstance(graph, CurrentKnowledgeGraph):
        return merge_memory(graph, delta)
    if isinstance(graph, LocalClauseGraph):
        return LocalClauseGraph(graph.base, merge_memory(graph.local, delta), graph.base_entities)
    names = {normalize_name(e.name) for unit in existing_units for e in unit.entities}
    return LocalClauseGraph(graph, delta, names)
