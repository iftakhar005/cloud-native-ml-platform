"""Everything that exists because the service may sit on the open internet: public mode, the
rate limiter, the security headers, and the web page that is served from the same process.

The cluster is a friendly place (a private network, Prometheus next door). The internet is
not, and a free host gives no firewall, so these properties live in the application and are
tested here rather than assumed.
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from thikana.api.main import WEB, create_app
from thikana.api.ratelimit import RateLimiter, client_key
from thikana.api.settings import Settings
from thikana.training.synth import build_places, generate, split_places
from thikana.training.train import build_vocab, train_model

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def model_path(tmp_path_factory):
    places = split_places(build_places())["train"]
    path = tmp_path_factory.mktemp("public-model") / "tiny.crfsuite"
    train_model(generate(places, 400, seed=1), path, {"district": build_vocab(places)["district"]}, memory=True)
    return path


def client_for(model_path, **settings):
    return TestClient(create_app(Settings(model_path=model_path, **settings)))


ADDRESS = {"text": "House 12, Road 5, Mirpur-10, Dhaka-1216"}


# ---- settings ----------------------------------------------------------------------------

def test_public_settings_default_to_the_cluster_behaviour():
    s = Settings.from_env({})
    assert (s.public_mode, s.rate_limit_per_minute, s.trusted_proxy_hops) == (False, 0, 0)


def test_public_settings_are_read_from_the_environment():
    s = Settings.from_env({"THIKANA_PUBLIC_MODE": "true", "THIKANA_RATE_LIMIT_PER_MINUTE": "60",
                           "THIKANA_RATE_LIMIT_BURST": "10", "THIKANA_TRUSTED_PROXY_HOPS": "1"})
    assert (s.public_mode, s.rate_limit_per_minute, s.rate_limit_burst, s.trusted_proxy_hops) == (True, 60, 10, 1)
    assert Settings.from_env({"THIKANA_PUBLIC_MODE": "0"}).public_mode is False


@pytest.mark.parametrize("env", [{"THIKANA_PUBLIC_MODE": "maybe"}, {"THIKANA_RATE_LIMIT_PER_MINUTE": "-1"},
                                 {"THIKANA_RATE_LIMIT_BURST": "0"}, {"THIKANA_TRUSTED_PROXY_HOPS": "x"}])
def test_bad_public_configuration_fails_at_startup_naming_the_variable(env):
    with pytest.raises(ValueError, match="THIKANA_"):
        Settings.from_env(env)


# ---- public mode hides what only the cluster should see ----------------------------------

def test_in_the_cluster_metrics_docs_and_the_instance_header_are_present(model_path):
    with client_for(model_path) as c:
        assert c.get("/metrics").status_code == 200
        assert c.get("/docs").status_code == 200 and c.get("/openapi.json").status_code == 200
        assert "x-thikana-instance" in c.get("/healthz").headers


def test_in_public_mode_metrics_docs_schema_and_the_instance_name_are_gone(model_path):
    with client_for(model_path, public_mode=True) as c:
        for path in ("/metrics", "/docs", "/redoc", "/openapi.json"):
            response = c.get(path)
            assert response.status_code == 404, path
            assert response.json()["error"]["code"] == "not_found"        # the usual envelope, no stack
        for path in ("/healthz", "/readyz", "/", "/api/v1/model"):
            assert "x-thikana-instance" not in c.get(path).headers, path  # no pod or host name leaks
        assert c.post("/api/v1/parse", json=ADDRESS).status_code == 200   # the product still works


# ---- headers ------------------------------------------------------------------------------

@pytest.mark.parametrize("public", [False, True])
def test_every_response_carries_the_security_headers(model_path, public):
    with client_for(model_path, public_mode=public) as c:
        responses = [c.get("/"), c.get("/assets/app.js"), c.get("/healthz"), c.get("/api/v1/model"),
                     c.post("/api/v1/parse", json=ADDRESS), c.get("/nope")]
        for r in responses:
            assert r.headers["x-content-type-options"] == "nosniff"
            assert r.headers["referrer-policy"] == "no-referrer"
            assert r.headers["x-frame-options"] == "DENY"


def test_the_content_security_policy_is_on_the_page_only_and_allows_nothing_inline(model_path):
    with client_for(model_path) as c:
        page, script = c.get("/"), c.get("/assets/app.js")
        csp = page.headers["content-security-policy"]
        assert script.headers["content-security-policy"] == csp
        assert "content-security-policy" not in c.get("/api/v1/model").headers   # /docs needs a CDN and inline
        assert "default-src 'none'" in csp and "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
        assert "unsafe-inline" not in csp and "unsafe-eval" not in csp and "*" not in csp


# ---- the page ------------------------------------------------------------------------------

def test_the_page_loads_nothing_from_anywhere_else_and_has_no_inline_code():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)", html), "inline <script>"
    assert not re.search(r"\son[a-z]+\s*=", html), "inline event handler"
    assert not re.search(r"\sstyle\s*=", html), "inline style attribute"
    urls = re.findall(r"https?://[^\s\"')]+", html)
    assert urls == ["http://www.w3.org/2000/svg"], urls          # only the SVG namespace inside the favicon
    assert (WEB / "style.css").read_text(encoding="utf-8").count("@import") == 0
    assert "url(" not in (WEB / "style.css").read_text(encoding="utf-8")


def test_every_asset_the_page_references_is_served_with_the_right_type(model_path):
    html = (WEB / "index.html").read_text(encoding="utf-8")
    refs = re.findall(r'(?:src|href)="(/assets/[^"]+)"', html)
    assert {r.rsplit("/", 1)[1] for r in refs} == {"style.css", "render.js", "app.js"}
    types = {".css": "text/css", ".js": "text/javascript"}
    with client_for(model_path) as c:
        for ref in refs:
            r = c.get(ref)
            assert r.status_code == 200 and r.headers["content-type"].startswith(types[ref[ref.rindex("."):]]), ref
        assert c.get("/").headers["content-type"].startswith("text/html")


@pytest.mark.parametrize("name", ["app.js", "render.js"])
def test_the_scripts_never_use_ways_of_putting_text_on_the_page_as_markup_or_storing_it(name):
    code = (WEB / name).read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)                # the header comments name these on purpose
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function",
                   "localStorage", "sessionStorage", "document.cookie", "indexedDB", "XMLHttpRequest",
                   "navigator.sendBeacon", "http://", "https://"):
        assert banned not in code, f"{name} uses {banned}"


def test_the_page_only_talks_to_its_own_api():
    code = (WEB / "app.js").read_text(encoding="utf-8")
    assert set(re.findall(r'fetch\("([^"]+)"', code)) == {"/api/v1/model", "/api/v1/parse", "/api/v1/parse/batch"}


# ---- rate limiter: the unit -----------------------------------------------------------------

def test_the_token_bucket_allows_a_burst_then_refills_steadily():
    now = [0.0]
    limiter = RateLimiter(per_minute=60, burst=3, clock=lambda: now[0])       # 1 token per second
    assert [limiter.check("a")[0] for _ in range(4)] == [True, True, True, False]
    allowed, wait = limiter.check("a")
    assert not allowed and wait == pytest.approx(1.0)
    now[0] += 1.0
    assert limiter.check("a")[0] is True and limiter.check("a")[0] is False
    now[0] += 100.0                                                            # a long rest refills only to the burst
    assert [limiter.check("a")[0] for _ in range(4)] == [True, True, True, False]


def test_one_noisy_client_does_not_use_up_another_clients_allowance():
    limiter = RateLimiter(per_minute=60, burst=2, clock=lambda: 0.0)
    assert [limiter.check("noisy")[0] for _ in range(3)] == [True, True, False]
    assert limiter.check("quiet")[0] is True


def test_the_client_table_is_bounded_so_rotating_addresses_cannot_exhaust_memory():
    limiter = RateLimiter(per_minute=60, burst=2, max_clients=100, clock=lambda: 0.0)
    for i in range(10_000):
        limiter.check(f"10.0.{i // 256}.{i % 256}")
    assert len(limiter) == 100


def test_the_limiter_rejects_nonsense_settings():
    for bad in ({"per_minute": 0, "burst": 1}, {"per_minute": 5, "burst": 0}, {"per_minute": 5, "burst": 1, "max_clients": 0}):
        with pytest.raises(ValueError):
            RateLimiter(**bad)


# ---- which address is rate-limited ----------------------------------------------------------

def test_the_forwarded_header_is_ignored_unless_proxies_are_trusted():
    headers = {"x-forwarded-for": "6.6.6.6, 9.9.9.9"}
    assert client_key(headers, "10.0.0.1", 0) == "10.0.0.1"          # safe default: the socket peer
    assert client_key({}, None, 0) == "unknown"


def test_with_one_trusted_proxy_only_the_entry_that_proxy_added_is_believed():
    # A client can write anything on the LEFT; the single trusted proxy appends the real address.
    assert client_key({"x-forwarded-for": "6.6.6.6, 9.9.9.9"}, "10.0.0.1", 1) == "9.9.9.9"
    assert client_key({"x-forwarded-for": "1.1.1.1, 2.2.2.2, 9.9.9.9"}, "10.0.0.1", 1) == "9.9.9.9"
    assert client_key({"x-forwarded-for": "2.2.2.2, 9.9.9.9"}, "10.0.0.1", 2) == "2.2.2.2"
    assert client_key({}, "10.0.0.1", 1) == "10.0.0.1"                # header missing: fall back, never crash
    assert client_key({"x-forwarded-for": "9.9.9.9"}, "10.0.0.1", 2) == "10.0.0.1"   # fewer hops than trusted


# ---- rate limiter: in the app --------------------------------------------------------------

def test_the_api_is_limited_with_a_429_in_the_usual_envelope_and_a_retry_after(model_path):
    with client_for(model_path, rate_limit_per_minute=1, rate_limit_burst=3) as c:
        codes = [c.post("/api/v1/parse", json=ADDRESS).status_code for _ in range(5)]
        assert codes == [200, 200, 200, 429, 429]
        limited = c.post("/api/v1/parse", json=ADDRESS)
        assert int(limited.headers["retry-after"]) >= 1
        body = limited.json()["error"]
        assert body["code"] == "rate_limited" and body["request_id"] == limited.headers["x-request-id"]
        assert "House" not in limited.text                              # never echoes the address
        assert limited.headers["x-content-type-options"] == "nosniff"   # even refusals carry the headers


def test_probes_the_page_and_other_clients_are_never_limited(model_path):
    with client_for(model_path, rate_limit_per_minute=1, rate_limit_burst=1) as c:
        c.post("/api/v1/parse", json=ADDRESS)
        assert c.post("/api/v1/parse", json=ADDRESS).status_code == 429
        for path in ("/healthz", "/readyz", "/", "/assets/app.js", "/metrics"):
            assert c.get(path).status_code == 200, path                 # Kubernetes probes must never get a 429
        assert c.get("/api/v1/model").status_code == 429                # but every API route is limited


def test_without_trusted_proxies_a_forged_forwarded_header_does_not_buy_a_new_allowance(model_path):
    with client_for(model_path, rate_limit_per_minute=1, rate_limit_burst=2) as c:
        codes = [c.post("/api/v1/parse", json=ADDRESS, headers={"X-Forwarded-For": f"203.0.113.{i}"}).status_code
                 for i in range(5)]
        assert codes == [200, 200, 429, 429, 429]


def test_with_one_trusted_proxy_clients_are_separate_and_forging_the_left_side_does_not_help(model_path):
    with client_for(model_path, rate_limit_per_minute=1, rate_limit_burst=2, trusted_proxy_hops=1) as c:
        def post(forwarded):
            return c.post("/api/v1/parse", json=ADDRESS, headers={"X-Forwarded-For": forwarded}).status_code
        assert [post("1.1.1.1, 9.9.9.9") for _ in range(3)] == [200, 200, 429]            # the proxy-added 9.9.9.9
        assert post("2.2.2.2, 9.9.9.9") == 429                                              # a new forged left entry: same client
        assert post("2.2.2.2, 8.8.8.8") == 200                                              # a genuinely different client


def test_rate_limiting_is_off_unless_asked_for(model_path):
    with client_for(model_path) as c:
        assert {c.post("/api/v1/parse", json=ADDRESS).status_code for _ in range(30)} == {200}


# ---- privacy: the limiter must hold addresses in memory only --------------------------------

def test_client_addresses_never_reach_the_logs_even_though_the_limiter_uses_them(model_path, caplog):
    import logging
    caplog.set_level(logging.DEBUG)
    with client_for(model_path, rate_limit_per_minute=1, rate_limit_burst=1, trusted_proxy_hops=1) as c:
        for _ in range(3):                                           # the second and third are 429s
            c.post("/api/v1/parse", json=ADDRESS, headers={"X-Forwarded-For": "198.51.100.77, 203.0.113.9"})
    logged = " ".join(r.getMessage() + " " + str(getattr(r, "__dict__", "")) for r in caplog.records)
    assert "request" in logged and "429" in logged                   # the refusals were logged...
    for forbidden in ("198.51.100.77", "203.0.113.9", "testclient", "House 12"):
        assert forbidden not in logged, forbidden                    # ...without who asked or what


# ---- the image ships the page --------------------------------------------------------------

def test_the_dockerfile_and_allowlist_include_the_web_directory():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "COPY --chmod=a=rX thikana/web/ thikana/web/" in dockerfile
    assert "!thikana/web/" in ignore
    for name in ("index.html", "style.css", "render.js", "app.js"):
        assert (WEB / name).is_file()
    assert {p.name for p in WEB.iterdir()} == {"index.html", "style.css", "render.js", "app.js"}   # nothing stray ships


def test_the_page_keeps_its_privacy_and_prototype_statements_and_has_no_bottom_clutter():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    flat = " ".join(re.sub(r"<[^>]+>", " ", html).split())
    for promise in ("Please don't type a real person's address",
                    "does not store what you type and logs only counts, never the text",
                    "That host may keep its own logs of requests, which this app cannot see or control",
                    "no cookies, no analytics and nothing is loaded from other sites",
                    "Treat its output as a draft, never as a verified address",
                    "A file you choose is read in your browser and is never uploaded as a file",
                    "not a product, with no uptime promise"):
        assert promise in flat, promise
    assert 'class="badge"' not in html and "<title>Thikana - Bangladeshi address parser</title>" in html   # no label
    assert 'class="privacy"' not in html               # the strip is gone; the same facts live in the dialog
    assert "<footer" not in html                       # the old footer and "What this is, and is not" section are gone
    assert "What this is, and is not" not in html
    assert 'id="about"' in html and "<dialog" in html  # the model's limits still reach the reader, one click away
