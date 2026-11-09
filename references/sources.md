# Sources and design notes

Reviewed on 2026-11-09 (the Google links used by the score rubric were all opened that day). Check the current official docs during each audit. This file is a starting point, not a fixed statement of search policy.

## Design references

- [AgriciDaniel/claude-seo](https://github.com/AgriciDaniel/claude-seo) ([full audit](https://github.com/AgriciDaniel/claude-seo/blob/main/skills/seo-audit/SKILL.md), [technical audit](https://github.com/AgriciDaniel/claude-seo/blob/main/skills/seo-technical/SKILL.md), [hub](https://github.com/AgriciDaniel/claude-seo/blob/main/skills/seo/SKILL.md)): we took the breadth, page-type thinking and saved deliverables. We did not take its runtime, sub-agent design, marketing footer, weighted scores or fixed policy claims.
- [affaan-m/ECC SEO skill](https://github.com/affaan-m/ECC/blob/main/skills/seo/SKILL.md): a compact, practical review with page-specific fixes. We treat its fixed length targets and single-heading advice as hints, not rules.

This is an independent Codex workflow. It is not a copy of either project, and no upstream code or assets are included. The optional Python helpers use only the standard library. The PageSpeed and HTML helpers were inspired by claude-seo's [PageSpeed](https://github.com/AgriciDaniel/claude-seo/blob/main/scripts/pagespeed_check.py) and [HTML extraction](https://github.com/AgriciDaniel/claude-seo/blob/main/scripts/parse_html.py) scripts. The guarded-fetch layer borrows the idea of one shared SSRF guard with an explicit local-target allowance from claude-seo's url_safety.py, written independently. No browser runtime is included: use whatever browser tool you have, and report unmeasured areas as unknown.

## Official references by topic

- [Search Essentials](https://developers.google.com/search/docs/essentials): basic eligibility and policies.
- [Technical requirements](https://developers.google.com/search/docs/essentials/technical): the three minimum requirements to be indexed: Googlebot is not blocked, the page works (HTTP 200), and it has indexable content.
- [robots.txt introduction](https://developers.google.com/search/docs/crawling-indexing/robots/intro): crawling versus indexing controls.
- [Robots meta tag and X-Robots-Tag](https://developers.google.com/search/docs/crawling-indexing/robots-meta-tag): `noindex` and other rules. The stricter rule wins, and a robots.txt block hides them.
- [Redirects and Google Search](https://developers.google.com/search/docs/crawling-indexing/301-redirects): permanent and temporary redirects.
- [HTTP status codes](https://developers.google.com/search/docs/crawling-indexing/http-network-errors): how status codes, soft 404s and redirect hops affect crawling (Googlebot generally follows 10 hops).
- [Link best practices](https://developers.google.com/search/docs/crawling-indexing/links-crawlable): crawlable `<a href>` links and descriptive anchor text.
- [Snippets](https://developers.google.com/search/docs/appearance/snippet): meta descriptions and how snippets are made.
- [Image SEO](https://developers.google.com/search/docs/appearance/google-images): `alt` text and image guidance.
- [Page experience](https://developers.google.com/search/docs/appearance/page-experience): HTTPS and Core Web Vitals (there is no single page experience signal).
- [Canonical consolidation](https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls): canonical signals and duplicate URLs.
- [Sitemaps](https://developers.google.com/search/docs/crawling-indexing/sitemaps/overview): discovery and sitemap expectations.
- [JavaScript SEO](https://developers.google.com/search/docs/crawling-indexing/javascript/javascript-seo-basics): rendering, content and link discovery.
- [Title links](https://developers.google.com/search/docs/appearance/title-link): title guidance and display.
- [Structured-data policies](https://developers.google.com/search/docs/appearance/structured-data/sd-policies) and [supported features](https://developers.google.com/search/docs/appearance/structured-data/search-gallery): validity, eligibility and changing features.
- [Schema.org validator](https://validator.schema.org/) and [Rich Results Test](https://search.google.com/test/rich-results): they test different things.
- [Web Vitals](https://web.dev/articles/vitals): metrics, thresholds and field assessment.
- [PageSpeed getting started](https://developers.google.com/speed/docs/insights/v5/get-started) and [API reference](https://developers.google.com/speed/docs/insights/v5/reference/pagespeedapi/runpagespeed): hosted lab runs, the optional API key, field-data limits.
- [Lighthouse CLI](https://github.com/GoogleChrome/lighthouse#using-the-node-cli) and [CrUX API](https://developer.chrome.com/docs/crux/api): local lab reports versus field data.
- [Localized versions](https://developers.google.com/search/docs/specialty/international/localized-versions): how hreflang works.
- [Helpful content](https://developers.google.com/search/docs/fundamentals/creating-helpful-content) and [generative AI guidance](https://developers.google.com/search/docs/fundamentals/using-gen-ai-content): usefulness, trust, scaled content.
- [AI features and websites](https://developers.google.com/search/docs/appearance/ai-features): how search inclusion works, and that no special AI markup is required.
- [Google Search status](https://status.search.google.com/): confirmed incidents and ranking updates.

For other search engines and AI crawlers, find the vendor's current official documentation for that exact product. Do not guess search behavior from a training-bot name or an old third-party list.
