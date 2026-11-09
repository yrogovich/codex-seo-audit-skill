#!/usr/bin/env python3
"""Render action-plan.md (and report.md) from findings.json so the files cannot disagree; standard library only.

findings.json is the single source of truth. The renderer refuses a document that fails the contract checks,
never invents content, and keeps the auditor's own narrative (executive assessment, scope and method) verbatim."""

import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_audit as contract  # noqa: E402

SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"]
PHASES = ["now", "next", "later"]
PHASE_TITLES = {"now": "Now: confirmed blockers and urgent fixes", "next": "Next: material improvements and dependent work",
                "later": "Later: minor improvements"}
URL_LIMIT, EVIDENCE_EXCERPT = 10, 300


def cell(value):
    text = " ".join(str(value if value is not None else "").split())
    return text.replace("|", "\\|") or "-"


def sev(finding):
    return finding["severity"].strip().lower()


def plan_phases(findings):
    """Base phase from severity, never earlier than any prerequisite; returns {id: phase}."""
    base = {"critical": "now", "medium": "next", "low": "later"}
    phase = {}
    by_id = {f["id"]: f for f in findings}
    for f in findings:
        phase[f["id"]] = "now" if sev(f) == "high" and not f.get("dependencies") else "next" if sev(f) == "high" else base[sev(f)]
    for _ in range(len(findings) + 1):  # relaxation over an acyclic graph; validated beforehand
        changed = False
        for f in findings:
            for dep in f.get("dependencies") or []:
                if dep in by_id and PHASES.index(phase[dep]) > PHASES.index(phase[f["id"]]):
                    phase[f["id"]] = phase[dep]
                    changed = True
        if not changed:
            break
    return phase


def depth(findings):
    by_id = {f["id"]: f for f in findings}
    cache = {}

    def of(fid):
        if fid not in cache:
            cache[fid] = 1 + max([of(d) for d in by_id[fid].get("dependencies") or [] if d in by_id] or [-1])
        return cache[fid]
    return {f["id"]: of(f["id"]) for f in findings}


def order_key(finding, levels):
    return (levels[finding["id"]], SEVERITY_ORDER.index(sev(finding)), finding["id"])


def plan_row(finding):
    return "| %s | %s | %s | %s | %s | %s |" % (
        cell(finding["id"]), cell(finding.get("recommendation")), sev(finding).capitalize(),
        cell(finding.get("owner_role")), cell(", ".join(finding.get("dependencies") or [])),
        cell(finding.get("acceptance_test")))


def render_plan(data):
    findings = [f for f in data["findings"] if sev(f) != "info"]
    info = [f for f in data["findings"] if sev(f) == "info"]
    phases, levels = plan_phases(findings), depth(findings)
    lines = ["# Action plan: %s" % data["target"], "",
             "Audit date: %s. Mode: %s. Generated from findings.json by render_report.py; change findings.json and re-render rather than editing this file." % (data["audited_at"], data["mode"]), "",
             "Priorities follow severity and dependencies; prerequisite fixes are scheduled first.", ""]
    header = ["| ID | Proposed solution | Priority | Owner | Depends on | Acceptance test |",
              "| --- | --- | --- | --- | --- | --- |"]
    for name in PHASES:
        rows = sorted((f for f in findings if phases[f["id"]] == name), key=lambda f: order_key(f, levels))
        lines += ["## " + PHASE_TITLES[name], ""]
        lines += header + [plan_row(f) for f in rows] if rows else ["Nothing in this phase."]
        lines.append("")
    lines += ["", "## Not scheduled (Info)", ""]
    lines += ["- %s: %s" % (f["id"], f["title"]) for f in info] or ["None."]
    return "\n".join(lines) + "\n"


def bullets(items):
    return ["- " + item for item in items]


