import hashlib
import json
import logging
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from thikana.api.main import create_app
from thikana.api.observability import JsonFormatter
from thikana.api.service import to_result, validate_text
from thikana.api.settings import DEFAULT_MODEL, Settings
from thikana.api.errors import ApiError
from thikana.schema import ENTITY_TYPES, Span
from thikana.training.synth import build_places, generate, split_places
from thikana.training.train import build_vocab, train_model

ROOT = Path(__file__).resolve().parents[1]
MARKER = "SECRET-ADDRESS-MARKER"   # stands in for a real address; must never leak
ADDRESS = "House 12, Road 5, Mirpur-10, Dhaka-1216"


@pytest.fixture(scope="module")
def model_path(tmp_path_factory):
    places = split_places(build_places())["train"]
    path = tmp_path_factory.mktemp("api-model") / "tiny.crfsuite"
    vocab = {"district": build_vocab(places)["district"]}
    train_model(generate(places, 400, seed=1), path, vocab, memory=True)
    return path


def make_client(settings, **kwargs):
    return TestClient(create_app(settings), **kwargs)


@pytest.fixture
def client(model_path):
    with make_client(Settings(model_path=model_path, max_text_chars=200, max_batch=3)) as c:
        yield c


@pytest.fixture
def no_model_client(tmp_path):
    with make_client(Settings(model_path=tmp_path / "missing.crfsuite")) as c:
        yield c


# ---- operations: liveness is not readiness -----------------------------------

def test_healthz_is_ok_even_without_a_model(no_model_client):
    assert no_model_client.get("/healthz").json() == {"status": "ok"}


def test_readyz_is_ready_with_a_model_and_503_without(client, no_model_client):
    ready = client.get("/readyz")
    assert ready.status_code == 200 and ready.json()["status"] == "ready"
    unready = no_model_client.get("/readyz")
    assert unready.status_code == 503 and unready.json()["reason"] == "model_not_loaded"


def test_a_corrupt_model_file_makes_the_service_unready_not_crashed(tmp_path):
    bad = tmp_path / "corrupt.crfsuite"
    bad.write_bytes(b"this is not a crfsuite model")
    with make_client(Settings(model_path=bad)) as c:
        assert c.get("/healthz").status_code == 200
        assert c.get("/readyz").status_code == 503


def test_a_missing_model_is_logged_with_its_type_and_serving_continues(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="thikana")
    with make_client(Settings(model_path=tmp_path / "gone.crfsuite")) as c:
        assert c.get("/healthz").status_code == 200
    failed = [r for r in caplog.records if r.getMessage() == "model_load_failed"]
    assert failed and failed[0].fields["error_type"] == "FileNotFoundError"


# ---- the product ---------------------------------------------------------------

def test_parse_returns_entities_whose_offsets_index_the_original_text(client):
    body = client.post("/api/v1/parse", json={"text": ADDRESS}).json()
    assert body["entities"]
    for e in body["entities"]:
        assert ADDRESS[e["start"]:e["end"]] == e["text"]
        assert e["label"] in ENTITY_TYPES
    assert len(body["model_version"]) == 12
    assert set(body["fields"]) == {e["label"].lower() for e in body["entities"]}


@pytest.mark.parametrize("name", ["কাউনিয়া",    # gazetteer form
                                  "কাউনিয়া"])  # NFC form
def test_offsets_stay_valid_for_bangla_in_both_keyboard_forms(client, name):
    text = f"বাসা ১২, {name}, Dhaka ১২১০"
    for e in client.post("/api/v1/parse", json={"text": text}).json()["entities"]:
        assert text[e["start"]:e["end"]] == e["text"]


def test_the_text_is_never_altered_before_parsing(client):
    text = "  House 5,\n\tRoad 3, Dhaka  "          # leading / trailing space, newline, tab
    for e in client.post("/api/v1/parse", json={"text": text}).json()["entities"]:
        assert text[e["start"]:e["end"]] == e["text"]


