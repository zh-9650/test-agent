import json

import pytest

from core.diag_logger import DiagLogger, _truncate_llm_content, get_diag


@pytest.mark.asyncio
async def test_disabled_diag_logger_finalize_is_awaitable():
    await get_diag("disabled-test").finalize()


def test_truncate_llm_content_respects_utf8_byte_limit(monkeypatch):
    from core import diag_logger

    monkeypatch.setattr(diag_logger, "_RAW_LLM_MAX_BYTES", 5)
    result = _truncate_llm_content("你好世界")

    assert result["truncated"] is True
    assert len(result["text"].encode("utf-8")) <= 5


@pytest.mark.asyncio
async def test_diag_logger_flushes_atomically_and_redacts(monkeypatch, tmp_path):
    from core import diag_logger

    monkeypatch.setattr(diag_logger, "_ENABLED", True)
    monkeypatch.setattr(diag_logger, "_BASE_DIR", tmp_path)
    logger = DiagLogger("task-1")
    logger.start()

    logger.dump(
        "00_entry",
        password="plain-secret",
        note="token=abc123",
        raw_json='{"password": "json-secret", "token": "json-token"}',
    )
    logger.dump("07_l2_planning_explore_step", mode="append", node="observe")
    logger.dump("07_l2_planning_explore_step", mode="append", node="decide")
    await logger.finalize()

    entry = json.loads((tmp_path / "task-1" / "00_entry.json").read_text(encoding="utf-8"))
    index = json.loads((tmp_path / "task-1" / "index.json").read_text(encoding="utf-8"))

    assert entry["password"] == "***"
    assert entry["note"] == "token=***"
    assert "json-secret" not in entry["raw_json"]
    assert "json-token" not in entry["raw_json"]
    append_entry = next(
        item for item in index["files"]
        if item["stage"] == "07_l2_planning_explore_step"
    )
    assert append_entry["count"] == 2
    assert not list((tmp_path / "task-1").glob("*.tmp"))
