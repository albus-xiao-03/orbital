"""``r1-retest run``, ``repeat`` and ``adopt``: stages and the operator's decisions."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping

from r1_retest.cli.utils import add_run_options, open_store, say
from r1_retest.procedure.retest_procedure import RetestProcedure
from r1_retest.runner.stage_runner import StageRunner


class RunCommand:
    """Runs one stage; ``repeat`` opens a new attempt; ``adopt`` supplies a lost task id."""

    def configure(self, commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
        stages = [s.stage_id for s in RetestProcedure.STAGES]
        run = commands.add_parser(
            "run",
            help="run one stage",
            description="Stages, in order: "
            "a3 (D-2), a2 (D-7), a1-submit, a1-down, a1-up (D-9); optional a4-submit, "
            "a4-down, a4-up (SIGHUP).",
        )
        add_run_options(run)
        run.add_argument("stage", choices=stages)
        run.add_argument(
            "--ready", action="store_true", help="confirm a stage that starts a real Claude run"
        )
        run.set_defaults(handler=self.run)
        repeat = commands.add_parser(
            "repeat", help="start a new attempt (a new task) of A-2, A-1 or A-4"
        )
        add_run_options(repeat)
        repeat.add_argument("test", choices=["A-2", "A-1", "A-4"])
        repeat.add_argument("--ready", action="store_true", help="confirm the new attempt")
        repeat.set_defaults(handler=self.repeat)
        adopt = commands.add_parser(
            "adopt", help="continue a test whose submission output was lost"
        )
        add_run_options(adopt)
        adopt.add_argument("test", choices=["A-2", "A-1", "A-4"])
        adopt.add_argument("task_id")
        adopt.set_defaults(handler=self.adopt)

    def run(self, args: argparse.Namespace, environ: Mapping[str, str]) -> int:
        store = open_store(args, environ)
        with store.lock():
            return StageRunner(store, environ, say).run(
                args.stage, args.ready, ["r1-retest", *sys.argv[1:]]
            )

    def repeat(self, args: argparse.Namespace, environ: Mapping[str, str]) -> int:
        store = open_store(args, environ)
        with store.lock():
            return StageRunner(store, environ, say).repeat(args.test, args.ready)

    def adopt(self, args: argparse.Namespace, environ: Mapping[str, str]) -> int:
        store = open_store(args, environ)
        with store.lock():
            return StageRunner(store, environ, say).adopt(args.test, args.task_id)
