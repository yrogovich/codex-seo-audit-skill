"""Real-socket checks of the network scripts against a server on 127.0.0.1.

These cover what the in-memory tests cannot: the pinned connection over a real socket, gzip on the wire and TLS
certificate verification. They are skipped when local ports cannot be bound (for example inside a sandbox) or
when no openssl is available for the TLS test.

Run: python3 -m unittest discover -s tests -v
"""

import csv
import gzip
import http.server
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
LOG = []


def page(title, body, head=""):
    return ("<html lang=en><head><title>%s</title>%s</head><body>%s</body></html>" % (title, head, body)).encode()


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        host = self.headers.get("Host")
        LOG.append((self.path, self.headers.get("User-Agent")))
        sitemap = '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">%s</urlset>' % "".join(
            "<url><loc>http://%s%s</loc></url>" % (host, p) for p in ("/", "/about", "/orphan"))
        routes = {
            "/robots.txt": (200, "text/plain", ("User-agent: *\nDisallow: /private/\nSitemap: http://%s/sitemap.xml\n" % host).encode(), {}),
            "/sitemap.xml": (200, "application/xml", sitemap.encode(), {}),
            "/": (200, "text/html", page("Home", '<a href="/about">About us</a><a href="/old">Old</a><a href="/private/x">Private</a><a href="/missing">Gone</a>' + "<p>filler</p>" * 300), {"gzip": True}),
            "/about": (200, "text/html", page("About", "<h1>About</h1>", '<link rel="canonical" href="http://%s/">' % host), {}),
            "/old": (301, "text/html", b"", {"Location": "/about"}),
            "/orphan": (200, "text/html", page("Orphan", "<h1>O</h1>"), {}),
        }
        status, content_type, body, extra = routes.get(self.path, (404, "text/html", page("Not found", ""), {}))
        if extra.pop("gzip", False) and "gzip" in (self.headers.get("Accept-Encoding") or ""):
            body, extra = gzip.compress(body), {"Content-Encoding": "gzip"}
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Set-Cookie", "session=TOPSECRETVALUE; Path=/")
        for key, value in extra.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True  # a handler stuck on an aborted TLS handshake must not hold the test process open


def stop(server):
    server.shutdown()
    server.server_close()


def serve(certificate=None):
    server = Server(("127.0.0.1", 0), Handler)
    if certificate:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(*certificate)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def script(name, *args, env=None):
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / name), *map(str, args)], capture_output=True, text=True, env={**os.environ, **(env or {})})
    return result.returncode, result.stdout, result.stderr


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.server = serve()
        except OSError as exc:
            raise unittest.SkipTest("cannot bind a local port here (%s)" % type(exc).__name__)
        cls.origin = "http://127.0.0.1:%d" % cls.server.server_address[1]
        cls.work = Path(tempfile.mkdtemp(prefix="seo-network-"))

    @classmethod
    def tearDownClass(cls):
        stop(cls.server)
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_a_loopback_target_is_refused_without_the_explicit_allowance(self):
        LOG.clear()
        code, _, _ = script("probe.py", self.origin + "/", "--output-dir", self.work / "refused")
        report = json.loads((self.work / "refused/probe.json").read_text())
        self.assertEqual((code, report["fetch"]["error"], LOG), (1, "blocked-target", []))

    def test_probe_crawl_and_analysis_over_real_connections(self):
        probe_dir, audit = self.work / "probe", self.work / "audit"
        code, _, err = script("probe.py", self.origin + "/", "--allow-local", self.origin, "--output-dir", probe_dir, "--delay", "0.2")
        self.assertEqual(code, 0, err)
        report = json.loads((probe_dir / "probe.json").read_text())
        self.assertEqual(report["fetch"]["status"], 200)
        self.assertTrue((probe_dir / "main.html").read_bytes().startswith(b"<html"))  # gzip decoded
        self.assertNotIn("TOPSECRETVALUE", (probe_dir / "probe.json").read_text())
        self.assertEqual((report["robots"]["status"], report["sitemaps"]["total_urls"]), ("ok", 3))

        LOG.clear()
        code, _, err = script("crawl.py", self.origin + "/", "--allow-local", self.origin, "--output-dir", audit / "evidence/crawl",
                              "--inventory", audit / "url-inventory.csv", "--delay", "0.2")
        self.assertEqual(code, 0, err)
        summary = json.loads((audit / "evidence/crawl/summary.json").read_text())
        with (audit / "url-inventory.csv").open(newline="") as stream:
            rows = {r["url"].replace(self.origin, ""): r for r in csv.DictReader(stream)}
        paths = [p for p, _ in LOG]
        self.assertEqual(summary["stop_reason"], "queue-exhausted")
        self.assertNotIn("/private/x", paths)
        self.assertEqual(rows["/private/x"]["fetch_status"], "blocked-by-robots")
        self.assertEqual((rows["/old"]["http_status"], rows["/old"]["final_url"].endswith("/about")), ("301", True))
        self.assertTrue(all((audit / r["evidence_ref"]).is_file() for r in rows.values() if r["evidence_ref"]))
        self.assertTrue(all((agent or "").startswith("codex-seo-audit/") for _, agent in LOG))
        self.assertEqual(summary["counts"]["requests"], len(LOG))

        code, out, err = script("analyze_crawl.py", audit / "evidence/crawl", "--inventory", audit / "url-inventory.csv")
        self.assertEqual(code, 0, err)
        self.assertIn("status.client_error", out)
        self.assertIn("links.orphan_candidates", out)


class TlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix="seo-tls-"))
        openssl = shutil.which("openssl")
        if not openssl:
            raise unittest.SkipTest("openssl is not available")
        cls.cert, key = cls.work / "cert.pem", cls.work / "key.pem"
        made = subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(cls.cert), "-days", "1",
                               "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost"], capture_output=True, text=True)
        if made.returncode:
            raise unittest.SkipTest("this openssl cannot create a test certificate")
        try:
            cls.server = serve((str(cls.cert), str(key)))
        except OSError as exc:
            raise unittest.SkipTest("cannot bind a local port here (%s)" % type(exc).__name__)
        cls.origin = "https://localhost:%d" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            stop(cls.server)
        shutil.rmtree(cls.work, ignore_errors=True)

    def probe(self, name, env=None):
        script("probe.py", self.origin + "/", "--allow-local", self.origin, "--no-site-checks", "--output-dir", self.work / name, env=env)
        return json.loads((self.work / name / "probe.json").read_text())["fetch"]

    def test_certificates_are_verified_and_the_pinned_connection_works_over_tls(self):
        self.assertEqual(self.probe("untrusted")["error"], "tls-error")
        trusted = self.probe("trusted", {"SSL_CERT_FILE": str(self.cert)})
        self.assertEqual((trusted["status"], trusted["error"]), (200, None))
        self.assertEqual(trusted["ip"], "127.0.0.1")  # the address actually connected to, after skipping an unreachable ::1


if __name__ == "__main__":
    unittest.main()
