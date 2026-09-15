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
    provider: str = "mock"  # "anthropic" | "openai" | "custom" | "mock"
    api_key: str | None = None
    base_url: str | None = None
    model: str = "mock-model"
    timeout_seconds: float = 60.0

    @classmethod
    def from_env(cls) -> LLMConfig:
        return cls(
            provider=os.getenv("LLM_PROVIDER", "mock").strip().lower(),
            api_key=os.getenv("LLM_API_KEY") or None,
            base_url=os.getenv("LLM_BASE_URL") or None,
            model=os.getenv("LLM_MODEL", "mock-model"),
            timeout_seconds=_float_env("LLM_TIMEOUT_SECONDS", 60.0),
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

    @classmethod
    def from_env(cls, env_file: str | Path | None = ".env") -> PipelineConfig:
        if env_file is not None and Path(env_file).exists():
            load_dotenv(env_file, override=False)
        else:
            load_dotenv(override=False)

        return cls(
            hitl_enabled=_bool_env("HITL_ENABLED", True),
            confidence_threshold=_float_env("CONFIDENCE_THRESHOLD", 0.6),
            checkpoint_db_path=Path(os.getenv("CHECKPOINT_DB_PATH", ".atlaz/checkpoints.sqlite")),
            llm=LLMConfig.from_env(),
            neo4j=Neo4jConfig.from_env(),
        )
