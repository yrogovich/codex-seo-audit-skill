# SEO Audit for Codex

Audit live websites and local projects before deployment with `$seo-audit`. Get evidence-backed findings, a prioritized action plan, and clear coverage limits.

This is an instruction-based Codex skill. It uses the browsing, terminal, and connected data tools available in your session; it does not bundle a crawler or require a paid SEO service.

## What it checks

- Crawlability, index eligibility, redirects, canonicals, robots and sitemaps.
- Source HTML, rendered content, mobile behavior and internal links.
- Metadata, content relevance, images and structured data.
- Performance and Core Web Vitals when measurement tools or data are available.
- Search visibility, authority and AI search considerations.
- Relevant ecommerce, local-business and multilingual concerns.

Audits distinguish observed problems from inferences and missing evidence. A full audit covers applicable disciplines; large sites may be sampled. Changes to your website require a separate request.

## Installation

Download or clone this repository, then open a terminal in its root—the directory containing `SKILL.md`, `agents/` and `references/`.

Choose one installation scope. The commands below are for macOS/Linux and create a fresh `seo-audit` folder. If it already exists, review your existing installation before replacing it.

### Personal installation

Make the skill available across projects:

```sh
mkdir -p "$HOME/.agents/skills"
mkdir "$HOME/.agents/skills/seo-audit" &&
  cp -R SKILL.md agents references "$HOME/.agents/skills/seo-audit/"
```

### Project-only installation

Replace `/absolute/path/to/your-project` with the project that will use the skill. Run these commands from this skill repository:

```sh
SEO_PROJECT='/absolute/path/to/your-project'
mkdir -p "$SEO_PROJECT/.agents/skills"
mkdir "$SEO_PROJECT/.agents/skills/seo-audit" &&
  cp -R SKILL.md agents references "$SEO_PROJECT/.agents/skills/seo-audit/"
```

You can commit that project's `.agents/skills/seo-audit/` directory to share the skill with teammates.

Codex supports user skills in `~/.agents/skills/` and repository skills in `.agents/skills/`. If the installed skill does not appear, restart Codex. See the [official skill documentation](https://learn.chatgpt.com/docs/build-skills).

Use `$seo-audit` in a Codex prompt. Avoid installing duplicate copies with the same name in multiple scopes. If you already have a working copy installed elsewhere, update that copy rather than adding another. Installation copies the files; later edits in this repository do not automatically update an installed copy.

## Audit a live website

Open a Codex workspace where the audit files should be saved, then ask:

```text
Use $seo-audit to audit https://example.com.
Create an evidence-backed report and a prioritized action plan.
Our main goal is qualified leads from English-speaking customers in the UK.
```

For a focused review:

```text
Use $seo-audit to audit https://example.com/services.
Focus on metadata, content relevance, internal links and structured data.
```

For an audit with search data:

```text
Use $seo-audit to audit https://example.com using the attached
Search Console export. Separate measured performance issues from
recommendations based on public website inspection.
```

Public inspection works without Search Console or analytics access. Connected accounts or supplied exports can deepen the analysis; missing data is reported as unknown. Browser access is needed to verify rendered pages and visual behavior.

## Audit a local project before deployment

Open the website's project in Codex, then provide its running local URL:

```text
Use $seo-audit in local-project mode to audit this codebase
and http://localhost:3000 before deployment.
Inspect source code and rendered pages, link findings to source files,
and produce a launch checklist.
```

Replace the URL with your actual port. If the server is not running:

```text
Use $seo-audit in local-project mode to audit this project before launch.
Find the documented run command and start a local preview if practical.
Prefer a production build and preview, and report any checks you cannot run.
```

The local mode:

- Traces routes, metadata, rendering, sitemap/robots generation and configuration in the code.
- Compares source intent with local HTTP responses and browser output, including direct page loads.
- Prefers a production preview; labels development-server measurements separately.
- Preserves intentional development restrictions such as local `noindex`.
- Separates fixes before launch, release-configuration checks and checks after deployment.

If the app cannot run, the audit continues with source inspection and marks runtime checks unavailable. Localhost cannot confirm production hosting behavior, actual search indexing, rankings or real-user Core Web Vitals. Those remain follow-up checks.

See the [local-project workflow](references/local-project.md) for details.

## Deliverables

Live audits are saved under `seo-audits/<hostname>/<date>-<run>/`. Local audits use `seo-audits/<project-slug>-local/<date>-<run>/`.

| File | Contents |
| --- | --- |
| `report.md` | Executive assessment, findings, evidence and coverage limits |
| `action-plan.md` | Priorities, suggested owners, dependencies and retests |
| `url-inventory.csv` | Discovered URLs and inspection status |
| `findings.json` | Structured scope, coverage and findings |
| `evidence/` | Collected evidence, including screenshots when available |
| `launch-checklist.md` | Local mode: pre-launch and production verification checklist |

Each run gets a separate folder. PDF, slides and spreadsheets are optional when requested and supported. Review audit artifacts before sharing them, especially when private project or analytics data was used.

## Skill files

- [SKILL.md](SKILL.md): entry point and audit rules.
- [agents/openai.yaml](agents/openai.yaml): Codex display metadata.
- [references/collection.md](references/collection.md): collection and sampling.
- [references/checks.md](references/checks.md): core SEO checks.
- [references/local-project.md](references/local-project.md): pre-deployment mode.
- [references/specialized.md](references/specialized.md): industry and international checks.
- [references/search-data.md](references/search-data.md): analytics, search and comparisons.
- [references/reporting.md](references/reporting.md): deliverables and evidence contract.
- [references/sources.md](references/sources.md): primary sources and design provenance.

## Acknowledgments

Inspired by [AgriciDaniel/claude-seo](https://github.com/AgriciDaniel/claude-seo) and [affaan-m/ECC's SEO skill](https://github.com/affaan-m/ECC/blob/main/skills/seo/SKILL.md). This is an independently written Codex workflow; no upstream scripts or assets are bundled.
