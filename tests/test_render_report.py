"""Behavior checks for render_report.py: rendered files must satisfy the validator and agree with findings.json.

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
from test_validate_audit import audit as validator, build, finding  # noqa: E402
from test_score_audit import analysis as analysis_doc, healthy_probe  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


render, score_audit = load("render_report"), load("score_audit")
NARRATIVE = "## Summary\n\nThe site is crawlable; one template blocks indexing (SEO-001).\n\n## Scope and method\n\nPublic read-only inspection.\n"


def run_render(folder, *extra):
    out, err = io.StringIO(), io.StringIO()
    with patch.object(render.sys, "argv", ["render_report.py", str(folder), *extra]), redirect_stdout(out), redirect_stderr(err):
        code = render.main()
    return code, out.getvalue(), err.getvalue()


def sections(plan):
    """{heading: text} for the '## ' sections of action-plan.md."""
    parts, name = {}, None
    for line in plan.splitlines():
        if line.startswith("## "):
            name = line[3:].split("(")[0].strip().lower()
            parts[name] = ""
        elif name:
            parts[name] += line + "\n"
    return parts


def row_ids(text):
    return [line.split("|")[1].strip() for line in text.splitlines() if line.startswith("| SEO-")]


def many(d):
    """Findings across both tracks and several severities."""
    d["findings"] = [
        finding(id="SEO-001", severity="Critical", title="Index blocked"),
        finding(id="SEO-002", severity="High", track="content", category="On-page", title="Pages share one title"),
        finding(id="SEO-003", severity="Low", title="Tidy redirect"),
        finding(id="SEO-004", severity="Medium", track="content", category="On-page", title="Thin descriptions"),
        finding(id="SEO-005", severity="Medium", title="Slow template", recommendation="Use a pipe | and\na newline", affected_count=None, count_basis=None),
        {"id": "SEO-006", "category": "Search data", "title": "No Search Console export", "severity": "Info", "track": "content", "evidence_status": "unverified",
         "urls": [], "affected_count": None, "count_basis": None, "observation": "No export supplied.", "impact": "Query data unknown.", "evidence": []}]


class RenderReportTests(unittest.TestCase):
    def render_in(self, mutate=None, *extra):
        with tempfile.TemporaryDirectory() as temporary:
            folder = build(temporary, mutate)
            (folder / "action-plan.md").unlink()
            (folder / "report.md").unlink()
            narrative = folder.parent / "narrative.md"
            narrative.write_text(NARRATIVE)
            code, out, err = run_render(folder, "--narrative", str(narrative), *extra)
            plan = (folder / "action-plan.md").read_text() if (folder / "action-plan.md").exists() else None
            report = (folder / "report.md").read_text() if (folder / "report.md").exists() else None
            issues, _ = validator.validate(folder)
            return {"code": code, "out": out, "err": err, "plan": plan, "report": report, "issues": issues}

    def test_rendered_audit_passes_the_validator(self):
        result = self.render_in()
        self.assertEqual(result["code"], 0, result["err"])
        self.assertEqual([i for i in result["issues"] if i["level"] == "error"], [])
        self.assertIn("SEO-001", result["plan"])
        self.assertTrue(result["report"].startswith("## Summary"))

    def test_the_plan_has_one_table_per_track_sorted_by_severity(self):
        parts = sections(self.render_in(many)["plan"])
        self.assertEqual(row_ids(parts["technical fixes"]), ["SEO-001", "SEO-005", "SEO-003"])   # Critical, Medium, Low
        self.assertEqual(row_ids(parts["content fixes"]), ["SEO-002", "SEO-004"])                # High, Medium
        self.assertIn("SEO-006", parts["not scheduled"])
        self.assertNotIn("| SEO-006 |", "".join(parts.values()))

    def test_the_plan_is_five_plain_columns_with_no_owner_or_phases(self):
        plan = self.render_in(many)["plan"]
        self.assertEqual(plan.count("| ID | Priority | Fix | Affected | How to check |"), 2)
        for retired in ("Owner", "Depends on", "Now:", "Next:", "Later:", "Quick win"):
            self.assertNotIn(retired, plan)
        row = next(line for line in plan.splitlines() if line.startswith("| SEO-001 |"))
        self.assertIn("| Critical |", row)
        self.assertIn("1 (complete: every fetched product page)", row)

    def test_cells_cannot_break_the_table(self):
        plan = self.render_in(many)["plan"]
        row = next(line for line in plan.splitlines() if line.startswith("| SEO-005 |"))
        self.assertIn("Use a pipe \\| and a newline", row)
        self.assertEqual(len(row.replace("\\|", "").split("|")) - 2, 5)  # five cells, so the pipe did not add a column
        self.assertIn("| ? |", row)  # unknown count

    def test_the_report_groups_findings_by_track_and_keeps_each_one_short(self):
        report = self.render_in(many)["report"]
        for heading in ("## Summary", "## Scope and method", "## Findings", "### Technical (for developers)", "### Content (for writers and editors)",
                        "## Coverage", "## Limitations and follow-up evidence", "## Sources"):
            self.assertIn(heading, report)
        self.assertLess(report.index("### Technical"), report.index("### Content"))
        order = [report.index("#### SEO-00%d:" % n) for n in (1, 5, 3, 2, 4, 6)]
        self.assertEqual(order, sorted(order))  # technical by severity, then content by severity
        self.assertIn("(3 technical, 2 content)", report)
        self.assertIn("High · observed · On-page", report)
        for label in ("**Affected:**", "**Problem:**", "**Why it matters:**", "**Fix:**", "**Check:**", "**Evidence:**"):
            self.assertIn(label, report)
        info_block = report[report.index("#### SEO-006:"):report.index("## Coverage")]
        self.assertNotIn("**Fix:**", info_block)
        for retired in ("Owner", "Depends on", "confidence"):
            self.assertNotIn(retired, report)

    def test_long_url_lists_are_trimmed_but_not_lost(self):
        def long_list(d):
            d["findings"][0].update(urls=["https://example.com/p%d" % i for i in range(25)], affected_count=400, count_basis="sampled: 25 of 400 pages")
        report = self.render_in(long_list)["report"]
        self.assertIn("(+20 more in findings.json)", report)
        self.assertIn("400 (sampled: 25 of 400 pages)", report)

    def test_limitations_come_from_coverage(self):
        def limited(d):
            d["coverage"][-1].update(status="unknown", checked_count=None, discovered_count=None, limitation="No AI-search tooling was available.")
            d["scope"]["assumptions"] = ["Mobile first", "Google organic"]
        report = self.render_in(limited)["report"]
        self.assertIn("AI search (unknown): No AI-search tooling was available.", report)
        self.assertIn("Assumption: Mobile first", report)
        self.assertIn("| AI search | unknown | ? / ? |", report)

    def test_invalid_findings_are_refused_and_nothing_is_written(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = build(temporary, lambda d: d["findings"][0].update(track="ops"))
            (folder / "action-plan.md").unlink()
            code, out, err = run_render(folder)
            self.assertEqual(code, 1)
            self.assertIn("FINDING_TRACK", err)
            self.assertFalse((folder / "action-plan.md").exists())
            (folder / "findings.json").write_text("{broken")
            self.assertEqual(run_render(folder)[0], 1)

    def test_existing_files_are_protected_unless_forced(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = build(temporary)
            before = (folder / "action-plan.md").read_text()
            code, _, err = run_render(folder)
            self.assertEqual(code, 1)
            self.assertIn("--force", err)
            self.assertEqual((folder / "action-plan.md").read_text(), before)
            self.assertEqual(run_render(folder, "--force")[0], 0)
            self.assertNotEqual((folder / "action-plan.md").read_text(), before)

    def test_report_is_only_written_with_a_narrative(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = build(temporary)
            (folder / "action-plan.md").unlink()
            report_before = (folder / "report.md").read_text()
            code, out, err = run_render(folder)
            self.assertEqual(code, 0)
            self.assertIn("report.md not written", err)
            self.assertEqual((folder / "report.md").read_text(), report_before)

    def test_local_project_fields_are_rendered(self):
        def local(d):
            d.update(mode="local-project")
            d["scope"].update({key: None for key in validator.LOCAL_SCOPE})
            d["scope"]["runtime_mode"] = "production-preview"
            d["findings"][0].update(launch_stage="fix-before-launch", runtime_mode="production-preview",
                                    source_locations=[{"path": "evidence/a.html", "line": 3}])
        report = self.render_in(local)["report"]
        self.assertIn("Launch stage: fix-before-launch", report)
        self.assertIn("`evidence/a.html:3`", report)


def write_score(folder, probe=None, legacy=False):
    data = {"links.broken_internal": (3, 20), "status.server_error": (0, 40), "onpage.title_missing": (1, 40), "redirects.chains": (2, 10)}
    ctx = score_audit.Context(analysis_doc(data), probe or healthy_probe())
    report = score_audit.build_report(score_audit.load_rubric(score_audit.RUBRIC), ctx, [])
    if legacy:  # a score.json written before tracks and Google links existed
        report.pop("tracks")
        for action in report["actions"]:
            action.pop("track"), action.pop("basis"), action.pop("google")
    (folder / "score.json").write_text(json.dumps(report))
    return report


class ScoreSectionTests(unittest.TestCase):
    def render_with_score(self, probe=None, tamper=None, legacy=False):
        with tempfile.TemporaryDirectory() as temporary:
            folder = build(temporary)
            (folder / "action-plan.md").unlink()
            (folder / "report.md").unlink()
            data = write_score(folder, probe, legacy)
            if tamper:
                tamper(data, folder)
            narrative = folder.parent / "narrative.md"
            narrative.write_text(NARRATIVE)
            code, out, err = run_render(folder, "--narrative", str(narrative))
            report = (folder / "report.md").read_text() if (folder / "report.md").exists() else None
            issues, stats = validator.validate(folder) if report else ([], {})
            return {"code": code, "err": err, "report": report, "issues": issues, "score": data}

    def test_the_report_shows_the_number_tracks_and_what_to_fix_first(self):
        result = self.render_with_score()
        report, data = result["report"], result["score"]
        self.assertEqual(result["code"], 0, result["err"])
        self.assertIn("## Checklist score", report)
        self.assertIn("**%s / 100.**" % data["overall"]["score"], report)
        self.assertIn("%d%% of the checklist" % round(data["overall"]["coverage"] * 100), report)
        self.assertIn("not a Google ranking predictor", report)
        self.assertIn("| Technical |", report)
        self.assertIn("| Content |", report)
        self.assertIn("**Blockers:** none flagged.", report)
        self.assertIn("| Fix | Track | Points | Where | Google |", report)
        self.assertIn("| Fix or remove links to pages that are missing. | Technical | +", report)
        self.assertIn("3 of 20 pages", report)
        self.assertIn("| Add a unique <title> to every page. | Content | +", report)
        self.assertIn("**By area:**", report)
        self.assertIn("**Not checked**", report)
        self.assertIn("**Not covered by this checklist:**", report)
        self.assertLess(report.index("## Summary"), report.index("## Checklist score"))
        self.assertLess(report.index("## Checklist score"), report.index("## Findings"))

    def test_each_fix_says_what_google_says_or_that_it_is_our_own_check(self):
        report = self.render_with_score()["report"]
        self.assertIn("[guidance](https://developers.google.com/search/docs/crawling-indexing/http-network-errors)", report)
        self.assertIn("[guidance](https://developers.google.com/search/docs/appearance/title-link)", report)
        redirect_row = next(line for line in report.splitlines() if line.startswith("| Link or redirect straight to the final URL."))
        self.assertTrue(redirect_row.rstrip().endswith("| our check |"))

    def test_the_rendered_report_passes_the_validator(self):
        self.assertEqual([i for i in self.render_with_score()["issues"] if i["level"] == "error"], [])

    def test_blockers_are_listed_beside_the_number(self):
        probe = healthy_probe()
        probe["fetch"]["status"] = 503
        report = self.render_with_score(probe)["report"]
        self.assertIn("- main-fetch-failed: The audited URL did not return a successful response.", report)

    def test_areas_with_nothing_to_check_say_n_a_and_unrun_areas_say_not_checked(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = build(temporary)
            (folder / "action-plan.md").unlink()
            (folder / "report.md").unlink()
            data = {"links.broken_internal": (3, 20), "structured.json_ld_syntax_error": (0, 0), "structured.json_ld_missing_type": (0, 0), "structured.json_ld_placeholder": (0, 0)}
            ctx = score_audit.Context(analysis_doc(data), healthy_probe())
            (folder / "score.json").write_text(json.dumps(score_audit.build_report(score_audit.load_rubric(score_audit.RUBRIC), ctx, [])))
            narrative = folder.parent / "narrative.md"
            narrative.write_text(NARRATIVE)
            run_render(folder, "--narrative", str(narrative))
            report = (folder / "report.md").read_text()
        self.assertIn("| Structured data | n/a | 0 of 0 |", report)       # no JSON-LD on any page: nothing to check
        self.assertIn("| Performance | not checked | 0 of 5 |", report)    # no speed data supplied

    def test_an_older_score_file_without_tracks_still_renders(self):
        result = self.render_with_score(legacy=True)
        self.assertEqual(result["code"], 0, result["err"])
        self.assertNotIn("| Track | Score |", result["report"])
        self.assertIn("| our check |", result["report"])
        self.assertEqual([i for i in result["issues"] if i["level"] == "error"], [])

    def test_a_tampered_score_is_refused(self):
        def edit(data, folder):
            data["overall"]["score"] = 99.0
            (folder / "score.json").write_text(json.dumps(data))
        result = self.render_with_score(tamper=edit)
        self.assertEqual(result["code"], 1)
        self.assertIn("SCORE_MISMATCH", result["err"])
        self.assertIsNone(result["report"])

    def test_no_score_file_means_no_score_section(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = build(temporary)
            (folder / "action-plan.md").unlink()
            (folder / "report.md").unlink()
            narrative = folder.parent / "narrative.md"
            narrative.write_text(NARRATIVE)
            self.assertEqual(run_render(folder, "--narrative", str(narrative))[0], 0)
            self.assertNotIn("Checklist score", (folder / "report.md").read_text())


if __name__ == "__main__":
    unittest.main()
