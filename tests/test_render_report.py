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

spec = importlib.util.spec_from_file_location("render_report", Path(__file__).resolve().parents[1] / "scripts" / "render_report.py")
render = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render)

NARRATIVE = "## Executive assessment\n\nThe site is crawlable; one template blocks indexing (SEO-001).\n\n## Scope and method\n\nPublic read-only inspection.\n"


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
            name = line[3:].split(":")[0].strip().lower()
            parts[name] = ""
        elif name:
            parts[name] += line + "\n"
    return parts


def many(d):
    """Findings covering each phase, dependencies and quick-win edge cases."""
    d["findings"] = [
        finding(id="SEO-001", severity="Critical", title="Index blocked", impact_estimate={"level": "high", "expected_outcome": "Restores indexing.", "rationale": "Template-wide.", "confidence": "high"}),
        finding(id="SEO-002", severity="High", title="Quick high-impact fix", effort={"min": 30, "max": 90, "unit": "minutes", "includes": "edit and test", "scope": "one page", "assumptions": "CMS access", "confidence": "high"}),
        finding(id="SEO-003", severity="Low", title="Tidy anchors"),
        finding(id="SEO-004", severity="High", title="Depends on the low one", dependencies=["SEO-003"]),
        finding(id="SEO-005", severity="Medium", title="Large effort", effort={"min": 2, "max": 4, "unit": "working_days", "includes": "build and test", "scope": "all templates", "assumptions": "Design ready", "confidence": "low"}),
        finding(id="SEO-006", severity="Medium", title="Unknown effort", effort={"min": None, "max": None, "unit": None, "includes": "n/a", "scope": "n/a", "assumptions": "Need template source.", "confidence": "low"},
                recommendation="Use a pipe | and\na newline"),
        {"id": "SEO-007", "category": "Search data", "title": "No Search Console export", "severity": "Info", "confidence": "high", "evidence_status": "unverified",
         "urls": [], "affected_count": None, "count_basis": None, "observation": "No export supplied.", "impact": "Query data unknown.", "evidence": [], "dependencies": []}]


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
        self.assertTrue(result["report"].startswith("## Executive assessment"))

    def test_phases_follow_severity_and_dependencies(self):
        result = self.render_in(many)
        self.assertEqual(result["code"], 0, result["err"])
        parts = sections(result["plan"])
        placed = {name: [i for i in ("SEO-00%d" % n for n in range(1, 8)) if "| %s |" % i in text] for name, text in parts.items() if name in ("now", "next", "later")}
        self.assertEqual(placed["now"], ["SEO-001", "SEO-002"])
        self.assertEqual(placed["next"], ["SEO-005", "SEO-006"])
        # SEO-004 is High but waits for the Low SEO-003, so it can never be scheduled before it.
        self.assertEqual(placed["later"], ["SEO-003", "SEO-004"])
        self.assertLess(parts["later"].index("| SEO-003 |"), parts["later"].index("| SEO-004 |"))
        self.assertIn("SEO-007", parts["not scheduled (info)"])
        self.assertNotIn("| SEO-007 |", result["plan"])

    def test_audit_renders_without_estimates(self):
        def no_estimates(d):
            for f in d["findings"]:
                for key in ("effort", "impact_estimate", "waiting_time"):
                    f.pop(key, None)
        result = self.render_in(no_estimates)
        self.assertEqual(result["code"], 0, result["err"])
        self.assertEqual([i for i in result["issues"] if i["level"] == "error"], [])
        self.assertIn("**Proposed solution:**", result["report"])
        self.assertNotIn("Fix time", result["plan"] + result["report"])
        self.assertNotIn("Expected impact", result["plan"] + result["report"])

    def test_cells_cannot_break_the_table(self):
        plan = self.render_in(many)["plan"]
        row = next(line for line in plan.splitlines() if line.startswith("| SEO-006 |"))
        self.assertIn("Use a pipe \\| and a newline", row)
        self.assertEqual(len(row.replace("\\|", "").split("|")) - 2, 6)  # six cells, so the pipe did not add a column

    def test_report_contains_every_section_the_contract_requires(self):
        report = self.render_in(many)["report"]
        for heading in ("## Executive assessment", "## Scope and method", "## Coverage", "## Findings", "## Action plan", "## Limitations and follow-up evidence", "## Sources"):
            self.assertIn(heading, report)
        for n in range(1, 8):
            self.assertIn("#### SEO-00%d:" % n, report)
        self.assertLess(report.index("### Critical"), report.index("### High"))
        self.assertNotIn("Fix time (implementation plus validation)", report)
        self.assertIn("**Depends on:** SEO-003", report)
        self.assertIn("| Technical and indexing | checked | 1 / 1 |", report)
        self.assertIn("https://developers.google.com/search/docs (retrieved 2026-11-09)", report)

    def test_long_url_lists_are_trimmed_but_not_lost(self):
        def long_list(d):
            d["findings"][0].update(urls=["https://example.com/p%d" % i for i in range(25)], affected_count=400, count_basis="sampled: 25 of 400 pages")
        report = self.render_in(long_list)["report"]
        self.assertIn("... and 15 more listed in findings.json", report)
        self.assertIn("sampled: 25 of 400 pages", report)

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
            folder = build(temporary, lambda d: d["findings"][0].update(severity="severe"))
            (folder / "action-plan.md").unlink()
            code, out, err = run_render(folder)
            self.assertEqual(code, 1)
            self.assertIn("FINDING_SEVERITY", err)
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


