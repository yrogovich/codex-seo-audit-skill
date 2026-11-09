#!/usr/bin/env python3
"""Turn a crawl.py output directory into candidate issues with affected URLs and counts; standard library only.

Everything reported is a lead for the auditor to verify in context. Nothing here assigns severity, claims a
page is or is not indexed, or treats a sampled crawl as the whole site."""

import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

URL_CAP, DETAIL_CAP = 50, 25
GENERIC_ANCHORS = {"click here", "here", "read more", "learn more", "more", "this", "link", "click", "details", "more info", "continue", "read on"}
HREFLANG = re.compile(r"^(x-default|[a-z]{2,3}(-[a-z]{4})?(-([a-z]{2}|[0-9]{3}))?)$", re.I)
MIN_DUPLICATE_TEXT_CHARS = 200  # operational floor so near-empty pages do not group as duplicates


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def norm(text):
    return " ".join((text or "").lower().split())


class Analysis:
    def __init__(self, crawl_dir, inventory):
        self.summary = json.loads((crawl_dir / "summary.json").read_text(encoding="utf-8"))
        self.rows = {r["url"]: r for r in read_csv(inventory)}
        self.records = {}
        for line in (crawl_dir / "crawl.jsonl").read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            self.records[record["url"]] = record
        self.links = [dict(l, internal=l["internal"] == "1") for l in read_csv(crawl_dir / "links.csv")]
        sitemap_file = crawl_dir / "sitemap-urls.csv"
        self.sitemap = {r["url"] for r in read_csv(sitemap_file)} if sitemap_file.exists() else set()
        self.status = {u: int(r["http_status"]) for u, r in self.rows.items() if r["http_status"].isdigit()}
        self.pages = {u: rec["page"] for u, rec in self.records.items() if "page" in rec and self.status.get(u) == 200}
        self.start = self.summary["start_url"]
        self.inlinks = defaultdict(set)
        for link in self.links:
            if link["internal"] and link["from_url"] != link["to_url"]:
                self.inlinks[link["to_url"]].add(link["from_url"])
        self.candidates, self.checks_run = [], []
        counts = self.summary["counts"]
        self.partial = not self.summary["complete_within_scope"]
        self.crawl_label = ("complete within scope" if not self.partial else "partial (stopped: %s; %d of %d discovered URLs fetched)"
                            % (self.summary["stop_reason"], counts["fetched_rows"], counts["discovered"]))

    # --- helpers ---------------------------------------------------------------------------------------------
    def canonical(self, page):
        return (page["canonicals"] or [page["canonical_header"]])[0]

    def eligible(self):
        return [u for u, p in self.pages.items() if not (p["noindex_meta"] or p["noindex_header"])]

    def indexable(self):
        return [u for u in self.eligible() if self.canonical(self.pages[u]) in (None, "", u)]

    def check(self, name, area, title, urls, details=None, unit="fetched HTML pages", denominator=None, note=None, count=None):
        """Record a check; empty results are kept in checks_run so 'none found' is distinguishable from 'not run'."""
        urls = list(dict.fromkeys(urls))
        total = len(urls) if count is None else count
        denominator = len(self.pages) if denominator is None else denominator
        self.checks_run.append({"check": name, "count": total, "denominator": denominator, "unit": unit})
        if not total:
            return
        self.candidates.append({
            "check": name, "area": area, "title": title, "count": total, "denominator": denominator,
            "basis": "%d of %d %s; crawl %s" % (total, denominator, unit, self.crawl_label),
            "urls": urls[:URL_CAP], "urls_truncated": len(urls) > URL_CAP,
            "details": (details or [])[:DETAIL_CAP], "details_truncated": len(details or []) > DETAIL_CAP, "note": note})

    def referrers(self, url, limit=3):
        return sorted(self.inlinks.get(url, ()))[:limit]

    # --- checks ----------------------------------------------------------------------------------------------
    def run(self):
        self.status_and_indexability()
        self.redirects()
        self.link_checks()
        self.onpage()
        self.media_and_data()
        self.hreflang()
        self.sitemap_checks()

    def status_and_indexability(self):
        for name, low, high, title in (("status.client_error", 400, 499, "Crawled URLs returning 4xx"), ("status.server_error", 500, 599, "Crawled URLs returning 5xx")):
            hits = [u for u, s in self.status.items() if low <= s <= high]
            self.check(name, "technical/indexing", title, hits, [{"url": u, "status": self.status[u], "inlinks": len(self.inlinks.get(u, ())),
                                                                   "example_referrers": self.referrers(u), "in_sitemap": u in self.sitemap} for u in hits],
                       "fetched URLs", len(self.status))
        failed = [u for u, r in self.rows.items() if r["fetch_status"].startswith("failed:")]
        self.check("status.fetch_failed", "technical/indexing", "URLs that could not be fetched (network or TLS failure)", failed,
                   [{"url": u, "reason": self.rows[u]["fetch_status"]} for u in failed], "fetched URLs", self.summary["counts"]["fetched_rows"])
        noindex = [u for u in self.pages if self.pages[u]["noindex_meta"] or self.pages[u]["noindex_header"]]
        self.check("index.noindex", "technical/indexing", "Pages with a noindex directive (meta or X-Robots-Tag)", noindex,
                   [{"url": u, "meta": self.pages[u]["noindex_meta"], "header": self.pages[u]["noindex_header"], "in_sitemap": u in self.sitemap,
                     "inlinks": len(self.inlinks.get(u, ()))} for u in noindex], note="Confirm intent before calling these defects; staging and utility pages are often intentionally noindex.")
        self.check("index.noindex_in_sitemap", "technical/indexing", "Sitemap URLs that carry a noindex directive", [u for u in noindex if u in self.sitemap],
                   None, "sitemap URLs", len(self.sitemap))
        blocked = [u for u, r in self.rows.items() if r["fetch_status"] == "blocked-by-robots"]
        self.check("index.blocked_by_robots", "technical/indexing", "Discovered URLs disallowed by robots.txt", blocked,
                   [{"url": u, "rule": self.rows[u]["notes"], "inlinks": len(self.inlinks.get(u, ())), "in_sitemap": u in self.sitemap} for u in blocked],
                   "discovered URLs", len(self.rows), "Disallow controls crawling, not removal from search; a blocked page cannot show its noindex.")
        elsewhere, bad = [], []
        for u, p in self.pages.items():
            target = self.canonical(p)
            if target and target != u:
                state = self.target_state(target)
                elsewhere.append({"url": u, "canonical": target, "target": state})
                if state not in ("200", "not-crawled"):
                    bad.append({"url": u, "canonical": target, "target": state})
        self.check("index.canonical_elsewhere", "technical/indexing", "Pages whose canonical points to a different URL", [d["url"] for d in elsewhere], elsewhere,
                   note="Often intentional (parameters, variants). Canonicals are signals, not directives.")
        self.check("index.canonical_bad_target", "technical/indexing", "Canonical targets that redirect, error, are noindex or canonicalize elsewhere", [d["url"] for d in bad], bad,
                   "pages whose canonical points elsewhere", len(elsewhere))
        multiple = [u for u, p in self.pages.items() if len(set(p["canonicals"])) > 1 or len(p["canonicals"]) > 1
                    or (p["canonicals"] and p["canonical_header"] and p["canonicals"][0] != p["canonical_header"])]
        self.check("index.canonical_multiple", "technical/indexing", "Pages with more than one or conflicting canonical declarations", multiple)
        self.check("index.canonical_missing", "technical/indexing", "Pages with no canonical declaration",
                   [u for u, p in self.pages.items() if not p["canonicals"] and not p["canonical_header"]],
                   note="A missing canonical is not a defect by itself; matters where duplicate URL variants exist.")
        conflicts = [u for u, p in self.pages.items() if (p["noindex_header"] and ({"index", "all"} & set(p["robots_meta"]))) or
                     (p["noindex_meta"] and p["x_robots_tag"] and not p["noindex_header"] and ({"index", "all"} & set(p["robots_header_tokens"])))]
        self.check("index.robots_directive_conflict", "technical/indexing", "Meta robots and X-Robots-Tag disagree about indexing", conflicts)

    def target_state(self, target):
        status = self.status.get(target)
        if status is None:
            return "not-crawled"
        if status != 200:
            return str(status)
        page = self.pages.get(target)
        if page and (page["noindex_meta"] or page["noindex_header"]):
            return "noindex"
        if page and self.canonical(page) not in (None, "", target):
            return "canonical-elsewhere"
        return "200"

    def redirects(self):
        step = {u: rec["redirect_to"] for u, rec in self.records.items() if rec.get("redirect_to") and 300 <= (self.status.get(u) or 0) < 400}
        chains, loops, to_error = [], [], []
        for start in step:
            seen, path = {start}, [start]
            while path[-1] in step:
                nxt = step[path[-1]]
                if nxt in seen:
                    loops.append(start)
                    break
                seen.add(nxt)
                path.append(nxt)
            else:
                end_status = self.status.get(path[-1])
                if len(path) > 2:
                    chains.append({"url": start, "hops": len(path) - 1, "path": path})
                if end_status and end_status >= 400:
                    to_error.append({"url": start, "final": path[-1], "status": end_status})
        self.check("redirects.chains", "technical/indexing", "Redirect chains of two or more hops (one row per chain start)", [c["url"] for c in chains], chains, "redirecting URLs", len(step))
        self.check("redirects.loops", "technical/indexing", "Redirect loops", loops, None, "redirecting URLs", len(step))
        self.check("redirects.to_error", "technical/indexing", "Redirects that end at a 4xx/5xx URL", [d["url"] for d in to_error], to_error, "redirecting URLs", len(step))
        temporary = [u for u in step if self.status[u] in (302, 303, 307)]
        self.check("redirects.temporary", "technical/indexing", "Temporary redirects (302/303/307) found while crawling",
                   temporary, [{"url": u, "status": self.status[u], "to": step[u], "inlinks": len(self.inlinks.get(u, ()))} for u in temporary],
                   "redirecting URLs", len(step), "Temporary redirects are correct for temporary moves; confirm which these are.")
        off = [u for u, r in self.rows.items() if r["fetch_status"] == "off-scope"]
        self.check("redirects.off_scope", "technical/indexing", "Redirect targets on a host outside the crawl scope (not followed)", off,
                   [{"url": u, "referrer": self.rows[u]["discovered_via"]} for u in off], "discovered URLs", len(self.rows))
        into_redirect = defaultdict(set)
        for link in self.links:
            if link["internal"] and link["to_url"] in step and link["from_url"] != link["to_url"]:
                into_redirect[link["to_url"]].add(link["from_url"])
        self.check("redirects.internal_links_to_redirects", "architecture/links", "Pages linking to URLs that redirect",
                   [s for sources in into_redirect.values() for s in sorted(sources)],
                   [{"target": t, "redirects_to": self.rows[t]["final_url"], "linking_pages": len(s), "example_referrers": sorted(s)[:3]} for t, s in into_redirect.items()],
                   "fetched HTML pages", len(self.pages))

    def link_checks(self):
        internal = [l for l in self.links if l["internal"]]
        broken = defaultdict(set)
        insecure = defaultdict(set)
        for link in internal:
            if self.status.get(link["to_url"], 0) >= 400:
                broken[link["to_url"]].add(link["from_url"])
            if self.start.startswith("https://") and link["to_url"].startswith("http://"):
                insecure[link["to_url"]].add(link["from_url"])
        self.check("links.broken_internal", "architecture/links", "Pages with internal links to 4xx/5xx URLs",
                   [s for sources in broken.values() for s in sorted(sources)],
                   [{"target": t, "status": self.status[t], "linking_pages": len(s), "example_referrers": sorted(s)[:3]} for t, s in broken.items()],
                   "fetched HTML pages", len(self.pages))
        self.check("links.http_scheme_internal", "architecture/links", "Internal links using http:// on an https site",
                   [s for sources in insecure.values() for s in sorted(sources)],
                   [{"target": t, "linking_pages": len(s), "example_referrers": sorted(s)[:3]} for t, s in insecure.items()], "fetched HTML pages", len(self.pages))
        with_links = sum(1 for p in self.pages.values() if p["link_total"])
        empty = {u: p["link_empty_anchor"] for u, p in self.pages.items() if p["link_empty_anchor"]}
        self.check("links.empty_anchor", "architecture/links", "Pages with links that have no anchor text, image alt or aria-label", list(empty),
                   [{"url": u, "links": n} for u, n in empty.items()], "fetched HTML pages with links", with_links,
                   "Link text with no accessible name gives crawlers and users no context.")
        generic = defaultdict(set)
        for link in internal:
            if norm(link["anchor_text"]) in GENERIC_ANCHORS:
                generic[norm(link["anchor_text"])].add(link["from_url"])
        self.check("links.generic_anchor", "architecture/links", "Internal links with generic anchor text",
                   [s for sources in generic.values() for s in sorted(sources)],
                   [{"anchor": a, "pages": len(s), "example_pages": sorted(s)[:3]} for a, s in sorted(generic.items(), key=lambda i: -len(i[1]))],
                   "fetched HTML pages with links", with_links, "Judge in context: a generic label next to descriptive text may be fine.")
        orphans = [u for u in sorted(self.sitemap) if u != self.start and not self.inlinks.get(u) and u in self.rows]
        self.check("links.orphan_candidates", "architecture/links", "Sitemap URLs with no internal link found in this crawl", orphans,
                   [{"url": u, "fetched": self.rows[u]["fetch_status"] == "fetched"} for u in orphans], "sitemap URLs", len(self.sitemap),
                   note="Candidates only" + (": the crawl is partial, so a missing inlink may simply be an unfetched linking page." if self.partial else "; confirm no links exist from JavaScript-rendered content."))
        nofollow = [l for l in internal if "nofollow" in l["rel"].lower()]
        self.check("links.nofollow_internal", "architecture/links", "Internal links marked nofollow", [l["from_url"] for l in nofollow],
                   [{"from": l["from_url"], "to": l["to_url"]} for l in nofollow], "internal links", len(internal), count=len(nofollow))

    def onpage(self):
        eligible, indexable = self.eligible(), self.indexable()
        empty_titles = [u for u in eligible if not any(t.strip() for t in self.pages[u]["titles"])]
        self.check("onpage.title_missing", "content/on-page", "Pages with no or an empty <title>", empty_titles, denominator=len(eligible))
        self.check("onpage.title_multiple", "content/on-page", "Pages with more than one <title> element", [u for u in eligible if len(self.pages[u]["titles"]) > 1], denominator=len(eligible))
        self.duplicates("onpage.title_duplicate", "Indexable pages sharing the same title", indexable, lambda p: norm(p["titles"][0]) if p["titles"] else "")
        self.check("onpage.description_missing", "content/on-page", "Pages with no meta description", [u for u in eligible if not any(d.strip() for d in self.pages[u]["meta_descriptions"])],
                   denominator=len(eligible), note="Google may write its own snippet; missing is an opportunity, not a defect by itself.")
        self.duplicates("onpage.description_duplicate", "Indexable pages sharing the same meta description", indexable,
                        lambda p: norm(p["meta_descriptions"][0]) if p["meta_descriptions"] else "")
        self.check("onpage.h1_missing", "content/on-page", "Pages with no <h1>", [u for u in eligible if not self.pages[u]["h1"]], denominator=len(eligible))
        self.check("onpage.h1_multiple", "content/on-page", "Pages with more than one <h1> (cue, not a defect by itself)", [u for u in eligible if len(self.pages[u]["h1"]) > 1], denominator=len(eligible))
        self.duplicates("onpage.h1_duplicate", "Indexable pages sharing the same first <h1>", indexable, lambda p: norm(p["h1"][0]) if p["h1"] else "")
        self.duplicates("onpage.duplicate_text", "Indexable pages with identical visible text", indexable,
                        lambda p: p["visible_text"]["sha256"] if p["visible_text"]["chars"] >= MIN_DUPLICATE_TEXT_CHARS else "",
                        note="Exact text match among pages with at least %d visible characters; near-duplicates are not detected." % MIN_DUPLICATE_TEXT_CHARS)
        self.check("onpage.html_lang_missing", "content/on-page", "Pages with no <html lang>", [u for u in eligible if not (self.pages[u]["lang"] or "").strip()], denominator=len(eligible))
        self.check("mobile.viewport_missing", "rendering/mobile", "Pages with no viewport meta tag", [u for u in eligible if not self.pages[u]["viewport"]], denominator=len(eligible))
        self.check("rendering.client_rendered_cue", "rendering/mobile", "Pages that look client-rendered in the raw HTML (marker plus little text)",
                   [u for u in eligible if self.pages[u]["rendering_hint"]["possible_client_rendered"]], denominator=len(eligible),
                   note="Heuristic cue from raw HTML; render in a browser to confirm what a search engine sees.")

    def duplicates(self, name, title, urls, key, note=None):
        groups = defaultdict(list)
        for u in urls:
            value = key(self.pages[u])
            if value:
                groups[value].append(u)
        dup = {k: v for k, v in groups.items() if len(v) > 1}
        self.check(name, "content/on-page", title, [u for v in dup.values() for u in v],
                   [{"value": k[:120], "pages": len(v), "urls": v[:5]} for k, v in sorted(dup.items(), key=lambda i: -len(i[1]))],
                   denominator=len(urls), unit="indexable HTML pages", note=note)

    def media_and_data(self):
        pages = self.pages
        for name, key, title in (("images.missing_alt", "missing_alt", "Pages with images that have no alt attribute"),
                                 ("images.missing_dimensions", "missing_dimensions", "Pages with images missing width or height attributes")):
            hits = {u: p["images"][key] for u, p in pages.items() if p["images"][key]}
            self.check(name, "images/media", title, list(hits), [{"url": u, "images": n, "of": pages[u]["images"]["total"]} for u, n in hits.items()],
                       unit="fetched HTML pages with images", denominator=sum(1 for p in pages.values() if p["images"]["total"]),
                       note="Missing alt means no attribute; alt=\"\" (decorative) is not counted. Width/height may be set in CSS." if key == "missing_dimensions" else
                       "Missing alt means no attribute; alt=\"\" (decorative) is not counted.")
        for name, key, title in (("structured.json_ld_syntax_error", "syntax_errors", "Pages with JSON-LD that does not parse"),
                                 ("structured.json_ld_missing_type", "missing_type", "Pages with a JSON-LD object that has @context but no @type"),
                                 ("structured.json_ld_placeholder", "placeholder_blocks", "Pages whose JSON-LD contains placeholder-looking values")):
            hits = {u: p["json_ld"][key] for u, p in pages.items() if p["json_ld"][key]}
            self.check(name, "structured data", title, list(hits), [{"url": u, "blocks": n} for u, n in hits.items()],
                       unit="fetched HTML pages with JSON-LD", denominator=sum(1 for p in pages.values() if p["json_ld"]["blocks"]),
                       note="Syntax and placeholders only; schema validity and rich-result eligibility need a validator.")

    def hreflang(self):
        declared = {u: {h["href"]: h["hreflang"] for h in p["hreflang"] if h["href"]} for u, p in self.pages.items() if p["hreflang"]}
        invalid, no_self, no_return, unusable = [], [], [], []
        for u, entries in declared.items():
            bad = sorted({c for c in entries.values() if not HREFLANG.match(c or "")})
            if bad:
                invalid.append({"url": u, "codes": bad})
            if u not in entries:
                no_self.append(u)
            for target, code in entries.items():
                if target == u or target not in self.pages:
                    continue
                if u not in declared.get(target, {}):
                    no_return.append({"url": u, "target": target, "code": code})
                state = self.target_state(target)
                if state != "200":
                    unusable.append({"url": u, "target": target, "state": state})
        uncrawled = sum(1 for entries in declared.values() for t in entries if t not in self.pages)
        scope = "pages with hreflang"
        self.check("hreflang.invalid_code", "international", "hreflang values that are not syntactically valid language/region codes", [d["url"] for d in invalid], invalid,
                   scope, len(declared), "Syntax only; this does not check codes against ISO lists.")
        self.check("hreflang.missing_self_reference", "international", "Pages whose hreflang set does not include themselves", no_self, None, scope, len(declared))
        self.check("hreflang.missing_return_link", "international", "hreflang targets crawled that do not link back", [d["url"] for d in no_return], no_return, scope, len(declared),
                   "Only targets fetched in this crawl are checked; %d target(s) were not crawled and remain unverified." % uncrawled)
        self.check("hreflang.target_not_usable", "international", "hreflang targets that redirect, error, are noindex or canonicalize elsewhere",
                   [d["url"] for d in unusable], unusable, scope, len(declared))

    def sitemap_checks(self):
        if not self.sitemap:
            self.checks_run.append({"check": "sitemap.*", "count": None})
            return
        listed = [u for u in sorted(self.sitemap) if u in self.rows]
        not_ok = [u for u in listed if self.status.get(u) and self.status[u] != 200]
        self.check("sitemap.url_not_ok", "technical/indexing", "Sitemap URLs that did not return 200", not_ok,
                   [{"url": u, "status": self.status[u], "to": self.rows[u]["final_url"] if 300 <= self.status[u] < 400 else None} for u in not_ok],
                   "sitemap URLs", len(self.sitemap))
        mixed = [u for u in listed if u in self.pages and self.target_state(u) in ("noindex", "canonical-elsewhere")]
        self.check("sitemap.url_not_indexable_signal", "technical/indexing", "Sitemap URLs that are noindex or canonicalize elsewhere",
                   mixed, [{"url": u, "state": self.target_state(u)} for u in mixed], "sitemap URLs", len(self.sitemap))
        blocked = [u for u in listed if self.rows[u]["fetch_status"] == "blocked-by-robots"]
        self.check("sitemap.blocked_by_robots", "technical/indexing", "Sitemap URLs disallowed by robots.txt", blocked, None, "sitemap URLs", len(self.sitemap))
        unlisted = [u for u in self.indexable() if u not in self.sitemap]
        self.check("sitemap.indexable_not_listed", "technical/indexing", "Indexable crawled pages absent from the sitemap", unlisted, None,
                   "indexable HTML pages", len(self.indexable()),
                   "Cue only: not every page belongs in a sitemap" + ("; the crawl is partial and the sitemap may be sampled." if self.partial else "."))

    # --- statistics --------------------------------------------------------------------------------------------
    def statistics(self):
        depth = Counter(str(rec["depth"]) for rec in self.records.values())
        types = defaultdict(Counter)
        for u, p in self.pages.items():
            for t in p["json_ld"]["types"]:
                types[self.rows[u]["template"]][t] += 1
        lengths = sorted(len(p["titles"][0]) for p in self.pages.values() if p["titles"])
        top = sorted(((u, len(s)) for u, s in self.inlinks.items()), key=lambda i: (-i[1], i[0]))[:10]
        return {"http_status": self.summary["counts"]["http_status"], "observed_indexability": dict(Counter(r["observed_indexability"] or "(not fetched)" for r in self.rows.values())),
                "depth_distribution": dict(sorted(depth.items(), key=lambda i: int(i[0]))), "top_linked_pages": [{"url": u, "inlinks": n} for u, n in top],
                "json_ld_types_by_template": {t: dict(c) for t, c in sorted(types.items())},
                "title_length_chars": {"min": lengths[0], "median": lengths[len(lengths) // 2], "max": lengths[-1]} if lengths else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("crawl_dir", type=Path, help="Output directory of crawl.py")
    parser.add_argument("--inventory", type=Path, help="url-inventory.csv written by the crawl (default: inside crawl_dir)")
    parser.add_argument("--output", type=Path, help="New analysis JSON file (default: crawl_dir/analysis.json)")
    args = parser.parse_args()
    inventory = args.inventory or args.crawl_dir / "url-inventory.csv"
    output = args.output or args.crawl_dir / "analysis.json"
    try:
        if output.exists():
            raise ValueError("Output file already exists; choose a fresh path.")
        analysis = Analysis(args.crawl_dir, inventory)
        analysis.run()
        counts = analysis.summary["counts"]
        report = {"tool": "analyze_crawl.py", "analyzed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "crawl_dir": str(args.crawl_dir),
                  "scope": {"start_url": analysis.start, "stop_reason": analysis.summary["stop_reason"], "complete_within_scope": analysis.summary["complete_within_scope"],
                            "discovered": counts["discovered"], "html_pages": counts["html_pages"], "fetched_rows": counts["fetched_rows"], "requests": counts["requests"],
                            "sitemap_urls": len(analysis.sitemap)},
                  "statistics": analysis.statistics(), "candidates": analysis.candidates, "checks_run": analysis.checks_run,
                  "limitations": ["Candidates are leads to verify in context; no severity, impact or indexing status is assigned.",
                                  "Based on raw HTML from one crawl: no JavaScript rendering, and only fetched pages are analysed.",
                                  "Counts and denominators describe this crawl; a partial crawl is a sample and must not be described as site-wide.",
                                  "A check with count 0 means nothing was found in the fetched pages, not that the problem is absent from the site."] + analysis.summary["limitations"]}
        with output.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    except (OSError, ValueError, KeyError) as exc:
        print(f"Error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(output)
    for item in analysis.candidates:
        print("%-42s %5d  %s" % (item["check"], item["count"], item["title"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
