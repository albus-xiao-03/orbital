"""The targeted re-test (plans/R1-fix.md §9.2, decision D3) as data: tests, stages, checks.

The commands and expected outcomes are those of plans/R1.md, revision 6 (§14 C and §16 D-2,
D-7, D-9). The Claude-side helper functions wrap the plan's own commands word for word, so that
their output can be pasted into the harness and carries its own UTC time.
"""

from __future__ import annotations

from typing import ClassVar

from r1_retest.procedure.manual_check import ManualCheck
from r1_retest.procedure.operation import TASK_PLACEHOLDER, Operation
from r1_retest.procedure.stage import Stage
from r1_retest.procedure.test_definition import TestDefinition


class RetestProcedure:
    """Everything the harness knows about the re-test, as class-level constants."""

    SLEEP_60: ClassVar[str] = 'Run the shell command "sleep 60", then reply with the word SLEPT.'
    SERVER_COMMAND: ClassVar[str] = (
        "orbital-bridge serve --port 8765 --workdir ~/orbital-acceptance/workdir "
        ">> ~/orbital-acceptance/serve.log 2>&1"
    )
    TAIL_COMMAND: ClassVar[str] = "tail -f ~/orbital-acceptance/serve.log"
    PROCESS_CHECK: ClassVar[str] = (
        "date -u +%FT%TZ; pgrep -af -- '--output-format json --session[-]id' || echo none; "
        "pgrep -af '^sleep 6[0]$' || echo none"
    )
    CLAUDE_SETUP: ClassVar[str] = (
        "\n".join(
            (
                "# Claude sandbox, second terminal: define these once (paste the whole block).",
                "# orbital_check is plans/R1.md §16's timed process check, word for word.",
                "orbital_check() {",
                (
                    "  date -u +%FT%TZ; "
                    "pgrep -af -- '--output-format json --session[-]id' || echo none; "
                    "pgrep -af '^sleep 6[0]$' || echo none"
                ),
                "}",
                "# usage: orbital_evidence <test> <task_id>; "
                "serve.log lines and the transcript check of §16",
                "orbital_evidence() {",
                '  echo "ORBITAL-EVIDENCE $1 $2 utc=$(date -u +%FT%TZ) offset=$(date +%z)"',
                (
                    '  grep -n -E "$2|orbital\\.bridges\\.cli: (listening|stopping|stopped)" '
                    "~/orbital-acceptance/serve.log | tail -n 60"
                ),
                '  echo "ORBITAL-TRANSCRIPT"',
                '  ls -l --time-style=full-iso ~/.claude/projects/*/"$2".jsonl 2>&1',
                '  echo "ORBITAL-SLEPT"',
                '  grep -c \'"text":"SLEPT"\' ~/.claude/projects/*/"$2".jsonl 2>&1',
                '  echo "ORBITAL-END"',
                "}",
                "# usage: orbital_source <repository copy>; "
                "the commit and source digest the server runs",
                "orbital_source() {",
                '  echo "ORBITAL-SOURCE utc=$(date -u +%FT%TZ)"',
                '  git -C "$1" rev-parse HEAD 2>&1',
                "  python3 -c 'import hashlib, pathlib, sys",
                "r = pathlib.Path(sys.argv[1]); d = hashlib.sha256()",
                'for p in sorted(r.rglob("*.py")):',
                '    if "__pycache__" in p.parts: continue',
                (
                    '    d.update(p.relative_to(r).as_posix().encode() + b"\\0"); '
                    'd.update(hashlib.sha256(p.read_bytes()).hexdigest().encode() + b"\\n")'
                ),
                'print("digest", d.hexdigest())\' "$1/src/orbital"',
                '  echo "ORBITAL-END"',
                "}",
            )
        )
        + "\n"
    )

    TESTS: ClassVar[tuple[TestDefinition, ...]] = (
        TestDefinition(
            "A-3",
            "D-2",
            "Network path and mutual authentication",
            ("AC1", "AC6"),
            True,
            ("a3",),
            '{"ok": true, "error": null}, exit 0',
            False,
        ),
        TestDefinition(
            "A-2",
            "D-7",
            "Confirmed execution timeout",
            ("AC4", "AC6"),
            True,
            ("a2",),
            "timed_out / execution_timeout, exit 3; the timed check within 30 s prints none "
            "twice; serve.log shows the timeout; the transcript ends at the timeout with no "
            "SLEPT reply",
            True,
        ),
        TestDefinition(
            "A-1",
            "D-9",
            "Interrupted communication, graceful shutdown and restart",
            ("AC4", "AC6"),
            True,
            ("a1-submit", "a1-down", "a1-up"),
            "D-9a running, exit 6; the timed check within 30 s of the stop prints none twice; "
            "serve.log records stopping (SIGINT), exit 143, execution_cancelled and stopped; "
            "the transcript ends at the stop with no SLEPT reply; D-9b communication_error "
            "(gateway_error, connection_failed or connection_interrupted), exit 4; D-9c "
            "communication_error / unknown_task, exit 4, naming the new start time",
            True,
        ),
        TestDefinition(
            "A-4",
            "D-9, stopped by closing the terminal",
            "Closing the server's terminal is a graceful stop (optional)",
            (),
            False,
            ("a4-submit", "a4-down", "a4-up"),
            "as A-1, with stopping (SIGHUP)",
            True,
        ),
    )

    OPERATIONS: ClassVar[tuple[Operation, ...]] = (
        Operation("D-2", "A-3", "a3", "signed ping", ("ping",), None, (None,), 0, 60.0),
        Operation(
            "D-7",
            "A-2",
            "a2",
            "submit with a 10 s execution timeout and wait for the result",
            ("submit", "--execution-timeout", "10", SLEEP_60),
            "timed_out",
            ("execution_timeout",),
            3,
            300.0,
            starts_claude=True,
        ),
        Operation(
            "D-9a",
            "A-1",
            "a1-submit",
            "submit without waiting",
            ("submit", "--max-wait", "0", SLEEP_60),
            "running",
            (None,),
            6,
            60.0,
            starts_claude=True,
        ),
        Operation(
            "D-9b",
            "A-1",
            "a1-down",
            "wait up to 20 s while the server is stopped",
            ("wait", TASK_PLACEHOLDER, "--max-wait", "20"),
            "communication_error",
            ("gateway_error", "connection_failed", "connection_interrupted"),
            4,
            180.0,
            uses_task=True,
        ),
        Operation(
            "D-9c",
            "A-1",
            "a1-up",
            "poll once after the restart",
            ("wait", TASK_PLACEHOLDER, "--max-wait", "0"),
            "communication_error",
            ("unknown_task",),
            4,
            120.0,
            uses_task=True,
            checks_restart=True,
        ),
        Operation(
            "A-4a",
            "A-4",
            "a4-submit",
            "submit without waiting",
            ("submit", "--max-wait", "0", SLEEP_60),
            "running",
            (None,),
            6,
            60.0,
            starts_claude=True,
        ),
        Operation(
            "A-4b",
            "A-4",
            "a4-down",
            "wait up to 20 s while the server is stopped",
            ("wait", TASK_PLACEHOLDER, "--max-wait", "20"),
            "communication_error",
            ("gateway_error", "connection_failed", "connection_interrupted"),
            4,
            180.0,
            uses_task=True,
        ),
        Operation(
            "A-4c",
            "A-4",
            "a4-up",
            "poll once after the restart",
            ("wait", TASK_PLACEHOLDER, "--max-wait", "0"),
            "communication_error",
            ("unknown_task",),
            4,
            120.0,
            uses_task=True,
            checks_restart=True,
        ),
    )

    STAGES: ClassVar[tuple[Stage, ...]] = (
        Stage(
            "a3",
            "A-3",
            "A-3 / D-2: signed ping",
            "D-2",
            None,
            False,
            (
                "Claude sandbox, server terminal: the server runs with the corrected command "
                "(plans/R1.md §14 C), started after updating to the fixed commit:",
                "    {server_command}",
                "Claude sandbox, second terminal: paste the helper functions "
                "(r1-retest claude-setup), then follow the log with: {tail_command}",
            ),
            (
                "Next: stage a2 (A-2 / D-7). Before running it, type orbital_check in the "
                "second Claude-sandbox terminal without pressing Enter.",
            ),
        ),
        Stage(
            "a2",
            "A-2",
            "A-2 / D-7: confirmed execution timeout",
            "D-7",
            "reachable",
            True,
            (
                "Claude sandbox, second terminal: orbital_check is typed in, not yet run.",
                "This stage starts 1 real Claude run (sleep 60, ended by the 10 s execution "
                "timeout) and takes about 15 s.",
            ),
            (
                "Claude sandbox, second terminal, NOW (within 30 s of this result): press Enter "
                "on orbital_check.",
                "ChatGPT sandbox: r1-retest record D-7.process-check  (paste the output, then "
                "Ctrl-D on a new line)",
                "Claude sandbox, any time later: orbital_evidence D-7 {task_id}",
                "ChatGPT sandbox: r1-retest record D-7.claude-evidence  (paste, then Ctrl-D)",
                "Next: stage a1-submit (A-1 / D-9). Read its instructions first: r1-retest status",
            ),
        ),
        Stage(
            "a1-submit",
            "A-1",
            "A-1 / D-9a: submit the task that the stop interrupts",
            "D-9a",
            "reachable",
            True,
            (
                "Read this before running: right after this stage returns,",
                "  1. Claude sandbox, server terminal: press Ctrl-C within about 10 s;",
                "  2. Claude sandbox, second terminal, as soon as the server has exited "
                "(within 30 s): orbital_check, then tail -n 6 ~/orbital-acceptance/serve.log;",
                "  3. do not restart the server yet.",
                "This stage starts 1 real Claude run (sleep 60).",
            ),
            (
                "Claude sandbox, server terminal, NOW: press Ctrl-C (within about 10 s).",
                "Claude sandbox, second terminal, as soon as the server has exited (within "
                "30 s): orbital_check",
                "ChatGPT sandbox: r1-retest record D-9.process-check  (paste, then Ctrl-D)",
                "Do not restart the server yet. Next: r1-retest run a1-down",
            ),
        ),
        Stage(
            "a1-down",
            "A-1",
            "A-1 / D-9b: poll while the server is stopped",
            "D-9b",
            "unreachable",
            False,
            ("Claude sandbox: the server was stopped with Ctrl-C and is not running.",),
            (
                "Claude sandbox, server terminal: restart the server normally:",
                "    {server_command}",
                "Next: r1-retest run a1-up",
            ),
        ),
        Stage(
            "a1-up",
            "A-1",
            "A-1 / D-9c: poll once after the restart",
            "D-9c",
            "reachable",
            False,
            ("Claude sandbox: the server was restarted with the corrected command.",),
            (
                "Claude sandbox, second terminal, now: orbital_evidence D-9 {task_id}",
                "ChatGPT sandbox: r1-retest record D-9.claude-evidence  (paste, then Ctrl-D)",
                "Recommended: orbital_source <repository copy> in the Claude sandbox, then "
                "r1-retest record claude-source",
                "Then: r1-retest report",
            ),
        ),
        Stage(
            "a4-submit",
            "A-4",
            "A-4 (optional): submit the task that a closed terminal interrupts",
            "A-4a",
            "reachable",
            True,
            (
                "Optional SIGHUP check. Read this before running: right after this stage returns,",
                "  1. Claude sandbox: CLOSE the server's terminal (window or session) within "
                "about 10 s, instead of pressing Ctrl-C;",
                "  2. Claude sandbox, second terminal, within 30 s: orbital_check;",
                "  3. do not restart the server yet.",
                "This stage starts 1 real Claude run (sleep 60).",
            ),
            (
                "Claude sandbox, NOW: close the server's terminal (within about 10 s).",
                "Claude sandbox, second terminal, within 30 s: orbital_check",
                "ChatGPT sandbox: r1-retest record A-4.process-check  (paste, then Ctrl-D)",
                "Next: r1-retest run a4-down",
            ),
        ),
        Stage(
            "a4-down",
            "A-4",
            "A-4 (optional): poll while the server is stopped",
            "A-4b",
            "unreachable",
            False,
            ("Claude sandbox: the server's terminal was closed, and the server is not running.",),
            (
                "Claude sandbox, in a new terminal: restart the server normally:",
                "    {server_command}",
                "Next: r1-retest run a4-up",
            ),
        ),
        Stage(
            "a4-up",
            "A-4",
            "A-4 (optional): poll once after the restart",
            "A-4c",
            "reachable",
            False,
            ("Claude sandbox: the server was restarted with the corrected command.",),
            (
                "Claude sandbox, second terminal: orbital_evidence A-4 {task_id}",
                "ChatGPT sandbox: r1-retest record A-4.claude-evidence  (paste, then Ctrl-D)",
                "Then: r1-retest report",
            ),
        ),
    )

    CHECKS: ClassVar[tuple[ManualCheck, ...]] = (
        ManualCheck(
            "D-7.process-check",
            "A-2",
            "process-check",
            "No bridge-started Claude Code run and no sleep 60 left after the timeout",
            "orbital_check",
            "within 30 s of the D-7 result (stage a2)",
            True,
            reference="timeout",
        ),
        ManualCheck(
            "D-7.claude-evidence",
            "A-2",
            "claude-evidence",
            "serve.log records the timeout; the transcript ends at the timeout",
            "orbital_evidence D-7 {task_id}",
            "any time after stage a2",
            True,
        ),
        ManualCheck(
            "D-9.process-check",
            "A-1",
            "process-check",
            "No bridge-started Claude Code run and no sleep 60 left after the stop",
            "orbital_check",
            "within 30 s of stopping the server with Ctrl-C",
            True,
            reference="stop",
        ),
        ManualCheck(
            "D-9.claude-evidence",
            "A-1",
            "claude-evidence",
            "serve.log records the graceful stop and the restart; the transcript ends at the stop",
            "orbital_evidence D-9 {task_id}",
            "after the restart (stage a1-up)",
            True,
            expect_signal="SIGINT",
        ),
        ManualCheck(
            "A-4.process-check",
            "A-4",
            "process-check",
            "No bridge-started Claude Code run and no sleep 60 left after the terminal closed",
            "orbital_check",
            "within 30 s of closing the server's terminal",
            False,
            reference="stop",
        ),
        ManualCheck(
            "A-4.claude-evidence",
            "A-4",
            "claude-evidence",
            "serve.log records the SIGHUP stop and the restart; the transcript ends at the stop",
            "orbital_evidence A-4 {task_id}",
            "after the restart (stage a4-up)",
            False,
            expect_signal="SIGHUP",
        ),
        ManualCheck(
            "claude-source",
            None,
            "claude-source",
            "The Claude sandbox runs the fixed implementation (commit and source digest)",
            "orbital_source <repository copy in the Claude sandbox>",
            "any time",
            False,
        ),
    )

    CARRIED_FORWARD: ClassVar[tuple[tuple[str, str, tuple[str, ...], str], ...]] = (
        (
            "P-1",
            "Public API and command line in the ChatGPT sandbox",
            ("AC7",),
            "the 11 public names import from orbital.bridges; "
            "--help lists serve, submit, wait, ping",
        ),
        (
            "D-1",
            "Policy block",
            ("AC4",),
            "communication_error / network_policy_blocked, exit 4; the proxy's text labelled "
            "unverified",
        ),
        (
            "D-3",
            "Unauthorized requests are rejected",
            ("AC5", "AC6"),
            "D-3a unverified_auth_rejection, exit 4; D-3b HTTP 401 with WWW-Authenticate: "
            "ORBITAL-HMAC-SHA256; serve.log shows both authentication failures; no Claude run",
        ),
        (
            "D-4",
            "Delegation and response retrieval",
            ("AC1", "AC2", "AC3", "AC6"),
            "succeeded, response ORBITAL-OK, exit 0; "
            "serve.log shows the task accepted and finished",
        ),
        (
            "D-5",
            "Autonomous execution, confined to the Claude side",
            ("AC2", "AC6"),
            "succeeded, exit 0; the file holds ORBITAL-R1 in the Claude sandbox and is absent in "
            "the ChatGPT sandbox",
        ),
        (
            "D-6",
            "Running out of wait budget does not imply termination",
            ("AC3", "AC4", "AC6"),
            "D-6a running / wait_deadline_reached, exit 6; "
            "D-6b succeeded, response SLEPT, the same task id",
        ),
        (
            "D-8",
            "Execution failure on the Claude side",
            ("AC4", "AC6"),
            "failed / claude_error, exit 1, with api_error in the message",
        ),
    )
    SUPERSEDED: ClassVar[tuple[tuple[str, str], ...]] = (
        ("D-2", "passed in the earlier run; re-tested as A-3"),
        (
            "D-7",
            "passed in the earlier run, but its process checks were too late to show "
            "termination (qas/R1.md QA-03); re-tested as A-2",
        ),
        (
            "D-9",
            "failed in the earlier run (serve.log lacked the stop record, QA-01); re-tested as A-1",
        ),
    )

    CRITERIA: ClassVar[tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...]] = (
        (
            "AC1",
            "A ChatGPT-side client submits a prompt through orbital.bridges",
            ("A-3",),
            ("D-4",),
        ),
        (
            "AC2",
            "The Claude side receives the prompt and executes it autonomously",
            (),
            ("D-4", "D-5"),
        ),
        ("AC3", "The response returns with the correct task id", (), ("D-4", "D-6")),
        (
            "AC4",
            "Failures, interrupted communication and timeouts give distinguishable "
            "structured results",
            ("A-2", "A-1"),
            ("D-1", "D-6", "D-8"),
        ),
        ("AC5", "Unauthorized task requests are rejected", (), ("D-3",)),
        (
            "AC6",
            "Works across two separate Docker sandboxes without Docker management or shared "
            "filesystems",
            ("A-3", "A-2", "A-1"),
            ("D-3", "D-4", "D-5", "D-6", "D-8"),
        ),
        ("AC7", "All bridge functionality is accessible through orbital.bridges", (), ("P-1",)),
    )

    @classmethod
    def test(cls, test_id: str) -> TestDefinition:
        for test in cls.TESTS:
            if test.test_id == test_id:
                return test
        raise KeyError(test_id)

    @classmethod
    def stage(cls, stage_id: str) -> Stage:
        for stage in cls.STAGES:
            if stage.stage_id == stage_id:
                return stage
        raise KeyError(stage_id)

    @classmethod
    def operation(cls, op_id: str) -> Operation:
        for operation in cls.OPERATIONS:
            if operation.op_id == op_id:
                return operation
        raise KeyError(op_id)

    @classmethod
    def check(cls, check_id: str) -> ManualCheck:
        for check in cls.CHECKS:
            if check.check_id == check_id:
                return check
        raise KeyError(check_id)

    @classmethod
    def checks_of(cls, test_id: str | None) -> tuple[ManualCheck, ...]:
        return tuple(c for c in cls.CHECKS if c.test_id == test_id)

    @classmethod
    def stages_of(cls, test_id: str) -> tuple[Stage, ...]:
        return tuple(cls.stage(s) for s in cls.test(test_id).stages)

    @classmethod
    def render(cls, line: str, task_id: str | None) -> str:
        return (
            line.replace("{server_command}", cls.SERVER_COMMAND)
            .replace("{tail_command}", cls.TAIL_COMMAND)
            .replace("{task_id}", task_id or "<task_id>")
        )
