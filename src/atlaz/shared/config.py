"""Pipeline-wide runtime configuration (LLD Section 10.1, 13.1).

All configuration is environment-driven so the same code runs against a
mock LLM / no HITL in CI and against a real provider + reviewer in a demo,
with no code changes -- only a different `.env`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(slots=True)
class LLMConfig:
    provider: str = "mock"  # "anthropic" | "openai" | "azure" | "custom" | "mock"
    api_key: str | None = None
    base_url: str | None = None
    model: str = "mock-model"
    timeout_seconds: float = 60.0
    # Azure OpenAI-specific (only used when provider == "azure")
    azure_endpoint: str | None = None
    azure_deployment: str | None = None
    azure_api_version: str | None = None

    @classmethod
    def from_env(cls) -> LLMConfig:
        provider = os.getenv("LLM_PROVIDER", "mock").strip().lower()
        api_key = os.getenv("LLM_API_KEY") or None
        model = os.getenv("LLM_MODEL", "mock-model")
        if provider == "azure":
            api_key = os.getenv("AZURE_OPENAI_API_KEY") or api_key
            model = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME") or model
        return cls(
            provider=provider,
            api_key=api_key,
            base_url=os.getenv("LLM_BASE_URL") or None,
            model=model,
            timeout_seconds=_float_env("LLM_TIMEOUT_SECONDS", 60.0),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT") or None,
            azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME") or None,
            azure_api_version=os.getenv("AZURE_OPENAI_API_VERSION") or None,
        )


@dataclass(slots=True)
class Neo4jConfig:
    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: str = "password"
    database: str = "neo4j"

    @classmethod
    def from_env(cls) -> Neo4jConfig:
        return cls(
            uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            user=os.getenv("NEO4J_USER", "neo4j"),
            password=os.getenv("NEO4J_PASSWORD", "password"),
            database=os.getenv("NEO4J_DATABASE", "neo4j"),
        )


@dataclass(slots=True)
class CeleryConfig:
    broker_url: str = "redis://localhost:6379/0"
    result_backend: str = "redis://localhost:6379/1"

    @classmethod
    def from_env(cls) -> CeleryConfig:
        return cls(
            broker_url=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
            result_backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1"),
        )


@dataclass(slots=True)
class DatabaseConfig:
    """Audit database (Postgres). `admin_url` is only used by `atlaz db init`
    to create the `atlaz` database itself -- CREATE DATABASE cannot run
    inside a transaction against the database being created, so it connects
    to a database that already exists (the server's default `postgres`)."""

    url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/atlaz"
    admin_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/postgres"
    schema: str = "atlaz"

    @classmethod
    def from_env(cls) -> DatabaseConfig:
        return cls(
            url=os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/atlaz"),
            admin_url=os.getenv(
                "ADMIN_DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/postgres"
            ),
            schema=os.getenv("DB_SCHEMA", "atlaz"),
        )


@dataclass(slots=True)
class GuidelineStoreConfig:
    """Local vector store of enterprise coding/architecture/security
    guidelines the enhancement flow's code-modification step is instructed
    to follow. Mirrors `LLMConfig`'s "mock by default, real when configured"
    shape: `enabled=False` (or a missing `pymilvus` install) means the
    enhancement flow simply runs without guideline retrieval rather than
    failing, exactly like every other optional collaborator in this system."""

    enabled: bool = True
    db_path: str = ".atlaz/guidelines.db"
    collection_name: str = "enterprise_guidelines"

    @classmethod
    def from_env(cls) -> GuidelineStoreConfig:
        return cls(
            enabled=_bool_env("GUIDELINE_STORE_ENABLED", True),
            db_path=os.getenv("GUIDELINE_STORE_DB_PATH", ".atlaz/guidelines.db"),
            collection_name=os.getenv("GUIDELINE_STORE_COLLECTION", "enterprise_guidelines"),
        )


@dataclass(slots=True)
class QdrantConfig:
    """Vector index (LLD Section 10, 14.3) -- candidate retrieval only, per
    the user's explicit choice of Qdrant over a Neo4j-native vector index.
    `enabled=False` (the same "optional collaborator" shape as
    `GuidelineStoreConfig`) makes `write_vector_index` a no-op rather than
    failing when Qdrant isn't reachable."""

    enabled: bool = True
    url: str = "http://localhost:6333"
    api_key: str | None = None
    collection_prefix: str = "atlaz"

    @classmethod
    def from_env(cls) -> QdrantConfig:
        return cls(
            enabled=_bool_env("QDRANT_ENABLED", True),
            url=os.getenv("QDRANT_URL", "http://localhost:6333"),
            api_key=os.getenv("QDRANT_API_KEY") or None,
            collection_prefix=os.getenv("QDRANT_COLLECTION_PREFIX", "atlaz"),
        )


@dataclass(slots=True)
class ApiConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    base_url: str = "http://localhost:8000"  # what Streamlit's "Start Run" page calls

    @classmethod
    def from_env(cls) -> ApiConfig:
        port_raw = os.getenv("API_PORT", "8000")
        try:
            port = int(port_raw)
        except ValueError:
            port = 8000
        return cls(
            host=os.getenv("API_HOST", "0.0.0.0"),
            port=port,
            base_url=os.getenv("API_BASE_URL", "http://localhost:8000"),
        )


@dataclass(slots=True)
class PipelineConfig:
    """Corresponds directly to LLD Section 10.1's PipelineConfig."""

    hitl_enabled: bool = True
    confidence_threshold: float = 0.6
    ignore_dirs: tuple[str, ...] = (
        ".git",
        "node_modules",
        "__pycache__",
        "dist",
        "build",
        ".venv",
        "venv",
        ".idea",
        ".mypy_cache",
        ".pytest_cache",
        "site-packages",
    )
    checkpoint_db_path: Path = field(default_factory=lambda: Path(".atlaz/checkpoints.sqlite"))
    llm: LLMConfig = field(default_factory=LLMConfig)
    neo4j: Neo4jConfig = field(default_factory=Neo4jConfig)
    qdrant: QdrantConfig = field(default_factory=QdrantConfig)
    celery: CeleryConfig = field(default_factory=CeleryConfig)
    api: ApiConfig = field(default_factory=ApiConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    guideline_store: GuidelineStoreConfig = field(default_factory=GuidelineStoreConfig)
    capability_registry_path: Path | None = None

    @classmethod
    def from_env(cls, env_file: str | Path | None = ".env") -> PipelineConfig:
        if env_file is not None and Path(env_file).exists():
            load_dotenv(env_file, override=False)
        else:
            load_dotenv(override=False)

        registry_path_raw = os.getenv("CAPABILITY_REGISTRY_PATH")
        return cls(
            hitl_enabled=_bool_env("HITL_ENABLED", True),
            confidence_threshold=_float_env("CONFIDENCE_THRESHOLD", 0.6),
            checkpoint_db_path=Path(os.getenv("CHECKPOINT_DB_PATH", ".atlaz/checkpoints.sqlite")),
            llm=LLMConfig.from_env(),
            neo4j=Neo4jConfig.from_env(),
            qdrant=QdrantConfig.from_env(),
            celery=CeleryConfig.from_env(),
            api=ApiConfig.from_env(),
            database=DatabaseConfig.from_env(),
            guideline_store=GuidelineStoreConfig.from_env(),
            capability_registry_path=Path(registry_path_raw) if registry_path_raw else None,
        )
