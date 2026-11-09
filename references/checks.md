# Core audit checks

For every area, record checked scope, evidence, findings, and untested questions. A checklist item is not a finding until verified in context.

## 1. Crawlability and index eligibility

Inspect robots rules for relevant agents and important assets; HTTP status, redirects, HTML robots and X-Robots-Tag; canonical destinations and conflicts; sitemap membership and accuracy; indexable navigation paths; error and soft-404 behavior. Confirm intentional exclusions before calling them defects.

Robots disallow controls crawling, not guaranteed removal from search. A crawler prevented from fetching cannot reliably discover a page's noindex. Canonicals are signals, not guaranteed selections. Distinguish HTML canonical, HTTP Link canonical, sitemap, redirect, and internal-link preferences. Check destination status and intent before suggesting consolidation.

Test host/protocol consistency, important moved URLs, chains/loops, unintended redirects to the homepage, and actual missing-page responses. Report repeated server failures with timing and affected scope. Do not assume absent robots or sitemap is a blocker when pages are otherwise discoverable.

## 2. Rendering, mobile, and page experience

Compare source and rendered main content, navigation, metadata and structured data. Check whether crawlable links exist without interaction, pagination works through URLs, and lazy content becomes available. Diagnose JS/resource failures and hydration changes. Do not infer that a framework choice alone causes poor SEO.

Inspect mobile readability, overflow, navigation, intrusive overlays, and access to primary content. Separate accessibility/usability improvements from demonstrated search issues. On-site forms, checkout, and conversions are observed without submitting them.

## 3. Architecture and internal links

Review hierarchy against important intents, contextual links, anchor clarity, broken links, redirected destinations, breadcrumbs and pagination. Identify navigation-only vs contextual links. Cross-check candidate orphans against a sufficiently complete crawl and sitemap/export inventory. Report inlinks and depth only for the graph actually observed.

Evaluate faceted and parameter URLs by usefulness and intended indexing. Do not prescribe blanket noindex/canonical/robots rules: these controls solve different problems and may conflict. Avoid canonicalizing distinct paginated content to page one by default.

## 4. On-page relevance and content

Compare title, visible main heading, description, body content, URL and target intent. Detect missing/generic/duplicated values across comparable pages. Inspect meaningful heading hierarchy, descriptive links, and accurate snippets. Length is a readability/display heuristic; multiple H1s or long titles are not automatically critical defects.

Assess whether the page answers the query and supports the next user action. Look for original evidence, clear authorship where relevant, verifiable expertise, sources for material claims, meaningful update dates, business identity and appropriate trust information. Apply stronger scrutiny to high-stakes topics without inventing a numerical E-E-A-T score.

Judge thinness by missing utility, not word count. Similar keywords do not prove cannibalization; establish intent overlap and use performance data when available. Preserve useful pages when recommending consolidation; list destination, intent, internal-link and redirect implications. Flag scaled repetitive pages with concrete examples of absent value, not a guessed AI-generation percentage.

## 5. Structured data

Inventory JSON-LD, microdata and RDFa across representative templates. Check syntax, entity IDs, types/properties, referenced entities and visible-content consistency. Verify prices, availability, dates and review claims against the actual page. Distinguish parser validity, Schema.org validity, current Google eligibility, and observed rich-result appearance.

Consult current official feature documentation before recommending a type or promising eligibility, especially FAQ/HowTo or other changing features. Record the validator used and results; do not call markup validated after only spotting a script. Recommend appropriate markup with only verified facts; no invented reviews, people, addresses, offers or ratings.

## 6. Performance and Core Web Vitals

For full audits, attempt mobile PageSpeed on representative important templates when reachable; include desktop where relevant. Use the bundled runner and measurement guidance in [scripts.md](scripts.md). For focused audits, measure only requested pages. For local projects, use local Lighthouse JSON instead of hosted PSI. Record blocked measurements as unknown and continue other audit areas.

Use field data when available and identify URL versus origin coverage, device, collection period, and percentile. Current good thresholds are LCP <= 2.5 s, INP <= 200 ms, CLS <= 0.1 at the 75th percentile; verify these against web.dev at audit time. Missing field data is unknown, not a pass.

Separate field results from Lighthouse/lab diagnostics. A single lab run is not representative of all visitors. Lighthouse TBT is not field INP. Record environment and repeated-run variability when diagnosing. Identify actual LCP element, layout-shift sources, image/font delivery, main-thread work, third-party cost and caching using available traces. Do not prescribe preloading every image or lazy-loading the LCP image.

## 7. Images and media

Inspect meaningful vs decorative images, missing vs intentionally empty alt, intrinsic dimensions, responsive sources, loading behavior, actual resource size and delivery. Assess video discoverability and captions/thumbnails where relevant. Do not derive byte sizes from CSS dimensions or stuff keywords into alt text. Connect proposed compression or format changes to measured assets and visual requirements.

## 8. Search visibility, authority, and AI search

Use the search-data reference for queries, performance, competitors and links. Cover this area even when data is unavailable; name the limitation precisely.

Review clear entities, helpful standalone explanations, source attribution, machine-readable text, and search-crawler access. Distinguish search retrieval from model training and user-triggered fetchers; verify vendor documentation before interpreting tokens. Do not change crawler policy during an audit. Inclusion in an AI answer is not guaranteed by access or markup. Treat llms.txt and other emerging conventions as optional experiments, never mandatory SEO fixes or verified ranking factors.
