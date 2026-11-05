"""The guard that keeps these tests off the network."""

from __future__ import annotations

import socket

import httpx
import pytest

from .netguard import NetworkBlocked, is_loopback


@pytest.mark.parametrize("host", ["127.0.0.1", "127.9.9.9", "::1", "localhost"])
def test_loopback_hosts_are_allowed(host: str) -> None:
    assert is_loopback(host)


@pytest.mark.parametrize(
    "host",
    [
        "203.0.113.1",
        "10.0.0.5",
        "192.168.1.1",
        "api.x.com",
        "localhost.evil.com",
        "",
        None,
    ],
)
def test_everything_else_is_not_loopback(host) -> None:
    assert not is_loopback(host)


def test_a_connection_to_the_internet_is_refused_and_recorded(net_attempts) -> None:
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("203.0.113.1", 80), timeout=1)
    assert net_attempts == ["203.0.113.1:80"]
    net_attempts.clear()


def test_a_name_lookup_is_refused_and_recorded(net_attempts) -> None:
    with pytest.raises(NetworkBlocked):
        socket.getaddrinfo("graph.facebook.com", 443)
    assert net_attempts == ["graph.facebook.com:443"]
    net_attempts.clear()


def test_connect_ex_cannot_be_used_to_probe(net_attempts) -> None:
    with socket.socket() as probe, pytest.raises(NetworkBlocked):
        probe.connect_ex(("198.51.100.7", 443))
    net_attempts.clear()


def test_an_http_client_that_forgot_its_mock_transport_is_caught(net_attempts) -> None:
    with pytest.raises(httpx.ConnectError):
        httpx.get("https://api.example.com/v1/x", timeout=1)
    assert net_attempts and net_attempts[0].startswith("api.example.com")
    net_attempts.clear()


def test_loopback_and_unix_sockets_still_work() -> None:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        with socket.create_connection(server.getsockname(), timeout=1):
            pass
    pair = socket.socketpair()
    for end in pair:
        end.close()


pytest_plugins = ["pytester"]


def test_a_test_that_swallows_the_block_still_fails_at_teardown(pytester) -> None:
    """A best-effort provider call that catches the error must not hide a leak."""
    from pathlib import Path

    pytester.makepyfile(netguard=Path(__file__).with_name("netguard.py").read_text())
    pytester.makeconftest("from netguard import net_attempts  # noqa: F401\n")
    pytester.makepyfile(
        test_leaky="""
        import socket

        def test_swallows_the_error():
            try:
                socket.create_connection(("203.0.113.9", 443), timeout=1)
            except OSError:
                pass
        """
    )
    result = pytester.runpytest_subprocess("-p", "no:django", "-p", "no:cacheprovider")
    result.assert_outcomes(passed=1, errors=1)
    result.stdout.fnmatch_lines(["*tried to reach the network: 203.0.113.9:443*"])


def _run_in_exporter_module(tmp_path, package: str) -> tuple[list, list]:
    """Call ``socket.getaddrinfo`` from a thread whose stack passes through ``<package>/exporter.py``."""
    import importlib.util
    import threading

    module_dir = tmp_path / package
    module_dir.mkdir(parents=True)
    (module_dir / "exporter.py").write_text(
        "import socket\n"
        "def export(errors):\n"
        "    try:\n"
        "        socket.getaddrinfo('ingest.example.com', 443)\n"
        "    except OSError as error:\n"
        "        errors.append(type(error).__name__)\n"
    )
    spec = importlib.util.spec_from_file_location(
        f"{package.replace('/', '_')}_exporter", module_dir / "exporter.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    errors: list = []
    thread = threading.Thread(target=module.export, args=(errors,))
    thread.start()
    thread.join()
    return errors, []


@pytest.mark.parametrize("package", ["opentelemetry", "neatlogs"])
def test_a_tracing_exporter_thread_is_blocked_but_is_not_blamed_on_the_test(
    net_attempts, tmp_path, package
) -> None:
    errors, _ = _run_in_exporter_module(tmp_path, package)
    assert errors == ["NetworkBlocked"]  # it never reached the network
    assert net_attempts == []  # and the running test is not failed for it


def test_the_same_call_from_any_other_module_is_still_blamed(
    net_attempts, tmp_path
) -> None:
    errors, _ = _run_in_exporter_module(tmp_path, "somelib")
    assert errors == ["NetworkBlocked"]
    assert net_attempts == ["ingest.example.com:443"]
    net_attempts.clear()


def test_the_thread_wrapper_that_tracing_adds_does_not_excuse_a_test_thread(
    net_attempts, tmp_path
) -> None:
    errors, _ = _run_in_exporter_module(
        tmp_path, "opentelemetry/instrumentation/threading"
    )
    assert errors == ["NetworkBlocked"]
    assert net_attempts == ["ingest.example.com:443"]
    net_attempts.clear()
