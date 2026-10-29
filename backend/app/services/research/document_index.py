"""PostgreSQL document revisions, parent passages, and GIN full-text search.

Staged runs stay invisible until their vector batches have completed. A short
transaction switches the active revision; no distributed transaction is claimed.
"""
from contextlib import contextmanager
import json
import re
from uuid import uuid4

from psycopg import sql
from psycopg.types.json import Jsonb

from app.services.postgres import get_pool
from app.services.research.arxiv_client import extract_search_terms

DDL = """
CREATE TABLE IF NOT EXISTS rag_documents (
    collection TEXT NOT NULL, id TEXT NOT NULL, revision TEXT NOT NULL DEFAULT '',
    active_run TEXT, PRIMARY KEY(collection, id)
);
CREATE TABLE IF NOT EXISTS rag_runs (
    id TEXT PRIMARY KEY, collection TEXT NOT NULL, document_id TEXT NOT NULL,
    revision TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS rag_runs_collection ON rag_runs(collection, document_id);
CREATE TABLE IF NOT EXISTS rag_parents (
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES rag_runs(id) ON DELETE CASCADE,
    content TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rag_chunks (
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES rag_runs(id) ON DELETE CASCADE,
    parent_id TEXT NOT NULL REFERENCES rag_parents(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL, content TEXT NOT NULL, metadata JSONB NOT NULL,
    search_vector TSVECTOR GENERATED ALWAYS AS (
        setweight(to_tsvector('simple', coalesce(metadata->>'title', '')), 'A') ||
        setweight(to_tsvector('simple', coalesce(metadata->>'section', '')), 'B') ||
        setweight(to_tsvector('simple', content), 'C')
    ) STORED
);
CREATE INDEX IF NOT EXISTS rag_chunks_search ON rag_chunks USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS rag_chunks_run ON rag_chunks(run_id, ordinal);
CREATE TABLE IF NOT EXISTS rag_migrations (
    collection TEXT NOT NULL, source TEXT NOT NULL, migrated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(collection, source)
);
"""


def _where_filter(filters):
    if not filters:
        return sql.SQL('TRUE'), []
    clauses, params = [], []
    for key, value in filters.items():
        if key in {'$and', '$or'}:
            if not isinstance(value, list) or not value:
                raise ValueError('Logical filters require a nonempty list')
            children = [_where_filter(item) for item in value]
            joiner = sql.SQL(' AND ' if key == '$and' else ' OR ')
            clauses.append(sql.SQL('({})').format(joiner.join(c[0] for c in children)))
            params.extend(p for child in children for p in child[1])
            continue
        if not re.fullmatch(r'[A-Za-z_]\w*', key):
            raise ValueError('Unsupported metadata filter key')
        expression = sql.SQL('(c.metadata -> {})').format(sql.Literal(key))
        operations = value if isinstance(value, dict) else {'$eq': value}
        for operator, operand in operations.items():
            if operator in {'$in', '$nin'}:
                if not isinstance(operand, list) or not operand:
                    raise ValueError('Membership filters require a nonempty list')
                clauses.append(sql.SQL('{} {} ({})').format(
                    expression, sql.SQL('NOT IN' if operator == '$nin' else 'IN'),
                    sql.SQL(',').join(sql.Placeholder() for _ in operand)))
                params.extend(Jsonb(item) for item in operand)
            else:
                operation = {'$eq': '=', '$ne': '!=', '$gt': '>', '$gte': '>=', '$lt': '<', '$lte': '<='}.get(operator)
                if operation is None:
                    raise ValueError('Unsupported metadata filter operator')
                clauses.append(sql.SQL('{} {} %s').format(expression, sql.SQL(operation)))
                params.append(Jsonb(operand))
    return sql.SQL(' AND ').join(clauses), params


