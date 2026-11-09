# Measurement and extraction helpers

Both scripts use Python 3.9+ and its standard library. Resolve `scripts/` relative to the installed skill directory, not the audited project. Save output inside the current audit's `evidence/` directory. Commands below assume you are in the skill directory; replace example URLs and output paths with the actual scoped target and audit directory. Never run them against an unrelated example site as an audit target.

## Hosted PageSpeed Insights

```sh
python3 scripts/pagespeed_check.py https://example.com \
  --strategy both \
  --output-dir /absolute/project/seo-audits/example.com/run/evidence/pagespeed-home
```

Default strategy is mobile; `desktop` and `both` are supported. Each strategy requests performance, accessibility, best practices and SEO categories. The runner makes at most one hosted request per strategy, sequentially, with a 120-second timeout and a 32 MiB response cap. Use the execution tool's yielding/polling support for long runs so progress remains visible. It does not crawl links, render locally, or retry automatically. Inspect robots and audit scope first. Hosted PSI sends the supplied URL to Google; use public in-scope pages without secrets in query strings. Local/private URLs are rejected. DNS validation is an initial disclosure guard, not verification of the target's redirect chain or Google's crawl scope.

An optional `PAGESPEED_API_KEY` environment variable supplies the key as a request header. Use an existing secret environment; never put key values in prompts, CLI arguments, repository files or reports. Google documents keyless access, but actual access/quota may require a configured key. On quota, access or network failures, keep the failed measurement and continue the audit; do not repeatedly retry.

The output directory must be new. Successful responses are saved as `mobile.raw.json` / `desktop.raw.json`; `summary.json` includes scores, lab metrics, failing audit IDs, environment, timestamps, warnings and separate URL/origin field blocks when supplied. Saved provider/runtime errors remain errors. Exit code 0 means all requested measurements completed, not that the page passed performance checks; 1 means at least one measurement or input failed; 2 means invalid CLI usage. A successful device result remains usable when the other device fails.

Use raw audit details to identify affected resources and substantiate fixes. Failed Lighthouse audits are diagnostic candidates, not automatically SEO findings. A score of 100 is not proof of indexability or good field Core Web Vitals. A single run is a sample; for noisy or consequential comparisons, repeat in fresh directories and compare like-for-like URLs, devices, Lighthouse versions, throttling and environments.

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

Supply the original final response URL for relative-link resolution. The first HTML base href is respected and preserved; resolved URLs are evidence only and are never fetched. Specify `--encoding` when the saved response is not UTF-8. Output includes all titles, meta entries, canonicals, hreflang, H1–H6, anchors, image attributes, parsed JSON-LD or syntax errors, and a SHA-256 of the original file. Missing image alt is null; intentionally empty alt stays empty. Duplicate metadata remains visible. The output file must be new; parent directories must already exist.

This is an extraction helper, not a crawler, HTML validator, full browser parser or schema validator. Preserve the original file, fetch time, response status and headers separately. If you supply rendered HTML, label that evidence rendered; it does not establish what the server returned. Malformed HTML, unfinished tags, JS-generated data and complex browser recovery need browser verification. Do not treat extracted destination URLs as checked links.
