# Local project audit before deployment

Use this mode for a codebase and the copy of it running on this machine. Find launch blockers and fixable SEO problems, with file and line evidence plus real responses and rendered pages. An audit does not allow editing source or deploying.

## Set up

1. **Read the project:** instructions, git status, package files, run and build commands, routing, deployment config. In a monorepo, find the web app. Keep existing changes. Record the commit and whether the tree is dirty.
2. **Find the server.** Reuse one you were given or one already running for this app. Otherwise find the documented command and port. If the app is unclear, ask and keep reading source meanwhile. Do not assume port 3000. Do not kill another process to free a port.
3. **Start and build normally** when the project supports it. Read the scripts and build hooks first. Never run deploys, publishing, migrations, production writes or destructive cleanup. Use existing dependencies or the normal install steps where allowed. Never reset configuration to make the audit run.
4. **Prefer production behavior:** the documented production build and preview. If only a dev server works, continue and label it development mode. Do not guess production flags or rewrite env files. A build may fetch CMS data, so find out whether it is local, mocked, staging or production, without printing secrets. Missing credentials or content are coverage limits.
5. **Record the setup:** project root, commit, local origin with port, start command, development or production preview, intended public origin if known, content source, and whether your browser can reach it. A browser running elsewhere may not reach this localhost. Use a local tool or report runtime coverage as unavailable. Do not open a public tunnel just to test.

Stop only the processes you started, unless the user wants the preview left running. Leave existing servers alone. Normal build output is fine. Report unexpected changes to tracked files, and do not revert the user's work.

## Inspect the source

Find how this framework builds routes, layouts, the document head and metadata, using the installed version. Follow imports and data sources. Do not guess output from file names. Look at:

- title and description defaults and overrides, canonical and base URL logic, robots directives, language alternates, social metadata, and what happens when a CMS field is empty;
- what renders on the server, at build time or in the browser (content, navigation, links, JSON-LD), plus caching and revalidation that can leave metadata stale or empty;
- robots and sitemap generators or static files: which URLs, indexes, `lastmod`, pagination, parameters, dynamic routes, localization;
- redirects and rewrites, 404 handling, trailing slashes, base path, route headers, and hosting rules the local server does not run;
- templates, image components, navigation and breadcrumbs, structured-data builders and escaping, and duplicate metadata from layout inheritance.

Combine source routes with generated route lists, local links, sitemaps and fixtures. A dynamic route does not prove every slug exists. Test valid and missing slugs, translated pages, pagination and filters. Do not submit forms or call action endpoints.

## Check the running site

Run the core checks on the local origin. Save status, headers and original HTML, then inspect rendered pages on mobile and desktop for each important page type. Compare what the source intends with what is emitted. Load deep links directly, because in-app navigation can hide server failures. Check missing pages, redirects and lazy content.

Public URLs in generated sitemaps, canonicals and hreflang: keep the emitted URL as evidence, then test its path and query on the local origin if that makes sense. Do not rewrite saved files or crawl the production host. A production canonical emitted locally can be correct. A localhost canonical is a release defect only if production config or build evidence shows it will leak. Otherwise it is a release check.

With the scripts, pass the exact local origin as `--allow-local http://localhost:3000` to [probe.py](../scripts/probe.py) and [crawl.py](../scripts/crawl.py) (see [scripts.md](scripts.md)). Adjacent ports, other private addresses and cloud-metadata addresses stay blocked.

**Robots exception.** An explicit local-project audit may inspect the given app even if its development robots.txt disallows crawling. `crawl.py --ignore-robots-for-local` applies this to that origin only and records `robots_exception` in `summary.json`. Copy it into the audit scope. Keep all other limits and do not change robots.txt. It does not cover public or staging hosts, other ports or addresses, or redirects that leave the local scope. Leave intentional noindex and authentication in place, and check that environment settings give the intended release behavior. Localhost not being indexed is not a defect.

Local speed is lab evidence only. Prefer a production preview, and label dev-server overhead, local assets, mocked data, warm caches and no CDN. Report bottlenecks, but do not project real-user Core Web Vitals. If a tool cannot run, continue with the code and HTTP audit and mark that area unknown. Use local Lighthouse when you can, then summarize its JSON with [pagespeed_check.py](../scripts/pagespeed_check.py) `--input`. Hosted PageSpeed cannot reach localhost, and you must not publish or tunnel the project to get a score.

## Findings and launch decision

Link each local finding to its route or URL and, where possible, the source file and verified line. Include the run mode, response or DOM evidence, why it matters in production, the exact change and a retest. If you are unsure who owns the code, say so. Code you read is not behavior you observed.

Sort outcomes into three groups:

- **Fix before launch:** confirmed defects in source or runtime that affect intended public content.
- **Verify release configuration:** behavior that depends on the environment, with an unknown release value (robots, public base URL, CMS settings).
- **Verify after deployment:** things that only exist in production, and production measurements.

Use the normal severity and evidence fields. A development-only restriction is never Critical. A demonstrated production-wide noindex is still a launch blocker. Give a scoped readiness statement: blockers found, no blockers found in the checked scope, or not enough evidence. Never give unconditional launch approval from a sampled local audit.

## Deliverables

Use `seo-audits/<project-slug>-local/<date>-<run>/` so projects sharing localhost do not mix. Create the usual files plus `launch-checklist.md`. Keep `mode: local-project` and add under `scope`:

- `project_root`, `revision`, `working_tree_state`;
- `local_origin`, `intended_public_origin` (null if unknown), `runtime_mode` (development, production-preview or unavailable), `content_source`;
- `startup_command`, `build_result`, `runtime_limitations`, and an explanation of any `robots_exception`.

On local findings add `source_locations` (`[{path, line}]`, line null if unknown), `runtime_mode`, and `launch_stage` (fix-before-launch, verify-release-config or verify-after-deploy). Keep code evidence and runtime evidence as separate entries. These fields are optional outside this mode.

In the launch checklist, give each item a status (pass, fail, pending or not-applicable), evidence and how to verify it. Include fixes to make now and checks still pending in production: public DNS, TLS and host redirects; CDN headers and caching; production robots and noindex; public canonicals, hreflang and sitemaps; real CMS content; deployed error pages and rendering; search-engine access and real indexing; analytics; and field performance once there is data. Mark an item verified only in the environment you tested. Rankings, backlinks and real-user results cannot be measured from localhost.
