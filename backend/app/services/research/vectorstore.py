import chromadb
from chromadb.config import Settings as ChromaSettings
from langchain_community.vectorstores import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from app.config import get_settings
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)


class VectorStoreService:
    def __init__(self):
        self.settings = get_settings()
        
        # Initialize Google Gemini embeddings
        logger.info(f"Initializing Gemini embeddings: {self.settings.embedding_model}")
        self.embeddings = GoogleGenerativeAIEmbeddings(
            model=self.settings.embedding_model,
            google_api_key=self.settings.google_api_key,
        )
        
        # Initialize ChromaDB client with SQLite
        self.chroma_client = chromadb.PersistentClient(
            path=self.settings.chroma_db_path,
            settings=ChromaSettings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )
        
        # Initialize LangChain Chroma wrapper
        self.vectorstore = Chroma(
            client=self.chroma_client,
            collection_name=self.settings.collection_name,
            embedding_function=self.embeddings,
        )
        
        logger.info(f"ChromaDB initialized at {self.settings.chroma_db_path}")
    
    def add_documents(
        self,
        texts: List[str],
        metadatas: List[Dict[str, Any]],
        ids: List[str]
    ) -> None:
        """Add documents to vector store"""
        try:
            logger.info(f"Adding {len(texts)} documents to vector store with Gemini embeddings...")
            self.vectorstore.add_texts(
                texts=texts,
                metadatas=metadatas,
                ids=ids
            )
            logger.info(f"Successfully added {len(texts)} documents")
        except Exception as e:
            logger.error(f"Error adding documents: {e}")
            raise
    
    def similarity_search(
        self,
        query: str,
        k: int = 3,
        filter: Dict[str, Any] = None
    ) -> List[Dict[str, Any]]:
        """Search for similar documents"""
        try:
            logger.info(f"Searching with Gemini embeddings: '{query[:50]}...'")
            results = self.vectorstore.similarity_search_with_score(
                query=query,
                k=k,
                filter=filter
            )
            
            documents = []
            for doc, score in results:
                documents.append({
                    "content": doc.page_content,
                    "metadata": doc.metadata,
                    "score": float(score)
                })
            
            logger.info(f"Found {len(documents)} relevant documents")
            return documents
        except Exception as e:
            logger.error(f"Error searching documents: {e}")
            raise
    
    def get_collection_count(self) -> int:
        """Get total number of documents in collection"""
        try:
            collection = self.chroma_client.get_collection(
                name=self.settings.collection_name
            )
            return collection.count()
        except Exception as e:
            logger.warning(f"Collection doesn't exist yet: {e}")
            return 0
    
    def reset_collection(self) -> None:
        """Delete and recreate collection (use with caution!)"""
        try:
            self.chroma_client.delete_collection(
                name=self.settings.collection_name
            )
            logger.info(f"Collection {self.settings.collection_name} reset")
        except Exception as e:
            logger.warning(f"Error resetting collection: {e}")


# Singleton instance
_vectorstore_service = None

def get_vectorstore_service() -> VectorStoreService:
    global _vectorstore_service
    if _vectorstore_service is None:
        _vectorstore_service = VectorStoreService()
    return _vectorstore_service