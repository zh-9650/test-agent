"""core/diag_logger.py — Per-task diagnostic log dumper.

Tier 1 (2026-06-05): 9 JSON files per task. 0 业务逻辑侵入.
- 内部队列 + writer_loop, finalize() 同步落盘
- 写盘前 redaction (账号/密码/token/cookie/authorization/localStorage)
- 统一 metadata 注入 (task_id/case_id/attempt/stage/node/duration_ms/model/token_in/out/...)
- page_info 精简默认字段, DIAG_FULL=true 才存 a11y_tree + screenshot
- env DIAG_ENABLED 关闭时 = _NullLogger, 0 副作用

使用:
    diag = get_diag(task_id)         # 拿单例 (按 task_id)
    diag.start()                      # 启后台 writer
    diag.dump("00_entry", target_url=..., config=...)  # 非阻塞入队
    diag.dump_raw("04_l1_system_model", raw=...)         # normalize 前的 raw
    await diag.finalize()             # 任务结束 / 进程退出 必调
"""
from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# -----------------------------------------------------------------------------
# 模块级开关 + 路径
# -----------------------------------------------------------------------------

_BASE_DIR = Path("data") / "diag"
_ENABLED = os.getenv("DIAG_ENABLED", "false").lower() in ("true", "1", "yes")
_FULL = os.getenv("DIAG_FULL", "false").lower() in ("true", "1", "yes")
_RAW_LLM_MAX_BYTES = int(os.getenv("DIAG_RAW_MAX_BYTES", "4096"))  # 4KB 截断
_PREVIEW_MAX_CHARS = 500


# 阶段 → 序号 (控制文件名前缀顺序)
_STAGE_ORDER: dict[str, str] = {
    "00_entry": "00",
    "01_l1_knowledge": "01",
    "02_l1_use_case": "02",
    "03_l1_coverage": "03",
    "04_l1_system_model": "04",
    "04_l1_system_model_raw": "04",
    "05_l1_goals": "05",
    # Tier 2 (2026-06-05): astream 监听
    "06_l2_planning_extract_goals": "06",
    "07_l2_planning_explore_step": "07",
    "08_l2_planning_generate_system_map": "08",
    "09_l2_planning_extract_scenarios": "09",
    "10_l2_planning_generate_plan": "10",
    "11_l3_execution_step": "11",
    "12_l3_execution_assert": "12",
    "13_l3_execution_record": "13",
    "15_report_summary": "15",
    "99_task_config_evolution": "99",
}

# 强制 metadata 字段 (dump 内部自动注入, caller 不传 → "N/A")
META_KEYS: list[str] = [
    "task_id", "case_id", "attempt", "step_index", "stage", "node",
    "started_at", "duration_ms", "model",
    "token_in", "token_out",
    "prompt_hash", "input_hash", "output_hash",
]

# 精简 page_info 默认字段
PAGE_INFO_KEYS_DEFAULT: set[str] = {
    "url", "title", "interactive_count", "top_elements", "errors",
    "network", "pending", "tabs", "scroll", "truncated",
}

# Redaction 配置
REDACT_KEYS: set[str] = {
    "password", "passwd", "pwd", "token", "access_token", "refresh_token",
    "cookie", "set-cookie", "authorization", "auth",
    "localstorage", "sessionstorage", "api_key", "secret", "credentials",
    "anthropic_auth_token", "anthropic_api_key",
}

REDACT_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Handles plain key=value and JSON-like "key": "value" strings.
    (
        re.compile(
            r"""(?i)(["']?(?:password|passwd|pwd)["']?\s*[=:]\s*)(["']?)[^"'\s&,};]+"""
        ),
        r"\1\2***",
    ),
    (
        re.compile(
            r"""(?i)(["']?(?:token|secret|api[_-]?key)["']?\s*[=:]\s*)(["']?)[^"'\s&,};]+"""
        ),
        r"\1\2***",
    ),
    (re.compile(r"Bearer\s+[^\s&,};\"]+"), "Bearer ***"),
]


