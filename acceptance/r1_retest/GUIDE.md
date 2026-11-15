# r1-retest: operator guide for the targeted R1 dual-sandbox re-test

`r1-retest` is the semi-automated harness for the re-test that `plans/R1-fix.md` (decision D3) asks for. It is committed in this repository under `acceptance/r1_retest/`, outside the `orbital` package, and runs only in your **ChatGPT-side sandbox**.

| Test | Plan step | Required | Real Claude runs |
|---|---|---|---|
| A-3 | D-2: signed ping (network path, mutual authentication) | yes | 0 |
| A-2 | D-7: confirmed execution timeout | yes | 1 |
| A-1 | D-9: interrupted communication, graceful shutdown (Ctrl-C), restart | yes | 1 |
| A-4 | D-9 with the server's terminal closed (SIGHUP) | no, optional | 1 |

- **Carried forward, not re-run:** the earlier evidence for P-1, D-1, D-3 … D-6 and D-8 comes from run `r1-20261115T030647Z-bc9829`.
- **Authoritative source:** commands and expected results come from `plans/R1.md`, revision 6.

**What it never does:**

- run Docker or `sbx`;
- touch network policy, ports or either sandbox;
- start or stop the bridge server;
- use an OpenAI account;
- contact the Claude sandbox other than through `orbital-bridge ping`, `submit` and `wait` over the authenticated bridge protocol;
- record the shared key.

Everything on the Claude side is yours to do. The harness tells you exactly what to do and when.

---

## 1. What you need

- **The fixed implementation in both sandboxes:** both repository copies at commit `135e0f2` or a later commit of the same branch. The commits after `135e0f2` add this harness and change nothing under `src/`, so the source digest decides, not the commit. The harness checks the ChatGPT-side copy: its `src/orbital` digest must be `2f98d10483d133a81d10b0c397a0810d920e23461a0bc48ef9af98703fa6b21c`. The Claude-side copy is checked with `orbital_source` (§3).
- **Python 3.11 or newer** in the ChatGPT sandbox. The harness uses only the standard library. Its only dependency is your `orbital` repository copy.
- **The same `ORBITAL_BRIDGE_KEY`** in both sandboxes, the port published, and the network policy open, as in your earlier run.
- **Terminals in the Claude sandbox:** one for the server, one for the checks, and optionally a third for `tail -f ~/orbital-acceptance/serve.log`.

## 2. Transfer and install (ChatGPT sandbox)

The sandboxes do not share a filesystem. Use either form; both run the same code.

**A. From the repository copy (recommended).** The ChatGPT sandbox needs a repository copy anyway, for `ORBITAL_SRC` (§3). At a commit that contains `acceptance/r1_retest/`, that copy carries the harness too. In the ChatGPT sandbox:

```bash
REPO='<path to the repository copy>'
r1-retest() { PYTHONPATH="$REPO/acceptance" python3 -m r1_retest "$@"; }
r1-retest --version                        # r1-retest 1.0.0
```

**B. One file.** In your repository on the host, or anywhere with the repository and Python 3.11 or newer:

```bash
python3 acceptance/build_r1_retest.py      # prints the archive's path and SHA-256
```

It writes three files to a new directory `acceptance/dist/<build id>/`, which git ignores:

- `r1-retest.pyz`: the whole harness, one file;
- `r1-retest.pyz.sha256`: its checksum;
- `GUIDE.md`: this guide.

Copy the three files into the ChatGPT sandbox, for example into the directory your sandbox mounts from the host, or with your usual host-level copy. Then, in the ChatGPT sandbox:

```bash
cd <the directory holding the three files>
sha256sum -c r1-retest.pyz.sha256          # must print: r1-retest.pyz: OK
RETEST="$PWD/r1-retest.pyz"
r1-retest() { python3 "$RETEST" "$@"; }
r1-retest --version                        # r1-retest 1.0.0
```

`init` records which form runs: the archive and its SHA-256, or the source directory and its digest. That digest equals the `source_digest` of an archive built from the same commit.

