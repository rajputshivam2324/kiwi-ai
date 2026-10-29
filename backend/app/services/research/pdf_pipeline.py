"""Stream PDFs to page/section-aware parent-child chunks, with provenance."""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
import hashlib
from pathlib import Path
import re
import tempfile
import unicodedata

import httpx
import pymupdf
import pymupdf4llm
import tiktoken
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import get_settings
from app.services.observability import observation

PIPELINE_VERSION = "page-parent-child-v1"


class PDFError(ValueError):
    pass


@dataclass(frozen=True)
class PDFPage:
    number: int
    text: str
    extraction: str = "layout"


@lru_cache(maxsize=1)
def tokenizer():
    return tiktoken.get_encoding("cl100k_base")


def token_count(text: str) -> int:
    return len(tokenizer().encode(text, disallowed_special=()))


def truncate_tokens(text: str, budget: int) -> str:
    return tokenizer().decode(tokenizer().encode(text, disallowed_special=())[:max(0, budget)])


def split_text(text: str, size: int, overlap: int = 0) -> list[str]:
    if not 0 <= overlap < size:
        raise ValueError("Chunk overlap must be >= 0 and smaller than chunk size")
    splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name="cl100k_base", chunk_size=size, chunk_overlap=overlap,
        disallowed_special=(), separators=["\n\n", "\n", ". ", " ", ""],
    )
    return splitter.split_text(text)


@contextmanager
def downloaded_pdf(url: str):
    """Spool to disk and enforce size while downloading, including chunked HTTP."""
    settings = get_settings()
    with observation("research.pdf.download") as span, tempfile.TemporaryDirectory(prefix="kiwi-pdf-") as temp:
        target = Path(temp) / "document.pdf"
        digest = hashlib.sha256()
        length = 0
        with httpx.stream("GET", url, follow_redirects=True, timeout=60,
                          headers={"User-Agent": "KiwiAI-Research/1.0"}) as response:
            response.raise_for_status()
            if int(response.headers.get("content-length", "0")) > settings.rag_max_pdf_bytes:
                raise PDFError("PDF exceeds RAG_MAX_PDF_BYTES")
            with target.open("wb") as output:
                for block in response.iter_bytes(64 * 1024):
                    length += len(block)
                    if length > settings.rag_max_pdf_bytes:
                        raise PDFError("PDF exceeds RAG_MAX_PDF_BYTES")
                    output.write(block)
                    digest.update(block)
        with target.open("rb") as handle:
            if b"%PDF-" not in handle.read(1024):
                raise PDFError("Response is not a PDF")
        span.update(metadata={"bytes": length, "sha256": digest.hexdigest()})
        yield target, digest.hexdigest()


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("\x00", "").replace("\u00ad", "")
    # Join line-wrap hyphenation, preserving ordinary compound words.
    text = re.sub(r"(?<=[a-z])-\n(?=[a-z])", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _margin_key(line: str) -> str:
    return re.sub(r"\d+", "#", line.strip()).casefold()


def iter_pdf_pages(path: str | Path):
    settings = get_settings()
    with observation("research.pdf.extract") as span, pymupdf.open(str(path)) as document:
        if document.needs_pass:
            raise PDFError("Encrypted PDFs require an unprotected copy")
        if len(document) > settings.rag_max_pdf_pages:
            raise PDFError("PDF exceeds RAG_MAX_PDF_PAGES")
        if not len(document):
            raise PDFError("PDF has no pages")
        # Sample throughout a long document; do not materialize all its pages.
        sampled = sorted({round(i * (len(document) - 1) / min(11, max(1, len(document) - 1)))
                          for i in range(min(12, len(document)))})
        margins = Counter()
        for number in sampled:
            page = document[number]
            edge_lines = set()
            for block in page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]:
                for line in block.get("lines", []):
                    if line["bbox"][1] < page.rect.height * .08 or line["bbox"][3] > page.rect.height * .92:
                        text = "".join(span["text"] for span in line["spans"])
                        if text.strip():
                            edge_lines.add(_margin_key(text))
            margins.update(edge_lines)
        repeated = {line for line, count in margins.items() if count >= max(3, len(sampled) * .6)}
        # Without this, to_markdown re-scans every page for font statistics on
        # every call, making page-by-page extraction quadratic in PDF length.
        headers = pymupdf4llm.IdentifyHeaders(document, pages=sampled)
        ocr_pages = 0
        readable_pages = 0
        for number, page in enumerate(document, 1):
            native = page.get_text("text").strip()
            extraction = "layout"
            if not native and not page.get_images() and not page.get_drawings():
                continue  # A truly blank separator page is not an extraction error.
            if len(re.sub(r"\W", "", native)) < 20 and (page.get_images() or page.get_drawings()):
                # Silently skipping scanned pages gives a misleadingly complete index.
                if not settings.rag_ocr_enabled:
                    raise PDFError(f"Page {number} has insufficient text; enable RAG_OCR_ENABLED and install Tesseract")
                try:
                    textpage = page.get_textpage_ocr(language=settings.rag_ocr_language, full=True, dpi=150)
                    text = page.get_text("text", textpage=textpage, sort=True)
                except Exception as error:
                    raise PDFError(f"OCR failed on page {number}; check Tesseract language data") from error
                if len(re.sub(r"\W", "", text)) < 20:
                    raise PDFError(f"Page {number} remains unreadable after OCR")
                extraction = "ocr"
                ocr_pages += 1
            else:
                chunks = pymupdf4llm.to_markdown(document, pages=[number - 1], hdr_info=headers, page_chunks=True,
                                                show_progress=False)
                text = chunks[0]["text"]
            lines = text.splitlines()
            # Only remove repeated margin lines near page edges.
            text = "\n".join(line for index, line in enumerate(lines)
                             if not ((index < 4 or index >= len(lines) - 4)
                                     and _margin_key(line.strip("# *")) in repeated))
            text = _normalize(text)
            if text:
                readable_pages += 1
                yield PDFPage(number, text, extraction)
        if not readable_pages:
            raise PDFError("PDF has no readable content")
        span.update(metadata={"pages": len(document), "ocr_pages": ocr_pages})


