#!/usr/bin/env python3
"""Validate a saved SEO audit directory against the deliverable contract; standard library only.

Checks structure and internal consistency (references/reporting.md). It never evaluates SEO
conclusions, never fetches anything, and never prints the value of a suspected secret.
"""

import argparse
import csv
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import sys

MODES = {"full", "single-page", "focused", "comparison", "source-only", "local-project"}
SEVERITIES = {"critical", "high", "medium", "low", "info"}
LEVELS = {"high", "medium", "low"}
EVIDENCE_STATUSES = {"observed", "inferred", "unverified"}
COVERAGE_STATUSES = {"checked", "partial", "unknown", "not-applicable"}
IMPACT_LEVELS = {"high", "medium", "low", "unknown"}
EFFORT_UNITS = {"minutes", "hours", "working_days"}
LAUNCH_STAGES = {"fix-before-launch", "verify-release-config", "verify-after-deploy"}
RUNTIME_MODES = {"development", "production-preview", "unavailable"}
TOP_LEVEL = ("schema_version", "target", "audited_at", "mode", "scope", "coverage", "findings", "sources")
COVERAGE_KEYS = ("area", "status", "checked_count", "discovered_count", "denominator_note", "limitation", "evidence_refs")
EFFORT_KEYS = ("min", "max", "unit", "includes", "scope", "assumptions", "confidence")
LOCAL_SCOPE = ("project_root", "revision", "working_tree_state", "local_origin", "intended_public_origin",
               "runtime_mode", "content_source", "startup_command", "build_result", "runtime_limitations")
INVENTORY_COLUMNS = ("url", "final_url", "discovered_via", "template", "fetch_status", "http_status",
                     "rendered", "observed_indexability", "canonical", "evidence_ref", "notes")
REQUIRED_FILES = ("report.md", "action-plan.md", "url-inventory.csv", "findings.json")
# Every core area must appear in the coverage table of a broad audit; matching is by keyword.
CORE_AREAS = (("technical/indexing", r"technical|crawl|index"), ("rendering/mobile", r"render|mobile"),
              ("architecture/links", r"architecture|link"), ("content/on-page", r"content|on-?page"),
              ("structured data", r"structured|schema"), ("performance", r"performance|vitals|speed"),
              ("media", r"image|media"), ("search/authority", r"authority|backlink|visib|search data|search console|analytics"),
              ("AI search", r"\bai\b|llm|generative"))
MAX_SCAN_BYTES = 32 * 1024 * 1024
SECRETS = (  # (label, pattern, level). Matched text is never printed.
    ("Google API key", r"AIza[0-9A-Za-z_\-]{35}", "error"),
    ("AWS access key ID", r"\bAKIA[0-9A-Z]{16}\b", "error"),
    ("private key block", r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "error"),
    ("Authorization header value", r"(?i)\bauthorization\s*:\s*(?:bearer|basic)\s+(?!\[REDACTED\])\S{8,}", "error"),
    ("API key header value", r"(?i)\bx-(?:goog-)?api-key\s*:\s*(?!\[REDACTED\])\S{8,}", "error"),
    ("JSON Web Token", r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}", "error"),
    ("cookie header", r"(?i)^\s*(?:set-)?cookie\s*:\s*\S+", "warning"),
    ("key/secret/token/password assignment", r"(?i)\b(?:api[_-]?key|secret|token|password)\b[\"']?\s*[:=]\s*[\"']?(?!\[REDACTED\])[A-Za-z0-9_\-/+=]{16,}", "warning"),
)
UPLIFT = re.compile(r"\+\s*\d+(?:\.\d+)?\s*%|\b\d+(?:\.\d+)?\s*%\s*(?:more|increase|uplift|growth|higher|boost)"
                    r"|\b(?:increase|boost|grow|lift|raise|uplift)\w*\b[^.;]{0,60}\d+(?:\.\d+)?\s*%", re.I)
OUTCOME_WORDS = re.compile(r"traffic|rank|click|conversion|revenue|visibility|impression|sales|leads|\bctr\b", re.I)
SITEWIDE = re.compile(r"site-?wide|every page|all pages|entire site|whole site", re.I)