def test_postcodes_are_returned_with_ascii_digits_in_fields():
    # Bangla digits one, two, one, six: U+09E7 U+09E8 U+09E7 U+09EC  (U+09E6 is ZERO)
    text = "Dhaka ১২১৬"
    result = to_result(text, [Span(0, 5, "DISTRICT"), Span(6, 10, "POSTCODE")])
    assert result.fields == {"district": ["Dhaka"], "postcode": ["1216"]}
    assert result.entities[1].text == text[6:10]   # the entity keeps the ORIGINAL digits


def test_batch_returns_one_result_per_address(client):
    body = client.post("/api/v1/parse/batch", json={"texts": [ADDRESS, "Mazara, Dhaka"]}).json()
    assert len(body["results"]) == 2 and len(body["model_version"]) == 12


def test_model_endpoint_reports_a_verifiable_identity_and_honest_limits(client, model_path):
    info = client.get("/api/v1/model").json()
    digest = hashlib.sha256(model_path.read_bytes())
    digest.update(model_path.with_suffix(".json").read_bytes())
    assert info["version"] == digest.hexdigest()[:12]
    assert info["name"] == "tiny" and info["uses_district_memory"] is True
    assert info["labels"] == list(ENTITY_TYPES) and info["vocabulary"] == ["district"]
    limits = " ".join(info["limitations"]).lower()
    assert "synthetic" in limits and "never on real" in limits


def test_parse_is_503_with_the_error_envelope_when_no_model_is_loaded(no_model_client):
    response = no_model_client.post("/api/v1/parse", json={"text": ADDRESS})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "model_not_ready"


# ---- validation ----------------------------------------------------------------

