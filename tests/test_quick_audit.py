"""Behavior checks for quick_audit.py: the whole scan runs in this process against an in-memory site (no sockets).

Run: python3 -m unittest discover -s tests -v
"""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fakesite import FakeSite, TIMEOUT  # noqa: E402
from test_crawl import sample_site  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
spec = importlib.util.spec_from_file_location("quick_audit", SCRIPTS / "quick_audit.py")
quick = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quick)
validator = quick.render_report.contract


class Result:
    pass


def run_quick(site, *argv, folder_name="quick", keep=None):
    """Run the scan and read what it wrote while the temporary folder still exists."""
    with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
        for item in site.patches():
            stack.enter_context(item)
        folder = Path(temporary) / folder_name
        out, err = io.StringIO(), io.StringIO()
        with patch.object(quick.sys, "argv", ["quick_audit.py", *argv, "--output-dir", str(folder)]), redirect_stdout(out), redirect_stderr(err):
            try:
                code = quick.main()
            except SystemExit as stop:
                code = stop.code
        result = Result()
        result.code, result.out, result.err, result.folder = code, out.getvalue(), err.getvalue(), folder
        result.files = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()} if folder.exists() else set()
        read = lambda name: json.loads((folder / name).read_text()) if (folder / name).exists() else None  # noqa: E731
        result.score = read("score.json")
        result.report = (folder / "quick-report.md").read_text() if (folder / "quick-report.md").exists() else None
        result.summary = read("crawl/summary.json")
        if keep:
            keep(folder, result)
        return result


