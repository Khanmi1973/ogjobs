"""Local dashboard server.

Serves the same report as the static export, plus a "Scan now" button that
triggers a real scrape and streams progress back to the page.

Binds to 127.0.0.1 only. Nothing here is exposed to the network, and there is
no authentication because there is nothing to authenticate to: it is your own
machine talking to itself.
"""
import json
import os
import secrets
import socket
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import report
from .models import now_iso
from .pipeline import Runner

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ScanState:
    """Tracks the one scan that is allowed to run at a time."""

    def __init__(self):
        self.lock = threading.Lock()
        self.running = False
        self.started_at = ""
        self.finished_at = ""
        self.log = []
        self.current = ""
        self.index = 0
        self.total = 0
        self.found = 0
        self.matched = 0
        self.new = 0
        self.errors = []
        self.fresh = False

    def reset(self, fresh):
        self.running = True
        self.started_at = now_iso()
        self.finished_at = ""
        self.log = []
        self.current = "starting"
        self.index = self.total = 0
        self.found = self.matched = self.new = 0
        self.errors = []
        self.fresh = fresh

    def snapshot(self):
        return {
            "running": self.running,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "current": self.current,
            "index": self.index,
            "total": self.total,
            "found": self.found,
            "matched": self.matched,
            "new": self.new,
            "errors": self.errors[-6:],
            "fresh": self.fresh,
            "log": self.log[-40:],
        }


STATE = ScanState()


def _run_scan(only, fresh):
    def progress(ev):
        kind = ev.get("type")
        if kind == "start":
            STATE.total = ev.get("total", 0)
            STATE.log.append("Scanning %d source(s)%s"
                             % (STATE.total, " - ignoring cache" if fresh else ""))
        elif kind == "source":
            STATE.index = ev.get("index", 0)
            STATE.current = ev.get("company") or ev.get("id") or ""
            STATE.log.append("[%d/%d] %s ..." % (STATE.index, STATE.total, STATE.current))
        elif kind == "source_done":
            STATE.found += ev.get("scraped", 0)
            STATE.matched += ev.get("matched", 0)
            STATE.new += ev.get("new", 0)
            STATE.log.append("      %s: %d scraped, %d match, %d new (%.0fs)"
                             % (ev.get("company"), ev.get("scraped", 0),
                                ev.get("matched", 0), ev.get("new", 0),
                                ev.get("seconds", 0)))
        elif kind == "source_error":
            msg = "      %s FAILED: %s" % (ev.get("company"), ev.get("message"))
            STATE.errors.append(msg)
            STATE.log.append(msg)
        elif kind == "done":
            STATE.log.append("Finished: %d scraped, %d matched, %d new"
                             % (ev.get("found", 0), ev.get("kept", 0), ev.get("new", 0)))

    runner = None
    try:
        runner = Runner(verbose=True, fresh=fresh)
        runner.run(only=only or None, progress=progress)
        runner.report()
        STATE.log.append("Report rebuilt - refreshing the page.")
    except Exception as e:
        msg = "scan failed: %s: %s" % (type(e).__name__, e)
        STATE.errors.append(msg)
        STATE.log.append(msg)
    finally:
        if runner:
            try:
                runner.close()
            except Exception:
                pass
        STATE.running = False
        STATE.finished_at = now_iso()
        STATE.current = "done"


LOCAL_HOSTS = ("127.0.0.1", "::1", "localhost")