# -----------------------------------------------------------------------------
# 工具函数
# -----------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_obj(obj: Any) -> str:
    """Stable hash for a JSON-serializable object (used for input/output/prompt hash)."""
    try:
        s = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        s = repr(obj)
    return hashlib.sha256(s.encode("utf-8", errors="replace")).hexdigest()[:16]


def _truncate_str(s: str, n: int = _PREVIEW_MAX_CHARS) -> str:
    if not isinstance(s, str):
        s = str(s)
    if len(s) <= n:
        return s
    return s[:n] + f"...(truncated, total {len(s)} chars)"


def _truncate_llm_content(content: str | None) -> dict[str, Any]:
    """Truncate raw LLM content + return metadata. Always returns a dict for traceability."""
    if content is None:
        return {"available": False}
    b = content.encode("utf-8", errors="replace")
    truncated = len(b) > _RAW_LLM_MAX_BYTES
    text = content if not truncated else b[:_RAW_LLM_MAX_BYTES].decode("utf-8", errors="ignore")
    return {
        "available": True,
        "size_bytes": len(b),
        "truncated": truncated,
        "text": text,
    }


# -----------------------------------------------------------------------------
# Redactor
# -----------------------------------------------------------------------------

class Redactor:
    """递归遍历 dict/list/str, 按 key + pattern 双层 redaction."""

    def __init__(
        self,
        keys: set[str] = REDACT_KEYS,
        patterns: list[tuple[re.Pattern, str]] = REDACT_PATTERNS,
        placeholder: str = "***",
    ):
        self._keys = {k.lower() for k in keys}
        self._patterns = patterns
        self._placeholder = placeholder

    def redact(self, obj: Any) -> Any:
        if isinstance(obj, dict):
            return {
                k: (self._placeholder if k.lower() in self._keys else self.redact(v))
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [self.redact(v) for v in obj]
        if isinstance(obj, str):
            return self._redact_str(obj)
        return obj

    def _redact_str(self, s: str) -> str:
        for pat, repl in self._patterns:
            s = pat.sub(repl, s)
        return s


# -----------------------------------------------------------------------------
# MetaInjector
# -----------------------------------------------------------------------------

class MetaInjector:
    """对每条 dump 自动注入统一 metadata, caller 已有则尊重 caller."""

    def __init__(self, task_id: str, model: str | None = None):
        self._task_id = task_id
        self._model = model or os.getenv("ANTHROPIC_MODEL", "unknown")

    def inject(self, stage: str, fields: dict[str, Any], started_at: str) -> dict[str, Any]:
        merged: dict[str, Any] = {"started_at": started_at, "task_id": self._task_id, "stage": stage}
        for k in META_KEYS:
            if k not in merged:
                merged[k] = fields.get(k, "N/A")
        # stage / task_id 不允许 caller 覆盖
        merged["stage"] = stage
        merged["task_id"] = self._task_id
        # 默认 model
        if merged.get("model") in (None, "N/A"):
            merged["model"] = self._model
        # 业务字段 (除 META 外的) 全保留
        for k, v in fields.items():
            if k not in META_KEYS and k not in merged:
                merged[k] = v
        return merged


# -----------------------------------------------------------------------------
# DiagLogger
# -----------------------------------------------------------------------------

class DiagLogger:
    """单 task 维度的诊断日志落盘器."""

    def __init__(self, task_id: str):
        self.task_id = task_id
        self._base = _BASE_DIR / task_id
        self._queue: asyncio.Queue | None = None
        self._writer_task: asyncio.Task | None = None
        self._redactor = Redactor()
        self._meta = MetaInjector(task_id)
        self._files_written: list[dict[str, Any]] = []
        self._started = False
        self._finalized = False
        # Tier 2: append mode 缓冲 (explore/execution 循环多次 dump 同一 stage 累积到 array)
        self._append_buffers: dict[str, list[dict[str, Any]]] = {}

    def start(self) -> None:
        """启动后台 writer. 非阻塞, 失败不抛 (只 stderr 提示)."""
        if not _ENABLED or self._started:
            return
        try:
            self._base.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            sys.stderr.write(f"[Diag] mkdir failed for {self._base}: {e}\n")
            return
        self._queue = asyncio.Queue()
        self._writer_task = asyncio.create_task(self._writer_loop())
        self._started = True

    def dump(self, stage: str, **fields: Any) -> None:
        """非阻塞入队. 内部: redact → 注入 meta → enqueue.

        Args:
            stage: 阶段名 (见 _STAGE_ORDER)
            mode: "overwrite" (默认) 每次 dump 覆盖文件;
                  "append" 多次 dump 累积到 array (explore loop 用)
            **fields: 业务字段 + 可选 metadata
        """
        if not _ENABLED or not self._started or self._queue is None:
            return
        mode = fields.pop("mode", "overwrite")
        started_at = _now_iso()
        merged = self._meta.inject(stage, fields, started_at)
        redacted = self._redactor.redact(merged)
        try:
            if mode == "append":
                buf = self._append_buffers.setdefault(stage, [])
                buf.append(redacted)
                # 立刻把整个 array 入队 (caller 拿到一致快照)
                self._queue.put_nowait((stage, {"_mode": "append", "items": list(buf)}))
            else:
                self._queue.put_nowait((stage, redacted))
        except Exception as e:
            sys.stderr.write(f"[Diag] enqueue {stage} failed: {e}\n")

    def dump_raw(self, stage: str, raw: Any) -> None:
        """normalize 前后对比用. 自动加 _raw 后缀写到同 stage 序列."""
        if not _ENABLED or not self._started or self._queue is None:
            return
        raw_stage = f"{stage}_raw"
        started_at = _now_iso()
        # raw 走专用通道: input_hash 自动算, 不入 meta 强约束
        fields = {
            "raw": raw,
            "input_hash": _hash_obj(raw),
            "stage_override": raw_stage,
        }
        merged = self._meta.inject(raw_stage, fields, started_at)
        merged["stage"] = raw_stage
        redacted = self._redactor.redact(merged)
        try:
            self._queue.put_nowait((raw_stage, redacted))
        except Exception as e:
            sys.stderr.write(f"[Diag] enqueue raw {raw_stage} failed: {e}\n")

    async def finalize(self) -> None:
        """await flush 全部 pending + 写 index.json. 任务结束 / 进程退出 必调."""
        if not _ENABLED or self._finalized:
            return
        self._finalized = True
        if self._queue is not None:
            try:
                await self._queue.join()
            except Exception as e:
                sys.stderr.write(f"[Diag] queue.join failed: {e}\n")
        if self._writer_task is not None:
            self._writer_task.cancel()
            try:
                await self._writer_task
            except (asyncio.CancelledError, Exception):
                pass
        # 写 index.json
        self._write_index()

    def _stage_to_filename(self, stage: str) -> str:
        # stage 名已自带序号 (如 "00_entry"), 直接用, 不重复加
        return f"{stage}.json"

    def _write_file(self, stage: str, data: dict[str, Any]) -> None:
        if not self._base:
            return
        try:
            path = self._base / self._stage_to_filename(stage)
            # append mode: data 是 {"_mode": "append", "items": [...]}
            if isinstance(data, dict) and data.get("_mode") == "append" and "items" in data:
                payload = {
                    "task_id": self.task_id,
                    "stage": stage,
                    "mode": "append",
                    "count": len(data["items"]),
                    "items": data["items"],
                }
            else:
                payload = data
            temp_path = path.with_suffix(f"{path.suffix}.tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
            os.replace(temp_path, path)
            size = path.stat().st_size
            mode = payload.get("mode", "overwrite")
            existing = next(
                (
                    item for item in self._files_written
                    if item.get("stage") == stage
                    and item.get("mode", "overwrite") == mode
                ),
                None,
            )
            if existing is None:
                entry = {
                    "stage": stage,
                    "path": str(path.relative_to(_BASE_DIR.parent)),
                    "size_bytes": size,
                    "mtime": _now_iso(),
                }
                if mode == "append":
                    entry["mode"] = "append"
                    entry["count"] = payload.get("count", 0)
                self._files_written.append(entry)
            else:
                existing["size_bytes"] = size
                existing["mtime"] = _now_iso()
                if mode == "append":
                    existing["count"] = payload.get("count", 0)
        except Exception as e:
            sys.stderr.write(f"[Diag] write {stage} failed: {e}\n")

    def _write_index(self) -> None:
        if not self._base or not self._files_written:
            return
        try:
            index_path = self._base / "index.json"
            index_data = {
                "task_id": self.task_id,
                "created_at": _now_iso(),
                "diag_enabled": _ENABLED,
                "diag_full": _FULL,
                "files": self._files_written,
            }
            temp_path = index_path.with_suffix(f"{index_path.suffix}.tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(index_data, f, ensure_ascii=False, indent=2)
            os.replace(temp_path, index_path)
        except Exception as e:
            sys.stderr.write(f"[Diag] write index failed: {e}\n")

    async def _writer_loop(self) -> None:
        assert self._queue is not None
        while True:
            try:
                stage, data = await self._queue.get()
            except asyncio.CancelledError:
                return
            try:
                self._write_file(stage, data)
            finally:
                self._queue.task_done()


# -----------------------------------------------------------------------------
# 进程级单例 + NullLogger
# -----------------------------------------------------------------------------

class _NullLogger:
    task_id = ""

    def start(self) -> None:
        return None

    def dump(self, *args: Any, **kwargs: Any) -> None:
        return None

    def dump_raw(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def finalize(self) -> None:
        return None


_loggers: dict[str, DiagLogger] = {}
_null = _NullLoggerSentinel = _NullLogger()

# Context variable — 当前 task_id (异步上下文, 调 skill 前 set, skill 内 get)
_current_task_id: contextvars.ContextVar[str] = contextvars.ContextVar("diag_current_task_id", default="")


def is_enabled() -> bool:
    return _ENABLED


def set_current_task(task_id: str) -> None:
    """在调 L1/L2 skill 前 set, skill 内部可用 get_current_task() 拿 task_id."""
    _current_task_id.set(task_id)


def get_current_task() -> str:
    return _current_task_id.get()


def get_diag(task_id: str) -> DiagLogger | _NullLogger:
    """Get or create the per-task DiagLogger. Returns _NullLogger when DIAG_ENABLED is false."""
    if not _ENABLED:
        return _null
    if task_id not in _loggers:
        _loggers[task_id] = DiagLogger(task_id)
    return _loggers[task_id]


def get_diag_auto() -> DiagLogger | _NullLogger:
    """从 contextvar 拿 task_id 后取 diag. Skill 内部用 (不破坏签名)."""
    tid = _current_task_id.get()
    if not tid:
        return _null
    return get_diag(tid)


def get_or_create_diag(task_id: str) -> DiagLogger:
    """Alias for get_diag that returns DiagLogger (or raises if disabled)."""
    logger = get_diag(task_id)
    if isinstance(logger, _NullLogger):
        # Build a real logger anyway — caller is going to call start()/finalize()
        return DiagLogger(task_id)
    return logger


# -----------------------------------------------------------------------------
# 工具: 截断 page_info (per 你的 #4 调整)
# -----------------------------------------------------------------------------

def slim_page_info(page_info: dict[str, Any]) -> dict[str, Any]:
    """Default: 保留 url/title/.../truncated; DIAG_FULL=true 才带 a11y_tree + screenshot."""
    if not isinstance(page_info, dict):
        return {"truncated": True, "original_type": str(type(page_info).__name__)}
    slim = {k: page_info[k] for k in PAGE_INFO_KEYS_DEFAULT if k in page_info}
    slim["interactive_count"] = slim.get("interactive_count") or len(page_info.get("interactive_elements", []) or [])
    if _FULL:
        a11y = page_info.get("a11y_tree") or page_info.get("accessibility")
        if a11y is not None:
            slim["a11y_tree_size"] = len(json.dumps(a11y, default=str))
            slim["a11y_tree_preview"] = _truncate_str(json.dumps(a11y, default=str), 500)
        if page_info.get("screenshot"):
            slim["screenshot_path"] = page_info["screenshot"] if isinstance(page_info["screenshot"], str) else "<base64 omitted>"
    return slim
