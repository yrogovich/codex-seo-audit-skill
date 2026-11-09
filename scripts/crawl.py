#!/usr/bin/env python3
"""Bounded, polite, read-only crawl: saves raw HTML and writes the URL inventory, link edges and per-page signals.

Standard library only. It honors robots.txt, never renders JavaScript, never submits forms, and stops on repeated
failures or denial. Output is evidence for the auditor (see analyze_crawl.py), not findings."""

import argparse
import csv
import heapq
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as common  # noqa: E402
import parse_html  # noqa: E402

ASSET_EXT = re.compile(r"\.(?:jpe?g|png|gif|webp|avif|svg|ico|bmp|tiff?|mp4|webm|mov|avi|mp3|wav|ogg|woff2?|ttf|otf|eot|css|js|mjs|map|json|"
                       r"xml|txt|pdf|docx?|xlsx?|pptx?|zip|gz|tar|rar|7z|dmg|exe|apk)$", re.I)
ACTION_URL = re.compile(r"(?i)log-?out|sign-?out|unsubscribe|add[-_]to[-_]cart|/cart(?:/|$|\?)|/checkout|wp-admin|wp-login")
PARAM_CAP = 20           # query variants kept per path, so filters and calendars cannot explode
MAX_RETRY_AFTER = 60     # seconds; a longer wait stops the crawl instead
STOP_AFTER = 5           # consecutive 5xx / denials / network failures
DIRECTIVES = {"noindex", "nofollow", "none", "noarchive", "nosnippet", "notranslate", "noimageindex", "indexifembedded"}
PLACEHOLDER = re.compile(r"^\s*(\[[A-Za-z][^\]]{2,}\]|\{\{.+\}\}|lorem ipsum.*)\s*$", re.I)
INVENTORY_COLUMNS = ["url", "final_url", "discovered_via", "template", "fetch_status", "http_status", "rendered",
                     "observed_indexability", "canonical", "evidence_ref", "notes"]


def path_query(url):
    parts = urlsplit(url)
    return (parts.path or "/") + ("?" + parts.query if parts.query else "")


def path_group(url):
    segments = [s for s in urlsplit(url).path.split("/") if s]
    if not segments:
        return "(home)"
    first = segments[0]
    return "(root-file)" if len(segments) == 1 and "." in first else first + "/*" if len(segments) > 1 else first


def x_robots_directives(value):
    """Directives from X-Robots-Tag by user-agent: {None: {...}} for generic, {'googlebot': {...}} for agent-specific."""
    found, agent = {}, None
    for part in (value or "").lower().split(","):
        part = part.strip()
        left, sep, right = part.partition(":")
        if sep and left.strip() not in DIRECTIVES and not left.strip().startswith(("max-", "unavailable_after")):
            agent, part = left.strip(), right.strip()
        if part:
            found.setdefault(agent, set()).add(part)
    return found


def link_header_canonical(value):
    for match in re.finditer(r"<([^>]+)>\s*;([^,]*)", value or ""):
        if re.search(r"""rel\s*=\s*["']?[^"';,]*\bcanonical\b""", match.group(2), re.I):
            return match.group(1)
    return None


def ld_nodes(value):
    if isinstance(value, list):
        for item in value:
            yield from ld_nodes(item)
    elif isinstance(value, dict):
        yield value
        if isinstance(value.get("@graph"), list):
            yield from ld_nodes(value["@graph"])


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def summarize_json_ld(blocks):
    types, missing, placeholders = [], 0, 0
    for block in blocks:
        if block.get("syntax_error"):
            continue
        for node in ld_nodes(block["value"]):
            kind = node.get("@type")
            if kind:
                types += kind if isinstance(kind, list) else [kind]
            elif "@graph" not in node and "@context" in node:
                missing += 1
        placeholders += any(PLACEHOLDER.match(s) for s in strings(block["value"]))
    return {"blocks": len(blocks), "syntax_errors": sum(1 for b in blocks if b.get("syntax_error")),
            "types": sorted({t for t in types if isinstance(t, str)}), "missing_type": missing, "placeholder_blocks": placeholders}


