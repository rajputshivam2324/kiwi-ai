"""Offline regression and retrieval checks using actual PDFs and Chroma."""
from contextlib import contextmanager
from unittest.mock import Mock
import hashlib

import pymupdf
import pytest

from app.config import get_settings
from app.scripts import ingest_arxiv
from app.services.research import vectorstore as vector_module
from app.services.research.pdf_pipeline import (
    PDFError, PDFPage, downloaded_pdf, iter_chunks, iter_pdf_pages, split_text, token_count,
)
from app.services.research.rag_agent import RAGAgent


@pytest.fixture(autouse=True)
def settings(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    monkeypatch.setenv("CHROMA_DB_PATH", str(tmp_path / "chroma"))
    monkeypatch.setenv("COLLECTION_NAME", "test-" + hashlib.sha256(str(tmp_path).encode()).hexdigest()[:20])
    monkeypatch.setenv("RAG_OCR_ENABLED", "false")
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


class FakeEmbeddings:
    def __init__(self, **_):
        self.batch_sizes = []
        self.fail = False

    def embed_documents(self, texts, **kwargs):
        self.batch_sizes.append(len(texts))
        assert kwargs["task_type"] == "retrieval_document"
        if self.fail:
            raise RuntimeError("embedding service unavailable")
        return [[0.2, 0.4, 0.6] for _ in texts]

    def embed_query(self, query, **kwargs):
        assert kwargs["task_type"] == "retrieval_query"
        return [0.2, 0.4, 0.6]


@pytest.fixture
def store(monkeypatch):
    import os
    if not os.getenv("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL-backed retrieval tests")
    monkeypatch.setattr(vector_module, "GoogleGenerativeAIEmbeddings", FakeEmbeddings)
    store = vector_module.VectorStoreService()
    yield store
    store.index.clear()


def make_pdf(path, pages):
    with pymupdf.open() as document:
        for number, text in enumerate(pages, 1):
            page = document.new_page()
            page.insert_text((50, 30), "Recurring Journal Header", fontsize=9)
            page.insert_textbox(pymupdf.Rect(50, 80, 540, 720), text, fontsize=11)
            page.insert_text((270, 800), f"Page {number}", fontsize=9)
        document.save(path)
    return path


def chunks(text, paper="paper-a", page=1):
    return iter_chunks([PDFPage(page, text)], {"arxiv_id": paper, "title": "Test Study", "authors": "A. Author"})


def test_chunks_preserve_headings_pages_and_token_limits(settings):
    pages = [PDFPage(7, "# Methods\n\n" + "A complete scientific sentence with measurements. " * 500),
             PDFPage(8, "Continuation of the method and experimental setup.")]
    documents = list(iter_chunks(pages, {"title": "Study"}))
    assert len(documents) > 5
    assert all(token_count(d["content"]) <= settings.rag_child_tokens for d in documents)
    assert all(token_count(d["parent_content"]) <= settings.rag_parent_tokens for d in documents)
    assert all(d["metadata"]["section"] == "Methods" for d in documents)
    assert documents[-1]["metadata"]["page_start"] == 8
    assert documents[0]["metadata"]["parent_id"] == documents[1]["metadata"]["parent_id"]


def test_unicode_and_unbroken_text_remain_bounded():
    parts = split_text("人工智能研究 🥝 " * 500 + "x" * 2000, 64, 10)
    assert len(parts) > 20
    assert all(token_count(part) <= 64 for part in parts)
    with pytest.raises(ValueError):
        split_text("hello", 10, 10)


def test_real_pdf_removes_margins_and_keeps_last_page(tmp_path):
    pdf = make_pdf(tmp_path / "study.pdf", [f"Scientific content for section {i}. " * 8 for i in range(12)])
    pages = list(iter_pdf_pages(pdf))
    assert len(pages) == 12 and pages[-1].number == 12
    assert "section 11" in pages[-1].text
    assert all("Recurring Journal Header" not in p.text for p in pages)
    assert all(f"Page {p.number}" not in p.text for p in pages)


def test_real_pdf_preserves_column_reading_order(tmp_path):
    path = tmp_path / "columns.pdf"
    with pymupdf.open() as document:
        page = document.new_page()
        left = "LEFT START scientific context.\n" + "The left column explains the method.\n" * 12 + "LEFT END scientific evidence."
        right = "RIGHT START experimental context.\n" + "The right column explains the results.\n" * 12 + "RIGHT END experimental evidence."
        page.insert_textbox(pymupdf.Rect(40, 80, 275, 600), left, fontsize=9)
        page.insert_textbox(pymupdf.Rect(320, 80, 555, 600), right, fontsize=9)
        document.save(path)
    text = next(iter_pdf_pages(path)).text
    assert text.index("LEFT START") < text.index("LEFT END") < text.index("RIGHT START") < text.index("RIGHT END")


def test_scan_fails_explicitly_without_ocr(tmp_path):
    path = tmp_path / "scan.pdf"
    with pymupdf.open() as document:
        page = document.new_page()
        image = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 100, 100), False)
        image.clear_with(255)
        page.insert_image(page.rect, stream=image.tobytes("png"))
        document.save(path)
    with pytest.raises(PDFError, match="RAG_OCR_ENABLED"):
        list(iter_pdf_pages(path))


