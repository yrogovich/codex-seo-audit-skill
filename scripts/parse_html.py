#!/usr/bin/env python3
"""Extract SEO evidence from saved HTML, without fetching URLs or executing JavaScript."""

import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import sys
from urllib.parse import urljoin

# Text inside these elements is not visible page content. <title> is listed so a stray
# body title never counts as visible text; head content is skipped separately.
SKIP_TEXT = {"script", "style", "noscript", "template", "svg", "title"}
# Operational cue, not an SEO standard: a client-rendering marker plus very little
# server-delivered text suggests the page needs a browser check.
SPA_TEXT_THRESHOLD = 400
SPA_ROOT_IDS = {"root", "app", "__next", "__nuxt", "___gatsby"}


class Extractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.result = {"titles": [], "meta": [], "canonicals": [], "hreflang": [],
                       "headings": [], "links": [], "images": [], "json_ld": [], "base_hrefs": []}
        self.capture = None
        self.text = []
        self.link = None
        self.link_text = []
        self.link_images = []
        self.skip = {}
        self.in_head = False
        self.visible = []
        self.markers = set()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in SKIP_TEXT:
            self.skip[tag] = self.skip.get(tag, 0) + 1
        if tag == "head":
            self.in_head = True
        if tag == "body":
            self.in_head = False
        self.note_markers(tag, a)
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
            if self.link is not None:
                self.link_images.append(a.get("alt"))
        if tag == "a":
            self.link, self.link_text, self.link_images = a, [], []
        # SVG <title> elements are accessibility labels, not the document title.
        if (tag == "title" and not self.skip.get("svg")) or tag in ("h1", "h2", "h3", "h4", "h5", "h6") or (
                tag == "script" and a.get("type", "").lower().split(";")[0].strip() == "application/ld+json"):
            self.capture, self.text = tag, []

    def note_markers(self, tag, a):
        if a.get("id") in SPA_ROOT_IDS:
            self.markers.add('id="%s"' % a["id"])
        for name in ("data-reactroot", "ng-version"):
            if name in a:
                self.markers.add(name)
        if any(name.startswith("data-svelte-h") for name in a):
            self.markers.add("data-svelte-h")
        if tag in ("app-root", "astro-island"):
            self.markers.add("<%s>" % tag)

    def handle_data(self, data):
        if self.capture:
            self.text.append(data)
        if self.link is not None:
            self.link_text.append(data)
        if self.skip.get("noscript") and "javascript" in data.lower():
            self.markers.add("noscript-javascript-notice")
        if not self.in_head and not any(self.skip.values()):
            self.visible.append(data)

    def handle_endtag(self, tag):
        if tag in SKIP_TEXT and self.skip.get(tag):
            self.skip[tag] -= 1
        if tag == "head":
            self.in_head = False
        if tag == "a" and self.link is not None:
            text = " ".join("".join(self.link_text).split())
            alts = [alt for alt in self.link_images if alt and alt.strip()]
            self.result["links"].append({**self.link, "text": text,
                                         # Alt values of images inside the link (null = image has no alt).
                                         "image_alts": list(self.link_images),
                                         # Effective anchor text: link text, else the images' alt text.
                                         "anchor_text": text or " ".join(" ".join(alt.split()) for alt in alts)})
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
    # Chunks are joined with a space so adjacent blocks do not merge into one word.
    visible = " ".join(" ".join(parser.visible).split())
    result["visible_text"] = {"chars": len(visible), "words": len(visible.split()),
                              "excludes": "head, script, style, noscript, template and SVG content"}
    markers = sorted(parser.markers)
    result["rendering_hint"] = {"shell_markers": markers, "visible_text_chars": len(visible),
                                "possible_client_rendered": bool(markers) and len(visible) < SPA_TEXT_THRESHOLD,
                                "threshold_chars": SPA_TEXT_THRESHOLD,
                                "basis": "Heuristic cue from saved HTML only; confirm in a browser before concluding content depends on JavaScript."}
    result["limitations"] = ["Saved HTML only; no HTTP status, headers, robots rules, rendered DOM or linked destinations verified.",
                             "JSON-LD parsing establishes syntax only, not schema validity or rich-result eligibility.",
                             "Standard-library HTML parser; malformed markup may differ from a browser DOM.",
                             "Visible text and rendering_hint are diagnostic cues from the original HTML, not rendered-DOM measurements or ranking thresholds."]
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
