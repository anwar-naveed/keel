"""LLM Provider adapters - P1.4

Provider ABC: complete(system, messages, tools) ->
ProviderResponse{content, tool_calls, usage{tokens_in,tokens_out,cost_usd}}
Registry: {"mock","ollama","openai","anthropic"}
MockProvider: deterministic scripted responses from YAML
OllamaProvider: stdlib urllib POST to http://ollama:11434/api/chat (no SDK)
OpenAI/Anthropic: raise ProviderNotConfigured unless env key present; stdlib urllib
Cost table per provider/model.
"""

import json
import os
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import yaml


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

        content = step.get("content", "")
        tool_calls = step.get("tool_calls", [])

        return ProviderResponse(
            content=content,
            tool_calls=tool_calls,
            usage=Usage(tokens_in=10, tokens_out=5, cost_usd=0.0),
        )


class OllamaProvider(Provider):
    """Ollama provider using stdlib urllib."""

    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or os.getenv("KEEL_OLLAMA_URL", "http://ollama:11434")
        self.model = os.getenv("KEEL_OLLAMA_MODEL", "llama3.1:8b")

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

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ProviderNotConfigured("OPENAI_API_KEY not set")
        self.model = model or os.getenv("KEEL_OPENAI_MODEL", "gpt-4o-mini")
        self.base_url = "https://api.openai.com/v1"

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
            usage=Usage(tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost),
        )

    def _calculate_cost(self, tokens_in: int, tokens_out: int) -> float:
        """Calculate cost based on model pricing."""
        pricing = COST_TABLE.get("openai", {}).get(self.model, {})
        input_cost = pricing.get("input", 0.0)
        output_cost = pricing.get("output", 0.0)
        return (tokens_in / 1_000_000) * input_cost + (tokens_out / 1_000_000) * output_cost


class AnthropicProvider(Provider):
    """Anthropic provider using stdlib urllib."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ProviderNotConfigured("ANTHROPIC_API_KEY not set")
        self.model = model or os.getenv("KEEL_ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
        self.base_url = "https://api.anthropic.com/v1"

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
            usage=Usage(tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost),
        )

    def _calculate_cost(self, tokens_in: int, tokens_out: int) -> float:
        """Calculate cost based on model pricing."""
        pricing = COST_TABLE.get("anthropic", {}).get(self.model, {})
        input_cost = pricing.get("input", 0.0)
        output_cost = pricing.get("output", 0.0)
        return (tokens_in / 1_000_000) * input_cost + (tokens_out / 1_000_000) * output_cost


# Cost table per provider/model (USD per 1M tokens)
COST_TABLE = {
    "mock": {
        "mock-1": {"input": 0.0, "output": 0.0},
    },
    "ollama": {
        "llama3.1:8b": {"input": 0.0, "output": 0.0},
    },
    "openai": {
        "gpt-4o": {"input": 5.0, "output": 15.0},
        "gpt-4o-mini": {"input": 0.15, "output": 0.6},
        "gpt-4-turbo": {"input": 10.0, "output": 30.0},
        "gpt-3.5-turbo": {"input": 0.5, "output": 1.5},
    },
    "anthropic": {
        "claude-3-5-sonnet-20241022": {"input": 3.0, "output": 15.0},
        "claude-3-5-haiku-20241022": {"input": 0.8, "output": 4.0},
        "claude-3-opus-20240229": {"input": 15.0, "output": 75.0},
    },
}

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
    "COST_TABLE",
]
