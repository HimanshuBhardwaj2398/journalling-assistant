"""
Centralized configuration management using Pydantic Settings.
All environment variables are loaded and validated here.
"""

from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Database configuration settings."""

    model_config = SettingsConfigDict(
        env_prefix="DB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    url: str = Field(
        default="",
        description="PostgreSQL connection URL (Supabase or local)",
    )
    pool_size: int = Field(
        default=10,
        description="Connection pool size (Supabase recommends 10)",
    )
    max_overflow: int = Field(
        default=20,
        description="Max overflow connections (Supabase recommends 20)",
    )
    pool_timeout: int = Field(
        default=30,
        description="Pool checkout timeout in seconds",
    )
    pool_recycle: int = Field(
        default=3600,
        description="Recycle connections after N seconds (1 hour)",
    )
    echo: bool = Field(default=False, description="Echo SQL queries (for debugging)")

    @field_validator("url", mode="before")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Also check DATABASE_URL for backward compatibility."""
        import os

        if not v:
            v = os.getenv("DATABASE_URL", "")
        if not v:
            raise ValueError(
                "Database URL must be set via DB_URL or DATABASE_URL environment variable"
            )
        return v

    @property
    def is_supabase(self) -> bool:
        """Check if using Supabase database."""
        return "supabase.com" in self.url or "supabase.co" in self.url


class EmbeddingSettings(BaseSettings):
    """Embedding model configuration."""

    model_config = SettingsConfigDict(
        env_prefix="EMBEDDING_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    voyage_api_key: Optional[str] = Field(
        default=None,
        description="Voyage AI API key for embeddings",
    )
    voyage_model: str = Field(
        default="voyage-3.5",
        description="Voyage AI model name",
    )
    huggingface_model: str = Field(
        default="BAAI/bge-small-en-v1.5",
        description="HuggingFace model for semantic chunking",
    )
    batch_size: int = Field(
        default=100,
        description="Batch size for embedding operations",
    )

    @field_validator("voyage_api_key", mode="before")
    @classmethod
    def validate_voyage_key(cls, v: Optional[str]) -> Optional[str]:
        """Also check VOYAGE_API_KEY for backward compatibility."""
        import os

        if not v:
            v = os.getenv("VOYAGE_API_KEY")
        return v


class ParsingSettings(BaseSettings):
    """Document parsing configuration."""

    model_config = SettingsConfigDict(
        env_prefix="PARSING_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llamaparse_api_key: Optional[str] = Field(
        default=None,
        description="LlamaParse API key for PDF parsing",
    )
    high_res_ocr: bool = Field(
        default=True,
        description="Enable high resolution OCR for PDFs",
    )

    @field_validator("llamaparse_api_key", mode="before")
    @classmethod
    def validate_llamaparse_key(cls, v: Optional[str]) -> Optional[str]:
        """Also check LLAMAPARSE_API for backward compatibility."""
        import os

        if not v:
            v = os.getenv("LLAMAPARSE_API")
        return v


class ChunkingSettings(BaseSettings):
    """Text chunking configuration."""

    model_config = SettingsConfigDict(
        env_prefix="CHUNKING_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    max_size: int = Field(default=2000, description="Maximum chunk size in characters")
    min_size: int = Field(default=700, description="Minimum chunk size in characters")
    max_header_level: int = Field(default=6, description="Maximum header level to split on")
    enable_semantic: bool = Field(default=True, description="Enable semantic chunking")
    enable_parallel: bool = Field(default=True, description="Enable parallel processing")
    max_workers: int = Field(default=4, description="Max worker threads for parallel processing")
    tiny_chunk_threshold: int = Field(default=50, description="Threshold for tiny chunks to merge")

    @field_validator("max_size", mode="after")
    @classmethod
    def validate_max_size(cls, v: int, info) -> int:
        """Ensure max_size > min_size."""
        # We can't access other fields directly in field_validator
        # This will be validated in Settings.__init__
        return v


class Settings(BaseSettings):
    """
    Root application settings.
    Loads configuration from environment variables and .env file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application settings
    environment: str = Field(default="development", description="Environment name")
    log_level: str = Field(default="INFO", description="Logging level")
    debug: bool = Field(default=False, description="Debug mode")

    # HuggingFace token (for some models)
    hf_token: Optional[str] = Field(default=None, description="HuggingFace API token")

    # Nested settings - loaded with their own prefixes
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    parsing: ParsingSettings = Field(default_factory=ParsingSettings)
    chunking: ChunkingSettings = Field(default_factory=ChunkingSettings)

    @field_validator("hf_token", mode="before")
    @classmethod
    def validate_hf_token(cls, v: Optional[str]) -> Optional[str]:
        """Also check HF_TOKEN for backward compatibility."""
        import os

        if not v:
            v = os.getenv("HF_TOKEN")
        return v

    def model_post_init(self, __context) -> None:
        """Validate settings after initialization."""
        if self.chunking.max_size <= self.chunking.min_size:
            raise ValueError(
                f"chunking.max_size ({self.chunking.max_size}) must be greater than "
                f"chunking.min_size ({self.chunking.min_size})"
            )


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.
    Uses lru_cache to ensure settings are only loaded once.
    """
    return Settings()


# Backward compatibility: expose commonly used settings as module-level variables
# These will be lazily loaded when accessed
def _get_db_url() -> str:
    return get_settings().database.url


def _get_voyage_api_key() -> Optional[str]:
    return get_settings().embedding.voyage_api_key


def _get_llamaparse_api() -> Optional[str]:
    return get_settings().parsing.llamaparse_api_key


def _get_hf_token() -> Optional[str]:
    return get_settings().hf_token
