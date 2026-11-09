"""Behavior checks for evidence extraction and measurement failure handling.

Run: python3 -m unittest discover -s tests -v
"""

from contextlib import redirect_stdout, redirect_stderr
import importlib.util
import io
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


psi = load("pagespeed_check")
html = load("parse_html")


def report():
    return {"lighthouseVersion": "13.0.0", "requestedUrl": "https://example.com/",
            "finalUrl": "https://example.com/", "fetchTime": "2026-11-09T12:00:00Z",
            "configSettings": {"formFactor": "mobile"},
            "categories": {"performance": {"score": 0}, "seo": {"score": None}},
            "audits": {"largest-contentful-paint": {"numericValue": 3210, "numericUnit": "millisecond", "score": 0.5},
                       "manual": {"score": None, "scoreDisplayMode": "manual"}}}


class ScriptTests(unittest.TestCase):
    def test_zero_score_missing_metrics_and_no_field_data(self):
        result = psi.summarize(report())
        self.assertEqual(result["scores"], {"performance": 0, "seo": None})
        self.assertEqual(result["lab_metrics"]["LCP"]["value"], 3210)
        self.assertIsNone(result["lab_metrics"]["TBT"]["value"])
        self.assertFalse(result["field_data"]["url"]["available"])
        self.assertEqual([a["id"] for a in result["failed_audits"]], ["largest-contentful-paint"])

    def test_origin_field_data_does_not_replace_url_data(self):
        data = {"lighthouseResult": report(), "originLoadingExperience": {
            "id": "https://example.com", "metrics": {"CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 12}}}}
        result = psi.summarize(data)
        self.assertFalse(result["field_data"]["url"]["available"])
        self.assertTrue(result["field_data"]["origin"]["available"])
        self.assertEqual(result["field_data"]["origin"]["metrics"]["CUMULATIVE_LAYOUT_SHIFT_SCORE"]["percentile"], 12)
        self.assertIsNone(result["field_data"]["origin"]["collection_period"])

    def test_runtime_and_provider_errors_are_not_measurements(self):
        data = report()
        data["runtimeError"] = {"code": "NO_FCP"}
        self.assertEqual(psi.summarize(data)["status"], "error")
        for data in ({"error": {"code": 429}}, {}, []):
            with self.assertRaises(ValueError):
                psi.summarize(data)

    def test_private_targets_and_credentials_rejected_before_request(self):
        for target in ("http://localhost:3000", "http://127.0.0.1", "http://[::1]", "https://user:secret@example.com", "file:///tmp/page"):
            with self.assertRaises(ValueError):
                psi.public_url(target)
        address = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443))]
        with patch.object(psi.socket, "getaddrinfo", return_value=address):
            with self.assertRaises(ValueError):
                psi.public_url("https://private.example.com")

    def test_collect_encodes_target_and_does_not_leak_key_on_error(self):
        opener = unittest.mock.Mock()
        opener.open.side_effect = HTTPError("secret-url", 429, "secret-key", {}, None)
        with patch.object(psi, "build_opener", return_value=opener), patch.dict(psi.os.environ, {"PAGESPEED_API_KEY": "secret-key"}):
            with self.assertRaisesRegex(ValueError, "PageSpeed HTTP 429") as failure:
                psi.collect("https://example.com/?a=1&b=2", "mobile", 120)
        self.assertNotIn("secret", str(failure.exception))
        request = opener.open.call_args.args[0]
        self.assertNotIn("secret-key", request.full_url)
        self.assertIn("%26b%3D2", request.full_url)

    def test_both_devices_preserve_partial_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "evidence"
            argv = ["pagespeed_check.py", "https://example.com", "--strategy", "both", "--output-dir", str(destination)]
            with patch.object(psi.sys, "argv", argv), patch.object(psi, "public_url"), patch.object(psi, "collect", side_effect=[ValueError("PageSpeed HTTP 429."), {"lighthouseResult": report()}]), redirect_stdout(io.StringIO()):
                self.assertEqual(psi.main(), 1)
            summary = json.loads((destination / "summary.json").read_text())
            self.assertEqual([r["status"] for r in summary["runs"]], ["error", "measured"])
            self.assertIn("429", summary["runs"][0]["error"])
            self.assertTrue((destination / "desktop.raw.json").is_file())

    def test_offline_import_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "lh.json"
            source.write_text(json.dumps(report()))
            destination = Path(temporary) / "imported"
            argv = ["pagespeed_check.py", "--input", str(source), "--output-dir", str(destination)]
            with patch.object(psi.sys, "argv", argv), patch.object(psi, "collect") as collect, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(psi.main(), 0)
                original = (destination / "summary.json").read_bytes()
                self.assertEqual(psi.main(), 1)
                self.assertEqual((destination / "summary.json").read_bytes(), original)
                collect.assert_not_called()

    def test_html_preserves_duplicates_alt_and_jsonld_errors(self):
        markup = '''<html lang="pl"><base href="/shop/"><title>A &amp; B</title><title>Duplicate</title>
        <meta name="robots" content="noindex"><link rel="CANONICAL" href="item">
        <h1>Hello <em>world</em></h1><a href="../about">About <b>us</b></a>
        <img src="a"><img src="b" alt=""><img src="c" alt="Photo">
        <script type="application/ld+json">{"@type":"Thing"}</script>
        <script type="application/ld+json">broken</script></html>'''
        data = html.extract(markup, "https://example.com/start")
        self.assertEqual(data["titles"], ["A & B", "Duplicate"])
        self.assertEqual(data["resolved_canonicals"], ["https://example.com/shop/item"])
        self.assertEqual(data["headings"], [{"level": 1, "text": "Hello world"}])
        self.assertEqual(data["links"][0]["resolved_href"], "https://example.com/about")
        self.assertEqual([i["alt"] for i in data["images"]], [None, "", "Photo"])
        self.assertIsNone(data["json_ld"][0]["syntax_error"])
        self.assertIsNotNone(data["json_ld"][1]["syntax_error"])