score_spec = importlib.util.spec_from_file_location("score_audit", Path(__file__).resolve().parents[1] / "scripts" / "score_audit.py")
score_audit = importlib.util.module_from_spec(score_spec)
score_spec.loader.exec_module(score_audit)
from test_score_audit import analysis as analysis_doc, healthy_probe  # noqa: E402


def write_score(folder, probe=None):
    ctx = score_audit.Context(analysis_doc({"links.broken_internal": (3, 20), "status.server_error": (0, 40), "onpage.title_missing": (1, 40)}), probe or healthy_probe())
    report = score_audit.build_report(score_audit.load_rubric(score_audit.RUBRIC), ctx, [])
    (folder / "score.json").write_text(json.dumps(report))
    return report


class ScoreSectionTests(unittest.TestCase):
    def render_with_score(self, probe=None, tamper=None):
        with tempfile.TemporaryDirectory() as temporary:
            folder = build(temporary)
            (folder / "action-plan.md").unlink()
            (folder / "report.md").unlink()
            data = write_score(folder, probe)
            if tamper:
                tamper(data, folder)
            narrative = folder.parent / "narrative.md"
            narrative.write_text(NARRATIVE)
            code, out, err = run_render(folder, "--narrative", str(narrative))
            report = (folder / "report.md").read_text() if (folder / "report.md").exists() else None
            issues, stats = validator.validate(folder) if report else ([], {})
            return {"code": code, "err": err, "report": report, "issues": issues, "score": data}

    def test_the_report_shows_the_number_with_coverage_label_and_what_to_fix(self):
        result = self.render_with_score()
        report, data = result["report"], result["score"]
        self.assertEqual(result["code"], 0, result["err"])
        self.assertIn("## Checklist score", report)
        self.assertIn("**%s / 100.**" % data["overall"]["score"], report)
        self.assertIn("%d%% of the checklist" % round(data["overall"]["coverage"] * 100), report)
        self.assertIn("not a Google ranking predictor", report)
        self.assertIn("| Indexing and access |", report)
        self.assertIn("**Blockers:** none flagged.", report)
        self.assertIn("**Fix first**", report)
        self.assertIn("| Fix or remove links to pages that are missing. | +", report)
        self.assertIn("3 of 20 pages", report)
        self.assertIn("**Not checked**", report)
        self.assertIn("**Not covered by this checklist:**", report)
        self.assertIn("comparison key %s" % data["comparison_key"], report)
        self.assertLess(report.index("## Executive assessment"), report.index("## Checklist score"))
        self.assertLess(report.index("## Checklist score"), report.index("## Coverage"))

    def test_the_rendered_report_passes_the_validator(self):
        result = self.render_with_score()
        self.assertEqual([i for i in result["issues"] if i["level"] == "error"], [])

    def test_blockers_are_listed_beside_the_number(self):
        probe = healthy_probe()
        probe["fetch"]["status"] = 503
        report = self.render_with_score(probe)["report"]
        self.assertIn("- main-fetch-failed: The audited URL did not return a successful response.", report)

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