@pytest.mark.parametrize("payload, code", [
    ({"text": ""}, "empty_text"),
    ({"text": "   \n\t "}, "empty_text"),
    ({"text": "x" * 201}, "text_too_long"),
    ({"text": "Dhaka\x00 1216"}, "invalid_characters"),
    ({"text": "Dhaka\x07"}, "invalid_characters"),
    ({}, "invalid_request"),
    ({"text": 12345}, "invalid_request"),
    ({"text": ADDRESS, "adress": "typo"}, "invalid_request"),
])
def test_bad_input_is_422_with_a_specific_code(client, payload, code):
    response = client.post("/api/v1/parse", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code


def test_batch_limits_and_a_bad_item_is_named_by_index(client):
    assert client.post("/api/v1/parse/batch", json={"texts": []}).json()["error"]["code"] == "batch_size"
    too_many = client.post("/api/v1/parse/batch", json={"texts": [ADDRESS] * 4})
    assert too_many.status_code == 422 and too_many.json()["error"]["code"] == "batch_size"
    bad = client.post("/api/v1/parse/batch", json={"texts": [ADDRESS, "  "]}).json()["error"]
    assert bad["code"] == "empty_text" and "texts[1]" in bad["message"]


def test_a_body_larger_than_the_limit_is_413(model_path):
    with make_client(Settings(model_path=model_path, max_body_bytes=1024)) as c:
        response = c.post("/api/v1/parse", content=b"x" * 5000,
                          headers={"content-type": "application/json"})
    assert response.status_code == 413 and response.json()["error"]["code"] == "body_too_large"


def test_unknown_routes_and_methods_use_the_same_envelope(client):
    assert client.get("/nope").json()["error"]["code"] == "not_found"
    assert client.get("/api/v1/parse").json()["error"]["code"] == "method_not_allowed"


# ---- privacy: an address is personal data --------------------------------------

def test_error_responses_never_echo_what_the_client_sent(client):
    attempts = [
        client.post("/api/v1/parse", json={"text": ADDRESS, "adress": MARKER}),   # extra field
        client.post("/api/v1/parse", json={"text": MARKER * 40}),                  # too long
        client.post("/api/v1/parse", json={"text": MARKER + "\x00"}),              # control char
        client.post("/api/v1/parse", json={"text": [MARKER]}),                     # wrong type
        client.post("/api/v1/parse/batch", json={"texts": [ADDRESS, MARKER + "\x00"]}),
    ]
    for response in attempts:
        assert response.status_code == 422
        assert MARKER not in response.text


def test_logs_never_contain_the_address(client, caplog):
    caplog.set_level(logging.DEBUG, logger="thikana")
    client.post("/api/v1/parse", json={"text": f"{MARKER}, Dhaka"})
    client.post("/api/v1/parse", json={"text": MARKER * 40})                 # rejected
    client.post("/api/v1/parse/batch", json={"texts": [MARKER, MARKER]})
    emitted = [JsonFormatter().format(r) for r in caplog.records if r.name == "thikana"]
    assert any('"event": "request"' in line for line in emitted)             # we DID log
    assert not [line for line in emitted if MARKER in line]


def test_the_access_log_carries_counts_and_latency_not_content(client, caplog):
    caplog.set_level(logging.INFO, logger="thikana")
    text = f"{MARKER} House 5, Dhaka"
    client.post("/api/v1/parse", json={"text": text}, headers={"x-request-id": "trace-77"})
    line = [r for r in caplog.records if r.getMessage() == "request" and r.fields["route"] == "/api/v1/parse"][-1]
    assert line.fields["request_id"] == "trace-77" and line.fields["status"] == 200
    assert line.fields["text_chars"] == len(text) and line.fields["addresses"] == 1
    assert isinstance(line.fields["entities"], int) and line.fields["duration_ms"] >= 0


def test_an_unexpected_error_leaks_neither_to_the_client_nor_the_log(model_path, caplog):
    caplog.set_level(logging.DEBUG, logger="thikana")
    app = create_app(Settings(model_path=model_path))
    with TestClient(app, raise_server_exceptions=False) as c:
        def boom(text):
            raise RuntimeError(f"failed on {text}")   # an exception MESSAGE containing the address
        app.state.service.parse = boom
        response = c.post("/api/v1/parse", json={"text": f"{MARKER}, Dhaka"})
    assert response.status_code == 500 and response.json()["error"]["code"] == "internal_error"
    assert MARKER not in response.text
    emitted = [JsonFormatter().format(r) for r in caplog.records if r.name == "thikana"]
    assert any("unhandled_error" in line for line in emitted)
    assert not [line for line in emitted if MARKER in line]


def test_api_responses_are_not_cacheable_but_ops_endpoints_are_unaffected(client):
    assert client.post("/api/v1/parse", json={"text": ADDRESS}).headers["cache-control"] == "no-store"
    assert "cache-control" not in client.get("/healthz").headers


# ---- request ids -----------------------------------------------------------------

def test_request_ids_are_echoed_when_valid_and_replaced_when_not(client):
    assert client.get("/healthz", headers={"x-request-id": "abc-123"}).headers["x-request-id"] == "abc-123"
    generated = client.get("/healthz").headers["x-request-id"]
    assert len(generated) == 32
    hostile = client.get("/healthz", headers={"x-request-id": "bad id;{evil}"}).headers["x-request-id"]
    assert hostile != "bad id;{evil}" and len(hostile) == 32


# ---- metrics -------------------------------------------------------------------------

def test_metrics_count_requests_entities_and_model_state(client):
    client.post("/api/v1/parse", json={"text": ADDRESS})
    text = client.get("/metrics").text
    assert 'thikana_http_requests_total{method="POST",route="/api/v1/parse",status="200"} 1.0' in text
    assert "thikana_addresses_parsed_total 1.0" in text
    assert "thikana_model_ready 1.0" in text
    for label in ENTITY_TYPES:                       # every label series exists, even at 0
        assert f'thikana_entities_total{{label="{label}"}}' in text
    assert "thikana_text_chars_count 1.0" in text and "thikana_model_info{" in text


def test_metric_labels_stay_bounded_for_junk_paths(client):
    for i in range(5):
        client.get(f"/api/v1/random-{i}")
    series = [l for l in client.get("/metrics").text.splitlines()
              if l.startswith("thikana_http_requests_total{") and "random" in l]
    assert not series
    assert 'route="unmatched"' in client.get("/metrics").text


def test_no_model_shows_up_in_the_readiness_gauge(no_model_client):
    assert "thikana_model_ready 0.0" in no_model_client.get("/metrics").text


# ---- concurrency ---------------------------------------------------------------------

def test_concurrent_requests_all_get_the_same_answer(client):
    def call(_):
        return client.post("/api/v1/parse", json={"text": ADDRESS}).json()["entities"]

    with ThreadPoolExecutor(max_workers=16) as pool:
        answers = list(pool.map(call, range(64)))
    assert all(a == answers[0] for a in answers)


# ---- configuration -------------------------------------------------------------------

def test_cors_is_off_by_default_and_on_only_for_listed_origins(model_path):
    probe = {"Origin": "https://example.org", "Access-Control-Request-Method": "POST"}
    with make_client(Settings(model_path=model_path)) as off:
        assert "access-control-allow-origin" not in off.options("/api/v1/parse", headers=probe).headers
    with make_client(Settings(model_path=model_path, cors_origins=("https://example.org",))) as on:
        assert on.options("/api/v1/parse", headers=probe).headers["access-control-allow-origin"] \
            == "https://example.org"


def test_settings_default_to_safe_values():
    s = Settings.from_env({})
    assert s.max_text_chars == 500 and s.max_batch == 100 and s.cors_origins == ()
    assert s.model_path.name == f"{DEFAULT_MODEL}.crfsuite" and s.git_sha == "unknown"


def test_settings_read_the_environment():
    s = Settings.from_env({"THIKANA_MODEL_PATH": "/models/m.crfsuite", "THIKANA_MAX_TEXT_CHARS": "300",
                           "THIKANA_CORS_ORIGINS": "https://a.org, https://b.org",
                           "THIKANA_LOG_LEVEL": "warning", "THIKANA_GIT_SHA": "abc1234"})
    assert s.model_path == Path("/models/m.crfsuite") and s.max_text_chars == 300
    assert s.cors_origins == ("https://a.org", "https://b.org")
    assert s.log_level == "WARNING" and s.git_sha == "abc1234"


@pytest.mark.parametrize("env", [{"THIKANA_MAX_TEXT_CHARS": "lots"}, {"THIKANA_MAX_TEXT_CHARS": "0"},
                                 {"THIKANA_MAX_BODY_BYTES": "10"}, {"THIKANA_LOG_LEVEL": "LOUD"}])
def test_bad_configuration_fails_at_startup_with_a_clear_message(env):
    with pytest.raises(ValueError, match="THIKANA_"):
        Settings.from_env(env)


def test_the_serving_default_model_matches_the_production_model():
    from thikana.training.train_all import PRODUCTION_MODEL

    assert DEFAULT_MODEL == PRODUCTION_MODEL


def test_validate_text_accepts_normal_multiline_text():
    validate_text("House 5,\nRoad 3,\tDhaka", 100)
    with pytest.raises(ApiError):
        validate_text("", 100)


# ---- the image will not contain pandas -------------------------------------------

def test_serving_never_imports_the_training_stack():
    code = ("import sys, thikana.api.main; "
            "print([m for m in ('pandas', 'numpy', 'thikana.training') if m in sys.modules])")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]"


def test_json_responses_declare_utf8_for_clients_that_default_to_latin1(client, no_model_client):
    # Windows PowerShell 5.1's Invoke-RestMethod decodes application/json WITHOUT a
    # charset as ISO-8859-1, turning Bangla into mojibake (found against the live server)
    expected = "application/json; charset=utf-8"
    responses = [
        client.post("/api/v1/parse", json={"text": ADDRESS}),
        client.post("/api/v1/parse", json={"text": ""}),            # our 422 handler
        client.post("/api/v1/parse", json={"nope": 1}),             # the validation handler
        client.get("/api/v1/model"), client.get("/readyz"), client.get("/healthz"),
        client.get("/no-such-route"),                               # the 404 handler
        no_model_client.get("/readyz"),                             # the 503 built by hand
    ]
    assert [r.headers["content-type"] for r in responses] == [expected] * len(responses)
