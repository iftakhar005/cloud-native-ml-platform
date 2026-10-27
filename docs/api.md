# API

A FastAPI service around the trained address parser. It splits one free-text
Bangladeshi address (Bangla and/or English) into labelled parts.

**It is a prototype.** The model was trained on synthetic addresses and checked
only against small hand-written sets, never against real addresses. See
`GET /api/v1/model` (`limitations`) and `docs/results.md`.

## Run it

From the project folder, in PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn thikana.api.main:app --port 8000
```

Then open <http://localhost:8000/docs> for interactive documentation.

The model is loaded at startup from `models/crf_all_district_memory.crfsuite`. If
you have not trained it yet: `python -m thikana.training.train_all`.

## Endpoints

| Method and path | Purpose |
|---|---|
| `POST /api/v1/parse` | one address -> labelled parts |
| `POST /api/v1/parse/batch` | up to 100 addresses in one request |
| `GET /api/v1/model` | which model is serving, its verifiable version, its limitations |
| `GET /healthz` | **liveness**: the process is up. Checks nothing external, on purpose |
| `GET /readyz` | **readiness**: 200 only when a model is loaded, else 503 |
| `GET /metrics` | Prometheus metrics |

Liveness and readiness are different questions. A failing liveness probe
*restarts* the container, and a restart cannot fix a missing model, so `/healthz`
never looks at the model. `/readyz` does, so a pod with no model stays out of
rotation and the reason is visible.

## Parse an address

In PowerShell, the simplest call builds the JSON for you:

```powershell
$body = @{ text = "House 12, Road 5, Mirpur-10, Dhaka-1216" } | ConvertTo-Json
Invoke-RestMethod -Uri http://localhost:8000/api/v1/parse -Method Post `
    -ContentType "application/json" -Body $body
```

or, with `curl.exe`, read the body from a file (`request.json` containing
`{"text": "House 12, Road 5, Mirpur-10, Dhaka-1216"}`):

```powershell
curl.exe -s -H "Content-Type: application/json" --data-binary "@request.json" http://localhost:8000/api/v1/parse
```

> Do not pass inline JSON to `curl.exe` from Windows PowerShell 5.1. Its quote
> handling splits the JSON at the spaces into separate arguments, and curl then
> tries to treat `Road` and `12,` as hostnames (confirmed against this service).
> The `\"` workaround you may find online does not fix that. A file, or
> `Invoke-RestMethod`, avoids quoting entirely.

The response:

```json
{
  "entities": [
    {"label": "HOUSE",    "text": "House 12",  "start": 0,  "end": 8},
    {"label": "ROAD",     "text": "Road 5",    "start": 10, "end": 16},
    {"label": "AREA",     "text": "Mirpur-10", "start": 18, "end": 27},
    {"label": "DISTRICT", "text": "Dhaka",     "start": 29, "end": 34},
    {"label": "POSTCODE", "text": "1216",      "start": 35, "end": 39}
  ],
  "fields": {"house": ["House 12"], "road": ["Road 5"], "area": ["Mirpur-10"],
             "district": ["Dhaka"], "postcode": ["1216"]},
  "model_version": "49b58b49a6fe"
}
```

- `start` / `end` are character offsets into **your original text**, which the
  service never strips or alters, so a UI can highlight each span exactly.
- `entities` keeps the text as written. `fields` groups the same parts by label,
  and returns postcodes with ASCII digits (`১২১৬` becomes `1216`).
- Labels: `HOUSE ROAD BLOCK AREA UPAZILA DISTRICT DIVISION POSTCODE LANDMARK`.
  Anything else (`Dist:`, `P.O:`, `Shop 12`, `Bangladesh`) is deliberately unlabelled;
  see `docs/label-schema.md` for every rule.

### Bangla from PowerShell

Send **bytes**, so PowerShell's own console encoding cannot mangle the text:

```powershell
$bytes = [System.IO.File]::ReadAllBytes("request.json")   # a UTF-8 file: {"text": "বাসা ১২, ..."}
Invoke-RestMethod -Uri http://localhost:8000/api/v1/parse -Method Post `
    -ContentType "application/json; charset=utf-8" -Body $bytes
```

Windows PowerShell 5.1 decodes a JSON response with no declared charset as
ISO-8859-1, which turns Bangla into mojibake. This service therefore sends
`Content-Type: application/json; charset=utf-8` on every JSON response. (Found
by calling the live server from PowerShell; covered by a test.) To *display*
Bangla in the console, run `[Console]::OutputEncoding = [Text.Encoding]::UTF8`.

## Errors

Every error has one shape. Switch on `code`; quote `request_id` to find the log line.

```json
{"error": {"code": "empty_text", "message": "text must contain at least one non-space character",
           "request_id": "15f69cb4c44a4cc6824bd4d3e15b0fc9"}}
