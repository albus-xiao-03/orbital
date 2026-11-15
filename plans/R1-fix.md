# R1 Fix Plan — QA-01 … QA-06

> Project `ORBITAL` — Requirement 1. Targeted corrections for the findings of the QA report `qas/R1.md`.

**Status: implemented and verified locally (revision 3, 2026-11-15).** You approved revision 2 with the decisions below. Phases 12.0 – 12.5 are complete; their results are in §14, and the hand-over (12.6) is in our conversation. Still pending: your targeted dual-sandbox re-test (A-1, A-2, A-3).

| Item | Value |
|---|---|
| Decisions (2026-11-15) | **D1:** Option A, a graceful SIGHUP stop that keeps an inherited SIGHUP-ignore (`nohup`). **D2:** approved, the stop line names its signal. **D3:** targeted re-test, A-1 (D-9), A-2 (D-7) and A-3 (D-2) by you, carrying the other valid evidence forward. **D4:** approved, the logging note in `docs/bridges.md`. **D5:** no local real-Claude rehearsal; the simulated tests are used. |
| Basis | `qas/R1.md` (commit `b20cb59`): findings QA-01 … QA-06, from the dual-sandbox run `r1-20261115T030647Z-bc9829` and the reproduction of the D-9 stop |
| Code under review | `src/orbital` at HEAD, identical to `eef7a7b` (digest `1cc88d273dac7ad88774dc7d2227b6a33544a871550368b58747b809c488cba7`) |
| Governing documents | `CONSTRICTION.md`, which overrides everything; `specs/R1.md`; `plans/R1.md`, revision 5 |
| Scope | QA-01 … QA-06 only. The two additions that go beyond a finding's letter are listed in §2 and need your approval (decisions D2 and D4). |

## Contents

