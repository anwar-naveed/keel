"""LLM Provider adapters - P1.4

Provider ABC: complete(system, messages, tools) ->
ProviderResponse{content, tool_calls, usage{tokens_in,tokens_out,cost_usd}}
Registry: {"mock","ollama","openai","anthropic"}
MockProvider: deterministic scripted responses from YAML
OllamaProvider: stdlib urllib POST to http://ollama:11434/api/chat (no SDK)
OpenAI/Anthropic: raise ProviderNotConfigured unless env key present; stdlib urllib
Cost table loaded from config/providers.json (env override KEEL_PROVIDERS_CONFIG).
"""

import json
import os
import time
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import yaml

from keel.config import ConfigError, load_providers_config


@dataclass
class Usage:
    """Token usage and cost."""
    tokens_in: int
    tokens_out: int
    cost_usd: float


@dataclass
class ProviderResponse:
    """Response from a provider."""
    content: str
    tool_calls: list[dict]
    usage: Usage


class ProviderError(Exception):
    """Base provider error."""
    pass


class ProviderNotFound(ProviderError):
    """Unknown provider name."""
    pass


class ProviderNotConfigured(ProviderError):
    """Provider needs configuration (API key)."""
    pass


class ScriptExhausted(ProviderError):
    """Mock provider script exhausted."""
    pass


class Provider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    def complete(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None,
    ) -> ProviderResponse:
        """Complete a chat request."""
        pass


def _load_provider_config(provider_name: str) -> dict:
    """Load config for a specific provider from providers.json."""
    try:
        config = load_providers_config()
        return config.get(provider_name, {})
    except ConfigError:
        # Return empty config if file not found - providers will use defaults/env
        return {}


class MockProvider(Provider):
    """Deterministic mock provider for testing."""

    def __init__(self, script_path: Path | str | None = None):
        self.script: list[dict] = []
        self.index = 0

        if script_path:
            self.load_script(script_path)

    def load_script(self, script_path: Path | str) -> None:
        """Load scripted responses from YAML file."""
        with open(script_path) as f:
            self.script = yaml.safe_load(f) or []
        self.index = 0

    def complete(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None,
    ) -> ProviderResponse:
        if self.index >= len(self.script):
            raise ScriptExhausted("Mock provider script exhausted")

        step = self.script[self.index]
        self.index += 1

        # Bomb hook (P1.9): optional per-step delay so durability tests can
        # SIGKILL the engine mid-provider-call, inside this sleep.
        delay = step.get("sleep", 0)
        if delay:
            time.sleep(float(delay))

        content = step.get("content", "")
        tool_calls = step.get("tool_calls", [])

        return ProviderResponse(
            content=content,
            tool_calls=tool_calls,
            usage=Usage(tokens_in=10, tokens_out=5, cost_usd=0.0),
        )


class OllamaProvider(Provider):
    """Ollama provider using stdlib urllib."""

    def __init__(self, base_url: str | None = None, model: str | None = None):
        config = _load_provider_config("ollama")
        self.base_url = (
            base_url
            or os.getenv("KEEL_OLLAMA_URL")
            or config.get("base_url", "http://ollama:11434")
        )
        self.model = (
            model
            or os.getenv("KEEL_OLLAMA_MODEL")
            or config.get("default_model", "llama3.1:8b")
        )
        self._cost_table = config.get("models", {})

    def complete(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None,
    ) -> ProviderResponse:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                *messages,
            ],
            "stream": False,
        }

        if tools:
            payload["tools"] = tools

        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode())

        content = result.get("message", {}).get("content", "")
        tool_calls = result.get("message", {}).get("tool_calls", [])

        return ProviderResponse(
            content=content,
            tool_calls=tool_calls,
            usage=Usage(tokens_in=0, tokens_out=0, cost_usd=0.0),
        )


