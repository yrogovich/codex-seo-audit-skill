# Measurement, extraction and validation helpers

The scripts use Python 3.9+ and its standard library. Resolve `scripts/` relative to the installed skill directory, not the audited project. Save output inside the current audit's `evidence/` directory. Commands below assume you are in the skill directory; replace example URLs and output paths with the actual scoped target and audit directory. Never run them against an unrelated example site as an audit target.

## Hosted PageSpeed Insights

```sh
python3 scripts/pagespeed_check.py https://example.com \
  --strategy both \
  --output-dir /absolute/project/seo-audits/example.com/run/evidence/pagespeed-home
```

Default strategy is mobile; `desktop` and `both` are supported. Each strategy requests performance, accessibility, best practices and SEO categories. The runner makes at most one hosted request per strategy, sequentially, with a 120-second timeout and a 32 MiB response cap. Use the execution tool's yielding/polling support for long runs so progress remains visible. It does not crawl links, render locally, or retry automatically. Inspect robots and audit scope first. Hosted PSI sends the supplied URL to Google; use public in-scope pages without secrets in query strings. Local/private URLs are rejected. DNS validation is an initial disclosure guard, not verification of the target's redirect chain or Google's crawl scope.

To measure several important templates in one run, list public URLs one per line (`#` comments and duplicates are ignored) and pass `--urls-file` instead of a URL:

```sh
python3 scripts/pagespeed_check.py --urls-file /absolute/project/seo-audits/example.com/run/evidence/psi-urls.txt \
  --strategy mobile \
  --output-dir /absolute/project/seo-audits/example.com/run/evidence/pagespeed-templates
```

A batch holds at most 20 URLs and runs sequentially, one hosted request per URL and strategy. Every URL is validated before the first request. Each URL gets its own numbered subdirectory with the files described below, and `index.json` lists each URL's status and scores. Choose representative templates rather than every page; a failed URL does not stop the rest, and the exit code is 1 if any measurement failed.

An optional `PAGESPEED_API_KEY` environment variable supplies the key as a request header. Use an existing secret environment; never put key values in prompts, CLI arguments, repository files or reports. Google documents keyless access, but actual access/quota may require a configured key. On quota, access or network failures, keep the failed measurement and continue the audit; do not repeatedly retry.

The output directory must be new. Successful responses are saved as `mobile.raw.json` / `desktop.raw.json`; `summary.json` includes scores, lab metrics, failing audit IDs, environment, timestamps, warnings and separate URL/origin field blocks when supplied. Saved provider/runtime errors remain errors. Exit code 0 means all requested measurements completed, not that the page passed performance checks; 1 means at least one measurement or input failed; 2 means invalid CLI usage. A successful device result remains usable when the other device fails.

Use raw audit details to identify affected resources and substantiate fixes. `failed_audits` lists every audit scoring below 1, so read each entry's `rating` (Lighthouse's published bands: pass 90–100, average 50–89, fail 0–49) before treating it as a defect, and each carries bounded `items`: the top 10 detail rows (URLs, DOM nodes, wasted bytes or milliseconds), text clipped at 300 characters, with `items_total` giving the full count. `diagnostics` keeps the informative audits that checks.md asks for even though Lighthouse does not score them: LCP element and phases, layout-shift elements, third-party cost and server response time. The raw report remains the complete record. Row extraction follows Lighthouse's documented table and list detail shapes and was tested on synthetic fixtures, not live PSI responses; an unrecognized shape yields no items rather than a failure, so read the raw report in that case. Failed Lighthouse audits are diagnostic candidates, not automatically SEO findings. A score of 100 is not proof of indexability or good field Core Web Vitals. A single run is a sample; for noisy or consequential comparisons, repeat in fresh directories and compare like-for-like URLs, devices, Lighthouse versions, throttling and environments.

PSI may omit field data. Keep URL and origin coverage separate; never replace missing URL data silently with origin data. The helper preserves provider field metrics without applying its own unit conversions or CWV pass/fail rules. PSI does not establish a collection window here (`collection_period: null`). Google plans to remove field data from PSI; use the separately available CrUX API, History API, or an authorized export to establish field coverage and dates. Missing LCP/INP/CLS or dates remain unknown. TBT is a lab metric, not measured field INP.

## Local or saved Lighthouse results

Use the project's existing Lighthouse tooling when available. If the CLI and Chrome are already installed, an example is:

```sh
lighthouse http://localhost:3000 --output=json \
  --output-path=/absolute/audit/evidence/lighthouse-mobile.json
python3 scripts/pagespeed_check.py \
  --input /absolute/audit/evidence/lighthouse-mobile.json \
  --output-dir /absolute/audit/evidence/lighthouse-mobile-summary
```

Inspect the installed CLI's `--help` and project instructions before choosing flags or installing tools. Record its device/throttling settings; use separate runs for desktop and mobile. `--input` also accepts saved PSI JSON, performs no network calls, and preserves the imported report. Its strategy comes from the report's `configSettings.formFactor`; `--strategy` controls hosted runs only. Never label an imported report as a new live measurement; preserve its original fetch time and source path. Runtime errors and missing Lighthouse results are not usable measurements.

## Saved HTML extraction

```sh
python3 scripts/parse_html.py /absolute/audit/evidence/home.html \
  --base-url https://example.com/ \
  --output /absolute/audit/evidence/home.extracted.json
```

Supply the original final response URL for relative-link resolution. The first HTML base href is respected and preserved; resolved URLs are evidence only and are never fetched. Specify `--encoding` when the saved response is not UTF-8. Output includes all titles, meta entries, canonicals, hreflang, H1–H6, anchors, image attributes, parsed JSON-LD or syntax errors, visible-text size, a rendering hint, and a SHA-256 of the original file. Missing image alt is null; intentionally empty alt stays empty. Duplicate metadata remains visible, but SVG `<title>` elements are accessibility labels and are not reported as document titles.

Each link keeps its raw attributes (including `rel`) and gains `text` (text content), `image_alts` (alt of images inside the link; null means the image has no alt) and `anchor_text` (the text, or the images' alt text when the link has none). `visible_text` counts characters and words of body text excluding head, script, style, noscript, template and SVG content. `rendering_hint.possible_client_rendered` is true only when a client-rendering shell marker (such as `id="root"`, `__next`, `__nuxt`, `ng-version` or a noscript JavaScript notice) appears with under 400 visible characters. These are diagnostic cues from the original HTML, not rendered-DOM measurements, ranking thresholds or findings; render the page in a browser before concluding that content depends on JavaScript. The output file must be new; parent directories must already exist.

This is an extraction helper, not a crawler, HTML validator, full browser parser or schema validator. Preserve the original file, fetch time, response status and headers separately. If you supply rendered HTML, label that evidence rendered; it does not establish what the server returned. Malformed HTML, unfinished tags, JS-generated data and complex browser recovery need browser verification. Do not treat extracted destination URLs as checked links.

## Audit validation

```sh
python3 scripts/validate_audit.py /absolute/project/seo-audits/example.com/2026-11-09-1
```

Run it once the deliverables are written, fix every error, and re-run. It reads files only: nothing is fetched, modified or executed. It checks:

- the required files exist and are non-empty (`launch-checklist.md` too for `local-project`);
- `findings.json` against the contract in [reporting.md](reporting.md): top-level keys, enumerations, counts and count basis, evidence records, impact and effort estimates (including that unknown effort explains why), dependencies (unknown IDs and cycles), source records, and the local-project fields;
- that evidence references resolve to files under the audit directory or the workspace above `seo-audits/` (use `--root` for another source tree), or are named URLs;
- that `url-inventory.csv` is readable, has the required columns, no duplicate URLs and valid statuses;
- that every finding ID appears in `report.md` (and in `action-plan.md` unless it is Info);
- coverage records for every core area in broad audits, with limitations named where status is partial or unknown;
- patterns of accidentally saved secrets (API keys, bearer tokens, private keys, cookie headers, the value of `PAGESPEED_API_KEY`), reported by file and line without echoing the value.

Warnings flag likely problems that need a judgment call, such as an unverified Critical severity, a sampled count described as site-wide, a promised percentage traffic gain, or a finding URL missing from the inventory. `--strict` turns warnings into failures; `--json` prints machine-readable results. Exit code 0 means no errors, 1 means errors (or warnings with `--strict`), and 2 means invalid usage. A pass establishes structure and internal consistency only. It does not evaluate whether evidence supports a conclusion, whether report text agrees with the JSON beyond finding IDs, or whether an estimate is sensible, so the final verification in reporting.md still applies. Do not weaken findings or edit the validator to silence a check that points at a real gap.
