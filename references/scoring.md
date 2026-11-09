# Checklist score (optional)

Give a 0-100 number only when the user asks for one. Otherwise report findings and coverage, not a score.

The score is an **internal checklist metric, not a Google ranking predictor**. It counts how many checks from a fixed list pass. It cannot tell you how a site will rank.

## Run it

```sh
python3 scripts/score_audit.py \
  --analysis evidence/crawl/analysis.json \
  --probe evidence/probe/probe.json \
  --psi evidence/pagespeed/summary.json \
  --crux evidence/crux/summary.json \
  --output score.json
```

Every input is optional. The more you supply, the more of the checklist is checked. `render_report.py` adds a "Checklist score" section to `report.md` when `score.json` sits in the audit folder.

## How the number is made

- The checks and weights live in [score-rubric.json](score-rubric.json). Each check has a weight from 1 to 5 and a one-line fix.
- A check scores 1 when nothing is wrong and drops as more pages are affected: `max(0, 1 - sensitivity x affected / total)`.
- Overall score = weighted average of the checks that could be checked, times 100. Each area (indexing, links, on-page and so on) gets its own score the same way.
- Weights are our judgment of how directly a problem can stop crawling or indexing. They are not measured effects on rankings.

## Read it in this order

1. **Checked %** (coverage). Checks that could not run, such as no CrUX data or no sitemap, are left out. They are not counted as passes, so a high score with low coverage means little.
2. **Blockers.** A robots.txt that blocks everything, a noindex on the start page, or a failing main URL is flagged next to the score. These matter more than the number, and the score is never capped to hide or add to them.
3. **Fix first.** The checks that lost the most points, with the affected count and a plain fix. "Points" is roughly how much the score would rise if that check fully passed.

## What it does not cover

Content quality, trust signals, backlinks, rankings and real indexing status, AI search, local and shop-specific checks, and anything that only appears after JavaScript runs. The crawl reads raw HTML. A partial crawl scores only the pages it fetched, and the report says so.

## Compare two runs

Pass the earlier file with `--baseline score.json`. Scores are only comparable when the rubric version matches, and the comparison uses just the checks both runs measured, so extra coverage cannot look like progress. If the rubric file changed without a version bump, the script refuses to compare.

## Change the rubric

Edit [score-rubric.json](score-rubric.json) and raise `version` whenever a weight, a check or a threshold changes. Performance thresholds follow web.dev; check them again at audit time.
