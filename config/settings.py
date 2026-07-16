"""
Centralized configuration management using Pydantic Settings.
All environment variables are loaded and validated here.
"""

from functools import lru_cache
from typing import Optional

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Database configuration settings."""

    model_config = SettingsConfigDict(
        env_prefix="DB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    url: str = Field(
        default="",
        validation_alias=AliasChoices("DB_URL", "DATABASE_URL"),
        description="PostgreSQL connection URL (Supabase or local or Neon)",
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

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v:
            raise ValueError(
                "Database URL must be set via DB_URL or DATABASE_URL environment variable"
            )
        return v

    @property
    def is_remote(self) -> bool:
        """True for managed/remote Postgres (Neon, Supabase, any non-local host).

        Remote databases require TLS and benefit from connection resilience
        (``pool_pre_ping`` + recycle), because providers like Neon suspend idle
        connections (scale-to-zero) and drop them from under the pool.
        """
        from urllib.parse import urlparse

        host = (urlparse(self.url).hostname or "").lower()
        return host not in ("", "localhost", "127.0.0.1", "::1")


class EmbeddingSettings(BaseSettings):
    """Embedding model configuration."""

    model_config = SettingsConfigDict(
        env_prefix="EMBEDDING_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    voyage_api_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("EMBEDDING_VOYAGE_API_KEY", "VOYAGE_API_KEY"),
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


class ParsingSettings(BaseSettings):
    """Document parsing configuration."""

    model_config = SettingsConfigDict(
        env_prefix="PARSING_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    llamaparse_api_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("PARSING_LLAMAPARSE_API_KEY", "LLAMAPARSE_API"),
        description="LlamaParse API key for PDF parsing",
    )
    high_res_ocr: bool = Field(
        default=True,
        description="Enable high resolution OCR for PDFs",
    )


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
    tiny_chunk_threshold: int = Field(
        default=50, description="Chunks under this size (characters) merge into their neighbor"
    )

    def model_post_init(self, __context) -> None:
        """Cross-field invariant, enforced where the fields live."""
        if self.max_size <= self.min_size:
            raise ValueError(
                f"chunking max_size ({self.max_size}) must be greater than "
                f"min_size ({self.min_size})"
            )


class LangfuseSettings(BaseSettings):
    """Langfuse tracing configuration."""

    model_config = SettingsConfigDict(
        env_prefix="LANGFUSE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    public_key: Optional[str] = Field(default=None, description="Langfuse public API key")
    secret_key: Optional[str] = Field(default=None, description="Langfuse secret API key")
    base_url: str = Field(
        default="https://cloud.langfuse.com",
        description="Langfuse API base URL",
    )
    tracing_enabled: bool = Field(default=True, description="Enable Langfuse tracing")
    tracing_environment: str = Field(
        default="development",
        description="Logical environment name for Langfuse traces",
    )
    release: Optional[str] = Field(default=None, description="App release or version label")

    @property
    def is_configured(self) -> bool:
        """Return True when enough configuration is present to send traces."""
        return bool(self.tracing_enabled and self.public_key and self.secret_key)


class LLMSettings(BaseSettings):
    """LLM provider configuration for retrieval and eval pipelines."""

    model_config = SettingsConfigDict(
        env_prefix="LLM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    provider: str = Field(
        default="groq",
        description="LLM provider: groq, ollama, or openai",
    )
    model: Optional[str] = Field(
        default=None,
        description="Override the provider's default model",
    )
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        validation_alias=AliasChoices("LLM_OLLAMA_BASE_URL", "OLLAMA_BASE_URL"),
        description="Base URL for a local Ollama server",
    )

    # Agent role→model routing (design: 2026-07-16-agentic-rag-v1). Format
    # "provider/model", e.g. LLM_ROLE_GRADER=groq/llama-3.1-8b-instant.
    role_interpreter: Optional[str] = Field(
        default=None, description="Model id for the query-interpreter role"
    )
    role_grader: Optional[str] = Field(
        default=None, description="Model id for the sufficiency-grader role"
    )
    role_answerer: Optional[str] = Field(
        default=None, description="Model id for the answer-generation role"
    )

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        allowed = ("groq", "ollama", "openai")
        normalized = v.lower().strip()
        if normalized not in allowed:
            raise ValueError(f"Unknown LLM_PROVIDER '{v}'. Must be one of: {list(allowed)}")
        return normalized

    @field_validator("role_interpreter", "role_grader", "role_answerer")
    @classmethod
    def validate_role_model_id(cls, v: Optional[str]) -> Optional[str]:
        # A bare model name (no provider prefix) would land off the fallback
        # ladder and silently get every rung as a fallback — fail loudly here.
        if v is None:
            return v
        normalized = v.strip()
        if "/" not in normalized:
            raise ValueError(
                f"Invalid role model id '{v}'. Expected 'provider/model' format, "
                "e.g. 'groq/llama-3.3-70b-versatile'."
            )
        return normalized


class VectorSettings(BaseSettings):
    """Vector store configuration."""

    model_config = SettingsConfigDict(
        env_prefix="VECTOR_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    collection_name: str = Field(
        default="buddhist_texts",
        description=(
            "Default vector store collection. Collections partition sources by type "
            "(e.g. buddhist_texts, talks, meditation_research, scientific_discussions); "
            "callers pass their own collection_name to route a resource elsewhere."
        ),
    )


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
    langfuse: LangfuseSettings = Field(default_factory=LangfuseSettings)
    vector: VectorSettings = Field(default_factory=VectorSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)

    @field_validator("debug", mode="before")
    @classmethod
    def validate_debug(cls, v):
        """Accept common environment-style debug aliases."""
        if isinstance(v, str):
            normalized = v.strip().lower()
            if normalized in {"release", "prod", "production"}:
                return False
            if normalized in {"debug", "dev", "development"}:
                return True
        return v


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.
    Uses lru_cache to ensure settings are only loaded once.
    """
    return Settings()