def test_page_limit_is_enforced(monkeypatch, tmp_path):
    monkeypatch.setenv("RAG_MAX_PDF_PAGES", "1")
    get_settings.cache_clear()
    path = make_pdf(tmp_path / "two.pdf", ["Readable scientific evidence. " * 5] * 2)
    with pytest.raises(PDFError, match="RAG_MAX_PDF_PAGES"):
        list(iter_pdf_pages(path))


def test_download_stream_enforces_size(monkeypatch):
    monkeypatch.setenv("RAG_MAX_PDF_BYTES", "1024")
    get_settings.cache_clear()
    response = Mock(headers={})
    response.iter_bytes.return_value = iter([b"%PDF-" + b"x" * 1500])
    @contextmanager
    def fake_stream(*args, **kwargs):
        yield response
    monkeypatch.setattr("app.services.research.pdf_pipeline.httpx.stream", fake_stream)
    with pytest.raises(PDFError, match="RAG_MAX_PDF_BYTES"):
        with downloaded_pdf("https://arxiv.org/pdf/test"):
            pytest.fail("oversized download should not be yielded")


def test_index_is_batched_idempotent_and_parent_expanded(store, settings):
    text = "# Methods\n\n" + "Gradient optimization uses a stable learning rate. " * 1200
    count = store.index_document("paper-a", "revision-1", chunks(text))
    assert count > settings.rag_embedding_batch_size
    assert max(store.embeddings.batch_sizes) <= settings.rag_embedding_batch_size
    before = len(store.embeddings.batch_sizes)
    assert store.index_document("paper-a", "revision-1", iter(())) == 0
    assert len(store.embeddings.batch_sizes) == before
    results = store.similarity_search("gradient optimization", k=4)
    assert results
    assert any(len(r["content"]) > len(r["matched_content"]) for r in results)
    assert all(r["metadata"]["page_start"] == 1 and r["score_type"] == "rrf" for r in results)


def test_failed_reindex_keeps_previous_evidence(store):
    store.index_document("paper-a", "old", chunks("The old study measures the stable quasar flux."))
    old_count = store.get_collection_count()
    store.embeddings.fail = True
    with pytest.raises(RuntimeError, match="embedding service"):
        store.index_document("paper-a", "new", chunks("The replacement study measures a pulsar."))
    assert store.index.matches("paper-a", "old")
    assert store.get_collection_count() == old_count
    assert store.index.search("quasar", 5) and not store.index.search("pulsar", 5)


def test_reindex_replaces_fts_parents_and_vectors(store):
    store.index_document("paper-a", "old", chunks("Old results report a quasar."))
    store.index_document("paper-a", "new", chunks("New results report a pulsar."))
    assert not store.index.search("quasar", 5) and store.index.search("pulsar", 5)
    assert store.get_collection_count() == 1


def test_keyword_retrieval_finds_last_page_of_large_document(store, tmp_path):
    # Equal embeddings: lexical retrieval must locate the unique needle.
    texts = [f"Experiment section {i} discusses calibration of generic detectors. " * 5 for i in range(80)]
    texts[-1] += " The XZQ991 detector has a recovery latency of 17 milliseconds."
    pdf = make_pdf(tmp_path / "large.pdf", texts)
    store.index_document("large-study", "one", iter_chunks(iter_pdf_pages(pdf), {
        "title": "Large Detector Study", "arxiv_id": "large-study",
    }))
    result = store.similarity_search("XZQ991 recovery latency", k=6)
    assert any("17 milliseconds" in r["content"] and r["metadata"]["page_start"] == 80 for r in result)