```

| Status | `code` | When |
|---|---|---|
| 422 | `empty_text` | nothing but whitespace |
| 422 | `text_too_long` | over `THIKANA_MAX_TEXT_CHARS` (default 500) |
| 422 | `invalid_characters` | control characters (tab, newline and CR are allowed) |
| 422 | `batch_size` | not between 1 and `THIKANA_MAX_BATCH` addresses |
| 422 | `invalid_request` | wrong shape or type, a missing field, or an unknown field |
| 404 / 405 | `not_found` / `method_not_allowed` | |
| 413 | `body_too_large` | `Content-Length` over `THIKANA_MAX_BODY_BYTES` |
| 429 | `rate_limited` | over `THIKANA_RATE_LIMIT_PER_MINUTE` (off by default); `Retry-After` says how long |
| 503 | `model_not_ready` | no model loaded |
| 500 | `internal_error` | a bug; the message never contains your text |

Error responses **never repeat what you sent**. FastAPI's default 422 does
(under `"input"`); that is replaced, because an address is personal data.

## Configuration

Environment variables only; the service has **no secrets** in v1 (no database, no
keys, no outbound calls). `.env.example` lists them. In Docker they become `-e`
flags, in Kubernetes a ConfigMap.

| Variable | Default | Meaning |
|---|---|---|
| `THIKANA_MODEL_PATH` | `models/crf_all_district_memory.crfsuite` | the model to serve |
| `THIKANA_MAX_TEXT_CHARS` | `500` | longest accepted address |
| `THIKANA_MAX_BATCH` | `100` | most addresses per batch request |
| `THIKANA_MAX_BODY_BYTES` | `65536` | largest request body (by `Content-Length`) |
| `THIKANA_LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `THIKANA_CORS_ORIGINS` | *(empty = CORS off)* | comma-separated allowed origins |
| `THIKANA_GIT_SHA` | `unknown` | stamped by the build; shown by `/api/v1/model` |
| `THIKANA_INSTANCE` | the machine's hostname | which replica answered; sent in the `X-Thikana-Instance` response header. The hostname is the pod name in Kubernetes and the container id in Docker. 1-63 characters from `A-Z a-z 0-9 . _ -`; anything else fails at startup because the value goes into an HTTP header. Set it to something neutral to hide the pod name |

For a deployment on the open internet (read `docs/public-hosting.md` first):

| Variable | Default | Meaning |
|---|---|---|
| `THIKANA_PUBLIC_MODE` | `false` | `true` makes `/metrics`, `/docs`, `/redoc` and `/openapi.json` return 404 and stops sending `X-Thikana-Instance`. The cluster leaves it off because Prometheus needs `/metrics` |
| `THIKANA_RATE_LIMIT_PER_MINUTE` | `0` (off) | per-client limit on `/api/*` only (never the page, `/healthz`, `/readyz` or `/metrics`); a 429 with `Retry-After` beyond it |
| `THIKANA_RATE_LIMIT_BURST` | `20` | requests a client may make at once before the steady rate applies |
| `THIKANA_TRUSTED_PROXY_HOPS` | `0` | how many proxies in front of the service append to `X-Forwarded-For`. `0` ignores the header and rate-limits the socket peer (behind a proxy that means one shared bucket: annoying, not exploitable). Set it only after checking how your host behaves |

A bad value fails at startup with a message naming the variable.

The web page is served at `/` (static files under `/assets/`, strict CSP, nothing loaded from other
hosts); it is the same process as the API, so there is no CORS and no second service.

Every response carries `X-Request-ID` (echoed if valid, else generated) and
`X-Thikana-Instance`. The second exists so that behind a load balancer you can see
*which* replica served a request (`docs/kubernetes.md`); it says nothing about the address.

## Privacy

The submitted address is never logged, returned in an error, cached
(`Cache-Control: no-store` on `/api/*`), or used as a metric label. A log line
looks like this, and tests fail if the text ever appears in one:

```json
{"ts": "2026-10-26T18:04:45.262+00:00", "level": "INFO", "event": "request",
 "request_id": "81c088b9...", "method": "POST", "route": "/api/v1/parse",
 "status": 200, "duration_ms": 5.39, "addresses": 1, "text_chars": 39, "entities": 5}
```

Exceptions are logged by **type and location only**, never by message, because an
exception message is the one place user text could leak by accident.

## Metrics worth watching

| Metric | Why |
|---|---|
| `thikana_http_requests_total{method,route,status}` | traffic and errors. `route` is the template (`/api/v1/parse`), so junk URLs cannot create unbounded series |
| `thikana_http_request_duration_seconds` | latency |
| `thikana_model_ready` | 1 if a model is loaded |
| `thikana_entities_total{label}` | **ML-specific**: the distribution of predicted labels. A shift means the input has probably drifted |
| `thikana_empty_parses_total` | **ML-specific**: addresses in which nothing was found |
| `thikana_text_chars` | the length of inputs people send |

## Behaviour you should know about

- **Calls to the model are serialised by a lock.** `pycrfsuite.Tagger` makes no
  thread-safety promise and FastAPI runs ordinary endpoints in a thread pool.
  Inference takes a few milliseconds; scaling out means more replicas, not more threads.
- **The model version is a hash.** `version` is the first 12 hex digits of the
  SHA-256 of the model file plus its sidecar, so it identifies what is serving.
- **The request size limit uses `Content-Length`.** A chunked body that omits it is
  bounded by the ingress or reverse proxy in front of the service, not by this code.
- **No authentication, no rate limiting.** Both belong at the ingress / platform
  layer and are not in this service yet.
- **A missing or corrupt model does not crash the process.** It starts, serves
  `/healthz`, answers `/readyz` with 503 and logs `model_load_failed` with the error type.
- **Single-request latency observed locally was 3.8-5.4 ms** (three requests, one
  machine). That is not a benchmark.
