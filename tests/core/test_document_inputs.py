import pytest

from core.document_parser import parse_and_fetch_links
from core.skills.document_chunking import build_requirement_chunks


@pytest.mark.asyncio
async def test_parse_and_fetch_links_normalizes_wrapped_document_values():
    enriched = await parse_and_fetch_links({
        "prd": {"value": "# 登录\n支持账号密码登录"},
        "swagger": ["openapi: 3.0.0", "paths: {}"],
        "changelog": {"content": "## 变更\n- 调整审批规则"},
    })

    assert enriched["prd"] == "# 登录\n支持账号密码登录"
    assert enriched["swagger"] == "openapi: 3.0.0\npaths: {}"
    assert enriched["changelog"] == "## 变更\n- 调整审批规则"


def test_build_requirement_chunks_accepts_wrapped_document_values():
    chunks = build_requirement_chunks(
        prd_content={"value": "# 模块A\n支持查询"},
        changelog_content={"text": "## 变更\n- 调整审批"},
        rules=["仅验证主流程", {"value": "忽略演示账号"}],
    )

    assert [chunk.source_type for chunk in chunks] == ["prd", "changelog", "rule"]
    assert chunks[0].content.startswith("# 模块A")
    assert "调整审批" in chunks[1].content
    assert "忽略演示账号" in chunks[2].content


def test_build_requirement_chunks_scopes_to_focus_terms():
    chunks = build_requirement_chunks(
        prd_content="\n\n".join([
            "# 15-数据看板\n" + ("展示看板指标。 " * 80),
            "# 01-开发者配置中心\n" + ("展示 7 个业务 Tab。 " * 80),
        ]),
        focus_areas="dashboard",
        target_url="http://localhost:5000/dashboard",
    )

    assert chunks
    assert all(
        "数据看板" in chunk.source_reference or "数据看板" in chunk.content
        for chunk in chunks
    )