## 3. Prepare both sides

**ChatGPT sandbox:**

```bash
REPO='<path to the repository copy>'       # at 135e0f2 or later (§1)
export ORBITAL_SRC="$REPO/src"
export ORBITAL_BRIDGE_KEY='<the shared key>'
export ORBITAL_BRIDGE_URL='http://host.docker.internal:8765'
r1-retest init
```

`init` does the following:

- refuses if the source is not the fixed implementation, and then creates nothing;
- records the source digest and commit, and non-secret facts about the sandbox;
- imports the public API and runs `--help` from that source;
- creates a new, uniquely named run under `~/orbital-acceptance/r1-retest/` (`--results` or `R1_RETEST_RESULTS` to change it);
- fingerprints the earlier run read-only if it finds it at `~/orbital-acceptance/r1-acceptance/r1-20261115T030647Z-bc9829` (`--previous-run PATH` otherwise).

**Claude sandbox, server terminal.** Start the server with the corrected command of `plans/R1.md` §14 C. It redirects the log; do not use `tee`:

```bash
orbital-bridge serve --port 8765 --workdir ~/orbital-acceptance/workdir >> ~/orbital-acceptance/serve.log 2>&1
```

**Claude sandbox, second terminal.** Paste these helper functions once. `r1-retest claude-setup` prints the same block.

- `orbital_check` is the plan's timed process check, word for word.
- `orbital_evidence` collects the plan's serve.log and transcript checks.
- `orbital_source` prints the commit and source digest the server runs.

Each prints its own UTC time, so the harness can tell when an observation was made.

```bash
# Claude sandbox, second terminal: define these once (paste the whole block).
# orbital_check is plans/R1.md §16's timed process check, word for word.
orbital_check() {
  date -u +%FT%TZ; pgrep -af -- '--output-format json --session[-]id' || echo none; pgrep -af '^sleep 6[0]$' || echo none
}
# usage: orbital_evidence <test> <task_id>; serve.log lines and the transcript check of §16
orbital_evidence() {
  echo "ORBITAL-EVIDENCE $1 $2 utc=$(date -u +%FT%TZ) offset=$(date +%z)"
  grep -n -E "$2|orbital\.bridges\.cli: (listening|stopping|stopped)" ~/orbital-acceptance/serve.log | tail -n 60
  echo "ORBITAL-TRANSCRIPT"
  ls -l --time-style=full-iso ~/.claude/projects/*/"$2".jsonl 2>&1
  echo "ORBITAL-SLEPT"
  grep -c '"text":"SLEPT"' ~/.claude/projects/*/"$2".jsonl 2>&1
  echo "ORBITAL-END"
}
# usage: orbital_source <repository copy>; the commit and source digest the server runs
orbital_source() {
  echo "ORBITAL-SOURCE utc=$(date -u +%FT%TZ)"
  git -C "$1" rev-parse HEAD 2>&1
  python3 -c 'import hashlib, pathlib, sys
r = pathlib.Path(sys.argv[1]); d = hashlib.sha256()
for p in sorted(r.rglob("*.py")):
    if "__pycache__" in p.parts: continue
    d.update(p.relative_to(r).as_posix().encode() + b"\0"); d.update(hashlib.sha256(p.read_bytes()).hexdigest().encode() + b"\n")
print("digest", d.hexdigest())' "$1/src/orbital"
  echo "ORBITAL-END"
}
```

## 4. The sequence: A-3, A-2, A-1

"Record" always means: run `r1-retest record <check>` in the ChatGPT sandbox, paste the output you copied from the Claude sandbox, including its first (time) line, then press Ctrl-D on a new line. You can also save the output to a file and add `--file <path>`.

