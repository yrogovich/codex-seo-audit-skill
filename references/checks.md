# Core audit checks

For each area, record what you checked, the evidence, the findings, and what you could not test. A checklist item is not a finding until you have verified it in context.

## 1. Crawling and index eligibility

Look at robots.txt rules, HTTP status and redirects, the robots meta tag and `X-Robots-Tag` header, canonical targets and conflicts (the "preferred URL" tag), sitemap accuracy, whether pages are reachable through normal links, and error pages and soft 404s (a "not found" page that returns 200). Confirm an exclusion is not intentional before calling it a defect.

- `Disallow` stops crawling. It does not guarantee a page leaves search results. A crawler that cannot fetch a page cannot see its `noindex`.
- A canonical is a hint, not a command. The HTML canonical, the HTTP `Link` canonical, the sitemap, redirects and internal links can all point at a preferred URL, so tell them apart. Check the target's status and purpose before suggesting consolidation.

Also test http/https and www consistency, important moved URLs, redirect chains and loops, redirects to the homepage that should not happen, and what a missing page returns. Report repeated server errors with timing and scope. A missing robots.txt or sitemap is not a blocker if pages are still easy to find.

## 2. Rendering, mobile and page experience

Compare the source HTML with the rendered page (content, navigation, metadata, structured data). Check that links exist without clicking, pagination uses real URLs, and lazy content appears. Find JavaScript or resource failures and content that changes after hydration. A framework choice alone does not prove bad SEO.

Look at mobile readability, overflow, navigation, pop-ups that cover content, and access to the main content. Keep accessibility advice apart from proven search problems. Observe forms, checkout and conversions without submitting them.

## 3. Site structure and internal links

Review the hierarchy against the important topics, links inside content versus navigation-only links, anchor text, broken links, links to redirecting URLs, breadcrumbs and pagination. Check candidate orphan pages against a crawl that is complete enough plus the sitemap or an export. Report inlinks and depth only for the graph you saw.

Judge filter and parameter URLs by whether they are useful and meant to be indexed. Do not hand out blanket noindex, canonical or robots rules: they solve different problems and can conflict. Do not canonicalize different paginated pages to page one by default.

## 4. On-page content

Compare the title, main heading, description, body, URL and the intent the page should serve. Find missing, generic or duplicated values across similar pages. Check heading structure, link text and snippet accuracy. Length is a display hint. Several H1s or a long title are not automatically critical.

Ask whether the page answers the search and helps the next step. Look for original evidence, authorship where it matters, real expertise, sources for important claims, meaningful dates, business identity and trust information. Look harder at high-stakes topics. Do not invent a numeric E-E-A-T score.

Judge thin content by what is missing for the user, not word count. Similar keywords do not prove cannibalization: confirm the intent overlaps and use performance data if you have it. When you suggest merging pages, keep the useful ones and list the destination, intent, internal links and redirects. For mass-produced pages, point to concrete examples of missing value. Do not guess a percentage of AI-written text.

## 5. Structured data

Find JSON-LD, microdata and RDFa on representative page types. Check syntax, entity IDs, types and properties, references, and that the markup matches what is visible, including prices, availability, dates and reviews. Keep these apart: parses correctly, valid Schema.org, currently eligible for Google, and actually shown as a rich result.

Read the current official docs before recommending a type or promising eligibility, especially for FAQ, HowTo and other features that change. Record the validator and its result. Do not call markup validated because you saw a script tag. Suggest markup only with verified facts, with no invented reviews, people, addresses, offers or ratings.

## 6. Performance and Core Web Vitals

Full audit: try mobile PageSpeed on important page types, and desktop when it matters ([scripts.md](scripts.md)). Focused audit: only the requested pages. Local project: local Lighthouse JSON, not hosted PageSpeed. If a measurement is blocked, record it as unknown and carry on.

Use real-user (field) data when you have it. Note URL versus origin, device, period and percentile. Good thresholds at the 75th percentile: LCP up to 2.5 s, INP up to 200 ms, CLS up to 0.1 (check web.dev at audit time). No field data is unknown, not a pass.

Keep field data apart from Lighthouse lab data. One lab run is not representative, and TBT is not field INP. Find the real LCP element, layout-shift causes, image and font delivery, main-thread work, third-party cost and caching. Do not tell people to preload every image or lazy-load the LCP image.

## 7. Images and media

Check meaningful versus decorative images, missing `alt` versus intentionally empty `alt`, dimensions, responsive sources, loading behavior, real file size and delivery. For video, check discoverability, captions and thumbnails. Do not work out file sizes from CSS dimensions, and do not stuff keywords into `alt`. Tie compression or format advice to measured files.

## 8. Search visibility, authority and AI search

Use [search-data.md](search-data.md) for queries, performance, competitors and links. Cover this area even without data, and name the limit exactly.

Look at clear entities, helpful self-contained explanations, source attribution, machine-readable text and search-crawler access. Keep search retrieval apart from model training and user-triggered fetchers, and check the vendor's docs before interpreting a crawler token. Do not change crawler rules during an audit. Access or markup does not guarantee inclusion in an AI answer. Treat `llms.txt` and other new conventions as optional experiments, never required fixes or proven ranking factors.