def iter_chunks(pages, metadata: dict):
    """Small embedding children point at larger, bounded generation parents.

    Page boundaries remain explicit. Heading paths carry across pages, so a
    continuation retains its section without flattening the complete PDF.
    """
    settings = get_settings()
    heading_path: dict[int, str] = {}
    index = 0
    for page in pages:
        parts = re.split(r"(?m)^(#{1,6})\s+(.+?)\s*$", page.text)
        sections = []
        if parts[0].strip():
            sections.append((" > ".join(heading_path.values()), parts[0].strip()))
        for i in range(1, len(parts), 3):
            level = len(parts[i])
            heading_path = {key: value for key, value in heading_path.items() if key < level}
            heading_path[level] = parts[i + 1].strip()
            # Headings live in metadata/context headers; avoid orphan chunks
            # containing only a heading before a long body paragraph.
            body = parts[i + 2].strip() or parts[i + 1].strip()
            sections.append((" > ".join(heading_path.values()), body))
        for section, text in sections:
            for parent_number, parent in enumerate(split_text(text, settings.rag_parent_tokens)):
                parent_key = hashlib.sha256(f"{page.number}:{section}:{parent_number}:{parent}".encode()).hexdigest()[:24]
                for child in split_text(parent, settings.rag_child_tokens, settings.rag_child_overlap):
                    yield {
                        "content": child,
                        "parent_content": parent,
                        "metadata": {
                            **metadata, "page_start": page.number, "page_end": page.number,
                            "section": section, "parent_id": parent_key, "chunk_index": index,
                            "chunk_type": "full_text", "extraction": page.extraction,
                            "pipeline_version": PIPELINE_VERSION, "token_count": token_count(child),
                        },
                    }
                    index += 1
