from unittest.mock import AsyncMock, patch

import pytest

from core.interfaces import RequirementFact
from core.skills.fact_extractor import FactExtractionResult


@pytest.mark.asyncio
async def test_fact_extractor_keeps_empty_chunks_without_failing(monkeypatch):
    monkeypatch.setenv("L1_CHUNK_MAX_CHARS", "1000")
    long_prd = "\n\n".join([
        "# 模块一\n" + ("需求一内容。 " * 140),
        "# 模块二\n" + ("说明性文字。 " * 140),
    ])
    fact = RequirementFact(
        id="FACT-001",
        source_type="prd",
        source_reference="模块一",
        quote="需求一内容",
        subject="模块一",
        action="展示",
        object="内容",
        confidence=0.9,
        status="confirmed",
    )

    with patch(
        "core.skills.fact_extractor.safe_structured_invoke",
        new=AsyncMock(side_effect=[
            FactExtractionResult(facts=[fact]),
            FactExtractionResult(facts=[]),
        ]),
    ) as mock:
        from core.skills.fact_extractor import extract_facts

        result = await extract_facts(prd_content=long_prd)

    assert mock.await_count == 2
    assert [item.id for item in result] == ["FACT-001"]


@pytest.mark.asyncio
async def test_fact_extractor_still_fails_when_some_chunks_return_none(monkeypatch):
    monkeypatch.setenv("L1_CHUNK_MAX_CHARS", "1000")
    long_prd = "\n\n".join([
        "# 模块一\n" + ("需求一内容。 " * 140),
        "# 模块二\n" + ("需求二内容。 " * 140),
    ])
    fact = RequirementFact(
        id="FACT-001",
        source_type="prd",
        source_reference="模块一",
        quote="需求一内容",
        subject="模块一",
        action="展示",
        object="内容",
        confidence=0.9,
        status="confirmed",
    )

    with patch(
        "core.skills.fact_extractor.safe_structured_invoke",
        new=AsyncMock(side_effect=[
            FactExtractionResult(facts=[fact]),
            None,
        ]),
    ):
        from core.skills.fact_extractor import extract_facts

        with pytest.raises(
            RuntimeError,
            match="fact_extraction_incomplete: 1/2 chunks failed",
        ):
            await extract_facts(prd_content=long_prd)


@pytest.mark.asyncio
async def test_fact_extractor_allows_configured_failed_chunks(monkeypatch):
    monkeypatch.setenv("L1_CHUNK_MAX_CHARS", "1000")
    monkeypatch.setenv("L1_MAX_FAILED_CHUNKS", "1")
    long_prd = "\n\n".join([
        "# 模块一\n" + ("需求一内容。 " * 140),
        "# 模块二\n" + ("需求二内容。 " * 140),
    ])
    fact = RequirementFact(
        id="FACT-001",
        source_type="prd",
        source_reference="模块一",
        quote="需求一内容",
        subject="模块一",
        action="展示",
        object="内容",
        confidence=0.9,
        status="confirmed",
    )

    with patch(
        "core.skills.fact_extractor.safe_structured_invoke",
        new=AsyncMock(side_effect=[
            FactExtractionResult(facts=[fact]),
            None,
        ]),
    ):
        from core.skills.fact_extractor import extract_facts

        result = await extract_facts(prd_content=long_prd)

    assert [item.id for item in result] == ["FACT-001"]
