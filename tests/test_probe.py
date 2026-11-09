"""Behavior checks for the shared fetch/robots/sitemap layer and probe.py (no sockets are opened).

Run: python3 -m unittest discover -s tests -v
"""

from contextlib import ExitStack, redirect_stdout, redirect_stderr
import importlib.util
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fakesite import FakeSite, TIMEOUT, common  # noqa: E402

spec = importlib.util.spec_from_file_location("probe", Path(__file__).resolve().parents[1] / "scripts" / "probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

URLSET = ('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
          '<url><loc>https://example.com/</loc><lastmod>2026-01-02</lastmod></url>'
          '<url><loc>https://example.com/a</loc><lastmod>yesterday</lastmod></url>'
          '<url><loc>https://example.com/a</loc></url><url><loc>/relative</loc></url></urlset>')


def standard_site():
    site = FakeSite()
    site.page("example.com", "/", title="Home", scheme="https")
    site.redirect("example.com", "/", "https://example.com/", scheme="http")
    site.redirect("www.example.com", "/", "https://example.com/")
    site.add("example.com", "/robots.txt", "User-agent: *\nDisallow: /private/\nSitemap: https://example.com/sitemap.xml\n\n"
             "User-agent: GPTBot\nDisallow: /\n", content_type="text/plain")
    site.add("example.com", "/sitemap.xml", URLSET, content_type="application/xml")
    return site


def patched(site):
    stack = ExitStack()
    for item in site.patches():
        stack.enter_context(item)
    return stack


def client(**kwargs):
    return common.Client(delay=0.2, **kwargs)


class UrlAndAddressTests(unittest.TestCase):
    def test_normalize_url(self):
        n = common.normalize_url
        self.assertEqual(n("HTTPS://Example.COM:443/a?b=1#frag"), "https://example.com/a?b=1")
        self.assertEqual(n("../x", "https://e.com/a/b/c"), "https://e.com/a/x")
        self.assertEqual(n("http://e.com"), "http://e.com/")
        self.assertEqual(n("http://e.com:8080/p"), "http://e.com:8080/p")
        for bad in ("mailto:a@b.c", "javascript:void(0)", "ftp://e.com/", "https://u:p@e.com/", "//", "", "https://e.com:99999/"):
            self.assertIsNone(n(bad))

    def test_private_and_metadata_addresses_are_refused(self):
        with patch.object(common, "resolve", return_value=["10.0.0.5"]):
            with self.assertRaises(common.BlockedTarget):
                common.check_addresses("intranet.example.com", 443)
        with patch.object(common, "resolve", return_value=["127.0.0.1"]):
            self.assertEqual(common.check_addresses("localhost", 3000, {("localhost", 3000)}), ["127.0.0.1"])
            with self.assertRaises(common.BlockedTarget):
                common.check_addresses("localhost", 4000, {("localhost", 3000)})  # adjacent port stays blocked
        with patch.object(common, "resolve", return_value=["169.254.169.254"]):
            with self.assertRaises(common.BlockedTarget):
                common.check_addresses("localhost", 3000, {("localhost", 3000)})  # metadata never allowed
        with patch.object(common, "resolve", return_value=["93.184.216.34", "10.0.0.1"]):
            with self.assertRaises(common.BlockedTarget):
                common.check_addresses("mixed.example.com", 443)  # every answer must be public


class RobotsTests(unittest.TestCase):
    def test_longest_rule_wildcards_and_ties(self):
        robots = common.Robots("User-agent: *\nDisallow: /private/\nAllow: /private/ok\nDisallow: /*.pdf$\nDisallow: /tie\nAllow: /tie\n")
        allowed = lambda path: robots.allowed(path, "anybot")[0]  # noqa: E731
        self.assertFalse(allowed("/private/x"))
        self.assertTrue(allowed("/private/ok"))
        self.assertFalse(allowed("/docs/file.pdf"))
        self.assertTrue(allowed("/docs/file.pdf?x=1"))  # `$` anchors at the end of path+query, so this URL does not match
        self.assertTrue(allowed("/tie"))  # equal length: Allow wins
        self.assertTrue(allowed("/other"))
        self.assertTrue(robots.allowed("/robots.txt", "anybot")[0])

    def test_group_selection_and_defaults(self):
        robots = common.Robots("User-agent: Googlebot\nUser-agent: Bingbot\nDisallow: /g/\n\nUser-agent: Googlebot-Image\nDisallow: /img/\n\n"
                               "User-agent: *\nDisallow:\nCrawl-delay: 4\nSitemap: https://e.com/s.xml\n")
        self.assertFalse(robots.allowed("/g/x", "Bingbot")[0])
        self.assertFalse(robots.allowed("/g/x", "Googlebot")[0])
        self.assertEqual(robots.group_agent("Googlebot-Image"), "googlebot-image")
        self.assertTrue(robots.allowed("/g/x", "Googlebot-Image")[0])  # the more specific group replaces the general one
        self.assertEqual(robots.group_agent("Googlebot-News"), "googlebot")
        self.assertTrue(robots.allowed("/g/x", "SomeBot")[0])  # empty Disallow allows everything
        self.assertEqual(robots.crawl_delay("SomeBot"), 4.0)
        self.assertEqual(robots.sitemaps, ["https://e.com/s.xml"])
        self.assertEqual(common.Robots("").allowed("/x")[0], True)
        self.assertFalse(common.Robots("User-agent: *\nDisallow: /\n").allowed("/x")[0])

    def test_fetch_robots_status_semantics(self):
        for status, expected in ((200, "ok"), (404, "not-found-allow-all"), (410, "not-found-allow-all"), (403, "not-found-allow-all"),
                                 (500, "unreachable"), (503, "unreachable"), (429, "unreachable")):
            site = FakeSite().add("example.com", "/robots.txt", "User-agent: *\nDisallow: /x\n", status=status, content_type="text/plain")
            with patched(site):
                info = common.fetch_robots("https://example.com", client())
            self.assertEqual(info["status"], expected, status)
        site = FakeSite().fail("example.com", "/robots.txt", TIMEOUT)
        with patched(site):
            self.assertEqual(common.fetch_robots("https://example.com", client())["status"], "unreachable")
        site = FakeSite().add("example.com", "/robots.txt", "<!DOCTYPE html><html><body>Nope</body></html>")
        with patched(site):
            info = common.fetch_robots("https://example.com", client())
        self.assertTrue(info["looks_like_html"])


class FetchTests(unittest.TestCase):
    def fetch(self, site, url, **kwargs):
        with patched(site):
            return common.Client(delay=0.2, **kwargs.pop("client", {}))(url, **kwargs)

    def test_follows_redirects_and_records_the_chain(self):
        site = FakeSite().redirect("a.com", "/", "http://a.com/x").redirect("a.com", "/x", "https://b.com/y", 302).page("b.com", "/y")
        result = self.fetch(site, "http://a.com/")
        self.assertEqual((result["status"], result["final_url"]), (200, "https://b.com/y"))
        self.assertEqual([(c["status"], c["location"]) for c in result["redirect_chain"]], [(301, "http://a.com/x"), (302, "https://b.com/y")])

    def test_redirect_limits_loops_and_scope(self):
        loop = FakeSite().redirect("a.com", "/", "http://a.com/b").redirect("a.com", "/b", "http://a.com/")
        self.assertEqual(self.fetch(loop, "http://a.com/")["stopped"], "redirect-loop")
        long = FakeSite()
        for i in range(8):
            long.redirect("a.com", "/%d" % i, "http://a.com/%d" % (i + 1))
        result = self.fetch(long, "http://a.com/0", max_redirects=3)
        self.assertEqual((result["stopped"], len(result["redirect_chain"])), ("too-many-redirects", 4))
        off = FakeSite().redirect("a.com", "/", "https://other.com/").page("other.com", "/")
        result = self.fetch(off, "http://a.com/", allowed_hosts={"a.com"})
        self.assertEqual((result["stopped"], result["redirect_to"], result["final_url"]), ("off-scope", "https://other.com/", "http://a.com/"))
        self.assertNotIn("other.com", [r["host"] for r in off.log])

    def test_no_follow_reports_the_target_without_requesting_it(self):
        site = FakeSite().redirect("a.com", "/old", "/new").page("a.com", "/new")
        result = self.fetch(site, "http://a.com/old", follow=False)
        self.assertEqual((result["status"], result["redirect_to"], len(site.log)), (301, "http://a.com/new", 1))

    def test_blocked_targets_never_reach_the_connection(self):
        site = FakeSite()
        site.addresses["intranet.com"] = ["10.1.2.3"]
        result = self.fetch(site, "https://intranet.com/")
        self.assertEqual((result["error"], result["status"], site.log), ("blocked-target", None, []))
        site.redirect("a.com", "/", "http://intranet.com/")
        result = self.fetch(site, "http://a.com/")
        self.assertEqual((result["error"], result["redirect_to"]), ("blocked-target", "http://intranet.com/"))

    def test_connections_use_the_validated_address(self):
        site = FakeSite(address="93.184.216.34").page("a.com", "/")
        self.fetch(site, "http://a.com/")
        self.assertEqual(site.last_ip, "93.184.216.34")

    def test_every_validated_address_is_offered_and_unreachable_ones_are_skipped(self):
        site = FakeSite().page("a.com", "/")
        site.addresses["a.com"] = ["2606:2800:220:1::1", "93.184.216.34"]
        self.fetch(site, "http://a.com/")
        self.assertEqual(site.last_addresses, ["2606:2800:220:1::1", "93.184.216.34"])
        tried = []

        def refuse_first(address, timeout):
            tried.append(address[0])
            if address[0].startswith("2606"):
                raise ConnectionRefusedError()
            return "connected"

        with patch.object(common.socket, "create_connection", refuse_first):
            self.assertEqual(common.connect_pinned(site.last_addresses, 80, 5), "connected")
            with self.assertRaises(OSError):
                common.connect_pinned(["2606:2800:220:1::1"], 80, 5)
        self.assertEqual(tried, ["2606:2800:220:1::1", "93.184.216.34", "2606:2800:220:1::1"])

    def test_cookies_are_reduced_to_names(self):
        site = FakeSite().add("a.com", "/", "<html></html>", headers=[("Set-Cookie", "session=SECRETVALUE; Path=/"), ("Set-Cookie", "pref=1")])
        result = self.fetch(site, "http://a.com/")
        self.assertNotIn("SECRETVALUE", json.dumps(result["headers"]))
        self.assertIn("session", result["headers"]["set-cookie"])

    def test_gzip_bodies_are_decoded_and_capped(self):
        text = b"<html>" + b"x" * 50000 + b"</html>"
        packed = zlib.compress(text, wbits=31)
        site = FakeSite().add("a.com", "/", packed, headers={"Content-Encoding": "gzip"})
        self.assertEqual(self.fetch(site, "http://a.com/")["body"], text)
        capped = self.fetch(site, "http://a.com/", max_bytes=1000)
        self.assertEqual((len(capped["body"]), capped["body_truncated"]), (1000, True))
        bad = FakeSite().add("a.com", "/", b"not gzip", headers={"Content-Encoding": "gzip"})
        self.assertTrue(self.fetch(bad, "http://a.com/")["body_decode_error"])

    def test_body_is_read_only_for_wanted_types(self):
        site = FakeSite().add("a.com", "/f.pdf", b"%PDF-1.4", content_type="application/pdf")
        self.assertEqual(self.fetch(site, "http://a.com/f.pdf", read_types=("text/html",))["body"], b"")
        self.assertEqual(self.fetch(site, "http://a.com/f.pdf", read_types=None)["body"], b"%PDF-1.4")
        self.assertEqual(self.fetch(site, "http://a.com/f.pdf", read_types=())["body"], b"")

    def test_network_failures_are_classified_not_raised(self):
        for error, expected in ((TIMEOUT, "timeout"), (ConnectionRefusedError(), "connection-error"), (socket.gaierror(), "dns-error")):
            site = FakeSite().fail("a.com", "/", error)
            self.assertEqual(self.fetch(site, "http://a.com/")["error"], expected)

    def test_requests_are_counted_and_paced_per_host(self):
        site = FakeSite().redirect("a.com", "/", "http://a.com/x").page("a.com", "/x")
        waits = []
        with patched(site), patch.object(common.time, "sleep", waits.append):
            c = common.Client(delay=1.0)
            c("http://a.com/")
        self.assertEqual(c.requests, 2)  # the redirect hop counts
        self.assertTrue(waits and 0 < waits[0] <= 1.0)


class SitemapTests(unittest.TestCase):
    def test_urlset_stats(self):
        parsed = common.parse_sitemap(URLSET.encode())
        self.assertEqual(parsed["kind"], "urlset")
        self.assertEqual(parsed["stats"]["url_count"], 4)
        self.assertEqual((parsed["stats"]["duplicate_urls"], parsed["stats"]["invalid_loc"], parsed["stats"]["lastmod_invalid"]), (1, 1, 1))

    def test_index_text_feed_and_gzip(self):
        index = b'<sitemapindex xmlns="x"><sitemap><loc>https://e.com/1.xml</loc></sitemap></sitemapindex>'
        self.assertEqual(common.parse_sitemap(index)["children"], ["https://e.com/1.xml"])
        self.assertEqual(common.parse_sitemap(b"https://e.com/a\nnot a url\nhttps://e.com/b\n")["stats"]["url_count"], 2)
        self.assertEqual(common.parse_sitemap(zlib.compress(URLSET.encode(), wbits=31))["kind"], "urlset")
        atom = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><link href="https://e.com/p"/></entry></feed>'
        self.assertEqual(common.parse_sitemap(atom)["urls"], [("https://e.com/p", None)])

    def test_html_invalid_and_entity_declarations_are_not_sitemaps(self):
        self.assertEqual(common.parse_sitemap(b"<!DOCTYPE html><html><body>404</body></html>")["kind"], "html-not-sitemap")
        self.assertEqual(common.parse_sitemap(b"<urlset><url>")["kind"], "invalid")
        bomb = b'<?xml version="1.0"?><!DOCTYPE lol [<!ENTITY a "aaaa">]><urlset><url><loc>&a;</loc></url></urlset>'
        refused = common.parse_sitemap(bomb)
        self.assertEqual((refused["kind"], refused["urls"]), ("invalid", []))
        self.assertEqual(common.parse_sitemap(b"<html2/>")["kind"], "invalid")

    def test_discovery_follows_indexes_once_and_stays_in_scope(self):
        site = FakeSite()
        site.add("example.com", "/index.xml", '<sitemapindex xmlns="x"><sitemap><loc>https://example.com/a.xml</loc></sitemap>'
                 '<sitemap><loc>https://example.com/a.xml</loc></sitemap><sitemap><loc>https://elsewhere.com/b.xml</loc></sitemap></sitemapindex>',
                 content_type="application/xml")
        site.add("example.com", "/a.xml", URLSET, content_type="application/xml")
        with patched(site):
            records, entries = common.discover_sitemaps("https://example.com", ["https://example.com/index.xml"], client(), {"example.com"})
        self.assertEqual([(r["source"], r["kind"], r["skipped"]) for r in records],
                         [("robots", "sitemapindex", None), ("index", "urlset", None), ("index", None, "invalid-or-duplicate"), ("index", None, "off-scope")])
        self.assertEqual(len(entries), 4)
        self.assertNotIn("elsewhere.com", [r["host"] for r in site.log])

    def test_conventional_locations_and_file_limit(self):
        site = FakeSite()
        with patched(site):
            records, entries = common.discover_sitemaps("https://example.com", [], client(), {"example.com"})
        self.assertEqual([(r["source"], r["kind"]) for r in records], [("conventional", "unavailable")] * 2)
        many = FakeSite().add("example.com", "/i.xml", '<sitemapindex xmlns="x">' + "".join(
            "<sitemap><loc>https://example.com/s%d.xml</loc></sitemap>" % i for i in range(10)) + "</sitemapindex>", content_type="application/xml")
        with patched(many):
            records, _ = common.discover_sitemaps("https://example.com", ["https://example.com/i.xml"], client(), {"example.com"}, max_files=3)
        self.assertEqual(records[-1]["skipped"], "file-limit")


class ProbeTests(unittest.TestCase):
    def run_probe(self, site, url="https://example.com/", **kwargs):
        with tempfile.TemporaryDirectory() as temporary, patched(site):
            out = Path(temporary) / "probe"
            out.mkdir()
            report = probe.probe(url, common.Client(delay=0.2, **kwargs.pop("client", {})), probe.DEFAULT_AGENTS, True, out, frozenset())
            files = sorted(p.name for p in out.iterdir())
            return report, files

    def codes(self, report):
        return {o["code"] for o in report["observations"]}

    def test_healthy_site(self):
        report, files = self.run_probe(standard_site())
        self.assertEqual(report["fetch"]["status"], 200)
        self.assertEqual(report["robots"]["status"], "ok")
        self.assertEqual(report["robots"]["declared_sitemaps"], ["https://example.com/sitemap.xml"])
        self.assertEqual(report["sitemaps"]["total_urls"], 4)
        access = {a["agent"]: a for a in report["robots"]["agent_access"]}
        self.assertTrue(access["*"]["target_allowed"])
        self.assertFalse(access["GPTBot"]["root_allowed"])
        self.assertEqual(access["GPTBot"]["matched_rule"], "/")
        self.assertEqual(self.codes(report), {"robots.agents_blocked_from_root"})
        self.assertEqual({v["final_url"] for v in report["variants"]}, {"https://example.com/"})
        self.assertEqual(report["missing_page"]["status"], 404)
        self.assertEqual(files[:3], ["main.html", "robots.txt", "sitemap-01.xml"])

    def test_problems_become_candidate_observations(self):
        site = standard_site()
        site.pages.pop(("*", "example.com", "/sitemap.xml"))
        site.add("example.com", "/sitemap.xml", "<!DOCTYPE html><html>Not found</html>")
        site.pages[("*", "www.example.com", "/")] = site.pages[("https", "example.com", "/")]  # www serves its own copy
        site.add("example.com", "/robots.txt", "User-agent: *\nDisallow: /\n", content_type="text/plain")
        site.default = (200, [("Content-Type", "text/html")], b"<html>OK</html>")
        report, _ = self.run_probe(site)
        self.assertTrue({"robots.blocks_target", "sitemap.problem", "variants.divergent_final_urls", "missing_page.soft_404_candidate",
                         "robots.no_sitemap_declared"} <= self.codes(report), self.codes(report))

    def test_redirect_and_header_observations(self):
        site = standard_site()
        site.redirect("example.com", "/old", "/mid", 302, scheme="https").redirect("example.com", "/mid", "/mid2", 301, scheme="https")
        site.redirect("example.com", "/mid2", "/new", 301, scheme="https")
        site.page("example.com", "/new", headers={"X-Robots-Tag": "noindex"}, scheme="https")
        report, _ = self.run_probe(site, "https://example.com/old")
        self.assertTrue({"redirect.long_chain", "redirect.temporary_in_chain", "headers.noindex"} <= self.codes(report), self.codes(report))

    def test_robots_unreachable_is_reported_not_assumed_open(self):
        site = standard_site()
        site.add("example.com", "/robots.txt", "down", status=503, content_type="text/plain")
        report, _ = self.run_probe(site)
        self.assertEqual(report["robots"]["status"], "unreachable")
        self.assertIn("robots.unreachable", self.codes(report))

    def test_failed_main_fetch_stops_early(self):
        site = FakeSite().fail("example.com", "*", TIMEOUT)
        report, _ = self.run_probe(site)
        self.assertEqual(report["fetch"]["error"], "timeout")
        self.assertNotIn("robots", report)

    def test_cli_refuses_existing_directory_and_local_targets(self):
        with tempfile.TemporaryDirectory() as temporary:
            argv = ["probe.py", "https://example.com/", "--output-dir", temporary]
            with patch.object(probe.sys, "argv", argv), redirect_stderr(io.StringIO()):
                self.assertEqual(probe.main(), 1)
            site = FakeSite()
            site.addresses["localhost"] = ["127.0.0.1"]
            site.page("localhost", "/", scheme="http")
            out = Path(temporary) / "blocked"
            with patch.object(probe.sys, "argv", ["probe.py", "http://localhost:3000/", "--output-dir", str(out)]), patched(site), redirect_stdout(io.StringIO()):
                self.assertEqual(probe.main(), 1)
            self.assertEqual(json.loads((out / "probe.json").read_text())["fetch"]["error"], "blocked-target")
            self.assertEqual(site.log, [])
            out = Path(temporary) / "local"
            argv = ["probe.py", "http://localhost:3000/", "--output-dir", str(out), "--allow-local", "http://localhost:3000"]
            with patch.object(probe.sys, "argv", argv), patched(site), redirect_stdout(io.StringIO()):
                self.assertEqual(probe.main(), 0)
            report = json.loads((out / "probe.json").read_text())
            self.assertEqual((report["fetch"]["status"], report["local_exception"], "variants" in report), (200, ["localhost:3000"], False))


if __name__ == "__main__":
    unittest.main()
