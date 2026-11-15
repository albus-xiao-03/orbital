# R1 dual-sandbox acceptance harness

`r1_acceptance` automates the dual-sandbox acceptance procedure of requirement R1, steps D-1 … D-9 in [plans/R1.md](../plans/R1.md) section 16. It runs **only in the ChatGPT-side Docker Sandbox** and acts as the ChatGPT side through the `orbital-bridge` command line. Its one other request is the unauthenticated HTTP request of D-3b.

- **Staged.** It runs in stages that end where you have to act. Before each stage it tells you exactly what to do, where to do it, what to check, and which command comes next.
- **Persistent.** Every observation is kept as immutable evidence. Nothing is ever overwritten or deleted, and an interrupted stage resumes without submitting a task twice.
- **Reported.** It produces a JSON and a Markdown report covering D-1 … D-9 and the criteria AC1 … AC7.
- **Hands off.** It never runs Docker or `sbx` commands, never changes network policies or published ports, and never starts or stops the Claude-side server. Those steps are yours, and the harness only records the observations you report.
- **Self-contained.** It is not part of the `orbital` package and uses only the Python standard library (3.11 or newer). It runs the `orbital` client from the `src/` directory of the same repository copy, so nothing needs installing.

## What is automated and what is yours

| Step | Automated, in the ChatGPT sandbox | Your part (host or Claude sandbox) |
|---|---|---|
| P-1 | The public API imports from `orbital.bridges`; `python -m orbital.bridges --help` works | — |
| D-1 *(optional)* | `ping` gives `communication_error` / `network_policy_blocked`, exit 4, and the proxy text is labelled unverified | Keep the network policy closed until D-1 has run, then open it |
| D-2 | `ping` gives `{"ok": true}`, exit 0 | — |
| D-3 | D-3a: `ping` with a random wrong key gives `unverified_auth_rejection`, exit 4. D-3b: unsigned `POST /v1/tasks` gives `401` with `WWW-Authenticate: ORBITAL-HMAC-SHA256` | Before D-4 starts: no bridge-started Claude run (`pgrep`); `serve.log` shows the two authentication failures |
| D-4 | `succeeded`, response `ORBITAL-OK`, exit 0, same task id | `serve.log` shows the task accepted and finished |
| D-5 | `succeeded`, exit 0; the file is **absent** in the ChatGPT sandbox | The file in the Claude sandbox contains `ORBITAL-R1` |
| D-6 | D-6a: a 5 s wait gives `running` / `wait_deadline_reached`, exit 6. D-6b: `succeeded`, `SLEPT`, exit 0, same task id | — |
| D-7 | `timed_out` / `execution_timeout`, exit 3 | Right afterwards: no bridge-started Claude run and no `sleep 60` (two `pgrep` checks) |
| D-8 | `failed` / `claude_error`, exit 1, `api_error` in the message | Restart the server with an invalid model before D-8; restart it normally afterwards |
| D-9 | D-9a: `running`, exit 6. D-9b: `communication_error` (`gateway_error`, `connection_failed` or `connection_interrupted`), exit 4. D-9c: `unknown_task`, exit 4, naming a server start time after D-9a | Stop the server within about 10 s of D-9a. Then: the task is cancelled in `serve.log`, and nothing is left (two `pgrep` checks). Restart the server before D-9c. |

The harness never claims what only the Claude sandbox shows. Those checks stay **pending-manual** until you record them.

## 1. Getting the harness into the ChatGPT sandbox

The harness is committed in this repository, in `acceptance/`, next to `src/`. Use either method; neither needs a shared filesystem or anything from the development sandbox.

**A. A repository copy (recommended).** On the host, make a separate copy of the repository at the commit to test, and create the ChatGPT sandbox from it as you normally do:

```bash
git clone --branch feature/bridge <path of the orbital repository> orbital-chatgpt
git -C orbital-chatgpt log -1 --oneline      # the commit under test
```

**B. One archive file.** On the host, pack the two directories at the commit to test, and note the checksum:

```bash
git -C <path of the orbital repository> archive --format=tar.gz -o orbital-r1-acceptance.tar.gz HEAD acceptance src
sha256sum orbital-r1-acceptance.tar.gz
```

Put the file into the ChatGPT sandbox's workspace, then, inside the sandbox:

```bash
sha256sum orbital-r1-acceptance.tar.gz       # must match the value from the host
mkdir -p ~/orbital-chatgpt && tar -xzf orbital-r1-acceptance.tar.gz -C ~/orbital-chatgpt
```

