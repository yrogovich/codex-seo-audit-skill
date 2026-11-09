"""Shared helpers for the audit scripts: guarded HTTP fetching, robots.txt rules and sitemap parsing.

Standard library only. Not a command-line tool; imported by probe.py, crawl.py and analyze_crawl.py.
"""

from datetime import datetime, timezone
import http.client
import ipaddress
import re
import socket
import ssl
import time
from urllib.parse import urljoin, urlsplit, urlunsplit
import xml.etree.ElementTree as ElementTree
import zlib

USER_AGENT = "codex-seo-audit/1.0 (read-only SEO audit)"
ROBOTS_TOKEN = "codex-seo-audit"
ROBOTS_MAX_BYTES = 512 * 1024
SITEMAP_MAX_BYTES = 50 * 1024 * 1024
SITEMAP_MAX_URLS = 50000
CLOUD_METADATA = {"169.254.169.254", "fd00:ec2::254", "100.100.100.200"}
HTML_TYPES = ("text/html", "application/xhtml+xml")
ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
# Headers worth keeping as SEO evidence; cookies are never stored.
SEO_HEADERS = ("content-type", "content-length", "content-encoding", "content-language", "cache-control", "x-robots-tag",
               "link", "location", "last-modified", "etag", "vary", "server", "retry-after", "strict-transport-security")
LASTMOD = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?)?$")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- URLs -----------------------------------------------------------------------------------------------------------

def normalize_url(value, base=None):
    """Absolute http(s) URL without fragment, with lower-cased scheme/host and default port dropped; None if unusable."""
    try:
        text = value.strip()
        parts = urlsplit(urljoin(base, text) if base else text)
        port = parts.port
    except (ValueError, AttributeError):
        return None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or not parts.hostname or parts.username is not None or parts.password is not None:
        return None
    host = parts.hostname.rstrip(".").lower()
    netloc = "[%s]" % host if ":" in host else host
    if port and port != (443 if scheme == "https" else 80):
        netloc += ":%d" % port
    return urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))


def host_port(url):
    parts = urlsplit(url)
    return parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)


def origin_of(url):
    parts = urlsplit(url)
    return "%s://%s" % (parts.scheme, parts.netloc)


def local_scope(value):
    """(host, port) of a local origin given as a URL such as http://localhost:3000."""
    url = normalize_url(value)
    if not url:
        raise ValueError("Use an origin such as http://localhost:3000.")
    return host_port(url)


# --- Guarded fetching -----------------------------------------------------------------------------------------------

class BlockedTarget(Exception):
    pass


def resolve(host, port):
    return [info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]


def check_addresses(host, port, allow_local=frozenset()):
    """Resolve a target and refuse non-public addresses, except an explicitly allowed local origin.

    Cloud metadata and link-local addresses are always refused. The address returned is the one connected to,
    so a name cannot resolve differently between this check and the request."""
    addresses = list(dict.fromkeys(a.split("%")[0] for a in resolve(host, port)))
    if not addresses:
        raise BlockedTarget("no-address")
    for text in addresses:
        address = ipaddress.ip_address(text)
        if text in CLOUD_METADATA or address.is_link_local:
            raise BlockedTarget("metadata-or-link-local-address")
        if not address.is_global and (host, port) not in allow_local:
            raise BlockedTarget("non-public-address")
    return addresses


def connect_pinned(addresses, port, timeout):
    """Connect to the first reachable address from the validated list (an unreachable AAAA must not fail an IPv4 host)."""
    error = OSError("no address to connect to")
    for ip in addresses:
        try:
            return socket.create_connection((ip, port), timeout)
        except OSError as exc:
            error = exc
    raise error


class PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host, port, addresses, timeout):
        super().__init__(host, port, timeout=timeout)
        self.addresses = addresses

    def connect(self):
        self.sock = connect_pinned(self.addresses, self.port, self.timeout)


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, port, addresses, timeout):
        self.tls_context = ssl.create_default_context()
        super().__init__(host, port, timeout=timeout, context=self.tls_context)
        self.addresses = addresses

    def connect(self):
        raw = connect_pinned(self.addresses, self.port, self.timeout)
        self.sock = self.tls_context.wrap_socket(raw, server_hostname=self.host)