def summarize_page(url, headers, data):
    """Compact per-page SEO signals from parse_html output and response headers."""
    def meta(name):
        return [m.get("content") or "" for m in data["meta"] if (m.get("name") or "").lower() == name]
    robots_meta = sorted({t.strip().lower() for v in meta("robots") + meta("googlebot") for t in v.split(",") if t.strip()})
    header = headers.get("x-robots-tag", "")
    directives = x_robots_directives(header)
    header_tokens = sorted(set().union(*[d for a, d in directives.items() if a in (None, "googlebot", "*")] or [set()]))
    canonicals = [c for c in (common.normalize_url(c, url) if c else None for c in data.get("resolved_canonicals", [])) if c]
    header_canonical = link_header_canonical(headers.get("link"))
    images = data["images"]
    links = data["links"]
    return {
        "lang": data.get("language"), "titles": data["titles"], "meta_descriptions": meta("description"),
        "robots_meta": robots_meta, "x_robots_tag": header or None, "robots_header_tokens": header_tokens,
        "noindex_meta": bool({"noindex", "none"} & set(robots_meta)), "noindex_header": bool({"noindex", "none"} & set(header_tokens)),
        "canonicals": canonicals, "canonical_header": common.normalize_url(header_canonical, url) if header_canonical else None,
        "hreflang": [{"hreflang": h.get("hreflang"), "href": h.get("resolved_href")} for h in data["hreflang"]],
        "h1": [h["text"] for h in data["headings"] if h["level"] == 1], "heading_count": len(data["headings"]),
        "images": {"total": len(images), "missing_alt": sum(1 for i in images if i.get("alt") is None),
                   "empty_alt": sum(1 for i in images if i.get("alt") == ""),
                   "missing_dimensions": sum(1 for i in images if i.get("width") is None or i.get("height") is None)},
        "json_ld": summarize_json_ld(data["json_ld"]), "viewport": bool(meta("viewport")),
        "link_total": len(links), "link_empty_anchor": sum(1 for l in links if l.get("href") and not l["anchor_text"].strip() and not l.get("aria-label")),
        "visible_text": data["visible_text"], "rendering_hint": data["rendering_hint"]}


def indexability(status, is_html, page, url):
    """Directive-level observation, not an indexing claim: what a crawler can see that blocks or redirects."""
    if status is None:
        return ""
    if status >= 500:
        return "server-error"
    if status >= 400:
        return "client-error"
    if status >= 300:
        return "redirect"
    if not is_html:
        return "not-html"
    tokens = []
    if page["noindex_meta"]:
        tokens.append("noindex-meta")
    if page["noindex_header"]:
        tokens.append("noindex-header")
    canonical = (page["canonicals"] or [page["canonical_header"]])[0]
    if canonical and canonical != url:
        tokens.append("canonical-elsewhere")
    return ";".join(tokens) or "no-blocking-signal"


