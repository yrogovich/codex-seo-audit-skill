"""Behavior checks for crux_check.py, using fixtures shaped like the documented CrUX API responses (no network).

Run: python3 -m unittest discover -s tests -v
"""

from contextlib import redirect_stdout, redirect_stderr
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
spec = importlib.util.spec_from_file_location("crux_check", Path(__file__).resolve().parents[1] / "scripts" / "crux_check.py")
crux = importlib.util.module_from_spec(spec)
spec.loader.exec_module(crux)

PERIOD = {"firstDate": {"year": 2026, "month": 10, "day": 5}, "lastDate": {"year": 2026, "month": 11, "day": 1}}


def bins(*densities):
    edges = [(0, 100), (100, 200), (200, None)]
    return [dict({"start": s, "density": d}, **({"end": e} if e else {})) for (s, e), d in zip(edges, densities)]


def current(lcp=2300, inp=150, cls="0.04", include_inp=True):
    metrics = {"largest_contentful_paint": {"histogram": bins(0.81, 0.12, 0.07), "percentiles": {"p75": lcp}},
               "cumulative_layout_shift": {"histogram": bins(0.9, 0.06, 0.04), "percentiles": {"p75": cls}},  # CLS p75 arrives as a string
               "experimental_time_to_first_byte": {"histogram": bins(0.7, 0.2, 0.1), "percentiles": {"p75": 700}}}
    if include_inp:
        metrics["interaction_to_next_paint"] = {"histogram": bins(0.8, 0.1, 0.1), "percentiles": {"p75": inp}}
    return {"record": {"key": {"formFactor": "PHONE"}, "metrics": metrics, "collectionPeriod": PERIOD},
            "urlNormalizationDetails": {"originalUrl": "https://example.com/a?x=1", "normalizedUrl": "https://example.com/a"}}


def history():
    return {"record": {"key": {}, "collectionPeriods": [{"firstDate": {"year": 2026, "month": 9, "day": 7}, "lastDate": {"year": 2026, "month": 10, "day": 4}}, dict(PERIOD)],
                       "metrics": {"largest_contentful_paint": {"percentilesTimeseries": {"p75s": [None, 2600]}},
                                   "cumulative_layout_shift": {"percentilesTimeseries": {"p75s": ["0.05", "0.30"]}}}}}


def run(argv, post, key="test-key"):
    out, err = io.StringIO(), io.StringIO()
    env = {"CRUX_API_KEY": key} if key else {}
    with patch.object(crux.sys, "argv", ["crux_check.py", *argv]), patch.object(crux, "post", side_effect=post) as mocked, \
            patch.object(crux, "public_url"), patch.dict(crux.os.environ, env, clear=True), redirect_stdout(out), redirect_stderr(err):
        code = crux.main()
    return code, mocked, err.getvalue()


