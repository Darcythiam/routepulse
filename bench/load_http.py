"""Small bounded HTTP load generator for the cached trip detail path."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
import statistics
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def request_once(url):
    started = time.perf_counter()
    try:
        with urlopen(url, timeout=10) as response:
            response.read()
            status = response.status
    except HTTPError as exc:
        status = exc.code
    except (URLError, TimeoutError):
        status = 0
    return (time.perf_counter() - started) * 1000, status


def percentile(values, percent):
    ordered = sorted(values)
    return ordered[min(math.ceil(len(ordered) * percent / 100) - 1, len(ordered) - 1)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:5000/api/trips/1")
    parser.add_argument("--requests", type=int, default=2000)
    parser.add_argument("--concurrency", type=int, default=32)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1:
        parser.error("requests and concurrency must be positive")
    # Confirm a working endpoint before generating requests.
    _, initial_status = request_once(args.url)
    if initial_status != 200:
        parser.error(f"Endpoint returned HTTP {initial_status}; seed a trip and check readiness first")
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        results = [future.result() for future in as_completed(
            [executor.submit(request_once, args.url) for _ in range(args.requests)]
        )]
    elapsed = time.perf_counter() - started
    latencies = [latency for latency, _ in results]
    errors = sum(status < 200 or status >= 400 for _, status in results)
    report = {
        "url": args.url,
        "requests": args.requests,
        "concurrency": args.concurrency,
        "duration_seconds": round(elapsed, 3),
        "requests_per_second": round(args.requests / elapsed, 2),
        "p50_ms": round(statistics.median(latencies), 2),
        "p95_ms": round(percentile(latencies, 95), 2),
        "error_rate_percent": round(errors / args.requests * 100, 3),
    }
    print(json.dumps(report, indent=2))
    if args.output:
        with open(args.output, "w", encoding="utf-8") as file:
            json.dump(report, file, indent=2)


if __name__ == "__main__":
    main()
