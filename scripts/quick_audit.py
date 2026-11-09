#!/usr/bin/env python3
"""One-command quick scan: probe, crawl, analyze and score a site, then print a short score card with the top fixes.

It chains the other scripts, so every step's output is the same as the manual flow. It is a fast scan, not a full
audit: it reads raw HTML, has no per-finding evidence write-up, and cannot judge content quality. Standard library only."""

import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
import io
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as common  # noqa: E402
import analyze_crawl  # noqa: E402
import crawl  # noqa: E402
import crux_check  # noqa: E402
import pagespeed_check  # noqa: E402
import probe  # noqa: E402
import render_report  # noqa: E402
import score_audit  # noqa: E402

UNSCORED_LIMIT = 5


def call(module, argv):
    """Run a script's main() in this process: (exit code, stdout, stderr)."""
    out, err, saved = io.StringIO(), io.StringIO(), sys.argv
    sys.argv = [module.__name__ + ".py"] + [str(a) for a in argv]
    try:
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = module.main()
            except SystemExit as stop:
                code = stop.code if isinstance(stop.code, int) else 2
    finally:
        sys.argv = saved
    return code, out.getvalue(), err.getvalue()


def default_folder(url, today=None):
    """seo-audits/<host>/<date>-quick, with -2, -3 ... if it already exists."""
    parts = urlsplit(url)
    name = parts.hostname + ("-%d" % parts.port if parts.port and parts.port not in (80, 443) else "")
    base = Path("seo-audits") / name
    stem = "%s-quick" % (today or date.today().isoformat())
    folder, number = base / stem, 2
    while folder.exists():
        folder, number = base / ("%s-%d" % (stem, number)), number + 1
    return folder


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def also_worth_a_look(analysis, rubric):
    """Candidates the score ignores because they are often intentional, with the reason."""
    notes = rubric.get("unscored_checks", {})
    items = [c for c in analysis.get("candidates", []) if c["check"] in notes]
    return ["- `%s`: %d (%s). Example: `%s`. %s" % (c["check"], c["count"], c["title"], (c["urls"] or ["-"])[0], notes[c["check"]]) for c in items[:UNSCORED_LIMIT]]


