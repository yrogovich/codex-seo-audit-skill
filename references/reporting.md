# Audit deliverables and quality gate

## Files

Create a fresh folder `seo-audits/<hostname>/<YYYY-MM-DD>-<run>/` with:

- `report.md`: findings, evidence and limits.
- `action-plan.md`: what to fix, by priority and dependency.
- `url-inventory.csv`: every URL seen and how it was checked.
- `findings.json`: scope, coverage and findings (format below).
- `evidence/`: only files you really collected, with clear names.
- `score.json`: optional, only if the user asked for a 0-100 score ([scoring.md](scoring.md)).

`findings.json` is the source of truth. [render_report.py](../scripts/render_report.py) builds `action-plan.md`, and `report.md` from your narrative, so the files cannot disagree ([scripts.md](scripts.md)). Never overwrite an earlier audit. For a focused audit, use the same structure at smaller scale. If the user wants another format, give it, but keep the evidence record.

For `local-project` mode, also follow [local-project.md](local-project.md) (extra scope fields and `launch-checklist.md`). If only the source could be inspected, keep `local-project` mode and say runtime coverage is unavailable.

## Report structure

1. **Executive assessment:** the goal, top confirmed blockers and opportunities, what works, first actions. Do not invent "critical" issues to fill a quota.
2. **Scope and method:** target, date and timezone, allowed hosts, tools, budgets, counts of discovered/fetched/rendered pages, samples, data periods, assumptions.
3. **Coverage table:** technical/indexing; rendering/mobile; architecture/links; content/on-page; structured data; performance; media; search/authority; AI search; specialized areas. Status: checked, partial, unknown or not-applicable, with evidence and a reason. Coverage is not health.
4. **Findings:** group by root cause and priority. For each: seen versus inferred, examples and count basis, evidence, why it matters, fix, dependencies, acceptance test.
5. **Action plan:** now / next / later, owner role, dependencies, how to measure success. Recommendations, not assigned tasks or deadlines.
6. **Limitations and follow-up evidence:** what data or tools were missing, what that stops you concluding, sources and artifact links.

## Severity and confidence

| Severity | Meaning |
| --- | --- |
| Critical | Confirmed, broad failure that stops important public content being reached or indexed. Urgent |
| High | Confirmed, material defect on an important page type or high-value intent. Fix soon |
| Medium | Local defect, or a real improvement with a plausible effect |
| Low | Minor improvement with limited scope |
| Info | Context, optional experiment or measurement gap. Not a proven defect |

Severity is not confidence. Give confidence (high/medium/low) and evidence status (observed/inferred/unverified) separately. Never present an unverified suspicion as a confirmed Critical defect. State known business importance, or label it inferred.

Default to per-area health summaries and coverage, not one SEO score. If the user asks for a number, use a transparent checklist rubric: state weights and denominator, leave out unknown and not-applicable checks, show the unchecked share next to the score, and label it an internal checklist metric, not a Google ranking predictor. Do not compare sites with different coverage. [score_audit.py](../scripts/score_audit.py) does this ([scoring.md](scoring.md)).

## findings.json

An object with:

- `schema_version`: `1`.
- `target`, `audited_at` (ISO 8601 with timezone), `mode` (full, single-page, focused, comparison, source-only, local-project).
- `scope`: allowed hosts, requested focus, budgets, assumptions, sampling method.
- `coverage`: array of `{area, status, checked_count, discovered_count, denominator_note, limitation, evidence_refs}`. Counts are null when unknown, otherwise non-negative integers.
- `findings`: array (below). Empty is valid, but it does not replace coverage.
- `sources`: array of `{url, retrieved_at, supports}`.

Each finding:

| Field | Content |
| --- | --- |
| `id`, `category`, `title` | Stable ID like SEO-001, the area, a precise problem |
| `severity`, `confidence`, `evidence_status` | Values from above |
| `urls`, `affected_count`, `count_basis` | Example URLs, the count (or null), and whether it is sampled, complete or estimated |
| `observation`, `impact` | What happened and why it matters. Say when inferred |
| `evidence` | Array of `{ref, method, captured_at, excerpt}`. `ref` is a real file path, URL or tool-result reference |
| `recommendation`, `acceptance_test` | The change and a repeatable check that it worked |
| `owner_role`, `dependencies` | Suggested role and IDs of findings to fix first |

Allowed values (any case): `severity` critical, high, medium, low, info; `confidence` high, medium, low; `evidence_status` observed, inferred, unverified; coverage `status` checked, partial, unknown, not-applicable.

- Info findings may omit `recommendation`, `acceptance_test` and `owner_role`. Other findings need all fields.
- Critical needs `observed` evidence.
- `urls` may list fewer URLs than `affected_count` (they are examples), never more.

Inventory columns: `url, final_url, discovered_via, template, fetch_status, http_status, rendered, observed_indexability, canonical, evidence_ref, notes`. Leave unknown values empty or write "unknown". If a URL was found several ways, list them all in `discovered_via` and keep one row.

## Final verification

- Every blocker has direct evidence and a clear reason to think it is unintended.
- Findings, action plan and JSON agree on IDs, priorities, URLs and counts.
- Every evidence link works or names a retrievable source.
- Denominators are defined, unknowns are not counted as passes, sampled findings are labeled.
- Schema advice matches current eligibility and observed facts.
- Field data, lab data, real indexing and estimates stay separate.
- No unsupported claims about uplift, penalties, authority, keyword volume or AI visibility.
- No secrets or unneeded personal data.

Run [validate_audit.py](../scripts/validate_audit.py) ([scripts.md](scripts.md)). Fix every error, and fix or explain every warning. It does not check SEO conclusions or whether report text matches the JSON beyond finding IDs, so compare priorities and counts yourself.
