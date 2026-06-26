"""Tests for core/llm_client.py — LLM Client with multi-model support."""

from __future__ import annotations

import os
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage

from core.llm_client import get_llm_client, count_tokens
from core.interfaces import RequirementFact
from core.skills.assertion_deriver import AssertionDerivationResult
from core.skills.fact_extractor import FactExtractionResult
from core.skills.case_generator import CaseGenerationResult
from core.skills.technique_selector import TechniqueResult


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


@pytest.mark.asyncio
async def test_safe_structured_invoke_recovers_native_tool_args_before_retry():
    from core import llm_client

    payload = {
        "id": "FACT-001",
        "source_type": "prd",
        "source_reference": "section-1",
        "quote": "Only administrators can access settings",
        "subject": "administrators",
        "action": "access",
        "object": "settings",
        "confidence": 1.0,
        "status": "confirmed",
    }
    raw_message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "RequirementFact",
                "args": payload,
                "id": "call-1",
                "type": "tool_call",
            }
        ],
    )
    structured_wrapper = AsyncMock()
    structured_wrapper.ainvoke.return_value = {
        "raw": raw_message,
        "parsed": None,
        "parsing_error": ValueError("provider parser rejected response"),
    }
    fake_llm = MagicMock()
    fake_llm.with_structured_output.return_value = structured_wrapper
    fake_llm.ainvoke = AsyncMock()

    with patch.object(llm_client, "get_llm_client", return_value=fake_llm):
        result = await llm_client.safe_structured_invoke(
            "extract facts",
            RequirementFact,
        )

    assert result is not None
    assert result.subject == "administrators"
    assert result.action == "access"
    fake_llm.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_safe_structured_invoke_recovers_native_text_before_retry():
    from core import llm_client

    payload = {
        "id": "FACT-002",
        "source_type": "prd",
        "source_reference": "section-2",
        "quote": "Administrator",
        "subject": "Administrator",
        "action": "login",
        "object": "system",
        "confidence": 1.0,
        "status": "draft",
    }
    raw_message = AIMessage(content=json.dumps(payload))
    structured_wrapper = AsyncMock()
    structured_wrapper.ainvoke.return_value = {
        "raw": raw_message,
        "parsed": None,
        "parsing_error": ValueError("provider parser rejected response"),
    }
    fake_llm = MagicMock()
    fake_llm.with_structured_output.return_value = structured_wrapper
    fake_llm.ainvoke = AsyncMock()

    with patch.object(llm_client, "get_llm_client", return_value=fake_llm):
        result = await llm_client.safe_structured_invoke(
            "extract facts",
            RequirementFact,
        )

    assert result is not None
    assert result.subject == "Administrator"
    assert result.action == "login"
    fake_llm.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_safe_structured_invoke_decodes_json_string_list_fields():
    from core import llm_client

    fact_payload = {
        "id": "FACT-003",
        "source_type": "prd",
        "source_reference": "section-3",
        "quote": "Weights must total 100%",
        "subject": "Weights",
        "action": "total",
        "object": "100%",
        "confidence": 1.0,
        "status": "confirmed",
    }
    payload = {"facts": json.dumps([fact_payload])}
    raw_message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "FactExtractionResult",
                "args": payload,
                "id": "call-1",
                "type": "tool_call",
            }
        ],
    )
    structured_wrapper = AsyncMock()
    structured_wrapper.ainvoke.return_value = {
        "raw": raw_message,
        "parsed": None,
        "parsing_error": ValueError("list fields were JSON-encoded strings"),
    }
    fake_llm = MagicMock()
    fake_llm.with_structured_output.return_value = structured_wrapper
    fake_llm.ainvoke = AsyncMock()

    with patch.object(llm_client, "get_llm_client", return_value=fake_llm):
        result = await llm_client.safe_structured_invoke(
            "extract facts",
            FactExtractionResult,
        )

    assert result is not None
    assert result.facts[0].subject == "Weights"
    assert result.facts[0].action == "total"
    fake_llm.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_safe_structured_invoke_decodes_double_encoded_json_string_list_fields():
    from core import llm_client

    assertion_payload = {
        "id": "ASSERT-001",
        "fact_ids": ["FACT-001"],
        "assertion_text": "系统应展示总分占比",
        "assertion_type": "functional",
        "risk_level": "medium",
        "review_status": "auto_generated",
        "source_references": ["section-3"],
    }
    payload = {"assertions": json.dumps(json.dumps([assertion_payload]))}
    raw_message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "AssertionDerivationResult",
                "args": payload,
                "id": "call-1",
                "type": "tool_call",
            }
        ],
    )
    structured_wrapper = AsyncMock()
    structured_wrapper.ainvoke.return_value = {
        "raw": raw_message,
        "parsed": None,
        "parsing_error": ValueError("list fields were double JSON-encoded strings"),
    }
    fake_llm = MagicMock()
    fake_llm.with_structured_output.return_value = structured_wrapper
    fake_llm.ainvoke = AsyncMock()

    with patch.object(llm_client, "get_llm_client", return_value=fake_llm):
        result = await llm_client.safe_structured_invoke(
            "derive assertions",
            AssertionDerivationResult,
        )

    assert result is not None
    assert result.assertions[0].assertion_text == "系统应展示总分占比"
    assert result.assertions[0].fact_ids == ["FACT-001"]
    fake_llm.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_safe_structured_invoke_wraps_top_level_list_for_single_list_field_schema():
    from core import llm_client

    fact_payload = {
        "id": "FACT-005",
        "source_type": "prd",
        "source_reference": "section-5",
        "quote": "Dashboard shows KPI cards",
        "subject": "Dashboard",
        "action": "shows",
        "object": "KPI cards",
        "confidence": 1.0,
        "status": "confirmed",
    }
    raw_message = AIMessage(content=json.dumps([fact_payload]))
    structured_wrapper = AsyncMock()
    structured_wrapper.ainvoke.return_value = {
        "raw": raw_message,
        "parsed": None,
        "parsing_error": ValueError("provider emitted a top-level list"),
    }
    fake_llm = MagicMock()
    fake_llm.with_structured_output.return_value = structured_wrapper
    fake_llm.ainvoke = AsyncMock()

    with patch.object(llm_client, "get_llm_client", return_value=fake_llm):
        result = await llm_client.safe_structured_invoke(
            "extract facts",
            FactExtractionResult,
        )

    assert result is not None
    assert result.facts[0].subject == "Dashboard"
    assert result.facts[0].object == "KPI cards"
    fake_llm.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_safe_structured_invoke_decodes_list_items_that_are_json_strings():
    from core import llm_client

    fact_payload = {
        "id": "FACT-006",
        "source_type": "prd",
        "source_reference": "section-6",
        "quote": "Dashboard shows warning badges",
        "subject": "Dashboard",
        "action": "shows",
        "object": "warning badges",
        "confidence": 1.0,
        "status": "confirmed",
    }
    payload = {"facts": json.dumps([json.dumps(fact_payload)])}
    raw_message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "FactExtractionResult",
                "args": payload,
                "id": "call-1",
                "type": "tool_call",
            }
        ],
    )
    structured_wrapper = AsyncMock()
    structured_wrapper.ainvoke.return_value = {
        "raw": raw_message,
        "parsed": None,
        "parsing_error": ValueError("provider nested dict items as JSON strings"),
    }
    fake_llm = MagicMock()
    fake_llm.with_structured_output.return_value = structured_wrapper
    fake_llm.ainvoke = AsyncMock()

    with patch.object(llm_client, "get_llm_client", return_value=fake_llm):
        result = await llm_client.safe_structured_invoke(
            "extract facts",
            FactExtractionResult,
        )

    assert result is not None
    assert result.facts[0].object == "warning badges"
    fake_llm.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_safe_structured_invoke_accepts_unescaped_control_chars():
    from core import llm_client

    raw_json = (
        '{"id":"FACT-004","source_type":"prd","source_reference":"section-4",'
        '"quote":"line one\\nline two","subject":"line","action":"one",'
        '"object":"two","confidence":1.0,"status":"draft"}'
    )
    raw_message = AIMessage(content=raw_json)
    structured_wrapper = AsyncMock()
    structured_wrapper.ainvoke.return_value = {
        "raw": raw_message,
        "parsed": None,
        "parsing_error": ValueError("invalid control character"),
    }
    fake_llm = MagicMock()
    fake_llm.with_structured_output.return_value = structured_wrapper
    fake_llm.ainvoke = AsyncMock()

    with patch.object(llm_client, "get_llm_client", return_value=fake_llm):
        result = await llm_client.safe_structured_invoke(
            "extract facts",
            RequirementFact,
        )

    assert result is not None
    assert result.quote == "line one\nline two"
    fake_llm.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_safe_structured_invoke_salvages_partial_list_field_from_native_args():
    from core import llm_client

    fact_payload = {
        "id": "FACT-007",
        "source_type": "prd",
        "source_reference": "section-7",
        "quote": "Dashboard cards are read only",
        "subject": "Dashboard cards",
        "action": "remain",
        "object": "read only",
        "confidence": 1.0,
        "status": "confirmed",
        "conflict_references": [],
    }
    payload = {
        "facts": (
            f"[{json.dumps(fact_payload)}, "
            "{\"id\": \"FACT-008\", \"source_type\": "
        ),
    }
    raw_message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "FactExtractionResult",
                "args": payload,
                "id": "call-1",
                "type": "tool_call",
            }
        ],
    )
    structured_wrapper = AsyncMock()
    structured_wrapper.ainvoke.return_value = {
        "raw": raw_message,
        "parsed": None,
        "parsing_error": ValueError("provider emitted a truncated list string"),
    }
    fake_llm = MagicMock()
    fake_llm.with_structured_output.return_value = structured_wrapper
    fake_llm.ainvoke = AsyncMock()

    with patch.object(llm_client, "get_llm_client", return_value=fake_llm):
        result = await llm_client.safe_structured_invoke(
            "extract facts",
            FactExtractionResult,
        )

    assert result is not None
    assert len(result.facts) == 1
    assert result.facts[0].id == "FACT-007"
    fake_llm.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_safe_structured_invoke_salvages_partial_list_field_from_raw_fallback():
    from core import llm_client

    fact_payload = {
        "id": "FACT-009",
        "source_type": "prd",
        "source_reference": "section-9",
        "quote": "Read-only regions reject inline editing",
        "subject": "Read-only regions",
        "action": "reject",
        "object": "inline editing",
        "confidence": 1.0,
        "status": "confirmed",
        "conflict_references": [],
    }
    raw_message = AIMessage(content="")
    malformed_raw = AIMessage(
        content=(
            '{"facts": ['
            + json.dumps(fact_payload)
            + ', {"id": "FACT-010", "source_type": broken}]}'
        )
    )
    structured_wrapper = AsyncMock()
    structured_wrapper.ainvoke.return_value = {
        "raw": raw_message,
        "parsed": None,
        "parsing_error": ValueError("provider parser rejected response"),
    }
    fake_llm = MagicMock()
    fake_llm.with_structured_output.return_value = structured_wrapper
    fake_llm.ainvoke = AsyncMock(return_value=malformed_raw)

    with patch.object(llm_client, "get_llm_client", return_value=fake_llm):
        result = await llm_client.safe_structured_invoke(
            "extract facts",
            FactExtractionResult,
        )

    assert result is not None
    assert len(result.facts) == 1
    assert result.facts[0].id == "FACT-009"
    fake_llm.ainvoke.assert_awaited_once()


