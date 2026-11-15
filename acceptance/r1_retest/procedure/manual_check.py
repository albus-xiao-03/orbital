"""A Claude-side observation that the operator makes and imports into the harness."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ManualCheck:
    """An observation of the Claude sandbox, recorded with ``r1-retest record <check_id>``.

    ``kind`` is ``process-check`` (the timed check of plans/R1.md §16, D-7 and D-9),
    ``claude-evidence`` (serve.log lines and the transcript check) or ``claude-source`` (the code
    the server runs). ``reference`` names the Claude-side event a process check is timed against:
    ``timeout`` (D-7) or ``stop`` (D-9, A-4). ``expect_signal`` is the stop signal that
    ``serve.log`` must name (``SIGINT`` for Ctrl-C, ``SIGHUP`` for a closed terminal).
    """

    check_id: str
    test_id: str | None
    kind: str
    title: str
    command: str
    when: str
    required: bool
    reference: str | None = None
    expect_signal: str | None = None
