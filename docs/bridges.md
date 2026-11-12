# `orbital.bridges` reference

`orbital.bridges` lets a ChatGPT agent delegate a task to Claude Code running in a separate Docker Sandbox, using only the network. This document describes the behaviour of requirement R1 as implemented and verified. The requirement is [specs/R1.md](../specs/R1.md), and the implementation plan, including the dual-sandbox acceptance procedure, is [plans/R1.md](../plans/R1.md).

## Contents

1. [Architecture](#architecture)
2. [Task status semantics](#task-status-semantics)
3. [Error codes](#error-codes)
4. [Wire protocol v1](#wire-protocol-v1)
5. [Security model](#security-model)
6. [Restart semantics](#restart-semantics)
7. [Configuration](#configuration)
8. [Command line](#command-line)
9. [Python API](#python-api)
10. [Deployment across two Docker Sandboxes](#deployment-across-two-docker-sandboxes)
11. [Usage notes for the ChatGPT side](#usage-notes-for-the-chatgpt-side)
12. [Troubleshooting](#troubleshooting)

## Architecture

```
ChatGPT sandbox
  ChatGPT agent (or a person) ── orbital-bridge submit / wait / ping ── BridgeClient
         │  HTTP/1.1 + JSON, HMAC-SHA256 signatures on requests and responses
         │  (leaves through the sandbox's HTTP proxy, which applies network policy)
         ▼
Docker host   http://host.docker.internal:8765 → published port → Claude sandbox :8765
         │
         ▼
Claude sandbox
  orbital-bridge serve ── BridgeServer (0.0.0.0:8765)
    ├─ authenticates each request and signs each response
    ├─ TaskSupervisor + TaskRegistry: at most one running task; results kept by task id
    └─ ClaudeCodeExecutor: claude -p --output-format json --session-id <task_id>, prompt on stdin
```

- The client generates the task id (a UUID version 4) before any network I/O. Every result, including a failure to reach the server, carries that id.
- `POST /v1/tasks` returns at once. The client then polls `GET /v1/tasks/<id>`, so a dropped connection loses nothing while the server keeps running.
- The server runs at most one task at a time. A second submission while one runs is `rejected` / `server_busy`.
- The bridge never interprets the prompt and never judges the response. Claude Code does the work.

## Task status semantics

| Status | Outcome settled? | Exact claim |
|---|---|---|
| `running` | no | At the server's last report the Claude Code process was executing. It may have finished since. |
| `succeeded` | yes | The Claude Code process exited with status 0 **and** reported success. `response` is its final result text, unchanged. |
| `failed` | yes | The process ended without reporting success, could not start, or the bridge failed while running it. It is no longer running. Partial work may exist. |
| `timed_out` | yes | The process was still running at its execution deadline. The server terminated it **and confirmed that it exited**. |
| `rejected` | yes | The request was refused before execution, either by a verified server response or by the client's local size check. |
| `communication_error` | **unknown** | No authoritative answer was obtained. The task may never have started, may be running, or may have finished. |

**`succeeded` is not verification of the objective.** It reports what Claude Code said about its own run. For example, when a tool call is denied for lack of permission, Claude Code still reports success and explains in its response that it could not do the task. Read the response to judge the outcome.

**Execution timeout versus wait budget.**

- The *execution timeout* (`--execution-timeout`, `execution_timeout_seconds`) is sent with the task. Only the server enforces it, and only the server reports `timed_out`, after the process has exited.
- The *wait budget* (`--max-wait`, `max_wait_seconds`) is how long one client call waits; it is never sent. When the budget runs out, the client returns the last snapshot: status `running`, error code `wait_deadline_reached`.
- If the most recent exchange failed when the budget ran out, the client returns that `communication_error` instead. Its message says when `running` was last confirmed.
- Stopping waiting never cancels the task.
- The default wait budget is the execution timeout plus 60 s. A wait budget of `0` means a single poll, which returns the plain snapshot.

**Success rule of the executor.** The result counts as success only if all of these hold:

- Claude Code exited with status 0;
- stdout holds exactly one JSON object with `type: "result"`, `is_error: false`, `subtype: "success"` and a string `result`;
- `terminal_reason` is `"completed"`, whenever that field is present.

Anything else is a failure. In particular, Claude Code reports an API error with `subtype: "success"` together with `is_error: true`, so `subtype` alone is never trusted. Only `result` is relayed; usage, cost and every other field are ignored.

## Error codes

Every code belongs to exactly one status.

| Code | Status | Meaning |
|---|---|---|
| `unauthorized` | `rejected` | A **verified** 401: authentication failed. The message gives the reason (for example `timestamp_out_of_window`). |
| `invalid_request` | `rejected` | Malformed or invalid request, unknown route (404) or wrong method (405) |
| `payload_too_large` | `rejected` | Request body over the limit (the server's 413, or the client's pre-check; the request was not sent) |
| `server_busy` | `rejected` | Another task is running; the message names it |
| `task_id_conflict` | `rejected` | This server instance has already used the task id |
| `connection_failed` | `communication_error` | Could not connect (refused, DNS failure, unreachable) |
| `connection_interrupted` | `communication_error` | The connection dropped mid-exchange |
| `request_timeout` | `communication_error` | No HTTP response within the per-request timeout |
| `gateway_error` | `communication_error` | Unverified 502, 503 or 504 from an intermediary |
| `network_policy_blocked` | `communication_error` | Unverified 403: the sandbox proxy appears to block the request |
| `unverified_auth_rejection` | `communication_error` | A 401 whose signature does not verify. The usual cause is a different key on each side. |
| `response_unverified` | `communication_error` | Any other response without a valid signature |
| `invalid_response` | `communication_error` | A verified response that is malformed or inconsistent |
| `unknown_task` | `communication_error` | This server instance has no record of the task (restart, retention limit, wrong server) |
| `server_error` | `communication_error` | An unexpected bridge-server error |
| `claude_error` | `failed` | Claude Code reported an error. The message has `terminal_reason`, `api_error_status`, `subtype` and an excerpt. |
| `executor_failed` | `failed` | Claude Code exited abnormally without a valid success result (for example, a reused session id) |
| `executor_unavailable` | `failed` | Claude Code could not be started |
| `invalid_executor_output` | `failed` | Claude Code's output could not be interpreted, or exceeded 32 MiB |
| `execution_cancelled` | `failed` | Stopped because the server shut down; the process has exited |
| `internal_error` | `failed` | An unexpected bridge error; any running process was terminated first |
| `execution_timeout` | `timed_out` | The deadline was reached; the process tree was terminated and the process has exited |
| `wait_deadline_reached` | `running` | The client stopped waiting; the task was not confirmed finished |

## Wire protocol v1

| Method and path | Purpose | Success | Errors |
|---|---|---|---|
| `POST /v1/tasks` | Submit a task | `202` new; `200` identical resubmission (within one server lifetime) | 400, 401, 409, 411, 413 |
| `GET /v1/tasks/<task_id>` | Current record of a task | `200` | 400, 401, 404 |
| `GET /v1/health` | Authenticated round trip | `200` | 401 |

**Bodies** are UTF-8, compact JSON objects:

| Message | Shape |
|---|---|
| Submit request | `{"task_id": "<uuid4>", "prompt": "<text>", "execution_timeout_seconds": 1800}` |
| Task record | `{"task_id": ..., "status": ..., "response": ... or null, "error": {"code": ..., "message": ...} or null}` (the same shape the CLI prints) |
| Error | `{"error": {"code": ..., "message": ...}, "task_id": ... or null}` |
| Health | `{"service": "orbital-bridge", "protocol_version": "1"}` |

Decoding is strict on both sides. A message is rejected if it is not a JSON object, has duplicate keys, contains `NaN` or infinities, has unknown or missing keys, or has a value of the wrong type.

**Headers.**

| Header | Value |
|---|---|
| `X-Orbital-Protocol` | `1` |
| `X-Orbital-Timestamp` | Unix seconds |
| `X-Orbital-Nonce` | 32 lowercase hex characters |
| `X-Orbital-Signature` | 64 lowercase hex characters |

`401` responses also carry `WWW-Authenticate: ORBITAL-HMAC-SHA256`. Every response carries `Connection: close` and `Cache-Control: no-store`. Chunked request bodies are not supported.

**Signatures** are `hex(HMAC-SHA256(key, canonical))`, where the canonical string joins these lines with `\n`:

```
request:  ORBITAL-HMAC-SHA256, 1, request,  METHOD, TARGET, TIMESTAMP, NONCE, sha256hex(body)
response: ORBITAL-HMAC-SHA256, 1, response, METHOD, TARGET, request NONCE, STATUS, sha256hex(body)
```

- `TARGET` is the origin-form path. The server normalises the absolute-form targets that proxies send.
- The server signs every response whose request carries a well-formed nonce, including 401, 411 and 413.

**Limits** (defaults):

| Limit | Value |
|---|---|
| Request body | 1 MiB |
| `execution_timeout_seconds` | 1 to 14,400 |
| Socket timeout per connection | 30 s |
| Claude stdout captured | 32 MiB |
| Claude stderr kept | last 64 KiB |
| Finished results kept | 100 |

## Security model

**Request checks.** The server checks each request in this order, and answers the first failure with a `401` carrying a coarse, non-secret reason:

1. All credential headers are present and well-formed (`missing_credentials`, `malformed_credentials`).
2. The protocol version is `1` (`unsupported_protocol`).
3. The timestamp is within ±300 s of the server clock (`timestamp_out_of_window`).
4. The signature matches, compared in constant time (`invalid_signature`).
5. The nonce has not been seen in the last 600 s (`replayed_nonce`). Nonces are recorded only after the signature verifies, and the cache holds at most 100,000 of them (`nonce_cache_full`).

Unauthenticated requests never reach the task supervisor or Claude Code.

**Trust rule on the client.** Only a response whose signature verifies under the client's own key is authoritative. The signature covers the request's method, target and nonce, the status and the body.

- `succeeded`, `failed`, `timed_out` and server-side `rejected` come only from verified responses.
- Every unverified response becomes `communication_error` (see the 401, 403, 5xx and other rows above). Its text is quoted as unverified, and a code it claims is never used.
- A wrong key therefore shows up as `unverified_auth_rejection`. With the same key but skewed clocks, the result is a verified `rejected` / `unauthorized` with reason `timestamp_out_of_window`.

**Credential isolation.**

- The key comes only from `ORBITAL_BRIDGE_KEY`. There is no command-line option for it, and it is never logged; `repr(SharedKey)` is redacted.
- Claude Code's environment excludes every `ORBITAL_BRIDGE_*` variable, so Claude never sees the key. It also excludes the 13 variables a Claude Code session exports to its children (`CLAUDECODE`, `CLAUDE_CODE_*` session markers, `CLAUDE_MODEL`, `CLAUDE_EFFORT`, ...), so a server started inside a Claude Code session still runs each task as an independent session. Every other variable, including other `CLAUDE_*` settings, passes through unchanged.
- Logs contain task ids, sizes, statuses and durations, never prompts, responses or the key.

**Process supervision.**

- Claude Code runs in its own session, and its descendants are tracked through `/proc`, because its tool processes run in sessions of their own.
- On the deadline or at shutdown, the executor:
  1. sends `SIGTERM` to the process group (Claude Code then terminates its tools and exits with status 143);
  2. after 5 s, sends `SIGKILL` to the group and to every tracked descendant that is still alive;
  3. reaps the process;
  4. re-checks the descendants.
- `timed_out` or `execution_cancelled` is recorded only after that sequence.

**Not protected against:**

- **Confidentiality.** Plain HTTP means content can be read on the host's network path.
- **The key holder.** Anyone with the key can delegate any task.
- **Floods of unauthenticated requests.** These are limited only by socket timeouts.

The Claude sandbox is the isolation boundary: tasks run with whatever permissions its Claude Code has.

## Restart semantics

Task records live in the memory of one server process. Idempotency, conflict detection, single execution and retention hold only within one server lifetime:

| After a restart | Behaviour |
|---|---|
| Resubmitting a pre-restart task id | The bridge accepts it as new. With the **same workdir**, Claude Code refuses the reused session id (`Session ID … is already in use`), so the result is `failed` / `executor_failed` and the task does not run twice. With a different workdir, it runs again. |
| Polling a pre-restart task id | `communication_error` / `unknown_task`. The message gives the new server's start time. |
| A graceful stop (Ctrl-C, `SIGTERM`) | The running task is terminated and reaped before the server exits; nothing is left running. |
| A crash or `SIGKILL` of the server | The running Claude Code process may continue as an orphan that the new server does not know about. Check for leftovers with `pgrep -af -- '--output-format json --session[-]id'`. |

Each task leaves a Claude Code session transcript under its task id in Claude Code's project store on the Claude side.

## Configuration

Command-line options override environment variables, which override the defaults. The key is read only from the environment.

**Server** (`orbital-bridge serve`, `ServerConfig.from_env`):

| Variable | Default | Meaning |
|---|---|---|
| `ORBITAL_BRIDGE_KEY` | required | Shared key (base64url, at least 32 bytes) |
| `ORBITAL_BRIDGE_HOST` | `0.0.0.0` | Bind address. It must listen on all interfaces to be publishable from a sandbox. |
| `ORBITAL_BRIDGE_PORT` | `8765` | Bind port |
| `ORBITAL_BRIDGE_WORKDIR` | current directory | Claude Code's working directory |
| `ORBITAL_BRIDGE_CLAUDE_BIN` | `claude` | Claude Code executable |
| `ORBITAL_BRIDGE_CLAUDE_ARGS` | `--permission-prompts none` | Extra Claude Code arguments in shell syntax; replaces the default. Flags that change the output contract (`-p`, `--print`, `--output-format`, `--input-format`, `--session-id`, `-r`, `--resume`, `-c`, `--continue`, `--verbose`) are refused. |
| `ORBITAL_BRIDGE_MAX_EXECUTION_TIMEOUT` | `14400` | Largest accepted execution timeout |
| `ORBITAL_BRIDGE_MAX_REQUEST_BYTES` | `1048576` | Request body limit |
| `ORBITAL_BRIDGE_RETAINED_TASKS` | `100` | Finished results kept |
| `ORBITAL_BRIDGE_CLOCK_SKEW` | `300` | Accepted timestamp skew, in seconds |

**Client** (`submit`, `wait`, `ping`, `ClientConfig.from_env`):

| Variable | Default | Meaning |
|---|---|---|
| `ORBITAL_BRIDGE_KEY` | required | The same key as the server's |
| `ORBITAL_BRIDGE_URL` | `http://host.docker.internal:8765` | `http://host[:port]`, with no path |
| `ORBITAL_BRIDGE_EXECUTION_TIMEOUT` | `1800` | Execution timeout sent with each task |
| `ORBITAL_BRIDGE_MAX_WAIT` | execution timeout + 60 | Wait budget (never sent) |
| `ORBITAL_BRIDGE_POLL_INTERVAL` | `2` | Seconds between polls |
| `ORBITAL_BRIDGE_REQUEST_TIMEOUT` | `30` | Timeout of each HTTP request |
| `ORBITAL_BRIDGE_MAX_RETRIES` | `5` | Consecutive transient failures retried, with backoff of 1, 2, 4, 8, 16 s (capped at 30 s) and never past the wait budget |
| `ORBITAL_BRIDGE_MAX_REQUEST_BYTES` | `1048576` | Local pre-check; keep it equal to the server's |

By default the client honours `HTTP_PROXY` and `NO_PROXY`, which a sandbox needs. `--no-proxy` connects directly. Redirects are never followed.

## Command line

`orbital-bridge` (the same as `python -m orbital.bridges`) prints results as one JSON object on stdout, and logs to stderr.

| Command | Purpose | Options |
|---|---|---|
| `serve` | Run the Claude-side server. It checks first that the workdir and Claude binary exist. | `--host`, `--port`, `--workdir`, `--claude-bin`, `--claude-arg ARG` (repeatable; replaces the default `--permission-prompts none`; write `--claude-arg=--flag` for values starting with `-`), `--max-execution-timeout`, `--log-level` |
| `submit` | Submit a prompt and wait within the budget | `PROMPT`, `-` (stdin) or `--prompt-file PATH`; `--execution-timeout`; `--max-wait` (`0` returns after submitting); `--url`; `--no-proxy` |
| `wait` | Retrieve a task, waiting up to `--max-wait` (`0` = one poll) | `TASK_ID`, `--max-wait`, `--url`, `--no-proxy` |
| `ping` | Signed round trip without running Claude; prints `{"ok": ..., "error": ...}` | `--url`, `--no-proxy` |

The exit code reports the printed status:

| Exit code | Meaning |
|---|---|
| 0 | `succeeded`, ping ok, or serve stopped |
| 1 | `failed` |
| 2 | usage or configuration error; no request was sent |
| 3 | `timed_out` |
| 4 | `communication_error` |
| 5 | `rejected` |
| 6 | `running` |

## Python API

```python
from orbital.bridges import BridgeClient, BridgeServer, ClientConfig, ServerConfig, TaskStatus

client = BridgeClient(ClientConfig.from_env())
client.submit(prompt, *, execution_timeout_seconds=None)                    # running, or a failure
client.wait(task_id, *, max_wait_seconds=None)                              # 0 = one poll
client.run(prompt, *, execution_timeout_seconds=None, max_wait_seconds=None)
client.ping()                                                               # None, or an ErrorDetail

server = BridgeServer(ServerConfig.from_env())   # binds immediately; server.port is known
server.serve_forever()                           # server.stop() from another thread: graceful
```

`None` selects the configured value. For `max_wait_seconds` that is `ClientConfig.max_wait_seconds` if it is set, and otherwise the execution timeout plus 60 s. These methods never raise for task or communication outcomes; every outcome is a `TaskResult`, or for `ping` an `ErrorDetail`. They raise `ValueError` only for invalid arguments, for example:

- a blank prompt, or one that is not valid Unicode;
- an execution timeout below 1 s;
- a malformed task id;
- a negative wait.

## Deployment across two Docker Sandboxes

`orbital` never creates, configures or inspects Docker Sandboxes. The host-level steps are yours to run; check the exact syntax with `sbx ports --help` and `sbx policy --help`.

1. **Create two sandboxes.**
   - The Claude sandbox needs Claude Code (authenticated) and Python 3.11 or later.
   - The ChatGPT sandbox needs Python 3.11 or later; no OpenAI login is required to drive it with the CLI.
   - Give each its own copy of this repository at the same commit, ideally from separate source directories.
2. **Publish the server port on the host loopback:**
   ```bash
   sbx ports '<claude sandbox>' --publish 127.0.0.1:8765:8765
   ```
3. **Allow the ChatGPT sandbox to reach it:**
   ```bash
   sbx policy allow network localhost:8765
   ```
   Approve any pending approval reported by `sbx policy approval ls`.
4. **In each sandbox**, use the repository copy without installing:
   ```bash
   orbital-bridge() { PYTHONPATH="<repository>/src" python3 -m orbital.bridges "$@"; }
   ```
   Set the same `ORBITAL_BRIDGE_KEY` in both sandboxes, and do not put it in a file on a shared mount.
5. **In the Claude sandbox**, from a plain shell:
   ```bash
   orbital-bridge serve --port 8765 --workdir <dir>
   ```
6. **In the ChatGPT sandbox:**
   ```bash
   export ORBITAL_BRIDGE_URL=http://host.docker.internal:8765
   orbital-bridge ping
   ```

The acceptance procedure for this setup (steps D-1 … D-9, with expected results) is in [plans/R1.md](../plans/R1.md), section 16.

## Usage notes for the ChatGPT side

These notes can be pasted into the instructions of an agent that drives the bridge:

```
Delegate a task to Claude:   orbital-bridge submit --prompt-file task.md
The command prints one JSON object; read "status" first.
- succeeded: Claude Code reported that it finished. "response" is its final message.
  Read it to judge whether the task was really accomplished; the bridge does not check.
- failed / timed_out / rejected: read error.code and error.message.
- communication_error: the outcome is unknown. The task may still be running.
- running: not finished yet (or this command stopped waiting).
  Continue with:  orbital-bridge wait <task_id> --max-wait 600
```

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `network_policy_blocked` (exit 4) | The sandbox proxy blocks the bridge address. Allow `localhost:8765` (or your host and port) in the network policy, and approve any pending approval. |
| `gateway_error` (exit 4) | The proxy could not reach the server: it is not running, or its port is not published. |
| `unverified_auth_rejection` (exit 4) | The two sides use different `ORBITAL_BRIDGE_KEY` values. |
| `rejected` / `unauthorized` with `timestamp_out_of_window` | The two clocks differ by more than `ORBITAL_BRIDGE_CLOCK_SKEW` seconds. |
| `rejected` / `server_busy` | Another task is running; the message names it. Wait for it, then submit again. |
| `communication_error` / `unknown_task` | The server restarted (its start time is in the message) or no longer retains the result. The outcome is unknown, so inspect the Claude side before re-running work with side effects. |
| `failed` / `executor_failed` with `Session ID … is already in use` | The task id was already executed in this workdir, for example before a server restart. Submit again; a new submission uses a new id. |
| `failed` / `claude_error` | Claude Code reported an error. The message gives `terminal_reason`, `api_error_status` and Claude's explanation, for example an unknown model. |
| `running` / `wait_deadline_reached` (exit 6) | The task has not finished. Continue with `orbital-bridge wait <task_id>`. |
| The server warns "started from inside a Claude Code session" | It still works, because the session's variables are removed from each task. Prefer starting it from a plain shell. |