def open_connection(scheme, host, port, addresses, timeout):
    """Connection restricted to pre-validated addresses; replaced in tests."""
    return (PinnedHTTPSConnection if scheme == "https" else PinnedHTTPConnection)(host, port, addresses, timeout)


def read_capped(response, encoding, max_bytes):
    """Read and decompress (gzip/deflate) a body with a cap on decoded size: (bytes, truncated, decode_error)."""
    name = (encoding or "").strip().lower()
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS) if name in ("gzip", "x-gzip") else zlib.decompressobj() if name == "deflate" else None
    out, raw_total = bytearray(), 0
    while True:
        chunk = response.read(65536)
        if not chunk:
            return bytes(out), False, False
        raw_total += len(chunk)
        if decoder:
            try:
                chunk = decoder.decompress(chunk, max_bytes - len(out) + 1)
            except zlib.error:
                return bytes(out), False, True
        out += chunk
        if len(out) > max_bytes or raw_total > 4 * max_bytes:
            return bytes(out[:max_bytes]), True, False


def decode_body(body, content_type=None):
    candidates = []
    if body.startswith(b"\xef\xbb\xbf"):
        candidates.append("utf-8-sig")
    declared = re.search(r"charset=([\w.-]+)", content_type or "", re.I)
    if declared:
        candidates.append(declared.group(1))
    meta = re.search(rb"<meta[^>]+charset=[\"']?([\w.-]+)", body[:4096], re.I)
    if meta:
        candidates.append(meta.group(1).decode("ascii", "ignore"))
    for name in candidates + ["utf-8"]:
        try:
            return body.decode(name)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", errors="replace")


def one_request(url, method, headers, timeout, max_bytes, read_types, allow_local):
    parts = urlsplit(url)
    host, port = host_port(url)
    addresses = check_addresses(host, port, allow_local)
    connection = open_connection(parts.scheme, host, port, addresses, timeout)
    try:
        connection.request(method, (parts.path or "/") + ("?" + parts.query if parts.query else ""), headers=headers)
        try:  # the socket is closed once a "Connection: close" response arrives, so read the peer first
            ip = connection.sock.getpeername()[0]
        except (AttributeError, OSError):
            ip = addresses[0]
        response = connection.getresponse()
        collected = {}
        cookies = []
        for key, value in response.getheaders():
            key = key.lower()
            if key == "set-cookie":
                cookies.append(value.split("=", 1)[0].strip())
            else:
                collected[key] = collected[key] + ", " + value if key in collected else value
        if cookies:  # Cookie values can be session identifiers; keep names only.
            collected["set-cookie"] = "[names only: %s]" % ", ".join(cookies)
        content_type = collected.get("content-type", "")
        body, truncated, decode_error = b"", False, False
        wanted = read_types is None or content_type.lower().startswith(tuple(read_types))
        if method != "HEAD" and wanted and response.status not in (204, 304) and not 300 <= response.status < 400:
            body, truncated, decode_error = read_capped(response, collected.get("content-encoding"), max_bytes)
        return {"status": response.status, "reason": response.reason, "headers": collected, "body": body,
                "body_truncated": truncated, "body_decode_error": decode_error, "ip": ip}
    finally:
        connection.close()


