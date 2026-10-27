"""The app.   Run:  uvicorn thikana.api.main:app --port 8000   (docs at /docs)"""

from __future__ import annotations

import logging
import math
import mimetypes
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.exceptions import HTTPException as StarletteHTTPException

from thikana.api.errors import ApiError, envelope
from thikana.api.ratelimit import RateLimiter, client_key
from thikana.api.responses import Utf8JSONResponse
from thikana.api.observability import REQUEST_ID_OK, Metrics, configure_logging, log
from thikana.api.schemas import (BatchRequest, BatchResponse, ErrorResponse, ModelInfo,
                                 ParseRequest, ParseResponse)
from thikana.api.service import ParserService, validate_text
from thikana.api.settings import Settings
from thikana.model import AddressParser

VERSION = "0.1.0"
ERRORS = {422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}}
WEB = Path(__file__).resolve().parents[1] / "web"

# Python reads MIME types from the Windows registry, where .js is sometimes text/plain; with
# `nosniff` (below) a browser then refuses to run the script. Pin the ones the UI needs.
for _ext, _type in ((".js", "text/javascript"), (".css", "text/css"), (".svg", "image/svg+xml")):
    mimetypes.add_type(_type, _ext)

# On every response: never let a browser guess a type, never leak the address through a
# Referer, never allow the page (or the API) to be framed.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
}
# On the UI only. The page loads nothing from anywhere else (no CDN, no fonts, no analytics),
# so the policy can forbid everything but itself; `connect-src 'self'` lets it call the API.
UI_CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
          "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def load_service(settings: Settings) -> ParserService | None:
    """Load the model, or return None and say why. Never raises.

    A broken model must make the pod UNREADY and visible (/readyz 503, a clear log
    line), not crash-loop: a crash loop hides the reason behind restart noise.
    """
    try:
        if not settings.model_path.exists():
            raise FileNotFoundError(settings.model_path.name)
        parser = AddressParser.load(settings.model_path)
        parser.predict("Dhaka 1212")  # prove it actually runs, not merely that it opened
        return ParserService(parser, settings.model_path, settings.git_sha)
    except Exception as exc:
        log("model_load_failed", logging.ERROR, exc_info=True,
            model_file=settings.model_path.name, error_type=type(exc).__name__)
        return None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    configure_logging(settings.log_level)
    metrics = Metrics()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        service = load_service(settings)
        app.state.service = service
        metrics.model_ready.set(1 if service else 0)
        if service:
            info = service.info
            metrics.model_info.labels(info.name, info.version).set(1)
            log("model_loaded", model=info.name, version=info.version, size_bytes=info.size_bytes)
        yield

    # On the open internet the interactive docs and the schema are switched off (smaller
    # surface, less noise); the API is documented in docs/api.md.
    docs = {} if not settings.public_mode else {"docs_url": None, "redoc_url": None, "openapi_url": None}
    app = FastAPI(
        title="Thikana address parser", version=VERSION, lifespan=lifespan,
        default_response_class=Utf8JSONResponse,
        description="Splits a free-text Bangladeshi address into house, road, block, area, "
                    "upazila, district, division, postcode and landmark. A PROTOTYPE: see "
                    "/api/v1/model for its limitations.", **docs)
    app.state.service = None
    limiter = (RateLimiter(settings.rate_limit_per_minute, settings.rate_limit_burst)
               if settings.rate_limit_per_minute else None)

    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                           allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-Request-ID"])

    # ---- every response gets a request id, a latency, a log line and metrics ----
    @app.middleware("http")
    async def observe(request: Request, call_next):
        started = time.perf_counter()
        rid = request.headers.get("x-request-id", "")
        request.state.request_id = rid if REQUEST_ID_OK.match(rid) else uuid.uuid4().hex
        request.state.audit = {}

        wait = None
        # `is not None`, NOT truthiness: RateLimiter has __len__, and an empty one is falsy,
        # which silently turned the limiter off (caught by tests/test_public_mode.py).
        if limiter is not None and request.url.path.startswith("/api/"):   # never the UI, probes or scrapes
            peer = request.client.host if request.client else None
            allowed, seconds = limiter.check(client_key(request.headers, peer, settings.trusted_proxy_hops))
            wait = None if allowed else seconds

        length = request.headers.get("content-length", "")
        if wait is not None:
            retry = max(1, math.ceil(wait))
            response = Utf8JSONResponse(
                envelope("rate_limited", f"too many requests: try again in {retry} s", request.state.request_id),
                status_code=429, headers={"Retry-After": str(retry)})
        elif length.isdigit() and int(length) > settings.max_body_bytes:
            # Enforced on Content-Length only. A chunked body without one is bounded
            # by the ingress / reverse proxy in front of the service, not here.
            response = Utf8JSONResponse(
                envelope("body_too_large",
                         f"request body exceeds {settings.max_body_bytes} bytes", request.state.request_id),
                status_code=413)
        else:
            try:
                response = await call_next(request)
            except Exception as exc:
                _finish(request, metrics, 500, started)
                log("unhandled_error", logging.ERROR, exc_info=True,
                    request_id=request.state.request_id, error_type=type(exc).__name__)
                raise

        response.headers["X-Request-ID"] = request.state.request_id
        if not settings.public_mode:      # a pod name is useful in a cluster and a leak on the internet
            response.headers["X-Thikana-Instance"] = settings.instance   # makes load balancing visible
        response.headers.update(SECURITY_HEADERS)
        path = request.url.path
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"  # addresses are personal data
        elif path == "/" or path.startswith("/assets/"):
            response.headers["Content-Security-Policy"] = UI_CSP
            response.headers["Cache-Control"] = "no-cache"  # revalidate (ETag) so a new image shows at once
        _finish(request, metrics, response.status_code, started)
        return response

    # ---- errors: one shape, and never an echo of what the client sent ----------
    def respond(request: Request, status: int, code: str, message: str, **extra) -> Utf8JSONResponse:
        body = envelope(code, message, getattr(request.state, "request_id", "unknown"))
        body["error"].update(extra)
        return Utf8JSONResponse(body, status_code=status)

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        return respond(request, exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        # FastAPI's default 422 includes the submitted value under "input". For an
        # address that would copy personal data into the response (and any proxy
        # log), so only the location and the rule that failed are returned.
        details = [{"loc": [str(p) for p in e["loc"]], "type": e["type"], "message": e["msg"]}
                   for e in exc.errors()]
        return respond(request, 422, "invalid_request", "request body is invalid", details=details)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        codes = {404: "not_found", 405: "method_not_allowed"}
        return respond(request, exc.status_code, codes.get(exc.status_code, "http_error"), str(exc.detail))

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        return respond(request, 500, "internal_error", "an unexpected error occurred")

    def service_of(request: Request) -> ParserService:
        service = request.app.state.service
        if service is None:
            raise ApiError(503, "model_not_ready", "the model is not loaded")
        return service

    def record(request: Request, texts: list[str], results) -> None:
        """Metrics and the audit fields for the access log. Counts, never content."""
        entities = sum(len(r.entities) for r in results)
        metrics.parsed.inc(len(texts))
        for text, result in zip(texts, results):
            metrics.chars.observe(len(text))
            for entity in result.entities:
                metrics.entities.labels(entity.label).inc()
            if not result.entities:
                metrics.empty.inc()
        request.state.audit = {"addresses": len(texts), "text_chars": sum(map(len, texts)),
                               "entities": entities}

    # ---- operations -------------------------------------------------------------
    @app.get("/healthz", tags=["ops"], summary="Liveness: the process is up")
    def healthz():
        # Checks nothing external on purpose: a failing liveness probe RESTARTS the
        # container, and a restart cannot fix a missing model.
        return {"status": "ok"}

    @app.get("/readyz", tags=["ops"], summary="Readiness: able to answer requests",
             responses={503: {"description": "model not loaded"}})
    def readyz(request: Request):
        service = request.app.state.service
        if service is None:
            return Utf8JSONResponse({"status": "not_ready", "reason": "model_not_loaded"}, status_code=503)
        return {"status": "ready", "model_version": service.info.version}

    if not settings.public_mode:
        # Absent (404) on the open internet: request counts and model internals are for the
        # cluster's Prometheus, not for whoever finds the URL.
        @app.get("/metrics", tags=["ops"], summary="Prometheus metrics")
        def prometheus():
            return Response(generate_latest(metrics.registry), media_type=CONTENT_TYPE_LATEST)

    # ---- the product ------------------------------------------------------------
    @app.get("/api/v1/model", tags=["model"], response_model=ModelInfo, responses=ERRORS,
             summary="Which model is serving, and what it cannot do")
    def model_info(request: Request):
        return service_of(request).info

    @app.post("/api/v1/parse", tags=["parse"], response_model=ParseResponse, responses=ERRORS,
              summary="Split one address into labelled parts")
    def parse(body: ParseRequest, request: Request):
        service = service_of(request)
        validate_text(body.text, settings.max_text_chars)
        result = service.parse(body.text)
        record(request, [body.text], [result])
        return ParseResponse(**result.model_dump(), model_version=service.info.version)

    @app.post("/api/v1/parse/batch", tags=["parse"], response_model=BatchResponse, responses=ERRORS,
              summary="Split several addresses in one request")
    def parse_batch(body: BatchRequest, request: Request):
        service = service_of(request)
        if not 1 <= len(body.texts) <= settings.max_batch:
            raise ApiError(422, "batch_size", f"send between 1 and {settings.max_batch} addresses, "
                                              f"got {len(body.texts)}")
        for i, text in enumerate(body.texts):
            validate_text(text, settings.max_text_chars, where=f"texts[{i}]")
        results = [service.parse(text) for text in body.texts]
        record(request, body.texts, results)
        return BatchResponse(results=results, model_version=service.info.version)

    # ---- the web page: one HTML file and its assets, served by the same process ---------
    # Same origin as the API, so no CORS and no second host to secure.
    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(WEB / "index.html", media_type="text/html; charset=utf-8")

    app.mount("/assets", StaticFiles(directory=WEB), name="assets")

    return app


def _finish(request: Request, metrics: Metrics, status: int, started: float) -> None:
    """Count the request and write ONE access-log line (no address content)."""
    elapsed = time.perf_counter() - started
    route = getattr(request.scope.get("route"), "path", "unmatched")  # template, not raw path
    metrics.requests.labels(request.method, route, str(status)).inc()
    metrics.latency.labels(request.method, route).observe(elapsed)
    log("request", request_id=request.state.request_id, method=request.method, route=route,
        status=status, duration_ms=round(elapsed * 1000, 2), **request.state.audit)


app = create_app()
