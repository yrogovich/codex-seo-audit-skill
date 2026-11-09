#!/usr/bin/env python3
"""Collect PSI evidence or summarize saved PSI/Lighthouse JSON; standard library only."""

import argparse
from datetime import datetime, timezone
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import socket
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
MAX_BYTES = 32 * 1024 * 1024
MAX_BATCH = 20
ITEM_LIMIT = 10
TEXT_LIMIT = 300
METRICS = {
    "largest-contentful-paint": "LCP",
    "first-contentful-paint": "FCP",
    "cumulative-layout-shift": "CLS",
    "total-blocking-time": "TBT",
    "speed-index": "Speed Index",
    "server-response-time": "Server response time",
}
# Cells kept from Lighthouse detail tables; everything else stays in the raw report.
ITEM_KEYS = ("url", "href", "text", "label", "source", "message", "line", "index", "wastedBytes", "totalBytes",
             "wastedMs", "transferSize", "blockingTime", "mainThreadTime", "cacheLifetimeMs", "entity", "score",
             "phase", "timing", "percent", "total", "scripting", "scriptParseCompile", "group", "groupLabel")
# Informative audits are never "failed" but carry the evidence checks.md asks for. Classic and
# newer insight-style audit IDs are both listed; absent IDs are skipped.
DIAGNOSTICS = {
    "lcp_element": ("largest-contentful-paint-element", "lcp-breakdown-insight"),
    "layout_shifts": ("layout-shift-elements", "layout-shifts", "cls-culprits-insight"),
    "third_party": ("third-party-summary", "third-parties-insight"),
    "server_response": ("server-response-time",),
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


def clip(value):
    return value[:TEXT_LIMIT] if isinstance(value, str) else value


def scalar(value):
    """Reduce a Lighthouse table cell to a compact scalar or node description, else None."""
    if isinstance(value, dict):
        kind = value.get("type")
        if kind == "node":
            node = {k: clip(value[k]) for k in ("selector", "snippet", "nodeLabel") if value.get(k)}
            return node or None
        if kind == "source-location":
            return clip("%s:%s" % (value.get("url"), value.get("line"))) if value.get("url") else None
        if kind == "link":
            return clip(value.get("url") or value.get("text"))
        for key in ("value", "url", "text"):
            if key in value:
                return scalar(value[key])
        return None
    if isinstance(value, bool) or isinstance(value, str):
        return clip(value)
    return value if number(value) else None


def table_rows(details):
    """Rows of a Lighthouse details object, flattening nested lists of tables."""
    if not isinstance(details, dict):
        return []
    items = details.get("items")
    if not isinstance(items, list):
        return []
    if details.get("type") == "list":
        return [row for part in items for row in table_rows(part)]
    return [row for row in items if isinstance(row, dict)]


def compact_row(row):
    compact = {}
    for key, value in row.items():
        if key == "node" or key in ITEM_KEYS:
            cell = scalar(value)
            if cell not in (None, "", {}):
                compact[key] = cell
    return compact


def bounded_items(audit):
    """Top detail rows of an audit as bounded evidence; the raw report stays complete."""
    try:
        rows = table_rows(audit.get("details"))
        items = [row for row in (compact_row(r) for r in rows[:ITEM_LIMIT]) if row]
        return {"items": items, "items_total": len(rows)}
    except (AttributeError, TypeError, ValueError, KeyError):
        return {"items": [], "items_total": None, "items_error": "Audit details could not be read; inspect the raw report."}


def rating(score):
    """Lighthouse's published bands: 90-100 pass, 50-89 average, 0-49 fail."""
    return "pass" if score >= 0.9 else "average" if score >= 0.5 else "fail"


def diagnostics(audits):
    found = {}
    for name, audit_ids in DIAGNOSTICS.items():
        for audit_id in audit_ids:
            item = audits.get(audit_id)
            if isinstance(item, dict) and (item.get("details") or item.get("numericValue") is not None):
                entry = {"audit_id": audit_id, "title": item.get("title"), "display": item.get("displayValue"),
                         "numeric_value": item.get("numericValue"), "numeric_unit": item.get("numericUnit")}
                entry.update(bounded_items(item))
                found.setdefault(name, []).append(entry)
    return found


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
            details = item.get("details")
            entry = {"id": audit_id, "title": item.get("title"), "score": score, "rating": rating(score),
                     "display": item.get("displayValue"),
                     "metric_savings": item.get("metricSavings"),
                     "estimated_savings_ms": details.get("overallSavingsMs") if isinstance(details, dict) else None}
            entry.update(bounded_items(item))
            failed.append(entry)
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
        "diagnostics": diagnostics(audits),
        "limitations": ["Lab TBT is not field INP. Scores do not establish rankings or indexing.",
                         "Missing field data is unknown. Origin data does not establish URL performance.",
                         "PSI field data may be absent; use CrUX separately for collection dates and field coverage.",
                         "Failed audits are diagnostic candidates (Lighthouse score below 1), not automatic SEO findings; see each audit's rating.",
                         "Detail items are bounded excerpts (top %d rows, text clipped); the raw report holds complete lists." % ITEM_LIMIT]}


