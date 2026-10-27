"""Audit a deployed Thikana URL from the OUTSIDE, the way a stranger would. Standard library only.

    python scripts/check_public.py https://your-service.example
    python scripts/check_public.py https://your-service.example --probe-rate-limit

Exit status 0 only if every check passes. It checks what the deployment promises
(docs/public-hosting.md): the page loads and is locked down, `/metrics` and the API docs are
not reachable, nothing leaks the host's internals, the API works and refuses what it should.

--probe-rate-limit also sends a burst of requests (up to --max-requests) to find out whether the
per-client limit works BEHIND THIS HOST'S PROXY and whether forging X-Forwarded-For buys a new
allowance. That is the one thing that cannot be known in advance, because it depends on how the
host's proxy writes that header. It uses up the caller's own allowance for about a minute.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

SAMPLE = {"text": "House 12, Road 5, Mirpur-10, Dhaka-1216"}


@dataclass
class Reply:
    status: int
    headers: dict
    body: bytes

    def json(self):
        return json.loads(self.body.decode("utf-8"))


def request(base: str, path: str, method: str = "GET", body: dict | None = None,
            headers: dict | None = None, timeout: float = 90.0) -> Reply:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    hdrs = {"Accept": "*/*", **({"Content-Type": "application/json"} if body is not None else {}), **(headers or {})}
    req = urllib.request.Request(base.rstrip("/") + path, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:      # verifies the TLS certificate
            return Reply(response.status, {k.lower(): v for k, v in response.headers.items()}, response.read())
    except urllib.error.HTTPError as err:
        return Reply(err.code, {k.lower(): v for k, v in err.headers.items()}, err.read())


def checks(base: str) -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        out.append((name, bool(ok), detail))

    page = request(base, "/")
    add("the page loads", page.status == 200 and b"Thikana" in page.body, f"HTTP {page.status}")
    add("the page is HTML", page.headers.get("content-type", "").startswith("text/html"), page.headers.get("content-type", "?"))
    csp = page.headers.get("content-security-policy", "")
    add("the page sends a strict CSP", "default-src 'none'" in csp and "unsafe-inline" not in csp, csp or "missing")
    add("nosniff and no framing", page.headers.get("x-content-type-options") == "nosniff"
        and page.headers.get("x-frame-options") == "DENY", "")

    for asset, kind in (("/assets/app.js", "javascript"), ("/assets/render.js", "javascript"), ("/assets/style.css", "css")):
        r = request(base, asset)
        add(f"{asset} is served as {kind}", r.status == 200 and kind in r.headers.get("content-type", ""),
            f"HTTP {r.status} {r.headers.get('content-type', '')}")

    for hidden in ("/metrics", "/docs", "/redoc", "/openapi.json"):
        r = request(base, hidden)
        add(f"{hidden} is NOT reachable", r.status == 404, f"HTTP {r.status}")

    leaked = [p for p in ("/", "/healthz", "/api/v1/model") if "x-thikana-instance" in request(base, p).headers]
    add("no instance (pod/host) name is leaked", not leaked, ", ".join(leaked))

    ready = request(base, "/readyz")
    add("the model is loaded (/readyz)", ready.status == 200, f"HTTP {ready.status}")
    model = request(base, "/api/v1/model")
    info = model.json() if model.status == 200 else {}
    add("/api/v1/model states its limitations", bool(info.get("limitations")), f"HTTP {model.status}")

    parsed = request(base, "/api/v1/parse", "POST", SAMPLE)
    fields = parsed.json().get("fields", {}) if parsed.status == 200 else {}
    add("parsing works", parsed.status == 200 and fields.get("postcode") == ["1216"], f"HTTP {parsed.status}")
    add("API answers are not cacheable", parsed.headers.get("cache-control") == "no-store", parsed.headers.get("cache-control", "?"))

    too_long = request(base, "/api/v1/parse", "POST", {"text": "a" * 501})
    add("oversized input is refused without echo", too_long.status == 422 and b"aaaa" not in too_long.body,
        f"HTTP {too_long.status}")
    return out


def probe_rate_limit(base: str, max_requests: int) -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []
    first = None
    for i in range(1, max_requests + 1):
        if request(base, "/api/v1/parse", "POST", SAMPLE).status == 429:
            first = i
            break
    out.append(("the rate limit engages (no forged header)", first is not None,
                f"first 429 at request {first}" if first else f"no 429 in {max_requests} requests: limiter off or too generous"))
    if first is None:
        return out
    # The caller's own allowance is now spent. If the limiter keys on a forgeable header, a fresh
    # fake address in X-Forwarded-For would buy a new allowance and these would succeed.
    forged = [request(base, "/api/v1/parse", "POST", SAMPLE, {"X-Forwarded-For": f"203.0.113.{i}"}).status
              for i in range(1, 6)]
    out.append(("forging X-Forwarded-For does NOT buy a new allowance", forged.count(429) >= 4,
                f"statuses {forged}: if these are 200 the limiter trusts a header it should not "
                f"(lower THIKANA_TRUSTED_PROXY_HOPS)"))
    refused = request(base, "/api/v1/parse", "POST", SAMPLE)
    retry = refused.headers.get("retry-after", "")
    out.append(("a refusal says when to retry", refused.status == 429 and retry.isdigit() and int(retry) >= 1,
                f"Retry-After={retry!r}"))
    page = request(base, "/")
    out.append(("the page itself is never rate-limited", page.status == 200, f"HTTP {page.status}"))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Audit a deployed Thikana URL from the outside.")
    ap.add_argument("url", help="e.g. https://your-service.example")
    ap.add_argument("--probe-rate-limit", action="store_true", help="also test the rate limiter (sends a burst)")
    ap.add_argument("--max-requests", type=int, default=300)
    args = ap.parse_args(argv)

    results = checks(args.url)
    if args.probe_rate_limit:
        results += probe_rate_limit(args.url, args.max_requests)
    width = max(len(name) for name, _, _ in results)
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name:{width}s}  {detail if not ok or detail.startswith('first') else ''}".rstrip())
    failed = [name for name, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)} of {len(results)} checks passed" + (f"; FAILED: {', '.join(failed)}" if failed else ""))
    if not args.url.startswith("https://") and "127.0.0.1" not in args.url and "localhost" not in args.url:
        print("WARNING: this URL is not https, so what visitors type travels in clear text.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
