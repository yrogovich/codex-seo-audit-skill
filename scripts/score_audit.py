#!/usr/bin/env python3
"""Compute a transparent 0-100 checklist score from collected evidence; standard library only.

Only deterministic checks from the published rubric (references/score-rubric.json) are scored, from analyze_crawl,
probe, PageSpeed and CrUX output. Unmeasured and not-applicable checks are excluded, never scored as passes, and the
measured coverage always accompanies the score. It is an internal checklist metric, not a Google ranking predictor."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
from urllib.parse import urlsplit

RUBRIC = Path(__file__).resolve().parents[1] / "references" / "score-rubric.json"
LABEL = "Internal checklist metric, not a Google ranking predictor."
SOURCES = {"analysis", "probe", "psi", "crux"}
TRACKS = {"technical": "Technical", "content": "Content"}
BASES = {"requirement", "guidance", "hygiene"}
PARSEABLE = {"urlset", "sitemapindex", "text", "rss", "feed"}
NOINDEX_SHARE_BLOCKER = 0.5  # operational: most crawled pages carry noindex


class Skip(Exception):
    def __init__(self, status, reason):
        super().__init__(reason)
        self.status, self.reason = status, reason


def measured(score, **detail):
    return {"status": "measured", "score": max(0.0, min(1.0, score)), "reason": None, "detail": detail}


def not_measured(reason):
    return {"status": "not-measured", "score": None, "reason": reason, "detail": {}}


def not_applicable(reason):
    return {"status": "not-applicable", "score": None, "reason": reason, "detail": {}}


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError("%s is missing or not valid JSON." % Path(path).name) from None


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# --- rubric ---------------------------------------------------------------------------------------------------------

def load_rubric(path):
    raw = Path(path).read_bytes()
    try:
        rubric = json.loads(raw)
    except ValueError:
        raise ValueError("The rubric is not valid JSON.") from None
    problems, seen = [], set()
    if not isinstance(rubric.get("version"), int) or rubric["version"] < 1:
        problems.append("version must be a positive integer")
    areas = rubric.get("areas")
    if not isinstance(areas, dict) or not areas:
        problems.append("areas must be a non-empty object")
        areas = {}
    checks = rubric.get("checks")
    if not isinstance(checks, list) or not checks:
        problems.append("checks must be a non-empty array")
        checks = []
    for spec in checks:
        name = spec.get("id") if isinstance(spec, dict) else None
        if not isinstance(name, str) or not name or name in seen:
            problems.append("check id missing or duplicated: %r" % (name,))
            continue
        seen.add(name)
        if spec.get("area") not in areas:
            problems.append("%s: unknown area" % name)
        if not isinstance(spec.get("weight"), int) or isinstance(spec.get("weight"), bool) or not 1 <= spec["weight"] <= 5:
            problems.append("%s: weight must be an integer 1-5" % name)
        if not isinstance(spec.get("fix"), str) or not spec["fix"].strip():
            problems.append("%s: needs a short plain-language fix hint" % name)
        if spec.get("track") not in TRACKS:
            problems.append("%s: track must be technical or content" % name)
        if spec.get("basis") not in BASES:
            problems.append("%s: basis must be requirement, guidance or hygiene" % name)
        elif spec["basis"] != "hygiene" and not str(spec.get("google") or "").startswith("https://"):
            problems.append("%s: a requirement or guidance check needs a Google https link" % name)
        if spec.get("sensitivity") is not None and (not number(spec["sensitivity"]) or spec["sensitivity"] < 0):
            problems.append("%s: sensitivity must be a non-negative number" % name)
        source = spec.get("source")
        if source not in SOURCES:
            problems.append("%s: source must be one of %s" % (name, ", ".join(sorted(SOURCES))))
        elif source == "probe" and spec.get("test") not in PROBE_TESTS:
            problems.append("%s: unknown probe test" % name)
        elif source == "crux" and (spec.get("target") not in ("url", "origin") or not spec.get("form_factor") or not spec.get("metrics")):
            problems.append("%s: crux checks need target, form_factor and metrics" % name)
        elif source == "psi" and not (spec.get("metric") and spec.get("strategy") and number(spec.get("good")) and number(spec.get("poor")) and spec["good"] < spec["poor"]):
            problems.append("%s: psi checks need metric, strategy and good < poor" % name)
    if problems:
        raise ValueError("Invalid rubric: " + "; ".join(problems) + ".")
    rubric["sha256"] = hashlib.sha256(raw).hexdigest()
    return rubric


# --- evaluators -----------------------------------------------------------------------------------------------------

class Context:
    def __init__(self, analysis=None, probe=None, psi=(), crux=()):
        self.analysis, self.probe, self.psi = analysis, probe, list(psi)
        self.crux = [row for summary in crux for row in summary.get("results", [])]
        self.run = {c["check"]: c for c in (analysis or {}).get("checks_run", [])}
        self.complete = bool(((analysis or {}).get("scope") or {}).get("complete_within_scope"))


def eval_analysis(spec, ctx):
    if ctx.analysis is None:
        return not_measured("no crawl analysis supplied")
    entry = ctx.run.get(spec["id"])
    if entry is None:
        if spec["id"].startswith("sitemap.") and "sitemap.*" in ctx.run:
            return not_measured("no sitemap URLs were available to the crawl")
        return not_measured("this check is missing from the analysis (re-run analyze_crawl.py)")
    if entry.get("count") is None:
        return not_measured("the check could not run")
    if spec.get("requires_complete_crawl") and not ctx.complete:
        return not_measured("the crawl stopped early; a page may look unlinked only because its linking page was never fetched")
    denominator = entry.get("denominator")
    if denominator is None:
        return not_measured("the analysis has no denominator for this check (re-run analyze_crawl.py)")
    if denominator == 0:
        return not_applicable("no applicable items")
    ratio = min(1.0, entry["count"] / denominator)
    return measured(1.0 - spec.get("sensitivity", 1) * ratio, affected=entry["count"], denominator=denominator, unit=entry.get("unit"), ratio=round(ratio, 4))


def probe_main_fetch_ok(p):
    fetch = p["fetch"]
    return (1.0 if fetch.get("status") == 200 and not fetch.get("error") else 0.0), {"status": fetch.get("status"), "error": fetch.get("error")}


def probe_robots_reachable(p):
    robots = p.get("robots")
    if not robots:
        raise Skip("not-measured", "the probe did not check robots.txt")
    return (0.0 if robots["status"] == "unreachable" else 1.0), {"robots_status": robots["status"]}


def probe_googlebot_target_allowed(p):
    access = (p.get("robots") or {}).get("agent_access")
    entry = next((a for a in access or [] if a["agent"] == "Googlebot"), None)
    if entry is None:
        raise Skip("not-measured", "robots matching for Googlebot is not in the probe")
    return (1.0 if entry["target_allowed"] else 0.0), {"path": p["robots"].get("target_path"), "rule": entry["matched_rule"]}


def probe_https_final(p):
    if p.get("local_exception"):
        raise Skip("not-applicable", "local project origin")
    scheme = urlsplit(p["fetch"]["final_url"]).scheme
    return (1.0 if scheme == "https" else 0.0), {"final_scheme": scheme}


def probe_redirect_chain_short(p):
    hops = len(p["fetch"]["redirect_chain"])
    return (1.0 if hops <= 2 else 0.0), {"hops": hops}


def probe_host_variants_consistent(p):
    variants = p.get("variants")
    if variants is None:
        raise Skip("not-measured", "host variants were not checked (local origin or --no-site-checks)")
    ends = {v["final_url"] for v in variants if v["status"] and v["status"] < 400}
    if not ends:
        raise Skip("not-measured", "no host variant responded")
    return (1.0 if len(ends) == 1 else 0.0), {"final_urls": sorted(ends)}


def probe_missing_page_status(p):
    missing = p.get("missing_page")
    if not missing or missing.get("error") or missing.get("status") is None:
        raise Skip("not-measured", "the missing-page test did not complete")
    codes = {o["code"] for o in p.get("observations", [])}
    bad = missing["status"] == 200 or "missing_page.redirects_to_home" in codes
    return (0.0 if bad else 1.0), {"status": missing["status"]}


def parseable_sitemaps(p):
    sitemaps = p.get("sitemaps")
    if not sitemaps:
        raise Skip("not-measured", "the probe did not check sitemaps")
    return [f for f in sitemaps["files"] if f.get("kind") in PARSEABLE]


def probe_sitemap_found(p):
    found = parseable_sitemaps(p)
    return (1.0 if found else 0.0), {"parseable_sitemaps": len(found)}


def probe_sitemap_valid(p):
    found = parseable_sitemaps(p)
    if not found:
        raise Skip("not-applicable", "no sitemap to validate")
    problems = [o for o in p.get("observations", []) if o["code"] == "sitemap.problem"]
    return (0.0 if problems else 1.0), {"problems": len(problems)}


PROBE_TESTS = {name[len("probe_"):]: fn for name, fn in list(globals().items()) if name.startswith("probe_") and callable(fn)}


def eval_probe(spec, ctx):
    if ctx.probe is None:
        return not_measured("no probe output supplied")
    try:
        score, detail = PROBE_TESTS[spec["test"]](ctx.probe)
    except Skip as skip:
        return not_measured(skip.reason) if skip.status == "not-measured" else not_applicable(skip.reason)
    except (KeyError, TypeError):
        return not_measured("the probe output lacks the fields this check needs")
    return measured(score, **detail)


RATING_VALUE = {"good": 1.0, "needs-improvement": 0.5, "poor": 0.0}


def eval_crux(spec, ctx):
    rows = [r for r in ctx.crux if r.get("kind") == "current" and r.get("target") == spec["target"] and r.get("form_factor") == spec["form_factor"]]
    if not rows:
        return not_measured("no CrUX result for this target and device was supplied")
    row = rows[0]
    if row.get("status") == "no-data":
        return not_measured("CrUX has no data for this target, which is unknown and not a pass")
    if row.get("status") != "measured":
        return not_measured("the CrUX request failed")
    metrics = row.get("metrics") or {}
    ratings = {m: metrics[m]["rating"] for m in spec["metrics"] if m in metrics and metrics[m].get("rating") in RATING_VALUE}
    if not ratings:
        return not_measured("the CrUX result has none of the required metrics")
    return measured(sum(RATING_VALUE[r] for r in ratings.values()) / len(ratings), ratings=ratings,
                    missing=[m for m in spec["metrics"] if m not in ratings], collection_period=row.get("collection_period"))


def eval_psi(spec, ctx):
    values = []
    for summary in ctx.psi:
        for run in summary.get("runs", []):
            value = ((run.get("lab_metrics") or {}).get(spec["metric"]) or {}).get("value")
            if run.get("status") == "measured" and run.get("strategy") == spec["strategy"] and number(value):
                values.append(value)
    if not values:
        return not_measured("no %s lab measurement was supplied" % spec["strategy"])
    ratings = ["good" if v <= spec["good"] else "poor" if v > spec["poor"] else "needs-improvement" for v in values]
    return measured(sum(RATING_VALUE[r] for r in ratings) / len(ratings), pages=len(values), worst=max(values), ratings={r: ratings.count(r) for r in sorted(set(ratings))})


EVALUATORS = {"analysis": eval_analysis, "probe": eval_probe, "crux": eval_crux, "psi": eval_psi}


# --- blockers -------------------------------------------------------------------------------------------------------

def find_blockers(ctx):
    """Conditions that outweigh any number. They are flagged beside the score; the score is never capped."""
    found = []

    def flag(name, description, **evidence):
        found.append({"id": name, "description": description, "evidence": evidence})

    probe = ctx.probe
    if probe:
        fetch = probe["fetch"]
        if fetch.get("error") or not fetch.get("status") or fetch["status"] >= 400:
            flag("main-fetch-failed", "The audited URL did not return a successful response.", status=fetch.get("status"), error=fetch.get("error"))
        robots = probe.get("robots") or {}
        if robots.get("status") == "unreachable":
            flag("robots-unreachable", "robots.txt was unreachable, which compliant crawlers treat as no permission.", http_status=robots.get("http_status"))
        if any(a["agent"] == "*" and not a["root_allowed"] for a in robots.get("agent_access", [])):
            flag("robots-disallows-everything", "robots.txt disallows the whole site for all crawlers.")
        if "noindex" in (fetch.get("headers") or {}).get("x-robots-tag", "").lower():
            flag("main-url-noindex-header", "The audited URL sends a noindex X-Robots-Tag.")
    if ctx.analysis:
        candidates = {c["check"]: c for c in ctx.analysis.get("candidates", [])}
        start = (ctx.analysis.get("scope") or {}).get("start_url")
        if start and start in (candidates.get("index.noindex") or {}).get("urls", []):
            flag("start-url-noindex", "The start URL carries a noindex directive.", url=start)
        entry = ctx.run.get("index.noindex")
        if entry and entry.get("denominator") and entry["count"] / entry["denominator"] >= NOINDEX_SHARE_BLOCKER:
            flag("most-pages-noindex", "At least half of the fetched pages carry noindex.", affected=entry["count"], denominator=entry["denominator"])
    return found


# --- scoring --------------------------------------------------------------------------------------------------------

def aggregate(items):
    done = [c for c in items if c["status"] == "measured"]
    pending = [c for c in items if c["status"] == "not-measured"]
    weight = sum(c["weight"] for c in done)
    total = weight + sum(c["weight"] for c in pending)
    return {"score": round(100 * sum(c["weight"] * c["score"] for c in done) / weight, 1) if weight else None,
            "measured_weight": weight, "total_weight": total, "coverage": round(weight / total, 4) if total else None,
            "checks_measured": len(done), "checks_applicable": len(done) + len(pending)}


ACTION_LIMIT = 10


def build_actions(checks, overall, specs):
    """Checks that lost points, biggest first. points_to_gain is roughly how much the overall score would rise
    if that check fully passed and nothing else changed."""
    total = overall["measured_weight"]
    items = []
    for c in checks:
        if c["status"] == "measured" and c["score"] < 1 and total:
            gain = round(100 * c["weight"] * (1 - c["score"]) / total, 1)
            if gain >= 0.1:
                detail, spec = c["detail"], specs[c["id"]]
                items.append({"id": c["id"], "area": c["area"], "track": spec["track"], "points_to_gain": gain, "fix": spec["fix"],
                              "basis": spec["basis"], "google": spec.get("google"),
                              "affected": detail.get("affected"), "total": detail.get("denominator"), "unit": detail.get("unit")})
    return sorted(items, key=lambda a: (-a["points_to_gain"], a["id"]))[:ACTION_LIMIT]


def build_report(rubric, ctx, inputs):
    checks = []
    for spec in rubric["checks"]:
        checks.append({"id": spec["id"], "area": spec["area"], "track": spec["track"], "weight": spec["weight"], **EVALUATORS[spec["source"]](spec, ctx)})
    overall = aggregate(checks)
    areas = [dict(area=key, label=label, **aggregate([c for c in checks if c["area"] == key])) for key, label in rubric["areas"].items()]
    tracks = [dict(track=key, label=label, **aggregate([c for c in checks if c["track"] == key])) for key, label in TRACKS.items()]
    unmeasured = {}
    for c in checks:
        if c["status"] != "measured":
            unmeasured.setdefault("%s: %s" % (c["status"], c["reason"]), []).append(c["id"])
    ids = sorted(c["id"] for c in checks if c["status"] == "measured")
    scope = (ctx.analysis or {}).get("scope") or {}
    crawl = None
    if ctx.analysis:
        crawl = {"complete": ctx.complete, "stop_reason": scope.get("stop_reason"), "discovered": scope.get("discovered"), "html_pages": scope.get("html_pages"),
                 "note": "the whole crawl scope" if ctx.complete else "a partial crawl: the score describes the fetched sample (%s of %s discovered URLs fetched)" % (scope.get("fetched_rows"), scope.get("discovered"))}
    return {"tool": "score_audit.py", "scored_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "label": LABEL,
            "rubric": {"version": rubric["version"], "sha256": rubric["sha256"], "formula": rubric["score_formula"]},
            "overall": overall, "tracks": tracks, "areas": areas, "actions": build_actions(checks, overall, {s["id"]: s for s in rubric["checks"]}),
            "blockers": find_blockers(ctx), "crawl": crawl, "inputs": inputs,
            "comparison_key": hashlib.sha256(("%d|%s" % (rubric["version"], ",".join(ids))).encode()).hexdigest()[:16],
            "checks": checks, "not_measured_groups": unmeasured, "unscored_checks": rubric.get("unscored_checks", {}), "not_covered": rubric.get("not_covered", [])}


def compare(current, baseline):
    """Score change on the checks measured in both runs, so differing coverage cannot masquerade as improvement."""
    if baseline["rubric"]["version"] != current["rubric"]["version"]:
        raise ValueError("The baseline used rubric version %s and this run %s; the scores are not comparable." % (baseline["rubric"]["version"], current["rubric"]["version"]))
    if baseline["rubric"]["sha256"] != current["rubric"]["sha256"]:
        raise ValueError("The rubric changed without a version bump; the scores are not comparable.")
    now = {c["id"]: c for c in current["checks"] if c["status"] == "measured"}
    before = {c["id"]: c for c in baseline["checks"] if c["status"] == "measured"}
    common = sorted(set(now) & set(before))
    if not common:
        return {"comparable": False, "reason": "No measured check is common to both runs."}
    weight = sum(now[i]["weight"] for i in common)

    def total(source):
        return round(100 * sum(now[i]["weight"] * source[i]["score"] for i in common) / weight, 1)
    changed = [{"id": i, "baseline": round(before[i]["score"], 3), "current": round(now[i]["score"], 3)} for i in common if abs(now[i]["score"] - before[i]["score"]) >= 0.005]
    return {"comparable": True, "same_measured_checks": set(now) == set(before), "common_checks": len(common), "only_in_baseline": sorted(set(before) - set(now)),
            "only_in_current": sorted(set(now) - set(before)), "baseline_score_on_common_checks": total(before), "current_score_on_common_checks": total(now),
            "delta": round(total(now) - total(before), 1), "changed_checks": changed[:25]}


def where(action):
    return "%s of %s %s" % (action["affected"], action["total"], action["unit"]) if action["affected"] is not None and action["total"] else "see score.json"


def summary_text(report):
    overall = report["overall"]
    if overall["score"] is None:
        return "No score: no check could be measured from the evidence you supplied."
    lines = ["Score: %s / 100  (checked %d%% of the checklist: %d of %d checks, rubric v%d)" % (
        overall["score"], round(overall["coverage"] * 100), overall["checks_measured"], overall["checks_applicable"], report["rubric"]["version"])]
    if report["crawl"] and not report["crawl"]["complete"]:
        lines.append("Note: " + report["crawl"]["note"])
    row = lambda a: "  %-34s %s" % (a["label"], "not checked" if a["score"] is None else "%5.1f  (%d of %d checks)" % (a["score"], a["checks_measured"], a["checks_applicable"]))  # noqa: E731
    lines += [row(t) for t in report["tracks"]] + ["  By area:"] + ["  " + row(a) for a in report["areas"]]
    lines.append("Blockers: " + (", ".join(b["id"] for b in report["blockers"]) or "none flagged"))
    if report["actions"]:
        lines.append("Fix first (points the score would gain):")
        lines += ["  +%-4s [%s] %s  (%s: %s)" % (a["points_to_gain"], a["track"], a["fix"], a["id"], where(a)) for a in report["actions"][:5]]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, help="analysis.json from analyze_crawl.py")
    parser.add_argument("--probe", type=Path, help="probe.json from probe.py")
    parser.add_argument("--psi", type=Path, action="append", default=[], help="summary.json from pagespeed_check.py (repeatable)")
    parser.add_argument("--crux", type=Path, action="append", default=[], help="summary.json from crux_check.py (repeatable)")
    parser.add_argument("--rubric", type=Path, default=RUBRIC)
    parser.add_argument("--baseline", type=Path, help="Earlier score.json to compare on the checks both runs measured")
    parser.add_argument("--output", type=Path, required=True, help="New score.json; never overwritten")
    args = parser.parse_args()
    if not (args.analysis or args.probe or args.psi or args.crux):
        parser.error("Provide at least one of --analysis, --probe, --psi or --crux.")
    try:
        if args.output.exists():
            raise ValueError("Output file already exists; choose a fresh path.")
        rubric = load_rubric(args.rubric)
        named = [("analysis", args.analysis), ("probe", args.probe)] + [("psi", p) for p in args.psi] + [("crux", p) for p in args.crux]
        inputs = [{"kind": kind, "path": str(path), "sha256": digest(path)} for kind, path in named if path]
        ctx = Context(read_json(args.analysis) if args.analysis else None, read_json(args.probe) if args.probe else None,
                      [read_json(p) for p in args.psi], [read_json(p) for p in args.crux])
        report = build_report(rubric, ctx, inputs)
        if args.baseline:
            report["comparison"] = compare(report, read_json(args.baseline))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    except (OSError, ValueError, KeyError) as exc:
        print("Error: %s" % exc, file=sys.stderr)
        return 1
    print(args.output)
    print(summary_text(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
