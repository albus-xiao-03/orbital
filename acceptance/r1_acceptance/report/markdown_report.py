"""MarkdownReport: the acceptance report rendered for people."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from r1_acceptance.report.utils import fenced, md_cell, md_code


class MarkdownReport:
    """Renders a report document (from ``ReportBuilder``) as Markdown.

    The Markdown carries the same facts as the JSON: verdicts, expected and observed results,
    commands with timestamps and exit codes, raw responses, manual records and the evidence
    index.
    """

    def __init__(self, document: Mapping[str, Any]) -> None:
        self._document = document

    def render(self) -> str:
        """The whole report as Markdown text."""
        lines: list[str] = []
        self._header(lines)
        self._criteria(lines)
        self._step_table(lines)
        self._manual_table(lines)
        for step in self._document["steps"]:
            self._step_details(lines, step)
        self._preflights(lines)
        self._closing(lines)
        return "\n".join(lines) + "\n"

    def _header(self, lines: list[str]) -> None:
        run = self._document["run"]
        orbital = run.get("orbital", {})
        harness = run.get("harness", {})
        environment = run.get("environment", {})
        overall = self._document["overall"]
        harness_text = f"{md_cell(harness.get('version'))}, digest {md_code(harness.get('digest'))}"
        ignored = md_cell(", ".join(environment.get("ignored_variables", [])))
        lines += [
            "# R1 dual-sandbox acceptance report",
            "",
            f"**Overall: {overall['verdict'].upper()}.** {overall['summary']}",
            "",
            "| Item | Value |",
            "|---|---|",
            f"| Run | {md_code(run.get('run_id'))} (created {md_cell(run.get('created_at'))}) |",
            f"| Report generated | {md_cell(self._document['generated_at'])} |",
            f"| Bridge URL | {md_code(run.get('settings', {}).get('url'))} |",
            f"| orbital source | {md_code(orbital.get('src'))} |",
            f"| orbital source digest | {md_code(orbital.get('digest'))} |",
            f"| Repository commit | {md_code(orbital.get('commit'))} |",
            f"| Harness | {harness_text} |",
            f"| ChatGPT sandbox | host {md_code(environment.get('hostname'))}, Python "
            f"{md_cell(environment.get('python'))} |",
            f"| Proxy settings | {md_code(json.dumps(environment.get('proxies', {})))} |",
            f"| Ignored ORBITAL_BRIDGE_* | {ignored} |",
            "",
            "Counts: steps "
            + self._counts("steps")
            + "; criteria "
            + self._counts("criteria")
            + "; manual checks "
            + self._counts("manual_checks")
            + ".",
            "",
        ]

    def _counts(self, key: str) -> str:
        values = self._document["counts"][key]
        return ", ".join(f"{count} {verdict}" for verdict, count in values.items()) or "none"

    def _criteria(self, lines: list[str]) -> None:
        lines += [
            "## Acceptance criteria",
            "",
            "| Criterion | Verdict | Supporting steps | Notes |",
            "|---|---|---|---|",
        ]
        for item in self._document["criteria"]:
            steps = ", ".join(f"{s} ({v})" for s, v in item["step_verdicts"].items())
            lines.append(
                f"| **{item['criterion_id']}** {md_cell(item['title'])} | "
                f"**{item['verdict']}** | {md_cell(steps)} | {md_cell('; '.join(item['notes']))} |"
            )
        lines.append("")

    def _step_table(self, lines: list[str]) -> None:
        lines += [
            "## Steps",
            "",
            "| Step | Title | Criteria | Verdict | Automated | Attempt | Task id |",
            "|---|---|---|---|---|---|---|",
        ]
        for step in self._document["steps"]:
            title = step["title"] + (" (optional)" if step["optional"] else "")
            lines.append(
                f"| {step['step_id']} | {md_cell(title)} | {', '.join(step['criteria'])} | "
                f"**{step['verdict']}** | {step['automated_verdict']} | {step['attempt']} | "
                f"{md_code(step['task_id'])} |"
            )
        lines.append("")

    def _manual_table(self, lines: list[str]) -> None:
        lines += [
            "## Manual verification (recorded by the operator)",
            "",
            "These are observations of the Claude sandbox. The harness only stores what the "
            "operator recorded; it did not observe the Claude sandbox itself.",
            "",
            "| Check | Verdict | Recorded | Observed | Note |",
            "|---|---|---|---|---|",
        ]
        for step in self._document["steps"]:
            for check in step["manual_checks"]:
                note = "; ".join(
                    part for part in (check.get("note"), check.get("timing_note")) if part
                )
                lines.append(
                    f"| {check['check_id']} | **{check['verdict']}** | "
                    f"{md_cell(check.get('recorded_at'))} | {md_code(check.get('observed'))} | "
                    f"{md_cell(note)} |"
                )
        lines.append("")

    def _step_details(self, lines: list[str], step: Mapping[str, Any]) -> None:
        lines += [
            f"## {step['step_id']}: {step['title']} ({step['verdict']})",
            "",
            f"{step['purpose']} Criteria: {', '.join(step['criteria'])}.",
            "",
            f"Expected (plans/R1.md): {step['expected']}",
            "",
        ]
        if step["skipped_reason"]:
            lines += [f"Skipped: {step['skipped_reason']}", ""]
        for note in step["notes"]:
            lines += [f"Note: {note}", ""]
        lines += [
            "| Phase | Stage | Expected status / code / exit | Observed status / code / exit "
            "| Result |",
            "|---|---|---|---|---|",
        ]
        for phase in step["phases"]:
            expected = phase["expected"]
            result = phase["result"] or {}
            expected_text = " / ".join(
                [
                    md_cell(expected["status"]),
                    md_cell(" or ".join(expected["error_code"] or []) or "none"),
                    md_cell(expected["exit_code"]),
                ]
            )
            observed_text = " / ".join(
                [
                    md_cell(result.get("observed_status")),
                    md_cell(result.get("observed_code") or "none"),
                    md_cell(result.get("observed_exit")),
                ]
            )
            lines.append(
                f"| {phase['phase_id']} ({md_cell(phase['title'])}) | {phase['stage']} | "
                f"{expected_text} | {observed_text} | **{phase['state']}** |"
            )
        lines.append("")
        for phase in step["phases"]:
            self._phase_details(lines, phase)
        for attempt in step["superseded_attempts"]:
            lines += [
                f"Superseded attempt {attempt['attempt']} ({attempt['automated_verdict']}, task "
                f"{md_code(attempt['task_id'])}): {md_cell(json.dumps(attempt['phases']))}",
                "",
            ]

    def _phase_details(self, lines: list[str], phase: Mapping[str, Any]) -> None:
        result = phase["result"]
        if result is None:
            return
        lines.append(f"**{phase['phase_id']}** evaluated {result['evaluated_at']}")
        lines.append("")
        failed = [check for check in result["checks"] if check["verdict"] != "passed"]
        for check in failed:
            diagnostic = f" ({check['diagnostic']})" if check["diagnostic"] else ""
            lines.append(
                f"- FAILED {check['description']}: expected {md_code(check['expected'])}, "
                f"observed {md_code(check['observed'])}{diagnostic}"
            )
        for diagnostic in result["diagnostics"]:
            lines.append(f"- note: {diagnostic}")
        if failed or result["diagnostics"]:
            lines.append("")
        for command in phase["commands"]:
            self._command(lines, command)
        if phase["earlier_evaluations"]:
            states = ", ".join(item["state"] for item in phase["earlier_evaluations"])
            lines += [f"Earlier evaluations in this attempt: {states}.", ""]

    def _command(self, lines: list[str], command: Mapping[str, Any]) -> None:
        lines += [
            f"- Command {command['command_id']}: {md_code(command.get('display'))}",
            f"  - started {md_cell(command.get('started_at'))}, finished "
            f"{md_cell(command.get('finished_at'))}, {md_cell(command.get('duration_seconds'))} s,"
            f" outcome {md_cell(command.get('outcome'))}, exit code "
            f"{md_cell(command.get('exit_code'))}, key: {md_cell(command.get('key'))}",
            f"  - raw output: {md_code(command.get('stdout_file'))} (SHA-256 "
            f"{md_code(command.get('stdout_sha256'))}), errors: "
            f"{md_code(command.get('stderr_file'))}",
            "",
        ]
        document = command.get("document")
        if document is not None:
            lines += [*fenced(json.dumps(document, ensure_ascii=False, indent=2), "json"), ""]
        elif command.get("parse_error"):
            lines += [f"Output could not be read: {command['parse_error']}", ""]
        stderr = command.get("stderr_excerpt") or ""
        if stderr.strip():
            lines += ["Standard error (end):", "", *fenced(stderr), ""]

    def _preflights(self, lines: list[str]) -> None:
        preflights: Sequence[Mapping[str, Any]] = self._document["preflights"]
        if not preflights:
            return
        lines += [
            "## Preflight checks before stages",
            "",
            "| Time | Stage | Expectation | Observed | Passed |",
            "|---|---|---|---|---|",
        ]
        for item in preflights:
            lines.append(
                f"| {md_cell(item.get('at'))} | {md_cell(item.get('stage'))} | "
                f"{md_cell(item.get('expectation'))} | {md_code(item.get('observed'))} | "
                f"{'yes' if item.get('passed') else 'no'} |"
            )
        lines.append("")

    def _closing(self, lines: list[str]) -> None:
        unreadable = self._document.get("unreadable_events") or []
        if unreadable:
            lines += [
                "## Unreadable event files",
                "",
                "These event files could not be read (a command was killed while writing "
                "them). They were left in place and treated as if the events never happened:",
                "",
                *[f"- {md_code(name)}" for name in unreadable],
                "",
            ]
        lines += ["## What this report does and does not claim", ""]
        lines += [f"- {text}" for text in self._document["limitations"]]
        lines += ["", "## Verdict legend", "", "| Verdict | Meaning |", "|---|---|"]
        for item in self._document["legend"]:
            lines.append(f"| {item['verdict']} | {md_cell(item['meaning'])} |")
        lines += ["", "## Evidence index", "", "| File | Bytes | SHA-256 |", "|---|---|---|"]
        for item in self._document["evidence_index"]:
            lines.append(
                f"| {md_code(item['path'])} | {item['bytes']} | {md_code(item['sha256'])} |"
            )
        lines.append("")
