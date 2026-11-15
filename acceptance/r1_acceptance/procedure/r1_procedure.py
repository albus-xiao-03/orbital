"""R1Procedure: the dual-sandbox acceptance procedure of ``plans/R1.md`` section 16, as data."""

from __future__ import annotations

from typing import ClassVar

from r1_acceptance.models.manual_check import ManualCheck
from r1_acceptance.models.phase_definition import PhaseDefinition
from r1_acceptance.models.stage_definition import StageDefinition
from r1_acceptance.models.step_definition import StepDefinition


class R1Procedure:
    """The steps, phases, manual checks, stages and criteria of the R1 acceptance procedure.

    Prompts, wait budgets and expected results are those of ``plans/R1.md`` section 16. Each
    submission is made with ``--max-wait 0`` and then observed with ``wait``. That is the same
    exchange as a waiting ``submit`` (one POST, then polling GETs), but the task id is recorded
    as soon as the server accepts the task, so an interrupted stage resumes by polling and never
    submits a task twice. Criteria follow the plan's traceability table (section 4): AC6 is
    supported by D-2 ... D-9, and AC7 by the local preflight P-1.
    """

    OK_PROMPT: ClassVar[str] = "Reply with exactly: ORBITAL-OK"
    FILE_PROMPT: ClassVar[str] = (
        "Create a file named orbital-acceptance.txt in the current working directory "
        "containing exactly the text ORBITAL-R1, then reply with the word DONE."
    )
    SLEEP_30_PROMPT: ClassVar[str] = (
        'Run the shell command "sleep 30", then reply with the word SLEPT.'
    )
    SLEEP_60_PROMPT: ClassVar[str] = (
        'Run the shell command "sleep 60", then reply with the word SLEPT.'
    )
    BRIDGE_RUNS_CHECK: ClassVar[str] = (
        "pgrep -af -- '--output-format json --session[-]id' || echo none"
    )
    SLEEP_CHECK: ClassVar[str] = "pgrep -af '^sleep 6[0]$' || echo none"
    SERVE: ClassVar[str] = (
        "orbital-bridge serve --port 8765 --workdir {claude_workdir} 2>&1 | tee -a {serve_log}"
    )
    INVALID_MODEL_ARGS: ClassVar[str] = (
        "ORBITAL_BRIDGE_CLAUDE_ARGS='--permission-prompts none --model orbital-no-such-model' \\"
    )

    CRITERIA: ClassVar[tuple[tuple[str, str], ...]] = (
        ("AC1", "A ChatGPT-side client submits a prompt through orbital.bridges"),
        (
            "AC2",
            "The Claude side receives the prompt and starts autonomous execution without the "
            "bridge doing the task",
        ),
        ("AC3", "The response comes back with the correct task id"),
        (
            "AC4",
            "Failed tasks, interrupted communication and timeouts give distinguishable "
            "structured results",
        ),
        ("AC5", "Unauthorized requests are rejected"),
        (
            "AC6",
            "Works across two separate Docker sandboxes with no Docker management and no "
            "shared-filesystem communication",
        ),
        ("AC7", "All bridge functionality is reachable through orbital.bridges"),
    )

    STEPS: ClassVar[tuple[StepDefinition, ...]] = (
        StepDefinition(
            "P-1",
            "Public API and command line in the ChatGPT sandbox",
            "The public API imports from orbital.bridges, and the orbital-bridge command line "
            "starts, from the source under test in this sandbox.",
            "Python 3.11 or newer; the 11 public names import from orbital.bridges; "
            "python -m orbital.bridges --help lists serve, submit, wait and ping.",
            ("AC7",),
        ),
        StepDefinition(
            "D-1",
            "Policy block",
            "While the network policy is closed, the sandbox proxy blocks the bridge, and the "
            "client reports it without trusting the unsigned reply.",
            "ok false; communication_error / network_policy_blocked; exit 4; the message "
            "quotes the proxy's text, labelled as unverified.",
            ("AC4",),
            optional=True,
        ),
        StepDefinition(
            "D-2",
            "Network path and mutual authentication",
            "A signed request crosses the real proxy with its headers intact, and both "
            "directions authenticate. No Claude run.",
            '{"ok": true, "error": null}; exit 0.',
            ("AC1", "AC6"),
        ),
        StepDefinition(
            "D-3",
            "Unauthorized requests are rejected",
            "Requests with a wrong key or without credentials are rejected, and a rejection "
            "that cannot be verified is not reported as authoritative.",
            "D-3a: communication_error / unverified_auth_rejection, exit 4. D-3b: HTTP 401 "
            "with WWW-Authenticate: ORBITAL-HMAC-SHA256. serve.log shows the authentication "
            "failures, and no Claude run was started.",
            ("AC5", "AC6"),
        ),
        StepDefinition(
            "D-4",
            "Delegation and response retrieval",
            "A prompt is delegated to Claude Code, and its response comes back with the same "
            "task id.",
            "succeeded; response ORBITAL-OK; exit 0; serve.log shows the same task id accepted "
            "and finished.",
            ("AC1", "AC2", "AC3", "AC6"),
            claude_runs=1,
        ),
        StepDefinition(
            "D-5",
            "Autonomous execution, confined to the Claude side",
            "Claude Code acts autonomously with its own tools, and the effect stays in the "
            "Claude sandbox.",
            "succeeded; exit 0; the Claude sandbox has the file containing ORBITAL-R1, and the "
            "ChatGPT sandbox has no such file.",
            ("AC2", "AC6"),
            claude_runs=1,
        ),
        StepDefinition(
            "D-6",
            "Running out of wait budget does not imply termination",
            "A client that stops waiting reports running, never an ended task, and the same "
            "task can be retrieved later.",
            "D-6a: running / wait_deadline_reached, exit 6. D-6b: succeeded, response SLEPT, "
            "exit 0, the same task id.",
            ("AC3", "AC4", "AC6"),
            claude_runs=1,
        ),
        StepDefinition(
            "D-7",
            "Confirmed execution timeout",
            "The server enforces the execution timeout and reports timed_out only after the "
            "process tree has been terminated.",
            "timed_out / execution_timeout; exit 3; no bridge-started Claude run and no "
            "sleep 60 left in the Claude sandbox.",
            ("AC4", "AC6"),
            claude_runs=1,
        ),
        StepDefinition(
            "D-8",
            "Execution failure on the Claude side",
            "A failure reported by Claude Code is reported as failed, never as succeeded.",
            "failed / claude_error; exit 1; api_error in the message.",
            ("AC4", "AC6"),
            claude_runs=1,
        ),
        StepDefinition(
            "D-9",
            "Interrupted communication and restart",
            "Losing the server mid-task and restarting it give communication errors, never a "
            "false outcome, and nothing is left running.",
            "D-9a: running, exit 6. At the stop: the task cancelled in serve.log, nothing left "
            "running. D-9b: communication_error (gateway_error, connection_failed or "
            "connection_interrupted), exit 4. D-9c: communication_error / unknown_task, exit 4, "
            "naming the new server start time.",
            ("AC4", "AC6"),
            claude_runs=1,
        ),
    )

    PHASES: ClassVar[tuple[PhaseDefinition, ...]] = (
        PhaseDefinition(
            "P-1",
            "P-1",
            "p1",
            PhaseDefinition.LOCAL_PACKAGE,
            "import the public API and run python -m orbital.bridges --help",
            PhaseDefinition.ON_FAILURE,
            expect_status="passed",
        ),
        PhaseDefinition(
            "D-1",
            "D-1",
            "d1",
            PhaseDefinition.PING,
            "ping while the network policy is closed",
            PhaseDefinition.ON_FAILURE,
            expect_status="communication_error",
            expect_codes=("network_policy_blocked",),
            expect_exit=4,
            expect_fragments=("unverified",),
        ),
        PhaseDefinition(
            "D-2",
            "D-2",
            "d2-d3",
            PhaseDefinition.PING,
            "ping",
            PhaseDefinition.ON_FAILURE,
            expect_status="ok",
            expect_exit=0,
        ),
        PhaseDefinition(
            "D-3a",
            "D-3",
            "d2-d3",
            PhaseDefinition.WRONG_KEY_PING,
            "ping with a random wrong key",
            PhaseDefinition.ON_FAILURE,
            expect_status="communication_error",
            expect_codes=("unverified_auth_rejection",),
            expect_exit=4,
        ),
        PhaseDefinition(
            "D-3b",
            "D-3",
            "d2-d3",
            PhaseDefinition.UNSIGNED_POST,
            "POST /v1/tasks without credentials (like curl -i)",
            PhaseDefinition.ON_FAILURE,
            expect_status="HTTP 401",
            expect_header=("WWW-Authenticate", "ORBITAL-HMAC-SHA256"),
        ),
        PhaseDefinition(
            "D-4.submit",
            "D-4",
            "d4-d7",
            PhaseDefinition.SUBMIT,
            "submit the prompt",
            PhaseDefinition.NEVER,
            prompt=OK_PROMPT,
            expect_status="running",
            expect_exit=6,
        ),
        PhaseDefinition(
            "D-4.wait",
            "D-4",
            "d4-d7",
            PhaseDefinition.WAIT_SETTLE,
            "wait for the result",
            PhaseDefinition.UNTIL_SETTLED,
            max_wait=600,
            expect_status="succeeded",
            expect_exit=0,
            expect_response="ORBITAL-OK",
        ),
        PhaseDefinition(
            "D-5.submit",
            "D-5",
            "d4-d7",
            PhaseDefinition.SUBMIT,
            "submit the prompt",
            PhaseDefinition.NEVER,
            prompt=FILE_PROMPT,
            expect_status="running",
            expect_exit=6,
        ),
        PhaseDefinition(
            "D-5.wait",
            "D-5",
            "d4-d7",
            PhaseDefinition.WAIT_SETTLE,
            "wait for the result",
            PhaseDefinition.UNTIL_SETTLED,
            max_wait=600,
            expect_status="succeeded",
            expect_exit=0,
        ),
        PhaseDefinition(
            "D-5.chatgpt",
            "D-5",
            "d4-d7",
            PhaseDefinition.FILE_ABSENT,
            "the file does not exist in this sandbox",
            PhaseDefinition.ON_FAILURE,
            expect_status="absent",
            local_path="{claude_workdir}/orbital-acceptance.txt",
        ),
        PhaseDefinition(
            "D-6.submit",
            "D-6",
            "d4-d7",
            PhaseDefinition.SUBMIT,
            "submit the prompt",
            PhaseDefinition.NEVER,
            prompt=SLEEP_30_PROMPT,
            expect_status="running",
            expect_exit=6,
        ),
        PhaseDefinition(
            "D-6a",
            "D-6",
            "d4-d7",
            PhaseDefinition.WAIT_OBSERVE,
            "wait 5 s, less than the task needs",
            PhaseDefinition.IF_UNOBSERVED,
            max_wait=5,
            expect_status="running",
            expect_codes=("wait_deadline_reached",),
            expect_exit=6,
        ),
        PhaseDefinition(
            "D-6b",
            "D-6",
            "d4-d7",
            PhaseDefinition.WAIT_SETTLE,
            "wait again, up to 120 s",
            PhaseDefinition.UNTIL_SETTLED,
            max_wait=120,
            expect_status="succeeded",
            expect_exit=0,
            expect_response="SLEPT",
        ),
        PhaseDefinition(
            "D-7.submit",
            "D-7",
            "d4-d7",
            PhaseDefinition.SUBMIT,
            "submit the prompt with a 10 s execution timeout",
            PhaseDefinition.NEVER,
            prompt=SLEEP_60_PROMPT,
            execution_timeout=10,
            expect_status="running",
            expect_exit=6,
        ),
        PhaseDefinition(
            "D-7.wait",
            "D-7",
            "d4-d7",
            PhaseDefinition.WAIT_SETTLE,
            "wait for the result",
            PhaseDefinition.UNTIL_SETTLED,
            max_wait=120,
            expect_status="timed_out",
            expect_codes=("execution_timeout",),
            expect_exit=3,
        ),
        PhaseDefinition(
            "D-8.submit",
            "D-8",
            "d8",
            PhaseDefinition.SUBMIT,
            "submit the prompt to the server running with an invalid model",
            PhaseDefinition.NEVER,
            prompt=OK_PROMPT,
            expect_status="running",
            expect_exit=6,
        ),
        PhaseDefinition(
            "D-8.wait",
            "D-8",
            "d8",
            PhaseDefinition.WAIT_SETTLE,
            "wait for the result",
            PhaseDefinition.UNTIL_SETTLED,
            max_wait=120,
            expect_status="failed",
            expect_codes=("claude_error",),
            expect_exit=1,
            expect_fragments=("api_error",),
        ),
        PhaseDefinition(
            "D-9a",
            "D-9",
            "d9a",
            PhaseDefinition.SUBMIT,
            "submit with --max-wait 0",
            PhaseDefinition.NEVER,
            prompt=SLEEP_60_PROMPT,
            expect_status="running",
            expect_exit=6,
        ),
        PhaseDefinition(
            "D-9b",
            "D-9",
            "d9b",
            PhaseDefinition.WAIT_OBSERVE,
            "wait up to 20 s while the server is stopped",
            PhaseDefinition.IF_UNOBSERVED,
            max_wait=20,
            expect_status="communication_error",
            expect_codes=("gateway_error", "connection_failed", "connection_interrupted"),
            expect_exit=4,
        ),
        PhaseDefinition(
            "D-9c",
            "D-9",
            "d9c",
            PhaseDefinition.WAIT_OBSERVE,
            "poll once after the restart",
            PhaseDefinition.ON_FAILURE,
            max_wait=0,
            expect_status="communication_error",
            expect_codes=("unknown_task",),
            expect_exit=4,
            expect_restart_after="D-9a",
        ),
    )

    MANUAL_CHECKS: ClassVar[tuple[ManualCheck, ...]] = (
        ManualCheck(
            "D-3.claude-no-bridge-runs",
            "D-3",
            "No Claude run was started by the D-3 requests",
            "Claude sandbox",
            "after stage d2-d3 and before stage d4-d7 starts",
            BRIDGE_RUNS_CHECK,
            "prints none",
            expected_text="none",
            before_stage="d4-d7",
        ),
        ManualCheck(
            "D-3.claude-serve-log",
            "D-3",
            "serve.log shows the D-3 authentication failures",
            "Claude sandbox",
            "after stage d2-d3",
            "grep 'authentication failed' {serve_log} | tail -n 2",
            "a 'GET /v1/health ... invalid_signature' line (D-3a) and a 'POST /v1/tasks ... "
            "missing_credentials' line (D-3b)",
            expected_fragments=("invalid_signature", "missing_credentials"),
        ),
        ManualCheck(
            "D-4.claude-serve-log",
            "D-4",
            "serve.log shows the D-4 task accepted and finished",
            "Claude sandbox",
            "after stage d4-d7",
            "grep '{task_id}' {serve_log}",
            "'task {task_id} accepted' and 'task {task_id} finished: succeeded'",
            expected_fragments=("task {task_id} accepted", "task {task_id} finished: succeeded"),
        ),
        ManualCheck(
            "D-5.claude-file",
            "D-5",
            "The file exists in the Claude sandbox",
            "Claude sandbox",
            "after stage d4-d7",
            "cat {claude_workdir}/orbital-acceptance.txt",
            "prints ORBITAL-R1",
            expected_text="ORBITAL-R1",
        ),
        ManualCheck(
            "D-7.claude-no-bridge-runs",
            "D-7",
            "No bridge-started Claude run is left after the timeout",
            "Claude sandbox",
            "right after stage d4-d7, before stage d8",
            BRIDGE_RUNS_CHECK,
            "prints none",
            expected_text="none",
            before_stage="d8",
        ),
        ManualCheck(
            "D-7.claude-no-sleep",
            "D-7",
            "The task's sleep 60 is gone after the timeout",
            "Claude sandbox",
            "right after stage d4-d7, before stage d8",
            SLEEP_CHECK,
            "prints none",
            expected_text="none",
            before_stage="d8",
        ),
        ManualCheck(
            "D-9.claude-serve-log",
            "D-9",
            "serve.log shows the D-9 task cancelled when the server stopped",
            "Claude sandbox",
            "after stopping the server (checkpoint after stage d9a)",
            "grep '{task_id}' {serve_log}",
            "'task {task_id} finished: failed (execution_cancelled)'",
            expected_fragments=("task {task_id} finished: failed (execution_cancelled)",),
        ),
        ManualCheck(
            "D-9.claude-no-bridge-runs",
            "D-9",
            "No bridge-started Claude run is left after the stop",
            "Claude sandbox",
            "after stopping the server, before restarting it",
            BRIDGE_RUNS_CHECK,
            "prints none",
            expected_text="none",
            before_stage="d9c",
        ),
        ManualCheck(
            "D-9.claude-no-sleep",
            "D-9",
            "The task's sleep 60 is gone after the stop",
            "Claude sandbox",
            "after stopping the server, before restarting it",
            SLEEP_CHECK,
            "prints none",
            expected_text="none",
            before_stage="d9c",
        ),
    )

    STAGES: ClassVar[tuple[StageDefinition, ...]] = (
        StageDefinition(
            "p1",
            "local preflight P-1",
            ("P-1",),
            (),
            None,
            StageDefinition.NO_PREFLIGHT,
            0,
            False,
        ),
        StageDefinition(
            "d1",
            "D-1, policy block (optional)",
            ("D-1",),
            (
                "Claude sandbox: the bridge server runs from a plain shell (plans/R1.md 14 C):",
                "    mkdir -p {claude_workdir}",
                "    " + SERVE,
                "Host: the network policy does NOT yet allow this sandbox to reach the bridge.",
                "To skip D-1 instead (for example, the policy is already open), run:",
                '    r1-acceptance record D-1 skip --note "the network policy was already open"',
                "and continue with stage d2-d3.",
            ),
            "policy-closed",
            StageDefinition.NO_PREFLIGHT,
            0,
            False,
        ),
        StageDefinition(
            "d2-d3",
            "D-2 and D-3, network path and authentication",
            ("D-2", "D-3"),
            (
                "Host: allow this sandbox to reach the bridge (plans/R1.md 14 A.3), if not done:",
                "    sbx policy allow network localhost:8765",
                "    sbx policy approval ls        # approve the request if one is pending",
                "Claude sandbox: the bridge server is running (plans/R1.md 14 C).",
            ),
            None,
            StageDefinition.NO_PREFLIGHT,
            0,
            False,
        ),
        StageDefinition(
            "d4-d7",
            "D-4 ... D-7, delegation, autonomy, wait budget and timeout",
            ("D-4", "D-5", "D-6", "D-7"),
            (
                "Claude sandbox: make the D-3 checks first; they must happen before any Claude "
                "run starts.",
                "This stage starts 4 real Claude runs and takes about 2 minutes.",
            ),
            None,
            StageDefinition.REACHABLE,
            4,
            True,
        ),
        StageDefinition(
            "d8",
            "D-8, execution failure",
            ("D-8",),
            (
                "Claude sandbox: make the D-7 checks first. Then stop the server (Ctrl-C) and",
                "restart it with an invalid model:",
                "    " + INVALID_MODEL_ARGS,
                "      " + SERVE,
                "This stage starts 1 Claude run, which the API rejects at no cost (plan F-3).",
            ),
            "invalid-model-server",
            StageDefinition.REACHABLE,
            1,
            True,
        ),
        StageDefinition(
            "d9a",
            "D-9a, a task that the next checkpoint interrupts",
            ("D-9",),
            (
                "Claude sandbox: stop the server (Ctrl-C) and restart it normally:",
                "    " + SERVE,
                "Read the next checkpoint now: right after this stage, stop the server within "
                "about 10 s.",
                'This stage starts 1 Claude run ("sleep 60").',
            ),
            "normal-server",
            StageDefinition.REACHABLE,
            1,
            True,
        ),
        StageDefinition(
            "d9b",
            "D-9b, polling while the server is stopped",
            ("D-9",),
            (
                "Claude sandbox, within about 10 s of stage d9a: stop the server (Ctrl-C).",
                "Do not restart it yet. Make the D-9 checks (record them now or later).",
            ),
            "server-stopped",
            StageDefinition.UNREACHABLE,
            0,
            True,
        ),
        StageDefinition(
            "d9c",
            "D-9c, polling after the restart",
            ("D-9",),
            (
                "Claude sandbox: restart the server normally:",
                "    " + SERVE,
            ),
            "server-restarted",
            StageDefinition.REACHABLE,
            0,
            True,
        ),
    )

    @classmethod
    def step(cls, step_id: str) -> StepDefinition:
        """The step *step_id*; ``KeyError`` if there is none."""
        for step in cls.STEPS:
            if step.step_id == step_id:
                return step
        raise KeyError(step_id)

    @classmethod
    def stage(cls, stage_id: str) -> StageDefinition:
        """The stage *stage_id*; ``KeyError`` if there is none."""
        for stage in cls.STAGES:
            if stage.stage_id == stage_id:
                return stage
        raise KeyError(stage_id)

    @classmethod
    def manual_check(cls, check_id: str) -> ManualCheck:
        """The manual check *check_id*; ``KeyError`` if there is none."""
        for check in cls.MANUAL_CHECKS:
            if check.check_id == check_id:
                return check
        raise KeyError(check_id)

    @classmethod
    def stage_ids(cls) -> tuple[str, ...]:
        """The stage ids, in order."""
        return tuple(stage.stage_id for stage in cls.STAGES)

    @classmethod
    def stages_before(cls, stage_id: str) -> tuple[StageDefinition, ...]:
        """The stages that come before *stage_id*."""
        index = cls.stage_ids().index(stage_id)
        return cls.STAGES[:index]

    @classmethod
    def stages_of(cls, step_id: str) -> tuple[str, ...]:
        """The stages in which the step has phases."""
        return tuple(stage.stage_id for stage in cls.STAGES if step_id in stage.steps)

    @classmethod
    def criterion_steps(cls, criterion_id: str) -> tuple[str, ...]:
        """The steps that support a criterion."""
        return tuple(step.step_id for step in cls.STEPS if criterion_id in step.criteria)