**Checking what runs.** `init` records the repository commit (when `.git` is present) and a digest of the `orbital` source it tests. Every report shows both. The R1 code that was verified locally (commit `eef7a7b` and later, with an unchanged `src/`) has this source digest:

```
1cc88d273dac7ad88774dc7d2227b6a33544a871550368b58747b809c488cba7
```

## 2. Setting up the ChatGPT sandbox

```bash
REPO=~/orbital-chatgpt                                   # the repository copy in this sandbox
r1-acceptance() { PYTHONPATH="$REPO/acceptance" python3 -m r1_acceptance "$@"; }
python3 --version                                        # 3.11 or newer
export ORBITAL_BRIDGE_KEY='<the same key as the Claude side>'
export ORBITAL_BRIDGE_URL='http://host.docker.internal:8765'   # optional: this is the default
r1-acceptance --help
```

- **The key** is read from the environment for each command and is never written anywhere. Every other `ORBITAL_BRIDGE_*` variable in your shell is ignored, so the procedure always runs with its own options; `init` records the names it ignored.
- **Runs** are kept in `~/orbital-acceptance/r1-acceptance/<run id>/`. Choose another place with `--results DIR` or `R1_ACCEPTANCE_RESULTS`.
- **Claude-side paths.** `init` assumes the server's workdir and log are `~/orbital-acceptance/workdir` and `~/orbital-acceptance/serve.log`, as in plans/R1.md section 14. If yours differ, pass `--claude-workdir PATH` and `--serve-log PATH` to `init`. D-5 checks that the same workdir path has no `orbital-acceptance.txt` in the ChatGPT sandbox.

The Claude sandbox needs the usual setup from plans/R1.md section 14: its own repository copy at the same commit, the `orbital-bridge` function, the same key, the published port, and the network policy.

## 3. Step by step

At every checkpoint the harness prints the same instructions as this table, filled in with your paths and task ids. `r1-acceptance status` repeats them at any time.

| # | Where | What you do | Then run (ChatGPT sandbox) |
|---|---|---|---|
| 1 | ChatGPT | Start a run; P-1 runs at once (no network traffic) | `r1-acceptance init` |
| 2 | Claude | Start the server from a plain shell: `mkdir -p ~/orbital-acceptance/workdir`, then `orbital-bridge serve --port 8765 --workdir ~/orbital-acceptance/workdir 2>&1 \| tee -a ~/orbital-acceptance/serve.log` | — |
| 3 | Host | Leave the network policy **closed** for D-1. To skip D-1, run `r1-acceptance record D-1 skip --note "<why>"` and continue with row 4. | `r1-acceptance run d1 --confirm policy-closed` |
| 4 | Host | Open the policy: `sbx policy allow network localhost:8765`, and approve with `sbx policy approval …` if a request is pending | — |
| 5 | — | — | `r1-acceptance run d2-d3` |
| 6 | Claude | **Before d4-d7 starts:** the D-3 checks: `pgrep -af -- '--output-format json --session[-]id' \|\| echo none`, and `grep 'authentication failed' ~/orbital-acceptance/serve.log \| tail -n 2`. Record both (section 4). | `r1-acceptance run d4-d7` (4 Claude runs, about 2 minutes) |
| 7 | Claude | **Right away:** the D-7 checks: the `pgrep` above, and `pgrep -af '^sleep 6[0]$' \|\| echo none`. Then the D-4 check (`grep '<D-4 task id>' …/serve.log`) and the D-5 check (`cat ~/orbital-acceptance/workdir/orbital-acceptance.txt`). Record them. | — |
| 8 | Claude | Stop the server (Ctrl-C) and restart it with an invalid model: `ORBITAL_BRIDGE_CLAUDE_ARGS='--permission-prompts none --model orbital-no-such-model' orbital-bridge serve …` (as in row 2) | `r1-acceptance run d8 --confirm invalid-model-server` |
| 9 | Claude | Stop the server and restart it normally (row 2). Read row 10 first. | `r1-acceptance run d9a --confirm normal-server` |
| 10 | Claude | **Within about 10 s:** stop the server (Ctrl-C), and do not restart it yet. Make the D-9 checks: the two `pgrep` checks, and `grep '<D-9 task id>' …/serve.log`, which must show `finished: failed (execution_cancelled)`. | `r1-acceptance run d9b --confirm server-stopped` |
| 11 | Claude | Restart the server normally (row 2) | `r1-acceptance run d9c --confirm server-restarted` |
| 12 | ChatGPT | Record any manual check still pending (`r1-acceptance status` lists them) | `r1-acceptance report` |

