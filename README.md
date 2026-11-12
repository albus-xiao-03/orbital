# ORBITAL

ORBITAL bridges AI agents. Requirement R1 delivers `orbital.bridges`: a ChatGPT agent running in one Docker Sandbox can delegate a task to Claude Code running in another Docker Sandbox and get Claude's answer back. The two sides communicate only over the network.

- **Claude side.** `orbital-bridge serve` runs a small HTTP server. It authenticates every request, hands the prompt to `claude -p`, and keeps the result under the task id. Claude Code does the work; the bridge only carries the prompt and the result.
- **ChatGPT side.** `orbital-bridge submit` (or the `BridgeClient` Python API) creates a task id, sends the prompt, waits, and prints one JSON result.
- **Every result** carries the task id and one status:

  | Status | Meaning |
  |---|---|
  | `succeeded` | Claude Code reported success |
  | `failed` | the task reached Claude but did not succeed |
  | `timed_out` | the Claude side confirmed the execution deadline was hit |
  | `communication_error` | the outcome is unknown |
  | `rejected` | the task was never executed |
  | `running` | not finished yet |
- **Requests and responses are signed** with HMAC-SHA256 under a key that both sides share. A response whose signature does not verify is never trusted.

## Requirements

- Python 3.11 or later on both sides. The package uses only the standard library.
- **Claude side:**
  - Claude Code, authenticated and allowed to run tools unattended (Docker Sandboxes allow this by default with `bypassPermissions`);
  - Linux, because process supervision reads `/proc`;
  - the bridge was verified against Claude Code 2.1.322.
- **ChatGPT side:** nothing beyond Python. No OpenAI login is needed to use the bridge.

## Install

```bash
python3 -m pip install .              # from a copy of this repository
# or, without installing:
PYTHONPATH=src python3 -m orbital.bridges --help
```

## Quick start

1. **Generate a shared key once.** Give it to both sides through the `ORBITAL_BRIDGE_KEY` environment variable only:

   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

2. **Claude side.** Start the server:

   ```bash
   export ORBITAL_BRIDGE_KEY='<key>'
   orbital-bridge serve --port 8765 --workdir ~/project
   ```

   Stop it with Ctrl-C. This is a graceful stop: a running task is terminated and reaped.

3. **ChatGPT side.** Point the client at the server, then use it:

   ```bash
   export ORBITAL_BRIDGE_KEY='<key>'
   export ORBITAL_BRIDGE_URL='http://host.docker.internal:8765'
   orbital-bridge ping                                  # {"ok": true, "error": null}
   orbital-bridge submit 'Reply with exactly: ORBITAL-OK'
   orbital-bridge submit --prompt-file task.md --max-wait 600
   orbital-bridge wait <task_id> --max-wait 600         # continue waiting for a long task
   ```

When the server runs in a Docker Sandbox, you publish its port and allow it in the network policy from the host. `orbital` never does that itself. See [docs/bridges.md](docs/bridges.md#deployment-across-two-docker-sandboxes).

From Python:

```python
from orbital.bridges import BridgeClient, ClientConfig, TaskStatus

result = BridgeClient(ClientConfig.from_env()).run("Summarise README.md in one sentence.")
if result.status is TaskStatus.SUCCEEDED:
    print(result.response)
else:
    print(result.status, result.error)
```

## Results and exit codes

Each ChatGPT-side command prints one JSON object on stdout:

```json
{"task_id": "0b6c1c2e-6f5d-4c9a-9a51-3f2f6d0c8e11", "status": "succeeded", "response": "ORBITAL-OK", "error": null}
```

- `succeeded` is **Claude Code's own report** that it finished. The bridge does not check whether the task was really accomplished, so read the response.
- `timed_out` is reported only after the Claude side has terminated the run and confirmed that it exited.
- A command that stops waiting reports `running`, with error code `wait_deadline_reached`. That never means the task ended.

| Exit code | Status |
|---|---|
| 0 | `succeeded` (also: `ping` ok, `serve` stopped cleanly) |
| 1 | `failed` |
| 2 | usage or configuration error; no request was sent |
| 3 | `timed_out` |
| 4 | `communication_error` |
| 5 | `rejected` |
| 6 | `running` |

## Documentation

- [docs/bridges.md](docs/bridges.md) covers:
  - the architecture;
  - status semantics and error codes;
  - the wire protocol and the security model;
  - restart semantics;
  - the configuration and CLI reference;
  - deployment across two sandboxes;
  - troubleshooting.
- [specs/R1.md](specs/R1.md) is the requirement, and [plans/R1.md](plans/R1.md) is the implementation plan. The plan includes the dual-sandbox acceptance procedure.

## License

MIT; see [LICENSE](LICENSE).
