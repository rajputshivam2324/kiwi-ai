import arxiv
import logging
from typing import List, Dict, Any
from pypdf import PdfReader
import io
import requests
from datetime import datetime

logger = logging.getLogger(__name__)


def download_pdf_text(pdf_url: str) -> str:
    """Download and extract text from arXiv PDF"""
    try:
        logger.info(f"Downloading PDF from {pdf_url}")
        response = requests.get(pdf_url, timeout=30)
        response.raise_for_status()
        
        # Read PDF
        pdf_file = io.BytesIO(response.content)
        reader = PdfReader(pdf_file)
        
        # Extract text from all pages
        text_parts = []
        for page in reader.pages:
            text_parts.append(page.extract_text())
        
        full_text = "\n\n".join(text_parts)
        logger.info(f"Extracted {len(full_text)} characters from PDF")
        return full_text
        
    except Exception as e:
        logger.error(f"Error downloading/parsing PDF: {e}")
        return ""


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> List[str]:
    """Split text into overlapping chunks"""
    if not text:
        return []
    
    chunks = []
    start = 0
    text_length = len(text)
    
    while start < text_length:
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        start += (chunk_size - overlap)
    
    logger.info(f"Created {len(chunks)} chunks from text")
    return chunks


def search_arxiv(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """Search arXiv and return paper metadata"""
    try:
        logger.info(f"Searching arXiv: query='{query}', max_results={max_results}")
        
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.Relevance
        )
        
        papers = []
        for result in search.results():
            paper = {
                "arxiv_id": result.entry_id.split("/")[-1],
                "title": result.title,
                "authors": [author.name for author in result.authors],
                "abstract": result.summary,
                "pdf_url": result.pdf_url,
                "published": result.published.strftime("%Y-%m-%d"),
                "categories": result.categories,
                "primary_category": result.primary_category
            }
            papers.append(paper)
            logger.info(f"Found paper: {paper['arxiv_id']} - {paper['title'][:50]}...")
        
        return papers
        
    except Exception as e:
        logger.error(f"Error searching arXiv: {e}")
        raise


def ingest_papers(
    query: str,
    max_results: int,
    vectorstore,
    include_full_text: bool = True
) -> Dict[str, Any]:
    """
    Main ingestion function
    
    Args:
        query: arXiv search query
        max_results: Maximum number of papers to fetch
        vectorstore: VectorStoreService instance
        include_full_text: If True, download and chunk full PDFs (slower but more comprehensive)
    """
    try:
        # Search arXiv
        papers = search_arxiv(query, max_results)
        
        if not papers:
            logger.warning("No papers found for query")
            return {
                "documents_added": 0,
                "arxiv_ids": []
            }
        
        # Prepare documents for vector store
        texts = []
        metadatas = []
        ids = []
        
        for paper in papers:
            arxiv_id = paper["arxiv_id"]
            
            # Create metadata
            metadata = {
                "arxiv_id": arxiv_id,
                "title": paper["title"],
                "authors": ", ".join(paper["authors"]),
                "published": paper["published"],
                "categories": ", ".join(paper["categories"]),
                "pdf_url": paper["pdf_url"],
                "source": "arxiv"
            }
            
            # Add abstract as first chunk
            texts.append(paper["abstract"])
            metadatas.append({**metadata, "chunk_type": "abstract"})
            ids.append(f"{arxiv_id}_abstract")
            
            # Optionally download and chunk full PDF
            if include_full_text:
                logger.info(f"Downloading full text for {arxiv_id}")
                full_text = download_pdf_text(paper["pdf_url"])
                
                if full_text:
                    chunks = chunk_text(full_text, chunk_size=1000, overlap=200)
                    
                    for i, chunk in enumerate(chunks):
                        texts.append(chunk)
                        metadatas.append({**metadata, "chunk_type": "full_text", "chunk_index": i})
                        ids.append(f"{arxiv_id}_chunk_{i}")
            
            logger.info(f"Prepared {len(texts)} text chunks for {arxiv_id}")
        
        # Add to vector store
        logger.info(f"Adding {len(texts)} documents to vector store")
        vectorstore.add_documents(
            texts=texts,
            metadatas=metadatas,
            ids=ids
        )
        
        arxiv_ids = [p["arxiv_id"] for p in papers]
        logger.info(f"Successfully ingested {len(papers)} papers")
        
        return {
            "documents_added": len(texts),
            "arxiv_ids": arxiv_ids
        }
        
    except Exception as e:
        logger.error(f"Error in ingest_papers: {e}")
        raise


if __name__ == "__main__":
    # Test script
    from app.services.vectorstore import get_vectorstore_service
    
    logging.basicConfig(level=logging.INFO)
    
    vectorstore = get_vectorstore_service()
    
    result = ingest_papers(
        query="attention is all you need",
        max_results=3,
        vectorstore=vectorstore,
        include_full_text=False  # Set to True for full PDF ingestion
    )
    
    print(f"\nIngestion complete!")
    print(f"Documents added: {result['documents_added']}")
    print(f"arXiv IDs: {result['arxiv_ids']}")