# Audit deliverables and quality gate

## Files

Create a fresh workspace folder `seo-audits/<hostname>/<YYYY-MM-DD>-<run>/` with:

- `report.md`: executive findings, evidence and limitations.
- `action-plan.md`: implementation backlog grouped by dependency and priority.
- `url-inventory.csv`: observed URLs and collection status, with proper CSV quoting.
- `findings.json`: structured scope, coverage and findings as specified below.
- `evidence/`: only artifacts actually collected, with meaningful filenames.

Reuse this structure at smaller scale for focused audits. Never overwrite a prior audit as a side effect. Use the user's preferred output format if specified, while retaining an inspectable evidence record.

For `local-project` mode, also follow [local-project.md](local-project.md) for environment metadata, source-to-runtime evidence, and `launch-checklist.md`. If only source inspection succeeds, keep the requested local-project mode but explicitly label runtime coverage unavailable.

## Report structure

1. **Executive assessment:** business/intent context, top verified blockers/opportunities, what is working, and recommended first actions. No forced quota of “critical” issues.
2. **Scope and method:** target, date/timezone, allowed hosts, tools, budgets, discovered/fetched/rendered counts, template/language samples, source periods, and assumptions.
3. **Coverage table:** technical/indexing; rendering/mobile; architecture/links; content/on-page; structured data; performance; media; search/authority; AI search; applicable specialized areas. Status: checked, partial, unknown, or not applicable, with evidence and explanation. Coverage status is separate from health.
4. **Findings:** group by root cause and priority. Give exact observed vs inferred behavior, affected examples/count basis, evidence, business/search implication, proposed solution, expected impact estimate, implementation and validation time estimate, assumptions, dependencies and acceptance test.
5. **Action plan:** now/next/later, suggested owner role, expected impact, hands-on implementation and validation time ranges with assumptions, dependencies and measurable validation. Highlight quick wins; keep urgent blockers visible even when they require substantial work. These are recommendations, not assigned tasks or promised deadlines.
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

## Impact and fix-time estimates

For each actionable finding, include these estimates consistently in the report, action plan and JSON:

- **Expected impact:** High / Medium / Low / Unknown, with the expected outcome, affected scope, rationale and confidence. High means restoring access/index eligibility for important content or addressing a broad, material problem; Medium means a meaningful template or localized improvement; Low means a limited improvement. Use Unknown when available evidence cannot support a useful estimate. Impact is the expected benefit of the proposed fix, separate from issue severity and evidence status.
- **Fix time:** a hands-on range for implementation plus validation, in minutes, hours or working days. Estimate at the root-cause level and state whether it covers one page, one shared template or all affected pages. Base it on the observed code/CMS, content volume and likely owner skill. If access or implementation details are missing, give a conditional range and low confidence, or mark unknown and identify what is needed to estimate it. Do not invent precision.
- **Assumptions and dependencies:** include access, owner role, content/design work, shared components and prerequisite fixes. Separate implementation and validation work when useful. Identify shared work so adding estimates does not double-count the same fix.
- **Elapsed waiting time:** report release/approval/external-service waits separately where known. Recrawling, reindexing and measurable SEO results are separate uncertain timelines, not part of hands-on fix time. Do not promise ranking or traffic gains or invent percentage uplift.

Use an action-plan table with: ID, proposed solution, priority, expected impact and rationale, estimated fix time (including validation), assumptions/confidence, owner, dependencies and acceptance test. Place detailed evidence in the linked finding. Highlight high-impact low-effort work as quick wins without letting it displace urgent access/indexing blockers.

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
| `impact_estimate` | Object: `{level, expected_outcome, rationale, confidence}`; level high/medium/low/unknown; qualitative estimates, not unsupported uplift percentages |
| `owner_role`, `effort`, `dependencies` | Suggested role; `effort` object `{min, max, unit, includes, scope, assumptions, confidence}` for hands-on implementation plus validation; prerequisite finding IDs. Use null bounds and unit when unknown, with the reason in assumptions |
| `waiting_time` | Object `{estimate, assumptions}` for known release/external waits, separate from hands-on work; estimate null when unknown or not applicable. Label any search-effect timing as uncertain |

Allowed values (case-insensitive): `mode` as listed above; `severity` critical, high, medium, low or info; `confidence` (including inside `impact_estimate` and `effort`) high, medium or low; `evidence_status` observed, inferred or unverified; coverage `status` checked, partial, unknown or not-applicable; `impact_estimate.level` high, medium, low or unknown; `effort.unit` minutes, hours or working_days. An Info finding may omit the action fields (`recommendation`, `acceptance_test`, `impact_estimate`, `owner_role`, `effort`, `waiting_time`); every other finding needs all fields. Critical requires `observed` evidence; an unverified suspicion is never Critical. `urls` may list fewer URLs than `affected_count` (examples) but never more.

Inventory columns: `url, final_url, discovered_via, template, fetch_status, http_status, rendered, observed_indexability, canonical, evidence_ref, notes`. Unknown HTTP/indexing values stay empty or explicitly unknown. Preserve duplicate discoveries in provenance without duplicating fetched-URL counts.

## Final verification

- Every reported blocker has direct evidence and a clear intent basis.
- Findings, action plan and JSON agree on IDs, priorities, URLs, counts, impact estimates and fix-time ranges. Every actionable finding has estimates or an explicit unknown with the evidence needed to estimate it.
- Every evidence link resolves or is a named retrievable source; no nonexistent screenshots or test outputs.
- Coverage denominators are defined; unknowns are not passes; sampled findings are labeled.
- Schema recommendations reflect current eligibility and observed facts.
- Field/lab data, actual indexing/eligibility, and measured/estimated impact remain distinct.
- No unsupported uplift, penalty, authority, keyword-volume or AI-visibility claims.
- Artifacts contain no secrets or unnecessary personal data.

Run [validate_audit.py](../scripts/validate_audit.py) on the audit directory (usage in [scripts.md](scripts.md)). It covers JSON and CSV readability, the contract above, evidence links, finding-ID agreement across files and secret patterns. Resolve every error and address or explain each warning. These checks do not validate SEO conclusions, or whether report text agrees with the JSON beyond finding IDs; inspect supporting evidence and compare priorities, counts and estimates across the files yourself.
