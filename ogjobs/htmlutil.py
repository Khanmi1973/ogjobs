"""Tiny HTML helpers so we never need BeautifulSoup/lxml.

Everything here is regex + html.parser based and is deliberately forgiving:
career sites emit broken markup all the time and we would rather return a
partial result than raise.
"""
import html as _html
import json
import re
import urllib.parse

_TAG = re.compile(r"<[^>]+>")
_SCRIPT_STYLE = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
_WS = re.compile(r"[ \t\r\f\v]+")
_MULTINL = re.compile(r"\n{3,}")


def strip_tags(fragment, keep_breaks=True):
    """Turn an HTML fragment into readable plain text."""
    if not fragment:
        return ""
    txt = _SCRIPT_STYLE.sub(" ", fragment)
    if keep_breaks:
        txt = re.sub(r"(?i)<br\s*/?>", "\n", txt)
        txt = re.sub(r"(?i)</(p|div|li|tr|h[1-6])>", "\n", txt)
        txt = re.sub(r"(?i)<li[^>]*>", "- ", txt)
    txt = _TAG.sub(" ", txt)
    # Some feeds double-encode ("&amp;#8211;"), so unescape until it settles.
    for _ in range(3):
        new = _html.unescape(txt)
        if new == txt:
            break
        txt = new
    txt = _WS.sub(" ", txt)
    txt = "\n".join(line.strip() for line in txt.split("\n"))
    return _MULTINL.sub("\n\n", txt).strip()


def text_of(html_doc):
    """Full-page visible text."""
    return strip_tags(html_doc)


def find_links(html_doc, base_url=None, pattern=None):
    """Return [(absolute_url, anchor_text)] optionally filtered by regex."""
    out = []
    seen = set()
    rx = re.compile(pattern, re.I) if pattern else None
    for m in re.finditer(r"<a\b[^>]*?href\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
                         html_doc or "", re.S | re.I):
        href, label = m.group(1).strip(), strip_tags(m.group(2), keep_breaks=False)
        if href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        url = urllib.parse.urljoin(base_url, href) if base_url else href
        url = url.split("#")[0]
        if rx and not rx.search(url):
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append((url, label))
    return out


def meta(html_doc, name):
    """Read a <meta name=...|property=...> content value."""
    for attr in ("name", "property"):
        m = re.search(r"<meta[^>]+%s\s*=\s*[\"']%s[\"'][^>]*content\s*=\s*[\"']([^\"']*)[\"']"
                      % (attr, re.escape(name)), html_doc or "", re.I)
        if m:
            return _html.unescape(m.group(1)).strip()
        m = re.search(r"<meta[^>]+content\s*=\s*[\"']([^\"']*)[\"'][^>]*%s\s*=\s*[\"']%s[\"']"
                      % (attr, re.escape(name)), html_doc or "", re.I)
        if m:
            return _html.unescape(m.group(1)).strip()
    return ""


def page_title(html_doc):
    m = re.search(r"<title[^>]*>(.*?)</title>", html_doc or "", re.S | re.I)
    return strip_tags(m.group(1), keep_breaks=False) if m else ""


def json_blobs(html_doc, type_filter="JobPosting"):
    """Yield JSON-LD objects of the given @type found anywhere in the page.

    Handles single objects, arrays and @graph containers. This is the single
    most portable way to read a modern career site: Google requires JobPosting
    structured data for jobs to appear in search, so most ATS platforms emit it.
    """
    found = []
    for m in re.finditer(
            r"<script[^>]+type\s*=\s*[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
            html_doc or "", re.S | re.I):
        raw = m.group(1).strip()
        raw = re.sub(r"^<!--|-->$", "", raw).strip()
        try:
            data = json.loads(raw)
        except Exception:
            # Some sites emit trailing commas or concatenated objects.
            try:
                data = json.loads(re.sub(r",\s*([}\]])", r"\1", raw))
            except Exception:
                continue
        _collect(data, type_filter, found)
    return found


def _collect(node, type_filter, out):
    if isinstance(node, list):
        for item in node:
            _collect(item, type_filter, out)
    elif isinstance(node, dict):
        if "@graph" in node:
            _collect(node["@graph"], type_filter, out)
        t = node.get("@type")
        types = t if isinstance(t, list) else [t]
        if not type_filter or type_filter in [x for x in types if x]:
            out.append(node)


def jsonld_location(node):
    """Flatten a JSON-LD jobLocation into 'City, Region, Country'."""
    loc = node.get("jobLocation")
    if isinstance(loc, list):
        parts = [jsonld_location({"jobLocation": x}) for x in loc]
        return " | ".join([p for p in parts if p])
    if isinstance(loc, str):
        return loc
    if not isinstance(loc, dict):
        if node.get("jobLocationType") == "TELECOMMUTE":
            return "Remote"
        return ""
    addr = loc.get("address") or {}
    if isinstance(addr, list):
        addr = addr[0] if addr else {}
    if isinstance(addr, str):
        return addr
    bits = [addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry")]
    flat = []
    for b in bits:
        if isinstance(b, dict):
            b = b.get("name") or b.get("addressCountry") or ""
        if b and str(b) not in flat:
            flat.append(str(b))
    return ", ".join(flat)


def jsonld_org(node):
    org = node.get("hiringOrganization")
    if isinstance(org, dict):
        return org.get("name") or ""
    if isinstance(org, str):
        return org
    return ""


def absolutize(base, href):
    return urllib.parse.urljoin(base, href) if href else ""