def fetch(url, method="GET", follow=True, max_redirects=5, timeout=30, max_bytes=5 * 1024 * 1024, read_types=None,
          user_agent=USER_AGENT, allow_local=frozenset(), allowed_hosts=None, before_request=None):
    """One guarded request, optionally following redirects. Never raises; failures set result["error"].

    read_types: None reads any body, a tuple of content-type prefixes reads matching bodies, () reads none.
    allowed_hosts: when set, a redirect to another host is not followed (stopped="off-scope").
    before_request: called with each URL (redirect hops included) just before it is requested."""
    result = {"requested_url": url, "final_url": url, "status": None, "reason": None, "headers": {}, "redirect_chain": [],
              "redirect_to": None, "stopped": None, "body": b"", "body_truncated": False, "body_decode_error": False,
              "content_type": None, "ip": None, "elapsed_ms": None, "error": None, "error_detail": None}
    started = time.monotonic()
    headers = {"User-Agent": user_agent, "Accept": ACCEPT, "Accept-Encoding": "gzip, deflate", "Connection": "close"}
    current, seen = url, {url}
    for hop in range(max_redirects + 1):
        if before_request:
            before_request(current)
        try:
            response = one_request(current, method, headers, timeout, max_bytes, read_types, allow_local)
        except BlockedTarget as exc:
            result.update(error="blocked-target", error_detail=str(exc))
            break
        except socket.gaierror:
            result.update(error="dns-error")
            break
        except (socket.timeout, TimeoutError):
            result.update(error="timeout")
            break
        except (ssl.SSLError, ssl.CertificateError):
            result.update(error="tls-error")
            break
        except http.client.HTTPException as exc:
            result.update(error="protocol-error", error_detail=type(exc).__name__)
            break
        except OSError as exc:
            result.update(error="connection-error", error_detail=type(exc).__name__)
            break
        result.update(final_url=current, status=response["status"], reason=response["reason"], headers=response["headers"],
                      body=response["body"], body_truncated=response["body_truncated"],
                      body_decode_error=response["body_decode_error"], ip=response["ip"],
                      content_type=response["headers"].get("content-type"))
        location = response["headers"].get("location")
        if not 300 <= response["status"] < 400 or not location:
            break
        target = normalize_url(location, current)
        result["redirect_to"] = target
        if not follow:
            break
        if target is None:
            result["stopped"] = "bad-redirect"
            break
        result["redirect_chain"].append({"url": current, "status": response["status"], "location": target})
        if target in seen:
            result["stopped"] = "redirect-loop"
            break
        if allowed_hosts is not None and urlsplit(target).hostname not in allowed_hosts:
            result["stopped"] = "off-scope"
            break
        if hop == max_redirects:
            result["stopped"] = "too-many-redirects"
            break
        seen.add(target)
        current = target
    result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    return result


class Pacer:
    """Minimum gap between requests to one host."""

    def __init__(self, delay):
        self.delay, self.last = delay, None

    def wait(self):
        if self.last is not None:
            gap = self.delay - (time.monotonic() - self.last)
            if gap > 0:
                time.sleep(gap)
        self.last = time.monotonic()


class Client:
    """Paced, counted fetcher shared by probe.py and crawl.py: one request per delay and host, redirect hops included."""

    def __init__(self, delay=1.0, timeout=30, user_agent=USER_AGENT, allow_local=frozenset(), allowed_hosts=None):
        self.delay, self.timeout, self.user_agent = delay, timeout, user_agent
        self.allow_local, self.allowed_hosts = allow_local, allowed_hosts
        self.requests, self.pacers = 0, {}

    def before(self, url):
        pacer = self.pacers.setdefault(urlsplit(url).hostname, Pacer(self.delay))
        pacer.delay = self.delay  # a robots Crawl-delay can raise the pace limit mid-crawl
        pacer.wait()
        self.requests += 1

    def __call__(self, url, **kwargs):
        kwargs.setdefault("timeout", self.timeout)
        kwargs.setdefault("allowed_hosts", self.allowed_hosts)
        return fetch(url, user_agent=self.user_agent, allow_local=self.allow_local, before_request=self.before, **kwargs)


# --- robots.txt -----------------------------------------------------------------------------------------------------

def pattern_regex(pattern):
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    return re.compile("".join(".*" if char == "*" else re.escape(char) for char in body) + ("$" if anchored else ""))


