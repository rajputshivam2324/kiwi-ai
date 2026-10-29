"""Chroma semantic retrieval + PostgreSQL full-text search + parent expansion."""
from collections import Counter
import hashlib
import logging
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from app.config import get_settings
from app.services.observability import observation, traced
from app.services.research.document_index import DocumentIndex
from app.services.research.pdf_pipeline import truncate_tokens

logger = logging.getLogger(__name__)


class VectorStoreService:
    def __init__(self):
        self.settings = get_settings()
        self.embeddings = GoogleGenerativeAIEmbeddings(
            model=self.settings.embedding_model, google_api_key=self.settings.google_api_key,
        )
        self.chroma_client = chromadb.PersistentClient(
            path=self.settings.chroma_db_path,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        # Preserve existing collection settings and legacy embeddings.
        self.collection = self.chroma_client.get_or_create_collection(self.settings.collection_name)
        name = hashlib.sha256(self.settings.collection_name.encode()).hexdigest()[:16]
        self.index = DocumentIndex(self.settings.collection_name)
        self.index.migrate_sqlite(Path(self.settings.chroma_db_path) / f"rag-{name}.sqlite3")

    @traced("research.index.document")
    def index_document(self, document_id, revision, chunks):
        if self.index.matches(document_id, revision):
            return 0
        activated = False
        with self.index.staging(document_id, revision) as stage:
            count = stage.write(chunks, self.settings.rag_embedding_batch_size)
            if not count:
                raise ValueError("Cannot index an empty document")
            try:
                for batch in stage.batches(self.settings.rag_embedding_batch_size):
                    self.add_documents([row["content"] for row in batch],
                                       [row["metadata"] for row in batch], [row["id"] for row in batch])
                retired_runs = self.index.activate(stage)
                activated = True
            finally:
                if not activated:
                    try:
                        # A commit may succeed even if its acknowledgement is
                        # lost. Never delete vectors until inactivity is known.
                        if not self.index.is_active(stage.run_id):
                            self.collection.delete(where={"ingest_run": stage.run_id})
                    except Exception:
                        logger.warning("Staged vector cleanup failed; inactive rows remain hidden", exc_info=True)
        # Captured under the commit lock: these runs can never become active again,
        # including when a concurrent ingestion commits immediately after ours.
        for retired_run in retired_runs:
            try:
                self.collection.delete(where={"ingest_run": retired_run})
                self.index.discard_retired(retired_run)
            except Exception:
                logger.warning("Retired vector cleanup failed; rows remain hidden", exc_info=True)
        return count

    def add_documents(self, texts, metadatas, ids):
        if not (len(texts) == len(metadatas) == len(ids)):
            raise ValueError("Texts, metadata and IDs must have equal lengths")
        size = self.settings.rag_embedding_batch_size
        for start in range(0, len(texts), size):
            batch = texts[start:start + size]
            metadata = metadatas[start:start + size]
            embedded_texts = [f"{truncate_tokens(meta.get('title', ''), 100)}\n{truncate_tokens(meta.get('section', ''), 128)}\n{text}"
                              for text, meta in zip(batch, metadata)]
            with observation("research.embedding.batch", "embedding", model=self.settings.embedding_model,
                             metadata={"documents": len(batch)}) as span:
                vectors = self.embeddings.embed_documents(embedded_texts, task_type="retrieval_document")
                self.collection.upsert(ids=ids[start:start + size], documents=batch,
                                       metadatas=metadata, embeddings=vectors)
                span.update(metadata={"documents": len(batch), "dimensions": len(vectors[0])})

    def _dense_search(self, query, k, filters):
        count = self.collection.count()
        if not count:
            return []
        with observation("research.embedding.query", "embedding", model=self.settings.embedding_model):
            vector = self.embeddings.embed_query(query, task_type="retrieval_query")
        result = self.collection.query(query_embeddings=[vector], n_results=min(k, count),
                                       where=filters, include=["documents", "metadatas", "distances"])
        ids = result["ids"][0]
        active = self.index.get_many(ids, filters)
        reingested = self.index.contains_documents([
            meta.get("arxiv_id", "") for meta in result["metadatas"][0]
        ])
        documents = []
        for chunk_id, text, meta, distance in zip(ids, result["documents"][0], result["metadatas"][0], result["distances"][0]):
            if chunk_id in active:
                document = active[chunk_id]
            elif not meta.get("pipeline_version") and meta.get("arxiv_id", "") not in reingested:
                document = {"id": chunk_id, "content": text, "metadata": meta}
            else:
                continue
            documents.append({**document, "distance": float(distance)})
        return documents

    @traced("research.retrieve.hybrid", "retriever")
    def similarity_search(self, query, k=6, filter=None):
        if k <= 0 or not query.strip():
            return []
        candidates = max(k, self.settings.rag_candidate_count)
        with observation("research.retrieve.candidates", "retriever") as span:
            try:
                dense = self._dense_search(query, candidates, filter)
            except Exception:
                logger.warning("Dense retrieval failed; using PostgreSQL full-text search", exc_info=True)
                dense = []
            try:
                lexical = self.index.search(query, candidates, filter)
            except Exception:
                logger.warning("PostgreSQL lexical retrieval failed; using dense retrieval", exc_info=True)
                lexical = []
            scores, documents = {}, {}
            for ranking in (dense, lexical):
                for rank, document in enumerate(ranking, 1):
                    key = document["id"]
                    scores[key] = scores.get(key, 0) + 1 / (60 + rank)
                    documents.setdefault(key, document)
            ranked = sorted(documents, key=lambda key: (-scores[key], key))
            selected, seen_parents, per_paper = [], set(), Counter()
            for key in ranked:
                document = documents[key]
                meta = dict(document["metadata"])
                parent_id = meta.get("parent_id", key)
                paper_id = meta.get("document_id", meta.get("arxiv_id", key))
                if parent_id in seen_parents or per_paper[paper_id] >= max(2, (k + 1) // 2):
                    continue
                seen_parents.add(parent_id)
                per_paper[paper_id] += 1
                selected.append({"content": document.get("parent_content", document["content"]),
                                 "metadata": meta, "score": scores[key],
                                 "score_type": "rrf", "matched_content": document["content"]})
                if len(selected) == k:
                    break
            span.update(metadata={"dense_candidates": len(dense), "lexical_candidates": len(lexical),
                                  "selected": len(selected),
                                  "chunk_ids": [d["metadata"].get("chunk_id", "legacy") for d in selected]})
            return selected

    def get_collection_count(self):
        return self.collection.count()

    def reset_collection(self):
        self.chroma_client.delete_collection(self.settings.collection_name)
        self.collection = self.chroma_client.get_or_create_collection(self.settings.collection_name)
        self.index.clear()


_vectorstore_service = None


def get_vectorstore_service():
    global _vectorstore_service
    if _vectorstore_service is None:
        _vectorstore_service = VectorStoreService()
    return _vectorstore_service