def measure(url, input_path, strategy, output_dir, timeout):
    """Collect (or import) measurements into a new directory; returns the summary dict."""
    output_dir.mkdir(parents=True, exist_ok=False)
    runs = [None] if input_path else (["mobile", "desktop"] if strategy == "both" else [strategy])
    results = []
    for run in runs:
        label = run or "imported"
        try:
            data = json.loads(input_path.read_text(encoding="utf-8")) if input_path else collect(url, run, timeout)
            # Retain error-bearing responses too, without exposing the API key.
            raw = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False)
            key = os.environ.get("PAGESPEED_API_KEY")
            if key:
                raw = raw.replace(key, "[REDACTED]").replace(json.dumps(key)[1:-1], "[REDACTED]")
            (output_dir / f"{label}.raw.json").write_text(raw + "\n", encoding="utf-8")
            result = summarize(json.loads(raw), run)
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            # Avoid leaking file contents, target query values or provider secrets.
            result = {"status": "error", "strategy": run,
                      "error": "Measurement unavailable. Check input, network, quota and API-key configuration; inspect saved evidence if present."}
            if str(exc).startswith(("PageSpeed HTTP ", "PageSpeed network ", "PageSpeed response exceeded ")):
                result["error"] = str(exc)
        results.append(result)
    summary = {"collected_at": datetime.now(timezone.utc).isoformat(),
               "source": str(input_path) if input_path else "PageSpeed Insights",
               "target_url": url, "runs": results}
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def read_urls(path):
    urls = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and line not in urls:
            urls.append(line)
    if not urls:
        raise ValueError("The URL list is empty.")
    if len(urls) > MAX_BATCH:
        raise ValueError(f"At most {MAX_BATCH} URLs per batch; split the list by template or priority.")
    return urls


def slug(url):
    parts = urlsplit(url)
    text = re.sub(r"[^a-z0-9]+", "-", ((parts.hostname or "") + parts.path).lower()).strip("-")
    return text[:60] or "page"


def has_error(summary):
    return any(r["status"] == "error" for r in summary["runs"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?")
    parser.add_argument("--input", type=Path, help="Saved PSI response or local Lighthouse JSON (offline)")
    parser.add_argument("--urls-file", type=Path, help=f"Text file of public URLs, one per line (max {MAX_BATCH}); measured sequentially")
    parser.add_argument("--strategy", choices=("mobile", "desktop", "both"), default="mobile")
    parser.add_argument("--output-dir", type=Path, required=True, help="New evidence directory; never overwritten")
    parser.add_argument("--timeout", type=int, default=120, help="Seconds per hosted run (1–300)")
    args = parser.parse_args()
    if sum(bool(x) for x in (args.url, args.input, args.urls_file)) != 1:
        parser.error("Provide exactly one of a public URL, --input or --urls-file.")
    if not 1 <= args.timeout <= 300:
        parser.error("--timeout must be between 1 and 300 seconds.")
    try:
        if args.output_dir.exists():
            raise ValueError("Output directory already exists; choose a fresh evidence directory.")
        if args.urls_file:
            urls = read_urls(args.urls_file)
            for target in urls:  # Validate every target before any hosted request is made.
                public_url(target)
            args.output_dir.mkdir(parents=True, exist_ok=False)
            entries, failed = [], False
            for number_, target in enumerate(urls, 1):
                folder = f"{number_:02d}-{slug(target)}"
                summary = measure(target, None, args.strategy, args.output_dir / folder, args.timeout)
                failed = failed or has_error(summary)
                entries.append({"url": target, "directory": folder,
                                "status": "error" if has_error(summary) else "measured",
                                "runs": [{"strategy": r.get("strategy"), "status": r["status"], "scores": r.get("scores")}
                                         for r in summary["runs"]]})
            index = {"collected_at": datetime.now(timezone.utc).isoformat(), "source": "PageSpeed Insights", "urls": entries}
            (args.output_dir / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(args.output_dir / "index.json")
            return 1 if failed else 0
        if args.url:
            public_url(args.url)
        summary = measure(args.url, args.input, args.strategy, args.output_dir, args.timeout)
        print(args.output_dir / "summary.json")
        return 1 if has_error(summary) else 0
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
