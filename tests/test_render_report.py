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


if __name__ == "__main__":
    unittest.main()