def write_report(folder, url, report, analysis, rubric, notes):
    crawl_info = report.get("crawl")
    lines = ["# Quick audit: %s" % url, "",
             "%s. This is a fast scan of raw HTML. It has no per-finding evidence write-up and cannot judge content quality. For a full audit with a fix plan, ask Codex to use $seo-audit." % date.today().isoformat(), ""]
    if crawl_info:
        lines += ["Pages: %s fetched of %s discovered (%s)." % (crawl_info["html_pages"], crawl_info["discovered"],
                                                                "crawl finished" if crawl_info["complete"] else "crawl stopped early: %s" % crawl_info["stop_reason"]), ""]
    if notes:
        lines += ["Notes:"] + ["- " + n for n in notes] + [""]
    lines += render_report.render_score(report)
    worth = also_worth_a_look(analysis, rubric) if analysis else []
    if worth:
        lines += ["## Also worth a look (not scored, often intentional)", ""] + worth + [""]
    lines += ["## Files", "", "- `score.json`: the score, every check and the fix-first list.", "- `crawl/analysis.json`: every candidate problem with affected URLs.",
              "- `crawl/url-inventory.csv`, `probe/probe.json`: the raw evidence.", ""]
    (folder / "quick-report.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--output-dir", type=Path, help="New folder (default: seo-audits/<host>/<date>-quick)")
    parser.add_argument("--max-pages", type=int, default=50, help="HTML pages to fetch (default 50)")
    parser.add_argument("--max-seconds", type=int, default=240, help="Crawl time limit (default 240)")
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds between requests to a host (default 1; minimum 0.2)")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--pagespeed", action="store_true", help="Also run PageSpeed Insights on mobile (sends the URL to Google)")
    parser.add_argument("--crux", action="store_true", help="Also fetch real-user Core Web Vitals (sends the URL to Google; needs CRUX_API_KEY)")
    parser.add_argument("--allow-local", action="append", default=[], metavar="ORIGIN", help="Explicitly in-scope local origin, e.g. http://localhost:3000")
    parser.add_argument("--ignore-robots-for-local", action="store_true", help="Apply the local-project robots exception to --allow-local origins only")
    parser.add_argument("--baseline", type=Path, help="Earlier score.json to compare against")
    args = parser.parse_args()
    url = common.normalize_url(args.url)
    if not url:
        parser.error("Provide an absolute http(s) URL without credentials.")
    if args.max_pages < 1 or args.max_seconds < 1 or args.delay < 0.2:
        parser.error("--max-pages and --max-seconds must be positive and --delay at least 0.2.")
    folder = args.output_dir or default_folder(url)
    if folder.exists():
        print("Error: %s already exists; choose a fresh folder." % folder, file=sys.stderr)
        return 1
    folder.mkdir(parents=True)
    local = [a for origin in args.allow_local for a in ("--allow-local", origin)]
    notes, score_args = [], ["--output", folder / "score.json"]
    print("Quick audit of %s\nFolder: %s" % (url, folder))

    print("[1/4] Checking the site (redirects, robots.txt, sitemaps)...")
    code, _, err = call(probe, [url, "--output-dir", folder / "probe", "--delay", args.delay, "--timeout", args.timeout] + local)
    probe_file = folder / "probe" / "probe.json"
    fetch_error = read(probe_file)["fetch"]["error"] if probe_file.exists() else None
    if code != 0 or not probe_file.exists():
        print("Could not fetch %s (%s). Nothing else was run." % (url, fetch_error or err.strip() or "unknown error"), file=sys.stderr)
        return 1
    score_args += ["--probe", probe_file]

    print("[2/4] Crawling up to %d pages (about one request per second)..." % args.max_pages)
    code, _, err = call(crawl, [url, "--output-dir", folder / "crawl", "--max-pages", args.max_pages, "--max-requests", args.max_pages * 3,
                                "--max-seconds", args.max_seconds, "--delay", args.delay, "--timeout", args.timeout]
                        + local + (["--ignore-robots-for-local"] if args.ignore_robots_for_local else []))
    summary_file, analysis_file = folder / "crawl" / "summary.json", folder / "crawl" / "analysis.json"
    if summary_file.exists() and read(summary_file)["counts"]["html_pages"]:
        print("[3/4] Finding likely problems...")
        code, _, err = call(analyze_crawl, [folder / "crawl", "--output", analysis_file])
        if code == 0:
            score_args += ["--analysis", analysis_file]
        else:
            notes.append("The crawl analysis failed (%s); the score uses the site checks only." % err.strip()[:100])
    else:
        reason = read(summary_file)["stop_reason"] if summary_file.exists() else "crawl did not start"
        notes.append("No pages were crawled (%s), so the score uses the site checks only." % reason)

    print("[4/4] Scoring...")
    if (args.pagespeed or args.crux) and local:
        notes.append("PageSpeed and CrUX were skipped: they cannot reach a local project.")
    elif args.pagespeed:
        code, _, err = call(pagespeed_check, [url, "--strategy", "mobile", "--output-dir", folder / "pagespeed"])
        if (folder / "pagespeed" / "summary.json").exists():
            score_args += ["--psi", folder / "pagespeed" / "summary.json"]
        if code != 0:
            notes.append("PageSpeed did not finish cleanly: %s" % (err.strip() or "see pagespeed/summary.json")[:120])
    if args.crux and not local:
        code, _, err = call(crux_check, [url, "--also-origin", "--form-factor", "phone", "--output-dir", folder / "crux"])
        if (folder / "crux" / "summary.json").exists():
            score_args += ["--crux", folder / "crux" / "summary.json"]
        if code != 0:
            notes.append("CrUX was skipped: %s" % (err.strip() or "no result")[:120])
    if args.baseline:
        score_args += ["--baseline", args.baseline]
    code, _, err = call(score_audit, score_args)
    if code != 0:
        print("Error: scoring failed: %s" % err.strip(), file=sys.stderr)
        return 1
    report = read(folder / "score.json")
    analysis = read(analysis_file) if analysis_file.exists() else {}
    write_report(folder, url, report, analysis, score_audit.load_rubric(score_audit.RUBRIC), notes)
    print("\n" + score_audit.summary_text(report))
    for note in notes:
        print("Note: " + note)
    print("\nReport: %s\nFor a full audit with evidence and a fix plan, ask Codex to use $seo-audit." % (folder / "quick-report.md"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
