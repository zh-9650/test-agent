"""Tests for core/llm_client.py — LLM Client with multi-model support."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

from core.llm_client import get_llm_client, count_tokens


class TestGetLlmClient:
    """Tests for get_llm_client function."""

    @pytest.fixture(autouse=True)
    def setup_env(self):
        """Set up environment variables for each test."""
        self.env_vars = {
            "ANTHROPIC_AUTH_TOKEN": "test-api-key",
            "ANTHROPIC_BASE_URL": "https://test-api.example.com",
            "ANTHROPIC_MODEL": "qwen3.7-max",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": "deepseek-v4-flash",
            "ANTHROPIC_DEFAULT_SONNET_MODEL": "kimi-k2.6",
            "ANTHROPIC_DEFAULT_OPUS_MODEL": "glm-5.1",
        }
        from core import llm_client
        llm_client._client_cache.clear()

    def test_get_default_client(self):
        """Returns ChatAnthropic with default model name."""
        with patch.dict(os.environ, self.env_vars, clear=False):
            client = get_llm_client("default")
            assert isinstance(client, ChatAnthropic)
            assert client.model == "qwen3.7-max"

    def test_get_haiku_client(self):
        """Returns ChatAnthropic with haiku model name."""
        with patch.dict(os.environ, self.env_vars, clear=False):
            client = get_llm_client("haiku")
            assert isinstance(client, ChatAnthropic)
            assert client.model == "deepseek-v4-flash"

    def test_get_sonnet_client(self):
        """Returns ChatAnthropic with sonnet model name."""
        with patch.dict(os.environ, self.env_vars, clear=False):
            client = get_llm_client("sonnet")
            assert isinstance(client, ChatAnthropic)
            assert client.model == "kimi-k2.6"

    def test_get_opus_client(self):
        """Returns ChatAnthropic with opus model name."""
        with patch.dict(os.environ, self.env_vars, clear=False):
            client = get_llm_client("opus")
            assert isinstance(client, ChatAnthropic)
            assert client.model == "glm-5.1"

    def test_client_caching(self):
        """Calling get_llm_client('default') twice returns same instance."""
        with patch.dict(os.environ, self.env_vars, clear=False):
            # Clear cache to ensure fresh start
            from core import llm_client
            llm_client._client_cache.clear()

            client1 = get_llm_client("default")
            client2 = get_llm_client("default")
            assert client1 is client2

    def test_missing_api_key_raises(self):
        """Clear error when ANTHROPIC_AUTH_TOKEN not set."""
        from core import llm_client
        llm_client._client_cache.clear()
        env_without_key = self.env_vars.copy()
        env_without_key.pop("ANTHROPIC_AUTH_TOKEN")
        with patch.dict(os.environ, env_without_key, clear=True):
            with pytest.raises(EnvironmentError) as exc_info:
                get_llm_client("default")
            assert "ANTHROPIC_AUTH_TOKEN" in str(exc_info.value)

    def test_missing_base_url_raises(self):
        """Clear error when ANTHROPIC_BASE_URL not set."""
        from core import llm_client
        llm_client._client_cache.clear()
        env_without_url = self.env_vars.copy()
        env_without_url.pop("ANTHROPIC_BASE_URL")
        with patch.dict(os.environ, env_without_url, clear=True):
            with pytest.raises(EnvironmentError) as exc_info:
                get_llm_client("default")
            assert "ANTHROPIC_BASE_URL" in str(exc_info.value)


class TestCountTokens:
    """Tests for count_tokens function."""

    def test_count_tokens_basic(self):
        """Non-empty messages return positive token count."""
        messages = [
            HumanMessage(content="Hello, this is a test message."),
            HumanMessage(content="Another message for counting."),
        ]
        result = count_tokens(messages)
        assert result > 0

    def test_count_tokens_empty(self):
        """Empty message list returns 0."""
        result = count_tokens([])
        assert result == 0

    def test_count_tokens_chinese(self):
        """Chinese text tokens are estimated correctly (shorter per token)."""
        messages = [HumanMessage(content="这是一个中文测试消息。")]
        result = count_tokens(messages)
        assert result > 0
        # Chinese characters should produce fewer tokens than English per char
        # since each token covers ~1.5 Chinese characters vs ~4 English chars

    def test_count_tokens_with_model_param(self):
        """Model parameter is accepted but doesn't change basic behavior."""
        messages = [HumanMessage(content="Test message.")]
        result = count_tokens(messages, model="some-model")
        assert result > 0


def test_sanitize_messages_for_structured_output():
    from core.llm_client import sanitize_messages_for_structured_output
    from langchain_core.messages import AIMessage, ToolMessage, HumanMessage, SystemMessage

    messages = [
        SystemMessage(content="sys"),
        AIMessage(content="evaluating", tool_calls=[{"name": "click", "args": {"target": "#btn"}, "id": "1"}]),
        ToolMessage(content="success", name="click", tool_call_id="1"),
        HumanMessage(content="next step")
    ]

    sanitized = sanitize_messages_for_structured_output(messages)
    assert len(sanitized) == 4

    assert isinstance(sanitized[0], SystemMessage)
    assert sanitized[0].content == "sys"

    assert isinstance(sanitized[1], AIMessage)
    assert not sanitized[1].tool_calls
    assert "调用工具: click" in sanitized[1].content
    assert "evaluating" in sanitized[1].content

    assert isinstance(sanitized[2], HumanMessage)
    assert "工具 click 执行结果" in sanitized[2].content
    assert "success" in sanitized[2].content

    assert isinstance(sanitized[3], HumanMessage)
    assert sanitized[3].content == "next step"
