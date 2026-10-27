"""Lossless GraphML exchange. Import only trusted local GraphML files."""

import json
from pathlib import Path

import networkx as nx

from algofactory.schemas.knowledge import KnowledgeBatch

from .store import canonical


def to_networkx(batch: KnowledgeBatch) -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    graph.graph["schema_version"] = 1
    graph.graph["sources_json"] = json.dumps(
        [s.model_dump(mode="json") for s in batch.sources], ensure_ascii=False, sort_keys=True
    )
    for entity in sorted(batch.entities, key=lambda item: item.id):
        graph.add_node(
            entity.id,
            type=entity.type,
            name=entity.name,
            source_id=entity.source_id,
            entity_json=canonical(entity.model_dump(mode="json")),
        )
    for edge in sorted(batch.relations, key=lambda item: item.id):
        graph.add_edge(
            edge.head_id,
            edge.tail_id,
            key=edge.id,
            type=edge.type,
            relation_json=canonical(edge.model_dump(mode="json")),
        )
    return graph


def export_graphml(batch: KnowledgeBatch, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    nx.write_graphml(to_networkx(batch), path, encoding="utf-8")


def load_graphml(path: Path) -> KnowledgeBatch:
    graph = nx.read_graphml(path, force_multigraph=True)
    if not graph.is_directed() or graph.graph.get("schema_version") != 1:
        raise ValueError("Unsupported GraphML schema")
    entities, relations = [], []
    for identifier, attrs in graph.nodes(data=True):
        entity = json.loads(attrs["entity_json"])
        if (entity["id"], entity["type"], entity["name"], entity["source_id"]) != (
            identifier,
            attrs["type"],
            attrs["name"],
            attrs["source_id"],
        ):
            raise ValueError("GraphML node metadata disagrees with payload")
        entities.append(entity)
    for head, tail, key, attrs in graph.edges(keys=True, data=True):
        edge = json.loads(attrs["relation_json"])
        if (edge["head_id"], edge["tail_id"], edge["id"], edge["type"]) != (
            head,
            tail,
            key,
            attrs["type"],
        ):
            raise ValueError("GraphML edge metadata disagrees with payload")
        relations.append(edge)
    return KnowledgeBatch.model_validate(
        {
            "sources": json.loads(graph.graph["sources_json"]),
            "entities": entities,
            "relations": relations,
        }
    )