class CruxTests(unittest.TestCase):
    def test_current_summary_rates_each_metric_and_keeps_the_period(self):
        summary = crux.summarize_current(current(inp=250))
        metrics = summary["metrics"]
        self.assertEqual((metrics["LCP"]["p75"], metrics["LCP"]["rating"]), (2300, "good"))
        self.assertEqual((metrics["INP"]["rating"], metrics["CLS"]["p75"], metrics["CLS"]["rating"]), ("needs-improvement", 0.04, "good"))
        self.assertEqual(metrics["LCP"]["distribution"], {"good": 0.81, "needs_improvement": 0.12, "poor": 0.07})
        self.assertEqual(summary["collection_period"], {"first_date": "2026-10-05", "last_date": "2026-11-01"})
        self.assertEqual(summary["core_web_vitals"], "failed")
        self.assertEqual(summary["normalization"]["normalizedUrl"], "https://example.com/a")

    def test_assessment_needs_all_three_core_metrics(self):
        self.assertEqual(crux.summarize_current(current())["core_web_vitals"], "passed")
        self.assertEqual(crux.summarize_current(current(include_inp=False))["core_web_vitals"], "incomplete")
        self.assertEqual(crux.summarize_current(current(lcp=4100, include_inp=False))["core_web_vitals"], "failed")
        self.assertEqual(crux.rate("LCP", 2500), "good")
        self.assertEqual(crux.rate("LCP", 4000), "needs-improvement")
        self.assertEqual(crux.rate("LCP", 4001), "poor")
        self.assertIsNone(crux.rate("CLS", None))

    def test_history_series_keep_gaps(self):
        summary = crux.summarize_history(history())
        lcp, cls = summary["metrics"]["LCP"], summary["metrics"]["CLS"]
        self.assertEqual((lcp["p75_series"], lcp["periods_with_data"], lcp["latest"], lcp["latest_rating"]), ([None, 2600], 1, 2600, "needs-improvement"))
        self.assertEqual((cls["earliest"], cls["latest"], cls["latest_rating"]), (0.05, 0.3, "poor"))
        self.assertEqual(summary["periods"][1]["last_date"], "2026-11-01")

    def test_url_and_origin_are_separate_requests_per_device(self):
        bodies = []

        def post(endpoint, body, key, timeout):
            bodies.append((endpoint.rsplit(":", 1)[1], body))
            return current()

        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "crux"
            code, _, _ = run(["https://example.com/a", "--also-origin", "--form-factor", "phone", "--form-factor", "desktop", "--output-dir", str(out)], post)
            summary = json.loads((out / "summary.json").read_text())
            self.assertTrue((out / "current-url-phone.raw.json").is_file() and (out / "current-origin-desktop.raw.json").is_file())
        self.assertEqual(code, 0)
        self.assertEqual(bodies, [("queryRecord", {"url": "https://example.com/a", "formFactor": "PHONE"}),
                                  ("queryRecord", {"origin": "https://example.com", "formFactor": "PHONE"}),
                                  ("queryRecord", {"url": "https://example.com/a", "formFactor": "DESKTOP"}),
                                  ("queryRecord", {"origin": "https://example.com", "formFactor": "DESKTOP"})])
        self.assertEqual([(r["target"], r["form_factor"]) for r in summary["results"]][:2], [("url", "PHONE"), ("origin", "PHONE")])
        self.assertIn("LCP", summary["thresholds"])

    def test_all_devices_omits_the_form_factor_and_history_is_opt_in(self):
        bodies = []

        def post(endpoint, body, key, timeout):
            bodies.append((endpoint.rsplit(":", 1)[1], body))
            return history() if "History" in endpoint else current()

        with tempfile.TemporaryDirectory() as temporary:
            run(["--origin", "https://example.com/", "--form-factor", "all", "--history", "--history-periods", "10", "--output-dir", temporary + "/c"], post)
        self.assertEqual(bodies, [("queryRecord", {"origin": "https://example.com"}),
                                  ("queryHistoryRecord", {"origin": "https://example.com", "collectionPeriodCount": 10})])

    def test_missing_data_is_unknown_and_not_an_error(self):
        def post(endpoint, body, key, timeout):
            raise crux.CruxError("CrUX HTTP 404.", 404)

        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "crux"
            code, _, _ = run(["https://example.com/rare", "--output-dir", str(out)], post)
            result = json.loads((out / "summary.json").read_text())["results"][0]
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "no-data")
        self.assertIn("unknown, not a pass", result["error"])

    def test_provider_errors_fail_the_run_without_echoing_secrets(self):
        def post(endpoint, body, key, timeout):
            raise crux.CruxError("CrUX HTTP 403. Check that the Chrome UX Report API is enabled for this key.", 403)

        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "crux"
            code, _, _ = run(["https://example.com/", "--output-dir", str(out)], post)
            result = json.loads((out / "summary.json").read_text())["results"][0]
        self.assertEqual((code, result["status"]), (1, "error"))
        self.assertNotIn("test-key", json.dumps(result))

    def test_key_is_required_sent_as_a_header_and_never_saved(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "crux"
            code, mocked, err = run(["https://example.com/", "--output-dir", str(out)], lambda *a: current(), key=None)
            self.assertEqual(code, 1)
            self.assertIn("CRUX_API_KEY", err)
            self.assertFalse(out.exists())
            leaky = current()
            leaky["note"] = "echo test-key"
            code, mocked, _ = run(["https://example.com/", "--output-dir", str(out)], lambda *a: leaky)
            self.assertEqual(mocked.call_args.args[2], "test-key")  # handed to post(), which sends it in X-Goog-Api-Key
            for path in out.iterdir():
                self.assertNotIn("test-key", path.read_text())

    def test_usage_errors_and_existing_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            code, _, err = run(["https://example.com/", "--output-dir", temporary], lambda *a: current())
            self.assertEqual(code, 1)
            self.assertIn("already exists", err)
            for argv in (["--output-dir", temporary + "/x"], ["https://example.com/", "--history-periods", "99", "--output-dir", temporary + "/y"]):
                with self.assertRaises(SystemExit) as stop:
                    run(argv, lambda *a: current())
                self.assertEqual(stop.exception.code, 2)

    def test_post_maps_http_errors_without_leaking_the_request(self):
        from urllib.error import HTTPError
        opener = unittest.mock.Mock()
        opener.open.side_effect = HTTPError("https://secret-url", 429, "secret-key", {}, io.BytesIO(b""))
        with patch.object(crux, "build_opener", return_value=opener):
            with self.assertRaisesRegex(crux.CruxError, "HTTP 429") as failure:
                crux.post(crux.CURRENT, {"url": "https://example.com/"}, "secret-key", 5)
        self.assertNotIn("secret", str(failure.exception))
        self.assertEqual(failure.exception.code, 429)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_header("X-goog-api-key"), "secret-key")
        self.assertNotIn("secret-key", request.full_url)


if __name__ == "__main__":
    unittest.main()