class QuickAuditTests(unittest.TestCase):
    def test_one_command_gives_a_score_card_and_a_report(self):
        result = run_quick(sample_site(), "https://example.com/", "--max-pages", "20", "--delay", "0.2")
        self.assertEqual(result.code, 0, result.err)
        for name in ("probe/probe.json", "crawl/summary.json", "crawl/analysis.json", "crawl/url-inventory.csv", "score.json", "quick-report.md"):
            self.assertIn(name, result.files)
        self.assertEqual(result.score["label"], "Internal checklist metric, not a Google ranking predictor.")
        for text in ("Score:", "Technical", "Content", "Blockers:", "Fix first", "[1/4]", "[4/4]", "quick-report.md"):
            self.assertIn(text, result.out)
        issues = validator.Issues()
        self.assertIsNotNone(validator.check_score(result.score, issues))
        self.assertEqual(issues.items, [])  # the score adds up

    def test_the_quick_report_is_short_honest_and_points_to_the_full_audit(self):
        report = run_quick(sample_site(), "https://example.com/", "--delay", "0.2").report
        for text in ("# Quick audit: https://example.com/", "fast scan of raw HTML", "$seo-audit", "## Checklist score", "| Technical |", "**Fix first**",
                     "Pages: ", "## Also worth a look (not scored, often intentional)", "`index.noindex`", "## Files"):
            self.assertIn(text, report)
        self.assertLess(len(report.split()), 700)

    def test_it_stays_inside_the_limits_it_was_given(self):
        result = run_quick(sample_site(), "https://example.com/", "--max-pages", "3", "--delay", "0.2")
        self.assertEqual(result.code, 0, result.err)
        self.assertLessEqual(result.summary["counts"]["html_pages"], 3)
        self.assertEqual(result.summary["stop_reason"], "page-budget")
        self.assertIn("crawl stopped early: page-budget", result.report)
        self.assertIn("partial crawl", result.out)

    def test_an_unreachable_site_stops_early_with_a_clear_message(self):
        result = run_quick(FakeSite().fail("example.com", "*", TIMEOUT), "https://example.com/")
        self.assertEqual(result.code, 1)
        self.assertIn("Could not fetch https://example.com/ (timeout). Nothing else was run.", result.err)
        self.assertNotIn("crawl/summary.json", result.files)
        self.assertIsNone(result.score)

    def test_a_site_that_blocks_the_crawl_still_gets_a_score_from_the_site_checks(self):
        site = sample_site()
        site.add("example.com", "/robots.txt", "down", status=503, content_type="text/plain")
        result = run_quick(site, "https://example.com/", "--delay", "0.2")
        self.assertEqual(result.code, 0, result.err)
        self.assertNotIn("crawl/analysis.json", result.files)
        self.assertIn("No pages were crawled (robots-unreachable)", result.out)
        self.assertIn("robots-unreachable", [b["id"] for b in result.score["blockers"]])
        self.assertIn("No pages were crawled", result.report)

    def test_local_projects_need_the_explicit_origin_and_skip_google_services(self):
        site = FakeSite()
        site.addresses["localhost"] = ["127.0.0.1"]
        site.page("localhost", "/", "Dev", '<a href="/a">a</a>')
        site.page("localhost", "/a", "A")
        refused = run_quick(site, "http://localhost:3000/")
        self.assertEqual(refused.code, 1)
        self.assertIn("blocked-target", refused.err)
        self.assertEqual(site.log, [])
        allowed = run_quick(site, "http://localhost:3000/", "--allow-local", "http://localhost:3000", "--pagespeed", "--crux", "--delay", "0.2")
        self.assertEqual(allowed.code, 0, allowed.err)
        self.assertIn("crawl/analysis.json", allowed.files)  # the local origin was crawled, not just probed
        self.assertIn("PageSpeed and CrUX were skipped", allowed.out)
        self.assertNotIn("pagespeed/summary.json", allowed.files)
        checks = {c["id"]: c for c in allowed.score["checks"]}
        self.assertEqual(checks["probe.https_final"]["status"], "not-applicable")

    def test_pagespeed_is_opt_in_and_its_result_feeds_the_score(self):
        def fake_pagespeed():
            target = Path(quick.sys.argv[quick.sys.argv.index("--output-dir") + 1])
            target.mkdir(parents=True)
            (target / "summary.json").write_text(json.dumps({"runs": [{"status": "measured", "strategy": "mobile", "lab_metrics": {
                "LCP": {"value": 3000}, "CLS": {"value": 0.05}, "TBT": {"value": 700}}}]}))
            return 0

        off = run_quick(sample_site(), "https://example.com/", "--delay", "0.2")
        self.assertNotIn("pagespeed/summary.json", off.files)
        with patch.object(quick.pagespeed_check, "main", fake_pagespeed):
            on = run_quick(sample_site(), "https://example.com/", "--pagespeed", "--delay", "0.2")
        checks = {c["id"]: c for c in on.score["checks"]}
        self.assertEqual((checks["perf.lab_lcp"]["status"], round(checks["perf.lab_lcp"]["score"], 2), checks["perf.lab_tbt"]["score"]), ("measured", 0.5, 0.0))
        self.assertEqual({c["id"]: c["status"] for c in off.score["checks"]}["perf.lab_lcp"], "not-measured")

    def test_crux_without_a_key_is_skipped_not_fatal(self):
        with patch.dict(os.environ):
            os.environ.pop("CRUX_API_KEY", None)
            os.environ.pop("PAGESPEED_API_KEY", None)
            result = run_quick(sample_site(), "https://example.com/", "--crux", "--delay", "0.2")
        self.assertEqual(result.code, 0, result.err)
        self.assertIn("CrUX was skipped", result.out)
        self.assertEqual({c["id"]: c["status"] for c in result.score["checks"]}["perf.crux_origin_cwv"], "not-measured")

    def test_a_baseline_adds_a_comparison_on_shared_checks(self):
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            site = sample_site()
            for item in site.patches():
                stack.enter_context(item)
            first, second = Path(temporary) / "first", Path(temporary) / "second"
            for folder, extra in ((first, []), (second, ["--baseline", str(first / "score.json")])):
                with patch.object(quick.sys, "argv", ["quick_audit.py", "https://example.com/", "--delay", "0.2", "--output-dir", str(folder)] + extra), \
                        redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    self.assertEqual(quick.main(), 0)
            comparison = json.loads((second / "score.json").read_text())["comparison"]
        self.assertEqual((comparison["comparable"], comparison["delta"], comparison["same_measured_checks"]), (True, 0.0, True))

    def test_an_existing_folder_is_never_reused_and_bad_options_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(quick.sys, "argv", ["quick_audit.py", "https://example.com/", "--output-dir", temporary]), redirect_stderr(io.StringIO()) as err:
                self.assertEqual(quick.main(), 1)
            self.assertIn("already exists", err.getvalue())
            for argv in (["not a url"], ["https://example.com/", "--delay", "0"], ["https://example.com/", "--max-pages", "0"]):
                with patch.object(quick.sys, "argv", ["quick_audit.py", *argv, "--output-dir", temporary + "/x"]), redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as stop:
                        quick.main()
                self.assertEqual(stop.exception.code, 2)

    def test_default_folders_are_dated_and_never_collide(self):
        saved = os.getcwd()
        with tempfile.TemporaryDirectory() as temporary:
            os.chdir(temporary)
            try:
                first = quick.default_folder("https://example.com/", "2026-11-09")
                self.assertEqual(first.as_posix(), "seo-audits/example.com/2026-11-09-quick")
                first.mkdir(parents=True)
                self.assertEqual(quick.default_folder("https://example.com/", "2026-11-09").name, "2026-11-09-quick-2")
                self.assertEqual(quick.default_folder("http://localhost:3000/", "2026-11-09").as_posix(), "seo-audits/localhost-3000/2026-11-09-quick")
            finally:
                os.chdir(saved)

    def test_call_reports_exit_codes_without_leaking_output(self):
        class Fake:
            __name__ = "fake"

            @staticmethod
            def main():
                print("hello")
                print("oops", file=sys.stderr)
                return 3

        class Exits(Fake):
            @staticmethod
            def main():
                raise SystemExit(2)

        self.assertEqual(quick.call(Fake, ["a"]), (3, "hello\n", "oops\n"))
        self.assertEqual(quick.call(Exits, [])[0], 2)


if __name__ == "__main__":
    unittest.main()
