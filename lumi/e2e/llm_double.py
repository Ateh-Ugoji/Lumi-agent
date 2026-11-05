"""An OpenAI-compatible HTTP server that plays the language model. It spends nothing.

The agent talks to it through the real ``openai`` client over a real socket, so the chain, the
agent loop, the tool registry and ``ToolExecution.as_dict`` all run unchanged. Only the model's
choices are scripted:

* a chat turn (the request carries ``tools``) whose last user message mentions connecting an
  account answers with a ``connect_account`` tool call, then, once the tool result is back, with
  a sentence that links to the ``connect_url`` the real tool returned;
* any other chat turn answers with a plain sentence;
* a request without tools (title, memory extraction) gets an empty JSON object.

``GET /_calls`` lists what the model received, so a test can see the tool schema and results.
"""

from __future__ import annotations

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

CALLS: list[dict[str, Any]] = []
_LOCK = threading.Lock()
CONNECT = re.compile(r"conect|connect", re.IGNORECASE)


def _completion(message: dict[str, Any], finish: str) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-sim-{len(CALLS)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "sim-model",
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def _text(content: str) -> dict[str, Any]:
    return _completion({"role": "assistant", "content": content}, "stop")


def _last(messages: list[dict[str, Any]], role: str) -> str:
    for message in reversed(messages):
        if message.get("role") == role:
            content = message.get("content")
            return content if isinstance(content, str) else json.dumps(content)
    return ""


def answer(payload: dict[str, Any]) -> dict[str, Any]:
    messages = payload.get("messages") or []
    if not payload.get("tools"):
        return _text("{}")
    if messages and messages[-1].get("role") == "tool":
        result = json.loads(messages[-1].get("content") or "{}")
        if result.get("connect_url"):
            return _text(
                f"[Connect {result.get('platform', 'account')}]({result['connect_url']})"
            )
        if result.get("already_connected"):
            return _text("Esa cuenta ya está conectada.")
        return _text(
            f"No pude conectar la cuenta: {result.get('error', 'sin detalle')}"
        )
    user = _last(messages, "user")
    if CONNECT.search(user):
        call = {
            "id": "call_sim_connect",
            "type": "function",
            "function": {
                "name": "connect_account",
                "arguments": json.dumps(
                    {
                        "platform": "facebook",
                        "reason": "The user asked to connect their Facebook account",
                    }
                ),
            },
        }
        return _completion(
            {"role": "assistant", "content": None, "tool_calls": [call]}, "tool_calls"
        )
    return _text(f"Respuesta del modelo simulado a: {user[-200:]}")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        return None

    def _send(self, body: Any, status: int = 200) -> None:
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        if self.path == "/_calls":
            with _LOCK:
                self._send(CALLS)
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}")
        if not self.path.endswith("/chat/completions"):
            self._send({"error": "not found"}, 404)
            return
        reply = answer(payload)
        with _LOCK:
            CALLS.append(
                {
                    "tools": [
                        t["function"]["name"] for t in payload.get("tools") or []
                    ],
                    "last_role": (payload.get("messages") or [{}])[-1].get("role"),
                    "reply": reply["choices"][0]["finish_reason"],
                }
            )
        self._send(reply)


def start(port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