class ExtractionTests(unittest.TestCase):
    def test_svg_titles_are_not_document_titles(self):
        markup = '<html><head><title>Real</title></head><body><svg><title>Icon</title><text>glyph</text></svg><p>Body copy</p></body></html>'
        data = html.extract(markup)
        self.assertEqual(data["titles"], ["Real"])
        self.assertEqual(data["visible_text"]["chars"], len("Body copy"))

    def test_image_link_anchor_text_uses_alt_and_flags_missing_alt(self):
        markup = ('<a href="/a"><img src="a.png" alt=" Company  logo "></a><a href="/b"><img src="b.png"></a>'
                  '<a href="/c">Plain <b>text</b></a>')
        links = html.extract(markup)["links"]
        self.assertEqual((links[0]["text"], links[0]["image_alts"], links[0]["anchor_text"]), ("", [" Company  logo "], "Company logo"))
        self.assertEqual((links[1]["image_alts"], links[1]["anchor_text"]), ([None], ""))
        self.assertEqual((links[2]["image_alts"], links[2]["anchor_text"]), ([], "Plain text"))

    def test_visible_text_excludes_non_content_and_keeps_block_words_apart(self):
        markup = ('<html><head><title>T</title><style>p{}</style></head><body><script>var hidden = 1</script>'
                  '<noscript>No script</noscript><div>One two</div><div>three</div></body></html>')
        data = html.extract(markup)
        self.assertEqual(data["visible_text"], {"chars": len("One two three"), "words": 3, "excludes": data["visible_text"]["excludes"]})

    def test_rendering_hint_needs_marker_and_little_text(self):
        shell = '<html><body><div id="root"></div><noscript>You need to enable JavaScript.</noscript></body></html>'
        hint = html.extract(shell)["rendering_hint"]
        self.assertEqual(hint["shell_markers"], ['id="root"', "noscript-javascript-notice"])
        self.assertTrue(hint["possible_client_rendered"])
        rendered = '<html><body><div id="root"><p>' + "word " * 200 + "</p></div></body></html>"
        self.assertFalse(html.extract(rendered)["rendering_hint"]["possible_client_rendered"])
        self.assertFalse(html.extract("<html><body><p>Short page</p></body></html>")["rendering_hint"]["possible_client_rendered"])


def detailed_report():
    data = report()
    audits = data["audits"]
    node = {"type": "node", "selector": "img.hero", "snippet": '<img class="hero">', "nodeLabel": "img", "path": "dropped"}
    audits["unsized-images"] = {"title": "Unsized images", "score": 0, "scoreDisplayMode": "binary",
                                "details": {"type": "table", "items": [{"url": "https://example.com/hero.jpg", "node": node, "ignored": 1}]}}
    audits["render-blocking-resources"] = {"title": "Render blocking", "score": 0.4, "scoreDisplayMode": "metricSavings",
                                           "details": {"type": "opportunity", "overallSavingsMs": 300,
                                                       "items": [{"url": "https://example.com/%d.css" % i, "wastedMs": i} for i in range(15)]}}
    audits["bootup-time"] = {"title": "Boot-up", "score": 0.7, "details": "unexpected shape"}
    audits["largest-contentful-paint-element"] = {
        "title": "LCP element", "score": None, "scoreDisplayMode": "informative", "displayValue": "3,210 ms",
        "details": {"type": "list", "items": [
            {"type": "table", "items": [{"node": {"type": "node", "selector": "div.hero > img"}}]},
            {"type": "table", "items": [{"phase": "TTFB", "timing": 600, "percent": "19%"}]}]}}
    audits["layout-shift-elements"] = {
        "title": "Layout shifts", "score": None, "scoreDisplayMode": "informative",
        "details": {"type": "table", "items": [{"node": {"type": "node", "selector": "div.banner"}, "score": 0.12}]}}
    audits["link-text"] = {"title": "Links have descriptive text", "score": 0, "scoreDisplayMode": "binary",
                           "details": {"type": "table", "items": [
                               {"href": "https://example.com/x" + "y" * 400, "text": "click here",
                                "source": {"type": "source-location", "url": "https://example.com/app.js", "line": 12},
                                "total": {"type": "numeric", "value": 5}}]}}
    return data


