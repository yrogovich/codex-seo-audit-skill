# Helper scripts

Optional Python scripts (Python 3.9+, standard library only). They collect evidence and list leads. They never decide severity or intent.

| Script | Use it to |
| --- | --- |
| [quick_audit.py](#quick-audit) | Fastest way in: probe, crawl, analyze and score in one command |
| [probe.py](#site-probe) | Check one URL and its site: redirects, robots.txt, sitemaps, variants |
| [crawl.py](#crawl-and-analysis) | Crawl within limits and build the URL inventory |
| [analyze_crawl.py](#crawl-and-analysis) | List likely problems from a crawl |
| [pagespeed_check.py](#pagespeed-insights) | Run PageSpeed Insights, or read a saved Lighthouse report |
| [crux_check.py](#real-user-speed-crux) | Get real-user Core Web Vitals with dates |
| [parse_html.py](#saved-html) | Extract SEO data from saved HTML |
| [score_audit.py](#checklist-score-only-when-asked) | Make a 0-100 checklist score (only when asked) |
| [render_report.py](#build-the-report) | Build `action-plan.md` and `report.md` from `findings.json` |
| [validate_audit.py](#check-the-audit-folder) | Check a finished audit folder |

Rules for all of them: run them from the installed skill folder (not the audited project). Save output under the audit's `evidence/` folder. Output folders and files must be new, and are never overwritten. Replace the example URLs and paths with your real ones. Do not run them against an unrelated example site.

## Quick audit

```sh
python3 scripts/quick_audit.py https://example.com
```

Runs probe, crawl (50 pages), analysis and score, then prints a score card: the 0-100 score, Technical and Content scores, blockers and the top fixes, each marked as a Google requirement, Google guidance or our own check. It writes `seo-audits/<host>/<date>-quick/` with `quick-report.md`, `score.json`, `probe/` and `crawl/` (the same files the manual steps make). Usually one to two minutes.

- Limits: `--max-pages` (50), `--max-seconds` (240), `--delay` (1 s per request, minimum 0.2). `--output-dir` sets a new folder.
- `--pagespeed` and `--crux` are opt-in because they send the URL to Google (CrUX needs `CRUX_API_KEY`). Without a key they are skipped with a note. They are always skipped for local projects.
- Local project: `--allow-local http://localhost:3000`, plus `--ignore-robots-for-local` for the robots exception. `--baseline old/score.json` compares with an earlier run.
- If robots.txt cannot be read or no pages could be crawled, the score uses the site checks only and says so. Exit code 0 means a score was written, 1 means the site could not be fetched.
- It is a scan, not a full audit: raw HTML only, no `findings.json`, no per-finding evidence, no content-quality judgment. Use the full audit for the fix plan.

## Site probe

```sh
python3 scripts/probe.py https://example.com/ --output-dir /abs/seo-audits/example.com/run/evidence/probe
```

Run this first. About 15 read-only requests, one per second per host. It writes `probe.json` plus the raw page, robots.txt and sitemaps, and records:

- the main fetch with every redirect hop and all headers (cookies saved as names only);
- robots.txt: 2xx is parsed, other 4xx means no restrictions, and 5xx, 429 or a network failure means "unreachable" (a polite crawler must not treat that as permission);
- robots matching per crawler token for the target path and `/`;
- sitemaps, declared or at the usual places (DOCTYPE and entity declarations are refused);
- `http`, `https` and `www` variants, and what a missing page returns.

`observations` are leads, such as `robots.blocks_target`, `sitemap.problem`, `variants.divergent_final_urls` and `missing_page.soft_404_candidate`. Crawler tokens are only for matching: what a token controls must be checked in the vendor's docs.

Targets must resolve to public addresses. The connection is locked to the checked address, so a redirect or DNS change cannot reach a private one. For a local project, `--allow-local http://localhost:3000` allows exactly that origin (other ports, other private addresses and cloud-metadata addresses stay blocked). Options: `--no-site-checks`, `--user-agent`, `--agent`. Exit 1 means the main fetch failed.

## Crawl and analysis

```sh
python3 scripts/crawl.py https://example.com/ \
  --output-dir /abs/seo-audits/example.com/run/evidence/crawl \
  --inventory /abs/seo-audits/example.com/run/url-inventory.csv
python3 scripts/analyze_crawl.py /abs/seo-audits/example.com/run/evidence/crawl \
  --inventory /abs/seo-audits/example.com/run/url-inventory.csv \
  --output /abs/seo-audits/example.com/run/evidence/crawl/analysis.json
```

**crawl.py** enforces the limits in [collection.md](collection.md): 100 HTML pages, 300 requests, 900 seconds, one request per second per host (`--delay`, minimum 0.2). It obeys robots.txt and `Crawl-delay`, never submits forms, skips asset files and cart/login URLs, and caps query variants at 20 per path. It stops if robots.txt is unreachable, or after five 5xx, 403/429 or network failures in a row. A 429 is retried at most twice after `Retry-After`. Each redirect hop is its own inventory row. Scope is the start host plus the host it redirects to; add `--allow-host` or `--seed` on purpose. External links are logged, never fetched. It reads raw HTML and never runs JavaScript.

For a local project use `--allow-local http://localhost:3000`. `--ignore-robots-for-local` applies the local robots exception to that origin only and records it as `robots_exception` in `summary.json`. Copy that into the report scope.

Output: `url-inventory.csv`, `crawl.jsonl`, `links.csv`, `pages/*.html`, `robots-*.txt`, sitemap files, `summary.json` (`stop_reason`, counts, `complete_within_scope`). In the inventory, `template` is a hint to refine, and `observed_indexability` lists blocking signals seen (it never says a page is indexed).

**analyze_crawl.py** writes `analysis.json`: likely problems with affected URLs, a count, a denominator and a `basis` saying whether the crawl was complete or partial. `checks_run` lists every check, including those with zero results, so "nothing found" differs from "not run". Candidates have no severity. Check each in context, decide whether it is intentional, and call a partial crawl a sample ("sampled: 100 of 340 discovered"), never site-wide.

## PageSpeed Insights

```sh
python3 scripts/pagespeed_check.py https://example.com --strategy both \
  --output-dir /abs/seo-audits/example.com/run/evidence/pagespeed-home
```

- Strategy: `mobile` (default), `desktop` or `both`. One request per strategy, in order, 120-second timeout, no retries.
- It sends the URL to Google. Use public, in-scope pages with no secrets in the query. Local and private URLs are rejected.
- `PAGESPEED_API_KEY` (environment variable) is sent as a header. Never put it in prompts, arguments, files or reports. On quota or network failure, keep the failed result and move on.
- Output: `mobile.raw.json`, `desktop.raw.json`, `summary.json`. Exit 0 means the runs finished (not that the page passed), 1 means a run or input failed, 2 means bad usage.
- Many pages: `--urls-file urls.txt` (one URL per line, max 20, run in order). Each URL gets its own folder plus an `index.json`. Pick representative page types.

Reading `summary.json`:
- `failed_audits` lists every audit scoring below 1, so check its `rating` (pass 90-100, average 50-89, fail 0-49) before calling it a defect. `items` holds up to 10 detail rows; `items_total` is the full count.
- `diagnostics` has the LCP element, layout-shift elements, third-party cost and server response time.
- The raw file is the full record. Row extraction was tested on fixtures, not live responses.
- A failed audit is a lead, not a finding. One run is a sample. Lab TBT is not field INP.
- PageSpeed may omit field data and has no collection dates. Keep URL and origin separate. Use CrUX for dates.

**Local or saved Lighthouse:**

```sh
lighthouse http://localhost:3000 --output=json --output-path=/abs/audit/evidence/lighthouse-mobile.json
python3 scripts/pagespeed_check.py --input /abs/audit/evidence/lighthouse-mobile.json \
  --output-dir /abs/audit/evidence/lighthouse-mobile-summary
```

Check `--help` and the project docs before choosing flags. Run mobile and desktop separately and note the throttling. `--input` makes no network calls and also reads saved PageSpeed JSON. Never present an imported report as a new live measurement.

## Real-user speed (CrUX)

```sh
CRUX_API_KEY=... python3 scripts/crux_check.py https://example.com/page --also-origin \
  --form-factor phone --history --output-dir /abs/seo-audits/example.com/run/evidence/crux
```

- Key: `CRUX_API_KEY`, or `PAGESPEED_API_KEY` if that key has the Chrome UX Report API enabled. It is sent as a header and never saved.
- URL and origin are separate results. Neither replaces the other.
- The summary has p75 per metric with a rating (LCP 2.5 s, INP 200 ms, CLS 0.1; check at audit time), the collection period, and `passed`, `failed` or `incomplete` overall.
- No data is `no-data`: unknown, never a pass, and it does not fail the run. Parsing was tested on fixtures, not live responses, so check your first live result against the raw file.

## Saved HTML

```sh
python3 scripts/parse_html.py /abs/audit/evidence/home.html \
  --base-url https://example.com/ --output /abs/audit/evidence/home.extracted.json
```

- Give the original final URL so relative links resolve. Use `--encoding` if the file is not UTF-8.
- Output: titles, meta tags, canonicals, hreflang, headings, links, image attributes, JSON-LD (or its syntax errors), visible-text size, a rendering hint and the file's SHA-256. Missing `alt` is null, empty `alt` stays empty, and SVG `<title>` is not a page title.
- Each link has `text`, `image_alts` and `anchor_text` (the text, or the images' `alt` if there is none).
- `rendering_hint.possible_client_rendered` is true only with a client-rendering marker (like `id="root"` or `__next`) and under 400 visible characters. It is a hint. Render the page in a browser before saying content needs JavaScript.
- It is not a crawler or validator. Keep the original file, status and headers separately. Label rendered HTML as rendered. Extracted URLs are not checked links.

## Checklist score (only when asked)

```sh
python3 scripts/score_audit.py --analysis .../analysis.json --probe .../probe.json \
  --psi .../summary.json --crux .../summary.json --output /abs/audit/score.json
```

All inputs are optional. It prints a short summary and writes `score.json`: the 0-100 score, how much of the checklist could be checked, a Technical and a Content score, a score per area, blockers, and a "fix first" list that says what Google says about each check (requirement, guidance, or our own check). Checks that could not run are left out, never counted as passes. It is not a Google ranking predictor. Details: [scoring.md](scoring.md).

## Build the report

```sh
python3 scripts/render_report.py /abs/seo-audits/example.com/2026-11-09-1 --narrative narrative.md
```

`findings.json` is the source of truth. This writes `action-plan.md` (two tables, Technical and Content, most severe first) and, with `--narrative`, `report.md`: your short summary and scope, then the score (if `score.json` is in the folder), findings split into Technical and Content, and coverage, limitations and sources. It refuses a `findings.json` that breaks the contract and will not overwrite files without `--force`. Change `findings.json` and re-render. Do not edit the generated files.

## Check the audit folder

```sh
python3 scripts/validate_audit.py /abs/seo-audits/example.com/2026-11-09-1
```

Reads files only. Fix every error and run it again. It checks:

- required files exist (and `launch-checklist.md` for `local-project`);
- `findings.json` against [reporting.md](reporting.md);
- evidence references resolve (`--root` adds another source folder);
- `url-inventory.csv` is readable, with the right columns and no duplicate URLs;
- every finding ID is in `report.md` (and `action-plan.md` unless Info);
- every core area has a coverage record;
- `score.json`, if present, adds up and `report.md` shows the checked percentage;
- saved secrets (keys, tokens, cookie headers), reported by file and line without printing the value.

Warnings need your judgment (an unverified Critical, a sampled count called site-wide, a promised traffic gain, a finding URL missing from the inventory). `--strict` fails on warnings, `--json` prints machine-readable output. Exit 0 means no errors, 1 means errors, 2 means bad usage. A pass shows structure only. It does not judge whether the evidence supports a conclusion. Do not weaken findings or edit the validator to silence a real gap.