class OpenAIProvider(Provider):
    """OpenAI provider using stdlib urllib."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ProviderNotConfigured("OPENAI_API_KEY not set")

        config = _load_provider_config("openai")
        self.model = (
            model
            or os.getenv("KEEL_OPENAI_MODEL")
            or config.get("default_model", "gpt-4o-mini")
        )
        self.base_url = (
            base_url
            or os.getenv("KEEL_OPENAI_BASE_URL")
            or config.get("base_url", "https://api.openai.com/v1")
        )
        self._cost_table = config.get("models", {})

    def _calculate_cost(self, tokens_in: int, tokens_out: int) -> float:
        """Calculate cost based on model pricing from config."""
        pricing = self._cost_table.get(self.model, {})
        if not pricing:
            # Unknown model - warn but don't crash
            import warnings

            warnings.warn(
                f"Unknown model '{self.model}' in cost table, cost will be 0.0",
                stacklevel=2,
            )
            return 0.0
        input_cost = pricing.get("input", 0.0)
        output_cost = pricing.get("output", 0.0)
        return (tokens_in / 1_000_000) * input_cost + (tokens_out / 1_000_000) * output_cost

    def complete(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None,
    ) -> ProviderResponse:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                *messages,
            ],
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode())

        choice = result["choices"][0]
        content = choice["message"].get("content", "") or ""
        tool_calls = choice["message"].get("tool_calls", [])
        usage = result.get("usage", {})

        tokens_in = usage.get("prompt_tokens", 0)
        tokens_out = usage.get("completion_tokens", 0)
        cost = self._calculate_cost(tokens_in, tokens_out)

        return ProviderResponse(
            content=content,
            tool_calls=tool_calls,
            usage=Usage(
                tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost
            ),
        )


class AnthropicProvider(Provider):
    """Anthropic provider using stdlib urllib."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ProviderNotConfigured("ANTHROPIC_API_KEY not set")

        config = _load_provider_config("anthropic")
        self.model = (
            model
            or os.getenv("KEEL_ANTHROPIC_MODEL")
            or config.get("default_model", "claude-3-5-sonnet-20241022")
        )
        self.base_url = (
            base_url
            or os.getenv("KEEL_ANTHROPIC_BASE_URL")
            or config.get("base_url", "https://api.anthropic.com/v1")
        )
        self._cost_table = config.get("models", {})

    def _calculate_cost(self, tokens_in: int, tokens_out: int) -> float:
        """Calculate cost based on model pricing from config."""
        pricing = self._cost_table.get(self.model, {})
        if not pricing:
            # Unknown model - warn but don't crash
            import warnings

            warnings.warn(
                f"Unknown model '{self.model}' in cost table, cost will be 0.0",
                stacklevel=2,
            )
            return 0.0
        input_cost = pricing.get("input", 0.0)
        output_cost = pricing.get("output", 0.0)
        return (tokens_in / 1_000_000) * input_cost + (tokens_out / 1_000_000) * output_cost

    def complete(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None,
    ) -> ProviderResponse:
        payload = {
            "model": self.model,
            "system": system,
            "messages": messages,
            "max_tokens": 4096,
        }

        if tools:
            # Convert to Anthropic tool format
            payload["tools"] = [
                {
                    "name": t["function"]["name"],
                    "description": t["function"].get("description", ""),
                    "input_schema": t["function"].get("parameters", {}),
                }
                for t in tools
            ]

        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self.base_url}/messages",
            data=data,
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )

        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode())

        content = ""
        tool_calls = []
        for block in result.get("content", []):
            if block["type"] == "text":
                content += block["text"]
            elif block["type"] == "tool_use":
                tool_calls.append({
                    "name": block["name"],
                    "arguments": block["input"],
                })

        usage = result.get("usage", {})
        tokens_in = usage.get("input_tokens", 0)
        tokens_out = usage.get("output_tokens", 0)
        cost = self._calculate_cost(tokens_in, tokens_out)

        return ProviderResponse(
            content=content,
            tool_calls=tool_calls,
            usage=Usage(
                tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost
            ),
        )


# Provider registry
PROVIDER_REGISTRY = {
    "mock": MockProvider,
    "ollama": OllamaProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
}


def get_provider(name: str, **kwargs) -> Provider:
    """Get provider instance by name."""
    if name not in PROVIDER_REGISTRY:
        raise ProviderNotFound(f"Unknown provider: {name}")
    return PROVIDER_REGISTRY[name](**kwargs)


__all__ = [
    "Provider",
    "ProviderResponse",
    "Usage",
    "MockProvider",
    "OllamaProvider",
    "OpenAIProvider",
    "AnthropicProvider",
    "ProviderNotFound",
    "ProviderNotConfigured",
    "ScriptExhausted",
    "get_provider",
    "PROVIDER_REGISTRY",
]
