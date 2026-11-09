"""Behavior checks for analyze_crawl.py, run on crawls of an in-memory site that contains known problems.

Run: python3 -m unittest discover -s tests -v
"""

from contextlib import ExitStack, redirect_stdout, redirect_stderr
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fakesite import FakeSite, common  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


crawl, analyze = load("crawl"), load("analyze_crawl")
U = "https://example.com"
LONG = "This paragraph is long enough to count as real page text. " * 6

HOME = ('<a href="/a">A</a><a href="/b">B</a><a href="/c">C</a><a href="/d">D</a><a href="/e">E</a><a href="/old1">old</a>'
        '<a href="/gone">gone</a><a href="/untitled">u</a><a href="http://example.com/a">insecure</a><a href="/b">click here</a>'
        '<a href="/b"></a><a href="/en">en</a><a href="/fr">fr</a><a href="/dup1">1</a><a href="/dup2">2</a><a href="/app">app</a>'
        '<a href="/media">m</a><a href="/ld">ld</a><a href="/loop1">loop</a><a href="/nofollow" rel="nofollow">nf</a><a href="/hidden">h</a>')


def issue_site():
    site = FakeSite()
    site.add("example.com", "/robots.txt", "User-agent: *\nDisallow: /blocked/\n", content_type="text/plain")
    urls = ["/", "/a", "/c", "/orphan", "/gone", "/blocked/x", "/old1"]
    site.add("example.com", "/sitemap.xml", '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">%s</urlset>' % "".join(
        "<url><loc>https://example.com%s</loc></url>" % u for u in urls), content_type="application/xml")
    site.page("example.com", "/", "Home", HOME + '<a href="/blocked/x">b</a>', head='<meta name="viewport" content="width=device-width">')
    same = '<meta name="description" content="Same description">'
    site.page("example.com", "/a", "Same Title", "<h1>One</h1><h1>Two</h1>", head=same)
    site.page("example.com", "/b", "Same   title", "<h1>One</h1>", head=same + '<link rel="canonical" href="https://example.com/b"><link rel="canonical" href="https://example.com/a">')
    site.page("example.com", "/c", "Noindexed", "<h1>C</h1>", head='<meta name="robots" content="noindex">')
    site.page("example.com", "/d", "Variant of A", "<h1>D</h1>", head='<link rel="canonical" href="https://example.com/a">')
    site.page("example.com", "/e", "Canonical to 404", "<h1>E</h1>", head='<link rel="canonical" href="https://example.com/gone">')
    site.redirect("example.com", "/old1", "/old2", 302).redirect("example.com", "/old2", "/new").page("example.com", "/new", "New", "<h1>New</h1>")
    site.redirect("example.com", "/loop1", "/loop2").redirect("example.com", "/loop2", "/loop1")
    site.add("example.com", "/untitled", "<html><body><p>No title, no h1, no lang.</p></body></html>")
    site.page("example.com", "/dup1", "Dup one", "<h1>Same text</h1><p>%s</p>" % LONG)
    site.page("example.com", "/dup2", "Dup two", "<h1>Same text</h1><p>%s</p>" % LONG)
    site.page("example.com", "/app", "App", '<div id="root"></div>')
    site.page("example.com", "/media", "Media", '<img src="a.png"><img src="b.png" alt=""><img src="c.png" alt="C" width="1" height="1">')
    site.page("example.com", "/ld", "LD", "", head='<script type="application/ld+json">{broken</script><script type="application/ld+json">'
              '{"@context":"https://schema.org","@type":"Organization","name":"[Company Name]"}</script>')
    site.page("example.com", "/en", "English", "", head='<link rel="alternate" hreflang="en" href="https://example.com/en">'
              '<link rel="alternate" hreflang="fr" href="https://example.com/fr"><link rel="alternate" hreflang="english" href="https://example.com/en-gb">')
    site.page("example.com", "/fr", "French", "<h1>Fr</h1>")
    site.page("example.com", "/nofollow", "Nofollow", "<h1>n</h1>")
    # Noindex page that would otherwise duplicate a title and lack an h1/description: it must not be reported as an on-page problem.
    site.page("example.com", "/hidden", "Same Title", "", head='<meta name="robots" content="noindex">')
    site.page("example.com", "/orphan", "Orphan", "<h1>O</h1>")
    return site


def analyze_site(site, **kwargs):
    """Crawl the site, analyse it, and return (Analysis, by-check dict) while the temporary files exist."""
    with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
        for item in site.patches():
            stack.enter_context(item)
        out = Path(temporary) / "crawl"
        out.mkdir()
        crawler = crawl.Crawler("https://example.com/", out, out / "url-inventory.csv", common.Client(delay=0.2), **kwargs)
        crawler.run()
        analysis = analyze.Analysis(out, out / "url-inventory.csv")
        analysis.run()
        return analysis, {c["check"]: c for c in analysis.candidates}


class AnalyzeCrawlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analysis, cls.found = analyze_site(issue_site(), max_pages=100)

    def urls(self, check):
        return {u[len(U):] if u.startswith(U) else u for u in self.found[check]["urls"]}

    def test_the_crawl_was_complete_and_labelled_as_such(self):
        self.assertTrue(self.analysis.summary["complete_within_scope"])
        self.assertIn("crawl complete within scope", self.found["status.client_error"]["basis"])

    def test_status_and_indexability(self):
        self.assertEqual(self.urls("status.client_error"), {"/gone"})
        details = self.found["status.client_error"]["details"][0]
        self.assertEqual((details["status"], details["in_sitemap"]), (404, True))
        self.assertIn(U + "/", details["example_referrers"])
        self.assertEqual(self.urls("index.noindex"), {"/c", "/hidden"})
        self.assertEqual(self.urls("index.noindex_in_sitemap"), {"/c"})
        self.assertEqual(self.urls("index.blocked_by_robots"), {"/blocked/x"})
        # /b declares itself first and /a second: that is a "multiple canonicals" case, not "elsewhere".
        self.assertEqual(self.urls("index.canonical_elsewhere"), {"/d", "/e"})
        self.assertEqual(self.urls("index.canonical_bad_target"), {"/e"})
        self.assertEqual(self.urls("index.canonical_multiple"), {"/b"})
        states = {d["url"][len(U):]: d["target"] for d in self.found["index.canonical_elsewhere"]["details"]}
        self.assertEqual((states["/d"], states["/e"]), ("200", "404"))

    def test_redirects(self):
        chains = self.found["redirects.chains"]["details"]
        self.assertEqual([(c["url"][len(U):], c["hops"]) for c in chains], [("/old1", 2)])
        self.assertEqual(self.urls("redirects.loops"), {"/loop1", "/loop2"})
        self.assertEqual(self.urls("redirects.temporary"), {"/old1"})
        self.assertEqual(self.urls("redirects.internal_links_to_redirects"), {"/", })
        target = self.found["redirects.internal_links_to_redirects"]["details"]
        self.assertIn(U + "/new", {d["redirects_to"] for d in target})

    def test_links(self):
        self.assertEqual(self.urls("links.broken_internal"), {"/"})
        self.assertEqual(self.urls("links.http_scheme_internal"), {"/"})
        self.assertEqual(self.urls("links.generic_anchor"), {"/"})
        self.assertEqual(self.found["links.generic_anchor"]["details"][0]["anchor"], "click here")
        self.assertEqual(self.urls("links.empty_anchor"), {"/"})
        self.assertEqual(self.urls("links.orphan_candidates"), {"/orphan"})
        self.assertEqual(self.found["links.nofollow_internal"]["count"], 1)

    def test_on_page_checks(self):
        self.assertEqual(self.urls("onpage.title_missing"), {"/untitled"})
        # Whitespace and case are normalised; /d is canonicalised away. The home page's http:// link made the crawler
        # fetch http://example.com/a too, which correctly shows up as a duplicate of its https:// twin.
        twin = "http://example.com/a"
        self.assertEqual(self.urls("onpage.title_duplicate"), {"/a", "/b", twin})
        self.assertEqual(self.urls("onpage.description_duplicate"), {"/a", "/b", twin})
        self.assertIn("/untitled", self.urls("onpage.h1_missing"))
        self.assertNotIn("/hidden", self.urls("onpage.h1_missing"))  # noindex pages are not held to on-page checks
        self.assertNotIn("/hidden", self.urls("onpage.description_missing"))
        self.assertNotIn("/hidden", self.urls("sitemap.indexable_not_listed"))
        self.assertEqual(self.urls("onpage.h1_multiple"), {"/a", twin})
        self.assertEqual(self.urls("onpage.duplicate_text"), {"/dup1", "/dup2"})
        self.assertEqual(self.urls("onpage.html_lang_missing"), {"/untitled"})
        self.assertIn("/untitled", self.urls("mobile.viewport_missing"))
        self.assertNotIn("/", self.urls("mobile.viewport_missing"))
        self.assertEqual(self.urls("rendering.client_rendered_cue"), {"/app"})

    def test_images_and_structured_data(self):
        self.assertEqual(self.urls("images.missing_alt"), {"/media"})
        self.assertEqual(self.found["images.missing_alt"]["details"][0], {"url": U + "/media", "images": 1, "of": 3})
        self.assertEqual(self.urls("images.missing_dimensions"), {"/media"})
        self.assertEqual(self.found["images.missing_dimensions"]["details"][0]["images"], 2)
        self.assertEqual(self.urls("structured.json_ld_syntax_error"), {"/ld"})
        self.assertEqual(self.urls("structured.json_ld_placeholder"), {"/ld"})
        self.assertEqual(self.analysis.statistics()["json_ld_types_by_template"], {"ld": {"Organization": 1}})

    def test_hreflang_and_sitemap(self):
        self.assertEqual(self.urls("hreflang.invalid_code"), {"/en"})
        self.assertEqual(self.found["hreflang.invalid_code"]["details"][0]["codes"], ["english"])
        self.assertEqual(self.urls("hreflang.missing_return_link"), {"/en"})
        self.assertEqual(self.found["hreflang.missing_return_link"]["details"][0]["target"], U + "/fr")
        self.assertIn("1 target(s) were not crawled", self.found["hreflang.missing_return_link"]["note"])
        self.assertEqual(self.urls("sitemap.url_not_ok"), {"/gone", "/old1"})
        self.assertEqual(self.urls("sitemap.url_not_indexable_signal"), {"/c"})
        self.assertEqual(self.urls("sitemap.blocked_by_robots"), {"/blocked/x"})
        self.assertIn("/b", self.urls("sitemap.indexable_not_listed"))
        self.assertNotIn("/a", self.urls("sitemap.indexable_not_listed"))

    def test_zero_results_are_recorded_as_run_not_as_missing(self):
        run = {c["check"]: c["count"] for c in self.analysis.checks_run}
        self.assertEqual(run["status.server_error"], 0)
        self.assertNotIn("status.server_error", self.found)
        self.assertGreater(len(run), 30)

    def test_statistics(self):
        stats = self.analysis.statistics()
        self.assertEqual(stats["depth_distribution"]["0"], 1)
        self.assertEqual(stats["observed_indexability"]["noindex-meta"], 2)
        counts = [p["inlinks"] for p in stats["top_linked_pages"]]  # distinct linking pages, most linked first
        self.assertEqual(counts, sorted(counts, reverse=True))
        self.assertEqual(stats["title_length_chars"]["min"], 2)  # the page titled "LD"


