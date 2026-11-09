# SEO Audit for Codex

Find SEO problems on your website and get a clear list of what to fix first. You can check a website that is already online or a project you are still building on your computer.

This skill gives Codex a repeatable audit process. It checks your pages, explains its findings, and saves a report with practical next steps.

**[View this project on GitHub](https://github.com/yrogovich/codex-seo-audit-skill)**

## Install in Codex

You need Codex with local skills support. You do not need a paid SEO tool or a Google Search Console account to get started.

### Option 1: Ask Codex to install it

Copy this into a Codex chat:

```text
Use $skill-installer to install the SEO audit skill from:
https://github.com/yrogovich/codex-seo-audit-skill

The SKILL.md file is at the repository root.
Install it as seo-audit so I can use it across my projects.
If I already have it installed, check the existing copy before making changes.
```

If Codex requests permission to download or install the skill, review and approve the request. If `$seo-audit` does not appear afterward, restart Codex and open a new chat.

### Option 2: Install from a terminal

On macOS or Linux, with Git installed, open Terminal and paste this entire block. You can run it from any folder:

```sh
mkdir -p "$HOME/.agents/skills" &&
  git clone https://github.com/yrogovich/codex-seo-audit-skill.git "$HOME/.agents/skills/seo-audit"
```

This downloads the skill into your personal skills folder. If the destination already exists, stop and use the update prompt below rather than deleting it.

Choose one installation option—you do not need both. Codex's supported skill locations are described in the [official installation documentation](https://learn.chatgpt.com/docs/build-skills).

### Check that it is installed

Paste this into Codex:

```text
Can you find the installed $seo-audit skill?
Tell me which audit modes it supports. Do not start an audit yet.
```

## Audit a website that is already online

Open a project or folder in Codex where you want the report saved. Copy the prompt below and replace `https://example.com` with your website address:

```text
Use $seo-audit to run a full SEO audit of https://example.com.

Explain the findings in plain language. Show the most important problems
first, give examples from my pages, and tell me how to fix each one.
Save the report and a prioritized action plan in this workspace.
Tell me what you could not check. Do not change the website.
```

For more relevant advice, add your target country, language and main goal—for example, “We sell furniture in Poland and want more online orders.”

### Check just one page

Replace the example address with the page you want to review:

```text
Use $seo-audit to review only https://example.com/services.
Check its title, description, headings, content, images and links.
Give me specific improvements with examples. Explain any technical terms.
```

## Audit a project before publishing it

Open your website's project folder in Codex. The skill can inspect your code and check the website running on your computer.

### If you do not know how to start the website

Copy this prompt as it is:

```text
Use $seo-audit in local-project mode to check this project before launch.

Read the project instructions and find how to run the website locally.
Start a local preview if practical, then check both the code and the pages.
Use a production-style preview if the project supports it.

Explain the findings in plain language and link each code issue to its file.
Create a checklist showing what to fix before launch and what to verify
once the website is online. Do not edit the code or deploy the website.
```

### If the website is already running

A local address often looks like `http://localhost:3000` or `http://localhost:5173`. Copy the address from your browser and replace the example below:

```text
Use $seo-audit in local-project mode to audit this project
and http://localhost:3000 before deployment.

Check the source code and the running website. Prioritize launch blockers,
link findings to the relevant files, and create a launch checklist.
Keep intentional development settings in place. Do not edit or deploy anything.
```

Local checks cannot confirm Google rankings, whether Google has indexed the site, or how fast it will be for real visitors. The report keeps those checks separate for after launch. If the local website cannot run, Codex can still inspect the code and explain what remains untested.

## What you get

Codex saves each audit in a new folder inside `seo-audits/` in your workspace.

| File | What it is for |
| --- | --- |
| `report.md` | Read this first: findings, examples and explanations |
| `action-plan.md` | What to fix first, with steps to check the fix |
| `launch-checklist.md` | Local audits: checks before and after publishing |
| `url-inventory.csv` | A list of discovered pages and their inspection status; opens in a spreadsheet app |
| `findings.json` | A structured copy of the findings for other tools |
| `evidence/` | Supporting material collected during the audit |

You can ask Codex to open or summarize any of these files. Screenshots and performance measurements depend on the tools available in your session. A large website may be sampled; the report tells you what was checked and what was not.

## PageSpeed and helper scripts

The skill includes optional Python helpers, with no extra Python packages required. They collect evidence and list leads; judgment and severity stay in the audit:

- `probe.py` checks one URL and its site: redirects, headers, robots.txt rules per crawler, sitemaps, www/https variants and what happens on a missing page.
- `crawl.py` crawls politely and read-only within strict limits (100 pages and one request per second by default, robots.txt honored), saving pages, links and your `url-inventory.csv`. It stops if the site pushes back.
- `analyze_crawl.py` turns that crawl into candidate problems with affected pages: broken links, redirect chains, duplicate titles, noindex or canonical conflicts, hreflang gaps and more. They are leads to check, not verdicts, and a partial crawl is labelled as a sample.
- `crux_check.py` fetches real-user Core Web Vitals with collection dates from Google's Chrome UX Report (needs an API key).
- `render_report.py` builds `action-plan.md` and `report.md` from `findings.json`, so the files cannot disagree.
- `pagespeed_check.py` checks public pages with Google's PageSpeed Insights on mobile, desktop or both, one page or a list of up to 20. It saves the original results and a summary with scores, measured metrics, the affected elements and files behind each failing check, and diagnostics such as the LCP element. It can also read a saved Lighthouse report from a local project.
- `parse_html.py` extracts titles, metadata, headings, links (with image alt text as anchor text), image attributes, JSON-LD and visible-text size from saved HTML.
- `validate_audit.py` checks a finished audit folder before you rely on it: required files, `findings.json` structure, evidence links that actually exist, matching finding IDs across the report files, and accidentally saved secrets. It checks structure only and does not judge the SEO conclusions.

You need Python 3.9+ to run the scripts. Probe, crawl, PageSpeed and CrUX need network access and only contact the site you give them (the crawler refuses private addresses unless you explicitly allow a local project origin). PageSpeed may require a Google API key if keyless quota is unavailable and CrUX always does; the helpers read `PAGESPEED_API_KEY` or `CRUX_API_KEY` from the environment, never from the command line. Local websites use local Lighthouse measurements. Missing data is reported as unknown. See [script usage and examples](references/scripts.md).

Try this prompt:

```text
Use $seo-audit to check PageSpeed for https://example.com on mobile
and desktop. Save the raw evidence, explain the main measured bottlenecks,
and keep lab results separate from real-user Core Web Vitals.
```

## More copy-and-paste prompts

### Explain the results

Use this after an audit:

```text
Explain the audit results as if I am new to SEO.
What are the three most useful things to fix first, why do they matter,
and how can I check that each fix worked?
```

### Include Google Search Console data

Attach your export first, then replace the example website address:

```text
Use $seo-audit to audit https://example.com with the attached Google
Search Console export. Explain what the data shows and keep measured
results separate from recommendations that still need verification.
```

### Recheck after making fixes

Use this in the same project after updating the website:

```text
Use $seo-audit to recheck the issues from the previous audit.
Compare the new results with the saved report. Show which issues are fixed,
which remain, and which you could not verify. Save a separate new report.
```

### Update the installed skill

```text
Update my installed seo-audit skill from:
https://github.com/yrogovich/codex-seo-audit-skill

Find the existing installation first. Preserve any local customizations
and avoid creating a second copy. Tell me when the update is complete.
```

## How it works

The skill checks whether search engines can access your pages, whether page titles and content are useful, whether links work, and whether the website behaves correctly on mobile. It also reviews speed, structured data (extra information for search engines), and relevant checks for shops, local businesses and multilingual websites.

It uses the tools available to Codex and reports missing evidence honestly. It does not promise rankings or automatically change your website. Ask separately when you want help implementing a fix.

For the full workflow, see [SKILL.md](SKILL.md), the [local project guide](references/local-project.md), and the [report format](references/reporting.md).

## Credits

Inspired by [claude-seo](https://github.com/AgriciDaniel/claude-seo) and [ECC's SEO skill](https://github.com/affaan-m/ECC/blob/main/skills/seo/SKILL.md). This is an independently written Codex workflow. See [sources and design notes](references/sources.md).
