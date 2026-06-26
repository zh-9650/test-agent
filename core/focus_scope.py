"""Helpers for deriving and applying focus-area scope terms."""

from __future__ import annotations

import re
from urllib.parse import urlparse

_FOCUS_ALIAS_MAP: dict[str, set[str]] = {
    "dashboard": {"dashboard", "数据看板", "看板"},
    "reports": {"reports", "report", "能力趋势", "能力趋势洞察", "趋势洞察"},
    "calibration": {"calibration", "数据校准", "校准"},
}


def expand_focus_terms(
    focus_areas: str | list[str] | None,
    target_url: str = "",
) -> set[str]:
    raw_terms: list[str] = []
    if isinstance(focus_areas, str):
        raw_terms.extend(re.split(r"[\s,;，；/|]+", focus_areas))
    elif isinstance(focus_areas, list):
        for item in focus_areas:
            if item:
                raw_terms.extend(re.split(r"[\s,;，；/|]+", str(item)))

    parsed = urlparse(target_url or "")
    raw_terms.extend(part for part in parsed.path.split("/") if part)

    expanded: set[str] = set()
    for term in raw_terms:
        normalized = term.strip().casefold()
        if not normalized:
            continue
        expanded.add(normalized)
        expanded.update(_FOCUS_ALIAS_MAP.get(normalized, set()))
    return expanded