Each `--confirm` token is your statement that the checkpoint before the stage is done. A stage refuses to run without it, before the earlier stages are complete, without a usable key, or if the `orbital` source changed since `init`. In all these cases nothing is sent to the bridge.

Before each stage that contacts the server, a signed `ping` checks the server state the stage needs:

- Before d4-d7, d8, d9a and d9c, the server must answer. If it does not, nothing is submitted.
- Before d9b, it must **not** answer. A server that still answers would make D-9b meaningless.

## 4. Recording manual verification

```bash
r1-acceptance record D-7.claude-no-sleep pass --observed none
r1-acceptance record D-3.claude-serve-log pass --observed -      # paste the output, then Ctrl-D
r1-acceptance record D-5.claude-file pass --observed ORBITAL-R1 --attach copied-file.txt
r1-acceptance record D-9.claude-no-bridge-runs fail --observed '<output>' --note "<what you saw>"
r1-acceptance record D-1 skip --note "the policy was already open"   # skips a whole step
```

- **Verdicts.** `pass`, `fail` or `skip`. The verdict is yours; the harness only notes whether the pasted output matches the expectation, and warns when the two disagree.
- **Observations.** `--observed` keeps the output you saw; `-` reads it from standard input. `--attach` copies files into the run, for example a log you copied over. `--note` adds free text.
- **History.** A record belongs to the step's current attempt. Recording again adds a new record; the latest one counts, and earlier ones stay in the evidence.
- **Timing.** The report notes a D-3, D-7 or D-9 process check that was recorded after the stage that had to follow it had started. Make the observation at the time shown, even if you record it later.

Manual check ids: `D-3.claude-no-bridge-runs`, `D-3.claude-serve-log`, `D-4.claude-serve-log`, `D-5.claude-file`, `D-7.claude-no-bridge-runs`, `D-7.claude-no-sleep`, `D-9.claude-serve-log`, `D-9.claude-no-bridge-runs`, `D-9.claude-no-sleep`.

## 5. Resuming, retries and Claude usage

- **Running a stage again continues it.** A check with a definitive result is not repeated. A task that has not settled is polled again with `wait`, never submitted again. Side-effect-free checks that failed (D-1, D-2, D-3, the D-5 file check, D-9c) are repeated, so you can fix the cause and run the stage again.
- **Submissions record the task id at once.** Each submission is made with `--max-wait 0` and then observed with `wait`. That is the same exchange as a waiting `submit` (one POST, then polling GETs), but the task id is saved as soon as the server accepts the task, so Ctrl-C during a wait loses nothing.
- **An interrupted submission needs your decision.** If the harness is killed while a submission is in flight, the task may or may not have been accepted. The step becomes **needs-decision**, and the stage refuses to continue until you decide:
  - look at the Claude side (`grep accepted …/serve.log`);
  - then either `r1-acceptance run <stage> --resubmit D-x`, which is another real Claude run, or skip the step.
- **Failed task steps are never resubmitted automatically.** `--resubmit D-x` is the only way. Stage d4-d7 stops at its first failed step, so no further Claude runs are spent; running it again continues with the next step.
- **Claude usage.** The procedure starts six real Claude runs (D-4 … D-9); the API rejects D-8's at no cost. Only `--resubmit` starts more.
- **Locking.** Commands that write take a lock on the run, so two commands never work on the same run at once.

## 6. Evidence and reports

Each run lives in its own directory with a unique id, `r1-<UTC time>-<random>`:

| Path | Content |
|---|---|
| `run.json` | Settings, environment, the `orbital` source and its digest, and the harness version and digest (written once) |
| `events/NNNNNN-<kind>.json` | One immutable file per event: stage starts and ends, attempts, commands, evaluations, preflight pings, manual records, skips, reports. The run's state is derived from these alone. |
| `artifacts/` | The raw output of every command (stdout and stderr), and the raw HTTP response of D-3b |
| `attachments/` | Copies of files attached to manual records |
| `reports/<time>-<id>/` | `report.json` and `report.md`; each `report` command writes a new directory |

Every file is created exclusively, so no file is ever overwritten or deleted. `r1-acceptance init --new` starts a new run, and the old run stays as it is. `init` refuses while the latest run is unfinished, unless you pass `--new`.

**The report** (`report.json` for machines, `report.md` for people) covers every step and phase:

- the expected and observed status, error code and exit code, and the task id;
- every command, with its timestamps, exit code, raw JSON output and stderr;
- automated checks with diagnostics, and manual records with your observations;
- verdicts for the steps and for AC1 … AC7;
- an index of all evidence files with their SHA-256.

Verdicts:

| Verdict | Meaning |
|---|---|
| passed | Every automated check passed, and every manual check was recorded as passed |
| failed | An automated check failed, or a manual check was recorded as failed |
| pending-manual | Every automated check passed; an observation of the Claude sandbox is not recorded yet |
| skipped | You skipped the step; the reason is recorded |
| incomplete | No failure, but a check was skipped, so it is not fully verified |
| in-progress | Started but not settled; running its stage again continues it |
| needs-decision | Interrupted while submitting; resubmit it or skip it |
| pending | Not run yet |

Criteria follow plans/R1.md section 4. AC7 also rests on PKG-01, verified locally (plans/R1.md section 20); the optional D-1 never blocks AC4, but the report notes when it did not pass.

| Criterion | Steps |
|---|---|
| AC1 | D-2, D-4 |
| AC2 | D-4, D-5 |
| AC3 | D-4, D-6 |
| AC4 | D-1 (optional), D-6, D-7, D-8, D-9 |
| AC5 | D-3 |
| AC6 | D-2 … D-9 |
| AC7 | P-1 |

## 7. Commands and exit codes

| Command | Purpose |
|---|---|
| `init [--url URL] [--claude-workdir PATH] [--serve-log PATH] [--orbital-src DIR] [--new]` | Start a run; run P-1 |
| `run STAGE [--confirm TOKEN] [--resubmit STEP]` | Run a stage: `p1`, `d1`, `d2-d3`, `d4-d7`, `d8`, `d9a`, `d9b`, `d9c` |
| `record CHECK_OR_STEP pass\|fail\|skip [--observed TEXT\|-] [--attach FILE] [--note TEXT]` | Record a manual check, or skip a step |
| `status` | Step verdicts, pending manual checks and the next action (read-only) |
| `report` | Write `report.json` and `report.md` |

Every command takes `--results DIR`. Every command except `init` also takes `--run RUN_ID`; the default is the latest run.

| Exit code | Meaning |
|---|---|
| 0 | Done: every check that ran passed (manual checks may still be pending) |
| 1 | Something failed: see the output and the report |
| 2 | Refused, or a usage error: nothing was sent to the bridge |
| 3 | Incomplete: run the same command again to continue (nothing is resubmitted) |
| 130 | Interrupted (Ctrl-C): run the same command again to resume |

## 8. Troubleshooting

| Symptom | What to do |
|---|---|
| A preflight `ping` fails before a stage | Check that the server is running, that both sides use the same key, and that the policy allows `localhost:8765`, then run the stage again. Nothing was submitted. |
| D-1 fails with `ok true` | The policy was already open. Skip D-1 (`record D-1 skip --note …`); it is optional. |
| D-2 fails with `unverified_auth_rejection` | The two sides use different keys. Fix the key and run `r1-acceptance run d2-d3` again; only the failed checks repeat. |
| D-5 reports that the file is visible here | The sandboxes share a filesystem, or `--claude-workdir` names a path that exists in this sandbox. |
| D-8 fails with `succeeded` | The server was not restarted with the invalid model. Restart it that way, then run `r1-acceptance run d8 --confirm invalid-model-server --resubmit D-8`. |
| d9b refuses: "the bridge still answers" | Stop the server first; D-9b needs it stopped. |
| The D-9 `serve.log` check shows `finished: succeeded` | The server was stopped too late, so the task was not interrupted. Record the check as failed, then repeat D-9 with a new task: `r1-acceptance run d9a --confirm normal-server --resubmit D-9`, and continue with d9b and d9c as before. |
| A step shows **needs-decision** | See section 5. |
| "another r1-acceptance command is working on this run" | Wait for the other command to finish. |
| `status` warns about an unreadable event file | A command was killed while writing it. It is kept and treated as if that event never happened. |

## How the harness was verified

Before delivery, the harness ran in the development sandbox against simulated responses: a simulated Claude Code that answers the procedure's prompts the way the real CLI did, and a simulated sandbox proxy that blocks, forwards or fails like the real one. The simulated runs covered:

- the whole procedure;
- resuming after Ctrl-C;
- a submission killed in flight;
- wrong keys, an early-opened policy, a forgotten restart, a server that was not stopped, and a shared filesystem;
- refused preconditions, and evidence immutability.

No real Claude run and no Docker or `sbx` command was used.
