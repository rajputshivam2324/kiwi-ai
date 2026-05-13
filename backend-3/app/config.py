from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, AliasChoices
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    # Google Gemini (chat / RAG LLM) — GOOGLE_API_KEY or GEMINI_API_KEY in .env
    google_api_key: str = Field(
        validation_alias=AliasChoices("GOOGLE_API_KEY", "GEMINI_API_KEY", "google_api_key"),
    )
    llm_model: str = "gemini-2.5-flash"

    # NVIDIA AI Endpoints (embeddings only)
    nvidia_api_key: str
    temperature: float = 0.6
    top_p: float = 0.9
    max_tokens: int = 4096
    
    # Embedding Config
    embedding_model: str = "nvidia/llama-3.2-nemoretriever-300m-embed-v1"
    embedding_truncate: str = "NONE"
    
    # Vector Store
    chroma_db_path: str = "./data/chroma_db"
    collection_name: str = "arxiv_papers"
    
    # Database
    database_url: str = "postgresql://kiwi:kiwi_secret_2024@localhost:5432/kiwi_ai"
    
    # API Config
    api_host: str = "0.0.0.0"
    api_port: int = 8000


@lru_cache()
def get_settings() -> Settings:
    return Settings()