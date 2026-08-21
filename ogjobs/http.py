"""Polite HTTP client built on the standard library only.

No third-party packages, no API keys. Handles gzip, cookies, retries,
per-host throttling, an on-disk cache and optional robots.txt compliance.
"""
import gzip
import hashlib
import json
import os
import random
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from http.cookiejar import CookieJar
from urllib.robotparser import RobotFileParser

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class Response:
    def __init__(self, url, status, text, headers=None, from_cache=False):
        self.url = url
        self.status = status
        self.text = text
        self.headers = headers or {}
        self.from_cache = from_cache

    @property
    def ok(self):
        return 200 <= self.status < 400

    def json(self):
        return json.loads(self.text)

    def __repr__(self):
        return "<Response %s %s %d chars>" % (self.status, self.url, len(self.text))


class Fetcher:
    """Shared, rate-limited, cached HTTP front-end for every adapter."""

    def __init__(self, cache_dir="data/cache", delay=1.5, timeout=30,
                 respect_robots=True, user_agent=DEFAULT_UA, verify_ssl=True,
                 cache_ttl=900, max_retries=2, verbose=True):
        self.cache_dir = cache_dir
        self.delay = delay
        self.timeout = timeout
        self.respect_robots = respect_robots
        self.user_agent = user_agent
        self.cache_ttl = cache_ttl
        self.max_retries = max_retries
        self.verbose = verbose
        # When true every request skips the cache, however long the caller's
        # requested TTL is. Used by "scan fresh" from the dashboard.
        self.force_fresh = False
        self._last_hit = {}
        self._robots = {}
        os.makedirs(cache_dir, exist_ok=True)

        ctx = ssl.create_default_context()
        if not verify_ssl:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ctx),
            urllib.request.HTTPCookieProcessor(CookieJar()),
        )

    # ---------------- public API ----------------

    def get(self, url, headers=None, cache_ttl=None,
            accept="text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8"):
        return self._request("GET", url, headers=headers, accept=accept, cache_ttl=cache_ttl)

    def get_json(self, url, headers=None, cache_ttl=None):
        r = self._request("GET", url, headers=headers,
                          accept="application/json, text/plain, */*", cache_ttl=cache_ttl)
        if not r.ok:
            return None
        try:
            return r.json()
        except Exception:
            return None

    def post_json(self, url, payload, headers=None, cache_ttl=None):
        body = json.dumps(payload).encode("utf-8")
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        h.update(headers or {})
        r = self._request("POST", url, body=body, headers=h,
                          accept="application/json", cache_ttl=cache_ttl)
        if not r.ok:
            return None
        try:
            return r.json()
        except Exception:
            return None

    # ---------------- internals ----------------

    def _cache_path(self, method, url, body):
        raw = method + "|" + url + "|" + (body.decode("utf-8", "ignore") if body else "")
        return os.path.join(self.cache_dir, hashlib.sha1(raw.encode("utf-8")).hexdigest() + ".json")

    def _cache_read(self, path, ttl):
        if ttl <= 0 or not os.path.exists(path):
            return None
        try:
            if time.time() - os.path.getmtime(path) > ttl:
                return None
            with open(path, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            return Response(d["url"], d["status"], d["text"], d.get("headers"), from_cache=True)
        except Exception:
            return None

    def _cache_write(self, path, resp):
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"url": resp.url, "status": resp.status,
                           "text": resp.text, "headers": resp.headers}, fh)
        except Exception:
            pass

    def _throttle(self, url):
        host = urllib.parse.urlsplit(url).netloc
        last = self._last_hit.get(host, 0)
        wait = self.delay + random.uniform(0, self.delay * 0.4) - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
        self._last_hit[host] = time.time()

    def allowed(self, url):
        """robots.txt check. An unreachable robots.txt is treated as permissive."""
        if not self.respect_robots:
            return True
        parts = urllib.parse.urlsplit(url)
        root = "%s://%s" % (parts.scheme, parts.netloc)
        if root not in self._robots:
            rp = RobotFileParser()
            rp.set_url(root + "/robots.txt")
            try:
                req = urllib.request.Request(root + "/robots.txt",
                                             headers={"User-Agent": self.user_agent})
                raw = self._opener.open(req, timeout=self.timeout).read().decode("utf-8", "ignore")
                rp.parse(raw.splitlines())
            except Exception:
                rp = None
            self._robots[root] = rp
        rp = self._robots[root]
        if rp is None:
            return True
        try:
            return rp.can_fetch(self.user_agent, url)
        except Exception:
            return True

    @staticmethod
    def _norm_headers(msg):
        """HTTPMessage lookups are case-insensitive; a plain dict is not.
        Lower-case every key so Content-Encoding is never missed."""
        return {k.lower(): v for k, v in msg.items()}

    def _decode(self, raw, headers):
        enc = (headers.get("content-encoding") or "").lower()
        if "gzip" in enc:
            try:
                raw = gzip.decompress(raw)
            except Exception:
                pass
        elif "deflate" in enc:
            try:
                raw = zlib.decompress(raw, -zlib.MAX_WBITS)
            except Exception:
                try:
                    raw = zlib.decompress(raw)
                except Exception:
                    pass
        charset = "utf-8"
        ctype = headers.get("content-type", "")
        if "charset=" in ctype:
            charset = ctype.split("charset=")[-1].split(";")[0].strip() or "utf-8"
        try:
            return raw.decode(charset, "ignore")
        except Exception:
            return raw.decode("utf-8", "ignore")

    def _request(self, method, url, body=None, headers=None, accept="*/*", cache_ttl=None):
        ttl = 0 if self.force_fresh else (self.cache_ttl if cache_ttl is None else cache_ttl)
        cpath = self._cache_path(method, url, body)
        cached = self._cache_read(cpath, ttl)
        if cached:
            return cached

        if not self.allowed(url):
            if self.verbose:
                print("      [robots] disallowed: %s" % url)
            return Response(url, 999, "", {})

        h = {"User-Agent": self.user_agent, "Accept": accept,
             "Accept-Language": "en-US,en;q=0.9", "Accept-Encoding": "gzip, deflate",
             "Connection": "close"}
        h.update(headers or {})

        last_err = ""
        for attempt in range(self.max_retries + 1):
            self._throttle(url)
            try:
                req = urllib.request.Request(url, data=body, headers=h, method=method)
                raw_resp = self._opener.open(req, timeout=self.timeout)
                resp_headers = self._norm_headers(raw_resp.headers)
                text = self._decode(raw_resp.read(), resp_headers)
                out = Response(raw_resp.geturl(), raw_resp.status, text, resp_headers)
                self._cache_write(cpath, out)
                return out
            except urllib.error.HTTPError as e:
                try:
                    resp_headers = self._norm_headers(e.headers)
                    text = self._decode(e.read(), resp_headers)
                except Exception:
                    resp_headers, text = {}, ""
                if e.code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    time.sleep(2 ** attempt * 2)
                    last_err = "HTTP %d" % e.code
                    continue
                return Response(url, e.code, text, resp_headers)
            except Exception as e:
                last_err = "%s: %s" % (type(e).__name__, e)
                if attempt < self.max_retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
        if self.verbose:
            print("      [net] failed %s (%s)" % (url, last_err))
        return Response(url, 0, "", {})
