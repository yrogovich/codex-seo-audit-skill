#!/usr/bin/env python3
"""Render action-plan.md (and report.md) from findings.json so the files cannot disagree; standard library only.

findings.json is the single source of truth. Findings are split into two tracks: technical (for developers) and
content (for writers and editors). The renderer refuses a document that fails the contract checks, never invents
content, and keeps the auditor's own narrative (the short summary and scope) verbatim."""

import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_audit as contract  # noqa: E402

SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"]
TRACKS = (("technical", "Technical", "for developers"), ("content", "Content", "for writers and editors"))
URL_LIMIT, EVIDENCE_EXCERPT = 5, 300


def cell(value):
    text = " ".join(str(value if value is not None else "").split())
    return text.replace("|", "\\|") or "-"


def sev(finding):
    return finding["severity"].strip().lower()


def track_of(finding):
    return finding["track"].strip().lower()


def ordered(findings):
    """Most severe first, then by ID."""
    return sorted(findings, key=lambda f: (SEVERITY_ORDER.index(sev(f)), f["id"]))


def affected_text(finding):
    count = finding.get("affected_count")
    basis = (finding.get("count_basis") or "").strip()
    return ("?" if count is None else str(count)) + (" (%s)" % basis[:40] if basis else "")


def plan_table(findings):
    rows = ["| ID | Priority | Fix | Affected | How to check |", "| --- | --- | --- | --- | --- |"]
    rows += ["| %s | %s | %s | %s | %s |" % (cell(f["id"]), sev(f).capitalize(), cell(f.get("recommendation")), cell(affected_text(f)), cell(f.get("acceptance_test")))
             for f in ordered(findings)]
    return rows


def render_plan(data):
    actionable = [f for f in data["findings"] if sev(f) != "info"]
    info = [f for f in data["findings"] if sev(f) == "info"]
    lines = ["# Action plan: %s" % data["target"], "",
             "Audit date: %s. Generated from findings.json by render_report.py; change findings.json and re-render rather than editing this file." % data["audited_at"], "",
             "Work from the top of each table: the most severe findings come first.", ""]
    for key, label, audience in TRACKS:
        group = [f for f in actionable if track_of(f) == key]
        lines += ["## %s fixes (%s)" % (label, audience), ""]
        lines += plan_table(group) if group else ["Nothing in this group."]
        lines.append("")
    lines += ["## Not scheduled (Info)", ""]
    lines += ["- %s: %s" % (f["id"], f["title"]) for f in ordered(info)] or ["None."]
    return "\n".join(lines) + "\n"


def bullets(items):
    return ["- " + item for item in items]


def render_finding(f):
    lines = ["#### %s: %s" % (f["id"], f["title"]), "", "%s · %s · %s" % (sev(f).capitalize(), f["evidence_status"], f["category"]), ""]
    count, urls = f.get("affected_count"), f.get("urls") or []
    examples = ", ".join("`%s`" % u for u in urls[:URL_LIMIT]) + (" (+%d more in findings.json)" % (len(urls) - URL_LIMIT) if len(urls) > URL_LIMIT else "")
    one = lambda text: " ".join(str(text).split())  # noqa: E731  (a line break would split the bullet)
    lines += ["- **Affected:** %s%s" % (affected_text(f) if count is not None else "count unknown", ". " + examples if examples else ""),
              "- **Problem:** " + one(f["observation"]), "- **Why it matters:** " + one(f["impact"])]
    if sev(f) != "info":
        lines += ["- **Fix:** " + one(f["recommendation"]), "- **Check:** " + one(f["acceptance_test"])]
    for e in f.get("evidence") or []:
        excerpt = " ".join(str(e.get("excerpt") or "").split())[:EVIDENCE_EXCERPT]
        lines.append("- **Evidence:** `%s` (%s, %s)%s" % (e["ref"], e["method"], e["captured_at"], ": " + excerpt if excerpt else ""))
    local = ["%s: %s" % (k, v) for k, v in (("Launch stage", f.get("launch_stage")), ("Runtime mode", f.get("runtime_mode"))) if v]
    locations = ["`%s%s`" % (s["path"], ":%d" % s["line"] if s.get("line") else "") for s in f.get("source_locations") or []]
    if local or locations:
        lines.append("- **Local project:** " + "; ".join(local + (["source " + ", ".join(locations)] if locations else [])))
    return lines + [""]


def action_where(action):
    if action.get("affected") is not None and action.get("total"):
        return "%s of %s %s" % (action["affected"], action["total"], action.get("unit") or "items")
    return "see score.json"


def google_text(action):
    basis, link = action.get("basis"), action.get("google")
    return "[%s](%s)" % (basis, link) if basis and link else "our check"