1. [Summary](#1-summary)
2. [Ground rules and scope](#2-ground-rules-and-scope)
3. [QA-01 — the documented log capture loses the stop record](#3-qa-01--the-documented-log-capture-loses-the-stop-record)
4. [QA-02 — SIGHUP: correct it in R1, or document it as a limitation](#4-qa-02--sighup-correct-it-in-r1-or-document-it-as-a-limitation)
5. [QA-03 — process checks that cannot show termination](#5-qa-03--process-checks-that-cannot-show-termination)
6. [QA-04 — verification that did not follow the documented procedure](#6-qa-04--verification-that-did-not-follow-the-documented-procedure)
7. [QA-05 and QA-06 — informational findings](#7-qa-05-and-qa-06--informational-findings)
8. [Change set and commits](#8-change-set-and-commits)
9. [Verification](#9-verification)
10. [Decisions requested](#10-decisions-requested)
11. [Implementation phases and gates (Phase 12)](#11-implementation-phases-and-gates-phase-12)
12. [Out of scope](#12-out-of-scope)
13. [Definition of done](#13-definition-of-done)
14. [Verification status](#14-verification-status)
15. [Revision history](#15-revision-history)

---

## 1. Summary

| Finding | Classification | Needed for R1 acceptance | Proposed correction | Files |
|---|---|---|---|---|
| **QA-01** | Documentation / procedure defect | **Yes** | Start the server with its output redirected straight to the log file (`>> serve.log 2>&1`) instead of piping it through `tee`, and follow the file with `tail -f` | `plans/R1.md` (§14 C, §16 D-8 and D-9); a logging note in `docs/bridges.md` (D4) |
| **QA-02** | Implementation defect: a gap in shutdown handling, outside the written design but against its intent; also a documentation omission | Not required by the spec. **Recommended** for R1 (decision D1). | **Option A, recommended:** treat SIGHUP as a graceful stop, like SIGTERM, unless SIGHUP was already ignored at startup (as under `nohup`). **Option B:** document it as a limitation. | A: `cli/serve_command.py`, `docs/bridges.md`, `plans/R1.md`. B: `docs/bridges.md`, `README.md`, `plans/R1.md`. |
| **QA-03** | Verification weakness (procedure) | **Yes**, to show that nothing is left running in D-7 and D-9 | Run the checks within 30 s of the event, printing their own UTC time, and add a transcript check that does not depend on timing | `plans/R1.md` (§16 D-7, D-9 and the evidence list) |
| **QA-04** | Verification weakness (process) | **Yes**, as part of verifying this fix; no product change | Temporary tests that run the documented server commands word for word in a terminal and stop them the documented ways; a documentation-consistency check; a table of how each documented action was rehearsed; a correction of §20's claim | `.tmp/r1/tests/` (temporary); `plans/R1.md` (record) |
| **QA-05** | Informational (evidence collection) | In part: `serve.log` as a file, with its stop lines, is D-9's evidence | Covered by QA-01 (the log is complete), D2 (the stop line names its signal) and the updated evidence list | `plans/R1.md` (§16) |
| **QA-06** | Informational | No | None. A manual re-run uses the plan's commands word for word, so re-running D-7 sends the waiting form of `submit` through the real proxy. | — |

**Implementation impact.** At most one source file changes: `src/orbital/bridges/cli/serve_command.py`, about 10 lines, under Option A only. Everything else stays as it is:

- the architecture and wire protocol v1;
- the `BridgeClient` and `BridgeServer` APIs;
- the CLI commands, options, JSON outputs and exit codes;
- authentication, credential isolation and the security boundaries;
- the executor and its termination sequence;
- the Claude Code invocation.

**Real Claude use.** None in this planning step, and none locally during implementation. Your acceptance re-test needs 2 runs (D-7 and D-9), plus 1 optional run. A full re-run would need 6 runs, plus the same optional one (decision D3).

**Decisions requested (§10):**

- **D1:** QA-02, fix SIGHUP or document it.
- **D2:** name the signal in the stop line.
- **D3:** the scope of the re-test.
- **D4:** a logging note in `docs/bridges.md`.
- **D5:** an optional local real-Claude rehearsal, which I do not propose.

---

## 2. Ground rules and scope

- **`CONSTRICTION.md`:**
  - each file's change is committed on its own, with a description, using a `change:` prefix; code and documents are in separate commits;
  - every test written for the fix is temporary, under `.tmp/r1/`: never committed, never deleted;
  - only the `.env` environment is used, and no dependency is added;
  - `config`, `push`, `branch`, `checkout`, `switch` and `reset` are not used.
- **Preserved:**
  - the architecture (plan §5) and the wire protocol (§8);
  - the public API and the CLI surface;
  - the authentication and security model (§9);
  - the executor and its descendant-tree termination (§10);
  - the Claude Code invocation and its result contract.
- **The fix is not:**
  - the future host-level test harness, which is a separate project component;
  - any ChatGPT-side harness;
  - a package-level test suite;
  - orphan prevention for crashes or `SIGKILL`.

  §12 has the full list.
- **Scope additions that need your approval,** because each goes slightly beyond the letter of a finding:
  - **D2**, the stop line names its signal. It is one line in the same function as Option A, and it records the stop method that QA-05 found missing.
  - **D4**, a short logging note in `docs/bridges.md`. It is the operator-facing side of QA-01.

  Nothing else is added.

---

## 3. QA-01 — the documented log capture loses the stop record

### Root cause and evidence

The plan starts the server as `orbital-bridge serve … 2>&1 | tee -a ~/orbital-acceptance/serve.log` (§14 C, §16 D-8 and D-9) and stops it with Ctrl-C. Ctrl-C makes the terminal send SIGINT to every process of the foreground job, `tee` included.

1. `tee` exits at once.
2. The server performs its graceful stop. The four lines it logs while stopping are written to a pipe with no reader, and Python's logging ignores the failed writes. The lines lost are `stopping`, `Claude Code exited with status 143`, `finished: failed (execution_cancelled)` and `stopped`.
3. The server's only log destination is stderr (plan §10).

| Evidence | Result |
|---|---|
| Documented command, Ctrl-C (`.tmp/r1/qa/runs/…-tee-54f9ff`, `…-tee-4756fb`, `…-tee-7951d9`) | `serve.log` holds only `accepted` for the task, in 3 runs of 3. This is your D-9 observation. Nothing was left running 0.7 s after the stop. |
| Controls: `tee -i` (`…-tee-i-569f46`) and `>> serve.log 2>&1` (`…-redirect-4f6037`) | All four lines logged; nothing left running |
| Stage R `serve.log` (log written by the server itself) | The four lines at the D-9 stop |
| Code | `cli/serve_command.py` logs `stopping` and `stopped`, `executor/claude_code_executor.py` the exit, and `server/task_supervisor.py` the `finished` line. All of them go through `logging` to stderr (`cli/utils.py`, `configure_logging`). |

### Classification

A documentation and procedure defect. The `orbital.bridges` code behaves as designed: the stop completes and is logged. `README.md` and `docs/bridges.md` never use `tee` and are not wrong.

### Needed for R1 acceptance

**Yes.** With the documented command, D-9's expectation that `serve.log` shows the task cancelled can never be met.

### Proposed correction

**C4, `plans/R1.md` §14 C.** The server writes its log straight into the file:

```bash
mkdir -p ~/orbital-acceptance/workdir
orbital-bridge serve --port 8765 --workdir ~/orbital-acceptance/workdir >> ~/orbital-acceptance/serve.log 2>&1
```

Follow the log, and later run the §16 checks, from a second terminal in the Claude sandbox:

```bash
tail -f ~/orbital-acceptance/serve.log
```

New text: "Stop the server with Ctrl-C in its terminal. That is a graceful stop: a running task is terminated and reaped, and `serve.log` records it (§10). Do not pipe the server through `tee`: Ctrl-C stops `tee` too, and the lines logged while the server stops are lost (`qas/R1.md`, QA-01)." The decision on QA-02 adds one sentence:

- Option A: "Closing the server's terminal is also a graceful stop."
- Option B: "Do not close the server's terminal while a task runs: that is not a graceful stop (§10)."

**C4, `plans/R1.md` §16 D-8.** Only the command form changes, in both places where the server is started:

```bash
ORBITAL_BRIDGE_CLAUDE_ARGS='--permission-prompts none --model orbital-no-such-model' \
  orbital-bridge serve --port 8765 --workdir ~/orbital-acceptance/workdir >> ~/orbital-acceptance/serve.log 2>&1
```

**C4, `plans/R1.md` §16 D-9.** The same command form for the restart; the D-9 checks are in §5.

**C2, `docs/bridges.md`** (decision D4). Add one note to the command-line section: "`serve` logs to stderr. To keep a log file, redirect it: `orbital-bridge serve … >> serve.log 2>&1`. Piping through `tee` loses the lines logged during a Ctrl-C stop, because Ctrl-C stops `tee` too."

### Alternatives considered

| Alternative | Why it was not chosen |
|---|---|
| `… 2>&1 \| tee -i -a serve.log` | It keeps live output and survives Ctrl-C (verified, `…-tee-i-569f46`). But `tee -i` ignores only SIGINT, so a closed terminal still kills it. Under Option A, the lines of a SIGHUP stop would be lost again. |
| A `--log-file` option or `ORBITAL_BRIDGE_LOG_FILE` | It adds an interface and file-handling code to the server. The procedure change removes the defect without any code. |
| Running the server under `nohup` or `setsid` | It changes how the server is stopped (no Ctrl-C) and adds operator steps |

### Affected files

`plans/R1.md`, and `docs/bridges.md` if D4 is approved. No code.

### Risks

- **No live output in the server's terminal.** Mitigated by `tail -f` in the second terminal, which the checks need anyway.
- **Redirection order typed wrongly** (`2>&1 >> file`). The exact command is given, and DOC-01 checks the plan's text.
- **Habitual `tee`.** The warning in §14 C and the note in `docs/bridges.md` address it.

### Tests

- **Local (§9.1):** IT-17a (the corrected command in a terminal, stopped with Ctrl-C), IT-17d (the D-8 form), DOC-01, and the reproduction re-run.
- **Acceptance (§9.2):** A-1, the corrected D-9.

---

## 4. QA-02 — SIGHUP: correct it in R1, or document it as a limitation

### Root cause and evidence

- `cli/serve_command.py` (lines 89–103) makes only SIGTERM a graceful stop, through its `interrupt` handler. SIGINT is turned into `KeyboardInterrupt` by Python itself. SIGHUP keeps its default action, which ends the process at once, so `server.stop()` never runs.
- Claude Code runs in its own session (`start_new_session=True`, `executor/process_runner.py:87`; this is by design, so that the whole group can be signalled). It therefore does not receive the terminal's SIGHUP and keeps running.
- Evidence: run `.tmp/r1/qa/runs/…-hangup-3be2a9`. The terminal running the documented pipeline was closed. The server disappeared at once and logged nothing, and 0.5 s later the simulated Claude Code process and its `sleep 60` were still running.

### Classification

An implementation defect of limited scope, plus a documentation omission.

- The written design (§10) promises a graceful stop only for SIGINT and SIGTERM, and documents crash and `SIGKILL` orphans as a deferred limitation (R9, §18). SIGHUP is mentioned nowhere: not in the plan, `README.md`, `docs/bridges.md` or `serve --help`.
- No objective or acceptance criterion of `specs/R1.md` covers process cleanup at shutdown. AC4 holds on the client side either way: D-9b and D-9c report `communication_error`.

### Evaluation: correct it in R1, or keep it as a documented limitation

| Criterion | Assessment |
|---|---|
| Is the behaviour verified? | Yes, reproduced (above) |
| Does it violate the spec? | No |
| Does it conflict with the design's intent? | Yes. §10's graceful stop exists so that "nothing is left running" after an operator stops the server, and §14 C runs the server in a dedicated terminal. Losing that terminal is an ordinary operator event, not a crash. |
| How likely is it? | Plausible in the documented operating model: closing the terminal window, ending a sandbox shell session, or a dropped connection all deliver SIGHUP. Whether `sbx` delivers SIGHUP, SIGTERM or SIGKILL when its session closes is unknown; acceptance test A-4 would show it. |
| Consequence | An autonomous Claude Code run keeps acting on the delegated prompt **with no execution deadline**, because the deadline is enforced by the server process that is gone. Its result is lost. After a restart, a new task can run at the same time as the orphan, because "at most one task runs" covers only the tasks the new process knows about (§10). The operator gets no Claude-side record. |
| Size and risk of a fix | Small and contained. SIGHUP joins SIGTERM on the existing, already verified graceful-stop path (IT-14, IT-14b, Stage R D-9): about 10 lines in one function. There is no new mechanism and no change to the protocol, API, executor or security. |
| Scope | SIGHUP can be caught, so the existing stop path applies unchanged. It does not reach into the deferred items: crash and `SIGKILL` handling, parent-death signals, or a persistent registry. |
| Effect on the D-9 evidence | The returned evidence cannot rule out that a hangup, not QA-01, produced the D-9 observation (`qas/R1.md` QA-01). Under Option A, that ambiguity no longer arises in future runs. |

**Recommendation: Option A, correct it in R1.** It closes a common operator path to exactly the failure the graceful stop exists to prevent, with a minimal change on a path that is already verified. The alternative relies on an operator rule, "never lose the server's terminal while a task runs", that cannot be enforced against a dropped connection.

Option B is acceptable if you prefer no code change at all. It does not affect the acceptance procedure, which stops the server with Ctrl-C.

### Option A — proposed correction (C1, `src/orbital/bridges/cli/serve_command.py`)

The behaviour to implement:

| How the server is stopped | Today | Option A |
|---|---|---|
| Ctrl-C (SIGINT) | graceful | graceful (unchanged) |
| `SIGTERM` | graceful | graceful (unchanged) |
| Terminal closed or connection lost (SIGHUP) | exits at once; the run is orphaned; nothing logged | **graceful**, logged as `stopping (SIGHUP)` (with D2) |
| SIGHUP after starting under `nohup` (SIGHUP ignored at startup) | ignored; the server keeps running | ignored; unchanged, `nohup` is respected |
| A second stop signal during the stop | SIGINT and SIGTERM ignored | SIGINT, SIGTERM **and SIGHUP** ignored |
| `SIGKILL`, a crash, `SIGQUIT` | orphan (documented, R9) | unchanged (documented, R9) |

A sketch for review; the final code follows the module's conventions and passes `mypy --strict`:

```python
received: list[str] = []

def interrupt(signum: int, frame: Any) -> None:
    received.append(signal.Signals(signum).name)
    raise KeyboardInterrupt

previous_term = signal.signal(signal.SIGTERM, interrupt)
# Closing the terminal (SIGHUP) stops the server gracefully too, unless SIGHUP was ignored
# when the server started (for example under nohup); that choice is respected.
hangup = signal.getsignal(signal.SIGHUP) is not signal.SIG_IGN
previous_hup = signal.signal(signal.SIGHUP, interrupt) if hangup else None
try:
    server.serve_forever()
except KeyboardInterrupt:
    log.info("stopping (%s); the running task, if any, is terminated and reaped",
             received[0] if received else "SIGINT")          # D2
finally:
    # Do not let a second signal interrupt the graceful stop.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if hangup:
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
    server.stop()
    # restore SIGTERM, SIGHUP (when it was installed) and SIGINT as before
log.info("stopped")
```

In the same file:

- The `serve` help text changes from "Stop it with Ctrl-C or SIGTERM" to also name closing the terminal (SIGHUP) and the `nohup` exception.
- The `ServeCommand` docstring changes to match.

**Verified while planning.** Python reports an inherited `nohup` as `signal.getsignal(signal.SIGHUP) is signal.SIG_IGN` → `True` (`.env` Python 3.13). This was a one-line check; nothing in the repository changed.

**Documentation under Option A:**

- **C2, `docs/bridges.md`.** The restart-semantics row becomes "A graceful stop (Ctrl-C, `SIGTERM`, or closing the server's terminal: `SIGHUP`)", with the `nohup` exception. The crash and `SIGKILL` row stays.
- **C4, `plans/R1.md`.** In §10, "Graceful stop" and "Shutdown" name SIGHUP and the `nohup` exception, and the logging list notes that the stop line names its signal (D2). In §17, R9 is narrowed: a hangup no longer orphans the run; a crash and `SIGKILL` still do.
- **`README.md`** needs no change: "Stop it with Ctrl-C. This is a graceful stop" stays true.

### Option B — documented limitation

There is no code change.

- **C2, `docs/bridges.md`.** A new row: "Closing the server's terminal (`SIGHUP`): not a graceful stop. The server exits at once, as after a crash (next row). Keep the terminal open and stop with Ctrl-C."
- **C3, `README.md`.** One sentence after "Stop it with Ctrl-C": closing the terminal instead is not a graceful stop and can leave Claude Code running.
- **C4, `plans/R1.md`.** §10 and §14 C gain the same warning, and R9 names SIGHUP as a trigger.

The residual risk stays as it is today.

### Affected files

| Option A | Option B |
|---|---|
| `serve_command.py`, `docs/bridges.md`, `plans/R1.md` | `docs/bridges.md`, `README.md`, `plans/R1.md` |

### Risks (Option A)

| Risk | Handling |
|---|---|
| After a hangup, log writes to the vanished terminal fail with `EIO` in the `README.md` form, which has no redirection | Logging ignores write errors, as it did in QA-01's reproduction, so the stop completes. The log is lost with the terminal, like any terminal output. IT-17c checks that nothing is left. |
| Anyone relying on SIGHUP to end the server immediately | It now stops gracefully, which takes at most about 10 s with a task running (5 s grace, then reaping) |
| `nohup` users expect SIGHUP to be ignored | Respected: an inherited `SIG_IGN` is detected, and the handler is not installed (IT-14d) |
| Repeated SIGHUP: bash re-sends it to its jobs, and the kernel may add SIGHUP and SIGCONT | Ignored during the stop, as SIGINT and SIGTERM are today (IT-14e) |
| What `sbx` sends when its session closes is unknown | SIGHUP and SIGTERM both become graceful; `SIGKILL` remains the documented crash case. Optional test A-4 shows the actual behaviour. |
| Portability | SIGHUP is POSIX, and the executor already requires POSIX (process groups, `/proc`) |
| The stop-line text changes (D2) | IT-14 matches `stopping` and still passes; the plan's quoted lines are updated in C4 |

### Tests

- **Option A, local:** IT-14c, IT-14d, IT-14e, IT-17b and IT-17c (§9.1); IT-14 and IT-14b unchanged; CLI-01 unchanged, since no option or output changes.
- **Option A, acceptance:** A-3, plus the optional A-4.
- **Option B:** IT-17b and IT-17c become characterization tests of the documented limitation. Like IT-16, they assert the orphan and then stop it.

---

## 5. QA-03 — process checks that cannot show termination

### Root cause and evidence

- The procedure says to stop the server "within about 10 s" but sets no deadline for the `pgrep` checks and does not ask for the time they were made.
- A surviving `sleep 60` ends by itself about a minute after it starts, so a check discriminates only within that window.
- In the run, the four D-7 and D-9 checks were recorded 3 min 51 s to 5 min 25 s after submission (`qas/R1.md` QA-03). The harness recorded when each result was entered, not when it was observed.

### Classification

A verification weakness in the procedure. It is not a product defect.

### Needed for R1 acceptance

**Yes**, for the Claude-side half of D-7 and D-9, "nothing is left running". Without discriminating evidence, AC4's Claude-side termination stays undemonstrated across the sandboxes.

### Proposed correction (C4, `plans/R1.md` §16)

The prompts stay as they are. `sleep 60` behaved as expected with real Claude Code in Stage R and in the dual-sandbox run, and it stays well within the default time limit of Claude Code's Bash tool. A longer sleep is untested with real Claude Code, and the tool could cut it short or move it to the background.

**D-7:**

```bash
# ChatGPT sandbox
step D-7 submit --execution-timeout 10 'Run the shell command "sleep 60", then reply with the word SLEPT.'
# Claude sandbox, second terminal, as soon as the result appears (within 30 s; type this line in advance)
date -u +%FT%TZ; pgrep -af -- '--output-format json --session[-]id' || echo none; pgrep -af '^sleep 6[0]$' || echo none
# Claude sandbox, any time later (substitute the task_id printed above)
grep '<task_id>' ~/orbital-acceptance/serve.log
ls -l --time-style=full-iso ~/.claude/projects/*/<task_id>.jsonl
grep -c '"text":"SLEPT"' ~/.claude/projects/*/<task_id>.jsonl
```

Expected for D-7:

- `timed_out` / `execution_timeout`, exit 3.
- The check prints a time no more than 30 s after the result, then `none` twice. A later check does not count: repeat the step, which costs one Claude run.
- `serve.log` shows the task accepted, `Claude Code timed out after …` and `finished: timed_out (execution_timeout)`.
- The transcript was last written within a few seconds of the `timed out` line (both are in the Claude sandbox's local time), and the `SLEPT` count is 0.

**D-9:**

```bash
# ChatGPT sandbox
step D-9a submit --max-wait 0 'Run the shell command "sleep 60", then reply with the word SLEPT.'
# Claude sandbox, server terminal, within about 10 s: stop the server (Ctrl-C)
# Claude sandbox, second terminal, as soon as the server has exited (within 30 s)
date -u +%FT%TZ; pgrep -af -- '--output-format json --session[-]id' || echo none; pgrep -af '^sleep 6[0]$' || echo none
tail -n 6 ~/orbital-acceptance/serve.log
# ChatGPT sandbox
step D-9b wait "$(tid D-9a.json)" --max-wait 20
# Claude sandbox: restart the server normally (§14 C); then, in the ChatGPT sandbox
step D-9c wait "$(tid D-9a.json)" --max-wait 0
# Claude sandbox, any time later (substitute D-9a's task_id)
grep '<task_id>' ~/orbital-acceptance/serve.log
ls -l --time-style=full-iso ~/.claude/projects/*/<task_id>.jsonl
grep -c '"text":"SLEPT"' ~/.claude/projects/*/<task_id>.jsonl
```

Expected for D-9:

- D-9a gives `running`, exit 6.
- The check prints a time no more than 30 s after the stop, then `none` twice.
- `serve.log` ends with `stopping (SIGINT); …` (with D2; otherwise `stopping; …`), `task <id>: Claude Code exited with status 143 …`, `task <id> finished: failed (execution_cancelled) …` and `stopped`.
- The transcript was last written within a few seconds of the `stopping` line, and the `SLEPT` count is 0.
- D-9b and D-9c are unchanged.

**Why the transcript check.** It is the timing-independent confirmation that the Claude Code run ended at the stop or the timeout rather than running to completion. It was validated on Stage R's transcripts: the cancelled D-9 run has no `SLEPT` reply and was last written at the stop, while the completed D-6 run has one. It cannot see a surviving tool process in its own session; only the timely `pgrep` covers that, together with the bridge's own descendant-tree termination.

**D-3** has the same caveat for its `pgrep`. Its evidence is already independent of timing, though: `serve.log` shows only the two authentication failures, and no task is accepted. No change is proposed.

### Affected files

`plans/R1.md`. No code.

### Risks

| Risk | Handling |
|---|---|
| The operator is still late | The printed time makes it visible, and the step is repeated. This adds at most one Claude run each for D-7 and D-9 (§9.3). |
| The transcript location or format differs in another Claude Code version | Validated with 2.1.322. If it differs, the evidence falls back to the timely `pgrep` and `serve.log`, and the difference is noted. |
| Reading transcripts | They are read only, and stay in the Claude sandbox |

### Tests

- **Acceptance:** A-1 (D-9) and A-2 (D-7).
- **Local:** IT-17a asserts the same `serve.log` lines with the fake Claude. The transcript check needs real Claude Code and is covered by A-1 and A-2.

---

## 6. QA-04 — verification that did not follow the documented procedure

### Root cause and evidence

None of the local verification started or stopped the server as §14 C documents. The evidence:

- `.tmp/r1/tests/helpers.py` (`ServerProcess`: `Popen(…, stdout=<log file>, stderr=STDOUT)`, and a signal to the server process only);
- `.tmp/r1/runs/stage-r/env.sh` (`start_server` with `Popen` into `serve.log`, and `stop_server` with `kill -INT <pid>`);
- the harness simulation (a file handle, and SIGINT to the server process).

No test signalled the whole terminal job, and the hand-over (§20) still reported that the procedure "needed no correction".

### Classification

A verification weakness in the process. It is not a product defect.

### Needed for R1 acceptance

**Yes**, as part of verifying this fix. Without faithful tests, the corrections to QA-01 and QA-02 would be verified the same way that missed them.

### Proposed correction

1. **Faithful temporary tests (§9.1).** IT-17a … IT-17d run the documented server command forms word for word, changing only the port, workdir and log path, with the fake Claude selected through `ORBITAL_BRIDGE_CLAUDE_BIN`. Each runs in an interactive `bash` on a pseudo-terminal, defines `orbital-bridge` as in plan §14 B, and stops the server the documented ways: Ctrl-C typed into the terminal, or the terminal closed. They reuse the terminal driver of `.tmp/r1/qa/repro_serve_log.py`; temporary tests may reuse temporary code.
2. **Documentation consistency (DOC-01).** Every `orbital-bridge serve` command in `plans/R1.md` §14 C and §16 must be a form that IT-17a or IT-17d runs. No documented server command, in `plans/R1.md`, `README.md` or `docs/bridges.md`, may pipe through `tee`.
3. **A rehearsal-fidelity table in the hand-over.** It lists each documented operator action of §14 and §16 and how it was rehearsed: word for word, with substitutions, or not at all, and why.
4. **Correct the record (C4).** Add a correction note to §20's "Your dual-sandbox run" stating that the rehearsal did not run §14 C's command and that its claim of needing no correction was wrong (QA-04). Record this fix round in a new section of `plans/R1.md`.

### Affected files

`.tmp/r1/tests/` (temporary, never committed) and `plans/R1.md`.

### Risks

Tests on a pseudo-terminal can be timing-sensitive. They use bounded waits and generous timeouts, and each is run 3 times in the final regression.

### Tests

These are themselves the tests: IT-17a … IT-17d, DOC-01, and the reproduction re-run.

---

## 7. QA-05 and QA-06 — informational findings

### QA-05 — the returned evidence omits the Claude sandbox's environment and server lifecycle

| | |
|---|---|
| Root cause | §16 already asks for `serve.log` from the Claude sandbox, but only excerpts came back, as manual-check observations. Because of QA-01, the file would have lacked the stop lines anyway, and no log line names how the server was stopped. |
| Classification | Informational (evidence collection) |
| Needed for acceptance | In part: D-9's evidence is the `serve.log` file with its stop lines. The Claude Code version is informational (risk R3). |
| Correction | Mostly covered by other changes. QA-01's correction makes the file complete, and its `listening` lines carry the Claude Code version and each start time. D2 records each stop's time and signal. C4 updates §16's evidence list: the whole `serve.log` file; every process-check output with its time line; for D-7 and D-9, the transcript `ls -l` line and the `SLEPT` count; and a note on any stop not made with Ctrl-C. |
| Files | `plans/R1.md`, plus `serve_command.py` for D2 |
| Risks | None beyond D2's (§4) |
| Tests | IT-14c and IT-17a assert the stop line; A-1 checks the returned file |

### QA-06 — some plan commands were not run word for word through the real proxy

| | |
|---|---|
| Root cause | The removed harness split every submission into `submit --max-wait 0` followed by `wait` |
| Classification | Informational |
| Needed for acceptance | No. The HTTP exchanges are the same requests, and the single-command forms are covered locally (IT-01, IT-07, CLI-01, Stage R). |
| Correction | None. Your re-test follows §16 word for word with the `step` helper, so A-2 (D-7) runs the waiting `submit` through the real proxy. How the future host-level harness runs commands is a matter for that separate component, not for this fix. |

---

## 8. Change set and commits

Each commit changes one file and carries a description. Code and documents are separate. The tests are temporary and never committed.

| Order | Commit (subject) | File | When |
|---|---|---|---|
| 1 | `change: record the authorization of the R1 fix plan` | `plans/R1-fix.md` | Always: the status becomes approved, and decisions D1–D5 are recorded |
| 2 | `change: treat SIGHUP as a graceful stop in \`serve\`` | `src/orbital/bridges/cli/serve_command.py` | Option A only (with D2, if approved) |
| 3 | `change: document stopping and log capture in \`docs/bridges.md\`` | `docs/bridges.md` | Always: the SIGHUP row for A or B, and the logging note if D4 is approved |
| 4 | `change: warn that closing the server's terminal is not a graceful stop` | `README.md` | Option B only; **not applicable**, since Option A was chosen |
| 5 | `change: correct the dual-sandbox procedure in \`plans/R1.md\`` | `plans/R1.md` | Always (revision 6): §10, §14 C, §16 D-7, D-8, D-9 and the evidence list, the test matrix, R9, §19, the §20 correction note, a new fix-round section, and the status line |
| 6 | `change: record the R1 fix verification status` | `plans/R1-fix.md` | Always, after the local regression |

No other tracked file changes. In particular, `qas/R1.md` stays the record of that QA pass; a QA re-assessment is a separate step at your request. `specs/`, `pyproject.toml` and the rest of `src/` are also unchanged.

---

## 9. Verification

### 9.1 Local regression (temporary; fake Claude only; no real Claude run)

| ID | Finding | Scenario | Expected after the fix | Before the fix |
|---|---|---|---|---|
| IT-14c | QA-02 | SIGHUP to the server process during a `tool-tree` task, with the log written to a file | Exit 0. The fake Claude and its separate-session tool child are reaped. The log has `stopping` (`stopping (SIGHUP)` with D2), `finished: failed (execution_cancelled)` and `stopped`. A poll gives `communication_error`. | Fails: the server dies at once and the orphans remain |
| IT-14d | QA-02 | Server started under `nohup`, SIGHUP sent during a task | The server keeps serving: ping is ok and the task ends `succeeded`. A later SIGTERM stops it gracefully. | Passes; it guards against a regression |
| IT-14e | QA-02 | A second stop signal (SIGHUP, SIGINT or SIGTERM) during the stop | The stop is not interrupted; exit 0; nothing left | The SIGHUP case fails |
| IT-17a | QA-01, QA-04 | §14 C's corrected command in a terminal; Ctrl-C typed during a D-9-style task | `serve.log` has `stopping` (`stopping (SIGINT)` with D2), `exited with status 143`, `finished: failed (execution_cancelled)` and `stopped`. Nothing is left within 1 s. | Passes with the corrected command, which fixes QA-01 without code. The old `tee` command fails, as reproduced. |
| IT-17b | QA-02, QA-04 | As IT-17a, but the terminal is closed | As IT-17a, with `stopping (SIGHUP)` | Fails: orphans |
| IT-17c | QA-02 | The `README.md` form (log on the terminal), then the terminal is closed | Nothing left. The log is lost with the terminal; the exit status is not asserted. | Fails: orphans |
| IT-17d | QA-01, QA-04 | §16 D-8's command form (`ORBITAL_BRIDGE_CLAUDE_ARGS=…`), started and then stopped with Ctrl-C | It starts; `stopping` and `stopped` are logged | — |
| DOC-01 | QA-01, QA-04 | A static check of the documented server commands (§6) | Every documented form is tested; no `tee` remains | Fails until commit 5 |
| QA-R | QA-01 … QA-04 | `.tmp/r1/qa/repro_serve_log.py` re-run, all variants | The `tee` variants still lose the lines; that is `tee`'s behaviour, and it documents why the procedure changed. Under Option A, the hangup variant leaves no orphan. | As in `qas/R1.md` |
| Gates and suite | all | `ruff check src`, `ruff format --check src`, `mypy` (strict), the full temporary suite (240 existing tests plus the new ones) | All pass; no leftover processes. The pseudo-terminal tests pass in 3 runs of 3. | 240 pass today |

Under Option B, IT-14c, IT-14e, IT-17b and IT-17c become characterization tests of the documented limitation (§4).

### 9.2 Acceptance re-test in the dual-sandbox environment (you)

You run the corrected procedure of `plans/R1.md` §16 by hand. The removed ChatGPT-side harness is not used, and the future host-level harness is not part of this fix.

| ID | Step | Claude runs | Required | Pass criteria |
|---|---|---|---|---|
| A-1 | D-9, corrected (§5) | 1 | **Yes** | D-9a `running`, exit 6. The timed check, within 30 s of the stop, prints `none` twice. `serve.log` has the four stop lines. The transcript ends at the stop with 0 `SLEPT`. D-9b `communication_error`, exit 4; D-9c `unknown_task`, exit 4. |
| A-2 | D-7, corrected (§5) | 1 | **Yes** | `timed_out` / `execution_timeout`, exit 3. The timed check, within 30 s of the result, prints `none` twice. `serve.log` has the timeout lines. The transcript ends about 10 s after `accepted`, with 0 `SLEPT`. |
| A-3 | D-2 | 0 | Recommended under Option A, as a smoke test of the new server code | `ok`, exit 0 |
| A-4 | D-9, stopped by closing the server's terminal instead of Ctrl-C | 1 | Optional, Option A only | As A-1, with `stopping (SIGHUP)`. It also shows what `sbx` sends when a session closes. |
| A-5 | D-1, D-3 … D-6, D-8 | 0 or 4 | Per decision D3: **carried over** (targeted re-test) | Either carried over from run `r1-20261115T030647Z-bc9829`, or re-run. A full re-run also repeats D-1 with the policy closed. |

Under D3 you run A-1, A-2 and A-3 by hand; A-4 stays optional.

**Why carrying the other steps over is justified.** Under Option A, the only source change is the server's signal handling and its stop line, inside `serve`. D-1 and D-3 … D-6 never stop the server. D-8's restarts are Ctrl-C stops whose outcome does not depend on the stop line. Under Option B the code is unchanged, so the earlier evidence covers the same code.

### 9.3 Claude run budget

| Activity | Runs | Account |
|---|---|---|
| This planning step | 0 | — |
| Local implementation and regression | 0; only the fake Claude | — |
| Your re-test, targeted (A-1, A-2) | 2 required, plus 1 optional (A-4) | Your Claude sandbox |
| Your re-test, full re-run (D3) | 6, plus 1 optional | Your Claude sandbox |
| Repeats allowed when a timed check is late (§5) | At most 1 each for D-7 and D-9 | Your Claude sandbox |

---

## 10. Decisions requested

| # | Decision | Options | Recommendation | Your decision (2026-11-15) |
|---|---|---|---|---|
| D1 | QA-02: SIGHUP handling | **A:** a graceful stop in R1, respecting `nohup`. **B:** a documented limitation. | **A** (§4) | **Option A**, keeping an inherited SIGHUP-ignore under `nohup` |
| D2 | The stop line names its signal (`stopping (SIGHUP); …`) | Approve or strike. It is one line in C1's function; under Option B it would be the only code change, so with B I recommend striking it. | Approve with A; strike with B | **Approved** |
| D3 | Scope of your acceptance re-test | **Targeted:** A-1, A-2, A-3, carrying over the other steps. **Full:** D-1 … D-9. | Targeted | **Targeted.** You run A-1 (D-9), A-2 (D-7) and A-3 (D-2) by hand after the implementation; the other valid evidence is carried forward. |
| D4 | The logging note in `docs/bridges.md` (QA-01, operator side) | Approve or strike | Approve | **Approved** |
| D5 | A local real-Claude rehearsal of the corrected D-7 and D-9 before your run (2 runs in this sandbox) | Not proposed: the changed behaviour does not depend on Claude Code, and the fake Claude reproduces F-4 exactly. Available if you want it. | Not proposed | **No rehearsal;** the simulated tests are used |

Your further instructions for the implementation:

- follow `CONSTRICTION.md` strictly;
- stay within the approved scope;
- preserve all earlier QA evidence;
- introduce no new ChatGPT-side or host-level test harness;
- show that the new tests reproduce each original defect before its fix and pass afterwards;
- leave the dual-sandbox re-test to you;
- report the changes, commits, test results and remaining limitations at the hand-over.

---

## 11. Implementation phases and gates (Phase 12)

The work continues the numbering of `plans/R1.md` §20, which assigned defect fixes to Phase 12. Nothing starts before your authorization.

| Phase | Work | Gate before the next phase |
|---|---|---|
| 12.0 | Record your decisions D1–D5 (commit 1) | Authorization received |
| 12.1 | Write the temporary tests (§9.1) and run them against the current code | The before-the-fix column of §9.1 is confirmed. This shows each defect before it is fixed. |
| 12.2 | Option A: change `serve_command.py` (commit 2) | `ruff check`, `ruff format --check` and `mypy --strict` clean; the full temporary suite and the new tests pass |
| 12.3 | Documentation: `docs/bridges.md` (commit 3); `README.md` under Option B (commit 4) | The texts match the tested behaviour |
| 12.4 | Procedure and record: `plans/R1.md`, revision 6 (commit 5) | DOC-01 passes |
| 12.5 | Final local regression: gates; full suite; pseudo-terminal tests 3 times; reproduction re-run; leftover check. Record the results, with the rehearsal-fidelity table, in this plan (commit 6). | Everything in §9.1 passes |
| 12.6 | Hand-over report in our conversation. You then run A-1 … A-5. | — |

If a gate fails, I stop and report rather than widening the change.

---

## 12. Out of scope

- The future host-level test harness, a separate project component, and any re-introduction of the ChatGPT-side harness.
- A `--log-file` option or any other logging redesign.
- Orphan prevention after a crash, `SIGKILL` or `SIGQUIT`: a parent-death signal, a subreaper or a watchdog. This stays a documented, deferred limitation (R9, §18).
- A persistent task registry, a cancellation endpoint, TLS, or any other deferred item of §18.
- Any change to the wire protocol, the client or server API, CLI options or outputs, exit codes, authentication, the executor's termination sequence, or the Claude Code invocation.
- A committed, package-level test suite, which would need a separate request under `CONSTRICTION.md`.
- Changes to `qas/R1.md`; a QA re-assessment is a separate step.

---

## 13. Definition of done

- [x] You have reviewed and authorized this plan; decisions D1–D5 are recorded (commit 1).
- [x] The corrections are committed, one file per commit, with code and documents separate: `a60be7d`, `44b8eb9`, `f8d7b21`. Commit 4 did not apply.
- [x] `ruff check`, `ruff format --check` and `mypy --strict` are clean on `src/`.
- [x] The temporary suite passes: 254 tests, the 240 existing ones and the 14 new ones. The new tests passed in 3 runs of 3, and no processes were left.
- [x] The before-the-fix behaviour was demonstrated by the new tests before the code change (Phase 12.1, §14).
- [x] No real Claude run was made locally, and no OpenAI access or host-level operation took place.
- [x] The verification status, including the rehearsal-fidelity table, is recorded in this plan (commit 6, §14) and reported to you.
- [ ] Your re-test passes: A-1 (D-9), A-2 (D-7) and A-3 (D-2); A-5 is carried forward under D3.

---

## 14. Verification status

Recorded on 2026-11-15, at the end of Phase 12.5. Evidence paths are relative to `.tmp/r1/`, which is temporary: never committed and never deleted.

### Commits

| Phase | Commit | File |
|---|---|---|
| 12.0 | `c38bedc` change: record the authorization of the R1 fix plan | `plans/R1-fix.md` |
| 12.2 | `a60be7d` change: treat SIGHUP as a graceful stop in `serve` | `src/orbital/bridges/cli/serve_command.py` |
| 12.3 | `44b8eb9` change: document stopping and log capture in `docs/bridges.md` | `docs/bridges.md` |
| 12.4 | `f8d7b21` change: correct the dual-sandbox procedure in `plans/R1.md` (revision 6) | `plans/R1.md` |
| 12.5 | `change: record the R1 fix verification status` (this revision) | `plans/R1-fix.md` |

Commit 4 (`README.md`) did not apply, because Option A was chosen. No other tracked file changed: `qas/R1.md`, `specs/`, `pyproject.toml` and `README.md` are unchanged, and `serve_command.py` is the only source file changed since `eef7a7b`.

### The new tests, before and after each fix

The new tests are temporary:

- IT-14c, IT-14d, IT-14e in `tests/integration/test_it_fix_signals.py`;
- IT-17a … IT-17d in `tests/integration/test_it_fix_terminal.py`;
- DOC-01 in `tests/integration/test_doc_consistency.py`;
- the terminal driver in `tests/operator_terminal.py`.

IT-17 and DOC-01 read the commands from the documents at run time, so each run types what the documents said at that moment.

| Test | 12.1, before any fix (`c38bedc`) | 12.2, code fixed, procedure not yet | 12.5, final (`f8d7b21`) |
|---|---|---|---|
| IT-14c, SIGHUP | **Failed:** exit −1 (killed by SIGHUP); the fake Claude Code and its tool left running; no stop record | passed | passed, 3 of 3 |
| IT-14c, SIGTERM and SIGINT | Failed only on the stop line naming the signal (D2, new behaviour); the stop itself was already graceful | passed | passed, 3 of 3 |
| IT-14d, `nohup` | passed (SIGHUP ignored) | passed | passed, 3 of 3 |
| IT-14e, SIGHUP as the second signal | **Failed:** a SIGHUP during a Ctrl-C stop killed the server partway through; the fake and its tool left running | passed | passed, 3 of 3 |
| IT-14e, SIGINT and SIGTERM as the second signal | passed | passed | passed, 3 of 3 |
| IT-17a, §14 C command, Ctrl-C | **Failed:** `serve.log` had none of the four stop lines (the documented `tee` command) | failed, as expected (procedure not yet corrected) | passed, 3 of 3 |
| IT-17b, §14 C command, terminal closed | **Failed:** the fake and its tool left running, and the plan's own D-9 check listed them; no stop record | failed only on the lost lines (`tee`); nothing left running | passed, 3 of 3 |
| IT-17c, `README.md` command, terminal closed | **Failed:** the fake and its tool left running | passed | passed, 3 of 3 |
| IT-17d, D-8 command, Ctrl-C | **Failed:** `stopping` and `stopped` lost (`tee`); the Claude Code arguments did arrive | failed, as expected (procedure not yet corrected) | passed, 3 of 3 |
| DOC-01 (3 checks) | 2 failed (`tee` in `plans/R1.md`; the log not written straight to the file); 1 passed | the same | passed, 3 of 3 |

Evidence:

- `runs/fix-12.1-before/`: `junit.xml`, `tests.log`;
- `runs/fix-12.2-code/`;
- `runs/fix-12.5-final/`;
- one directory per test under `runs/test_it_fix_signals/` and `runs/test_it_fix_terminal/`, holding `facts.json`, `serve.log` and `terminal.txt`.

### Gates and suite

| Run | Gates | Suite | Evidence |
|---|---|---|---|
| 12.2, code fixed (before its commit) | clean | 249 passed. The 5 failures were the procedure-dependent tests, as expected. | `runs/fix-12.2-code/` |
| 12.5, final at `f8d7b21` | `ruff check src`, `ruff format --check src` and `mypy` (strict, 46 source files) clean | **254 passed** (240 existing + 14 new) in 130.07 s; no processes left | `runs/fix-12.5-final/gates.log`, `junit.xml` |
| 12.5 repeats | — | The 14 new tests passed in runs 2 and 3 (43.0 s each) | `runs/fix-12.5-final/junit-new-run2.xml`, `junit-new-run3.xml`, `repeat.log` |

### Reproduction re-run (QA-R)

`qa/repro_serve_log.py`, unchanged, with every original variant; simulated Claude Code with D-9's prompt (`runs/fix-12.5-final/repro.log`).

| Variant | Before the fix (`qas/R1.md`) | After the fix | Run (`qa/runs/`) |
|---|---|---|---|
| `tee`, Ctrl-C | `accepted` only; nothing left | `accepted` only. This is `tee`'s behaviour, and it is why the procedure changed. Nothing left. | `20261115T051246Z-tee-79783d` |
| `tee -i`, Ctrl-C | full stop record | full stop record, with `stopping (SIGINT)` | `20261115T051251Z-tee-i-1e134e` |
| Redirect, Ctrl-C | full stop record | full stop record, with `stopping (SIGINT)` | `20261115T051255Z-redirect-a2cefc` |
| `tee`, terminal closed | The server died at once; Claude Code and its `sleep 60` left running | **Graceful stop in 0.31 s; nothing left.** The lines are lost with `tee`, which is why the procedure no longer uses it. | `20261115T051300Z-hangup-622055` |

### Rehearsal fidelity (QA-04)

| Documented operator action | How it was rehearsed in this round |
|---|---|
| §14 B, the `orbital-bridge` shell function | Word for word from `plans/R1.md`, with the `.env` Python in place of `python3` (`CONSTRICTION.md`), in IT-17a … IT-17d |
| §14 C, the server command | Word for word, with the port, workdir and log path replaced. The bind address came from `ORBITAL_BRIDGE_HOST=127.0.0.1`, and the fake Claude Code from `ORBITAL_BRIDGE_CLAUDE_BIN`. Run by IT-17a and IT-17b. |
| Stopping with Ctrl-C in the server's terminal | Ctrl-C typed into an interactive bash on a pseudo-terminal (IT-17a, IT-17d) |
| Closing the server's terminal | The pseudo-terminal closed (IT-17b, IT-17c) |
| §14 C, `tail -f serve.log` | Not rehearsed; it only reads the file |
| §16 D-8, the server command with `ORBITAL_BRIDGE_CLAUDE_ARGS` | Word for word in IT-17d; the arguments reach Claude Code |
| D-7 and D-9, the timed process check | The bridge-runs pattern was run right after each stop (IT-17a … IT-17c). The time line and the `sleep 6[0]` pattern were not rehearsed, because the fake's tool is `sleep 300`; the reproduction re-run covers `sleep 60`. |
| D-7 and D-9, the transcript check | Validated on Stage R's real transcripts (`qas/R1.md`); not run again, since D5 means no real Claude Code |
| `README.md`, the server command | Word for word in IT-17c |
| The other ChatGPT-side and Claude-side commands | Unchanged in this round. Covered by the existing suite and your earlier run. |

### Deviations from revision 2

1. **The stop handler ignores further stop signals as its first action,** as well as in `finally`. The sketch in §4 did so only in `finally`. This closes the short window in which a second signal, such as the second SIGHUP of a terminal hangup, could arrive before `finally` and skip `server.stop()`. The behaviour is as approved: a second stop signal during the stop is ignored.
2. **IT-14c is parametrized over SIGHUP, SIGTERM and SIGINT,** so that D2 (the stop line names its signal) is tested for every stop signal.
3. **IT-17a … IT-17d use the fake Claude Code's `tool-tree` mode** instead of D-9's prompt, because the temporary suite accepts only the fakes in `.tmp/r1/fakes/`. D-9's prompt itself is exercised by the reproduction re-run.

### Remaining limitations

- A crash, `SIGKILL` or `SIGQUIT` of the server still orphans the running Claude Code process (R9; deferred, `plans/R1.md` §18).
- **SIGINT keeps Python's own handler.** A second SIGTERM or SIGHUP arriving within a moment of a Ctrl-C, before the `finally` block has run, could still interrupt the stop. The window lasts one log write and a few signal calls, and it existed before. Every other ordering is covered by deviation 1 and IT-14e.
- A server started without redirection (the `README.md` form) loses its log with its terminal when the terminal is closed; the stop itself completes (IT-17c).
- A `tee` pipeline, with or without `-i`, loses the stop record when the terminal is closed, because `tee` dies on SIGHUP. The documents no longer use `tee`.
- The transcript check depends on Claude Code's transcript location and format, validated with 2.1.322.
- What `sbx` sends when its terminal session closes is unknown. Optional test A-4 would show it.
- Not yet verified across the sandboxes: A-1, A-2 and A-3, your re-test.

---

## 15. Revision history

| Revision | Date | Change |
|---|---|---|
| 1 | 2026-11-15 | Initial fix plan for QA-01 … QA-06 of `qas/R1.md`, for review. Nothing implemented. |
| 2 | 2026-11-15 | Approved. Records your decisions: D1 Option A, D2 approved, D3 targeted re-test (A-1, A-2, A-3 by you), D4 approved, D5 no local real-Claude rehearsal. Records your instructions for Phases 12.0 – 12.6. Commit 4 (`README.md`, Option B only) does not apply. |
| 3 | 2026-11-15 | Implemented and verified locally. Adds §14, Verification status: the commits; the new tests before and after each fix; the gates and the full suite (254 passed); the reproduction re-run; the rehearsal-fidelity table; deviations and remaining limitations. Updates the status line and the definition of done. |