| # | Where | What you do |
|---|---|---|
| 1 | ChatGPT | `r1-retest run a3`: A-3 / D-2, a signed ping |
| 2 | Claude, 2nd terminal | Type `orbital_check`, **without** pressing Enter |
| 3 | ChatGPT | `r1-retest run a2 --ready`: A-2 / D-7. One Claude run (`sleep 60`, ended by the 10 s timeout); about 15 s. It prints the task id. |
| 4 | Claude, 2nd terminal | **Within 30 s of the result:** press Enter on `orbital_check`; copy the output |
| 5 | ChatGPT | `r1-retest record D-7.process-check`, then paste |
| 6 | Claude, 2nd terminal | `orbital_evidence D-7 <task_id from step 3>`; copy the output |
| 7 | ChatGPT | `r1-retest record D-7.claude-evidence`, then paste |
| 8 | ChatGPT | `r1-retest status`: read the A-1 checkpoint before going on |
| 9 | ChatGPT | `r1-retest run a1-submit --ready`: A-1 / D-9a. One Claude run (`sleep 60`); it returns at once and prints the task id |
| 10 | Claude, **server terminal** | **Within about 10 s:** press Ctrl-C. Do not restart yet. |
| 11 | Claude, 2nd terminal | **As soon as the server has exited, within 30 s:** `orbital_check`; copy the output. Optionally `tail -n 6 ~/orbital-acceptance/serve.log`. |
| 12 | ChatGPT | `r1-retest record D-9.process-check`, then paste |
| 13 | ChatGPT | `r1-retest run a1-down`: D-9b, polls while the server is stopped |
| 14 | Claude, server terminal | Restart the server with the same command as in §3 |
| 15 | ChatGPT | `r1-retest run a1-up`: D-9c, polls once after the restart |
| 16 | Claude, 2nd terminal | `orbital_evidence D-9 <task_id from step 9>`; copy the output |
| 17 | ChatGPT | `r1-retest record D-9.claude-evidence`, then paste. This holds the stop record, the restart record and the transcript check. |
| 18 | Both (recommended) | Claude: `orbital_source <repository copy>`. ChatGPT: `r1-retest record claude-source`, then paste. |
| 19 | Both (recommended) | Bring the whole `~/orbital-acceptance/serve.log` over via your host, then `r1-retest attach serve.log --file <path>` |
| 20 | ChatGPT | `r1-retest report` |

**Timing (QA-03).**

- What counts is when `orbital_check` *ran*, which is its first line, against the server's own record of the timeout or the stop, both by the Claude sandbox's clock. When you record it does not matter, so record calmly afterwards.
- A check made more than 30 s after the event is **inconclusive**, never passed, even when it shows `none`. It cannot tell a terminated run from one that ended by itself.
- If that happens, repeat the test: `r1-retest repeat A-2 --ready` or `r1-retest repeat A-1 --ready`, then its first stage again. Each repeat is one more Claude run.
- A check that shows a process still running after the event fails the test.

## 5. Optional A-4: closing the server's terminal (SIGHUP)

Run it before A-1 or after it, not during it. It costs one Claude run and does not affect the required verdict.

1. ChatGPT: `r1-retest run a4-submit --ready`.
2. Claude, **within about 10 s:** close the server's terminal (the window or the session) instead of pressing Ctrl-C.
3. Claude, 2nd terminal, within 30 s: `orbital_check`. ChatGPT: `r1-retest record A-4.process-check`.
4. ChatGPT: `r1-retest run a4-down`.
5. Claude: restart the server in a new terminal (§3). ChatGPT: `r1-retest run a4-up`.
6. Claude: `orbital_evidence A-4 <task_id>`. ChatGPT: `r1-retest record A-4.claude-evidence`.

## 6. Status, interruptions and repeats