class Robots:
    """robots.txt rules with RFC 9309 matching: longest rule wins, Allow wins ties, * and $ supported."""

    def __init__(self, text):
        self.groups, self.sitemaps = [], []
        current, collecting = None, False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            field, value = (part.strip() for part in line.split(":", 1))
            field = field.lower()
            if field == "user-agent":
                if current is None or not collecting:
                    current = {"agents": [], "rules": [], "delay": None}
                    self.groups.append(current)
                current["agents"].append(value.lower())
                collecting = True
            elif field in ("allow", "disallow") and current is not None:
                collecting = False
                if value:
                    current["rules"].append((field == "allow", value, pattern_regex(value)))
            elif field == "crawl-delay" and current is not None:
                collecting = False
                try:
                    current["delay"] = float(value)
                except ValueError:
                    pass
            elif field == "sitemap" and value:
                self.sitemaps.append(value)

    def group_agent(self, token):
        token = token.lower()
        names = {a for g in self.groups for a in g["agents"] if a != "*" and (token == a or token.startswith(a + "-"))}
        return max(names, key=len) if names else "*"

    def rules_for(self, token):
        agent = self.group_agent(token)
        return agent, [rule for g in self.groups if agent in g["agents"] for rule in g["rules"]]

    def allowed(self, target, token=ROBOTS_TOKEN):
        """(allowed, matched pattern or None, group agent) for a path with optional query."""
        agent, rules = self.rules_for(token)
        if target.split("?", 1)[0] == "/robots.txt":
            return True, None, agent
        best = None
        for allow, pattern, regex in rules:
            if regex.match(target) and (best is None or (len(pattern), allow) > (len(best[1]), best[0])):
                best = (allow, pattern)
        return (True, None, agent) if best is None else (best[0], best[1], agent)

    def crawl_delay(self, token=ROBOTS_TOKEN):
        agent = self.group_agent(token)
        delays = [g["delay"] for g in self.groups if agent in g["agents"] and g["delay"] is not None]
        return delays[0] if delays else None


def fetch_robots(origin, fetcher):
    """Fetch robots.txt via fetcher(url, **kwargs) and apply the standard status semantics.

    ok: parsed; not-found-allow-all: 4xx other than 429 (no restrictions); unreachable: 5xx, 429, network or
    scope failures, where compliant crawlers must not assume access."""
    result = fetcher(origin + "/robots.txt", max_bytes=ROBOTS_MAX_BYTES, read_types=None, max_redirects=5)
    status = result["status"]
    info = {"url": origin + "/robots.txt", "final_url": result["final_url"], "http_status": status, "error": result["error"],
            "bytes": len(result["body"]), "truncated": result["body_truncated"], "robots": None, "raw": result["body"],
            "looks_like_html": False}
    if result["error"] or result["stopped"] or status is None or status >= 500 or status == 429 or 300 <= status < 400:
        info["status"] = "unreachable"
    elif 400 <= status < 500:
        info["status"] = "not-found-allow-all"
    else:
        text = decode_body(result["body"], result["content_type"])
        info["status"] = "ok"
        info["looks_like_html"] = bool(re.match(r"\s*<(?:!doctype\s+html|html|head|body)", text, re.I))
        info["robots"] = Robots(text)
    return info


# --- sitemaps -------------------------------------------------------------------------------------------------------

def local_name(element):
    return element.tag.rsplit("}", 1)[-1].lower()


