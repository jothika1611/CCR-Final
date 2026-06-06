import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class AgentConfig(BaseSettings):
    # Chroma DB settings
    chroma_db_path: str = "output/chroma_db"
    chroma_collection: str = "ccr_vault"
    
    # Text embedding settings
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    
    # Platform settings
    env: str = "development"
    log_level: str = "info"
    
    # LLM advisor configurations
    groq_api_key: Optional[str] = None
    groq_model: str = "llama-3.1-8b-instant"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False
    )

settings = AgentConfig()
