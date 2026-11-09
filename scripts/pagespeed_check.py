#!/usr/bin/env python3
"""Collect PSI evidence or summarize saved PSI/Lighthouse JSON; standard library only."""

import argparse
from datetime import datetime, timezone
import ipaddress
import json
import math
import os
from pathlib import Path
import socket
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
MAX_BYTES = 32 * 1024 * 1024
METRICS = {
    "largest-contentful-paint": "LCP",
    "first-contentful-paint": "FCP",
    "cumulative-layout-shift": "CLS",
    "total-blocking-time": "TBT",
    "speed-index": "Speed Index",
}


def public_url(value):
    """Reject local/private targets before disclosing them to the hosted service."""
    parts = urlsplit(value)
    if (parts.scheme not in ("http", "https") or not parts.hostname
            or parts.username is not None or parts.password is not None
            or parts.fragment or any(ord(c) < 33 for c in value)):
        raise ValueError("Use a public HTTP(S) URL without credentials, fragments or whitespace.")
    port = parts.port  # Validate malformed ports too.
    host = parts.hostname.rstrip(".").lower()
    if "." not in host or host.endswith((".localhost", ".local", ".internal", ".test")):
        raise ValueError("Hosted PageSpeed cannot inspect local/private URLs; use --input.")
    addresses = socket.getaddrinfo(host, port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("Hosted PageSpeed requires a publicly routable target; use --input.")
    return value


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def collect(url, strategy, timeout):
    params = [("url", url), ("strategy", strategy)]
    params += [("category", c) for c in ("performance", "seo", "accessibility", "best-practices")]
    headers = {"Accept": "application/json", "User-Agent": "codex-seo-audit/1.0"}
    key = os.environ.get("PAGESPEED_API_KEY")
    if key:
        headers["X-Goog-Api-Key"] = key
    request = Request(ENDPOINT + "?" + urlencode(params), headers=headers)
    try:
        with build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            payload = response.read(MAX_BYTES + 1)
        if len(payload) > MAX_BYTES:
            raise ValueError("PageSpeed response exceeded 32 MiB; no complete report saved.")
        return json.loads(payload)
    except HTTPError as exc:
        # Do not print request URLs, headers, echoed keys or provider error bodies.
        hint = " Check quota/API-key configuration and retry later." if exc.code in (400, 401, 403, 429) else ""
        raise ValueError(f"PageSpeed HTTP {exc.code}.{hint}") from None
    except (URLError, TimeoutError, OSError):
        raise ValueError("PageSpeed network request failed or timed out; retry later.") from None


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def summarize(data, strategy=None):
    if not isinstance(data, dict):
        raise ValueError("Expected a PSI response or Lighthouse report object.")
    if "error" in data:
        raise ValueError("Saved response contains a provider error, not a measurement.")
    lh = data.get("lighthouseResult", data)
    if not isinstance(lh, dict) or not isinstance(lh.get("audits"), dict) or not lh.get("lighthouseVersion"):
        raise ValueError("No complete Lighthouse measurement in the supplied JSON.")
    audits = lh["audits"]
    metrics = {}
    for audit_id, label in METRICS.items():
        item = audits.get(audit_id, {})
        metrics[label] = {"value": item.get("numericValue"), "unit": item.get("numericUnit"),
                          "display": item.get("displayValue")}
    failed = []
    for audit_id, item in audits.items():
        score = item.get("score")
        if number(score) and score < 1 and item.get("scoreDisplayMode") not in ("manual", "notApplicable", "informative"):
            failed.append({"id": audit_id, "title": item.get("title"), "score": score,
                           "display": item.get("displayValue"),
                           "metric_savings": item.get("metricSavings"),
                           "estimated_savings_ms": item.get("details", {}).get("overallSavingsMs")})
    field = {}
    for name, source in (("url", "loadingExperience"), ("origin", "originLoadingExperience")):
        experience = data.get(source) or {}
        field[name] = {"available": bool(experience.get("metrics")), "id": experience.get("id"),
                       "metrics": experience.get("metrics", {}), "collection_period": None}
    runtime_error = lh.get("runtimeError")
    return {
        "status": "error" if runtime_error else "measured", "runtime_error": runtime_error,
        "requested_url": lh.get("requestedUrl"), "final_url": lh.get("finalUrl"),
        "strategy": strategy or lh.get("configSettings", {}).get("formFactor"),
        "fetch_time": lh.get("fetchTime"), "analysis_time": data.get("analysisUTCTimestamp"),
        "lighthouse_version": lh["lighthouseVersion"], "environment": lh.get("environment"),
        "config": lh.get("configSettings"), "warnings": lh.get("runWarnings", []),
        "scores": {k: round(v["score"] * 100, 1) if number(v.get("score")) else None
                   for k, v in lh.get("categories", {}).items()},
        "lab_metrics": metrics, "field_data": field,
        "failed_audits": sorted(failed, key=lambda a: (a["score"], a["id"])),
        "limitations": ["Lab TBT is not field INP. Scores do not establish rankings or indexing.",
                         "Missing field data is unknown. Origin data does not establish URL performance.",
                         "PSI field data may be absent; use CrUX separately for collection dates and field coverage."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?")
    parser.add_argument("--input", type=Path, help="Saved PSI response or local Lighthouse JSON (offline)")
    parser.add_argument("--strategy", choices=("mobile", "desktop", "both"), default="mobile")
    parser.add_argument("--output-dir", type=Path, required=True, help="New evidence directory; never overwritten")
    parser.add_argument("--timeout", type=int, default=120, help="Seconds per hosted run (1–300)")
    args = parser.parse_args()
    if bool(args.url) == bool(args.input):
        parser.error("Provide either a public URL or --input, exclusively.")
    if not 1 <= args.timeout <= 300:
        parser.error("--timeout must be between 1 and 300 seconds.")
    try:
        if args.output_dir.exists():
            raise ValueError("Output directory already exists; choose a fresh evidence directory.")
        if args.url:
            public_url(args.url)
        args.output_dir.mkdir(parents=True, exist_ok=False)
        runs = [None] if args.input else (["mobile", "desktop"] if args.strategy == "both" else [args.strategy])
        results = []
        for strategy in runs:
            label = strategy or "imported"
            try:
                data = json.loads(args.input.read_text(encoding="utf-8")) if args.input else collect(args.url, strategy, args.timeout)
                # Retain error-bearing responses too, without exposing the API key.
                raw = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False)
                key = os.environ.get("PAGESPEED_API_KEY")
                if key:
                    raw = raw.replace(key, "[REDACTED]").replace(json.dumps(key)[1:-1], "[REDACTED]")
                (args.output_dir / f"{label}.raw.json").write_text(raw + "\n", encoding="utf-8")
                result = summarize(json.loads(raw), strategy)
            except (OSError, ValueError, TypeError, AttributeError) as exc:
                # Avoid leaking file contents, target query values or provider secrets.
                result = {"status": "error", "strategy": strategy,
                          "error": "Measurement unavailable. Check input, network, quota and API-key configuration; inspect saved evidence if present."}
                if str(exc).startswith(("PageSpeed HTTP ", "PageSpeed network ", "PageSpeed response exceeded ")):
                    result["error"] = str(exc)
            results.append(result)
        summary = {"collected_at": datetime.now(timezone.utc).isoformat(), "source": str(args.input) if args.input else "PageSpeed Insights",
                   "runs": results}
        (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(args.output_dir / "summary.json")
        return 1 if any(r["status"] == "error" for r in results) else 0
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
