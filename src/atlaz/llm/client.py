"""LLMClient interface (LLD Section 13.1).

Every agent that needs LLM synthesis depends only on this Protocol, never on
a provider SDK directly. Provider selection is a config value
(`LLM_PROVIDER=anthropic|openai|azure|custom|mock`), not a code dependency -- this
is what lets the same agent code run against a real model in production and
a deterministic mock in tests/CI.
"""

from __future__ import annotations

import json
import logging
from typing import Protocol, runtime_checkable

from atlaz.shared.config import LLMConfig

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Raised when the underlying provider call fails after retries."""


@runtime_checkable
class LLMClient(Protocol):
    def complete(self, prompt: str, schema: dict | None = None) -> str:
        """Return raw text completion. If `schema` is given, the provider is
        instructed to return JSON conforming to it; callers are responsible
        for parsing (see `complete_json`)."""
        ...


class BaseLLMClient:
    """Shared JSON-completion helper so agents call `complete_json` uniformly
    regardless of which concrete provider is behind `LLMClient`."""

    def complete(self, prompt: str, schema: dict | None = None) -> str:  # pragma: no cover
        raise NotImplementedError

    def complete_json(self, prompt: str, schema: dict | None = None) -> dict:
        raw = self.complete(prompt, schema=schema)
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            start, end = raw.find("{"), raw.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(raw[start : end + 1])
                except json.JSONDecodeError:
                    pass
            logger.warning("LLM response was not valid JSON; returning empty dict. raw=%r", raw[:200])
            return {}


class MockLLMClient(BaseLLMClient):
    """Deterministic, offline stand-in used as the default provider and in
    every unit test. Never makes a network call.

    Behaviour is intentionally simple and reproducible: it echoes back a
    plausible-shaped response derived from the prompt so callers exercising
    the "LLM assisted labeling" code paths get *something* structurally
    valid without needing real credentials.
    """

    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or LLMConfig(provider="mock")

    def complete(self, prompt: str, schema: dict | None = None) -> str:
        if schema is not None:
            return json.dumps(self._mock_json_for(prompt, schema))
        return f"[mock-llm] {prompt.strip().splitlines()[0][:120]}"

    def _mock_json_for(self, prompt: str, schema: dict) -> dict:
        result: dict = {}
        properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
        for key, spec in properties.items():
            ptype = spec.get("type") if isinstance(spec, dict) else None
            if ptype == "number":
                result[key] = 0.5
            elif ptype == "integer":
                result[key] = 1
            elif ptype == "boolean":
                result[key] = False
            elif ptype == "array":
                result[key] = []
            else:
                result[key] = f"mock-{key}"
        return result


class AnthropicLLMClient(BaseLLMClient):
    """Thin wrapper around the Anthropic Messages API."""

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self._client = None  # lazily constructed so importing this module never requires the SDK

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover
                raise LLMError(
                    "anthropic package is not installed; run `pip install anthropic` "
                    "or set LLM_PROVIDER=mock"
                ) from exc
            kwargs = {"api_key": self.config.api_key}
            if self.config.base_url:
                kwargs["base_url"] = self.config.base_url
            self._client = anthropic.Anthropic(**kwargs)
        return self._client

    def complete(self, prompt: str, schema: dict | None = None) -> str:
        client = self._get_client()
        system = None
        if schema is not None:
            system = (
                "Respond with ONLY a single JSON object matching this schema, "
                f"no prose, no markdown fences: {json.dumps(schema)}"
            )
        try:
            response = client.messages.create(
                model=self.config.model,
                max_tokens=2048,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                timeout=self.config.timeout_seconds,
            )
        except Exception as exc:
            raise LLMError(f"Anthropic completion failed: {exc}") from exc
        return "".join(block.text for block in response.content if hasattr(block, "text"))


class OpenAICompatibleLLMClient(BaseLLMClient):
    """Wrapper for the OpenAI Chat Completions API and any OpenAI-compatible
    endpoint (self-hosted gateway, Azure OpenAI, etc.) reached via
    `LLM_BASE_URL`. Used for both `LLM_PROVIDER=openai` and `=custom`."""

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import openai
            except ImportError as exc:  # pragma: no cover
                raise LLMError(
                    "openai package is not installed; run `pip install openai` "
                    "or set LLM_PROVIDER=mock"
                ) from exc
            kwargs = {"api_key": self.config.api_key or "unused"}
            if self.config.base_url:
                kwargs["base_url"] = self.config.base_url
            self._client = openai.OpenAI(**kwargs)
        return self._client

    def complete(self, prompt: str, schema: dict | None = None) -> str:
        client = self._get_client()
        messages = [{"role": "user", "content": prompt}]
        if schema is not None:
            messages.insert(
                0,
                {
                    "role": "system",
                    "content": (
                        "Respond with ONLY a single JSON object matching this schema, "
                        f"no prose, no markdown fences: {json.dumps(schema)}"
                    ),
                },
            )
        try:
            response = client.chat.completions.create(
                model=self.config.model,
                messages=messages,
                timeout=self.config.timeout_seconds,
            )
        except Exception as exc:
            raise LLMError(f"OpenAI-compatible completion failed: {exc}") from exc
        return response.choices[0].message.content or ""


class AzureOpenAILLMClient(BaseLLMClient):
    """Wrapper for Azure OpenAI's Chat Completions API. Uses the deployment
    name (not the base model name) as `model`, per Azure's API shape."""

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import openai
            except ImportError as exc:  # pragma: no cover
                raise LLMError(
                    "openai package is not installed; run `pip install openai` "
                    "or set LLM_PROVIDER=mock"
                ) from exc
            if not self.config.azure_endpoint:
                raise LLMError("AZURE_OPENAI_ENDPOINT is required when LLM_PROVIDER=azure")
            self._client = openai.AzureOpenAI(
                api_key=self.config.api_key,
                azure_endpoint=self.config.azure_endpoint,
                api_version=self.config.azure_api_version or "2024-12-01-preview",
            )
        return self._client

    def complete(self, prompt: str, schema: dict | None = None) -> str:
        client = self._get_client()
        deployment = self.config.azure_deployment or self.config.model
        messages = [{"role": "user", "content": prompt}]
        if schema is not None:
            messages.insert(
                0,
                {
                    "role": "system",
                    "content": (
                        "Respond with ONLY a single JSON object matching this schema, "
                        f"no prose, no markdown fences: {json.dumps(schema)}"
                    ),
                },
            )
        try:
            response = client.chat.completions.create(
                model=deployment,
                messages=messages,
                timeout=self.config.timeout_seconds,
            )
        except Exception as exc:
            raise LLMError(f"Azure OpenAI completion failed: {exc}") from exc
        return response.choices[0].message.content or ""


def build_llm_client(config: LLMConfig | None = None) -> BaseLLMClient:
    """Factory selecting the concrete `LLMClient` from config alone."""
    config = config or LLMConfig()
    provider = config.provider.lower().strip()
    if provider == "anthropic":
        return AnthropicLLMClient(config)
    if provider in {"openai", "custom"}:
        return OpenAICompatibleLLMClient(config)
    if provider == "azure":
        return AzureOpenAILLMClient(config)
    if provider == "mock":
        return MockLLMClient(config)
    raise ValueError(f"Unknown LLM_PROVIDER: {config.provider!r}")
