"""``r1-acceptance run STAGE``: run one stage of the procedure."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from r1_acceptance.bridge.utils import key_problem
from r1_acceptance.cli.utils import (
    EXIT_USAGE,
    add_run_options,
    complain,
    ledger_for,
    open_store,
    runner_for,
    say,
)
from r1_acceptance.models.verdict import Verdict
from r1_acceptance.procedure.errors import StageRefusedError
from r1_acceptance.procedure.r1_procedure import R1Procedure
from r1_acceptance.procedure.utils import (
    manual_check_lines,
    next_action_lines,
    pending_manual_checks,
    placeholder_values,
    render,
    rerun_hint_lines,
)
from r1_acceptance.utils import tree_digest


class RunCommand:
    """Run one stage, after checking that it may run now.

    A stage runs only after the stages before it are complete, with the ``--confirm`` token of
    its checkpoint, with a usable ``ORBITAL_BRIDGE_KEY``, and with the orbital source unchanged
    since ``init``. Running a stage again continues it; nothing already submitted is submitted
    again unless ``--resubmit`` names the step.
    """

    def configure(self, commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
        stages = ", ".join(R1Procedure.stage_ids())
        parser = commands.add_parser(
            "run",
            help="run one stage (status shows which one is next)",
            description=f"Run one stage of the procedure. Stages, in order: {stages}.",
        )
        parser.add_argument("stage", choices=R1Procedure.stage_ids(), metavar="STAGE")
        parser.add_argument(
            "--confirm",
            metavar="TOKEN",
            help="state that the checkpoint before the stage is done (the instructions name the "
            "token)",
        )
        parser.add_argument(
            "--resubmit",
            metavar="STEP",
            action="append",
            default=[],
            help="submit the step's task again as a new attempt: another real Claude run "
            "(repeatable)",
        )
        add_run_options(parser)
        parser.set_defaults(handler=self.run)

    def run(self, args: argparse.Namespace) -> int:
        """Check the preconditions, run the stage, and say what comes next."""
        try:
            store = open_store(args)
            store.lock()
        except (LookupError, RuntimeError) as exc:
            return complain(str(exc))
        stage = R1Procedure.stage(args.stage)
        settings = store.info.get("settings", {})
        values = placeholder_values(settings, None)
        ledger = ledger_for(store)
        if stage.stage_id != "p1" and ledger.step_status("P-1").automated is not Verdict.PASSED:
            return complain(
                "the local preflight P-1 has not passed; fix it, then run: r1-acceptance run p1"
            )
        for earlier in R1Procedure.stages_before(stage.stage_id):
            if not ledger.stage_complete(earlier.stage_id):
                say(*next_action_lines(ledger, settings))
                return complain(
                    f"stage {earlier.stage_id} is not complete, so stage {stage.stage_id} "
                    "cannot run yet"
                )
        if stage.confirm is not None and args.confirm != stage.confirm:
            say(f"Stage {stage.stage_id} needs this checkpoint first:")
            say(*[f"  {render(line, values)}" for line in stage.before])
            say("Then confirm it by running:", f"    {stage.command()}")
            return complain(f"stage {stage.stage_id} needs --confirm {stage.confirm}")
        if stage.confirm is None and args.confirm is not None:
            return complain(f"stage {stage.stage_id} takes no --confirm")
        orbital_src = Path(str(store.info["orbital"]["src"]))
        recorded = store.info["orbital"]["digest"]
        if tree_digest(orbital_src / "orbital") != recorded:
            return complain(
                f"the orbital source in {orbital_src} changed since this run started; restore "
                "it, or start a new run with: r1-acceptance init --new"
            )
        if stage.stage_id != "p1":
            problem = key_problem(os.environ, orbital_src)
            if problem is not None:
                return complain(problem)
        try:
            code = runner_for(store).run(
                stage,
                resubmit=frozenset(args.resubmit),
                confirmation=args.confirm,
                invocation=sys.argv,
            )
        except StageRefusedError as exc:
            say(str(exc))
            return EXIT_USAGE
        ledger = ledger_for(store)
        pending = pending_manual_checks(ledger, stage.steps)
        if pending:
            say("", "Manual checks of the Claude sandbox for this stage (each says when):")
            for check, task_id in pending:
                say(*manual_check_lines(check, placeholder_values(settings, task_id)))
        hints = [
            line
            for line in rerun_hint_lines(ledger)
            if any(line.startswith(f"{step_id} ") for step_id in stage.steps)
        ]
        if hints:
            say("", *hints)
        say("", *next_action_lines(ledger, settings))
        return code
