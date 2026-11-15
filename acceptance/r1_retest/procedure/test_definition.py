"""One test of the targeted re-test (A-1 … A-4 of plans/R1-fix.md §9.2)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TestDefinition:
    """A re-test item: the plan step it repeats, its criteria and stages.

    ``repeatable`` tests start a real Claude run, so a new attempt needs an explicit
    ``r1-retest repeat`` (a repeated invocation never resubmits silently).
    """

    __test__ = False  # not a pytest test class

    test_id: str
    step: str
    title: str
    criteria: tuple[str, ...]
    required: bool
    stages: tuple[str, ...]
    expected: str
    repeatable: bool