def render_finding(f):
    lines = ["#### %s: %s" % (f["id"], f["title"]), "",
             "Severity %s | confidence %s | evidence %s | category %s" % (sev(f).capitalize(), f["confidence"], f["evidence_status"], f["category"]), ""]
    count = f.get("affected_count")
    lines.append("**Affected:** %s (%s)" % ("count unknown" if count is None else count, f.get("count_basis") or "basis not stated"))
    urls = f.get("urls") or []
    lines += [""] + bullets(["`%s`" % u for u in urls[:URL_LIMIT]])
    if len(urls) > URL_LIMIT:
        lines.append("- ... and %d more listed in findings.json" % (len(urls) - URL_LIMIT))
    lines += ["", "**Observation:** " + f["observation"], "", "**Why it matters:** " + f["impact"], ""]
    if f.get("evidence"):
        lines.append("**Evidence:**")
        for e in f["evidence"]:
            excerpt = " ".join(str(e.get("excerpt") or "").split())[:EVIDENCE_EXCERPT]
            lines.append("- `%s` (%s, %s)%s" % (e["ref"], e["method"], e["captured_at"], ": " + excerpt if excerpt else ""))
        lines.append("")
    if sev(f) != "info":
        lines += ["**Proposed solution:** " + f["recommendation"], "",
                  "**Owner:** " + f.get("owner_role", ""), ""]
        if f.get("dependencies"):
            lines += ["**Depends on:** " + ", ".join(f["dependencies"]), ""]
        lines += ["**Acceptance test:** " + f["acceptance_test"], ""]
    local = [("Launch stage", f.get("launch_stage")), ("Runtime mode", f.get("runtime_mode"))]
    local = ["%s: %s" % (k, v) for k, v in local if v]
    locations = ["`%s%s`" % (s["path"], ":%d" % s["line"] if s.get("line") else "") for s in f.get("source_locations") or []]
    if local or locations:
        lines += ["**Local project:** " + "; ".join(local + (["source " + ", ".join(locations)] if locations else [])), ""]
    return lines


def action_where(action):
    if action.get("affected") is not None and action.get("total"):
        return "%s of %s %s" % (action["affected"], action["total"], action.get("unit") or "items")
    return "see score.json"


def render_score(score):
    """Short, structured score section: number, coverage, area table, blockers, what to fix first."""
    overall = score["overall"]
    lines = ["## Checklist score", ""]
    if overall["score"] is None:
        return lines + ["No score was computed: no check could be measured from the evidence supplied.", ""]
    lines += ["**%s / 100.** We could check %d%% of the checklist (%d of %d checks). %s" % (
        overall["score"], round(overall["coverage"] * 100), overall["checks_measured"], overall["checks_applicable"], score["label"]), ""]
    crawl = score.get("crawl")
    if crawl and not crawl["complete"]:
        lines += ["Note: %s." % crawl["note"], ""]
    lines += ["| Area | Score | Checks measured |", "| --- | --- | --- |"]
    for a in score.get("areas", []):
        lines.append("| %s | %s | %d of %d |" % (cell(a["label"]), "not checked" if a["score"] is None else a["score"], a["checks_measured"], a["checks_applicable"]))
    blockers = score.get("blockers") or []
    lines += ["", "**Blockers:** " + ("none flagged." if not blockers else "")]
    lines += ["- %s: %s" % (b["id"], b["description"]) for b in blockers]
    if score.get("actions"):
        lines += ["", "**Fix first** (points the score would gain if the check fully passed):", "", "| Fix | Points | Where | Check |", "| --- | --- | --- | --- |"]
        lines += ["| %s | +%s | %s | %s |" % (cell(a["fix"]), a["points_to_gain"], cell(action_where(a)), a["id"]) for a in score["actions"]]
    unchecked = [(k.split(": ", 1)[1], len(v)) for k, v in (score.get("not_measured_groups") or {}).items() if k.startswith("not-measured:")]
    if unchecked:
        lines += ["", "**Not checked** (left out of the score, not counted as passes):"]
        lines += ["- %d checks: %s" % (n, reason) for reason, n in sorted(unchecked, key=lambda i: -i[1])[:5]]
    if score.get("not_covered"):
        lines += ["", "**Not covered by this checklist:** " + "; ".join(score["not_covered"]) + "."]
    lines += ["", "Compare this score only with scores that used the same rubric version and the same checks (comparison key %s)." % score.get("comparison_key", "n/a"), ""]
    return lines