def test_lexical_fallback_and_filters_survive_embedding_outage(store, monkeypatch):
    store.index_document("paper-a", "a", chunks("The quasar has a measured flux of 42 units.", "paper-a"))
    store.index_document("paper-b", "b", chunks("The quasar has a measured flux of 17 units.", "paper-b"))
    monkeypatch.setattr(store.embeddings, "embed_query", Mock(side_effect=RuntimeError("provider offline")))
    result = store.similarity_search("quasar flux", filter={"arxiv_id": "paper-b"})
    assert len(result) == 1 and "17 units" in result[0]["content"]
    assert result[0]["metadata"]["arxiv_id"] == "paper-b"
    assert store.index.search("quasar flux", 5, {"$and": [{"arxiv_id": {"$in": ["paper-a"]}}, {"page_start": {"$gte": 1}}]})


def test_reset_clears_both_indexes_and_can_be_reused(store):
    store.index_document("paper-a", "a", chunks("The quasar study contains sufficient evidence."))
    store.reset_collection()
    assert store.get_collection_count() == 0 and not store.index.search("quasar", 5)
    store.index_document("paper-b", "b", chunks("A pulsar study contains sufficient evidence."))
    assert store.similarity_search("pulsar")


def test_context_keeps_passages_same_paper_with_budget(monkeypatch):
    monkeypatch.setenv("RAG_CONTEXT_TOKENS", "700")
    get_settings.cache_clear()
    agent = RAGAgent.__new__(RAGAgent)
    documents = [{"content": "Method evidence " * 100, "metadata": {"arxiv_id": "1706.03762", "title": "Study", "parent_id": "one", "page_start": 2}},
                 {"content": "Final result sentinel " * 100, "metadata": {"arxiv_id": "1706.03762", "title": "Study", "parent_id": "two", "page_start": 99}}]
    context = agent._format_context(documents)
    assert "Method evidence" in context and "Final result sentinel" in context and "page 99" in context
    assert token_count(context) <= 700


def test_ingestion_reports_failed_pdfs_and_skips_unchanged(store, monkeypatch, tmp_path):
    good = make_pdf(tmp_path / "good.pdf", ["The quasar study reports scientific measurements. " * 8])
    papers = [{"arxiv_id": aid, "title": "Study", "authors": ["Author"], "abstract": "Test abstract",
               "published": "2026-01-01", "categories": ["cs.AI"], "pdf_url": aid} for aid in ["good", "bad"]]
    monkeypatch.setattr(ingest_arxiv, "search_arxiv", lambda *a: papers)
    @contextmanager
    def download(url):
        if url == "bad":
            raise PDFError("Unparseable PDF")
        yield good, "hash"
    monkeypatch.setattr(ingest_arxiv, "downloaded_pdf", download)
    result = ingest_arxiv.ingest_papers("quasar", 2, store)
    assert result["status"] == "partial" and result["arxiv_ids"] == ["good"]
    assert result["errors"][0]["arxiv_id"] == "bad"
    repeat = ingest_arxiv.ingest_papers("quasar", 2, store)
    assert repeat["documents_added"] == 0 and repeat["skipped_arxiv_ids"] == ["good"]
    assert not store.index.contains_documents(["bad"])


def test_uncommitted_vectors_are_never_returned(store):
    store.collection.upsert(ids=["inactive"], documents=["Poisoned evidence about quasars"],
                            embeddings=[[0.2, 0.4, 0.6]], metadatas=[{"pipeline_version": "v1", "arxiv_id": "paper-a"}])
    assert store.similarity_search("quasar") == []


