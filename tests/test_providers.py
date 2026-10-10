"""Tests for runtime/providers.py - P1.4"""

from unittest.mock import MagicMock, patch

import pytest

from keel.runtime.providers import (
    COST_TABLE,
    PROVIDER_REGISTRY,
    AnthropicProvider,
    MockProvider,
    OllamaProvider,
    OpenAIProvider,
    ProviderNotConfigured,
    ProviderNotFound,
    ProviderResponse,
    ScriptExhausted,
    Usage,
    get_provider,
)


def test_provider_registry():
    """Test that all providers are registered."""
    assert "mock" in PROVIDER_REGISTRY
    assert "ollama" in PROVIDER_REGISTRY
    assert "openai" in PROVIDER_REGISTRY
    assert "anthropic" in PROVIDER_REGISTRY


def test_unknown_provider_raises():
    """Test that unknown provider raises ProviderNotFound."""
    with pytest.raises(ProviderNotFound):
        get_provider("unknown")


def test_mock_provider_deterministic(tmp_path):
    """Test MockProvider returns scripted responses."""
    # Create a mock script file
    script_file = tmp_path / "mock_script.yaml"
    script_file.write_text("""
- content: "Hello"
  tool_calls: []
- content: "World"
  tool_calls: []
""")

    provider = MockProvider(script_path=script_file)

    # First call
    response = provider.complete("system", [{"role": "user", "content": "hi"}], None)
    assert response.content == "Hello"
    assert response.tool_calls == []

    # Second call
    response = provider.complete("system", [{"role": "user", "content": "hi"}], None)
    assert response.content == "World"
    assert response.tool_calls == []


def test_mock_provider_script_exhausted(tmp_path):
    """Test MockProvider raises ScriptExhausted when past end."""
    script_file = tmp_path / "mock_script.yaml"
    script_file.write_text("""
- content: "Only response"
""")

    provider = MockProvider(script_path=script_file)

    # First call works
    response = provider.complete("system", [{"role": "user", "content": "hi"}], None)
    assert response.content == "Only response"

    # Second call raises
    with pytest.raises(ScriptExhausted):
        provider.complete("system", [{"role": "user", "content": "hi"}], None)


def test_mock_provider_with_tool_calls(tmp_path):
    """Test MockProvider with tool calls in script."""
    script_file = tmp_path / "mock_script.yaml"
    script_file.write_text("""
- content: "I'll call a tool"
  tool_calls:
    - name: "test_tool"
      arguments: {"key": "value"}
""")

    provider = MockProvider(script_path=script_file)

    response = provider.complete("system", [{"role": "user", "content": "hi"}], None)
    assert response.content == "I'll call a tool"
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0]["name"] == "test_tool"


def test_ollama_provider_not_configured(monkeypatch):
    """Test OllamaProvider works without extra config (has default URL)."""
    monkeypatch.delenv("KEEL_OLLAMA_URL", raising=False)
    # OllamaProvider has a default URL, so it should not raise ProviderNotConfigured
    provider = OllamaProvider()
    assert provider.base_url == "http://ollama:11434"


def test_openai_provider_not_configured(monkeypatch):
    """Test OpenAIProvider raises ProviderNotConfigured without API key."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ProviderNotConfigured):
        OpenAIProvider()


def test_anthropic_provider_not_configured(monkeypatch):
    """Test AnthropicProvider raises ProviderNotConfigured without API key."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ProviderNotConfigured):
        AnthropicProvider()


def test_cost_table_exists():
    """Test that cost table has entries for all providers."""
    assert "mock" in COST_TABLE
    assert "ollama" in COST_TABLE
    assert "openai" in COST_TABLE
    assert "anthropic" in COST_TABLE

    # Check structure
    for _provider, models in COST_TABLE.items():
        assert isinstance(models, dict)
        for _model, cost in models.items():
            assert "input" in cost
            assert "output" in cost


def test_usage_dataclass():
    """Test Usage dataclass."""
    usage = Usage(tokens_in=100, tokens_out=50, cost_usd=0.001)
    assert usage.tokens_in == 100
    assert usage.tokens_out == 50
    assert usage.cost_usd == 0.001


def test_provider_response_dataclass():
    """Test ProviderResponse dataclass."""
    usage = Usage(tokens_in=100, tokens_out=50, cost_usd=0.001)
    response = ProviderResponse(
        content="Hello",
        tool_calls=[{"name": "test", "arguments": {}}],
        usage=usage,
    )
    assert response.content == "Hello"
    assert len(response.tool_calls) == 1
    assert response.usage.tokens_in == 100


@patch("urllib.request.urlopen")
def test_ollama_provider_mocked(mock_urlopen):
    """Test OllamaProvider with mocked HTTP."""
    # Setup mock response
    mock_response = MagicMock()
    mock_response.read.return_value = b'{"message": {"content": "Hello from Ollama"}, "done": true}'
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=None)
    mock_urlopen.return_value = mock_response

    provider = OllamaProvider()
    response = provider.complete("system", [{"role": "user", "content": "hi"}], None)

    assert response.content == "Hello from Ollama"
    assert response.usage.tokens_in == 0  # Ollama doesn't return token counts
    assert response.usage.tokens_out == 0
    assert response.usage.cost_usd == 0.0  # Ollama is free


@patch("urllib.request.urlopen")
def test_openai_provider_mocked(mock_urlopen, monkeypatch):
    """Test OpenAIProvider with mocked HTTP."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    mock_response = MagicMock()
    mock_response.read.return_value = (
            b'{"choices": [{"message": {"content": "Hello from OpenAI", '
            b'"tool_calls": null}}], "usage": {"prompt_tokens": 10, '
            b'"completion_tokens": 5}}'
        )
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=None)
    mock_urlopen.return_value = mock_response

    provider = OpenAIProvider()
    response = provider.complete("system", [{"role": "user", "content": "hi"}], None)

    assert response.content == "Hello from OpenAI"
    assert response.usage.tokens_in == 10
    assert response.usage.tokens_out == 5
    assert response.usage.cost_usd > 0


@patch("urllib.request.urlopen")
def test_anthropic_provider_mocked(mock_urlopen, monkeypatch):
    """Test AnthropicProvider with mocked HTTP."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    mock_response = MagicMock()
    mock_response.read.return_value = (
            b'{"content": [{"type": "text", "text": "Hello from Anthropic"}]'
            b', "usage": {"input_tokens": 10, "output_tokens": 5}}'
        )
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=None)
    mock_urlopen.return_value = mock_response

    provider = AnthropicProvider()
    response = provider.complete("system", [{"role": "user", "content": "hi"}], None)

    assert response.content == "Hello from Anthropic"
    assert response.usage.tokens_in == 10
    assert response.usage.tokens_out == 5
    assert response.usage.cost_usd > 0
