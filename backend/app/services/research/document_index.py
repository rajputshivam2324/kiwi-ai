"""Disk-backed parent store and BM25 index, committed per complete document.

Chroma supplies vector candidates; SQLite controls new-pipeline visibility.
Failed/staged embeddings can never become evidence.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import re
import sqlite3

from app.services.research.arxiv_client import extract_search_terms


def _where_filter(filters):
    if not filters:
        return "1", []
    clauses, params = [], []
    for key, value in filters.items():
        if key in {"$and", "$or"}:
            if not isinstance(value, list) or not value:
                raise ValueError("Logical filters require a nonempty list")
            children = [_where_filter(item) for item in value]
            clauses.append("(" + (" AND " if key == "$and" else " OR ").join(c[0] for c in children) + ")")
            params.extend(p for child in children for p in child[1])
            continue
        if not re.fullmatch(r"[A-Za-z_]\w*", key):
            raise ValueError("Unsupported metadata filter key")
        expression = f"json_extract(c.metadata, '$.{key}')"
        operations = value if isinstance(value, dict) else {"$eq": value}
        for operator, operand in operations.items():
            if operator in {"$in", "$nin"}:
                if not isinstance(operand, list) or not operand:
                    raise ValueError("Membership filters require a nonempty list")
                clauses.append(f"{expression} {'NOT IN' if operator == '$nin' else 'IN'} ({','.join('?' for _ in operand)})")
                params.extend(operand)
            else:
                sql_operator = {"$eq": "=", "$ne": "!=", "$gt": ">", "$gte": ">=", "$lt": "<", "$lte": "<="}.get(operator)
                if sql_operator is None:
                    raise ValueError("Unsupported metadata filter operator")
                clauses.append(f"{expression} {sql_operator} ?")
                params.append(operand)
    return " AND ".join(clauses), params


class DocumentIndex:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, revision TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS parents (
                    id TEXT PRIMARY KEY, document_id TEXT NOT NULL, content TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS parents_document ON parents(document_id);
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY, document_id TEXT NOT NULL, parent_id TEXT NOT NULL,
                    content TEXT NOT NULL, metadata TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS chunks_document ON chunks(document_id);
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    id UNINDEXED, content, title, section, tokenize='unicode61'
                );
                CREATE TRIGGER IF NOT EXISTS chunks_insert AFTER INSERT ON chunks BEGIN
                    INSERT INTO chunks_fts(rowid, id, content, title, section)
                    VALUES (new.rowid, new.id, new.content, json_extract(new.metadata, '$.title'),
                            json_extract(new.metadata, '$.section'));
                END;
                CREATE TRIGGER IF NOT EXISTS chunks_delete AFTER DELETE ON chunks BEGIN
                    DELETE FROM chunks_fts WHERE rowid = old.rowid;
                END;
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def matches(self, document_id, revision):
        with self.connect() as db:
            row = db.execute("SELECT revision FROM documents WHERE id=?", (document_id,)).fetchone()
            return row is not None and row[0] == revision

    def stage(self, document_id, revision, run_id, chunks):
        """Called on an isolated temporary database; memory is bounded by a chunk."""
        count = 0
        with self.connect() as db:
            db.execute("INSERT INTO documents VALUES (?, ?)", (document_id, revision))
            for count, chunk in enumerate(chunks, 1):
                metadata = dict(chunk["metadata"])
                parent_id = f"{run_id}:{metadata.get('parent_id', count)}"
                chunk_id = f"{run_id}:{count}"
                metadata.update(parent_id=parent_id, chunk_id=chunk_id, document_id=document_id,
                                revision=revision, ingest_run=run_id)
                db.execute("INSERT OR IGNORE INTO parents VALUES (?, ?, ?)",
                           (parent_id, document_id, chunk.get("parent_content", chunk["content"])))
                db.execute("INSERT INTO chunks VALUES (?, ?, ?, ?, ?)",
                           (chunk_id, document_id, parent_id, chunk["content"], json.dumps(metadata)))
        return count

    def batches(self, size):
        with self.connect() as db:
            cursor = db.execute("SELECT id, content, metadata FROM chunks ORDER BY rowid")
            while rows := cursor.fetchmany(size):
                yield [{"id": row["id"], "content": row["content"], "metadata": json.loads(row["metadata"])} for row in rows]

    def activate(self, stage, document_id):
        with self.connect() as db:
            db.execute("ATTACH DATABASE ? AS stage", (stage.path,))
            db.execute("BEGIN IMMEDIATE")
            retired_runs = [row[0] for row in db.execute(
                "SELECT DISTINCT json_extract(metadata, '$.ingest_run') FROM chunks WHERE document_id=?",
                (document_id,),
            )]
            db.execute("DELETE FROM chunks WHERE document_id=?", (document_id,))
            db.execute("DELETE FROM parents WHERE document_id=?", (document_id,))
            db.execute("DELETE FROM documents WHERE id=?", (document_id,))
            db.execute("INSERT INTO documents SELECT * FROM stage.documents")
            db.execute("INSERT INTO parents SELECT * FROM stage.parents")
            db.execute("INSERT INTO chunks SELECT * FROM stage.chunks")
        return retired_runs

    def contains_documents(self, ids):
        if not ids:
            return set()
        with self.connect() as db:
            return {row[0] for row in db.execute(
                f"SELECT id FROM documents WHERE id IN ({','.join('?' for _ in ids)})", ids
            )}

    @staticmethod
    def _document(row):
        return {"id": row["id"], "content": row["content"], "metadata": json.loads(row["metadata"]),
                "parent_content": row["parent_content"]}

    def get_many(self, ids, filters=None):
        if not ids:
            return {}
        condition, params = _where_filter(filters)
        with self.connect() as db:
            rows = db.execute(f"""SELECT c.*, p.content AS parent_content FROM chunks c
                JOIN parents p ON p.id=c.parent_id
                WHERE c.id IN ({','.join('?' for _ in ids)}) AND ({condition})""", [*ids, *params])
            return {row["id"]: self._document(row) for row in rows}

    def search(self, query, k, filters=None):
        terms = extract_search_terms(query, limit=24)
        if not terms:
            return []
        match = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
        condition, params = _where_filter(filters)
        with self.connect() as db:
            rows = db.execute(f"""SELECT c.*, p.content AS parent_content,
                bm25(chunks_fts, 0, 1, 2, 1.5) AS lexical_score
                FROM chunks_fts JOIN chunks c ON c.id=chunks_fts.id
                JOIN parents p ON p.id=c.parent_id
                WHERE chunks_fts MATCH ? AND ({condition})
                ORDER BY lexical_score, c.id LIMIT ?""", [match, *params, k])
            return [self._document(row) for row in rows]

    def clear(self):
        with self.connect() as db:
            db.execute("DELETE FROM chunks")
            db.execute("DELETE FROM parents")
            db.execute("DELETE FROM documents")
