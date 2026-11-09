# SEO Audit for Codex

Find SEO problems on your website and get a clear list of what to fix first. You can check a website that is already online or a project you are still building on your computer.

This skill gives Codex a repeatable audit process. It checks your pages, explains its findings, and saves proposed solutions ranked by expected impact and estimated time to fix.

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
Confirm it is available. Do not start an audit yet.
```

## Run a full audit

Open your website's project folder in Codex, or a folder where you want the report saved. Use this one prompt for either a live website or a local project:

```text
Use $seo-audit to run a full SEO audit of my website or the current project.

If I provide a website URL, audit it. Otherwise, inspect the current project,
find how to run it, and start a local preview if practical. If neither is
available, ask me for the website URL.

Check every applicable SEO area and explain the findings in plain language.
For each issue, show evidence and affected pages or files, propose a concrete
solution, estimate its expected impact and how long it will take to implement
and validate, and explain the assumptions behind those estimates.

Prioritize the action plan by impact, urgency, effort and dependencies.
Highlight quick wins and separate hands-on fix time from waiting for releases,
recrawling or measurable SEO results. Save the full report and action plan in
this workspace, and tell me what you could not verify. Do not edit or deploy.
```

Add your website URL when auditing a live site. You can also add your target country, language and main goal—for example, “We sell furniture in Poland and want more online orders.” Attach Search Console exports or other relevant data if available; they are optional.

For a local project, Codex inspects the code and running pages, preferring a production-style preview where practical. If it cannot run the site, it reports what source inspection supports and what remains untested. Checks that require a public deployment or private search data stay explicitly unverified. There is no separate mode prompt to choose.

## What you get

Codex saves each audit in a new folder inside `seo-audits/` in your workspace.

| File | What it is for |
| --- | --- |
| `report.md` | Read this first: findings, examples and explanations |
| `action-plan.md` | Prioritized solutions, expected impact, estimated fix time, dependencies and validation steps |
| `launch-checklist.md` | Local audits: checks before and after publishing |
| `url-inventory.csv` | A list of discovered pages and their inspection status; opens in a spreadsheet app |
| `findings.json` | A structured copy of the findings for other tools |
| `evidence/` | Supporting material collected during the audit |

You can ask Codex to open or summarize any of these files. Screenshots and performance measurements depend on the tools available in your session. A large website may be sampled; the report tells you what was checked and what was not.

## PageSpeed and helper scripts

The skill includes three optional Python helpers, with no extra Python packages required:

- `pagespeed_check.py` checks public pages with Google's PageSpeed Insights on mobile, desktop or both, one page or a list of up to 20. It saves the original results and a summary with scores, measured metrics, the affected elements and files behind each failing check, and diagnostics such as the LCP element. It can also read a saved Lighthouse report from a local project.
- `parse_html.py` extracts titles, metadata, headings, links (with image alt text as anchor text), image attributes, JSON-LD and visible-text size from saved HTML.
- `validate_audit.py` checks a finished audit folder before you rely on it: required files, `findings.json` structure, evidence links that actually exist, matching finding IDs across the report files, and accidentally saved secrets. It checks structure only and does not judge the SEO conclusions.

You need Python 3.9+ to run the scripts. PageSpeed needs network access and may require a Google API key if keyless quota is unavailable; the helper reads `PAGESPEED_API_KEY` from the environment. Local websites use local Lighthouse measurements. Missing data is reported as unknown. See [script usage and examples](references/scripts.md).

## Optional prompts

The full-audit prompt above is the main starting point. Use these only when you want a narrower check or a follow-up. Actionable findings still include proposed solutions, expected impact and estimated fix time.

### Check one page

```text
Use $seo-audit to audit only https://example.com/services.
Check every applicable SEO area for this page and propose specific improvements
with expected impact and estimated time to implement and validate each fix.
```

### Review a local project before launch

```text
Use $seo-audit to run a full pre-launch audit of this project.
Find how to run it and use a production-style preview if practical.
Link findings to pages and source files, propose solutions with impact and
fix-time estimates, and create a before/after launch checklist. Do not edit or deploy.
```

If the site is already running, add its local URL, for example `http://localhost:3000`.

### Focus on PageSpeed

```text
Use $seo-audit to check PageSpeed for https://example.com on mobile and desktop.
Save the evidence, explain the main measured bottlenecks, and propose fixes
with expected impact and estimated implementation and validation time.
Keep lab results separate from real-user Core Web Vitals.
```

### Include Google Search Console data

```text
Use $seo-audit to run a full audit of https://example.com with the attached
Google Search Console export. Include proposed solutions, expected impact and
fix-time estimates. Separate measured results from recommendations that need verification.
```

### Explain the results

```text
Explain the audit results as if I am new to SEO.
What are the three most useful things to fix first, what impact should I expect,
how long might each take, and how can I check that each fix worked?
```

### Recheck after fixes

```text
Use $seo-audit to recheck the issues from the previous audit.
Compare the new results with the saved report. Show which issues are fixed,
which remain, and which you could not verify. Update impact and fix-time estimates
for remaining work, and save a separate new report.
```

## Update the installed skill

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
