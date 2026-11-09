"""Behavior checks for the audit directory validator.

Run: python3 -m unittest discover -s tests -v
"""

from contextlib import redirect_stdout, redirect_stderr
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("validate_audit", ROOT / "scripts" / "validate_audit.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

AREAS = ["Technical and indexing", "Rendering and mobile", "Architecture and internal links", "Content and on-page",
         "Structured data", "Performance", "Images and media", "Search visibility and authority", "AI search"]


def finding(**changes):
    value = {
        "id": "SEO-001", "category": "Indexing", "title": "Noindex on product template", "severity": "High",
        "confidence": "high", "evidence_status": "observed", "urls": ["https://example.com/a"], "affected_count": 1,
        "count_basis": "complete: every fetched product page", "observation": "Robots meta contains noindex.",
        "impact": "Product pages cannot be indexed.",
        "evidence": [{"ref": "evidence/a.html", "method": "HTTP GET", "captured_at": "2026-11-09T12:00:00+00:00", "excerpt": "noindex"}],
        "recommendation": "Remove the noindex directive from the template.", "acceptance_test": "Robots meta no longer contains noindex.",
        "impact_estimate": {"level": "high", "expected_outcome": "Restores index eligibility.", "rationale": "Template-wide.", "confidence": "medium"},
        "owner_role": "Developer",
        "effort": {"min": 1, "max": 2, "unit": "hours", "includes": "implementation and validation", "scope": "one shared template",
                   "assumptions": "Repository access", "confidence": "medium"},
        "dependencies": [], "waiting_time": {"estimate": "Next release", "assumptions": "Weekly deploys"}}
    value.update(changes)
    return value


def document():
    return {"schema_version": 1, "target": "https://example.com/", "audited_at": "2026-11-09T12:00:00+01:00", "mode": "full",
            "scope": {"allowed_hosts": ["example.com"]},
            "coverage": [{"area": area, "status": "checked", "checked_count": 1, "discovered_count": 1, "denominator_note": "one page",
                          "limitation": None, "evidence_refs": ["evidence/a.html"]} for area in AREAS],
            "findings": [finding()],
            "sources": [{"url": "https://developers.google.com/search/docs", "retrieved_at": "2026-11-09", "supports": "robots meta"}]}


INVENTORY = ("url,final_url,discovered_via,template,fetch_status,http_status,rendered,observed_indexability,canonical,evidence_ref,notes\n"
             "https://example.com/a,https://example.com/a,sitemap,product,fetched,200,no,noindex,,evidence/a.html,\"quoted, note\"\n")


def build(parent, mutate=None, local=False):
    folder = Path(parent) / "workspace" / "seo-audits" / "example.com" / "2026-11-09-1"
    (folder / "evidence").mkdir(parents=True)
    (folder / "evidence" / "a.html").write_text("<meta name=robots content=noindex>")
    data = document()
    if mutate:
        mutate(data)
    (folder / "findings.json").write_text(json.dumps(data))
    (folder / "report.md").write_text("# Report\n\nSEO-001 Noindex on product template\n")
    (folder / "action-plan.md").write_text("| ID |\n| SEO-001 |\n")
    (folder / "url-inventory.csv").write_text(INVENTORY)
    return folder


def run(folder):
    issues, stats = audit.validate(folder)
    return {(i["level"], i["code"]) for i in issues}, issues, stats


class ValidateAuditTests(unittest.TestCase):
    def check(self, mutate, expected, level="error", after=None):
        with tempfile.TemporaryDirectory() as temporary:
            folder = build(temporary, mutate)
            if after:
                after(folder)
            found, issues, _ = run(folder)
            self.assertIn((level, expected), found, issues)

    def test_valid_audit_has_no_issues(self):
        with tempfile.TemporaryDirectory() as temporary:
            found, issues, stats = run(build(temporary))
            self.assertEqual(issues, [])
            self.assertEqual((stats["findings"], stats["inventory_rows"], stats["inventory_with_http_status"]), (1, 1, 1))

    def test_missing_and_empty_deliverables(self):
        def drop(folder):
            (folder / "report.md").unlink()
            (folder / "url-inventory.csv").write_text("")
        self.check(None, "FILE_MISSING", after=drop)
        self.check(None, "FILE_EMPTY", after=drop)

    def test_top_level_contract(self):
        self.check(lambda d: d.update(schema_version=2), "SCHEMA_VERSION")
        self.check(lambda d: d.update(audited_at="2026-11-09T12:00:00"), "AUDITED_AT")
        self.check(lambda d: d.update(mode="deep"), "MODE")
        self.check(lambda d: d.pop("sources"), "TOP_LEVEL_KEYS")
        self.check(lambda d: d.update(coverage=[]), "COVERAGE_INVALID")

    def test_unparseable_json_is_reported(self):
        self.check(None, "JSON_UNREADABLE", after=lambda f: (f / "findings.json").write_text("{broken"))

    def test_enums_and_critical_rules(self):
        self.check(lambda d: d["findings"][0].update(severity="severe"), "FINDING_SEVERITY")
        self.check(lambda d: d["findings"][0].update(confidence="certain"), "FINDING_CONFIDENCE")
        self.check(lambda d: d["findings"][0].update(severity="Critical", evidence_status="unverified"), "CRITICAL_UNVERIFIED")
        self.check(lambda d: d["findings"][0].update(severity="critical", evidence_status="inferred"), "CRITICAL_INFERRED", "warning")
        self.check(lambda d: d["coverage"][0].update(status="maybe"), "COVERAGE_STATUS")

    def test_coverage_status_spelling_is_normalised_and_areas_are_required(self):
        def variant(d):
            d["coverage"][0].update(status="Not applicable", limitation="No JS on this site.")
        with tempfile.TemporaryDirectory() as temporary:
            _, issues, _ = run(build(temporary, variant))
            self.assertEqual(issues, [])
        self.check(lambda d: d["coverage"].pop(), "COVERAGE_MISSING_AREA", "warning")
        # A deliberately narrow audit is not expected to cover every core area.
        with tempfile.TemporaryDirectory() as temporary:
            found, _, _ = run(build(temporary, lambda d: d.update(mode="focused", coverage=d["coverage"][:1])))
            self.assertNotIn(("warning", "COVERAGE_MISSING_AREA"), found)

    def test_coverage_details(self):
        self.check(lambda d: d["coverage"][0].update(status="unknown", limitation=None), "COVERAGE_LIMITATION", "warning")
        self.check(lambda d: d["coverage"][0].update(checked_count=5, discovered_count=2), "COVERAGE_COUNT", "warning")
        self.check(lambda d: d["coverage"][0].update(checked_count=-1), "COVERAGE_COUNT")
        self.check(lambda d: d["coverage"][0].update(evidence_refs=["evidence/missing.json"]), "REF_MISSING")

    def test_evidence_references_must_resolve(self):
        self.check(lambda d: d["findings"][0]["evidence"][0].update(ref="evidence/nope.html"), "REF_MISSING")
        with tempfile.TemporaryDirectory() as temporary:
            def refs(d):
                d["findings"][0]["evidence"] += [
                    {"ref": "https://example.com/robots.txt", "method": "GET", "captured_at": "2026-11-09", "excerpt": None},
                    {"ref": "evidence/a.html:1", "method": "view", "captured_at": "2026-11-09", "excerpt": "x"},
                    {"ref": "tool-result:abc", "method": "browser", "captured_at": "2026-11-09", "excerpt": "x"}]
            found, issues, _ = run(build(temporary, refs))
            self.assertEqual([i["code"] for i in issues], ["REF_UNRESOLVABLE"])
        self.check(lambda d: d["findings"][0].update(evidence=[]), "FINDING_NO_EVIDENCE")

    def test_source_refs_resolve_against_the_workspace(self):
        def source_ref(d):
            d["findings"][0]["evidence"][0]["ref"] = "src/app/layout.tsx:12"
        with tempfile.TemporaryDirectory() as temporary:
            folder = build(temporary, source_ref)
            _, issues, _ = run(folder)
            self.assertIn("REF_MISSING", [i["code"] for i in issues])
            (folder.parents[2] / "src" / "app").mkdir(parents=True)
            (folder.parents[2] / "src" / "app" / "layout.tsx").write_text("export default 1")
            _, issues, _ = run(folder)
            self.assertEqual(issues, [])

    def test_counts_and_sampling(self):
        self.check(lambda d: d["findings"][0].update(affected_count=0), "FINDING_COUNT_URLS")
        self.check(lambda d: d["findings"][0].update(affected_count=-3), "FINDING_COUNT")
        self.check(lambda d: d["findings"][0].update(count_basis=""), "FINDING_COUNT_BASIS")
        self.check(lambda d: d["findings"][0].update(count_basis="sampled: 5 of 400 pages", title="Site-wide noindex"),
                   "SAMPLED_SITEWIDE", "warning")
        with tempfile.TemporaryDirectory() as temporary:
            found, _, _ = run(build(temporary, lambda d: d["findings"][0].update(affected_count=None, count_basis=None)))
            self.assertNotIn(("error", "FINDING_COUNT"), found)

    def test_estimates(self):
        self.check(lambda d: d["findings"][0]["effort"].update(min=3, max=2), "EFFORT_BOUNDS")
        self.check(lambda d: d["findings"][0]["effort"].update(unit="days"), "EFFORT_UNIT")
        self.check(lambda d: d["findings"][0]["effort"].update(min=None, max=None, unit=None, assumptions=""), "EFFORT_UNKNOWN_REASON")
        self.check(lambda d: d["findings"][0]["effort"].update(min=None), "EFFORT_BOUNDS")
        self.check(lambda d: d["findings"][0].update(impact_estimate={"level": "huge"}), "IMPACT_KEYS")
        self.check(lambda d: d["findings"][0]["impact_estimate"].update(level="huge"), "IMPACT_LEVEL")
        with tempfile.TemporaryDirectory() as temporary:
            def no_estimates(d):
                for key in ("effort", "impact_estimate", "waiting_time"):
                    d["findings"][0].pop(key)
            self.assertEqual(run(build(temporary, no_estimates))[1], [])
        with tempfile.TemporaryDirectory() as temporary:
            def unknown(d):
                d["findings"][0]["effort"].update(min=None, max=None, unit=None, assumptions="No CMS access; need template source.")
                d["findings"][0]["impact_estimate"].update(level="unknown", rationale="Needs Search Console data.")
            self.assertEqual(run(build(temporary, unknown))[1], [])
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(run(build(temporary, lambda d: d["findings"][0]["effort"].update(unit="Working days")))[1], [])

    def test_claim_lints(self):
        self.check(lambda d: d["findings"][0]["impact_estimate"].update(expected_outcome="Organic traffic will grow by 40%."),
                   "UNSUPPORTED_UPLIFT", "warning")
        self.check(lambda d: d["findings"][0].update(evidence_status="inferred", observation="Likely a Google penalty."),
                   "PENALTY_CLAIM", "warning")

    def test_info_findings_are_not_forced_into_the_action_plan(self):
        def info(d):
            d["findings"].append({"id": "SEO-002", "category": "Search data", "title": "No Search Console export", "severity": "Info",
                                  "confidence": "high", "evidence_status": "unverified", "urls": [], "affected_count": None,
                                  "count_basis": None, "observation": "No export supplied.", "impact": "Query data unknown.",
                                  "evidence": [], "dependencies": []})
        with tempfile.TemporaryDirectory() as temporary:
            folder = build(temporary, info)
            (folder / "report.md").write_text("SEO-001 and SEO-002\n")
            found, issues, _ = run(folder)
            self.assertNotIn(("error", "ID_NOT_IN_MARKDOWN"), found, issues)

    def test_ids_dependencies_and_markdown_agreement(self):
        def duplicate(d):
            d["findings"].append(finding())
        self.check(duplicate, "FINDING_DUPLICATE_ID")

        def second(d, deps):
            d["findings"].append(finding(id="SEO-002", dependencies=deps))
        self.check(lambda d: second(d, ["SEO-999"]), "DEPENDENCY_UNKNOWN")
        self.check(lambda d: second(d, ["SEO-002"]), "DEPENDENCY_SELF")

        def cycle(d):
            second(d, ["SEO-001"])
            d["findings"][0]["dependencies"] = ["SEO-002"]
        self.check(cycle, "DEPENDENCY_CYCLE")
        self.check(lambda d: second(d, []), "ID_NOT_IN_MARKDOWN")
        self.check(None, "ID_NOT_IN_MARKDOWN", after=lambda f: (f / "action-plan.md").write_text("empty plan"))
        self.check(None, "UNKNOWN_ID_IN_MARKDOWN", "warning", after=lambda f: (f / "report.md").write_text("SEO-001 and SEO-042"))

    def test_inventory_rules(self):
        header = INVENTORY.splitlines()[0]
        row = INVENTORY.splitlines()[1]
        self.check(None, "INVENTORY_DUPLICATE", after=lambda f: (f / "url-inventory.csv").write_text(INVENTORY + row + "\n"))
        self.check(None, "INVENTORY_HTTP_STATUS", after=lambda f: (f / "url-inventory.csv").write_text(
            INVENTORY.replace(",200,", ",two hundred,")))
        self.check(None, "INVENTORY_HEADER", after=lambda f: (f / "url-inventory.csv").write_text(header.replace("canonical,", "") + "\n"))
        self.check(None, "INVENTORY_ROW_WIDTH", after=lambda f: (f / "url-inventory.csv").write_text(INVENTORY + "https://example.com/b,only,three\n"))
        self.check(None, "REF_MISSING", after=lambda f: (f / "url-inventory.csv").write_text(INVENTORY.replace("evidence/a.html", "evidence/gone.html")))
        self.check(None, "FINDING_URL_NOT_IN_INVENTORY", "warning", after=lambda f: (f / "url-inventory.csv").write_text(
            INVENTORY.replace("https://example.com/a,https://example.com/a", "https://example.com/z,https://example.com/z")))
        with tempfile.TemporaryDirectory() as temporary:
            folder = build(temporary)
            (folder / "url-inventory.csv").write_text(INVENTORY.replace(",200,", ",unknown,"))
            self.assertEqual(run(folder)[1], [])

    def test_local_project_requirements(self):
        self.check(lambda d: d.update(mode="local-project"), "LOCAL_SCOPE_KEYS")
        self.check(lambda d: d.update(mode="local-project"), "LOCAL_LAUNCH_STAGE")
        self.check(lambda d: d.update(mode="local-project"), "FILE_MISSING")
        self.check(lambda d: d["findings"][0].update(source_locations=[{"path": "app/layout.tsx", "line": 0}]), "SOURCE_LOCATIONS")

        def complete(d):
            d.update(mode="local-project")
            d["scope"].update({key: None for key in audit.LOCAL_SCOPE})
            d["scope"]["runtime_mode"] = "production-preview"
            d["findings"][0].update(launch_stage="fix-before-launch", runtime_mode="production-preview",
                                    source_locations=[{"path": "evidence/a.html", "line": None}])
        with tempfile.TemporaryDirectory() as temporary:
            folder = build(temporary, complete)
            (folder / "launch-checklist.md").write_text("| Check | Status |\n| robots | pending |\n")
            self.assertEqual(run(folder)[1], [])

    def test_secrets_are_reported_without_echoing_them(self):
        key = "AIza" + "B" * 35
        with tempfile.TemporaryDirectory() as temporary:
            folder = build(temporary)
            (folder / "evidence" / "psi-request.txt").write_text("GET /run?key=%s\n" % key)
            (folder / "evidence" / "headers.txt").write_text("HTTP/1.1 200 OK\nSet-Cookie: session=abc123; Path=/\n")
            found, issues, _ = run(folder)
        self.assertIn(("error", "SECRET_PATTERN"), found)
        self.assertIn(("warning", "SECRET_PATTERN"), found)
        self.assertNotIn(key, json.dumps(issues))

    def test_environment_key_value_is_detected(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(audit.os.environ, {"PAGESPEED_API_KEY": "unit-test-secret-value"}):
            folder = build(temporary)
            (folder / "evidence" / "notes.txt").write_text("key was unit-test-secret-value")
            found, issues, _ = run(folder)
        self.assertIn(("error", "SECRET_ENV_VALUE"), found)
        self.assertNotIn("unit-test-secret-value", json.dumps(issues))

    def test_invalid_evidence_json_is_a_warning(self):
        self.check(None, "EVIDENCE_JSON_INVALID", "warning", after=lambda f: (f / "evidence" / "raw.json").write_text("{not json"))

    def test_cli_exit_codes_and_json_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = build(temporary)
            out = io.StringIO()
            with patch.object(audit.sys, "argv", ["validate_audit.py", str(folder), "--json"]), redirect_stdout(out):
                self.assertEqual(audit.main(), 0)
            self.assertTrue(json.loads(out.getvalue())["ok"])
            (folder / "evidence" / "headers.txt").write_text("Set-Cookie: session=abc123\n")  # warning only
            with patch.object(audit.sys, "argv", ["validate_audit.py", str(folder)]), redirect_stdout(io.StringIO()):
                self.assertEqual(audit.main(), 0)
            with patch.object(audit.sys, "argv", ["validate_audit.py", str(folder), "--strict"]), redirect_stdout(io.StringIO()):
                self.assertEqual(audit.main(), 1)
            (folder / "report.md").unlink()
            with patch.object(audit.sys, "argv", ["validate_audit.py", str(folder)]), redirect_stdout(io.StringIO()):
                self.assertEqual(audit.main(), 1)
            with patch.object(audit.sys, "argv", ["validate_audit.py", str(folder / "missing")]), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as stop:
                    audit.main()
            self.assertEqual(stop.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