def render_report(data, narrative, score=None):
    lines = [narrative.strip(), ""] + (render_score(score) if score else [])
    lines += ["## Coverage", "", "| Area | Status | Checked / discovered | Denominator and limitation | Evidence |", "| --- | --- | --- | --- | --- |"]
    for c in data["coverage"]:
        counts = "%s / %s" % ("?" if c["checked_count"] is None else c["checked_count"], "?" if c["discovered_count"] is None else c["discovered_count"])
        note = " ".join(x for x in (c.get("denominator_note"), c.get("limitation")) if x)
        lines.append("| %s | %s | %s | %s | %s |" % (cell(c["area"]), cell(c["status"]), counts, cell(note), cell(", ".join(c.get("evidence_refs") or []))))
    lines += ["", "Coverage status describes how much was inspected, not how healthy the area is.", "", "## Findings", ""]
    ordered = sorted(data["findings"], key=lambda f: (SEVERITY_ORDER.index(sev(f)), f["id"]))
    if not ordered:
        lines += ["No findings were recorded; see coverage and limitations for what that does and does not establish.", ""]
    for name in SEVERITY_ORDER:
        group = [f for f in ordered if sev(f) == name]
        if group:
            lines += ["### %s" % name.capitalize(), ""]
            for f in group:
                lines += render_finding(f)
    plan = [f for f in data["findings"] if sev(f) != "info"]
    phases = plan_phases(plan)
    lines += ["## Action plan", "", "The prioritised plan with proposed solutions, owners, dependencies and acceptance tests is in [action-plan.md](action-plan.md): %s." % (
        ", ".join("%d %s" % (sum(1 for f in plan if phases[f["id"]] == p), p) for p in PHASES) or "no actionable findings"), "",
        "## Limitations and follow-up evidence", ""]
    limits = ["%s (%s): %s" % (c["area"], c["status"], c["limitation"]) for c in data["coverage"] if c.get("limitation")]
    assumptions = (data.get("scope") or {}).get("assumptions")
    assumptions = [assumptions] if isinstance(assumptions, str) else assumptions or []
    lines += bullets(limits + ["Assumption: %s" % a for a in assumptions]) or ["None recorded."]
    lines += ["", "## Sources", ""]
    lines += bullets(["%s (retrieved %s): %s" % (s["url"], s["retrieved_at"], s["supports"]) for s in data.get("sources") or []]) or ["None recorded."]
    return "\n".join(lines) + "\n"


def write_new(path, text, force):
    if path.exists() and not force:
        raise FileExistsError("%s already exists; pass --force to regenerate it." % path.name)
    path.write_text(text, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit_dir", type=Path)
    parser.add_argument("--narrative", type=Path, help="Markdown with your executive assessment and scope-and-method sections; enables report.md")
    parser.add_argument("--root", type=Path, help="Extra directory for resolving evidence references")
    parser.add_argument("--force", action="store_true", help="Overwrite action-plan.md and report.md if they exist")
    args = parser.parse_args()
    if not args.audit_dir.is_dir():
        parser.error("audit_dir must be an existing directory.")
    issues = contract.Issues()
    try:
        data = json.loads((args.audit_dir / "findings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print("Error: findings.json is missing or not valid JSON (%s)." % type(exc).__name__, file=sys.stderr)
        return 1
    contract.check_document(data, contract.audit_roots(args.audit_dir, args.root), issues)
    errors = [i for i in issues.items if i["level"] == "error"]
    for item in errors:
        print("ERROR %s: %s [%s]" % (item["where"], item["message"], item["code"]), file=sys.stderr)
    if errors:
        print("Not rendered: fix findings.json first (python3 scripts/validate_audit.py shows all checks).", file=sys.stderr)
        return 1
    score = None
    if (args.audit_dir / "score.json").is_file():  # a score in the audit folder is always shown, with its coverage
        try:
            score = json.loads((args.audit_dir / "score.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            print("Error: score.json is not valid JSON.", file=sys.stderr)
            return 1
        score_issues = contract.Issues()
        contract.check_score(score, score_issues)
        bad = [i for i in score_issues.items if i["level"] == "error"]
        for item in bad:
            print("ERROR %s: %s [%s]" % (item["where"], item["message"], item["code"]), file=sys.stderr)
        if bad:
            print("Not rendered: fix or regenerate score.json first.", file=sys.stderr)
            return 1
    try:
        narrative = args.narrative.read_text(encoding="utf-8") if args.narrative else None
        plan_path, report_path = args.audit_dir / "action-plan.md", args.audit_dir / "report.md"
        if not args.force:
            for path in [plan_path] + ([report_path] if narrative is not None else []):
                if path.exists():
                    raise FileExistsError("%s already exists; pass --force to regenerate it." % path.name)
        write_new(plan_path, render_plan(data), True)
        print(plan_path)
        if narrative is not None:
            write_new(report_path, render_report(data, narrative, score), True)
            print(report_path)
            if not re.search(r"(?m)^##\s", narrative):
                print("Note: the narrative has no '## ' headings; report.md needs Executive assessment and Scope and method sections.", file=sys.stderr)
        else:
            print("report.md not written: pass --narrative with your executive assessment and scope-and-method sections.", file=sys.stderr)
    except (OSError, ValueError) as exc:
        print("Error: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
