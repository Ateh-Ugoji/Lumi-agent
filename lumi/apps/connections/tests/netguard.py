"""Keep the connections tests off the network.

No test here may reach a provider, so a Python socket may only go to loopback (the local
uvicorn in ``mcp/test_transport.py``) or to a unix socket. The database does not matter here:
libpq opens its own connections and never passes through Python's ``socket`` module.

An attempt raises ``NetworkBlocked`` and is also recorded. Code that swallows provider errors
(a best-effort revoke, say) would hide the raise, so the autouse fixture fails the test at
teardown if anything was recorded.
"""

from __future__ import annotations

import ipaddress
import socket
import traceback
from collections.abc import Iterator
from typing import Any

import pytest

LOOPBACK_NAMES = frozenset({"localhost", "localhost.localdomain"})
# A tracing exporter that an earlier test (the legacy ``tests/``) started keeps a thread alive and
# retries its endpoint at any time. It is blocked like any other attempt, but it is not this test's.
# OpenTelemetry wraps every new thread once tracing is on, so its wrapper frame sits at the
# bottom of *every* thread's stack. It says nothing about who started the thread.
THREAD_WRAPPERS = "/opentelemetry/instrumentation/"
BACKGROUND_EXPORTERS = ("/opentelemetry/", "/neatlogs/")


class NetworkBlocked(OSError):
    """A test tried to open a network connection that is not loopback."""


def is_loopback(host: Any) -> bool:
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if not isinstance(host, str):
        return False
    if host in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


def _target(address: Any) -> Any:
    return address[0] if isinstance(address, tuple) and address else address


def _from_a_background_exporter() -> bool:
    for frame in traceback.extract_stack():
        filename = frame.filename.replace("\\", "/")
        if THREAD_WRAPPERS in filename:
            continue
        if any(marker in filename for marker in BACKGROUND_EXPORTERS):
            return True
    return False


class Guard:
    def __init__(self) -> None:
        self.attempts: list[str] = []

    def check(self, host: Any, port: Any = None) -> None:
        if is_loopback(host):
            return
        if not _from_a_background_exporter():
            self.attempts.append(f"{host}:{port}")
        raise NetworkBlocked(
            f"test tried to reach {host}:{port}; only loopback is allowed"
        )

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        guard = self
        real_connect = socket.socket.connect
        real_connect_ex = socket.socket.connect_ex
        real_getaddrinfo = socket.getaddrinfo

        def connect(sock, address):
            if sock.family != getattr(socket, "AF_UNIX", None):
                guard.check(
                    _target(address), address[1] if isinstance(address, tuple) else None
                )
            return real_connect(sock, address)

        def connect_ex(sock, address):
            if sock.family != getattr(socket, "AF_UNIX", None):
                guard.check(
                    _target(address), address[1] if isinstance(address, tuple) else None
                )
            return real_connect_ex(sock, address)

        def getaddrinfo(host, port, *args, **kwargs):
            if host is not None:
                guard.check(host, port)
            return real_getaddrinfo(host, port, *args, **kwargs)

        monkeypatch.setattr(socket.socket, "connect", connect)
        monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
        monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


@pytest.fixture(autouse=True)
def net_attempts(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    guard = Guard()
    guard.install(monkeypatch)
    yield guard.attempts
    if guard.attempts:
        pytest.fail(
            f"the test tried to reach the network: {', '.join(guard.attempts)}",
            pytrace=False,
        )
