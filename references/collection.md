# Collection and coverage

For a local project, read [local-project.md](local-project.md) first.

## Pick a method for the tools you have

| What you have | What to do | Say this about the limits |
| --- | --- | --- |
| Browser and HTTP fetch or crawler | Save responses. Inspect rendered pages on mobile and desktop | A browser render is not proof of how Google renders or indexes |
| HTTP fetch or crawler only | Inspect headers and original HTML | Rendered content and interactions are unknown |
| Browser only | Inspect visible content and the DOM. Get response details only if the tool supports it | The DOM can differ from the original HTML. Do not invent headers or status codes |
| Crawl export or saved HTML | Analyze the data, with its timestamps | Nothing about the live site now |
| Repository only | Trace metadata, routes, rendering, CMS flow, redirects, robots and sitemap generation | Deployment, server responses and live CMS content are unverified |

Search snippets and extracted text help you find pages, but they are not raw HTML evidence. A tool that drops the `<head>` does not prove metadata is missing. If a site needs JavaScript, look at it in a browser before saying it is empty. A screenshot can back up a visual finding. It cannot prove canonical or HTTP behavior.

## Crawl limits

- Record the start URL, final host, protocols, allowed hosts, scope, time, user agent, device, tool and version, and budget. Do not drift to sibling domains.
- Fetch `/robots.txt` and read the groups for the relevant crawlers and the declared sitemaps. Follow sitemap indexes with a visited set and a depth limit. Check that a "sitemap" is real XML, not an HTML error page. Try the usual sitemap locations only if none is declared.
- Find URLs from navigation, sitemaps, internal links and allowed exports. Record how each was found, so a sitemap URL is not mistaken for a linked page.
- Default budget for a full audit: 100 HTML pages, one request per second per host, at most two at a time, 30 seconds per request, at most five redirect hops. Go lower if the server struggles. Count redirects and side requests. These are working defaults, not SEO standards.
- Obey robots.txt. If you cannot read it, stop that part and note it. A missing robots.txt is not a defect. On a 429, wait for `Retry-After` and retry at most twice. Stop on repeated 5xx, bot challenges or steady refusals, and keep what you have.
- Set hard limits for URLs, response size, sitemap size and time, and report which one stopped the crawl. Do not expand filter, query or calendar URLs without a limit. Keep query parameters that change content. Strip `#fragments` when fetching, but keep the original links as evidence.
- Use only normal, read-only, public pages in scope. Skip logout, cart changes, forms and other action URLs. Do not bypass logins or bot checks. Check redirect targets, and never follow a public URL to a private or local address. Inspect staging or logged-in areas only if explicitly in scope.

If Python 3.9+ and network access are available, prefer the bundled scripts ([scripts.md](scripts.md)): [probe.py](../scripts/probe.py) for redirects, headers, robots.txt, sitemaps and variants; [crawl.py](../scripts/crawl.py) for the bounded crawl (it enforces these limits and writes the inventory); [analyze_crawl.py](../scripts/analyze_crawl.py) for candidate issues. Their output is evidence and leads. An area you did not fetch or render is still unknown. Without the scripts, use the same limits with the tools you have.

## Choose representative pages

List page types and languages before you spend the budget. Include the homepage; key service, category and product pages; content lists and detail pages; contact, about and trust pages; conversion entry points; and, when relevant, pagination, filters, translations and slow pages. Render at least one page per important type, plus odd ones. On a small site, inspect every eligible page you find within budget.

Write down why you sampled what you did. Check several examples before calling a pattern template-wide. On a large site, say "sampled full-scope audit: N fetched out of M discovered". Discovered is not the same as existing. In a partial crawl, link depth is an upper bound, and a page with no inlinks is not proven an orphan.

## Evidence to keep

For saved HTML, [parse_html.py](../scripts/parse_html.py) extracts metadata, headings, links, images and JSON-LD without fetching or running anything. Keep the original response and headers separately.

For each URL, record what you can: requested and final URL, how it was found, page type, fetch time, method, status and redirects, content type, robots rules, `X-Robots-Tag`, canonical, language and hreflang, title, description, headings, internal links, image attributes, structured data, and a pointer to the evidence. Use null or "unknown" for what you could not get.

For rendering comparisons, compare the original and rendered title, canonical, robots, content and links. Note consent or login state, the mobile viewport, and console errors that explain missing content. Content that only appears in a browser is a rendering dependency, not automatically an indexing failure.

Keep short, relevant excerpts with source URLs and timestamps. Remove tokens, cookies, personal analytics data and secrets from saved files. Never create files for evidence you could not collect.
