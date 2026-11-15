"""Parsers for the Claude-side observations that the operator pastes into the harness.

Each parser is lenient about what surrounds the output (a pasted shell prompt, the command line,
blank lines) and strict about the output itself. Anything it cannot read is reported as a
problem; nothing is guessed.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from r1_retest.utils import ISO_UTC, TASK_ID, format_time, parse_offset, parse_time

PROCESS_LINE = re.compile(r"^(\d+)\s+(\S.*)$")
LOG_LINE = re.compile(
    r"^(?:(\d+):)?(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),(\d{3}) (\w+) ([\w.]+): (.*)$"
)
EVIDENCE_HEADER = re.compile(r"^ORBITAL-EVIDENCE (\S+) (\S+) utc=(\S+) offset=([+-]\d{4})\s*$")
SOURCE_HEADER = re.compile(r"^ORBITAL-SOURCE utc=(\S+)\s*$")
LS_LINE = re.compile(
    r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})(?:\.(\d+))? ([+-]\d{4}) "
    r"(\S*?([0-9a-f-]{36})\.jsonl)\s*$"
)
COUNT_LINE = re.compile(r"^(?:\S+:)?(\d+)$")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
COMMIT_HEX = re.compile(r"^[0-9a-f]{40}$")
STOP_LINE = re.compile(r"^stopping(?: \((SIG[A-Z0-9]+)\))?; ")


def clean_lines(text: str) -> list[str]:
    return [line.rstrip("\r") for line in text.replace("\r\n", "\n").split("\n")]


def parse_process_check(text: str) -> dict[str, Any]:
    """The output of ``orbital_check`` (plans/R1.md §16's timed process check).

    Expected: a UTC time line, then ``none`` twice, or the matching processes. A command line
    or prompt pasted along with the output is ignored and listed.
    """
    observed_at: str | None = None
    nones = 0
    processes: list[str] = []
    ignored: list[str] = []
    problems: list[str] = []
    for line in clean_lines(text):
        stripped = line.strip()
        if not stripped:
            continue
        if observed_at is None and ISO_UTC.match(stripped):
            observed_at = stripped
            continue
        if observed_at is None:
            ignored.append(stripped)
            continue
        if stripped == "none":
            nones += 1
        elif PROCESS_LINE.match(stripped) and "pgrep" not in stripped:
            processes.append(stripped)
        else:
            ignored.append(stripped)
    if observed_at is None:
        problems.append("no UTC time line (date -u +%FT%TZ) found: the observation time is unknown")
    elif not processes and nones != 2:
        problems.append(f"expected 'none' twice (or process lines), found 'none' {nones} time(s)")
    return {
        "observed_at": format_time(parse_time(observed_at)) if observed_at else None,
        "none_count": nones,
        "processes": processes,
        "ignored_lines": ignored,
        "problems": problems,
    }


def local_to_utc(local_text: str, millis: str, offset: timezone) -> datetime:
    moment = datetime.strptime(local_text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=offset)
    return (moment + timedelta(milliseconds=int(millis))).astimezone(UTC)


def parse_claude_evidence(text: str) -> dict[str, Any]:
    """The output of ``orbital_evidence <test> <task_id>``: serve.log lines and the transcript.

    serve.log times are local time without a zone; the header's ``date +%z`` offset converts
    them to UTC (both come from the Claude sandbox's own clock).
    """
    lines = clean_lines(text)
    problems: list[str] = []
    header: dict[str, Any] | None = None
    section = "before"
    log_lines: list[dict[str, Any]] = []
    transcript_lines: list[str] = []
    count_lines: list[str] = []
    complete = False
    for position, line in enumerate(lines):
        stripped = line.strip()
        if header is None:
            match = EVIDENCE_HEADER.match(stripped)
            if match:
                header = {
                    "test": match.group(1),
                    "task_id": match.group(2),
                    "captured_at_text": match.group(3),
                    "offset": match.group(4),
                }
                section = "log"
            continue
        if stripped == "ORBITAL-TRANSCRIPT":
            section = "transcript"
            continue
        if stripped == "ORBITAL-SLEPT":
            section = "slept"
            continue
        if stripped == "ORBITAL-END":
            complete = True
            break
        if not stripped:
            continue
        if section == "log":
            log_lines.append({"position": position, "raw": stripped})
        elif section == "transcript":
            transcript_lines.append(stripped)
        elif section == "slept":
            count_lines.append(stripped)
    if header is None:
        return {
            "problems": [
                "no 'ORBITAL-EVIDENCE' header: paste the whole output of orbital_evidence"
            ],
            "complete": False,
        }
    try:
        offset = parse_offset(header["offset"])
        captured = parse_time(header["captured_at_text"])
    except ValueError as exc:
        return {"problems": [f"unreadable header: {exc}"], "complete": False}
    if not TASK_ID.match(header["task_id"]):
        problems.append(f"the header's task id {header['task_id']!r} is not a task id")
    if not complete:
        problems.append("no 'ORBITAL-END' line: the pasted output looks truncated")
    parsed_log: list[dict[str, Any]] = []
    for entry in log_lines:
        match = LOG_LINE.match(entry["raw"])
        if not match:
            problems.append(f"unreadable serve.log line: {entry['raw'][:120]}")
            continue
        number, local, millis, level, logger, message = match.groups()
        order: int = int(number) if number else entry["position"]
        parsed_log.append(
            {
                "order": order,
                "line_number": int(number) if number else None,
                "utc": format_time(local_to_utc(local, millis, offset)),
                "local": f"{local},{millis}",
                "level": level,
                "logger": logger,
                "message": message,
            }
        )
    parsed_log.sort(key=lambda item: int(item["order"]))
    transcript = None
    for line in transcript_lines:
        match = LS_LINE.search(line)
        if match:
            date, clock, fraction, zone, path, name = match.groups()
            moment = datetime.strptime(f"{date} {clock}", "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=parse_offset(zone)
            )
            if fraction:
                moment += timedelta(microseconds=int((fraction + "000000")[:6]))
            transcript = {
                "path": path,
                "session": name,
                "modified_at": format_time(moment.astimezone(UTC)),
            }
            break
    counts = [int(m.group(1)) for m in (COUNT_LINE.match(c) for c in count_lines) if m]
    return {
        "test": header["test"],
        "task_id": header["task_id"],
        "captured_at": format_time(captured),
        "offset": header["offset"],
        "log": parsed_log,
        "transcript": transcript,
        "transcript_raw": transcript_lines,
        "slept_counts": counts,
        "slept_raw": count_lines,
        "complete": complete,
        "problems": problems,
    }


def parse_claude_source(text: str) -> dict[str, Any]:
    """The output of ``orbital_source <repository copy>``: commit and source digest."""
    captured = None
    commit = None
    digest = None
    for line in clean_lines(text):
        stripped = line.strip()
        match = SOURCE_HEADER.match(stripped)
        if match:
            captured = match.group(1)
        elif COMMIT_HEX.match(stripped):
            commit = stripped
        elif stripped.startswith("digest "):
            value = stripped.split(" ", 1)[1].strip()
            digest = value if SHA256_HEX.match(value) else None
    problems = []
    if captured is None:
        problems.append("no 'ORBITAL-SOURCE' header: paste the whole output of orbital_source")
    if digest is None:
        problems.append("no source digest found")
    return {"captured_at": captured, "commit": commit, "digest": digest, "problems": problems}


def task_events(log: list[dict[str, Any]], task_id: str) -> dict[str, Any]:
    """The serve.log records of one task, and the server's start and stop records around it."""
    accepted = next((e for e in log if e["message"].startswith(f"task {task_id} accepted")), None)
    executor = [e for e in log if e["message"].startswith(f"task {task_id}: Claude Code ")]
    finished = [e for e in log if e["message"].startswith(f"task {task_id} finished: ")]
    after = [e for e in log if accepted is not None and e["order"] > accepted["order"]]
    stopping = next(
        (
            e
            for e in after
            if e["logger"] == "orbital.bridges.cli" and STOP_LINE.match(e["message"])
        ),
        None,
    )
    stopped = None
    restart = None
    if stopping is not None:
        stopped = next(
            (
                e
                for e in after
                if e["order"] > stopping["order"]
                and e["logger"] == "orbital.bridges.cli"
                and e["message"] == "stopped"
            ),
            None,
        )
        if stopped is not None:
            restart = next(
                (
                    e
                    for e in after
                    if e["order"] > stopped["order"]
                    and e["logger"] == "orbital.bridges.cli"
                    and e["message"].startswith("listening on ")
                ),
                None,
            )
    return {
        "accepted": accepted,
        "executor": executor,
        "finished": finished,
        "stopping": stopping,
        "stopped": stopped,
        "restart": restart,
    }


def stop_signal(stopping: dict[str, Any]) -> str | None:
    match = STOP_LINE.match(stopping["message"])
    return match.group(1) if match else None
