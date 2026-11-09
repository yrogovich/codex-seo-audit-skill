#!/usr/bin/env python3
"""Probe one URL and its origin: redirects, headers, robots.txt, sitemaps, host variants and missing-page behavior.

Read-only and standard library only. Output is evidence and candidate observations for the auditor to judge;
it assigns no severity and does not establish indexing."""

import argparse
import json
from pathlib import Path
import secrets
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as common  # noqa: E402

# Convenience list for robots matching only. What each token governs must be verified in the vendor's own
# documentation (references/sources.md); this script reports rule matching, not policy.
DEFAULT_AGENTS = ["*", "Googlebot", "Bingbot", "GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot",
                  "PerplexityBot", "Google-Extended", "Applebot-Extended", "CCBot", common.ROBOTS_TOKEN]
MAIN_TYPES = ("text/", "application/xhtml+xml", "application/xml")
KEEP_RAW = 2 * 1024 * 1024


def trimmed(result):
    """Fetch result without the body, for JSON output."""
    keep = ("requested_url", "final_url", "status", "reason", "headers", "redirect_chain", "redirect_to", "stopped",
            "body_truncated", "content_type", "ip", "elapsed_ms", "error", "error_detail")
    out = {key: result[key] for key in keep}
    out["body_bytes"] = len(result["body"])
    return out


def path_of(url):
    parts = urlsplit(url)
    return (parts.path or "/") + ("?" + parts.query if parts.query else "")


