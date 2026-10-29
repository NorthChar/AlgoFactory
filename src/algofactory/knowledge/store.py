"""SQLite is the authoritative store; writes validate the complete graph atomically."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from algofactory.schemas.knowledge import RELATION_ENDPOINTS, KnowledgeBatch


def canonical(value: dict) -> str:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


class KnowledgeConflict(ValueError):
    pass


class KnowledgeStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=10)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in {0, 1, 2}:
            self.connection.close()
            raise ValueError("Unsupported database schema version")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS sources (
                id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY, type TEXT NOT NULL,
                source_id TEXT NOT NULL REFERENCES sources(id), payload TEXT NOT NULL,
                CHECK(type IN ('Task','Capability','Algorithm','Implementation','Dataset',
                               'ValidationRun','FailureCase','Experience','Dependency'))
            );
            CREATE TABLE IF NOT EXISTS allowed_edges (
                type TEXT NOT NULL, head_type TEXT NOT NULL, tail_type TEXT NOT NULL,
                PRIMARY KEY(type, head_type, tail_type)
            );
            CREATE TABLE IF NOT EXISTS relations (
                id TEXT PRIMARY KEY, type TEXT NOT NULL,
                head_id TEXT NOT NULL REFERENCES entities(id),
                tail_id TEXT NOT NULL REFERENCES entities(id),
                source_id TEXT NOT NULL REFERENCES sources(id), payload TEXT NOT NULL,
                CHECK(head_id != tail_id), UNIQUE(head_id, type, tail_id)
            );
            CREATE INDEX IF NOT EXISTS entities_type ON entities(type);
            CREATE INDEX IF NOT EXISTS entities_source ON entities(source_id);
            CREATE INDEX IF NOT EXISTS relations_head ON relations(head_id);
            CREATE INDEX IF NOT EXISTS relations_tail ON relations(tail_id);
            CREATE TRIGGER IF NOT EXISTS relation_types_insert BEFORE INSERT ON relations
            BEGIN
                SELECT CASE WHEN NOT EXISTS (
                    SELECT 1 FROM allowed_edges a
                    JOIN entities h ON h.id = NEW.head_id
                    JOIN entities t ON t.id = NEW.tail_id
                    WHERE a.type = NEW.type AND a.head_type = h.type AND a.tail_type = t.type
                ) THEN RAISE(ABORT, 'invalid relation endpoints') END;
            END;
            CREATE TRIGGER IF NOT EXISTS relation_types_update BEFORE UPDATE ON relations
            BEGIN
                SELECT RAISE(ABORT, 'relations are immutable');
            END;
            CREATE TABLE IF NOT EXISTS workflow_runs (
                workflow_id TEXT PRIMARY KEY, status TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            PRAGMA user_version = 2;
        """)
        with self.connection:
            self.connection.executemany(
                "INSERT OR IGNORE INTO allowed_edges VALUES (?, ?, ?)",
                [
                    (kind, head, tail)
                    for kind, pairs in RELATION_ENDPOINTS.items()
                    for head, tail in sorted(pairs)
                ],
            )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.connection.close()

    def snapshot(self) -> dict:
        return {
            "schema_version": 1,
            **{
                table: [
                    json.loads(row[0])
                    for row in self.connection.execute(f"SELECT payload FROM {table} ORDER BY id")
                ]
                for table in ("sources", "entities", "relations")
            },
        }

    def put_batch(
        self, batch: KnowledgeBatch, *, workflow_record: dict | None = None
    ) -> dict[str, int]:
        # Revalidate serialized input in case a caller mutated a nested list after creation.
        incoming = KnowledgeBatch.model_validate_json(batch.model_dump_json()).model_dump(
            mode="json"
        )
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            snapshot = self.snapshot()
            additions = {}
            for table in ("sources", "entities", "relations"):
                current = {obj["id"]: obj for obj in snapshot[table]}
                additions[table] = []
                for obj in incoming[table]:
                    if obj["id"] in current:
                        if canonical(current[obj["id"]]) != canonical(obj):
                            raise KnowledgeConflict(f"Immutable knowledge ID conflict: {obj['id']}")
                    else:
                        current[obj["id"]] = obj
                        additions[table].append(obj)
                snapshot[table] = list(current.values())
            KnowledgeBatch.model_validate(snapshot)
            for obj in additions["sources"]:
                self.connection.execute(
                    "INSERT INTO sources VALUES (?, ?, ?)",
                    (obj["id"], obj["sha256"], canonical(obj)),
                )
            for obj in additions["entities"]:
                self.connection.execute(
                    "INSERT INTO entities VALUES (?, ?, ?, ?)",
                    (obj["id"], obj["type"], obj["source_id"], canonical(obj)),
                )
            for obj in additions["relations"]:
                self.connection.execute(
                    "INSERT INTO relations VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        obj["id"],
                        obj["type"],
                        obj["head_id"],
                        obj["tail_id"],
                        obj["source_id"],
                        canonical(obj),
                    ),
                )
            if workflow_record is not None:
                self._insert_workflow(workflow_record)
        return {table: len(items) for table, items in additions.items()}

    def _insert_workflow(self, record: dict):
        payload = canonical(record)
        existing = self.connection.execute(
            "SELECT payload FROM workflow_runs WHERE workflow_id = ?", (record["workflow_id"],)
        ).fetchone()
        if existing is not None and existing[0] != payload:
            raise KnowledgeConflict("Workflow record is immutable")
        self.connection.execute(
            "INSERT OR IGNORE INTO workflow_runs VALUES (?, ?, ?)",
            (record["workflow_id"], record["status"], payload),
        )

    def record_workflow(self, record: dict):
        with self.connection:
            self._insert_workflow(record)

    def get_workflow(self, workflow_id: str) -> dict:
        row = self.connection.execute(
            "SELECT payload FROM workflow_runs WHERE workflow_id = ?", (workflow_id,)
        ).fetchone()
        if row is None:
            raise KeyError(workflow_id)
        return json.loads(row[0])

    def evidence(self, identifier: str) -> dict:
        row = self.connection.execute(
            "SELECT payload FROM entities WHERE id = ? UNION ALL "
            "SELECT payload FROM relations WHERE id = ?",
            (identifier, identifier),
        ).fetchone()
        if row is None:
            raise KeyError(identifier)
        obj = json.loads(row[0])
        source_row = self.connection.execute(
            "SELECT payload FROM sources WHERE id = ?", (obj["source_id"],)
        ).fetchone()
        source = json.loads(source_row[0])
        return {
            "record": obj,
            "source": {
                "id": source["id"],
                "title": source["title"],
                "sha256": source["sha256"],
                "span": obj["source_span"],
            },
        }

    def search(
        self,
        text: str = "",
        task_type: str | None = None,
        entity_type: str | None = None,
        limit: int = 20,
        *,
        source_id: str | None = None,
        data_kind: str | None = None,
    ) -> list[dict]:
        if not 1 <= limit <= 100:
            raise ValueError("Search limit must be between 1 and 100")
        if task_type not in {
            None,
            "binary_classification",
            "multiclass_classification",
            "regression",
        }:
            raise ValueError("Unsupported task type")
        if entity_type is None:
            rows = self.connection.execute("SELECT payload FROM entities ORDER BY id")
        else:
            rows = self.connection.execute(
                "SELECT payload FROM entities WHERE type = ? ORDER BY id", (entity_type,)
            )
        matches = []
        terms = text.casefold().split()
        for row in rows:
            entity = json.loads(row[0])
            if source_id is not None and entity["source_id"] != source_id:
                continue
            if (
                data_kind is not None
                and entity.get("conditions", entity.get("applicability", {})).get("data_kind")
                != data_kind
            ):
                continue
            if task_type:
                types = entity.get("conditions", entity.get("applicability", {})).get(
                    "task_types", []
                )
                if entity.get("task_type") != task_type and task_type not in types:
                    continue
            # Search semantic fields only; quoting the whole source must not make every
            # entity match all words in that source.
            searchable = {
                k: v
                for k, v in entity.items()
                if k not in {"id", "source_id", "source_span", "schema_version"}
            }
            haystack = canonical(searchable).casefold()
            if terms and not all(term in haystack for term in terms):
                continue
            evidence = self.evidence(entity["id"])
            related = self.connection.execute(
                "SELECT id FROM relations WHERE head_id = ? OR tail_id = ? ORDER BY id",
                (entity["id"], entity["id"]),
            )
            evidence["relations"] = [self.evidence(edge[0]) for edge in related]
            matches.append(evidence)
            if len(matches) >= limit:
                break
        return matches

    def export_json(self, path: Path):
        batch = KnowledgeBatch.model_validate(self.snapshot())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(batch.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
