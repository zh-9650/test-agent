"""Read-only memory recall helpers for L2 design prompts.

MemoryContext is intentionally hint-only. It must never become a
RequirementFact source, source registry entry, or traceability basis.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from pydantic import BaseModel, Field
from sqlalchemy import func, select

from database.connection import async_session
from database.models import AgentMemory


class MemoryContext(BaseModel):
    """A sanitized, read-only memory item selected for prompt context."""

    scope_type: str = Field(description="Memory scope type, e.g. domain/global")
    scope_value: str = Field(description="Scope value, e.g. example.com or *")
    memory_key: str = Field(description="Short memory label")
    memory_value: str = Field(description="Sanitized memory content")
    source_domain: str = Field(default="", description="Domain associated with the memory")
    provenance: str = Field(description="Non-authoritative origin of this memory item")


_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b("
    r"password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|"
    r"refresh[_-]?token|authorization|bearer|cookie|session(?:id)?|jwt|"
    r"private[_-]?key|credential"
    r")\b\s*[:=]\s*\S+"
)
_SECRET_KEYWORD_RE = re.compile(
    r"(?i)\b("
    r"password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|"
    r"refresh[_-]?token|authorization|bearer|cookie|session(?:id)?|jwt|"
    r"private[_-]?key|credential"
    r")\b|"
    r"\u5bc6\u7801|\u5bc6\u94a5|\u4ee4\u724c|\u51ed\u8bc1"
)
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN (?:RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----"
)
_JWT_RE = re.compile(
    r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
)
_LONG_TOKEN_RE = re.compile(r"\b(?:[A-Fa-f0-9]{32,}|[A-Za-z0-9+/=_-]{40,})\b")


def _normalize_domain(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if not raw or raw == "*":
        return ""

    parsed = urlparse(raw if "://" in raw else f"//{raw}")
    host = parsed.hostname
    if not host:
        host = raw.split("/", 1)[0].split(":", 1)[0]
    return host.rstrip(".")


def _clean_prompt_text(value: str, *, max_length: int = 700) -> str:
    text = " ".join((value or "").split())
    if len(text) <= max_length:
        return text
    return f"{text[:max_length - 3]}..."


def _looks_secret_like(memory_key: str, memory_value: str) -> bool:
    combined = f"{memory_key}\n{memory_value}"
    if _PRIVATE_KEY_RE.search(combined) or _JWT_RE.search(combined):
        return True
    if _SECRET_ASSIGNMENT_RE.search(combined):
        return True
    if _SECRET_KEYWORD_RE.search(memory_key or ""):
        return True
    return bool(_LONG_TOKEN_RE.search(memory_value or ""))


def _is_global_memory(memory: AgentMemory) -> bool:
    scope_type = (memory.scope_type or "").strip().lower()
    scope_value = (memory.scope_value or "").strip()
    return scope_type == "global" or scope_value == "*"


def _is_exact_domain_memory(memory: AgentMemory, target_domain: str) -> bool:
    if not target_domain:
        return False
    if (memory.scope_type or "").strip().lower() != "domain":
        return False
    candidates = {
        _normalize_domain(memory.scope_value),
        _normalize_domain(memory.source_domain),
    }
    return target_domain in candidates


def _to_context(memory: AgentMemory) -> MemoryContext | None:
    memory_key = (memory.memory_key or "").strip()
    memory_value = (memory.memory_value or "").strip()
    if not memory_key or not memory_value:
        return None
    if _looks_secret_like(memory_key, memory_value):
        return None

    source_domain = (
        _normalize_domain(memory.source_domain)
        or _normalize_domain(memory.scope_value)
    )
    return MemoryContext(
        scope_type=(memory.scope_type or "").strip().lower(),
        scope_value=(memory.scope_value or "").strip(),
        memory_key=memory_key,
        memory_value=memory_value,
        source_domain=source_domain,
        provenance=f"agent_memory:{memory.id}",
    )


async def recall_memory_context(
    target_url: str,
    limit: int = 5,
) -> list[MemoryContext]:
    """Recall read-only memory for a target URL.

    Domain-scoped exact matches are returned first. If fewer than ``limit``
    domain memories survive filtering, global memories fill the remainder.
    Empty values and secret-like content are excluded.
    """

    if limit <= 0:
        return []

    target_domain = _normalize_domain(target_url)
    async with async_session() as session:
        result = await session.execute(
            select(AgentMemory)
            .where(func.lower(AgentMemory.scope_type).in_(("domain", "global")))
            .order_by(AgentMemory.updated_at.desc(), AgentMemory.created_at.desc())
        )
        memories = list(result.scalars().all())

    domain_contexts: list[MemoryContext] = []
    global_contexts: list[MemoryContext] = []
    seen: set[tuple[str, str, str, str]] = set()

    for memory in memories:
        context = _to_context(memory)
        if context is None:
            continue

        dedupe_key = (
            context.scope_type,
            context.scope_value.strip().lower(),
            context.memory_key.strip().casefold(),
            context.memory_value.strip(),
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        if _is_exact_domain_memory(memory, target_domain):
            domain_contexts.append(context)
        elif _is_global_memory(memory):
            global_contexts.append(context)

    selected = domain_contexts[:limit]
    if len(selected) < limit:
        selected.extend(global_contexts[: limit - len(selected)])
    return selected


def format_memory_context_for_prompt(contexts: list[MemoryContext]) -> str:
    """Format MemoryContext items as a hint-only prompt section."""

    safe_contexts = [
        context
        for context in contexts
        if context.memory_key.strip()
        and context.memory_value.strip()
        and not _looks_secret_like(context.memory_key, context.memory_value)
    ]
    if not safe_contexts:
        return ""

    lines = [
        "<memory_context>",
        "Usage: hint-only, non-authoritative context.",
        "Do not use MemoryContext as RequirementFact source material.",
        "Do not cite MemoryContext in source_references, source_registry, or traceability.",
        "If MemoryContext conflicts with RequirementFact, RequirementAssertion, or SystemMap evidence, ignore MemoryContext.",
        "Items:",
    ]
    for index, context in enumerate(safe_contexts, start=1):
        scope = context.source_domain or context.scope_value
        lines.append(
            f"{index}. [{context.scope_type}:{scope}] "
            f"{_clean_prompt_text(context.memory_key, max_length=140)}: "
            f"{_clean_prompt_text(context.memory_value)} "
            f"(provenance: {context.provenance})"
        )
    lines.append("</memory_context>")
    return "\n".join(lines)
