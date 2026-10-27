"""scripts/loadtest.py produced two misleading results while the Kubernetes drills were run
(a 10 s IPv6 connect delay, and local port exhaustion that looked like service errors),
so it is tested against a tiny stand-in server rather than trusted."""

import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("loadtest", Path(__file__).resolve().parents[1] / "scripts" / "loadtest.py")
loadtest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(loadtest)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    fail = False

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        assert json.loads(body)["text"]
        status = 503 if Handler.fail else 200
        payload = b"{}"
        self.send_response(status)
        self.send_header("X-Thikana-Instance", "pod-a")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    Handler.fail = False
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd
    httpd.shutdown()


def run(monkeypatch, capsys, url, *extra):
    monkeypatch.setattr(sys, "argv", ["loadtest", url, "--seconds", "1", "--concurrency", "2", *extra])
    loadtest.main()
    return capsys.readouterr().out


def test_it_counts_responses_and_names_the_replica_that_answered(server, monkeypatch, capsys):
    out = run(monkeypatch, capsys, f"http://127.0.0.1:{server.server_port}")
    assert "{200:" in out and "pod-a" in out and "100.0%" in out
    assert "WARNING" not in out


def test_localhost_is_connected_to_as_ipv4_so_windows_does_not_wait_for_an_ipv6_timeout(server, monkeypatch, capsys):
    # The 10 s hang only happens when something silently drops IPv6 SYNs (Docker Desktop's
    # published ports did); a normal local server refuses instantly, so a timing test cannot
    # reproduce it (tried: it passed with the fix removed). Check the intent instead: which
    # host the tool actually connects to.
    seen = []
    real = loadtest.http.client.HTTPConnection

    class Spy(real):
        def __init__(self, host, *args, **kwargs):
            seen.append(host)
            super().__init__(host, *args, **kwargs)

    monkeypatch.setattr(loadtest.http.client, "HTTPConnection", Spy)
    out = run(monkeypatch, capsys, f"http://localhost:{server.server_port}", "--keepalive")
    assert "{200:" in out
    assert seen and set(seen) == {"127.0.0.1"}


def test_a_failing_service_shows_up_as_status_codes_not_as_a_crash(server, monkeypatch, capsys):
    Handler.fail = True
    out = run(monkeypatch, capsys, f"http://127.0.0.1:{server.server_port}")
    assert "{503:" in out and "throughput (200s only): 0.0" in out


def test_a_dead_server_is_counted_as_errors_and_does_not_hang(monkeypatch, capsys):
    out = run(monkeypatch, capsys, "http://127.0.0.1:9")   # nothing listens on the discard port
    assert "Error" in out and "{200:" not in out


def test_running_out_of_local_ports_is_called_out_as_a_load_generator_limit(monkeypatch, capsys):
    err = OSError(10048, "Only one usage of each socket address is normally permitted")

    class Boom:
        def __init__(self, *a, **k): pass
        def request(self, *a, **k): raise err
        def close(self): pass

    monkeypatch.setattr(loadtest.http.client, "HTTPConnection", Boom)
    out = run(monkeypatch, capsys, "http://127.0.0.1:9")
    assert "OSError[10048]" in out and "ran out of local ports" in out and "not a failure of the service" in out


def test_percentile_handles_small_and_empty_samples():
    assert loadtest.percentile([], 0.5) != loadtest.percentile([], 0.5)   # NaN
    assert loadtest.percentile([5.0], 0.99) == 5.0
    assert loadtest.percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 3.0
