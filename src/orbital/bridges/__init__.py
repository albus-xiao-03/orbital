"""Network bridge that lets a ChatGPT agent delegate tasks to Claude Code (requirement R1).

The Claude side runs a small authenticated HTTP server that hands each prompt to Claude Code;
the ChatGPT side submits prompts and retrieves structured results over HTTP.

ChatGPT side::

    from orbital.bridges import BridgeClient, ClientConfig, TaskStatus

    client = BridgeClient(ClientConfig.from_env())
    result = client.run("Reply with exactly: ORBITAL-OK")
    if result.status is TaskStatus.SUCCEEDED:
        print(result.response)  # Claude Code's own report; judge it yourself

Claude side::

    from orbital.bridges import BridgeServer, ServerConfig

    server = BridgeServer(ServerConfig.from_env())
    server.serve_forever()  # stop() from another thread ends it gracefully

The command line ``orbital-bridge`` (or ``python -m orbital.bridges``) offers ``serve``,
``submit``, ``wait`` and ``ping``.
"""

from orbital.bridges.auth.shared_key import SharedKey
from orbital.bridges.client.bridge_client import BridgeClient
from orbital.bridges.client.client_config import ClientConfig
from orbital.bridges.executor.claude_code_executor import ClaudeCodeExecutor
from orbital.bridges.models.error_code import ErrorCode
from orbital.bridges.models.error_detail import ErrorDetail
from orbital.bridges.models.task_request import TaskRequest
from orbital.bridges.models.task_result import TaskResult
from orbital.bridges.models.task_status import TaskStatus
from orbital.bridges.server.bridge_server import BridgeServer
from orbital.bridges.server.server_config import ServerConfig

__all__ = [
    "BridgeClient",
    "BridgeServer",
    "ClaudeCodeExecutor",
    "ClientConfig",
    "ErrorCode",
    "ErrorDetail",
    "ServerConfig",
    "SharedKey",
    "TaskRequest",
    "TaskResult",
    "TaskStatus",
]
