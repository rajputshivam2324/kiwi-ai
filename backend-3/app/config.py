from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # NVIDIA AI Endpoints
    nvidia_api_key: str
    model_name: str = "moonshotai/kimi-k2-instruct-0905"
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
    
    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()