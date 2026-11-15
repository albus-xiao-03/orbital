"""BridgeCli: runs the ``orbital-bridge`` command line as the ChatGPT side does."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from r1_acceptance.bridge.utils import (
    ALLOWED_COMMANDS,
    CLI_MODULE,
    child_environment,
    parse_json_object,
)
from r1_acceptance.models.execution import Execution
from r1_acceptance.utils import format_time, utc_now


class BridgeCli:
    """Runs ``python -m orbital.bridges`` (the ``orbital-bridge`` CLI) and captures everything.

    Only the client commands ``ping``, ``submit`` and ``wait`` (and ``--help``) can be run: the
    server is never started or stopped by the harness. A command that outlives its own budget
    by ``grace_seconds`` is stopped and recorded as ``harness-timeout``; Ctrl-C stops it and is
    recorded as ``interrupted``. Nothing is ever retried here.
    """

    def __init__(
        self,
        *,
        python: str,
        orbital_src: Path,
        url: str,
        environ: Mapping[str, str],
        grace_seconds: float = 300.0,
    ) -> None:
        self._python = python
        self._orbital_src = orbital_src
        self._url = url
        self._environ = dict(environ)
        self._grace_seconds = grace_seconds

    def run(
        self,
        arguments: Sequence[str],
        *,
        budget_seconds: float,
        wrong_key: str | None = None,
        expect_json: bool = True,
    ) -> Execution:
        """Run ``orbital-bridge <arguments>`` and return what it produced."""
        if not arguments or arguments[0] not in ALLOWED_COMMANDS:
            raise ValueError(
                f"refusing to run orbital-bridge {' '.join(arguments[:1])!r}: only "
                f"{', '.join(sorted(ALLOWED_COMMANDS))} are allowed"
            )
        argv = [self._python, "-m", CLI_MODULE, *arguments]
        env = child_environment(
            self._environ, orbital_src=self._orbital_src, url=self._url, key=wrong_key
        )
        started = utc_now()
        clock = time.monotonic()
        try:
            process = subprocess.Popen(  # noqa: S603 - fixed interpreter and module, no shell
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
        except OSError as exc:
            return Execution(
                started_at=format_time(started),
                finished_at=format_time(utc_now()),
                duration_seconds=round(time.monotonic() - clock, 3),
                outcome=Execution.START_FAILED,
                exit_code=None,
                stdout=b"",
                stderr=f"cannot start {self._python}: {exc}".encode(),
                document=None,
                parse_error=None,
            )
        outcome = Execution.EXITED
        try:
            stdout, stderr = process.communicate(timeout=budget_seconds + self._grace_seconds)
        except subprocess.TimeoutExpired:
            outcome = Execution.HARNESS_TIMEOUT
            stdout, stderr = self._stop(process)
        except KeyboardInterrupt:
            outcome = Execution.INTERRUPTED
            stdout, stderr = self._stop(process)
        document, problem = (None, None)
        if outcome == Execution.EXITED and expect_json:
            document, problem = parse_json_object(stdout)
        return Execution(
            started_at=format_time(started),
            finished_at=format_time(utc_now()),
            duration_seconds=round(time.monotonic() - clock, 3),
            outcome=outcome,
            exit_code=process.returncode,
            stdout=stdout,
            stderr=stderr,
            document=document,
            parse_error=problem,
        )

    @staticmethod
    def _stop(process: subprocess.Popen[bytes]) -> tuple[bytes, bytes]:
        """Stop the harness's own child command and collect what it printed."""
        process.terminate()
        try:
            return process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            return process.communicate()
