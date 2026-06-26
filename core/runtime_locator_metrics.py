from __future__ import annotations

"""Lightweight locator and semantic-extraction observability."""

from collections import Counter
from dataclasses import dataclass, field
import json
from typing import Any


@dataclass
class RuntimeLocatorMetrics:
    locator_attempts: int = 0
    locator_successes: int = 0
    locator_failures: int = 0
    locator_success_by_strategy: Counter[str] = field(default_factory=Counter)
    locator_failure_by_reason: Counter[str] = field(default_factory=Counter)
    semantic_observations: int = 0
    semantic_source_counts: Counter[str] = field(default_factory=Counter)

    def record_locator_attempt(self) -> None:
        self.locator_attempts += 1

    def record_locator_success(self, strategy: str) -> None:
        self.locator_successes += 1
        self.locator_success_by_strategy[strategy] += 1

    def record_locator_failure(self, reason: str) -> None:
        self.locator_failures += 1
        self.locator_failure_by_reason[reason] += 1

    def record_semantic_extraction(self, extraction: dict[str, Any] | None) -> None:
        if not isinstance(extraction, dict):
            return
        source = str(extraction.get("source") or "unknown").strip() or "unknown"
        self.semantic_observations += 1
        self.semantic_source_counts[source] += 1

    @property
    def locator_failure_rate(self) -> float:
        total = self.locator_successes + self.locator_failures
        if total <= 0:
            return 0.0
        return self.locator_failures / total

    def as_dict(self) -> dict[str, Any]:
        return {
            "locator_attempts": self.locator_attempts,
            "locator_successes": self.locator_successes,
            "locator_failures": self.locator_failures,
            "locator_failure_rate": round(self.locator_failure_rate, 4),
            "locator_success_by_strategy": dict(
                sorted(self.locator_success_by_strategy.items())
            ),
            "locator_failure_by_reason": dict(
                sorted(self.locator_failure_by_reason.items())
            ),
            "semantic_observations": self.semantic_observations,
            "semantic_source_counts": dict(
                sorted(self.semantic_source_counts.items())
            ),
        }

    def evidence_ref(self) -> str:
        return (
            "locator_metrics: "
            + json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True)
        )

    def has_signal(self) -> bool:
        return bool(self.locator_attempts or self.semantic_observations)
