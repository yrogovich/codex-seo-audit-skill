# Sources and design provenance

Reviewed on 2026-11-09. Revisit current primary documentation during each audit; this file is a starting point, not a frozen statement of search policy.

## Design references

- [AgriciDaniel/claude-seo](https://github.com/AgriciDaniel/claude-seo), particularly [full audit](https://github.com/AgriciDaniel/claude-seo/blob/main/skills/seo-audit/SKILL.md), [technical audit](https://github.com/AgriciDaniel/claude-seo/blob/main/skills/seo-technical/SKILL.md), and [hub](https://github.com/AgriciDaniel/claude-seo/blob/main/skills/seo/SKILL.md): useful breadth, template-aware analysis and persisted deliverables. Its runtime, delegation architecture, marketing footer, weighted scores and hardcoded policy claims are not adopted.
- [affaan-m/ECC SEO skill](https://github.com/affaan-m/ECC/blob/main/skills/seo/SKILL.md): useful compact practical review and page-specific remediation. Fixed length targets and single-heading guidance are treated as contextual heuristics.

This is an independently written Codex audit workflow, not a copy or installation of either repository. No upstream scripts or assets are bundled. Its optional standard-library Python helpers cover PageSpeed collection and report import, saved HTML extraction, CrUX field data, a site probe, a bounded crawler with analysis, audit validation and report rendering. The PageSpeed and HTML helpers were inspired by claude-seo's [PageSpeed](https://github.com/AgriciDaniel/claude-seo/blob/main/scripts/pagespeed_check.py) and [HTML extraction](https://github.com/AgriciDaniel/claude-seo/blob/main/scripts/parse_html.py) workflows; the guarded-fetch design borrows the idea of a shared SSRF layer with an explicit local-target allowance from claude-seo's url_safety.py, written independently. No browser runtime is bundled: rendering uses whatever browser tool is available, and unmeasured areas are reported as unknown.

## Primary references by decision

- [Search Essentials](https://developers.google.com/search/docs/essentials): foundational eligibility and policies.
- [robots.txt introduction](https://developers.google.com/search/docs/crawling-indexing/robots/intro): crawling versus indexing controls.
- [Canonical consolidation](https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls): canonical signals and duplicate URLs.
- [Sitemaps](https://developers.google.com/search/docs/crawling-indexing/sitemaps/overview): discovery and sitemap expectations.
- [JavaScript SEO](https://developers.google.com/search/docs/crawling-indexing/javascript/javascript-seo-basics): rendering, content and link discovery.
- [Title links](https://developers.google.com/search/docs/appearance/title-link): title guidance and search display behavior.
- [Structured-data policies](https://developers.google.com/search/docs/appearance/structured-data/sd-policies) and [supported features](https://developers.google.com/search/docs/appearance/structured-data/search-gallery): validity, eligibility and changing features.
- [Schema.org validator](https://validator.schema.org/) and [Rich Results Test](https://search.google.com/test/rich-results): different validation purposes; use only when available.
- [Web Vitals](https://web.dev/articles/vitals): current metrics, thresholds and field assessment.
- [PageSpeed getting started](https://developers.google.com/speed/docs/insights/v5/get-started) and [request/response reference](https://developers.google.com/speed/docs/insights/v5/reference/pagespeedapi/runpagespeed): hosted lab analysis, device strategies, categories, optional API key and field-data limitations.
- [Lighthouse CLI](https://github.com/GoogleChrome/lighthouse#using-the-node-cli) and [CrUX API](https://developer.chrome.com/docs/crux/api): local lab reports versus separately collected field measurements.
- [Localized versions](https://developers.google.com/search/docs/specialty/international/localized-versions): hreflang behavior.
- [Helpful content](https://developers.google.com/search/docs/fundamentals/creating-helpful-content) and [generative AI guidance](https://developers.google.com/search/docs/fundamentals/using-gen-ai-content): usefulness, trust and scaled-content concerns.
- [AI features and websites](https://developers.google.com/search/docs/appearance/ai-features): search inclusion and lack of special AI markup requirements.
- [Google Search status](https://status.search.google.com/): confirmed incidents and ranking updates.

For other search engines and AI crawlers, find the vendor's current official crawler/control documentation for the specific product. Do not infer search behavior from a training-bot name or an old third-party list.