def test_real_pdf_table_values_keep_their_row_labels(tmp_path):
    path = tmp_path / "table.pdf"
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((50, 70), "Detector measurement results", fontsize=13)
        for y in [100, 130, 160, 190]:
            page.draw_line((50, y), (450, y))
        for x in [50, 250, 450]:
            page.draw_line((x, 100), (x, 190))
        for y, model, latency in [(120, "Detector", "Latency"), (150, "XZQ991", "17 milliseconds"), (180, "Baseline", "42 milliseconds")]:
            page.insert_text((60, y), model, fontsize=10)
            page.insert_text((260, y), latency, fontsize=10)
        document.save(path)
    text = next(iter_pdf_pages(path)).text
    assert "|" in text
    row = next(line for line in text.splitlines() if "XZQ991" in line)
    assert "17 milliseconds" in row


def test_failed_mid_batch_replacement_removes_staged_vectors(store, monkeypatch):
    store.index_document("paper-a", "old", chunks("A quasar is visible in the old observations."))
    original = store.embeddings.embed_documents
    calls = []
    def fail_second_batch(texts, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("second batch failed")
        return original(texts, **kwargs)
    monkeypatch.setattr(store.embeddings, "embed_documents", fail_second_batch)
    with pytest.raises(RuntimeError, match="second batch"):
        store.index_document("paper-a", "new", chunks("The replacement detector measures a pulsar. " * 2200))
    assert len(calls) == 2
    assert store.get_collection_count() == 1
    assert store.index.matches("paper-a", "old")


def test_postgres_migrates_old_sidecar_once_without_reset_resurrection(store, tmp_path):
    import sqlite3
    import json
    path=tmp_path/'legacy.sqlite3'
    meta={'title':'Legacy Study','arxiv_id':'legacy','pipeline_version':'page-parent-child-v1','parent_id':'old-parent','chunk_id':'old-child'}
    with sqlite3.connect(path) as db:
        db.executescript('''CREATE TABLE documents(id TEXT,revision TEXT);
            CREATE TABLE parents(id TEXT,document_id TEXT,content TEXT);
            CREATE TABLE chunks(id TEXT,document_id TEXT,parent_id TEXT,content TEXT,metadata TEXT);''')
        db.execute('INSERT INTO documents VALUES (?,?)',('legacy','v1'))
        db.execute('INSERT INTO parents VALUES (?,?,?)',('old-parent','legacy','The XZQ991 latency is 17 milliseconds. Full parent passage.'))
        db.execute('INSERT INTO chunks VALUES (?,?,?,?,?)',('old-child','legacy','old-parent','XZQ991 latency is 17 milliseconds.',json.dumps(meta)))
    assert store.index.migrate_sqlite(path) == 1
    assert store.index.get_many(['old-child'])['old-child']['parent_content'].endswith('Full parent passage.')
    assert store.index.search('XZQ991',3)
    assert store.index.migrate_sqlite(path) == 0
    store.index.clear()
    assert store.index.migrate_sqlite(path) == 0
    assert not store.index.search('XZQ991',3)


def test_staging_parse_failure_rolls_back_invisible_rows(store):
    def broken():
        yield {'content':'partial evidence','metadata':{'title':'Broken'}}
        raise ValueError('page parsing failed')
    with pytest.raises(ValueError,match='page parsing'):
        store.index_document('broken','v1',broken())
    assert not store.index.contains_documents(['broken'])
    with store.index.pool.connection() as db:
        count=db.execute('SELECT count(*) AS n FROM rag_runs WHERE collection=%s',(store.index.collection,)).fetchone()['n']
    assert count == 0


def test_postgres_namespace_isolates_collections(store):
    from app.services.research.document_index import DocumentIndex
    store.index_document('paper-a','one',chunks('Measured quasar evidence for collection isolation.'))
    other=DocumentIndex(store.index.collection + '-other')
    assert not other.search('quasar',5)
    assert not other.contains_documents(['paper-a'])


def test_lost_activation_acknowledgement_cannot_delete_committed_vectors(store, monkeypatch):
    original=store.index.activate
    def committed_then_disconnected(stage):
        original(stage)
        raise OSError('lost commit acknowledgement')
    monkeypatch.setattr(store.index,'activate',committed_then_disconnected)
    with pytest.raises(OSError,match='acknowledgement'):
        store.index_document('paper-a','v1',chunks('The committed XZQ991 latency is 17 milliseconds.'))
    assert store.index.matches('paper-a','v1')
    assert store.get_collection_count() == 1
    assert store.similarity_search('XZQ991')