class DocumentIndex:
    def __init__(self, collection):
        self.collection = collection
        self.pool = get_pool()
        with self.pool.connection() as db, db.transaction():
            db.execute("SELECT pg_advisory_xact_lock(hashtextextended('kiwi:rag:schema', 0))")
            db.execute(DDL)

    @contextmanager
    def staging(self, document_id, revision):
        run_id = uuid4().hex
        with self.pool.connection() as db:
            db.execute('INSERT INTO rag_runs(id, collection, document_id, revision) VALUES (%s,%s,%s,%s)',
                       (run_id, self.collection, document_id, revision))
        try:
            yield StagedDocument(self, document_id, revision, run_id)
        finally:
            # Deletes only inactive runs. A committed active run survives cleanup.
            with self.pool.connection() as db:
                db.execute('''DELETE FROM rag_runs r WHERE r.id=%s AND NOT EXISTS
                    (SELECT 1 FROM rag_documents d WHERE d.active_run=r.id)''', (run_id,))

    def matches(self, document_id, revision):
        with self.pool.connection() as db:
            return db.execute('''SELECT 1 FROM rag_documents WHERE collection=%s AND id=%s
                AND active_run IS NOT NULL AND revision=%s''', (self.collection, document_id, revision)).fetchone() is not None

    def activate(self, stage):
        with self.pool.connection() as db, db.transaction():
            db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))',
                       (f'kiwi:rag:{self.collection}:{stage.document_id}',))
            current = db.execute('SELECT active_run FROM rag_documents WHERE collection=%s AND id=%s',
                                 (self.collection, stage.document_id)).fetchone()
            db.execute('''INSERT INTO rag_documents(collection,id,revision,active_run) VALUES (%s,%s,%s,%s)
                ON CONFLICT(collection,id) DO UPDATE SET revision=EXCLUDED.revision, active_run=EXCLUDED.active_run''',
                       (self.collection, stage.document_id, stage.revision, stage.run_id))
        return [current['active_run']] if current and current['active_run'] else []

    def discard_retired(self, run_id):
        with self.pool.connection() as db:
            db.execute('''DELETE FROM rag_runs r WHERE id=%s AND collection=%s AND NOT EXISTS
                (SELECT 1 FROM rag_documents d WHERE d.active_run=r.id)''', (run_id, self.collection))

    def is_active(self, run_id):
        with self.pool.connection() as db:
            return db.execute('SELECT 1 FROM rag_documents WHERE collection=%s AND active_run=%s',
                              (self.collection, run_id)).fetchone() is not None

    def contains_documents(self, ids):
        if not ids:
            return set()
        with self.pool.connection() as db:
            return {row['id'] for row in db.execute('''SELECT id FROM rag_documents
                WHERE collection=%s AND id=ANY(%s) AND active_run IS NOT NULL''', (self.collection, list(ids)))}

    @staticmethod
    def _document(row):
        return {'id': row['id'], 'content': row['content'], 'metadata': row['metadata'],
                'parent_content': row['parent_content']}

    def get_many(self, ids, filters=None):
        if not ids:
            return {}
        condition, params = _where_filter(filters)
        query = sql.SQL('''SELECT c.*, p.content AS parent_content FROM rag_chunks c
            JOIN rag_parents p ON p.id=c.parent_id
            JOIN rag_documents d ON d.active_run=c.run_id
            WHERE d.collection=%s AND c.id=ANY(%s) AND ({})''').format(condition)
        with self.pool.connection() as db:
            return {row['id']: self._document(row) for row in db.execute(query, [self.collection, list(ids), *params])}

    def search(self, query, k, filters=None):
        terms = [word for term in extract_search_terms(query, limit=24) for word in re.findall(r'\w+', term)]
        if not terms:
            return []
        match = ' | '.join(terms)
        condition, params = _where_filter(filters)
        statement = sql.SQL('''SELECT c.*, p.content AS parent_content,
            ts_rank_cd(c.search_vector, to_tsquery('simple', %s), 32) AS lexical_score
            FROM rag_chunks c JOIN rag_parents p ON p.id=c.parent_id
            JOIN rag_documents d ON d.active_run=c.run_id
            WHERE d.collection=%s AND c.search_vector @@ to_tsquery('simple', %s) AND ({})
            ORDER BY lexical_score DESC, c.id LIMIT %s''').format(condition)
        with self.pool.connection() as db:
            return [self._document(row) for row in db.execute(statement, [match, self.collection, match, *params, k])]

    def clear(self):
        with self.pool.connection() as db, db.transaction():
            db.execute('DELETE FROM rag_documents WHERE collection=%s', (self.collection,))
            db.execute('DELETE FROM rag_runs WHERE collection=%s', (self.collection,))
            # Keep the migration marker so an explicit reset cannot resurrect old data.

    def migrate_sqlite(self, path):
        """One-time, read-only import of the previous sidecar; never used at runtime."""
        if not path.is_file():
            return 0
        source = path.name
        with self.pool.connection() as db, db.transaction():
            db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', (f'kiwi:migration:{self.collection}',))
            if db.execute('SELECT 1 FROM rag_migrations WHERE collection=%s AND source=%s', (self.collection, source)).fetchone():
                return 0
            import sqlite3  # Compatibility reader only; no SQLite writes or search.
            imported = 0
            with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as old:
                old.row_factory = sqlite3.Row
                for document in old.execute('SELECT * FROM documents'):
                    if db.execute('SELECT 1 FROM rag_documents WHERE collection=%s AND id=%s',
                                  (self.collection, document['id'])).fetchone():
                        continue
                    run_id = uuid4().hex
                    db.execute('INSERT INTO rag_runs(id,collection,document_id,revision) VALUES (%s,%s,%s,%s)',
                               (run_id, self.collection, document['id'], document['revision']))
                    for row in old.execute('SELECT * FROM parents WHERE document_id=?', (document['id'],)):
                        db.execute('INSERT INTO rag_parents(id,run_id,content) VALUES (%s,%s,%s)',
                                   (row['id'], run_id, row['content']))
                    for ordinal, row in enumerate(old.execute('SELECT * FROM chunks WHERE document_id=?', (document['id'],))):
                        metadata = json.loads(row['metadata'])
                        db.execute('INSERT INTO rag_chunks(id,run_id,parent_id,ordinal,content,metadata) VALUES (%s,%s,%s,%s,%s,%s)',
                                   (row['id'], run_id, row['parent_id'], ordinal, row['content'], Jsonb(metadata)))
                        imported += 1
                    db.execute('INSERT INTO rag_documents(collection,id,revision,active_run) VALUES (%s,%s,%s,%s)',
                               (self.collection, document['id'], document['revision'], run_id))
            db.execute('INSERT INTO rag_migrations(collection,source) VALUES (%s,%s)', (self.collection, source))
        return imported


