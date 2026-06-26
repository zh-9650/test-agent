"""Lossless CandidateTestCase to runtime protocol adapter."""

from core.interfaces import CandidateTestCase, RuntimeExecutableCase


def adapt_single_case(case: CandidateTestCase) -> RuntimeExecutableCase:
    """Adapt fields without inferring roles, preconditions, steps, or IDs."""
    return RuntimeExecutableCase(
        id=case.id,
        objective=case.goal,
        expected=case.expected_result,
        hints=case.execution_hint,
        preconditions=case.preconditions,
        trace_references=case.trace_references,
        priority=case.priority,
        required_roles=case.required_roles,
    )


def adapt_executable_cases(
    candidate_cases: list[CandidateTestCase],
) -> list[RuntimeExecutableCase]:
    return [adapt_single_case(case) for case in candidate_cases]
