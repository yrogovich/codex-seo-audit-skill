"""In-memory HTTP stand-in for tests of the network scripts.

It replaces the connection factory and DNS resolution in scripts/_common.py, so no sockets are opened and the
tests also run where local ports cannot be bound. It records every request for assertions.
"""

from pathlib import Path
import socket
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import _common as common  # noqa: E402


class FakeResponse:
    def __init__(self, status, headers, body):
        self.status, self.reason = status, "OK" if status < 400 else "Error"
        self.headers, self.body, self.position = headers, body, 0

    def getheaders(self):
        return list(self.headers)

    def read(self, size=-1):
        chunk = self.body[self.position:] if size < 0 else self.body[self.position:self.position + size]
        self.position += len(chunk)
        return chunk


class FakeConnection:
    def __init__(self, site, scheme, host, port):
        self.site, self.scheme, self.host, self.port = site, scheme, host, port
        self.path = None

    def request(self, method, path, headers=None):
        self.site.log.append({"method": method, "scheme": self.scheme, "host": self.host, "port": self.port,
                              "path": path, "headers": dict(headers or {})})
        self.path, self.method = path, method

    def getresponse(self):
        failure = self.site.failures.get((self.host, self.path.split("?")[0])) or self.site.failures.get((self.host, "*"))
        if failure:
            raise failure
        entry = (self.site.pages.get((self.scheme, self.host, self.path)) or self.site.pages.get(("*", self.host, self.path))
                 or self.site.pages.get(("*", self.host, self.path.split("?")[0])))
        if entry is None:
            entry = self.site.default or (404, [("Content-Type", "text/html")], b"<html><body>Not found</body></html>")
        if isinstance(entry, list):  # a sequence of responses; the last one repeats
            entry = entry.pop(0) if len(entry) > 1 else entry[0]
        return FakeResponse(*entry)

    def close(self):
        pass


class FakeSite:
    def __init__(self, address="93.184.216.34"):
        self.pages, self.failures, self.log, self.addresses, self.address = {}, {}, [], {}, address
        self.default = None  # (status, headers, body) served for unknown paths instead of a 404
        self.sleeps = []     # waits the code under test asked for; nothing actually sleeps

    def add(self, host, path, body="", status=200, headers=None, content_type="text/html; charset=utf-8", scheme="*"):
        pairs = [("Content-Type", content_type)] if content_type else []
        pairs += list((headers or {}).items()) if isinstance(headers, dict) else list(headers or [])
        self.pages[(scheme, host, path)] = (status, pairs, body.encode("utf-8") if isinstance(body, str) else body)
        return self

    def redirect(self, host, path, location, status=301, scheme="*"):
        return self.add(host, path, "", status, {"Location": location}, scheme=scheme)

    def sequence(self, host, path, responses, scheme="*"):
        """Serve (status, headers_dict, body) responses in order; the last repeats."""
        self.pages[(scheme, host, path)] = [(s, [("Content-Type", "text/html")] + list(h.items()), b.encode()) for s, h, b in responses]
        return self

    def fail(self, host, path, error):
        self.failures[(host, path)] = error
        return self

    def page(self, host, path, title="Page", body="", head="", **kwargs):
        html = "<html lang=en><head><title>%s</title>%s</head><body>%s</body></html>" % (title, head, body)
        return self.add(host, path, html, **kwargs)

    def requested(self, host=None):
        return [(r["method"], r["host"], r["path"]) for r in self.log if host is None or r["host"] == host]

    def open(self, scheme, host, port, addresses, timeout):
        self.last_addresses = addresses
        self.last_ip = addresses[0]
        return FakeConnection(self, scheme, host, port)

    def patches(self):
        return [patch.object(common, "open_connection", self.open),
                patch.object(common, "resolve", lambda host, port: self.addresses.get(host, [self.address])),
                patch.object(common.time, "sleep", self.sleeps.append)]


TIMEOUT = socket.timeout("timed out")