def parse_sitemap(body):
    """Classify and parse a sitemap body: {kind, urls: [(loc, lastmod)], children, errors, stats}.

    A DOCTYPE or entity declaration is refused rather than parsed; an HTML page is reported as such."""
    errors = []
    data = body
    if data[:2] == b"\x1f\x8b":
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            data = decoder.decompress(data, SITEMAP_MAX_BYTES)
        except zlib.error:
            return {"kind": "invalid", "urls": [], "children": [], "errors": ["gzip data could not be decoded"], "stats": {}}
        if decoder.unconsumed_tail:
            errors.append("exceeds 50 MiB uncompressed")
    head = data[:4096].lstrip()
    if re.match(rb"(?i)(<!doctype\s+html|<html[\s>])", head):
        return {"kind": "html-not-sitemap", "urls": [], "children": [], "errors": ["An HTML page was returned, not a sitemap"], "stats": {}}
    urls, children = [], []
    if not head.startswith(b"<"):
        kind = "text"
        urls = [(line.strip(), None) for line in data.decode("utf-8", errors="replace").splitlines() if line.strip().lower().startswith(("http://", "https://"))]
    else:
        if re.search(rb"(?i)<!doctype|<!entity", data[:8192]):
            return {"kind": "invalid", "urls": [], "children": [], "errors": ["DOCTYPE/ENTITY declaration refused; not parsed"], "stats": {}}
        try:
            root = ElementTree.fromstring(data)
        except ElementTree.ParseError:
            return {"kind": "invalid", "urls": [], "children": [], "errors": ["XML is not well formed"], "stats": {}}
        kind = local_name(root)
        if kind == "urlset":
            for node in root:
                if local_name(node) == "url":
                    fields = {local_name(c): (c.text or "").strip() for c in node}
                    urls.append((fields.get("loc", ""), fields.get("lastmod") or None))
        elif kind == "sitemapindex":
            for node in root:
                if local_name(node) == "sitemap":
                    loc = next(((c.text or "").strip() for c in node if local_name(c) == "loc"), "")
                    children.append(loc)
        elif kind == "rss":
            urls = [((c.text or "").strip(), None) for c in root.iter() if local_name(c) == "link" and (c.text or "").strip()]
        elif kind == "feed":
            urls = [(c.get("href", ""), None) for c in root.iter() if local_name(c) == "link" and c.get("href")]
        else:
            return {"kind": "invalid", "urls": [], "children": [], "errors": ["Root element <%s> is not a sitemap" % kind], "stats": {}}
    locs = [u for u, _ in urls]
    stats = {"url_count": len(urls), "duplicate_urls": len(locs) - len(set(locs)),
             "invalid_loc": sum(1 for u in locs if not normalize_url(u)),
             "over_2048_chars": sum(1 for u in locs if len(u) > 2048),
             "lastmod_present": sum(1 for _, m in urls if m), "lastmod_invalid": sum(1 for _, m in urls if m and not LASTMOD.match(m)),
             "child_count": len(children)}
    if len(urls) > SITEMAP_MAX_URLS:
        errors.append("more than 50,000 URLs in one sitemap")
    return {"kind": kind, "urls": urls, "children": children, "errors": errors, "stats": stats}


def discover_sitemaps(origin, declared, fetcher, allowed_hosts, max_files=25, max_depth=3):
    """Fetch robots-declared (else conventional) sitemaps, following indexes with a visited set and bounds.

    fetcher(url, **kwargs) performs one request (the caller counts and paces requests). Returns (records, urls):
    one record per sitemap file and a list of (loc, lastmod, sitemap_url) entries."""
    if declared:
        queue = [(u, "robots", 0) for u in declared[:16]]
    else:
        queue = [(origin + "/sitemap.xml", "conventional", 0), (origin + "/sitemap_index.xml", "conventional", 0)]
    records, entries, visited = [], [], set()
    while queue and len(records) < max_files:
        raw_url, source, depth = queue.pop(0)
        url = normalize_url(raw_url, origin + "/")
        record = {"url": url or raw_url, "source": source, "depth": depth, "http_status": None, "kind": None, "skipped": None,
                  "errors": [], "stats": {}, "bytes": 0, "body": b""}
        records.append(record)
        if url is None or url in visited:
            record["skipped"] = "invalid-or-duplicate"
            continue
        visited.add(url)
        if urlsplit(url).hostname not in allowed_hosts:
            record["skipped"] = "off-scope"
            continue
        result = fetcher(url, max_bytes=SITEMAP_MAX_BYTES, read_types=None, max_redirects=5)
        record.update(http_status=result["status"], bytes=len(result["body"]), body=result["body"])
        if result["error"] or result["status"] != 200:
            record["kind"] = "unavailable"
            record["errors"] = [result["error"] or "HTTP %s" % result["status"]]
            continue
        parsed = parse_sitemap(result["body"])
        record.update(kind=parsed["kind"], errors=parsed["errors"], stats=parsed["stats"])
        entries += [(loc, lastmod, url) for loc, lastmod in parsed["urls"]]
        if depth < max_depth:
            queue += [(child, "index", depth + 1) for child in parsed["children"]]
    if queue:
        records.append({"url": None, "source": "limit", "depth": None, "http_status": None, "kind": None, "skipped": "file-limit",
                        "errors": ["%d sitemap file(s) not followed (limit %d)" % (len(queue), max_files)], "stats": {}, "bytes": 0, "body": b""})
    return records, entries
