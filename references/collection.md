# Collection and coverage

For local pre-deployment work, apply [local-project.md](local-project.md) first; it defines local origin mapping, intentional robots exclusions, and production-preview handling.

## Choose a practical inspection mode

| Available evidence | Method | Limits to disclose |
| --- | --- | --- |
| Browser + HTTP fetch/crawler | Save responses and inspect rendered templates, mobile and desktop | Browser rendering is not proof of Google's rendering/indexing |
| HTTP fetch/crawler only | Inspect response headers and original HTML | Rendered content, interactions, and visual behavior unknown |
| Browser only | Inspect visible content and DOM; collect response details only where supported | DOM may differ from original HTML; don't invent headers/status |
| Crawl export or saved HTML | Analyze supplied dataset and its timestamps | No claim of current live behavior |
| Repository only | Trace metadata, routes, SSR, CMS content flow, redirects, robots and sitemap generation | Deployment, server responses and live CMS values unverified |

Search-result snippets and extracted web text are discovery aids, not raw HTML evidence. A tool omitting the `<head>` does not establish missing metadata. If a site requires JavaScript, inspect it in a browser before concluding it is empty. Save screenshots when they substantiate a visual finding; screenshots alone cannot prove canonical or HTTP behavior.

## Discovery and crawl limits

- Record starting URL, final host, protocols, allowed hosts/subdomains, requested scope, time, user agent, viewport/device, tool/version, and budget. Do not silently expand to sibling domains.
- Retrieve `/robots.txt`; inspect applicable agent groups and declared sitemaps. Follow sitemap indexes with a visited set and bounded recursion; validate actual XML instead of accepting an HTML error page as a sitemap. Try conventional sitemap locations only when discovery fails.
- Discover URLs from navigation, sitemaps, internal links, and authorized exports. Preserve discovery sources so a sitemap URL is not mistaken for an internally linked page.
- For an unspecified full audit, use an initial budget of 100 HTML pages, one request per second per host, at most two concurrent requests, a 30-second per-request timeout, and at most five redirect hops. Adapt down to server limits. Count redirects and auxiliary requests in request totals. These are operational defaults, not SEO standards.
- Inspect robots before bulk crawling and honor exclusions. Stop the affected branch if robots cannot be reliably retrieved or parsed; record the limitation. Missing robots is not by itself an SEO defect. For 429, honor Retry-After and retry at most twice; reduce concurrency. Stop on repeated 5xx, access challenges, or persistent denial; retain partial results.
- Set finite URL, response-size, sitemap, and elapsed-time budgets in the chosen crawler; report which cap stopped it. Never expand faceted/query/calendar spaces without bounds. Keep meaningful query parameters; do not normalize distinct content into one page. Strip fragments for HTTP fetch deduplication but preserve original links as evidence.
- Use only ordinary read-only public resources in the target scope. Skip logout, cart mutations, forms, and other action URLs. Do not bypass authentication or bot challenges. Validate redirect destinations and do not follow public targets into private/local network addresses. Local or authenticated staging is inspected only when explicitly in scope.

## Select representative pages

Inventory templates and languages before spending the budget. Include the homepage, key service/category/product pages, content listings and detail pages, contact/about/trust pages, and important conversion entry points. Include pagination, filtered variants, translations, and poor-performing URLs when relevant. Render at least one representative per important template, plus anomalies. For small sites inspect every discovered eligible page within the budget.

Record the sampling rationale. Expand suspicious patterns to several instances before describing them as template-wide. On a large site, state “sampled full-scope audit: N fetched out of M discovered” with the known denominator. Discovered does not mean total existing. Sampled graph distances are upper bounds on shortest crawl depth; absent inlinks in a partial crawl do not prove an orphan.

## Evidence to preserve

For each URL: requested/final URL, discovery source, template, fetch time, method, status and redirect chain if available, content type, robots rules, X-Robots-Tag, canonical, language/hreflang, title, description, headings, internal links, relevant image attributes, structured data, and an evidence reference. Use null/unknown for unavailable fields.

For rendering comparisons: original vs rendered title, canonical, robots, main content and links; consent/auth state; mobile viewport; console/resource errors relevant to missing content; screenshot or DOM excerpt where useful. Browser-only content is a rendering dependency, not automatically an indexing failure.

Keep narrowly relevant response/DOM excerpts and source URLs. Remove tokens, cookies, personal analytics data, and secrets from saved artifacts. Preserve timestamps and dataset periods. Do not fabricate files for unavailable evidence.
