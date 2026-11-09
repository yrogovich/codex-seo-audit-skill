# SEO Audit for Codex

Find SEO problems on your website and get a clear list of what to fix first. It works on a live site or on a project you are still building on your computer.

Codex follows a repeatable process: it checks your pages, explains what it found, and saves a report with next steps.

**[View this project on GitHub](https://github.com/yrogovich/codex-seo-audit-skill)**

## Install in Codex

You need Codex with local skills support. You do not need a paid SEO tool or a Google Search Console account.

### Option 1: Ask Codex to install it

Paste this into a Codex chat:

```text
Use $skill-installer to install the SEO audit skill from:
https://github.com/yrogovich/codex-seo-audit-skill

The SKILL.md file is at the repository root.
Install it as seo-audit so I can use it across my projects.
If I already have it installed, check the existing copy before making changes.
```

Approve the download if Codex asks. If `$seo-audit` does not appear, restart Codex and open a new chat.

### Option 2: Install from a terminal

On macOS or Linux with Git installed, run this from any folder:

```sh
mkdir -p "$HOME/.agents/skills" &&
  git clone https://github.com/yrogovich/codex-seo-audit-skill.git "$HOME/.agents/skills/seo-audit"
```

If the folder already exists, do not delete it. Use the update prompt below instead. Pick one option, not both. Codex's skill locations are in the [official docs](https://learn.chatgpt.com/docs/build-skills).

### Check that it works

```text
Can you find the installed $seo-audit skill?
Tell me which audit modes it supports. Do not start an audit yet.
```

## Audit a live website

Open the folder where you want the report saved. Replace `https://example.com` with your address:

```text
Use $seo-audit to run a full SEO audit of https://example.com.

Explain the findings in plain language. Show the most important problems
first, give examples from my pages, and tell me how to fix each one.
Save the report and a prioritized action plan in this workspace.
Tell me what you could not check. Do not change the website.
```

For better advice, add your country, language and goal, for example: "We sell furniture in Poland and want more online orders."

### Check one page

```text
Use $seo-audit to review only https://example.com/services.
Check its title, description, headings, content, images and links.
Give me specific improvements with examples. Explain any technical terms.
```

## Audit a project before publishing

Open your project folder in Codex. It reads your code and checks the site running on your computer.

### If you do not know how to start the site

```text
Use $seo-audit in local-project mode to check this project before launch.

Read the project instructions and find how to run the website locally.
Start a local preview if practical, then check both the code and the pages.
Use a production-style preview if the project supports it.

Explain the findings in plain language and link each code issue to its file.
Create a checklist showing what to fix before launch and what to verify
once the website is online. Do not edit the code or deploy the website.
```

### If the site is already running

A local address looks like `http://localhost:3000`. Copy it from your browser:

```text
Use $seo-audit in local-project mode to audit this project
and http://localhost:3000 before deployment.

Check the source code and the running website. Prioritize launch blockers,
link findings to the relevant files, and create a launch checklist.
Keep intentional development settings in place. Do not edit or deploy anything.
```

Local checks cannot show Google rankings, whether Google indexed the site, or real visitor speed. The report keeps those for after launch. If the site cannot run, Codex still reads the code and says what it could not test.

## What you get

Each audit goes in a new folder under `seo-audits/` in your workspace.

| File | What it is for |
| --- | --- |
| `report.md` | Start here: findings, examples, explanations |
| `action-plan.md` | What to fix first, and how to check each fix |
| `launch-checklist.md` | Local audits: checks before and after publishing |
| `url-inventory.csv` | Pages found and how each was checked (opens in a spreadsheet) |
| `findings.json` | The findings in a format other tools can read |
| `score.json` | Only if you ask for a score: the 0-100 checklist score, coverage and top fixes |
| `evidence/` | Raw material collected during the audit |

Ask Codex to open or summarize any file. A big site may be sampled, and the report says what was and was not checked.

## Helper scripts (optional)

These Python scripts need Python 3.9+ and no extra packages. They collect evidence and suggest leads. The judgment stays in the audit.

| Script | What it does |
| --- | --- |
| `probe.py` | Checks one URL and its site: redirects, headers, robots.txt, sitemaps, www/https variants, missing-page behavior |
| `crawl.py` | Crawls politely and read-only (100 pages, one request per second, robots.txt honored) and saves pages, links and `url-inventory.csv` |
| `analyze_crawl.py` | Turns a crawl into a list of likely problems with affected pages. These are leads, not verdicts |
| `pagespeed_check.py` | Runs Google PageSpeed Insights on up to 20 pages, or reads a saved Lighthouse report |
| `crux_check.py` | Gets real-user Core Web Vitals with dates from Google's Chrome UX Report (needs an API key) |
| `score_audit.py` | Optional 0-100 checklist score with coverage, blockers and top fixes. Only when you ask. Not a Google ranking predictor |
| `render_report.py` | Builds `action-plan.md` and `report.md` from `findings.json` so they always agree |
| `validate_audit.py` | Checks a finished audit folder: files, structure, evidence links, matching IDs, saved secrets |
| `parse_html.py` | Pulls titles, headings, links, images and structured data out of saved HTML |

The scripts only contact the site you give them. The crawler refuses private addresses unless you explicitly allow a local project address. API keys come from the environment variables `PAGESPEED_API_KEY` and `CRUX_API_KEY`, never from the command line. Missing data is reported as unknown. Details and examples: [scripts.md](references/scripts.md).

## More prompts

### Add a 0-100 score

```text
Use $seo-audit to audit https://example.com and add the checklist score.
Show how much of the checklist could be checked, the score per area,
blockers, and the top fixes with the points each would gain.
```

### Check page speed

```text
Use $seo-audit to check PageSpeed for https://example.com on mobile
and desktop. Save the raw evidence, explain the main measured bottlenecks,
and keep lab results separate from real-user Core Web Vitals.
```

### Explain the results

```text
Explain the audit results as if I am new to SEO.
What are the three most useful things to fix first, why do they matter,
and how can I check that each fix worked?
```

### Add Google Search Console data

Attach your export first:

```text
Use $seo-audit to audit https://example.com with the attached Google
Search Console export. Explain what the data shows and keep measured
results separate from recommendations that still need verification.
```

### Recheck after fixes

```text
Use $seo-audit to recheck the issues from the previous audit.
Compare the new results with the saved report. Show which issues are fixed,
which remain, and which you could not verify. Save a separate new report.
```

### Update the skill

```text
Update my installed seo-audit skill from:
https://github.com/yrogovich/codex-seo-audit-skill

Find the existing installation first. Preserve any local customizations
and avoid creating a second copy. Tell me when the update is complete.
```

## How it works

The skill checks whether search engines can reach your pages, whether titles and content are useful, whether links work, and whether the site works on mobile. It also looks at speed, structured data (extra information for search engines), and checks for shops, local businesses and multilingual sites.

It reports missing evidence honestly. It does not promise rankings, and it does not change your site. Ask separately if you want help with a fix.

More detail: [SKILL.md](SKILL.md), the [local project guide](references/local-project.md) and the [report format](references/reporting.md).

## Credits

Inspired by [claude-seo](https://github.com/AgriciDaniel/claude-seo) and [ECC's SEO skill](https://github.com/affaan-m/ECC/blob/main/skills/seo/SKILL.md). This is an independently written Codex workflow. See [sources and design notes](references/sources.md).
