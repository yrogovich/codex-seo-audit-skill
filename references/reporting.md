# Audit deliverables and quality gate

## Files

Create a fresh workspace folder `seo-audits/<hostname>/<YYYY-MM-DD>-<run>/` with:

- `report.md`: executive findings, evidence and limitations.
- `action-plan.md`: implementation backlog grouped by dependency and priority.
- `url-inventory.csv`: observed URLs and collection status, with proper CSV quoting.
- `findings.json`: structured scope, coverage and findings as specified below.
- `evidence/`: only artifacts actually collected, with meaningful filenames.

`findings.json` is the source of truth. [render_report.py](../scripts/render_report.py) can generate `action-plan.md`, and `report.md` from your narrative sections, so the files cannot disagree; see [scripts.md](scripts.md). Reuse this structure at smaller scale for focused audits. Never overwrite a prior audit as a side effect. Use the user's preferred output format if specified, while retaining an inspectable evidence record.

For `local-project` mode, also follow [local-project.md](local-project.md) for environment metadata, source-to-runtime evidence, and `launch-checklist.md`. If only source inspection succeeds, keep the requested local-project mode but explicitly label runtime coverage unavailable.

## Report structure

1. **Executive assessment:** business/intent context, top verified blockers/opportunities, what is working, and recommended first actions. No forced quota of “critical” issues.
2. **Scope and method:** target, date/timezone, allowed hosts, tools, budgets, discovered/fetched/rendered counts, template/language samples, source periods, and assumptions.
3. **Coverage table:** technical/indexing; rendering/mobile; architecture/links; content/on-page; structured data; performance; media; search/authority; AI search; applicable specialized areas. Status: checked, partial, unknown, or not applicable, with evidence and explanation. Coverage status is separate from health.
4. **Findings:** group by root cause and priority. Give exact observed vs inferred behavior, affected examples/count basis, evidence, business/search implication, fix, dependencies and acceptance test.
5. **Action plan:** now/next/later, suggested owner role, dependencies and measurable validation. These are recommendations, not assigned tasks or promised deadlines.
6. **Limitations and follow-up evidence:** specific missing datasets/tools and which conclusions they prevent. Include sources and artifact links.

## Severity and confidence

| Severity | Meaning |
| --- | --- |
| Critical | Confirmed broad failure preventing important public content from being accessed or indexed, requiring urgent investigation |
| High | Confirmed material defect across an important template or high-value intent; prioritize promptly |
| Medium | Localized defect or substantive optimization opportunity with a plausible impact mechanism |
| Low | Minor improvement with limited observed scope/impact |
| Info | Context, optional experiment, or a measurement gap; not a demonstrated defect |

Severity is not confidence. Use high/medium/low confidence and observed/inferred/unverified evidence status. An unverified suspicion must not be presented as a confirmed Critical defect. Describe known business importance or label it inferred.

Default to category health summaries and measured coverage, not a composite SEO score. If the user requests a number, define a transparent check-based rubric before scoring, state weights and denominator, exclude unknown/not-applicable checks, show excluded coverage alongside the score, and label it an internal checklist metric, not a Google ranking predictor. Avoid cross-site comparisons with different coverage.

## Machine-readable contract

`findings.json` is an object with:

- `schema_version`: `1`.
- `target`, `audited_at` (ISO 8601 with timezone), `mode` (full/single-page/focused/comparison/source-only/local-project).
- `scope`: allowed hosts, requested focus, budgets, assumptions, sampling method.
- `coverage`: array of `{area, status, checked_count, discovered_count, denominator_note, limitation, evidence_refs}`. Counts may be null when unknown; use nonnegative integers otherwise. Counts describe their area, not necessarily pages.
- `findings`: array of records defined below; an empty array is valid and is not a substitute for coverage reporting.
- `sources`: array of `{url, retrieved_at, supports}` for authoritative guidance and external datasets.

Each finding:

| Field | Content |
| --- | --- |
| `id`, `category`, `title` | Stable ID such as SEO-001, affected area and precise problem |
| `severity`, `confidence`, `evidence_status` | Values defined above |
| `urls`, `affected_count`, `count_basis` | Exact examples, known count or null, and sampled/complete/estimated explanation |
| `observation`, `impact` | What happened and why it matters; distinguish inference |
| `evidence` | Array of `{ref, method, captured_at, excerpt}` with actual file paths, URLs or tool-result references; excerpt may be a concise measured result |
| `recommendation`, `acceptance_test` | Specific change and reproducible check for success |
| `owner_role`, `dependencies` | Suggested role and prerequisite finding IDs |

Allowed values (case-insensitive): `mode` as listed above; `severity` critical, high, medium, low or info; `confidence` high, medium or low; `evidence_status` observed, inferred or unverified; coverage `status` checked, partial, unknown or not-applicable. An Info finding may omit the action fields (`recommendation`, `acceptance_test`, `owner_role`); every other finding needs all fields. Critical requires `observed` evidence; an unverified suspicion is never Critical. `urls` may list fewer URLs than `affected_count` (examples) but never more.

Inventory columns: `url, final_url, discovered_via, template, fetch_status, http_status, rendered, observed_indexability, canonical, evidence_ref, notes`. Unknown HTTP/indexing values stay empty or explicitly unknown. Preserve duplicate discoveries in provenance without duplicating fetched-URL counts.

## Final verification

- Every reported blocker has direct evidence and a clear intent basis.
- Findings, action plan and JSON agree on IDs, priorities, URLs, and counts.
- Every evidence link resolves or is a named retrievable source; no nonexistent screenshots or test outputs.
- Coverage denominators are defined; unknowns are not passes; sampled findings are labeled.
- Schema recommendations reflect current eligibility and observed facts.
- Field/lab data, actual indexing/eligibility, and measured/estimated impact remain distinct.
- No unsupported uplift, penalty, authority, keyword-volume or AI-visibility claims.
- Artifacts contain no secrets or unnecessary personal data.

Run [validate_audit.py](../scripts/validate_audit.py) on the audit directory (usage in [scripts.md](scripts.md)). It covers JSON and CSV readability, the contract above, evidence links, finding-ID agreement across files and secret patterns. Resolve every error and address or explain each warning. These checks do not validate SEO conclusions, or whether report text agrees with the JSON beyond finding IDs; inspect supporting evidence and compare priorities and counts across the files yourself.
