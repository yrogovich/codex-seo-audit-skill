"""Behavior checks for crawl.py (no sockets are opened).

Run: python3 -m unittest discover -s tests -v
"""

from contextlib import ExitStack, redirect_stdout, redirect_stderr
import csv
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fakesite import FakeSite, TIMEOUT, common  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
spec = importlib.util.spec_from_file_location("crawl", SCRIPTS / "crawl.py")
crawl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(crawl)

HOME = ('<a href="/about">About us</a><a href="/products/a">Product A</a><a href="/products/b"><img src="b.png" alt="B"></a>'
        '<a href="/old">Old</a><a href="/missing">Gone</a><a href="https://other.com/ext">Ext</a><a href="mailto:a@b.c">mail</a>'
        '<a href="/file.pdf">PDF</a><a href="/logout">Out</a><a href="/private/secret">Secret</a><a href="#top">top</a><a href="/about#x">click here</a>')
SITEMAP = ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">%s</urlset>' % "".join(
    "<url><loc>https://example.com%s</loc></url>" % p for p in ("/", "/about", "/orphan", "/private/secret", "/products/a")))


def sample_site():
    site = FakeSite()
    site.add("example.com", "/robots.txt", "User-agent: *\nDisallow: /private/\nSitemap: https://example.com/sitemap.xml\n", content_type="text/plain")
    site.add("example.com", "/sitemap.xml", SITEMAP, content_type="application/xml")
    site.page("example.com", "/", "Home", HOME, head='<link rel="canonical" href="https://example.com/"><meta name="viewport" content="width=device-width">')
    site.page("example.com", "/about", "About", '<h1>About</h1><a href="/">Home</a>', head='<link rel="canonical" href="https://example.com/about">')
    site.page("example.com", "/products/a", "Product A", '<a href="/products/b">B</a>', head='<link rel="canonical" href="https://example.com/products/">')
    site.page("example.com", "/products/b", "Product B", "<p>B</p>", head='<meta name="robots" content="noindex">')
    site.redirect("example.com", "/old", "/new")
    site.page("example.com", "/new", "New")
    site.page("example.com", "/orphan", "Orphan", "<p>only in the sitemap</p>")
    return site


class Run:
    pass


def crawl_site(site, start="https://example.com/", client_options=None, **kwargs):
    with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
        for item in site.patches():
            stack.enter_context(item)
        root = Path(temporary)
        out = root / "evidence" / "crawl"
        out.mkdir(parents=True)
        inventory = root / "url-inventory.csv"
        client = common.Client(delay=0.2, **(client_options or {}))
        crawler = crawl.Crawler(start, out, inventory, client, **kwargs)
        crawler.run()
        run = Run()
        run.crawler, run.summary = crawler, json.loads((out / "summary.json").read_text())
        with inventory.open(newline="", encoding="utf-8") as stream:
            run.rows = list(csv.DictReader(stream))
        run.by_url = {r["url"]: r for r in run.rows}
        run.records = [json.loads(line) for line in (out / "crawl.jsonl").read_text().splitlines()]
        run.record = {r["url"]: r for r in run.records}
        with (out / "links.csv").open(newline="", encoding="utf-8") as stream:
            run.links = list(csv.DictReader(stream))
        run.files = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
        run.refs_ok = all((root / r["evidence_ref"]).is_file() for r in run.rows if r["evidence_ref"])
        run.requests = site.requested()
        return run


U = "https://example.com"


