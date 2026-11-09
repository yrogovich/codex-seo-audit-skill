#!/usr/bin/env python3
"""Collect real-user Core Web Vitals from the Chrome UX Report (CrUX) API, with collection dates; standard library only.

Field data is kept separate from lab data: URL and origin results are never substituted for one another, and
missing data is reported as no-data (unknown), never as a pass."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pagespeed_check import NoRedirect, number, public_url  # noqa: E402

CURRENT = "https://chromeuxreport.googleapis.com/v1/records:queryRecord"
HISTORY = "https://chromeuxreport.googleapis.com/v1/records:queryHistoryRecord"
MAX_BYTES = 8 * 1024 * 1024
# name: (label, unit, good threshold, poor threshold). Verify against web.dev/articles/vitals at audit time.
METRICS = {
    "largest_contentful_paint": ("LCP", "ms", 2500, 4000),
    "interaction_to_next_paint": ("INP", "ms", 200, 500),
    "cumulative_layout_shift": ("CLS", "", 0.1, 0.25),
    "first_contentful_paint": ("FCP", "ms", 1800, 3000),
    "experimental_time_to_first_byte": ("TTFB", "ms", 800, 1800),
}
CORE = ("LCP", "INP", "CLS")
FORM_FACTORS = {"phone": "PHONE", "desktop": "DESKTOP", "tablet": "TABLET", "all": None}


class CruxError(ValueError):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def post(endpoint, body, key, timeout):
    request = Request(endpoint, data=json.dumps(body).encode(), method="POST",
                      headers={"Content-Type": "application/json", "Accept": "application/json", "X-Goog-Api-Key": key,
                               "User-Agent": "codex-seo-audit/1.0"})
    try:
        with build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            payload = response.read(MAX_BYTES + 1)
        if len(payload) > MAX_BYTES:
            raise CruxError("CrUX response exceeded 8 MiB; no complete report saved.")
        return json.loads(payload)
    except HTTPError as exc:  # Never echo the request, key or provider error body.
        exc.close()
        hint = {400: " Check the URL/origin format.", 403: " Check that the Chrome UX Report API is enabled for this key.", 429: " Quota reached; retry later."}.get(exc.code, "")
        raise CruxError(f"CrUX HTTP {exc.code}.{hint}", exc.code) from None
    except (URLError, TimeoutError, OSError):
        raise CruxError("CrUX network request failed or timed out; retry later.") from None


def date_text(value):
    try:
        return "%04d-%02d-%02d" % (value["year"], value["month"], value["day"])
    except (KeyError, TypeError):
        return None


def as_number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if number(result) else None


def rate(label, value):
    _, _, good, poor = next(m for m in METRICS.values() if m[0] == label)
    return None if value is None else "good" if value <= good else "poor" if value > poor else "needs-improvement"


def summarize_current(response):
    record = response.get("record") or {}
    period = record.get("collectionPeriod") or {}
    metrics = {}
    for name, (label, unit, _good, _poor) in METRICS.items():
        data = (record.get("metrics") or {}).get(name)
        if not isinstance(data, dict):
            continue
        p75 = as_number((data.get("percentiles") or {}).get("p75"))
        densities = [as_number(b.get("density")) for b in data.get("histogram") or [] if isinstance(b, dict)]
        entry = {"p75": p75, "unit": unit, "rating": rate(label, p75)}
        if len(densities) == 3 and None not in densities:
            entry["distribution"] = dict(zip(("good", "needs_improvement", "poor"), densities))
        metrics[label] = entry
    present = [metrics[c]["rating"] for c in CORE if c in metrics and metrics[c]["rating"]]
    assessment = ("failed" if any(r != "good" for r in present) else "passed" if len(present) == len(CORE) else "incomplete")
    return {"status": "measured", "collection_period": {"first_date": date_text(period.get("firstDate")), "last_date": date_text(period.get("lastDate"))},
            "metrics": metrics, "core_web_vitals": assessment, "normalization": response.get("urlNormalizationDetails")}


def summarize_history(response):
    record = response.get("record") or {}
    periods = [{"first_date": date_text(p.get("firstDate")), "last_date": date_text(p.get("lastDate"))} for p in record.get("collectionPeriods") or [] if isinstance(p, dict)]
    series = {}
    for name, (label, unit, _good, _poor) in METRICS.items():
        data = (record.get("metrics") or {}).get(name)
        if not isinstance(data, dict):
            continue
        values = [as_number(v) for v in (data.get("percentilesTimeseries") or {}).get("p75s") or []]
        known = [v for v in values if v is not None]
        series[label] = {"unit": unit, "p75_series": values, "periods_with_data": len(known),
                         "earliest": known[0] if known else None, "latest": known[-1] if known else None, "latest_rating": rate(label, known[-1]) if known else None}
    return {"status": "measured", "periods": periods, "metrics": series}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", help="Public page URL (URL-level field data)")
    parser.add_argument("--origin", help="Public origin, e.g. https://example.com (origin-level field data)")
    parser.add_argument("--also-origin", action="store_true", help="Also query the origin of the URL")
    parser.add_argument("--form-factor", action="append", choices=sorted(FORM_FACTORS), help="phone (default), desktop, tablet or all (no device filter); repeatable")
    parser.add_argument("--history", action="store_true", help="Also fetch the weekly p75 history")
    parser.add_argument("--history-periods", type=int, default=25, help="History periods, 1-40 (default 25)")
    parser.add_argument("--output-dir", type=Path, required=True, help="New evidence directory; never overwritten")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()
    if not (args.url or args.origin):
        parser.error("Provide a page URL and/or --origin.")
    if not 1 <= args.history_periods <= 40 or not 1 <= args.timeout <= 120:
        parser.error("--history-periods must be 1-40 and --timeout 1-120.")
    targets = []
    if args.url:
        targets.append(("url", args.url))
        if args.also_origin:
            parts = urlsplit(args.url)
            targets.append(("origin", "%s://%s" % (parts.scheme, parts.netloc)))
    if args.origin:
        targets.append(("origin", args.origin.rstrip("/")))
    key = os.environ.get("CRUX_API_KEY") or os.environ.get("PAGESPEED_API_KEY")
    try:
        if not key:
            raise ValueError("Set CRUX_API_KEY (or PAGESPEED_API_KEY for a key with the Chrome UX Report API enabled) in the environment.")
        if args.output_dir.exists():
            raise ValueError("Output directory already exists; choose a fresh evidence directory.")
        for _kind, value in dict.fromkeys(targets):
            public_url(value)
        args.output_dir.mkdir(parents=True)
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    results = []
    for factor_name in dict.fromkeys(args.form_factor or ["phone"]):
        for kind, value in dict.fromkeys(targets):
            for mode, endpoint in (("current", CURRENT), ("history", HISTORY)):
                if mode == "history" and not args.history:
                    continue
                body = {kind: value}
                if FORM_FACTORS[factor_name]:
                    body["formFactor"] = FORM_FACTORS[factor_name]
                if mode == "history":
                    body["collectionPeriodCount"] = args.history_periods
                entry = {"target": kind, "target_value": value, "form_factor": FORM_FACTORS[factor_name] or "ALL", "kind": mode}
                try:
                    response = post(endpoint, body, key, args.timeout)
                    raw = json.dumps(response, indent=2, ensure_ascii=False, allow_nan=False).replace(key, "[REDACTED]")
                    name = "%s-%s-%s.raw.json" % (mode, kind, factor_name)
                    (args.output_dir / name).write_text(raw + "\n", encoding="utf-8")
                    entry.update((summarize_history if mode == "history" else summarize_current)(response), raw_file=name)
                except CruxError as exc:
                    entry.update(status="no-data" if exc.code == 404 else "error", error=str(exc))
                    if exc.code == 404:
                        entry["error"] = "No CrUX data for this target and device: unknown, not a pass."
                except (ValueError, TypeError, AttributeError):
                    entry.update(status="error", error="Response could not be read; inspect saved evidence if present.")
                results.append(entry)
    summary = {"collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": "Chrome UX Report API", "results": results,
               "thresholds": {label: {"good_max": good, "poor_above": poor, "unit": unit} for label, unit, good, poor in METRICS.values()},
               "limitations": ["Thresholds are the values documented at web.dev/articles/vitals when this script was written; verify them at audit time.",
                               "CrUX covers Chrome users who opted in; low-traffic pages and origins often have no data, which is unknown and not a pass.",
                               "URL-level and origin-level results answer different questions and must not substitute for each other.",
                               "Field p75 values describe past visitors during the collection period; they say nothing about rankings or indexing.",
                               "Response fields follow the CrUX API documentation and were checked against fixtures, not live responses."]}
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(args.output_dir / "summary.json")
    return 1 if any(r["status"] == "error" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