- **Where you are:** `r1-retest status`, at any time, shows every verdict and the next step.
- **Ctrl-C during a stage:** the bridge command runs in its own session and keeps running, and the harness keeps waiting for it. A second Ctrl-C stops the waiting without killing the command. Run the same stage again to collect its result. Nothing is sent twice.
- **Submissions never repeat by themselves:** running `a2`, `a1-submit` or `a4-submit` again only collects or reports. A new task needs `r1-retest repeat <test> --ready`; earlier attempts stay in the evidence.
- **Lost task id:** if a submission's output was lost, which needs both the harness and the command to die, take the task id from serve.log's `accepted` line and run `r1-retest adopt <test> <task_id>`, or repeat the test.
- **An observation that could not be made:** `r1-retest record <check> --unavailable "reason"` records it as inconclusive.
- **Anything unusual:** `r1-retest note "…"`.

## 7. The report

`r1-retest report` writes a new `reports/<time>/report.md` and `report.json` in the run directory each time. Earlier reports are kept. Every result is one of:

| Verdict | Meaning |
|---|---|
| passed | the evidence shows the expected result |
| failed | the evidence shows a different result |
| pending | evidence still to be produced or recorded |
| inconclusive | evidence is present but cannot establish the result (late or untimed, or a procedure deviation); repeat or complete it |
| not-applicable | an optional test not run, or a check without a task |

The report contains:

- per test, the exact commands, expected and observed status, error code and exit code, task ids, raw stdout and stderr files with SHA-256, the parsed JSON, and each manual check with its observation time, its import time and its evidence file;
- the source identity on both sides;
- the AC1–AC7 summary, saying for each criterion what was newly verified and what is carried forward;
- an index of every evidence file.

It says that the evidence supports acceptance only when every required check passed. The decision stays yours.

## 8. Retrieve the evidence for QA

Copy the whole run directory out of the ChatGPT sandbox (via your host). Never edit files inside it:

```bash
cd ~/orbital-acceptance/r1-retest
tar czf "$HOME/<run id>.tar.gz" <run id>       # the run id is printed by init and status
```

It holds:

- `run.json`;
- `events/`: one file per step, append-only;
- `artifacts/`: raw stdout, stderr and exit status of every command;
- `manual/`: what you pasted, byte for byte;
- `attachments/`;
- `reports/`.

## 9. Commands and exit codes

| Command | Purpose |
|---|---|
| `init` | start a run (checks the source) |
| `run <stage> [--ready]` | stages: `a3`, `a2`, `a1-submit`, `a1-down`, `a1-up`; optional `a4-submit`, `a4-down`, `a4-up` |
| `record <check> [--file F] [--unavailable R]` | checks: `D-7.process-check`, `D-7.claude-evidence`, `D-9.process-check`, `D-9.claude-evidence`, `A-4.process-check`, `A-4.claude-evidence`, `claude-source` |
| `attach <label> [--file F]`, `note "<text>"` | extra evidence |
| `repeat <A-2\|A-1\|A-4> --ready`, `adopt <test> <task_id>` | your decisions |
| `status`, `report`, `claude-setup`, `guide` | information |

Exit codes:

| Code | Meaning |
|---|---|
| 0 | done, and passed |
| 1 | something failed |
| 2 | refused or a usage error; nothing was sent |
| 3 | incomplete: `--ready`, a decision or more evidence is needed |
| 130 | interrupted; run the same command again |

## 10. Troubleshooting

| Message | What to do |
|---|---|
| `not the fixed implementation` (init) | Update the repository copy to `135e0f2` or later (§1), then `export ORBITAL_SRC=…` |
| `ORBITAL_BRIDGE_KEY is not set` | Export the key in this shell |
| `the bridge does not answer a signed ping` | Start or restart the server; check the port and the policy |
| `the bridge still answers` (a1-down, a4-down) | Stop the server first (Ctrl-C, or close its terminal for A-4) |
| `this evidence is for task …` | Run `orbital_evidence` with the task id of the current attempt (`r1-retest status`) |
| shutdown record: `names no signal` | The Claude sandbox does not run the fixed code: update it, restart the server, repeat A-1 |
| shutdown record: `stopped with SIGTERM` | The stop was not Ctrl-C: repeat A-1 |
| process check `late` or `untimed` | Repeat the test, and run `orbital_check` within 30 s |