class CrawlTests(unittest.TestCase):
    def test_full_crawl_of_a_small_site(self):
        run = crawl_site(sample_site())
        self.assertEqual(run.summary["stop_reason"], "queue-exhausted")
        self.assertTrue(run.summary["complete_within_scope"])
        self.assertEqual(list(run.rows[0].keys()), crawl.INVENTORY_COLUMNS)
        status = {url[len(U):]: (row["fetch_status"], row["http_status"]) for url, row in run.by_url.items()}
        self.assertEqual(status["/"], ("fetched", "200"))
        self.assertEqual(status["/missing"], ("fetched", "404"))
        self.assertEqual(status["/old"], ("fetched", "301"))
        self.assertEqual(status["/new"], ("fetched", "200"))
        self.assertEqual(status["/file.pdf"][0], "skipped:asset-extension")
        self.assertEqual(status["/logout"][0], "skipped:action-url")
        self.assertEqual(status["/private/secret"][0], "blocked-by-robots")
        self.assertEqual(status["/orphan"], ("fetched", "200"))
        self.assertNotIn("https://other.com/ext", run.by_url)
        self.assertTrue(run.refs_ok)

    def test_nothing_forbidden_is_requested(self):
        run = crawl_site(sample_site())
        paths = [p for _, host, p in run.requests]
        self.assertTrue(all(host == "example.com" for _, host, _ in run.requests))
        for forbidden in ("/private/secret", "/logout", "/file.pdf"):
            self.assertNotIn(forbidden, paths)
        self.assertLess(paths.index("/robots.txt"), paths.index("/about"))
        self.assertEqual({m for m, _, _ in run.requests}, {"GET"})
        self.assertEqual(run.summary["counts"]["requests"], len(run.requests))

    def test_inventory_signals_and_provenance(self):
        run = crawl_site(sample_site())
        rows = {url[len(U):]: row for url, row in run.by_url.items()}
        self.assertEqual(rows["/products/b"]["observed_indexability"], "noindex-meta")
        self.assertEqual(rows["/products/a"]["observed_indexability"], "canonical-elsewhere")
        self.assertEqual(rows["/products/a"]["canonical"], "https://example.com/products/")
        self.assertEqual(rows["/about"]["observed_indexability"], "no-blocking-signal")
        self.assertEqual(rows["/missing"]["observed_indexability"], "client-error")
        self.assertEqual(rows["/old"]["observed_indexability"], "redirect")
        self.assertEqual(rows["/old"]["final_url"], U + "/new")
        self.assertIn("redirect", rows["/new"]["discovered_via"])
        self.assertEqual(rows["/orphan"]["discovered_via"], "sitemap")
        self.assertIn("in sitemap", rows["/about"]["notes"])
        self.assertIn("robots rule /private/", rows["/private/secret"]["notes"])
        self.assertEqual(rows["/products/a"]["template"], "products/*")
        self.assertEqual(rows["/"]["template"], "(home)")

    def test_link_edges_and_page_signals(self):
        run = crawl_site(sample_site())
        external = [l for l in run.links if l["to_url"] == "https://other.com/ext"]
        self.assertEqual([l["internal"] for l in external], ["0"])
        self.assertFalse([l for l in run.links if l["to_url"].startswith("mailto") or "#" in l["to_url"]])
        image_link = next(l for l in run.links if l["to_url"] == U + "/products/b" and l["from_url"] == U + "/")
        self.assertEqual(image_link["anchor_text"], "B")
        page = run.record[U + "/"]["page"]
        self.assertEqual((page["titles"], page["viewport"], page["link_empty_anchor"]), (["Home"], True, 0))
        self.assertEqual(run.record[U + "/about"]["page"]["h1"], ["About"])

    def test_page_budget_stops_and_lists_the_rest(self):
        run = crawl_site(sample_site(), max_pages=2)
        self.assertEqual(run.summary["stop_reason"], "page-budget")
        self.assertFalse(run.summary["complete_within_scope"])
        self.assertEqual(run.summary["counts"]["html_pages"], 2)
        self.assertTrue(any(r["fetch_status"] == "not-fetched:page-budget" for r in run.rows))

    def test_request_budget_counts_every_request(self):
        run = crawl_site(sample_site(), max_requests=6)
        self.assertEqual(run.summary["stop_reason"], "request-budget")
        self.assertLessEqual(run.summary["counts"]["requests"], 6)

    def test_unreachable_robots_stops_before_crawling(self):
        site = sample_site()
        site.add("example.com", "/robots.txt", "down", status=503, content_type="text/plain")
        run = crawl_site(site)
        self.assertEqual(run.summary["stop_reason"], "robots-unreachable")
        self.assertEqual([r["fetch_status"] for r in run.rows], ["not-fetched:robots-unreachable"])
        self.assertNotIn("/about", [p for _, _, p in run.requests])

    def test_missing_robots_means_no_restrictions(self):
        site = sample_site()
        site.pages.pop(("*", "example.com", "/robots.txt"))
        run = crawl_site(site, use_sitemap=False)
        self.assertEqual(run.by_url[U + "/private/secret"]["fetch_status"], "fetched")

    def test_start_url_redirect_to_another_host_extends_scope_once(self):
        site = FakeSite()
        site.redirect("example.com", "/", "https://www.example.com/")
        site.page("www.example.com", "/", "Home", '<a href="/a">A</a><a href="https://elsewhere.com/">x</a>')
        site.page("www.example.com", "/a", "A")
        run = crawl_site(site, use_sitemap=False)
        self.assertEqual(run.summary["scope"]["allowed_hosts"], ["example.com", "www.example.com"])
        self.assertTrue(run.summary["scope"]["notes"])
        self.assertEqual(run.by_url["https://www.example.com/a"]["http_status"], "200")
        self.assertNotIn("elsewhere.com", [h for _, h, _ in run.requests])

    def test_internal_redirect_to_another_host_is_recorded_not_followed(self):
        site = FakeSite()
        site.page("example.com", "/", "Home", '<a href="/go">go</a>')
        site.redirect("example.com", "/go", "https://partner.com/landing")
        run = crawl_site(site, use_sitemap=False)
        self.assertEqual(run.by_url["https://partner.com/landing"]["fetch_status"], "off-scope")
        self.assertNotIn("partner.com", [h for _, h, _ in run.requests])

    def test_repeated_server_errors_stop_the_crawl(self):
        site = FakeSite()
        site.page("example.com", "/", "Home", "".join('<a href="/e%d">e</a>' % i for i in range(10)))
        for i in range(10):
            site.add("example.com", "/e%d" % i, "oops", status=503)
        run = crawl_site(site, use_sitemap=False)
        self.assertEqual(run.summary["stop_reason"], "repeated-5xx")
        self.assertEqual(run.summary["counts"]["fetched_rows"], 1 + crawl.STOP_AFTER)

    def test_persistent_denial_and_failures_stop_the_crawl(self):
        site = FakeSite()
        site.page("example.com", "/", "Home", "".join('<a href="/d%d">d</a>' % i for i in range(10)))
        for i in range(10):
            site.add("example.com", "/d%d" % i, "no", status=403)
        self.assertEqual(crawl_site(site, use_sitemap=False).summary["stop_reason"], "persistent-denial")
        site = FakeSite()
        site.page("example.com", "/", "Home", "".join('<a href="/t%d">t</a>' % i for i in range(10)))
        for i in range(10):
            site.fail("example.com", "/t%d" % i, TIMEOUT)
        run = crawl_site(site, use_sitemap=False)
        self.assertEqual(run.summary["stop_reason"], "repeated-failures")
        self.assertEqual(run.by_url[U + "/t0"]["fetch_status"], "failed:timeout")

    def test_429_honors_retry_after_then_continues(self):
        site = FakeSite()
        site.page("example.com", "/", "Home", '<a href="/slow">s</a>')
        site.sequence("example.com", "/slow", [(429, {"Retry-After": "3"}, "wait"), (200, {}, "<html><title>Slow</title></html>")])
        run = crawl_site(site, use_sitemap=False)
        self.assertEqual(run.by_url[U + "/slow"]["http_status"], "200")
        self.assertIn(3, site.sleeps)
        site = FakeSite()
        site.page("example.com", "/", "Home", '<a href="/slow">s</a>')
        site.add("example.com", "/slow", "wait", status=429, headers={"Retry-After": "3600"})
        self.assertEqual(crawl_site(site, use_sitemap=False).by_url[U + "/slow"]["http_status"], "429")

    def test_crawl_delay_in_robots_slows_the_pace(self):
        site = sample_site()
        site.add("example.com", "/robots.txt", "User-agent: *\nCrawl-delay: 5\n", content_type="text/plain")
        run = crawl_site(site, max_pages=1, use_sitemap=False)
        self.assertEqual(run.summary["crawl_delay_honored"], 5.0)
        self.assertEqual(run.summary["budgets"]["delay_seconds"], 5.0)

    def test_query_variants_are_capped(self):
        site = FakeSite()
        site.page("example.com", "/", "Home", "".join('<a href="/list?page=%d">p</a>' % i for i in range(40)))
        site.default = (200, [("Content-Type", "text/html")], b"<html><title>List</title></html>")
        run = crawl_site(site, use_sitemap=False)
        states = [r["fetch_status"] for url, r in run.by_url.items() if "/list?" in url]
        self.assertEqual(states.count("fetched"), crawl.PARAM_CAP)
        self.assertEqual(states.count("skipped:parameter-cap"), 40 - crawl.PARAM_CAP)

    def test_non_html_pages_are_not_parsed(self):
        site = FakeSite()
        site.page("example.com", "/", "Home", '<a href="/data">d</a>')
        site.add("example.com", "/data", '{"a": 1}', content_type="application/json")
        run = crawl_site(site, use_sitemap=False)
        self.assertEqual(run.by_url[U + "/data"]["observed_indexability"], "not-html")
        self.assertNotIn("page", run.record[U + "/data"])
        self.assertIn("not HTML", run.by_url[U + "/data"]["notes"])

    def test_header_noindex_and_link_header_canonical(self):
        site = FakeSite()
        site.page("example.com", "/", "Home", '<a href="/h">h</a>')
        site.page("example.com", "/h", "H", headers={"X-Robots-Tag": "googlebot: noindex", "Link": '<https://example.com/main>; rel="canonical"'})
        run = crawl_site(site, use_sitemap=False)
        row = run.by_url[U + "/h"]
        self.assertEqual((row["observed_indexability"], row["canonical"]), ("noindex-header;canonical-elsewhere", "https://example.com/main"))

    def test_local_origin_and_the_explicit_robots_exception(self):
        site = FakeSite()
        site.addresses["localhost"] = ["127.0.0.1"]
        site.add("localhost", "/robots.txt", "User-agent: *\nDisallow: /\n", content_type="text/plain")
        site.page("localhost", "/", "Dev", '<a href="/a">a</a>')
        site.page("localhost", "/a", "A")
        local = frozenset({("localhost", 3000)})
        start = "http://localhost:3000/"
        blocked = crawl_site(site, start, {"allow_local": local}, use_sitemap=False)
        self.assertEqual(blocked.by_url[start]["fetch_status"], "blocked-by-robots")
        self.assertIsNone(blocked.summary["robots_exception"])
        allowed = crawl_site(site, start, {"allow_local": local}, use_sitemap=False, ignore_local_robots=True)
        self.assertEqual(allowed.by_url["http://localhost:3000/a"]["http_status"], "200")
        self.assertEqual(allowed.summary["robots_exception"]["origins"], ["localhost:3000"])
        self.assertEqual(allowed.summary["scope"]["local_origins"], ["localhost:3000"])

    def test_local_target_is_blocked_without_the_explicit_allowance(self):
        site = FakeSite()
        site.addresses["localhost"] = ["127.0.0.1"]
        site.page("localhost", "/", "Dev")
        run = crawl_site(site, "http://localhost:3000/")
        self.assertTrue(run.summary["stop_reason"].startswith("start-unreachable:blocked-target"))
        self.assertEqual(site.log, [])

    def test_cli_refuses_existing_paths_and_bad_budgets(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(crawl.sys, "argv", ["crawl.py", "https://example.com/", "--output-dir", temporary]), redirect_stderr(io.StringIO()):
                self.assertEqual(crawl.main(), 1)
            with patch.object(crawl.sys, "argv", ["crawl.py", "https://example.com/", "--output-dir", temporary + "/x", "--delay", "0"]), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as stop:
                    crawl.main()
            self.assertEqual(stop.exception.code, 2)
            site = sample_site()
            out = Path(temporary) / "run"
            inventory = Path(temporary) / "audit" / "url-inventory.csv"
            argv = ["crawl.py", "https://example.com/", "--output-dir", str(out), "--inventory", str(inventory), "--max-pages", "3"]
            with patch.object(crawl.sys, "argv", argv), ExitStack() as stack, redirect_stdout(io.StringIO()):
                for item in site.patches():
                    stack.enter_context(item)
                self.assertEqual(crawl.main(), 0)
            self.assertTrue(inventory.is_file() and (out / "summary.json").is_file())
            with inventory.open(newline="") as stream:
                row = next(csv.DictReader(stream))
            self.assertTrue((inventory.parent / row["evidence_ref"]).is_file())  # evidence_ref is relative to the inventory file


class HelperTests(unittest.TestCase):
    def test_x_robots_directives_by_agent(self):
        self.assertEqual(crawl.x_robots_directives("noindex, nofollow"), {None: {"noindex", "nofollow"}})
        parsed = crawl.x_robots_directives("googlebot: noindex, nofollow, bingbot: noarchive, unavailable_after: 25 Jun 2030 15:00:00 PST")
        self.assertEqual(parsed["googlebot"], {"noindex", "nofollow"})
        self.assertIn("noarchive", parsed["bingbot"])
        self.assertEqual(crawl.x_robots_directives(""), {})

    def test_link_header_canonical(self):
        self.assertEqual(crawl.link_header_canonical('<https://e.com/a>; rel="canonical", <https://e.com/n>; rel="next"'), "https://e.com/a")
        self.assertIsNone(crawl.link_header_canonical('<https://e.com/n>; rel="next"'))
        self.assertIsNone(crawl.link_header_canonical(None))

    def test_json_ld_summary(self):
        blocks = [{"value": {"@context": "https://schema.org", "@graph": [{"@type": "Organization", "name": "[Company Name]"}, {"@type": ["WebSite", "Thing"]}]}, "syntax_error": None},
                  {"value": {"@context": "https://schema.org", "name": "no type"}, "syntax_error": None},
                  {"raw": "{broken", "syntax_error": "x"}]
        summary = crawl.summarize_json_ld(blocks)
        self.assertEqual((summary["syntax_errors"], summary["missing_type"], summary["placeholder_blocks"]), (1, 1, 1))
        self.assertEqual(summary["types"], ["Organization", "Thing", "WebSite"])

    def test_path_groups(self):
        self.assertEqual([crawl.path_group(u) for u in ("https://e.com/", "https://e.com/about", "https://e.com/blog/post", "https://e.com/sitemap.html")],
                         ["(home)", "about", "blog/*", "(root-file)"])


if __name__ == "__main__":
    unittest.main()
