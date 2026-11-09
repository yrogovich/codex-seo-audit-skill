# Local project audit before deployment

Use this mode for a codebase and its local runtime. The goal is to identify launch blockers and implementable SEO improvements with file/line evidence plus actual responses and rendered pages. An audit does not authorize source edits or deployment.

## Establish the local environment

1. Read project instructions and inspect the working-tree status, package manifests, lockfiles, documented run/build commands, routing structure, and relevant deployment configuration. Identify the web app in a monorepo. Preserve existing changes; record commit and dirty-state status when available.
2. Reuse the user-specified or already running local server when it belongs to this app. Otherwise discover the documented command and port from project configuration. If the target app remains ambiguous, ask while continuing useful source inspection. Do not assume port 3000 or kill another process to free a port.
3. Starting an ordinary local development/preview server and building the app are part of this mode when supported by the project. Inspect scripts and build hooks first. Do not execute deployment, publishing, migrations, production writes, or destructive cleanup as part of setup. Use existing dependencies or the project's normal installation workflow where authorized; never reset configuration to make the audit run.
4. Prefer the project's documented production build and local preview to assess generated SEO behavior. If only a dev server works, continue and label it development mode. Do not force a guessed production flag or rewrite environment files. Builds may fetch CMS data; establish whether data is local, mocked, staging or production without exposing secret values. Missing credentials/content become coverage limitations.
5. Record project root, branch/commit if present, local origin including port, server command, dev/production-preview status, intended public origin if known, content source type, and browser reachability. Match local ports to the app using logs/configuration. A browser running elsewhere may not reach the same localhost; use an available local tool or report runtime coverage unavailable. Do not create a public tunnel merely to enable testing.

Track processes started for the audit and stop only those when finished, unless the user wants the preview left running. Preserve pre-existing servers. Ordinary build artifacts are acceptable; inspect and report unexpected tracked changes without reverting user work.

## Source inspection and route inventory

Trace the actual framework's route, layout, document/head and metadata mechanisms using installed versions and project conventions. Follow imports and data sources; do not infer output from filenames alone. Review:

- Global defaults and per-route title/description overrides, canonical/base URL construction, robots directives, language alternates, social metadata, and fallback behavior for missing CMS fields.
- Server/static/client rendering boundaries for main content, navigation, links and JSON-LD; data-loading, cache and revalidation behavior that can leave stale or empty metadata.
- Robots/sitemap generators and static files, URL inclusion rules, sitemap indexes, lastmod sources, pagination, parameters, dynamic routes and localization.
- Redirect/rewrite rules, error handling and 404 status, trailing-slash/base-path behavior, route-specific headers, and hosting rules not exercised by the local server.
- Reusable content templates, image components, navigation and breadcrumb logic, structured-data builders and escaping, and duplicate metadata caused by layout inheritance.

Combine source-defined routes with generated route manifests, local links, sitemaps and available content fixtures. Dynamic route patterns are not evidence that every slug exists. Include representative valid and missing slugs, translated pages, pagination and relevant filtered variants. Avoid submitting forms or invoking action endpoints.

## Local response and browser checks

Apply the core checks to the local origin. Capture original status, headers and HTML where available, then inspect rendered content on mobile and desktop for each important template. Compare source intent with emitted metadata, canonical, robots, links and structured data. Test a direct deep-link load as well as in-app navigation: client navigation can hide server-side failures. Check missing-page behavior, redirects and lazy/interactive content.

Use a controlled origin mapping for intended public URLs in generated sitemaps, canonicals or hreflang: preserve the emitted URL as evidence, then separately test its path/query on the explicitly scoped local origin when meaningful. Do not rewrite artifacts or automatically crawl the production host. A production canonical emitted locally may be correct. A localhost canonical becomes a release defect only when production configuration/build evidence shows it will leak; otherwise it is a release check.

With the bundled collectors, pass the exact local origin as `--allow-local http://localhost:3000` to [probe.py](../scripts/probe.py) and [crawl.py](../scripts/crawl.py) (see [scripts.md](scripts.md)); only that origin is admitted, never an adjacent port, another private address, or a cloud-metadata or link-local address. `crawl.py --ignore-robots-for-local` applies the exception below to that origin alone and records it as `robots_exception` in its `summary.json`; copy that record into the audit's scope. An explicit local-project audit permits inspecting the specified local app even when its development robots disallows crawling. Record that controlled exception, retain all other crawl budgets, and do not alter robots. This exception does not extend to public/staging hosts, adjacent ports, arbitrary private addresses, or redirects leaving the local scope. Keep intentional local/staging noindex or authentication intact; inspect whether environment conditions produce the intended release behavior. Do not call localhost's lack of public indexing a defect.

Local performance is lab evidence only. Prefer production-preview measurements; label dev-server/HMR overhead, local assets, mocked data, warm caches and absent CDN effects. Report measured bottlenecks without extrapolating production field Core Web Vitals. If a browser or performance tool cannot run, continue the code/HTTP audit and mark those areas unknown.

Use local Lighthouse when available, then summarize its saved JSON with [pagespeed_check.py](../scripts/pagespeed_check.py) using `--input`; see [scripts.md](scripts.md). Hosted PageSpeed cannot reach localhost. Do not publish or tunnel a local project to obtain a score.

## Findings and launch decision

For each local finding, connect the observed route/URL to the source file and verified line when possible. Include the run mode, response/DOM evidence, production relevance, exact suggested change and retest. If the implementation owner is uncertain, say so. A code-only observation is not a runtime observation.

Separate these outcomes:

- **Fix before launch:** confirmed source/runtime defects affecting intended public content, with demonstrated release relevance.
- **Verify release configuration:** environment-dependent behavior whose release value remains unknown, such as robots, public base URL or CMS settings.
- **Verify after deployment:** production-only behavior and measurements.

Use the usual severity/confidence fields. Do not call a development-only restriction Critical; a demonstrated production-wide noindex remains a launch blocker. Give a scoped readiness assessment: blockers found, no blockers found in checked scope, or insufficient evidence. Never claim unconditional launch approval from a sampled local audit.

## Deliverables

Use `seo-audits/<project-slug>-local/<date>-<run>/` to distinguish projects sharing localhost. Produce the normal report, action plan, inventory and findings plus `launch-checklist.md`. Keep `mode: local-project`; add these fields under `scope`:

- `project_root`, `revision`, `working_tree_state`.
- `local_origin`, `intended_public_origin` (null if unknown), `runtime_mode` (development/production-preview/unavailable), `content_source`.
- `startup_command`, `build_result`, `runtime_limitations`, and any `robots_exception` explanation.

Add `source_locations` (array of `{path, line}` with line null if not established), `runtime_mode`, and `launch_stage` (fix-before-launch/verify-release-config/verify-after-deploy) to local findings. Record code and runtime evidence separately in the existing evidence array. All additions are optional outside this mode.

In the launch checklist, give each item a status (pass/fail/pending/not-applicable), evidence, responsible role and verification procedure. Include pre-deployment fixes and pending production checks: public DNS/TLS and preferred-host redirects; CDN/hosting headers and cache behavior; production robots/noindex; emitted public canonicals/hreflang/sitemaps; real CMS content; deployed error responses and representative rendering; search-engine access and actual indexing; analytics instrumentation; and field performance when sufficient data exists. Mark items only as verified in the environment actually tested. Rankings, backlinks and real-user outcomes are not measurable from localhost.