class PartialCrawlTests(unittest.TestCase):
    def test_partial_crawls_say_so_and_soften_orphans(self):
        analysis, found = analyze_site(issue_site(), max_pages=3)
        label = found["links.orphan_candidates"]["basis"] if "links.orphan_candidates" in found else analysis.crawl_label
        self.assertIn("partial (stopped: page-budget", label)
        self.assertIn("crawl is partial", found["links.orphan_candidates"]["note"])
        self.assertIn("(not fetched)", analysis.statistics()["observed_indexability"])

    def test_no_sitemap_skips_sitemap_checks(self):
        analysis, found = analyze_site(issue_site(), use_sitemap=False)
        self.assertFalse([c for c in found if c.startswith("sitemap.")])
        self.assertIn({"check": "sitemap.*", "count": None}, analysis.checks_run)


class CliTests(unittest.TestCase):
    def test_main_writes_a_new_analysis_file_once(self):
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            for item in issue_site().patches():
                stack.enter_context(item)
            out = Path(temporary) / "crawl"
            out.mkdir()
            crawl.Crawler("https://example.com/", out, out / "url-inventory.csv", common.Client(delay=0.2)).run()
            output = Path(temporary) / "analysis.json"
            printed = io.StringIO()
            with patch.object(analyze.sys, "argv", ["analyze_crawl.py", str(out), "--output", str(output)]), redirect_stdout(printed):
                self.assertEqual(analyze.main(), 0)
            report = json.loads(output.read_text())
            self.assertEqual(report["scope"]["stop_reason"], "queue-exhausted")
            self.assertTrue(any(c["check"] == "status.client_error" for c in report["candidates"]))
            self.assertTrue(all("severity" not in c for c in report["candidates"]))
            self.assertIn("status.client_error", printed.getvalue())
            with patch.object(analyze.sys, "argv", ["analyze_crawl.py", str(out), "--output", str(output)]), redirect_stderr(io.StringIO()):
                self.assertEqual(analyze.main(), 1)
            with patch.object(analyze.sys, "argv", ["analyze_crawl.py", str(Path(temporary) / "missing")]), redirect_stderr(io.StringIO()):
                self.assertEqual(analyze.main(), 1)


if __name__ == "__main__":
    unittest.main()
