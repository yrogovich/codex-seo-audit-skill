# Conditional checks

Use only the sections that apply. Mark the others "not applicable" with a reason. A mixed business may need several.

## Ecommerce

- Sample categories, products, variants, pagination, filters, and discontinued or out-of-stock items.
- Check that products are found through crawlable links, category pages are useful and distinct, variant URLs and canonicals make sense, and out-of-stock pages respond sensibly.
- Compare product and offer markup with the visible price, currency, availability and reviews.
- Check feed and landing-page consistency only if you have the feed.
- Do not recommend deleting temporarily unavailable products by default.
- Keep shopping-feature eligibility apart from normal organic eligibility.

## Local services and locations

- Verify the public business identity, name/address/phone consistency, real service area, unique location content and genuine reviews.
- Use public business profiles where possible. Owner-only settings stay unverified without access.
- Check LocalBusiness markup against real details. Tell storefront, service-area and hybrid businesses apart.
- A location search needs a stated location, and one search is not a map ranking survey.
- Avoid made-up addresses, review-gathering schemes and near-identical doorway pages.

## International and multilingual

- List the language and region URLs and their content.
- Check hreflang: valid codes, absolute URLs, pages that link to each other and to themselves, and compatibility with canonicals. `x-default` is optional.
- Check translated content and metadata, language navigation, redirects, index eligibility, currency and units.
- Do not canonicalize valid translations to one language by default.
- Call a return link missing only after checking the target page, not from one page's tags.

## Publishers, SaaS and service businesses

- **Publishers:** how articles, categories and authors are found; original reporting; attribution; honest dates; syndication and canonicals; useful archives.
- **SaaS:** tell product, feature, integration, comparison, pricing, help and docs pages apart. Check that useful docs are public and product claims have evidence. Login-only content is not automatically a defect.
- **Service and agency sites:** relevant services and industries, solid case studies, location claims, clear expertise, ways to get in touch. A visual portfolio is not "missing content" until you have checked its rendered text and links.

## Migrations and generated pages

- **Migration:** reconcile old and new URL lists, redirect maps, canonical and hreflang updates, staging exclusions, internal links and sitemaps. Verify production separately from what the repo intends. Do not remove a staging noindex just because it blocks indexing.
- **Generated landing pages:** group by template and sample typical and edge cases. Judge distinct usefulness, data completeness and duplication. If indexing looks like it is exploding, widen scope with bounded URL patterns, and never crawl endless combinations. Suggest staged changes with a measurable check, not fixed word-count or page-count rules.