def probe(url, client, agents, site_checks, out_dir, allow_local):
    observations = []

    def note(code, detail):
        observations.append({"code": code, "detail": detail})

    main = client(url, read_types=MAIN_TYPES)
    report = {"tool": "probe.py", "user_agent": client.user_agent, "fetched_at": common.now_iso(), "target": url,
              "fetch": trimmed(main), "limitations": [
                  "Read-only observation from one network location and user agent; not Google's view.",
                  "Robots matching is reported per token; what a token controls must be verified in vendor documentation.",
                  "Candidate observations are leads to verify, not findings; no severity is assigned."]}
    if main["body"] and (main["content_type"] or "").lower().startswith(("text/html", "application/xhtml")):
        (out_dir / "main.html").write_bytes(main["body"])
        report["fetch"]["body_file"] = "main.html"
    if main["error"]:
        note("fetch.error", main["error"])
    elif main["status"] != 200:
        note("fetch.non_200", "HTTP %s at %s" % (main["status"], main["final_url"]))
    chain = main["redirect_chain"]
    if len(chain) > 2:
        note("redirect.long_chain", "%d hops: %s" % (len(chain), " -> ".join([c["url"] for c in chain] + [main["final_url"]])))
    if any(c["status"] in (302, 307) for c in chain):
        note("redirect.temporary_in_chain", [c["status"] for c in chain])
    if main["stopped"]:
        note("redirect.stopped", main["stopped"])
    if main["status"] and urlsplit(main["final_url"]).scheme == "http" and urlsplit(url).scheme == "https":
        note("fetch.final_not_https", main["final_url"])
    if "noindex" in main["headers"].get("x-robots-tag", "").lower():
        note("headers.noindex", main["headers"]["x-robots-tag"])
    if main["error"] == "blocked-target" or not main["status"]:
        report["observations"] = observations
        report["request_count"] = client.requests
        return report

    final = main["final_url"]
    origin = common.origin_of(final)
    hostname = urlsplit(final).hostname
    local = common.host_port(final) in client.allow_local
    if site_checks:
        robots = common.fetch_robots(origin, client)
        raw = robots.pop("raw")
        report["robots"] = {k: v for k, v in robots.items() if k != "robots"}
        if raw:
            (out_dir / "robots.txt").write_bytes(raw[: common.ROBOTS_MAX_BYTES])
            report["robots"]["file"] = "robots.txt"
        rules = robots["robots"]
        if robots["status"] == "unreachable":
            note("robots.unreachable", {"http_status": robots["http_status"], "error": robots["error"]})
        elif robots["status"] == "not-found-allow-all":
            note("robots.missing_allow_all", "HTTP %s: no restrictions apply" % robots["http_status"])
        if robots["looks_like_html"]:
            note("robots.html_response", "robots.txt returned an HTML page")
        if robots["truncated"]:
            note("robots.over_size_limit", "robots.txt is larger than %d bytes; content beyond that may be ignored" % common.ROBOTS_MAX_BYTES)
        if rules is not None:
            target = path_of(final)
            access, blocked_root = [], []
            for agent in agents:
                allowed, pattern, group = rules.allowed(target, agent)
                root_allowed = rules.allowed("/", agent)[0]
                access.append({"agent": agent, "group": group, "target_allowed": allowed, "matched_rule": pattern, "root_allowed": root_allowed})
                if not root_allowed:
                    blocked_root.append(agent)
            report["robots"].update(target_path=target, agent_access=access, declared_sitemaps=rules.sitemaps,
                                    crawl_delay=rules.crawl_delay(), group_count=len(rules.groups))
            own = next(a for a in access if a["agent"] == common.ROBOTS_TOKEN)
            if not own["target_allowed"]:
                note("robots.blocks_target", {"agent": own["group"], "rule": own["matched_rule"], "path": target})
            if blocked_root:
                note("robots.agents_blocked_from_root", blocked_root)
            if not rules.sitemaps:
                note("robots.no_sitemap_declared", "No Sitemap: line; conventional locations were tried")
        records, entries = common.discover_sitemaps(origin, rules.sitemaps if rules else [], client, {hostname})
        sitemaps = []
        for number, record in enumerate(records, 1):
            body = record.pop("body")
            if body and len(body) <= KEEP_RAW:
                name = "sitemap-%02d.xml" % number
                (out_dir / name).write_bytes(body)
                record["file"] = name
            sitemaps.append(record)
            if record["skipped"] == "off-scope":
                note("sitemap.off_scope", record["url"])
            elif record["kind"] in ("html-not-sitemap", "invalid") or record["errors"] and record["kind"] not in (None, "unavailable"):
                note("sitemap.problem", {"url": record["url"], "kind": record["kind"], "errors": record["errors"]})
        found = [r for r in sitemaps if r["kind"] and r["kind"] not in ("unavailable", "html-not-sitemap", "invalid")]
        if not found:
            note("sitemap.none_found", "No parseable sitemap at declared or conventional locations")
        report["sitemaps"] = {"files": sitemaps, "total_urls": len(entries), "distinct_urls": len({e[0] for e in entries})}

        if not local:
            variants = []
            alternate = hostname[4:] if hostname.startswith("www.") else "www." + hostname
            for candidate in ("http://%s/" % hostname, "https://%s/" % hostname, "https://%s/" % alternate):
                got = client(candidate, read_types=())
                variants.append({"requested_url": candidate, "final_url": got["final_url"], "status": got["status"],
                                 "redirect_statuses": [c["status"] for c in got["redirect_chain"]], "error": got["error"], "stopped": got["stopped"]})
            report["variants"] = variants
            ends = {v["final_url"] for v in variants if v["status"] and v["status"] < 400}
            if len(ends) > 1:
                note("variants.divergent_final_urls", sorted(ends))
        missing = client(origin + "/seo-audit-404-check-" + secrets.token_hex(6), read_types=())
        report["missing_page"] = {"requested_url": missing["requested_url"], "final_url": missing["final_url"], "status": missing["status"],
                                  "redirect_statuses": [c["status"] for c in missing["redirect_chain"]], "error": missing["error"]}
        if missing["status"] == 200:
            note("missing_page.soft_404_candidate", "A nonexistent path returned HTTP 200")
        elif missing["redirect_chain"] and urlsplit(missing["final_url"]).path == "/":
            note("missing_page.redirects_to_home", missing["final_url"])
    report["observations"] = observations
    report["request_count"] = client.requests
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--output-dir", type=Path, required=True, help="New evidence directory; never overwritten")
    parser.add_argument("--allow-local", action="append", default=[], metavar="ORIGIN",
                        help="Explicitly in-scope local origin, e.g. http://localhost:3000 (local-project audits only)")
    parser.add_argument("--agent", action="append", default=[], help="Extra robots.txt user-agent token to test")
    parser.add_argument("--user-agent", default=common.USER_AGENT)
    parser.add_argument("--no-site-checks", action="store_true", help="Only fetch the URL; skip robots, sitemaps, variants and 404 test")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds between requests to a host (default 1; minimum 0.2)")
    args = parser.parse_args()
    url = common.normalize_url(args.url)
    if not url:
        parser.error("Provide an absolute http(s) URL without credentials.")
    if not 1 <= args.timeout <= 120 or args.delay < 0.2:
        parser.error("--timeout must be 1-120 seconds and --delay at least 0.2.")
    try:
        allow_local = frozenset(common.local_scope(o) for o in args.allow_local)
    except ValueError as exc:
        parser.error(str(exc))
    if args.output_dir.exists():
        print("Error: output directory already exists; choose a fresh evidence directory.", file=sys.stderr)
        return 1
    args.output_dir.mkdir(parents=True)
    client = common.Client(args.delay, args.timeout, args.user_agent, allow_local)
    agents = list(dict.fromkeys(DEFAULT_AGENTS + args.agent))
    report = probe(url, client, agents, not args.no_site_checks, args.output_dir, allow_local)
    report["local_exception"] = sorted("%s:%s" % scope for scope in allow_local) or None
    (args.output_dir / "probe.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(args.output_dir / "probe.json")
    return 1 if report["fetch"]["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
