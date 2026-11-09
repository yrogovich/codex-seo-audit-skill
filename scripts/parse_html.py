#!/usr/bin/env python3
"""Extract SEO evidence from saved HTML, without fetching URLs or executing JavaScript."""

import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import sys
from urllib.parse import urljoin


class Extractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.result = {"titles": [], "meta": [], "canonicals": [], "hreflang": [],
                       "headings": [], "links": [], "images": [], "json_ld": [], "base_hrefs": []}
        self.capture = None
        self.text = []
        self.link = None
        self.link_text = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.result["language"] = a.get("lang")
        if tag == "base" and "href" in a:
            self.result["base_hrefs"].append(a["href"])
        if tag == "meta":
            self.result["meta"].append(a)
        if tag == "link":
            rel = a.get("rel", "").lower().split()
            if "canonical" in rel:
                self.result["canonicals"].append(a.get("href"))
            if "alternate" in rel and "hreflang" in a:
                self.result["hreflang"].append(a)
        if tag == "img":
            # Preserve missing alt as null and decorative alt as an empty string.
            self.result["images"].append({k: a.get(k) for k in ("src", "srcset", "alt", "width", "height", "loading", "fetchpriority", "data-src")})
        if tag == "a":
            self.link, self.link_text = a, []
        if tag in ("title", "h1", "h2", "h3", "h4", "h5", "h6") or (tag == "script" and a.get("type", "").lower().split(";")[0].strip() == "application/ld+json"):
            self.capture, self.text = tag, []

    def handle_data(self, data):
        if self.capture:
            self.text.append(data)
        if self.link is not None:
            self.link_text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.link is not None:
            self.result["links"].append({**self.link, "text": " ".join("".join(self.link_text).split())})
            self.link = None
        if tag != self.capture:
            return
        raw = "".join(self.text)
        text = " ".join(raw.split())
        if tag == "title":
            self.result["titles"].append(text)
        elif tag.startswith("h"):
            self.result["headings"].append({"level": int(tag[1]), "text": text})
        else:
            try:
                self.result["json_ld"].append({"value": json.loads(raw), "syntax_error": None})
            except ValueError as exc:
                self.result["json_ld"].append({"raw": raw, "syntax_error": str(exc)})
        self.capture, self.text = None, []


def extract(html, base_url=None):
    parser = Extractor()
    parser.feed(html)
    parser.close()
    result = parser.result
    base = urljoin(base_url or "", result["base_hrefs"][0]) if result["base_hrefs"] else base_url
    result["resolution_base"] = base
    if base:
        for link in result["links"] + result["hreflang"]:
            if link.get("href") is not None:
                link["resolved_href"] = urljoin(base, link["href"])
        result["resolved_canonicals"] = [urljoin(base, c) if c is not None else None for c in result["canonicals"]]
    result["limitations"] = ["Saved HTML only; no HTTP status, headers, robots rules, rendered DOM or linked destinations verified.",
                             "JSON-LD parsing establishes syntax only, not schema validity or rich-result eligibility.",
                             "Standard-library HTML parser; malformed markup may differ from a browser DOM."]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html", type=Path)
    parser.add_argument("--base-url", help="Original response URL for resolving relative links")
    parser.add_argument("--encoding", default="utf-8", help="Use response/document encoding when known")
    parser.add_argument("--output", type=Path, help="New JSON file; defaults to stdout")
    args = parser.parse_args()
    try:
        content = args.html.read_bytes()
        result = extract(content.decode(args.encoding), args.base_url)
        result.update({"source_file": str(args.html), "sha256": hashlib.sha256(content).hexdigest(), "encoding": args.encoding})
        output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(output)
        else:
            print(output, end="")
        return 0
    except (OSError, ValueError, LookupError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
