"""A small load generator for the parse endpoint. Standard library only.

Run:  python scripts/loadtest.py http://localhost:8088 --seconds 20 --concurrency 8

It reports status codes, WHICH REPLICA answered (X-Thikana-Instance), throughput and
latency percentiles, and with --timeline a per-second table, which is how you see
exactly when errors happened during a rollout or a killed pod.

What it is not: a benchmark of the service. The load generator runs on the same
machine as the thing it is measuring and competes with it for CPU, and the addresses
are a handful of made-up examples. Numbers from it compare configurations on one
machine; they are not capacity claims.
"""

from __future__ import annotations

import argparse
import http.client
import itertools
import json
import threading
import time
from collections import Counter
from urllib.parse import urlsplit

ADDRESSES = [
    "House 12, Road 5, Mirpur-10, Dhaka-1216",
    "Flat 4B, House 7, Block C, Road 3, Banani, Dhaka 1213",
    "Vill: Kaunia, P.O: Kaunia, Thana: Kaunia, Dist: Rangpur",
    "বাসা ১২, রোড ৫, ধানমন্ডি, ঢাকা-১২০৫",
    "Sector 7, Uttara, Dhaka-1230",
    "Zindabazar, Sylhet Sadar, Sylhet 3100",
]


def worker(host, port, path, deadline, keepalive, results, lock, started):
    bodies = itertools.cycle(json.dumps({"text": t}).encode("utf-8") for t in ADDRESSES)
    headers = {"Content-Type": "application/json"}
    conn = None
    local = []
    while time.monotonic() < deadline:
        body = next(bodies)
        t0 = time.monotonic()
        status, instance, error = 0, "-", ""
        try:
            if conn is None:
                conn = http.client.HTTPConnection(host, port, timeout=10)
            conn.request("POST", path, body=body, headers=headers)
            response = conn.getresponse()
            response.read()
            status = response.status
            instance = response.getheader("X-Thikana-Instance", "-")
            if not keepalive or response.will_close:
                conn.close()
                conn = None
        except Exception as exc:                      # a refused/reset connection is a data point
            error = type(exc).__name__ + (f"[{exc.errno}]" if getattr(exc, "errno", None) else "")
            if conn is not None:
                conn.close()
            conn = None
        local.append((t0 - started, time.monotonic() - t0, status, instance, error))
    with lock:
        results.extend(local)


def percentile(sorted_values, p):
    return sorted_values[min(len(sorted_values) - 1, int(len(sorted_values) * p))] if sorted_values else float("nan")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("url", help="base URL, e.g. http://localhost:8088")
    ap.add_argument("--seconds", type=float, default=15)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--keepalive", action="store_true",
                    help="reuse one connection per worker (default: a new connection per request)")
    ap.add_argument("--timeline", action="store_true", help="print a per-second ok/error table")
    args = ap.parse_args()

    parts = urlsplit(args.url)
    host, port = parts.hostname, parts.port or 80
    if host == "localhost":
        # On Windows, Python tries IPv6 (::1) first; Docker Desktop's published ports do not
        # answer there, so every new connection waited out the whole connect timeout (10 s)
        # before falling back to 127.0.0.1. Measured: ~10 s per request vs ~31 ms.
        host = "127.0.0.1"
    path = (parts.path.rstrip("/") or "") + "/api/v1/parse"
    results, lock = [], threading.Lock()
    started = time.monotonic()
    deadline = started + args.seconds
    threads = [threading.Thread(target=worker, args=(host, port, path, deadline, args.keepalive,
                                                     results, lock, started))
               for _ in range(args.concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.monotonic() - started

    ok = [r for r in results if r[2] == 200]
    latencies = sorted(r[1] * 1000 for r in ok)
    codes = Counter(r[2] if r[2] else r[4] for r in results)
    print(f"{len(results)} requests in {elapsed:.1f}s  |  concurrency {args.concurrency}  |  "
          f"{'keep-alive' if args.keepalive else 'new connection per request'}")
    print(f"status/error counts: {dict(codes)}")
    print(f"throughput (200s only): {len(ok) / elapsed:.1f} req/s")
    print(f"latency ms (200s)  p50 {percentile(latencies, .50):.1f}  p95 {percentile(latencies, .95):.1f}  "
          f"p99 {percentile(latencies, .99):.1f}  max {latencies[-1] if latencies else float('nan'):.1f}")
    local_port_errors = sum(n for k, n in codes.items()
                            if isinstance(k, str) and any(c in k for c in ("[10048]", "[10055]", "[99]", "[98]")))
    if local_port_errors:
        print(f"WARNING: {local_port_errors} errors mean THIS MACHINE ran out of local ports (a new "
              "connection per request leaves each one in TIME_WAIT for ~2 minutes). That is a limit of "
              "the load generator, not a failure of the service. Use --keepalive or shorter runs.")
    by_instance = Counter(r[3] for r in ok)
    total = sum(by_instance.values()) or 1
    print("answered by:")
    for name, n in sorted(by_instance.items()):
        print(f"  {name:32s} {n:6d}  {100 * n / total:5.1f}%")

    if args.timeline:
        print("\nsecond  ok  errors  instances answering")
        for sec in range(int(elapsed) + 1):
            bucket = [r for r in results if sec <= r[0] < sec + 1]
            good = [r for r in bucket if r[2] == 200]
            print(f"{sec:5d} {len(good):4d} {len(bucket) - len(good):6d}   "
                  f"{len({r[3] for r in good})}")


if __name__ == "__main__":
    main()