def render_score(score):
    """Short score section: number, technical and content scores, blockers, what to fix first, then details."""
    overall = score["overall"]
    lines = ["## Checklist score", ""]
    if overall["score"] is None:
        return lines + ["No score was computed: no check could be measured from the evidence supplied.", ""]
    lines += ["**%s / 100.** We could check %d%% of the checklist (%d of %d checks). %s" % (
        overall["score"], round(overall["coverage"] * 100), overall["checks_measured"], overall["checks_applicable"], score["label"]), ""]
    if score.get("tracks"):
        lines += ["| Track | Score | Checks measured |", "| --- | --- | --- |"]
        lines += ["| %s | %s | %d of %d |" % (t["label"], "not checked" if t["score"] is None else t["score"], t["checks_measured"], t["checks_applicable"]) for t in score["tracks"]]
        lines.append("")
    crawl = score.get("crawl")
    if crawl and not crawl["complete"]:
        lines += ["Note: %s." % crawl["note"], ""]
    blockers = score.get("blockers") or []
    lines += ["**Blockers:** " + ("none flagged." if not blockers else "")]
    lines += ["- %s: %s" % (b["id"], b["description"]) for b in blockers]
    if score.get("actions"):
        lines += ["", "**Fix first** (points the score would gain if the check fully passed):", "", "| Fix | Track | Points | Where | Google |", "| --- | --- | --- | --- | --- |"]
        lines += ["| %s | %s | +%s | %s | %s |" % (cell(a["fix"]), (a.get("track") or "-").capitalize(), a["points_to_gain"], cell(action_where(a)), google_text(a)) for a in score["actions"][:5]]
    lines += ["", "**By area:**", "", "| Area | Score | Checks measured |", "| --- | --- | --- |"]
    lines += ["| %s | %s | %d of %d |" % (cell(a["label"]), "not checked" if a["score"] is None else a["score"], a["checks_measured"], a["checks_applicable"]) for a in score.get("areas", [])]
    unchecked = [(k.split(": ", 1)[1], len(v)) for k, v in (score.get("not_measured_groups") or {}).items() if k.startswith("not-measured:")]
    if unchecked:
        lines += ["", "**Not checked** (left out of the score, not counted as passes):"]
        lines += ["- %d checks: %s" % (n, reason) for reason, n in sorted(unchecked, key=lambda i: -i[1])[:3]]
    if score.get("not_covered"):
        lines += ["", "**Not covered by this checklist:** " + "; ".join(score["not_covered"]) + "."]
    lines += ["", "Compare this score only with scores that used the same rubric version and the same checks (comparison key %s)." % score.get("comparison_key", "n/a"), ""]
    return lines


def render_report(data, narrative, score=None):
    lines = [narrative.strip(), ""] + (render_score(score) if score else [])
    findings = data["findings"]
    counts = ", ".join("%d %s" % (sum(1 for f in findings if track_of(f) == key and sev(f) != "info"), key) for key, _, _ in TRACKS)
    lines += ["## Findings", "", "Fix list with priorities: [action-plan.md](action-plan.md) (%s)." % counts, ""]
    if not findings:
        lines += ["No findings were recorded; see coverage and limitations for what that does and does not establish.", ""]
    for key, label, audience in TRACKS:
        group = ordered([f for f in findings if track_of(f) == key])
        if group:
            lines += ["### %s (%s)" % (label, audience), ""]
            for f in group:
                lines += render_finding(f)
    lines += ["## Coverage", "", "| Area | Status | Checked / discovered | Denominator and limitation | Evidence |", "| --- | --- | --- | --- | --- |"]
    for c in data["coverage"]:
        numbers = "%s / %s" % ("?" if c["checked_count"] is None else c["checked_count"], "?" if c["discovered_count"] is None else c["discovered_count"])
        note = " ".join(x for x in (c.get("denominator_note"), c.get("limitation")) if x)
        lines.append("| %s | %s | %s | %s | %s |" % (cell(c["area"]), cell(c["status"]), numbers, cell(note), cell(", ".join(c.get("evidence_refs") or []))))
    lines += ["", "Coverage status describes how much was inspected, not how healthy the area is.", "", "## Limitations and follow-up evidence", ""]
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
    parser.add_argument("--narrative", type=Path, help="Markdown with your short summary and scope; enables report.md")
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
                print("Note: the narrative has no '## ' headings; start report.md with a '## Summary' section.", file=sys.stderr)
        else:
            print("report.md not written: pass --narrative with your short summary and scope.", file=sys.stderr)
    except (OSError, ValueError) as exc:
        print("Error: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
