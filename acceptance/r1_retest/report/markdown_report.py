"""Renders the JSON report as a Markdown document for people."""

from __future__ import annotations

import json
from typing import Any

from r1_retest.report.utils import bold, md_cell, md_code


class MarkdownReport:
    """One Markdown page with the same content as the JSON report."""

    def __init__(self, document: dict[str, Any]) -> None:
        self._doc = document
        self._out: list[str] = []

    def render(self) -> str:
        self._header()
        self._summary()
        self._criteria()
        for test in self._doc["tests"]:
            self._test(test)
        self._carried()
        self._records()
        self._closing()
        return "\n".join(self._out).rstrip() + "\n"

    def _w(self, line: str = "") -> None:
        self._out.append(line)

    def _table(self, head: list[str], rows: list[list[Any]]) -> None:
        self._w("| " + " | ".join(head) + " |")
        self._w("|" + "---|" * len(head))
        for row in rows:
            self._w(
                "| "
                + " | ".join(
                    md_cell(c) if not str(c).startswith(("`", "**")) else str(c) for c in row
                )
                + " |"
            )
        self._w()

    # ------------------------------------------------------------------------------ sections

    def _header(self) -> None:
        doc, run = self._doc, self._doc["run"]
        overall = doc["overall"]
        self._w("# R1 targeted dual-sandbox re-test report")
        self._w()
        self._w(f"**Overall: {overall['verdict'].upper()}.** {overall['statement']}")
        self._w()
        env = run.get("environment") or {}
        orbital = run.get("orbital") or {}
        self._table(
            ["Item", "Value"],
            [
                ["Run", md_code(run.get("run_id")) + f" (created {run.get('created_at')})"],
                ["Report generated", doc["generated_at"]],
                [
                    "Harness",
                    f"{doc['generator'].get('name')} {doc['generator'].get('version')}, "
                    f"{doc['generator'].get('form', '')} {md_code(doc['generator'].get('sha256'))}",
                ],
                ["Bridge URL", md_code(run.get("url"))],
                ["orbital source (ChatGPT sandbox)", md_code(orbital.get("src"))],
                ["Source digest", md_code(orbital.get("digest"))],
                ["Repository commit", md_code(orbital.get("commit"))],
                [
                    "ChatGPT sandbox",
                    f"host {md_code(env.get('hostname'))}, Python {env.get('python')}, "
                    f"{env.get('platform')}",
                ],
                ["Proxy settings", md_code(json.dumps(env.get("proxies", {})))],
                [
                    "Ignored ORBITAL_BRIDGE_* variables",
                    ", ".join(env.get("ignored_variables") or []) or "-",
                ],
            ],
        )

    def _summary(self) -> None:
        doc = self._doc
        source = doc["source"]
        chat, claude = source["chatgpt_side"], source["claude_side"]
        self._w("## Implementation under test")
        self._w()
        self._table(
            ["Side", "Verdict", "Detail"],
            [
                [
                    "ChatGPT sandbox (automatic)",
                    bold("passed" if chat["matches"] else "failed"),
                    f"digest {md_code(chat['digest'])}; "
                    f"expected {md_code(chat['expected_digest'])}; "
                    f"unchanged since init: {chat['unchanged_since_init']}",
                ],
                [
                    "Claude sandbox (orbital_source)",
                    bold(claude["verdict"]),
                    f"{claude.get('note')}; digest {md_code(claude.get('digest'))}, "
                    f"commit {md_code(claude.get('commit'))}",
                ],
            ],
        )
        if doc["overall"]["problems"]:
            for problem in doc["overall"]["problems"]:
                self._w(f"- {problem}")
            self._w()
        self._w("## Tests")
        self._w()
        rows = []
        for test in doc["tests"]:
            rows.append(
                [
                    test["test_id"],
                    test["step"],
                    test["title"],
                    "required" if test["required"] else "optional",
                    bold(test["verdict"]),
                    test["attempt"],
                    md_code(test.get("task_id")),
                ]
            )
        self._table(["Test", "Plan step", "Title", "Kind", "Verdict", "Attempt", "Task id"], rows)
        c = doc["counts"]
        self._w(
            f"Counts: tests {c['tests']}; automated operations {c['operations']}; manual checks "
            f"{c['manual_checks']}."
        )
        self._w()

    def _criteria(self) -> None:
        self._w("## Acceptance criteria")
        self._w()
        rows = []
        for item in self._doc["criteria"]:
            new = (
                ", ".join(
                    f"{p['test_id']} ({p['step']}): {p['verdict']}" for p in item["newly_verified"]
                )
                or "-"
            )
            old = ", ".join(p["step"] for p in item["carried_forward"]) or "-"
            rows.append(
                [
                    f"**{item['criterion']}** {item['text']}",
                    bold(item["verdict"]),
                    item["basis"],
                    new,
                    old,
                ]
            )
        self._table(
            ["Criterion", "Verdict", "Basis", "Newly verified", "Carried forward (passed)"], rows
        )

    def _test(self, test: dict[str, Any]) -> None:
        self._w(f"## {test['test_id']} ({test['step']}): {test['title']} — {test['verdict']}")
        self._w()
        self._w(f"Expected (plans/R1.md revision 6): {test['expected']}.")
        self._w()
        if test.get("note"):
            self._w(f"_{test['note']}_")
            self._w()
            return
        self._w(
            f"Attempt {test['attempt']}; task id {md_code(test.get('task_id'))}"
            + (" (adopted by the operator)" if test.get("task_adopted") else "")
            + "."
        )
        self._w()
        rows = []
        for op in test["operations"]:
            observed = op.get("observed") or {}
            shown = ", ".join(
                f"{k}={observed[k]}"
                for k in ("status", "code", "ok", "exit", "exit_derived", "server_started_at")
                if k in observed
            )
            rows.append(
                [
                    op["op_id"],
                    md_code(op["command"]),
                    op["expected"],
                    shown or "-",
                    bold(op["verdict"]),
                    "; ".join(op["diagnostics"]) or "-",
                ]
            )
        self._table(
            ["Operation", "Command", "Expected", "Observed", "Verdict", "Diagnostics"], rows
        )
        for op in test["operations"]:
            for attempt in op["tries"]:
                files = ", ".join(
                    f"{k} {md_code(v.get('path'))} ({v.get('bytes', '?')} B, sha256 "
                    f"{md_code(v.get('sha256', '-')[:16])}…)"
                    for k, v in attempt["files"].items()
                )
                self._w(
                    f"- {op['op_id']} try {attempt['try']}: started {attempt['started_at']}, "
                    f"finished {attempt['finished_at']}, {attempt['duration_seconds']} s, "
                    f"outcome {attempt['outcome']}, exit {attempt['exit_code']}"
                    f"{', recovered' if attempt['recovered'] else ''}; {files}"
                )
            if op.get("document") is not None:
                self._w(f"  - parsed result: {md_code(json.dumps(op['document']))}")
        if test["operations"]:
            self._w()
        if test["manual"]:
            rows = []
            for check in test["manual"]:
                timing = check.get("timing") or {}
                observed = check.get("observed")
                rows.append(
                    [
                        check["check_id"],
                        check["title"],
                        check["expected"],
                        md_code(json.dumps(observed)) if observed is not None else "-",
                        md_code(json.dumps(timing)) if timing else "-",
                        bold(check["verdict"]),
                        "; ".join(check["diagnostics"]) or "-",
                        ", ".join(
                            f"{e['path']} (imported {e['imported_at']})" for e in check["evidence"]
                        )
                        or "-",
                    ]
                )
            self._table(
                [
                    "Manual check",
                    "What",
                    "Expected",
                    "Observed",
                    "Timing",
                    "Verdict",
                    "Diagnostics",
                    "Evidence",
                ],
                rows,
            )
        for earlier in test["earlier_attempts"]:
            self._w(
                f"- Earlier attempt {earlier['attempt']} (task {md_code(earlier['task_id'])}): "
                f"{earlier['operations']}; {earlier['note']}."
            )
        if test["earlier_attempts"]:
            self._w()

    def _carried(self) -> None:
        carried = self._doc["carried_forward"]
        self._w(f"## Evidence carried forward from {carried['run_id']}")
        self._w()
        located = carried.get("located") or {}
        if located.get("found"):
            self._w(
                f"Located in this sandbox at {md_code(located.get('path'))}; latest report "
                f"{md_code(located.get('report'))} "
                f"(sha256 {md_code(located.get('report_sha256'))}). "
                "It was read, never changed."
            )
        else:
            self._w(
                "Not located in this sandbox; "
                "referenced by its run id (its report is quoted in qas/R1.md)."
            )
        self._w()
        self._table(
            ["Step", "Title", "Criteria", "Verdict", "Summary"],
            [
                [s["step"], s["title"], ", ".join(s["criteria"]), bold(s["verdict"]), s["summary"]]
                for s in carried["steps"]
            ],
        )
        for item in carried["superseded"]:
            self._w(f"- {item['step']}: {item['note']}.")
        self._w()

    def _records(self) -> None:
        doc = self._doc
        self._w("## Manual records, attachments and notes")
        self._w()
        if doc["manual_records"]:
            self._table(
                ["Check", "Attempt", "Observed (by its own clock)", "Imported", "File", "Problems"],
                [
                    [
                        r["check_id"],
                        r["attempt"],
                        r["observed_at"],
                        r["imported_at"],
                        md_code(r["file"]),
                        "; ".join(r["problems"]) or (r.get("unavailable") or "-"),
                    ]
                    for r in doc["manual_records"]
                ],
            )
        else:
            self._w("No manual records.")
            self._w()
        for item in doc["attachments"]:
            self._w(
                f"- Attachment {md_code(item['label'])}: {md_code(item['file'])}, "
                f"{item['bytes']} B, sha256 {md_code(item['sha256'])}"
            )
        for note in doc["notes"]:
            self._w(f"- Note ({note['at']}): {note['text']}")
        if doc["preflights"]:
            self._w()
            self._table(
                ["Preflight", "Stage", "Expectation", "Observed", "Passed"],
                [
                    [p["at"], p["stage_id"], p["expectation"], md_code(p["observed"]), p["passed"]]
                    for p in doc["preflights"]
                ],
            )

    def _closing(self) -> None:
        doc = self._doc
        self._w("## What this report does and does not claim")
        self._w()
        for line in doc["limitations"]:
            self._w(f"- {line}")
        self._w()
        self._table(
            ["Verdict", "Meaning"], [[item["verdict"], item["meaning"]] for item in doc["legend"]]
        )
        if doc["unreadable_events"]:
            self._w(f"Unreadable event files (skipped): {', '.join(doc['unreadable_events'])}")
            self._w()
        self._w("## Evidence index")
        self._w()
        self._table(
            ["File", "Bytes", "SHA-256"],
            [[md_code(e["path"]), e["bytes"], md_code(e["sha256"])] for e in doc["evidence_index"]],
        )