def test_coerce_adds_missing_technique_id():
    from core.llm_client import _coerce_to_pydantic

    result = _coerce_to_pydantic(
        {
            "techniques": [{
                "condition_id": "COND-001",
                "primary_technique": "equivalence_partitioning",
                "supplementary_techniques": [],
                "rationale": "覆盖正常与异常等价类",
            }],
        },
        TechniqueResult,
    )

    assert result.techniques[0].id == "TECH-COND-001"


def test_coerce_normalizes_case_value_and_required_roles():
    from core.llm_client import _coerce_to_pydantic

    result = _coerce_to_pydantic(
        {
            "cases": [{
                "id": "TC-CAND-001",
                "title": "部门领导查看数据",
                "goal": "验证部门数据隔离",
                "preconditions": [{
                    "type": "account_role",
                    "description": "使用部门领导账号",
                    "required_role": "部门领导",
                    "satisfiable_by_agent": True,
                    "failure_policy": "skipped",
                }],
                "input_data": [{
                    "name": "人数",
                    "value": 0,
                    "source": "generated",
                    "sensitivity": "public",
                }],
                "expected_result": "仅展示本部门数据",
                "priority": "high",
                "trace_references": ["COV-001"],
                "required_roles": [],
            }],
        },
        CaseGenerationResult,
    )

    assert result.cases[0].input_data[0].value == "0"
    assert result.cases[0].required_roles == ["部门领导"]
