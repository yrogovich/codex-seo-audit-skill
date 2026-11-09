"""Behavior checks for score_audit.py: the number must be reproducible, honest about coverage and point to fixes.

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

sys.path.insert(0, str(Path(__file__).resolve().parent))

spec = importlib.util.spec_from_file_location("score_audit", Path(__file__).resolve().parents[1] / "scripts" / "score_audit.py")
score = importlib.util.module_from_spec(spec)
spec.loader.exec_module(score)


def spec_for(check_id, area="a", weight=4, sensitivity=3, **extra):
    return dict({"id": check_id, "area": area, "weight": weight, "sensitivity": sensitivity, "source": "analysis", "fix": "Fix %s." % check_id}, **extra)


def rubric_file(directory, *checks, version=1):
    path = Path(directory) / "rubric.json"
    path.write_text(json.dumps({"version": version, "score_formula": "f", "areas": {"a": "Area A", "b": "Area B"}, "checks": list(checks), "not_covered": ["Rankings"]}))
    return path


def analysis(entries, complete=True, start="https://example.com/", noindex_urls=()):
    runs = [{"check": name, "count": count, "denominator": den, "unit": "pages"} for name, (count, den) in entries.items()]
    candidates = [{"check": "index.noindex", "urls": list(noindex_urls)}] if noindex_urls else []
    return {"scope": {"start_url": start, "complete_within_scope": complete, "stop_reason": "queue-exhausted" if complete else "page-budget",
                      "discovered": 100, "html_pages": 40, "fetched_rows": 50}, "checks_run": runs, "candidates": candidates}


def healthy_probe():
    access = [{"agent": a, "target_allowed": True, "root_allowed": True, "matched_rule": None} for a in ("*", "Googlebot")]
    return {"fetch": {"status": 200, "error": None, "final_url": "https://example.com/", "redirect_chain": [], "headers": {}},
            "robots": {"status": "ok", "http_status": 200, "target_path": "/", "agent_access": access},
            "sitemaps": {"files": [{"kind": "urlset"}]}, "variants": [{"final_url": "https://example.com/", "status": 200}] * 3,
            "missing_page": {"status": 404, "error": None}, "observations": [], "local_exception": None}


def run_checks(directory, checks, ctx):
    rubric = score.load_rubric(rubric_file(directory, *checks))
    return score.build_report(rubric, ctx, [])


def by_id(report):
    return {c["id"]: c for c in report["checks"]}


class RatioTests(unittest.TestCase):
    def test_score_drops_with_the_share_of_affected_items_and_sensitivity(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = run_checks(temporary, [spec_for("x.one"), spec_for("x.two"), spec_for("x.three", sensitivity=1)],
                                score.Context(analysis({"x.one": (1, 10), "x.two": (5, 10), "x.three": (5, 10)})))
        checks = by_id(report)
        self.assertAlmostEqual(checks["x.one"]["score"], 0.7)   # 1 - 3 x 0.1
        self.assertEqual(checks["x.two"]["score"], 0.0)         # 1 - 3 x 0.5, never below zero
        self.assertAlmostEqual(checks["x.three"]["score"], 0.5)  # sensitivity 1
        self.assertEqual(checks["x.one"]["detail"]["affected"], 1)

    def test_nothing_to_check_is_not_applicable_and_missing_results_are_not_measured(self):
        with tempfile.TemporaryDirectory() as temporary:
            checks = [spec_for("x.empty"), spec_for("x.absent"), spec_for("sitemap.thing"), spec_for("x.nocount")]
            ctx = score.Context(analysis({"x.empty": (0, 0), "x.nocount": (None, None), "sitemap.*": (None, None)}))
            report = run_checks(temporary, checks, ctx)
            none = run_checks(temporary, [spec_for("x.one")], score.Context())
        by = by_id(report)
        self.assertEqual(by["x.empty"]["status"], "not-applicable")
        self.assertEqual(by["x.absent"]["status"], "not-measured")
        self.assertIn("missing from the analysis", by["x.absent"]["reason"])
        self.assertIn("no sitemap", by["sitemap.thing"]["reason"])
        self.assertEqual(by["x.nocount"]["status"], "not-measured")
        self.assertEqual(none["overall"]["score"], None)
        self.assertIn("No score", score.summary_text(none))

    def test_unmeasured_checks_lower_coverage_but_never_count_as_passes(self):
        with tempfile.TemporaryDirectory() as temporary:
            checks = [spec_for("x.a", weight=4), spec_for("x.b", weight=1), spec_for("x.c", weight=5), spec_for("x.d", weight=2)]
            report = run_checks(temporary, checks, score.Context(analysis({"x.a": (0, 10), "x.b": (5, 10), "x.d": (0, 0)})))
        overall = report["overall"]
        # x.a passes (weight 4), x.b scores 0 (weight 1), x.c was not measured (weight 5), x.d is not applicable and ignored entirely.
        self.assertEqual((overall["score"], overall["measured_weight"], overall["total_weight"], overall["coverage"]), (80.0, 5, 10, 0.5))
        self.assertEqual((overall["checks_measured"], overall["checks_applicable"]), (2, 3))

    def test_orphan_style_checks_wait_for_a_complete_crawl(self):
        checks = [spec_for("links.orphan_candidates", requires_complete_crawl=True)]
        data = {"links.orphan_candidates": (2, 10)}
        with tempfile.TemporaryDirectory() as temporary:
            partial = run_checks(temporary, checks, score.Context(analysis(data, complete=False)))
            complete = run_checks(temporary, checks, score.Context(analysis(data, complete=True)))
        self.assertEqual(by_id(partial)["links.orphan_candidates"]["status"], "not-measured")
        self.assertEqual(by_id(complete)["links.orphan_candidates"]["status"], "measured")
        self.assertIn("partial crawl", partial["crawl"]["note"])
        self.assertEqual(complete["crawl"]["note"], "the whole crawl scope")

    def test_same_inputs_give_the_same_score(self):
        with tempfile.TemporaryDirectory() as temporary:
            rubric = score.load_rubric(rubric_file(temporary, spec_for("x.a"), spec_for("x.b", area="b")))
            ctx = score.Context(analysis({"x.a": (1, 10), "x.b": (2, 10)}))
            first, second = score.build_report(rubric, ctx, []), score.build_report(rubric, ctx, [])
        for report in (first, second):
            report.pop("scored_at")
        self.assertEqual(first, second)


class ActionTests(unittest.TestCase):
    def test_actions_are_ordered_by_points_and_add_up(self):
        with tempfile.TemporaryDirectory() as temporary:
            checks = [spec_for("x.big", weight=5), spec_for("x.small", weight=1), spec_for("x.fine", weight=4)]
            report = run_checks(temporary, checks, score.Context(analysis({"x.big": (2, 10), "x.small": (1, 10), "x.fine": (0, 10)})))
        actions = report["actions"]
        self.assertEqual([a["id"] for a in actions], ["x.big", "x.small"])  # passing checks are not listed
        self.assertEqual(actions[0]["fix"], "Fix x.big.")
        self.assertEqual((actions[0]["affected"], actions[0]["total"]), (2, 10))
        # Fixing everything that lost points would lift the score to 100.
        self.assertAlmostEqual(report["overall"]["score"] + sum(a["points_to_gain"] for a in actions), 100, delta=0.2)
        self.assertIn("Fix first", score.summary_text(report))
        self.assertIn("2 of 10", score.summary_text(report))


class ProbeTests(unittest.TestCase):
    def probe_checks(self, probe):
        rubric = score.load_rubric(score.RUBRIC)
        probe_specs = [s for s in rubric["checks"] if s["source"] == "probe"]
        with tempfile.TemporaryDirectory() as temporary:
            return by_id(run_checks(temporary, [dict(s, area="a") for s in probe_specs], score.Context(probe=probe)))

    def test_healthy_site_passes_every_probe_check(self):
        checks = self.probe_checks(healthy_probe())
        self.assertEqual({c["status"] for c in checks.values()}, {"measured"})
        self.assertEqual({c["score"] for c in checks.values()}, {1.0})

    def test_each_problem_fails_its_own_check(self):
        cases = {
            "probe.main_fetch_ok": lambda p: p["fetch"].update(status=500),
            "probe.robots_reachable": lambda p: p["robots"].update(status="unreachable"),
            "probe.googlebot_target_allowed": lambda p: p["robots"]["agent_access"][1].update(target_allowed=False, matched_rule="/"),
            "probe.https_final": lambda p: p["fetch"].update(final_url="http://example.com/"),
            "probe.redirect_chain_short": lambda p: p["fetch"].update(redirect_chain=[{}, {}, {}]),
            "probe.host_variants_consistent": lambda p: p["variants"].append({"final_url": "https://www.example.com/", "status": 200}),
            "probe.missing_page_status": lambda p: p["missing_page"].update(status=200),
            "probe.sitemap_found": lambda p: p["sitemaps"].update(files=[{"kind": "html-not-sitemap"}]),
        }
        for check_id, break_it in cases.items():
            probe = healthy_probe()
            break_it(probe)
            self.assertEqual(self.probe_checks(probe)[check_id]["score"], 0.0, check_id)
        probe = healthy_probe()
        probe["observations"] = [{"code": "sitemap.problem"}]
        self.assertEqual(self.probe_checks(probe)["probe.sitemap_valid"]["score"], 0.0)
        probe = healthy_probe()
        probe["observations"] = [{"code": "missing_page.redirects_to_home"}]
        probe["missing_page"]["status"] = 200
        self.assertEqual(self.probe_checks(probe)["probe.missing_page_status"]["score"], 0.0)

    def test_checks_the_probe_could_not_run_are_left_out(self):
        probe = healthy_probe()
        for key in ("robots", "sitemaps", "variants", "missing_page"):
            probe.pop(key)
        probe["local_exception"] = ["localhost:3000"]
        checks = self.probe_checks(probe)
        self.assertEqual(checks["probe.main_fetch_ok"]["status"], "measured")
        self.assertEqual(checks["probe.https_final"]["status"], "not-applicable")  # local project origin
        for name in ("robots_reachable", "googlebot_target_allowed", "host_variants_consistent", "missing_page_status", "sitemap_found"):
            self.assertEqual(checks["probe." + name]["status"], "not-measured", name)
        self.assertEqual(self.probe_checks(dict(healthy_probe(), sitemaps={"files": []}))["probe.sitemap_valid"]["status"], "not-applicable")


class FieldAndLabTests(unittest.TestCase):
    def test_crux_ratings_are_averaged_and_missing_data_is_unknown(self):
        row = {"kind": "current", "target": "origin", "form_factor": "PHONE", "status": "measured", "collection_period": {"first_date": "2026-10-05", "last_date": "2026-11-01"},
               "metrics": {"LCP": {"rating": "good"}, "INP": {"rating": "needs-improvement"}, "CLS": {"rating": "poor"}}}
        checks = [{"id": "perf.o", "area": "a", "weight": 4, "source": "crux", "target": "origin", "form_factor": "PHONE", "metrics": ["LCP", "INP", "CLS"], "fix": "Fix."},
                  {"id": "perf.u", "area": "a", "weight": 3, "source": "crux", "target": "url", "form_factor": "PHONE", "metrics": ["LCP", "INP", "CLS"], "fix": "Fix."}]
        with tempfile.TemporaryDirectory() as temporary:
            report = by_id(run_checks(temporary, checks, score.Context(crux=[{"results": [row]}])))
            nodata = by_id(run_checks(temporary, checks, score.Context(crux=[{"results": [dict(row, status="no-data")]}])))
        self.assertAlmostEqual(report["perf.o"]["score"], 0.5)  # (1 + 0.5 + 0) / 3
        self.assertEqual(report["perf.o"]["detail"]["collection_period"]["last_date"], "2026-11-01")
        self.assertEqual(report["perf.u"]["status"], "not-measured")  # URL data is never replaced by origin data
        self.assertIn("unknown and not a pass", nodata["perf.o"]["reason"])

    def test_lab_metrics_use_the_rubric_thresholds_across_pages(self):
        runs = lambda *values: {"runs": [{"status": "measured", "strategy": "mobile", "lab_metrics": {"LCP": {"value": v}}} for v in values]}  # noqa: E731
        checks = [{"id": "perf.lcp", "area": "a", "weight": 2, "source": "psi", "strategy": "mobile", "metric": "LCP", "good": 2500, "poor": 4000, "fix": "Fix."}]
        with tempfile.TemporaryDirectory() as temporary:
            report = by_id(run_checks(temporary, checks, score.Context(psi=[runs(2000), runs(3000), runs(5000)])))
            none = by_id(run_checks(temporary, checks, score.Context(psi=[{"runs": [{"status": "error", "strategy": "mobile"}]}])))
        self.assertAlmostEqual(report["perf.lcp"]["score"], 0.5)  # good, needs improvement, poor
        self.assertEqual((report["perf.lcp"]["detail"]["pages"], report["perf.lcp"]["detail"]["worst"]), (3, 5000))
        self.assertEqual(none["perf.lcp"]["status"], "not-measured")


class BlockerTests(unittest.TestCase):
    def blockers(self, **kwargs):
        return {b["id"] for b in score.find_blockers(score.Context(**kwargs))}

    def test_healthy_inputs_have_no_blockers(self):
        self.assertEqual(self.blockers(probe=healthy_probe(), analysis=analysis({"index.noindex": (1, 40)})), set())

    def test_each_blocker_is_flagged_without_touching_the_score(self):
        probe = healthy_probe()
        probe["fetch"].update(status=503)
        probe["robots"].update(status="unreachable")
        probe["robots"]["agent_access"][0].update(root_allowed=False)
        self.assertEqual(self.blockers(probe=probe), {"main-fetch-failed", "robots-unreachable", "robots-disallows-everything"})
        noindex_header = healthy_probe()
        noindex_header["fetch"]["headers"] = {"x-robots-tag": "noindex"}
        self.assertEqual(self.blockers(probe=noindex_header), {"main-url-noindex-header"})
        data = analysis({"index.noindex": (30, 40)}, noindex_urls=["https://example.com/", "https://example.com/a"])
        self.assertEqual(self.blockers(analysis=data), {"start-url-noindex", "most-pages-noindex"})
        with tempfile.TemporaryDirectory() as temporary:
            report = run_checks(temporary, [spec_for("x.a")], score.Context(analysis(dict({"x.a": (0, 10)}), noindex_urls=["https://example.com/"], ), probe=probe))
        self.assertEqual(report["overall"]["score"], 100.0)  # flagged, never capped
        self.assertTrue(report["blockers"])


class CompareTests(unittest.TestCase):
    def report(self, directory, counts, version=1, extra=()):
        checks = [spec_for("x.a", weight=4), spec_for("x.b", weight=2)] + list(extra)
        rubric = score.load_rubric(rubric_file(directory, *checks, version=version))
        return score.build_report(rubric, score.Context(analysis(counts)), [])

    def test_only_checks_measured_in_both_runs_are_compared(self):
        with tempfile.TemporaryDirectory() as temporary:
            before = self.report(temporary, {"x.a": (5, 10), "x.b": (5, 10)})
            after = self.report(temporary, {"x.a": (0, 10)})  # x.b was not measured this time
            comparison = score.compare(after, before)
        self.assertEqual((comparison["common_checks"], comparison["same_measured_checks"], comparison["only_in_baseline"]), (1, False, ["x.b"]))
        self.assertEqual((comparison["baseline_score_on_common_checks"], comparison["current_score_on_common_checks"], comparison["delta"]), (0.0, 100.0, 100.0))
        self.assertEqual(comparison["changed_checks"][0]["id"], "x.a")

    def test_different_rubrics_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            one = self.report(temporary, {"x.a": (1, 10)})
            two = self.report(temporary, {"x.a": (1, 10)}, version=2)
            with self.assertRaisesRegex(ValueError, "used rubric version 2"):
                score.compare(one, two)
            edited = json.loads(json.dumps(one))
            edited["rubric"]["sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "without a version bump"):
                score.compare(one, edited)
            self.assertFalse(score.compare(one, dict(one, checks=[]))["comparable"])


class RubricTests(unittest.TestCase):
    def test_the_shipped_rubric_is_valid_and_every_check_has_a_plain_fix(self):
        rubric = score.load_rubric(score.RUBRIC)
        self.assertEqual(len({c["id"] for c in rubric["checks"]}), len(rubric["checks"]))
        self.assertTrue(all(c["fix"].strip() and 1 <= c["weight"] <= 5 for c in rubric["checks"]))
        self.assertTrue(rubric["not_covered"])

    def test_every_analysis_check_in_the_rubric_exists_in_the_analyzer_output(self):
        from test_analyze_crawl import analyze_site, issue_site
        crawl, _ = analyze_site(issue_site(), max_pages=100)
        names = {c["check"] for c in crawl.checks_run}
        rubric = score.load_rubric(score.RUBRIC)
        wanted = {c["id"] for c in rubric["checks"] if c["source"] == "analysis"}
        self.assertEqual(sorted(wanted - names), [])
        self.assertTrue(all(c["denominator"] is not None for c in crawl.checks_run if c["check"] != "sitemap.*"))
        # Checks that only describe intent or cues must stay out of the score.
        self.assertEqual(sorted(set(rubric["unscored_checks"]) & wanted), [])

    def test_bad_rubrics_are_rejected_with_reasons(self):
        bad = [dict(spec_for("x.a"), weight=9), dict(spec_for("x.a"), area="zzz"), dict(spec_for("x.a"), source="magic"), dict(spec_for("x.a"), fix=""),
               dict(spec_for("x.a"), source="probe", test="nope"), spec_for("x.a", sensitivity=-1)]
        with tempfile.TemporaryDirectory() as temporary:
            for check in bad:
                with self.assertRaisesRegex(ValueError, "Invalid rubric"):
                    score.load_rubric(rubric_file(temporary, check))
            with self.assertRaisesRegex(ValueError, "duplicated"):
                score.load_rubric(rubric_file(temporary, spec_for("x.a"), spec_for("x.a")))


class CliTests(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(score.sys, "argv", ["score_audit.py", *argv]), redirect_stdout(out), redirect_stderr(err):
            try:
                code = score.main()
            except SystemExit as stop:
                code = stop.code
        return code, out.getvalue(), err.getvalue()

    def test_writes_a_new_score_file_and_prints_a_short_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            probe, output = Path(temporary) / "probe.json", Path(temporary) / "score.json"
            probe.write_text(json.dumps(healthy_probe()))
            code, out, err = self.run_cli("--probe", str(probe), "--output", str(output))
            report = json.loads(output.read_text())
            self.assertEqual(code, 0, err)
            self.assertEqual(report["label"], score.LABEL)
            self.assertEqual(report["inputs"][0]["kind"], "probe")
            self.assertIn("Score:", out)
            self.assertLess(report["overall"]["coverage"], 1)  # crawl and performance checks were not supplied
            self.assertEqual(self.run_cli("--probe", str(probe), "--output", str(output))[0], 1)  # never overwritten
            baseline = Path(temporary) / "second.json"
            code, _, _ = self.run_cli("--probe", str(probe), "--baseline", str(output), "--output", str(baseline))
            self.assertEqual((code, json.loads(baseline.read_text())["comparison"]["delta"]), (0, 0.0))

    def test_input_errors_are_clear(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(self.run_cli("--output", str(Path(temporary) / "s.json"))[0], 2)
            broken = Path(temporary) / "broken.json"
            broken.write_text("{nope")
            code, _, err = self.run_cli("--probe", str(broken), "--output", str(Path(temporary) / "s.json"))
            self.assertEqual(code, 1)
            self.assertIn("broken.json", err)


if __name__ == "__main__":
    unittest.main()