def lan_ip():
    """Best-effort local network address of this machine."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))   # no packets sent; just picks the route
        return s.getsockname()[0]
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"
    finally:
        s.close()


class Handler(BaseHTTPRequestHandler):
    server_version = "ogjobs"
    token = ""          # set by serve(); empty means localhost-only mode

    # ---- plumbing ------------------------------------------------------

    def log_message(self, fmt, *args):
        pass  # the scan itself already prints plenty

    def _authorized(self):
        """Localhost always passes. Anything else needs the access key.

        The key travels in ?k= on the first request and is then stored in a
        cookie, so the phone only types the long URL once.
        """
        host = (self.client_address[0] or "")
        if host in LOCAL_HOSTS:
            return True
        if not self.token:
            self._send(403, "text/plain",
                       b"This dashboard is running in localhost-only mode.\n"
                       b"Restart it with --host lan to allow your phone.")
            return False

        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        supplied = (query.get("k") or [""])[0]
        if not supplied:
            cookie = self.headers.get("Cookie") or ""
            for part in cookie.split(";"):
                name, _, value = part.strip().partition("=")
                if name == "ogjobs_key":
                    supplied = value
                    break
        if secrets.compare_digest(supplied, self.token):
            self._pending_cookie = supplied
            return True
        self._send(403, "text/plain",
                   b"Wrong or missing access key. Use the full link shown in "
                   b"the console window on your PC.")
        return False

    def _send(self, status, ctype, body, extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        pending = getattr(self, "_pending_cookie", "")
        if pending:
            self.send_header("Set-Cookie",
                             "ogjobs_key=%s; Path=/; Max-Age=86400; SameSite=Lax" % pending)
            self._pending_cookie = ""
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def _json(self, obj, status=200):
        self._send(status, "application/json; charset=utf-8",
                   json.dumps(obj).encode("utf-8"))

    # ---- routes --------------------------------------------------------

    def do_GET(self):
        if not self._authorized():
            return
        path = self.path.split("?")[0].rstrip("/") or "/"

        if path in ("/", "/index.html", "/jobs.html"):
            return self._dashboard()
        if path == "/api/status":
            return self._json(STATE.snapshot())
        if path == "/api/sources":
            return self._sources()
        if path in ("/jobs.csv", "/jobs.xml"):
            return self._file(path.lstrip("/"))
        self._send(404, "text/plain", b"not found")

    def do_POST(self):
        if not self._authorized():
            return
        if self.path.split("?")[0].rstrip("/") != "/api/scan":
            return self._send(404, "text/plain", b"not found")

        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            payload = {}

        with STATE.lock:
            if STATE.running:
                return self._json({"ok": False, "reason": "a scan is already running",
                                   "status": STATE.snapshot()}, 409)
            fresh = bool(payload.get("fresh", True))
            only = payload.get("sources") or None
            STATE.reset(fresh)

        threading.Thread(target=_run_scan, args=(only, fresh), daemon=True).start()
        self._json({"ok": True, "status": STATE.snapshot()})

    # ---- handlers ------------------------------------------------------

    def _dashboard(self):
        runner = Runner(verbose=False)
        try:
            rows = runner.store.query(limit=2000)
            last = runner.store.last_run_started()
            for r in rows:
                r["_new"] = bool(last and r.get("first_seen", "") >= last)
            meta = {"sources_run": len(runner.pick())}
            html = report.build_html(rows, meta, live=True)
        finally:
            runner.close()
        doc = ("<!doctype html><html><head><meta charset='utf-8'>"
               "<meta name='viewport' content='width=device-width,initial-scale=1'>"
               "</head><body>" + html + "</body></html>")
        self._send(200, "text/html; charset=utf-8", doc)

    def _sources(self):
        runner = Runner(verbose=False)
        try:
            out = [{"id": s.get("id"), "company": s.get("company", s.get("id")),
                    "adapter": s.get("adapter", "autodetect"),
                    "enabled": bool(s.get("enabled", True))}
                   for s in runner.sources]
        finally:
            runner.close()
        self._json({"sources": out})

    def _file(self, name):
        path = os.path.join(HERE, "data", "reports", name)
        if not os.path.exists(path):
            return self._send(404, "text/plain", b"not generated yet - run a scan")
        with open(path, "rb") as fh:
            body = fh.read()
        ctype = "text/csv" if name.endswith(".csv") else "application/rss+xml"
        self._send(200, ctype + "; charset=utf-8", body,
                   {"Content-Disposition": 'attachment; filename="%s"' % name})


def serve(port=8765, open_browser=True, host="local", token=None):
    """Run the dashboard.

    host="local" binds to 127.0.0.1 (this PC only).
    host="lan"   binds to every interface so a phone on the same Wi-Fi can
                 reach it; an access key is then required.
    """
    lan_mode = str(host).lower() in ("lan", "0.0.0.0", "all", "wifi")
    bind = "0.0.0.0" if lan_mode else "127.0.0.1"
    Handler.token = (token or secrets.token_urlsafe(9)) if lan_mode else ""

    httpd = ThreadingHTTPServer((bind, port), Handler)
    url = "http://127.0.0.1:%d/" % port

    print("=" * 66)
    print("  Oil & Gas Job Radar dashboard")
    print("=" * 66)
    if lan_mode:
        ip = lan_ip()
        phone_url = "http://%s:%d/?k=%s" % (ip, port, Handler.token)
        print("  On this PC : %s" % url)
        print()
        print("  ON YOUR PHONE - connect to the same Wi-Fi, then open:")
        print()
        print("     %s" % phone_url)
        print()
        print("  Type it once; the key is remembered for 24 hours.")
        print("  Anyone on this Wi-Fi who has that link can use the dashboard,")
        print("  so only run this on a network you trust, and stop it when done.")
        print()
        print("  If the phone cannot connect, Windows Firewall is blocking it.")
        print("  Run this ONCE in an Administrator PowerShell:")
        print('     netsh advfirewall firewall add rule name="ogjobs" '
              'dir=in action=allow protocol=TCP localport=%d' % port)
    else:
        print("  %s" % url)
        print("  This PC only. For your phone, restart with:  "
              "python -m ogjobs serve --host lan")
    print()
    print("  Press Ctrl+C to stop.")
    print("=" * 66)
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping...")
    finally:
        httpd.server_close()
        # Give a scan in flight a moment to finish its current write.
        if STATE.running:
            print("waiting for the running scan to stop...")
            for _ in range(20):
                if not STATE.running:
                    break
                time.sleep(0.5)