class DetailAndBatchTests(unittest.TestCase):
    def test_failed_audits_carry_bounded_items_and_rating(self):
        result = psi.summarize(detailed_report())
        failed = {a["id"]: a for a in result["failed_audits"]}
        # Sorted by (score, id): the two score-0 audits come first, alphabetically.
        self.assertEqual([a["id"] for a in result["failed_audits"]][:2], ["link-text", "unsized-images"])
        self.assertEqual(failed["unsized-images"]["rating"], "fail")
        self.assertEqual(failed["largest-contentful-paint"]["rating"], "average")
        self.assertEqual(failed["unsized-images"]["items"], [{"url": "https://example.com/hero.jpg", "node": {
            "selector": "img.hero", "snippet": '<img class="hero">', "nodeLabel": "img"}}])
        blocking = failed["render-blocking-resources"]
        self.assertEqual((len(blocking["items"]), blocking["items_total"], blocking["estimated_savings_ms"]), (psi.ITEM_LIMIT, 15, 300))
        link = failed["link-text"]["items"][0]
        self.assertEqual(len(link["href"]), psi.TEXT_LIMIT)
        self.assertEqual((link["source"], link["total"]), ("https://example.com/app.js:12", 5))
        # An unexpected details shape degrades to no items instead of failing the whole summary.
        self.assertEqual((failed["bootup-time"]["items"], failed["bootup-time"]["items_total"]), ([], 0))

    def test_informative_audits_are_kept_as_diagnostics(self):
        diagnostics = psi.summarize(detailed_report())["diagnostics"]
        lcp = diagnostics["lcp_element"][0]
        self.assertEqual(lcp["items"], [{"node": {"selector": "div.hero > img"}}, {"phase": "TTFB", "timing": 600, "percent": "19%"}])
        self.assertEqual(diagnostics["layout_shifts"][0]["items"], [{"node": {"selector": "div.banner"}, "score": 0.12}])
        self.assertEqual(psi.summarize(report())["diagnostics"], {})

    def test_batch_measures_each_url_and_indexes_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            urls = Path(temporary) / "urls.txt"
            urls.write_text("# templates\nhttps://example.com/\n\nhttps://example.com/a?b=1\nhttps://example.com/\n")
            destination = Path(temporary) / "psi"
            argv = ["pagespeed_check.py", "--urls-file", str(urls), "--output-dir", str(destination)]
            with patch.object(psi.sys, "argv", argv), patch.object(psi, "public_url") as check, \
                    patch.object(psi, "collect", side_effect=[{"lighthouseResult": report()}, ValueError("PageSpeed HTTP 429.")]), \
                    redirect_stdout(io.StringIO()):
                self.assertEqual(psi.main(), 1)
            index = json.loads((destination / "index.json").read_text())
            self.assertEqual([e["directory"] for e in index["urls"]], ["01-example-com", "02-example-com-a"])
            self.assertEqual([e["status"] for e in index["urls"]], ["measured", "error"])
            self.assertTrue((destination / "01-example-com" / "mobile.raw.json").is_file())
            self.assertEqual(json.loads((destination / "02-example-com-a" / "summary.json").read_text())["target_url"], "https://example.com/a?b=1")
            self.assertEqual(check.call_count, 2)  # the duplicate line was dropped

    def test_batch_validates_every_url_before_any_request(self):
        def reject_local(value):
            if "localhost" in value:
                raise ValueError("local")

        with tempfile.TemporaryDirectory() as temporary:
            urls = Path(temporary) / "urls.txt"
            urls.write_text("https://example.com/\nhttp://localhost:3000/\n")
            destination = Path(temporary) / "psi"
            argv = ["pagespeed_check.py", "--urls-file", str(urls), "--output-dir", str(destination)]
            with patch.object(psi.sys, "argv", argv), patch.object(psi, "public_url", side_effect=reject_local), \
                    patch.object(psi, "collect") as collect, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(psi.main(), 1)
            collect.assert_not_called()
            self.assertFalse(destination.exists())

    def test_batch_limit_and_exclusive_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            urls = Path(temporary) / "urls.txt"
            urls.write_text("\n".join("https://example.com/%d" % i for i in range(psi.MAX_BATCH + 1)))
            argv = ["pagespeed_check.py", "--urls-file", str(urls), "--output-dir", str(Path(temporary) / "psi")]
            with patch.object(psi.sys, "argv", argv), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(psi.main(), 1)
            self.assertFalse((Path(temporary) / "psi").exists())
            argv = ["pagespeed_check.py", "https://example.com", "--urls-file", str(urls), "--output-dir", str(Path(temporary) / "other")]
            with patch.object(psi.sys, "argv", argv), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as stop:
                    psi.main()
            self.assertEqual(stop.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
