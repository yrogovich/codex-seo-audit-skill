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


if __name__ == "__main__":
    unittest.main()