class StagedDocument:
    def __init__(self, index, document_id, revision, run_id):
        self.index, self.document_id, self.revision, self.run_id = index, document_id, revision, run_id

    def write(self, chunks, batch_size=32):
        count, batch = 0, []
        for count, chunk in enumerate(chunks, 1):
            batch.append((count, chunk))
            if len(batch) >= batch_size:
                self._insert(batch)
                batch.clear()
        if batch:
            self._insert(batch)
        return count

    def _insert(self, batch):
        with self.index.pool.connection() as db, db.transaction():
            for ordinal, chunk in batch:
                meta = dict(chunk['metadata'])
                parent_id = f"{self.run_id}:{meta.get('parent_id', ordinal)}"
                chunk_id = f'{self.run_id}:{ordinal}'
                meta.update(parent_id=parent_id, chunk_id=chunk_id, document_id=self.document_id,
                            revision=self.revision, ingest_run=self.run_id)
                db.execute('INSERT INTO rag_parents(id,run_id,content) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',
                           (parent_id, self.run_id, chunk.get('parent_content', chunk['content'])))
                db.execute('INSERT INTO rag_chunks(id,run_id,parent_id,ordinal,content,metadata) VALUES (%s,%s,%s,%s,%s,%s)',
                           (chunk_id, self.run_id, parent_id, ordinal, chunk['content'], Jsonb(meta)))

    def batches(self, size):
        after = 0
        while True:
            with self.index.pool.connection() as db:
                rows = db.execute('SELECT * FROM rag_chunks WHERE run_id=%s AND ordinal>%s ORDER BY ordinal LIMIT %s',
                                  (self.run_id, after, size)).fetchall()
            if not rows:
                return
            after = rows[-1]['ordinal']
            yield rows
