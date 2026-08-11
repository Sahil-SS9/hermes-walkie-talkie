"""Deterministic local fake model endpoint (REM-502, F-05).

Test-only loopback HTTP server that emulates the OpenAI chat-completions
surface just enough for the real-Hermes-binary E2E:

- First three requests exercise Hermes' real deferred-tool protocol:
  ``tool_search`` -> ``tool_describe`` -> ``tool_call(peer_list_agents)``.
- The final request echoes the plugin tool result so the parent test can make
  an exact cross-process identity assertion.

The server requires NO credentials, binds 127.0.0.1 only, and is imported
exclusively by the test. Production packages never import or open it
(asserted in the E2E).
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class FakeModelHandler(BaseHTTPRequestHandler):
    """Serves /v1/chat/completions with a scripted tool-call sequence.

    The default script exercises the deferred-tool protocol for
    ``peer_list_agents`` (search -> describe -> call). A custom ``script``
    (list of ``(tool_name, arguments)`` tuples) can be supplied per-server
    for other tool flows (e.g. structured requests).
    """

    def __init__(self, *args: Any, script: list | None = None, **kwargs: Any) -> None:
        self._script = script
        super().__init__(*args, **kwargs)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - BaseHTTPRequestHandler signature
        return  # silence

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            self._json(400, {"error": {"message": "bad request"}})
            return
        messages = payload.get("messages", [])
        stream = bool(payload.get("stream", False))
        # Hermes exposes deferred plugin tools through three host-owned tools.
        # Script the exact search -> describe -> call sequence, then echo the
        # plugin result into the final response.
        tool_messages = [message for message in messages if message.get("role") == "tool"]
        script = self._script or [
            ("tool_search", {"query": "peer_list_agents", "limit": 5}),
            ("tool_describe", {"name": "peer_list_agents"}),
            ("tool_call", {"name": "peer_list_agents", "arguments": {}}),
        ]
        if len(tool_messages) >= len(script):
            tool_result = str(tool_messages[-1].get("content") or "")
            response = {
                "id": "chatcmpl-fake",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": f"Discovery complete. Tool result: {tool_result}",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }
        else:
            tool_name, arguments = script[len(tool_messages)]
            response = {
                "id": "chatcmpl-fake-tool",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": f"call_fake_{len(tool_messages) + 1}",
                                    "type": "function",
                                    "function": {
                                        "name": tool_name,
                                        "arguments": json.dumps(arguments),
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }

        if stream:
            self._sse_stream(response)
        else:
            self._json(200, response)

    def _sse_stream(self, obj: dict) -> None:
        """Emit an OpenAI-style SSE stream using delta chunks (the format the
        real client parses): one chunk carrying the message/delta, then
        [DONE]."""
        choice = obj["choices"][0]
        message = choice.get("message", {})
        delta = {}
        if message.get("content") is not None:
            delta["content"] = message.get("content")
        if message.get("tool_calls"):
            delta["tool_calls"] = message.get("tool_calls")
        chunk = {
            "id": obj.get("id", "chatcmpl-fake"),
            "object": "chat.completion.chunk",
            "choices": [{"index": 0, "delta": delta, "finish_reason": choice.get("finish_reason")}],
        }
        body = f"data: {json.dumps(chunk)}\n\n".encode() + b"data: [DONE]\n\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, obj: dict) -> None:
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class FakeModelServer:
    """Bounded loopback fake model server (test-only, no credentials)."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0, script: list | None = None) -> None:
        self._script = script
        self._httpd = ThreadingHTTPServer((host, port), self._handler_factory)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def _handler_factory(self, *args: Any, **kwargs: Any):
        return FakeModelHandler(*args, script=self._script, **kwargs)

    @property
    def base_url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}/v1"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)
