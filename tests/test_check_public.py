"""scripts/check_public.py is how a deployment is audited from outside, so it is itself tested:
it must pass a correctly configured public service and FAIL each way a deployment can be wrong."""

import importlib.util
import socket
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from thikana.api.main import create_app
from thikana.api.settings import Settings
from thikana.training.synth import build_places, generate, split_places
from thikana.training.train import build_vocab, train_model

SPEC = importlib.util.spec_from_file_location("check_public", Path(__file__).resolve().parents[1] / "scripts" / "check_public.py")
check_public = importlib.util.module_from_spec(SPEC)
sys.modules["check_public"] = check_public        # @dataclass resolves its annotations through sys.modules
SPEC.loader.exec_module(check_public)


@pytest.fixture(scope="module")
def model_path(tmp_path_factory):
    places = split_places(build_places())["train"]
    path = tmp_path_factory.mktemp("check-model") / "tiny.crfsuite"
    train_model(generate(places, 400, seed=1), path, {"district": build_vocab(places)["district"]}, memory=True)
    return path


class Live:
    """A real uvicorn server on a free port: the script must work over real HTTP, not in process."""

    def __init__(self, settings):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        sock.close()
        # proxy_headers=False mirrors the Dockerfile's --no-proxy-headers. With uvicorn's default (on),
        # it trusts X-Forwarded-For from 127.0.0.1 and rewrites the client address, which let a forged
        # header defeat the limiter: this audit script is what found that.
        self.server = uvicorn.Server(uvicorn.Config(create_app(settings), host="127.0.0.1", port=self.port,
                                                    log_level="critical", access_log=False, proxy_headers=False))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                return f"http://127.0.0.1:{self.port}"
            time.sleep(0.1)
        raise RuntimeError("server did not start")

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(10)


def failed(results):
    return {name for name, ok, _ in results if not ok}


def test_a_correctly_configured_public_service_passes_every_check(model_path):
    settings = Settings(model_path=model_path, public_mode=True, rate_limit_per_minute=1, rate_limit_burst=5)
    with Live(settings) as url:
        results = check_public.checks(url)
        assert failed(results) == set(), failed(results)
        assert len(results) >= 14
        probe = check_public.probe_rate_limit(url, 60)
        assert failed(probe) == set(), probe


def test_a_service_left_in_cluster_mode_fails_the_exposure_checks(model_path):
    with Live(Settings(model_path=model_path)) as url:
        bad = failed(check_public.checks(url))
    assert {"/metrics is NOT reachable", "/docs is NOT reachable", "/openapi.json is NOT reachable",
            "no instance (pod/host) name is leaked"} <= bad


def test_a_missing_rate_limit_is_reported(model_path):
    with Live(Settings(model_path=model_path, public_mode=True)) as url:
        probe = check_public.probe_rate_limit(url, 30)
    assert failed(probe) == {"the rate limit engages (no forged header)"}


def test_a_limiter_that_trusts_a_forgeable_header_is_reported(model_path):
    # hops=1 with NO proxy in front: the "rightmost forwarded entry" is whatever the client wrote,
    # so rotating it buys a new allowance. This is exactly the misconfiguration to catch.
    settings = Settings(model_path=model_path, public_mode=True, rate_limit_per_minute=1,
                        rate_limit_burst=3, trusted_proxy_hops=1)
    with Live(settings) as url:
        probe = check_public.probe_rate_limit(url, 30)
    assert "forging X-Forwarded-For does NOT buy a new allowance" in failed(probe)


def test_the_exit_status_reflects_the_result(model_path, capsys):
    with Live(Settings(model_path=model_path, public_mode=True)) as url:
        assert check_public.main([url]) == 0
    with Live(Settings(model_path=model_path)) as url:
        assert check_public.main([url]) == 1
    assert "FAILED" in capsys.readouterr().out


def test_a_plain_http_public_url_is_warned_about_even_when_every_check_passes(monkeypatch, capsys):
    monkeypatch.setattr(check_public, "checks", lambda url: [("everything", True, "")])
    assert check_public.main(["http://service.example"]) == 0
    assert "not https" in capsys.readouterr().out
    assert check_public.main(["https://service.example"]) == 0
    assert "not https" not in capsys.readouterr().out
    assert check_public.main(["http://127.0.0.1:8000"]) == 0
    assert "not https" not in capsys.readouterr().out          # local testing over http is fine


def test_an_unreachable_server_is_an_error_not_a_pass():
    with pytest.raises(Exception):
        check_public.checks("http://127.0.0.1:9")