class Issues:
    def __init__(self):
        self.items = []

    def add(self, level, code, where, message):
        self.items.append({"level": level, "code": code, "where": where, "message": message})

    def error(self, code, where, message):
        self.add("error", code, where, message)

    def warn(self, code, where, message):
        self.add("warning", code, where, message)


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def has_text(value):
    return isinstance(value, str) and bool(value.strip())


def when(value, need_tz=False):
    """Parse an ISO 8601 date/datetime; None when invalid or (if required) lacking a timezone."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return None if need_tz and parsed.tzinfo is None else parsed


def shown(value):
    return repr(value)[:60]


def pick(obj, key, allowed, where, issues, code, norm=lambda s: s.strip().lower()):
    value = obj.get(key)
    if not isinstance(value, str) or norm(value) not in allowed:
        issues.error(code, f"{where}.{key}", "Expected one of: " + ", ".join(sorted(allowed)) + f"; got {shown(value)}.")
        return None
    return norm(value)


def require_keys(obj, keys, where, issues, code):
    missing = [k for k in keys if k not in obj]
    if missing:
        issues.error(code, where, "Missing required key(s): " + ", ".join(missing) + ".")
    return not missing


def load_json(path, issues):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        issues.error("JSON_UNREADABLE", path.name, f"Cannot parse findings.json: {type(exc).__name__}: {str(exc)[:120]}")
        return None


def within(path, root):
    try:
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, ValueError):
        return False


def check_ref(ref, roots, where, issues, missing_level="error"):
    """Evidence references resolve to a file/dir under the audit or workspace, or are named sources."""
    if re.match(r"^https?://", ref, re.I):
        return
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", ref):
        issues.warn("REF_UNRESOLVABLE", where, f"Reference {shown(ref)} is a tool-result style reference that cannot be resolved here; prefer a saved evidence file.")
        return
    target = re.sub(r":\d+(?::\d+)?$", "", ref.split("#", 1)[0]).strip()
    candidates = [Path(target)] if Path(target).is_absolute() else [root / target for root in roots]
    for candidate in candidates:
        if target and candidate.exists():
            if not any(within(candidate, root) for root in roots):
                issues.warn("REF_OUTSIDE_ROOT", where, f"Reference {shown(ref)} resolves outside the audit directory and workspace.")
            return
    issues.add(missing_level, "REF_MISSING", where, f"Reference {shown(ref)} does not resolve to an existing file or directory.")


def check_effort(effort, where, issues):
    if not isinstance(effort, dict):
        issues.error("EFFORT_INVALID", where, "effort must be an object.")
        return
    if not require_keys(effort, EFFORT_KEYS, where, issues, "EFFORT_KEYS"):
        return
    low, high, unit = effort["min"], effort["max"], effort["unit"]
    if low is None or high is None:
        if low is not None or high is not None:
            issues.error("EFFORT_BOUNDS", where, "min and max must both be null (unknown) or both be numbers.")
        if unit is not None:
            issues.warn("EFFORT_UNIT", f"{where}.unit", "Use a null unit when the bounds are unknown.")
        if not has_text(effort["assumptions"]):
            issues.error("EFFORT_UNKNOWN_REASON", f"{where}.assumptions", "Unknown effort needs the reason and the missing information in assumptions.")
    else:
        if not (is_num(low) and is_num(high) and low >= 0 and high >= 0):
            issues.error("EFFORT_BOUNDS", where, "min and max must be non-negative numbers.")
        elif low > high:
            issues.error("EFFORT_BOUNDS", where, "min must not exceed max.")
        norm = re.sub(r"[ -]+", "_", unit.strip().lower()) if isinstance(unit, str) else None
        if norm not in EFFORT_UNITS:
            issues.error("EFFORT_UNIT", f"{where}.unit", "unit must be minutes, hours or working_days; got " + shown(unit) + ".")
        for key in ("includes", "scope"):
            if not has_text(effort[key]):
                issues.warn("EFFORT_DETAIL", f"{where}.{key}", f"effort.{key} should say what the estimate covers.")
    pick(effort, "confidence", LEVELS, where, issues, "EFFORT_CONFIDENCE")


def check_impact(impact, where, issues):
    if not isinstance(impact, dict):
        issues.error("IMPACT_INVALID", where, "impact_estimate must be an object.")
        return
    if not require_keys(impact, ("level", "expected_outcome", "rationale", "confidence"), where, issues, "IMPACT_KEYS"):
        return
    pick(impact, "level", IMPACT_LEVELS, where, issues, "IMPACT_LEVEL")
    pick(impact, "confidence", LEVELS, where, issues, "IMPACT_CONFIDENCE")
    for key in ("expected_outcome", "rationale"):
        if not has_text(impact[key]):
            issues.error("IMPACT_TEXT", f"{where}.{key}", f"impact_estimate.{key} must be a non-empty string (for unknown impact, say what evidence is needed).")


def check_finding(finding, index, ids, mode, roots, issues):
    where = f"findings[{index}]"
    if not isinstance(finding, dict):
        issues.error("FINDING_INVALID", where, "Each finding must be an object.")
        return
    fid = finding.get("id")
    if not has_text(fid):
        issues.error("FINDING_ID", f"{where}.id", "id must be a non-empty string.")
    elif fid in ids:
        issues.error("FINDING_DUPLICATE_ID", f"{where}.id", f"Duplicate finding id {shown(fid)}.")
    for key in ("category", "title", "observation", "impact"):
        if not has_text(finding.get(key)):
            issues.error("FINDING_TEXT", f"{where}.{key}", f"{key} must be a non-empty string.")
    severity = pick(finding, "severity", SEVERITIES, where, issues, "FINDING_SEVERITY")
    pick(finding, "confidence", LEVELS, where, issues, "FINDING_CONFIDENCE")
    status = pick(finding, "evidence_status", EVIDENCE_STATUSES, where, issues, "FINDING_EVIDENCE_STATUS")
    if severity == "critical" and status == "unverified":
        issues.error("CRITICAL_UNVERIFIED", where, "An unverified suspicion must not be reported as a Critical defect.")
    elif severity == "critical" and status == "inferred":
        issues.warn("CRITICAL_INFERRED", where, "Critical severity means a confirmed failure; verify the inference or lower the severity.")
    actionable = severity != "info"

    urls = finding.get("urls")
    locations = finding.get("source_locations")
    if not isinstance(urls, list) or not all(has_text(u) for u in urls):
        issues.error("FINDING_URLS", f"{where}.urls", "urls must be an array of non-empty strings.")
        urls = []
    elif not urls and actionable and not locations:
        issues.warn("FINDING_NO_URLS", f"{where}.urls", "An actionable finding needs exact affected URLs or source locations.")
    count = finding.get("affected_count", "missing")
    if count == "missing" or not (count is None or (is_int(count) and count >= 0)):
        issues.error("FINDING_COUNT", f"{where}.affected_count", "affected_count must be null or a non-negative integer.")
    else:
        basis = finding.get("count_basis")
        if count is not None and not has_text(basis):
            issues.error("FINDING_COUNT_BASIS", f"{where}.count_basis", "count_basis must say whether the count is sampled, complete or estimated.")
        if count is not None and len(urls) > count:
            issues.error("FINDING_COUNT_URLS", where, f"Lists {len(urls)} URLs but affected_count is {count}.")
        if isinstance(basis, str) and re.search(r"\bsampled?\b", basis, re.I) and SITEWIDE.search(
                " ".join(str(finding.get(k) or "") for k in ("title", "observation", "impact"))):
            issues.warn("SAMPLED_SITEWIDE", where, "Count basis is sampled but the text claims site-wide scope.")

    evidence = finding.get("evidence")
    if not isinstance(evidence, list):
        issues.error("FINDING_EVIDENCE", f"{where}.evidence", "evidence must be an array.")
        evidence = []
    elif not evidence:
        (issues.error if status in ("observed", "inferred") else issues.warn)(
            "FINDING_NO_EVIDENCE", f"{where}.evidence", "Observed and inferred findings need at least one evidence record.")
    for j, item in enumerate(evidence):
        ewhere = f"{where}.evidence[{j}]"
        if not isinstance(item, dict) or not require_keys(item, ("ref", "method", "captured_at", "excerpt"), ewhere, issues, "EVIDENCE_KEYS"):
            if not isinstance(item, dict):
                issues.error("EVIDENCE_KEYS", ewhere, "Each evidence record must be an object.")
            continue
        if has_text(item["ref"]):
            check_ref(item["ref"].strip(), roots, f"{ewhere}.ref", issues)
        else:
            issues.error("EVIDENCE_REF", f"{ewhere}.ref", "ref must be a non-empty string.")
        if not has_text(item["method"]):
            issues.error("EVIDENCE_METHOD", f"{ewhere}.method", "method must be a non-empty string.")
        if when(item["captured_at"]) is None:
            issues.warn("EVIDENCE_TIME", f"{ewhere}.captured_at", "captured_at should be an ISO 8601 date or time.")
        if not (item["excerpt"] is None or isinstance(item["excerpt"], str)):
            issues.error("EVIDENCE_EXCERPT", f"{ewhere}.excerpt", "excerpt must be a string or null.")

    for key in ("recommendation", "acceptance_test"):
        value = finding.get(key)
        if actionable and not has_text(value):
            issues.error("FINDING_TEXT", f"{where}.{key}", f"{key} must be a non-empty string for an actionable finding.")
        elif value is not None and not isinstance(value, str):
            issues.error("FINDING_TEXT", f"{where}.{key}", f"{key} must be a string.")
    if "impact_estimate" in finding:
        check_impact(finding.get("impact_estimate"), f"{where}.impact_estimate", issues)
    if "effort" in finding:
        check_effort(finding.get("effort"), f"{where}.effort", issues)
    if actionable and not has_text(finding.get("owner_role")):
        issues.error("FINDING_OWNER", f"{where}.owner_role", "owner_role must be a non-empty string.")
    deps = finding.get("dependencies", [])
    if not isinstance(deps, list) or not all(has_text(d) for d in deps):
        issues.error("FINDING_DEPENDENCIES", f"{where}.dependencies", "dependencies must be an array of finding IDs.")
    waiting = finding.get("waiting_time")
    if waiting is not None:
        if not isinstance(waiting, dict) or not require_keys(waiting, ("estimate", "assumptions"), f"{where}.waiting_time", issues, "WAITING_KEYS"):
            if not isinstance(waiting, dict):
                issues.error("WAITING_KEYS", f"{where}.waiting_time", "waiting_time must be an object {estimate, assumptions}.")
        elif waiting["estimate"] is not None and not has_text(waiting["assumptions"]):
            issues.warn("WAITING_ASSUMPTIONS", f"{where}.waiting_time", "A waiting-time estimate needs its assumptions.")

    claims = [finding.get("impact"), finding.get("recommendation")]
    if isinstance(finding.get("impact_estimate"), dict):
        claims += [finding["impact_estimate"].get("expected_outcome"), finding["impact_estimate"].get("rationale")]
    for claim in claims:
        if isinstance(claim, str) and UPLIFT.search(claim) and OUTCOME_WORDS.search(claim):
            issues.warn("UNSUPPORTED_UPLIFT", where, "Text appears to promise a percentage traffic/ranking/conversion change; keep estimates qualitative unless measured.")
            break
    if status != "observed" and any(isinstance(c, str) and re.search(r"\bpenalt(?:y|ies|ized)\b|manual action", c, re.I) for c in claims + [finding.get("observation")]):
        issues.warn("PENALTY_CLAIM", where, "Penalty/manual-action language needs observed evidence.")

    if mode == "local-project":
        pick(finding, "launch_stage", LAUNCH_STAGES, where, issues, "LOCAL_LAUNCH_STAGE")
        if "runtime_mode" in finding:
            pick(finding, "runtime_mode", RUNTIME_MODES, where, issues, "LOCAL_RUNTIME_MODE")
        else:
            issues.warn("LOCAL_RUNTIME_MODE", where, "Local findings should record the runtime_mode they were observed in.")
    if locations is not None:
        if not isinstance(locations, list) or not all(
                isinstance(l, dict) and has_text(l.get("path")) and (l.get("line") is None or (is_int(l.get("line")) and l["line"] >= 1))
                for l in locations):
            issues.error("SOURCE_LOCATIONS", f"{where}.source_locations", "source_locations must be [{path, line}] with line null or a positive integer.")


def find_cycle(graph):
    state = {}

    def visit(node, stack):
        state[node] = 1
        for nxt in graph.get(node, ()):
            if state.get(nxt) == 1:
                return stack + [node, nxt]
            if nxt not in state:
                cycle = visit(nxt, stack + [node])
                if cycle:
                    return cycle
        state[node] = 2
        return None

    for node in graph:
        if node not in state:
            cycle = visit(node, [])
            if cycle:
                return cycle
    return None


def check_dependencies(findings, issues):
    ids = {f["id"] for f in findings if isinstance(f, dict) and has_text(f.get("id"))}
    graph = {}
    for i, f in enumerate(findings):
        if not isinstance(f, dict) or not has_text(f.get("id")) or not isinstance(f.get("dependencies"), list):
            continue
        graph[f["id"]] = []
        for dep in f["dependencies"]:
            if dep == f["id"]:
                issues.error("DEPENDENCY_SELF", f"findings[{i}].dependencies", "A finding cannot depend on itself.")
            elif dep not in ids:
                issues.error("DEPENDENCY_UNKNOWN", f"findings[{i}].dependencies", f"Unknown finding id {shown(dep)}.")
            else:
                graph[f["id"]].append(dep)
    cycle = find_cycle(graph)
    if cycle:
        issues.error("DEPENDENCY_CYCLE", "findings", "Dependency cycle: " + " -> ".join(cycle) + ".")


def check_coverage(coverage, mode, roots, issues):
    if not isinstance(coverage, list) or not coverage:
        issues.error("COVERAGE_INVALID", "coverage", "coverage must be a non-empty array of per-area records.")
        return
    areas = []
    for i, entry in enumerate(coverage):
        where = f"coverage[{i}]"
        if not isinstance(entry, dict) or not require_keys(entry, COVERAGE_KEYS, where, issues, "COVERAGE_KEYS"):
            if not isinstance(entry, dict):
                issues.error("COVERAGE_KEYS", where, "Each coverage record must be an object.")
            continue
        if not has_text(entry["area"]):
            issues.error("COVERAGE_AREA", f"{where}.area", "area must be a non-empty string.")
        else:
            areas.append(entry["area"].lower())
        status = pick(entry, "status", COVERAGE_STATUSES, where, issues, "COVERAGE_STATUS", norm=lambda s: re.sub(r"[ _]+", "-", s.strip().lower()))
        counts = {}
        for key in ("checked_count", "discovered_count"):
            if not (entry[key] is None or (is_int(entry[key]) and entry[key] >= 0)):
                issues.error("COVERAGE_COUNT", f"{where}.{key}", f"{key} must be null or a non-negative integer.")
            else:
                counts[key] = entry[key]
        if None not in counts.values() and len(counts) == 2 and counts["checked_count"] > counts["discovered_count"]:
            issues.warn("COVERAGE_COUNT", where, "checked_count exceeds discovered_count; check the denominator.")
        refs = entry["evidence_refs"]
        if not isinstance(refs, list) or not all(has_text(r) for r in refs):
            issues.error("COVERAGE_REFS", f"{where}.evidence_refs", "evidence_refs must be an array of strings.")
            refs = []
        for j, ref in enumerate(refs):
            check_ref(ref.strip(), roots, f"{where}.evidence_refs[{j}]", issues)
        if status == "checked" and not refs:
            issues.warn("COVERAGE_NO_EVIDENCE", where, "A checked area should cite evidence.")
        if status in ("partial", "unknown") and not has_text(entry["limitation"]):
            issues.warn("COVERAGE_LIMITATION", where, "A partial or unknown area must name its limitation.")
        if status == "not-applicable" and not (has_text(entry["limitation"]) or has_text(entry["denominator_note"])):
            issues.warn("COVERAGE_REASON", where, "A not-applicable area needs a reason.")
    if mode in ("full", "local-project", "comparison", "source-only"):
        for label, pattern in CORE_AREAS:
            if not any(re.search(pattern, area) for area in areas):
                issues.warn("COVERAGE_MISSING_AREA", "coverage", f"No coverage record appears to cover core area '{label}'; report it even if unknown.")


def check_scope(scope, mode, issues):
    if not isinstance(scope, dict):
        issues.error("SCOPE_INVALID", "scope", "scope must be an object.")
        return
    if mode == "local-project" and require_keys(scope, LOCAL_SCOPE, "scope", issues, "LOCAL_SCOPE_KEYS"):
        pick(scope, "runtime_mode", RUNTIME_MODES, "scope", issues, "LOCAL_RUNTIME_MODE")


def check_sources(sources, has_findings, issues):
    if not isinstance(sources, list):
        issues.error("SOURCES_INVALID", "sources", "sources must be an array of {url, retrieved_at, supports}.")
        return
    if has_findings and not sources:
        issues.warn("SOURCES_EMPTY", "sources", "Consequential recommendations should cite authoritative guidance with a retrieval date.")
    for i, source in enumerate(sources):
        where = f"sources[{i}]"
        if not isinstance(source, dict) or not require_keys(source, ("url", "retrieved_at", "supports"), where, issues, "SOURCE_KEYS"):
            if not isinstance(source, dict):
                issues.error("SOURCE_KEYS", where, "Each source must be an object.")
            continue
        if not (isinstance(source["url"], str) and re.match(r"^https?://", source["url"], re.I)):
            issues.error("SOURCE_URL", f"{where}.url", "url must be an http(s) URL.")
        if when(source["retrieved_at"]) is None:
            issues.error("SOURCE_RETRIEVED", f"{where}.retrieved_at", "retrieved_at must be an ISO 8601 date or time.")
        if not has_text(source["supports"]):
            issues.warn("SOURCE_SUPPORTS", f"{where}.supports", "Say which claim the source supports.")


def check_inventory(path, roots, issues, stats):
    try:
        with path.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.reader(stream, strict=True)
            header = next(reader, None)
            rows = [(reader.line_num, row) for row in reader if row]
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        issues.error("INVENTORY_UNREADABLE", path.name, f"CSV is not readable: {type(exc).__name__}.")
        return set()
    if header is None:
        issues.error("INVENTORY_HEADER", path.name, "CSV is empty; the header row is required.")
        return set()
    header = [h.strip() for h in header]
    if len(set(header)) != len(header):
        issues.error("INVENTORY_HEADER", path.name, "Duplicate column names in the header.")
    missing = [c for c in INVENTORY_COLUMNS if c not in header]
    if missing:
        issues.error("INVENTORY_HEADER", path.name, "Missing column(s): " + ", ".join(missing) + ".")
        return set()
    seen, urls = {}, set()
    stats["inventory_rows"] = len(rows)
    stats["inventory_with_http_status"] = stats["inventory_rendered"] = 0
    for line, values in rows:
        where = f"{path.name}:{line}"
        if len(values) != len(header):
            issues.error("INVENTORY_ROW_WIDTH", where, f"Row has {len(values)} fields; the header has {len(header)}.")
            continue
        row = dict(zip(header, (v.strip() for v in values)))
        if not row["url"]:
            issues.error("INVENTORY_URL", where, "url is empty.")
            continue
        if row["url"] in seen:
            issues.error("INVENTORY_DUPLICATE", where, f"Duplicate url (first on line {seen[row['url']]}); record extra discoveries in discovered_via.")
        seen.setdefault(row["url"], line)
        urls.update(u for u in (row["url"], row["final_url"]) if u)
        status = row["http_status"]
        if status and status.lower() != "unknown":
            if status.isdigit() and 100 <= int(status) <= 599:
                stats["inventory_with_http_status"] += 1
            else:
                issues.error("INVENTORY_HTTP_STATUS", where, f"http_status must be empty, 'unknown' or a 3-digit HTTP status; got {shown(status)}.")
        if row["rendered"].lower() in ("yes", "true", "1", "y"):
            stats["inventory_rendered"] += 1
        if row["evidence_ref"]:
            check_ref(row["evidence_ref"], roots, where, issues)
    if not rows:
        issues.warn("INVENTORY_EMPTY", path.name, "The inventory has no rows; confirm no URL was observed.")
    return urls


def check_markdown(audit_dir, findings, issues):
    ids = [f["id"] for f in findings if isinstance(f, dict) and has_text(f.get("id"))]
    prefixes = {re.sub(r"\d+$", "", i) for i in ids if re.search(r"\d+$", i)} - {""}
    for name, needs_all in (("report.md", True), ("action-plan.md", False)):
        path = audit_dir / name
        if not path.is_file():
            continue
        body = path.read_text(encoding="utf-8", errors="replace")
        for f in findings:
            if not isinstance(f, dict) or not has_text(f.get("id")):
                continue
            actionable = str(f.get("severity", "")).strip().lower() != "info"
            if (needs_all or actionable) and not re.search(r"(?<![\w-])" + re.escape(f["id"]) + r"(?![\w-])", body):
                issues.error("ID_NOT_IN_MARKDOWN", name, f"Finding {f['id']} appears in findings.json but not in {name}.")
        if prefixes:
            found = set(re.findall(r"(?<![\w-])(?:" + "|".join(map(re.escape, sorted(prefixes))) + r")\d+(?![\w-])", body)) - set(ids)
            if found:
                issues.warn("UNKNOWN_ID_IN_MARKDOWN", name, "IDs not in findings.json (a prior audit's IDs are fine): " + ", ".join(sorted(found)[:10]) + ".")


def scan_artifacts(audit_dir, issues, stats):
    patterns = [(label, re.compile(pattern, re.M), level) for label, pattern, level in SECRETS]
    env_key = os.environ.get("PAGESPEED_API_KEY")
    scanned = 0
    for folder, _dirs, files in os.walk(audit_dir):
        for name in sorted(files):
            path = Path(folder) / name
            rel = path.relative_to(audit_dir).as_posix()
            if path.is_symlink() or name == ".DS_Store":
                continue
            try:
                if path.stat().st_size > MAX_SCAN_BYTES:
                    issues.warn("SCAN_SKIPPED", rel, "File is larger than 32 MiB and was not scanned for secrets.")
                    continue
                data = path.read_bytes()
            except OSError:
                issues.warn("SCAN_SKIPPED", rel, "File could not be read for the secret scan.")
                continue
            if b"\0" in data[:8192]:
                continue
            scanned += 1
            body = data.decode("utf-8", errors="replace")
            for label, pattern, level in patterns:
                matches = list(pattern.finditer(body))
                if matches:
                    line = body.count("\n", 0, matches[0].start()) + 1
                    issues.add(level, "SECRET_PATTERN", rel, f"{len(matches)} possible {label}(s); first at line {line}. Value not shown; remove or redact it.")
            if env_key and len(env_key) >= 8 and env_key in body:
                issues.error("SECRET_ENV_VALUE", rel, "Contains the value of PAGESPEED_API_KEY. Remove it.")
            if name.endswith(".json") and name != "findings.json":
                try:
                    json.loads(body)
                except ValueError:
                    issues.warn("EVIDENCE_JSON_INVALID", rel, "File does not parse as JSON (fine for saved error responses; otherwise re-save it).")
    stats["files_scanned"] = scanned


def audit_roots(audit_dir, extra_root=None):
    """Directories evidence references resolve against: the audit folder, then the workspace above seo-audits/."""
    audit_dir = audit_dir.resolve()
    roots = [audit_dir]
    workspace = extra_root or (audit_dir.parent.parent.parent if audit_dir.parent.parent.name == "seo-audits" else None)
    if workspace and workspace.resolve() != audit_dir:
        roots.append(workspace.resolve())
    return roots


def check_document(data, roots, issues):
    """Validate a parsed findings.json against the contract in references/reporting.md: (mode, findings)."""
    if not isinstance(data, dict):
        issues.error("JSON_ROOT", "findings.json", "The top level must be an object.")
        return None, []
    require_keys(data, TOP_LEVEL, "findings.json", issues, "TOP_LEVEL_KEYS")
    if data.get("schema_version") != 1 or isinstance(data.get("schema_version"), bool):
        issues.error("SCHEMA_VERSION", "schema_version", "schema_version must be the integer 1.")
    if not has_text(data.get("target")):
        issues.error("TARGET", "target", "target must be a non-empty string.")
    if when(data.get("audited_at"), need_tz=True) is None:
        issues.error("AUDITED_AT", "audited_at", "audited_at must be ISO 8601 with a timezone, for example 2026-11-09T12:00:00+01:00.")
    mode = pick(data, "mode", MODES, "findings.json", issues, "MODE") if "mode" in data else None
    check_scope(data.get("scope"), mode, issues)
    check_coverage(data.get("coverage"), mode, roots, issues)
    findings = data.get("findings")
    if not isinstance(findings, list):
        issues.error("FINDINGS_INVALID", "findings", "findings must be an array (empty is allowed).")
        findings = []
    seen = set()
    for i, finding in enumerate(findings):
        check_finding(finding, i, seen, mode, roots, issues)
        if isinstance(finding, dict) and has_text(finding.get("id")):
            seen.add(finding["id"])
    check_dependencies(findings, issues)
    check_sources(data.get("sources"), bool(findings), issues)
    return mode, findings


def validate(audit_dir, extra_root=None):
    issues, stats = Issues(), {}
    audit_dir = audit_dir.resolve()
    roots = audit_roots(audit_dir, extra_root)
    if not re.match(r"\d{4}-\d{2}-\d{2}", audit_dir.name):
        issues.warn("DIR_NAME", audit_dir.name, "Audit folders are named <YYYY-MM-DD>-<run>.")
    for name in REQUIRED_FILES:
        path = audit_dir / name
        if not path.is_file():
            issues.error("FILE_MISSING", name, f"Required deliverable {name} is missing.")
        elif path.stat().st_size == 0:
            issues.error("FILE_EMPTY", name, f"{name} is empty.")
    if not (audit_dir / "evidence").is_dir():
        issues.warn("EVIDENCE_DIR", "evidence/", "No evidence/ directory; reported evidence refs must point somewhere else that exists.")

    data = load_json(audit_dir / "findings.json", issues) if (audit_dir / "findings.json").is_file() else None
    mode, findings = None, []
    if data is not None:
        mode, findings = check_document(data, roots, issues)
    inventory = check_inventory(audit_dir / "url-inventory.csv", roots, issues, stats) if (audit_dir / "url-inventory.csv").is_file() else set()
    if inventory and mode != "source-only":
        for i, finding in enumerate(findings):
            urls = finding.get("urls") if isinstance(finding, dict) else None
            absent = [u for u in urls if isinstance(u, str) and u.startswith(("http://", "https://")) and u not in inventory] if isinstance(urls, list) else []
            if absent:
                issues.warn("FINDING_URL_NOT_IN_INVENTORY", f"findings[{i}].urls", f"{len(absent)} URL(s) are not in url-inventory.csv, for example {shown(absent[0])}.")
    check_markdown(audit_dir, findings, issues)
    if mode == "local-project":
        checklist = audit_dir / "launch-checklist.md"
        if not checklist.is_file():
            issues.error("FILE_MISSING", "launch-checklist.md", "local-project audits require launch-checklist.md.")
        elif not re.search(r"\b(?:pass|fail|pending|not-applicable)\b", checklist.read_text(encoding="utf-8", errors="replace"), re.I):
            issues.warn("CHECKLIST_STATUS", "launch-checklist.md", "No item statuses (pass/fail/pending/not-applicable) found.")
    scan_artifacts(audit_dir, issues, stats)
    stats.update({"mode": mode, "findings": len(findings), "coverage_areas": len(data.get("coverage", [])) if isinstance(data, dict) and isinstance(data.get("coverage"), list) else 0})
    return issues.items, stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit_dir", type=Path, help="Audit directory, e.g. seo-audits/example.com/2026-11-09-1")
    parser.add_argument("--root", type=Path, help="Extra directory for resolving source/evidence refs (default: workspace above seo-audits/)")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as failures")
    parser.add_argument("--json", action="store_true", help="Print machine-readable results")
    args = parser.parse_args()
    if not args.audit_dir.is_dir():
        parser.error("audit_dir must be an existing directory.")
    issues, stats = validate(args.audit_dir, args.root)
    errors = [i for i in issues if i["level"] == "error"]
    warnings = [i for i in issues if i["level"] == "warning"]
    failed = bool(errors) or (args.strict and bool(warnings))
    if args.json:
        print(json.dumps({"audit_dir": str(args.audit_dir), "ok": not failed, "errors": len(errors), "warnings": len(warnings),
                          "stats": stats, "issues": issues}, indent=2, ensure_ascii=False))
    else:
        print(f"Audit: {args.audit_dir}")
        print("Mode: {mode} | findings: {findings} | coverage areas: {coverage_areas} | inventory rows: {rows} "
              "(with HTTP status: {http}, rendered: {rendered}) | files scanned: {files}".format(
                  mode=stats.get("mode"), findings=stats["findings"], coverage_areas=stats["coverage_areas"],
                  rows=stats.get("inventory_rows", "n/a"), http=stats.get("inventory_with_http_status", "n/a"),
                  rendered=stats.get("inventory_rendered", "n/a"), files=stats.get("files_scanned", 0)))
        for item in errors + warnings:
            print(f"{item['level'].upper():7} {item['where']}: {item['message']} [{item['code']}]")
        print(f"Result: {'FAIL' if failed else 'PASS'} - {len(errors)} error(s), {len(warnings)} warning(s).")
        print("Structural checks only: SEO conclusions, evidence content and recommendations were not evaluated.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