class Crawler:
    def __init__(self, start, out_dir, inventory, client, max_pages=100, max_requests=300, max_seconds=900, max_bytes=5 * 1024 * 1024,
                 seeds=(), allow_hosts=(), use_sitemap=True, max_sitemap_urls=5000, ignore_local_robots=False,
                 robots_token=common.ROBOTS_TOKEN):
        self.start, self.out_dir, self.inventory, self.client = start, out_dir, inventory, client
        self.max_pages, self.max_requests, self.max_seconds, self.max_bytes = max_pages, max_requests, max_seconds, max_bytes
        self.seeds, self.use_sitemap, self.max_sitemap_urls = list(seeds), use_sitemap, max_sitemap_urls
        self.ignore_local_robots, self.robots_token = ignore_local_robots, robots_token
        self.allowed_hosts = {urlsplit(start).hostname} | set(allow_hosts)
        client.allowed_hosts = self.allowed_hosts
        self.entries, self.order, self.heap, self.seq = {}, [], [], 0
        self.robots, self.sitemap_urls, self.sitemap_records, self.param_counts = {}, {}, [], {}
        self.pages = self.fetched = 0
        self.stop, self.scope_notes, self.streak = None, [], {"5xx": 0, "denied": 0, "failed": 0}
        self.crawl_delay = None
        self.local_robots_ignored = False
        self.start_final = start

    # --- frontier ----------------------------------------------------------------------------------------------
    def robots_for(self, url):
        origin = common.origin_of(url)
        if origin not in self.robots:
            self.robots[origin] = common.fetch_robots(origin, self.client)
            info = self.robots[origin]
            if info["raw"]:
                (self.out_dir / ("robots-%s.txt" % re.sub(r"[^a-z0-9]+", "-", origin.lower()).strip("-"))).write_bytes(info["raw"][: common.ROBOTS_MAX_BYTES])
            if info["robots"] and info["robots"].crawl_delay(self.robots_token):
                self.crawl_delay = max(self.crawl_delay or 0, info["robots"].crawl_delay(self.robots_token))
        return self.robots[origin]

    def robots_verdict(self, url):
        """(state, matched rule): None state means crawling is permitted."""
        info = self.robots_for(url)
        if info["status"] == "unreachable":
            return "skipped:robots-unreachable", None
        if info["robots"] is None:
            return None, None
        allowed, pattern, _ = info["robots"].allowed(path_query(url), self.robots_token)
        if not allowed and self.ignore_local_robots and common.host_port(url) in self.client.allow_local:
            self.local_robots_ignored = True
            return None, pattern
        return (None, None) if allowed else ("blocked-by-robots", pattern)

    def add(self, raw, via, depth, referrer=None, base=None, keep_off_scope=False):
        url = common.normalize_url(raw, base)
        if not url:
            return None
        entry = self.entries.get(url)
        if entry:
            entry["via"].add(via)
            if depth < entry["depth"]:
                entry["depth"] = depth
                if entry["state"] == "queued":
                    self.push(entry)
            return entry
        host = urlsplit(url).hostname
        if host not in self.allowed_hosts and not keep_off_scope:
            return None
        entry = self.new_entry(url, via, depth, referrer)
        parts = urlsplit(url)
        if host not in self.allowed_hosts:
            entry["state"] = "off-scope"
        elif ASSET_EXT.search(parts.path):
            entry["state"] = "skipped:asset-extension"
        elif ACTION_URL.search(path_query(url)):
            entry["state"] = "skipped:action-url"
        elif parts.query and self.over_param_cap(host, parts.path):
            entry["state"] = "skipped:parameter-cap"
        else:
            state, pattern = self.robots_verdict(url)
            if pattern:
                entry["notes"].append("robots rule %s" % pattern)
            entry["state"] = state or "queued"
        if entry["state"] == "queued":
            self.push(entry)
        return entry

    def new_entry(self, url, via, depth, referrer):
        entry = {"url": url, "via": {via}, "depth": depth, "referrer": referrer, "state": None, "notes": [], "http_status": None,
                 "redirect_to": None, "html_file": None, "indexability": "", "canonical": "", "in_sitemap": url in self.sitemap_urls}
        self.entries[url] = entry
        self.order.append(url)
        return entry

    def over_param_cap(self, host, path):
        key = (host, path)
        self.param_counts[key] = self.param_counts.get(key, 0) + 1
        return self.param_counts[key] > PARAM_CAP

    def push(self, entry):
        self.seq += 1
        heapq.heappush(self.heap, (entry["depth"], self.seq, entry["url"]))

    # --- setup ---------------------------------------------------------------------------------------------------
    def preflight(self):
        """Resolve where the start URL ends up to fix scope and robots before any page is queued."""
        result = self.client(self.start, follow=True, read_types=(), allowed_hosts=None)
        self.start_final = result["final_url"]
        if result["error"]:
            self.stop = "start-unreachable:%s" % result["error"]
            return
        final_host = urlsplit(result["final_url"]).hostname
        if final_host not in self.allowed_hosts and not result["stopped"]:
            self.allowed_hosts.add(final_host)
            self.scope_notes.append("Start URL redirects to host %s, which was added to the crawl scope." % final_host)
        if self.robots_for(result["final_url"])["status"] == "unreachable":
            self.stop = "robots-unreachable"
            return
        if self.crawl_delay:
            self.client.delay = max(self.client.delay, min(self.crawl_delay, 10))

    def load_sitemaps(self):
        origin = common.origin_of(self.start_final)
        info = self.robots_for(self.start_final)
        declared = info["robots"].sitemaps if info["robots"] else []
        records, entries = common.discover_sitemaps(origin, declared, self.client, self.allowed_hosts)
        for number, record in enumerate(records, 1):
            body = record.pop("body")
            if body and len(body) <= 2 * 1024 * 1024:
                record["file"] = "sitemaps/%02d.xml" % number
                (self.out_dir / "sitemaps").mkdir(exist_ok=True)
                (self.out_dir / record["file"]).write_bytes(body)
        self.sitemap_records = records
        for loc, lastmod, _source in entries:
            url = common.normalize_url(loc)
            if url:
                self.sitemap_urls.setdefault(url, lastmod)

    # --- fetching ------------------------------------------------------------------------------------------------
    def fetch_with_retry(self, url):
        for attempt in range(3):
            result = self.client(url, follow=False, max_bytes=self.max_bytes, read_types=common.HTML_TYPES)
            if result["status"] != 429:
                break
            wait = result["headers"].get("retry-after", "")
            if not wait.isdigit() or int(wait) > MAX_RETRY_AFTER or attempt == 2:
                break
            time.sleep(int(wait))
        return result

    def budget_stop(self, started):
        if self.pages >= self.max_pages:
            return "page-budget"
        if self.client.requests >= self.max_requests:
            return "request-budget"
        if time.monotonic() - started >= self.max_seconds:
            return "time-budget"
        return None

    def run(self):
        started = time.monotonic()
        self.started_at = common.now_iso()
        self.pages_dir = self.out_dir / "pages"
        self.pages_dir.mkdir()
        self.links_file = (self.out_dir / "links.csv").open("x", newline="", encoding="utf-8")
        self.links = csv.writer(self.links_file)
        self.links.writerow(["from_url", "to_url", "anchor_text", "rel", "internal"])
        self.records_file = (self.out_dir / "crawl.jsonl").open("x", encoding="utf-8")
        try:
            self.preflight()
            if self.stop:
                self.new_entry(self.start, "seed", 0, None)["state"] = "not-fetched:%s" % self.stop
            else:
                if self.use_sitemap:
                    self.load_sitemaps()
                self.add(self.start, "seed", 0)
                for seed in self.seeds:
                    self.add(seed, "seed", 1)
                for url in list(self.sitemap_urls)[: self.max_sitemap_urls]:
                    self.add(url, "sitemap", 2)
            while self.heap and not self.stop:
                self.stop = self.budget_stop(started)
                if self.stop:
                    break
                _depth, _seq, url = heapq.heappop(self.heap)
                entry = self.entries[url]
                if entry["state"] != "queued":
                    continue
                entry["state"] = "fetching"
                self.process(entry, self.fetch_with_retry(url))
        finally:
            self.links_file.close()
            self.records_file.close()
        self.ended_at = common.now_iso()
        self.elapsed = round(time.monotonic() - started, 1)
        if not self.stop:
            self.stop = "queue-exhausted"
        self.finish()

    def track(self, entry, result):
        status = result["status"]
        self.streak["failed"] = self.streak["failed"] + 1 if result["error"] else 0
        self.streak["5xx"] = self.streak["5xx"] + 1 if status and status >= 500 else 0
        self.streak["denied"] = self.streak["denied"] + 1 if status in (403, 429) else 0
        for key, reason in (("failed", "repeated-failures"), ("5xx", "repeated-5xx"), ("denied", "persistent-denial")):
            if self.streak[key] >= STOP_AFTER:
                self.stop = reason

    def process(self, entry, result):
        self.fetched += 1
        self.track(entry, result)
        entry["fetched_at"] = common.now_iso()
        record = {"url": entry["url"], "fetched_at": entry["fetched_at"], "depth": entry["depth"], "discovered_via": sorted(entry["via"]),
                  "status": result["status"], "error": result["error"], "elapsed_ms": result["elapsed_ms"],
                  "headers": {k: v for k, v in result["headers"].items() if k in common.SEO_HEADERS}}
        if result["error"]:
            entry["state"] = "failed:%s" % result["error"]
        else:
            status = result["status"]
            entry["http_status"] = status
            entry["state"] = "fetched"
            ctype = (result["content_type"] or "").lower()
            is_html = ctype.startswith(common.HTML_TYPES)
            page = None
            if 300 <= status < 400:
                target = result["redirect_to"]
                entry["redirect_to"] = target
                if target:
                    self.add(target, "redirect", entry["depth"], entry["url"], keep_off_scope=True)
                record["redirect_to"] = target
            elif 200 <= status < 300 and is_html and result["body"]:
                page = self.process_html(entry, result, record)
            elif 200 <= status < 300:
                entry["notes"].append("not HTML (%s)" % (ctype.split(";")[0] or "no content type"))
            entry["indexability"] = indexability(status, is_html, page, entry["url"])
            if page:
                entry["canonical"] = (page["canonicals"] or [page["canonical_header"] or ""])[0]
        record["indexability"] = entry["indexability"]
        self.records_file.write(json.dumps(record, ensure_ascii=False) + "\n")

    def process_html(self, entry, result, record):
        self.pages += 1
        name = "%04d.html" % self.pages
        (self.pages_dir / name).write_bytes(result["body"])
        entry["html_file"] = "pages/" + name
        if result["body_truncated"]:
            entry["notes"].append("body truncated at %d bytes" % self.max_bytes)
        data = parse_html.extract(common.decode_body(result["body"], result["content_type"]), entry["url"])
        page = summarize_page(entry["url"], result["headers"], data)
        record.update(page=page, html_file=entry["html_file"], bytes=len(result["body"]), body_truncated=result["body_truncated"])
        for link in data["links"][:2000]:
            href = link.get("resolved_href") or link.get("href")
            target = common.normalize_url(href, entry["url"]) if href else None
            if not target:
                continue
            internal = urlsplit(target).hostname in self.allowed_hosts
            self.links.writerow([entry["url"], target, link["anchor_text"][:200], link.get("rel", ""), int(internal)])
            if internal:
                self.add(target, "link", entry["depth"] + 1, entry["url"])
        return page

    # --- output --------------------------------------------------------------------------------------------------
    def destination(self, url):
        seen = set()
        while url in self.entries and self.entries[url]["redirect_to"] and url not in seen:
            seen.add(url)
            url = self.entries[url]["redirect_to"]
        return url

    def finish(self):
        reason = self.stop
        base = self.inventory.parent
        status_counts, skipped = {}, {}
        with self.inventory.open("x", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(INVENTORY_COLUMNS)
            for url in self.order:
                entry = self.entries[url]
                state = entry["state"]
                if state in ("queued", "fetching"):
                    state = "not-fetched:%s" % reason
                    entry["state"] = state
                if entry["http_status"]:
                    status_counts[str(entry["http_status"])] = status_counts.get(str(entry["http_status"]), 0) + 1
                if state != "fetched":
                    skipped[state] = skipped.get(state, 0) + 1
                notes = list(entry["notes"])
                if entry["in_sitemap"]:
                    notes.append("in sitemap")
                if entry["redirect_to"]:
                    notes.append("redirects to %s" % entry["redirect_to"])
                final = self.destination(url) if entry["redirect_to"] else url
                writer.writerow([url, final, ";".join(sorted(entry["via"])), path_group(url), state, entry["http_status"] or "", "no",
                                 entry["indexability"] if state == "fetched" else "blocked-by-robots" if state == "blocked-by-robots" else "",
                                 entry["canonical"], os.path.relpath(self.out_dir / entry["html_file"], base) if entry["html_file"] else "",
                                 "; ".join(notes)])
        if self.sitemap_urls:
            with (self.out_dir / "sitemap-urls.csv").open("x", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(["url", "lastmod"])
                writer.writerows(self.sitemap_urls.items())
        summary = {
            "tool": "crawl.py", "start_url": self.start, "user_agent": self.client.user_agent, "started_at": self.started_at,
            "ended_at": self.ended_at, "elapsed_seconds": self.elapsed, "stop_reason": reason,
            "complete_within_scope": reason == "queue-exhausted",
            "budgets": {"max_pages": self.max_pages, "max_requests": self.max_requests, "max_seconds": self.max_seconds,
                        "max_bytes": self.max_bytes, "delay_seconds": self.client.delay, "timeout_seconds": self.client.timeout,
                        "max_sitemap_urls": self.max_sitemap_urls},
            "scope": {"allowed_hosts": sorted(self.allowed_hosts), "notes": self.scope_notes,
                      "local_origins": sorted("%s:%s" % s for s in self.client.allow_local) or None},
            "counts": {"discovered": len(self.order), "fetched_rows": self.fetched, "html_pages": self.pages,
                       "requests": self.client.requests, "http_status": dict(sorted(status_counts.items())),
                       "not_fetched": dict(sorted(skipped.items())), "sitemap_urls": len(self.sitemap_urls)},
            "robots": {origin: {"status": i["status"], "http_status": i["http_status"], "truncated": i["truncated"]} for origin, i in self.robots.items()},
            "robots_exception": {"origins": sorted("%s:%s" % s for s in self.client.allow_local),
                                 "reason": "explicit local-project audit; robots rules were not applied to the local origin"} if self.local_robots_ignored else None,
            "crawl_delay_honored": self.crawl_delay, "sitemaps": [{k: v for k, v in r.items()} for r in self.sitemap_records],
            "limitations": [
                "Raw HTML only: no JavaScript rendering, so client-rendered content and links are not seen.",
                "Discovered URLs are not the total URLs that exist; unfetched rows are listed with the reason.",
                "Depth is the shortest path found in this crawl (an upper bound) and absent inlinks do not prove an orphan unless the crawl completed.",
                "Observed indexability describes blocking directives only; it does not establish that a page is indexed."]}
        (self.out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--output-dir", type=Path, required=True, help="New evidence directory; never overwritten")
    parser.add_argument("--inventory", type=Path, help="New url-inventory.csv path (default: inside the output directory)")
    parser.add_argument("--max-pages", type=int, default=100, help="HTML pages to fetch (default 100)")
    parser.add_argument("--max-requests", type=int, default=300, help="Total HTTP requests including robots, sitemaps and redirects (default 300)")
    parser.add_argument("--max-seconds", type=int, default=900)
    parser.add_argument("--max-bytes", type=int, default=5 * 1024 * 1024, help="Per-page body cap")
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds between requests to a host (default 1; minimum 0.2)")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--seed", action="append", default=[], help="Extra in-scope URL to include (repeatable)")
    parser.add_argument("--allow-host", action="append", default=[], help="Extra host to treat as in scope (repeatable)")
    parser.add_argument("--allow-local", action="append", default=[], metavar="ORIGIN", help="Explicitly in-scope local origin (local-project audits)")
    parser.add_argument("--ignore-robots-for-local", action="store_true", help="Apply the documented local-project robots exception to --allow-local origins only")
    parser.add_argument("--no-sitemap", action="store_true")
    parser.add_argument("--max-sitemap-urls", type=int, default=5000)
    parser.add_argument("--user-agent", default=common.USER_AGENT)
    parser.add_argument("--robots-token", default=common.ROBOTS_TOKEN, help="User-agent token used to match robots.txt groups")
    args = parser.parse_args()
    start = common.normalize_url(args.url)
    if not start:
        parser.error("Provide an absolute http(s) URL without credentials.")
    if args.delay < 0.2 or not 1 <= args.timeout <= 120 or min(args.max_pages, args.max_requests, args.max_seconds, args.max_bytes) < 1:
        parser.error("Budgets must be positive, --delay at least 0.2 and --timeout 1-120 seconds.")
    try:
        allow_local = frozenset(common.local_scope(o) for o in args.allow_local)
    except ValueError as exc:
        parser.error(str(exc))
    inventory = args.inventory or args.output_dir / "url-inventory.csv"
    if args.output_dir.exists() or inventory.exists():
        print("Error: the output directory or inventory file already exists; choose fresh paths.", file=sys.stderr)
        return 1
    args.output_dir.mkdir(parents=True)
    inventory.parent.mkdir(parents=True, exist_ok=True)
    client = common.Client(args.delay, args.timeout, args.user_agent, allow_local)
    crawler = Crawler(start, args.output_dir, inventory, client, args.max_pages, args.max_requests, args.max_seconds, args.max_bytes,
                      args.seed, args.allow_host, not args.no_sitemap, args.max_sitemap_urls, args.ignore_robots_for_local, args.robots_token)
    crawler.run()
    print(args.output_dir / "summary.json")
    return 1 if crawler.stop.startswith(("start-unreachable", "robots-unreachable")) else 0


if __name__ == "__main__":
    sys.exit(main())
