"""Source adapters.

Every adapter is a function ``fn(fetcher, cfg) -> list[Job]``. They all rely on
public, unauthenticated endpoints that career sites expose to their own front
end - no API keys, no paid aggregator, no scraping service.

The important one is ``autodetect``: give it any careers URL and it works out
which applicant tracking system (ATS) sits behind it and delegates to the right
adapter. That is what lets this run against companies whose job board we have
never seen before.
"""
import json
import re
import urllib.parse

from . import htmlutil as H
from .models import Job

REGISTRY = {}


def adapter(name):
    def deco(fn):
        REGISTRY[name] = fn
        return fn
    return deco


def _origin(url):
    p = urllib.parse.urlsplit(url)
    return "%s://%s" % (p.scheme, p.netloc)


def _mk(cfg, **kw):
    j = Job(source=cfg.get("id", ""), company=cfg.get("company", cfg.get("id", "")), **kw)
    return j.normalise()


def _paged_url(template, cfg, page):
    """Expand {page} and {offset} tokens in a listing URL.

    {page}   -> page number, starting at cfg['page_start'] (default 1)
    {offset} -> page * cfg['page_step'] (default 25), for offset-style boards
    """
    start = int(cfg.get("page_start", 1))
    step = int(cfg.get("page_step", 25))
    return (template.replace("{page}", str(page + start))
                    .replace("{offset}", str(page * step)))


def _is_paged(template):
    return "{page}" in template or "{offset}" in template


def _listify(cfg, *keys):
    for k in keys:
        v = cfg.get(k)
        if isinstance(v, list) and v:
            return v
        if isinstance(v, str) and v:
            return [v]
    return []


# --------------------------------------------------------------------------
# Workday  (Shell, many majors)  - POST /wday/cxs/{tenant}/{site}/jobs
# --------------------------------------------------------------------------
@adapter("workday")
def workday(f, cfg):
    host = cfg["host"].replace("https://", "").replace("http://", "").strip("/")
    tenant = cfg["tenant"]
    site = cfg["site"]
    lang = cfg.get("lang", "en-US")
    api = "https://%s/wday/cxs/%s/%s/jobs" % (host, tenant, site)
    public = "https://%s/%s/%s" % (host, lang, site)
    page_size = int(cfg.get("page_size", 20))
    max_pages = int(cfg.get("max_pages", 15))
    queries = _listify(cfg, "queries") or [""]

    jobs, seen = [], set()
    for q in queries:
        offset, total = 0, None
        for _ in range(max_pages):
            data = f.post_json(api, {"appliedFacets": cfg.get("facets", {}),
                                     "limit": page_size, "offset": offset, "searchText": q})
            if not data:
                break
            postings = data.get("jobPostings") or []
            if not postings:
                break
            # Workday reports the grand total on the first page only; later
            # pages come back with total=0, so remember it once.
            if total is None:
                total = int(data.get("total") or 0)
            for p in postings:
                path = p.get("externalPath") or ""
                url = public + path if path.startswith("/") else (path or public)
                if url in seen:
                    continue
                seen.add(url)
                bullets = " ".join([str(b) for b in (p.get("bulletFields") or [])])
                jobs.append(_mk(cfg, title=p.get("title", ""),
                                location=p.get("locationsText", ""),
                                url=url, posted=p.get("postedOn", ""),
                                external_id=bullets.strip(),
                                description=""))
            offset += page_size
            if len(postings) < page_size or (total and offset >= total):
                break

    if cfg.get("detail"):
        limit = int(cfg.get("max_details", 40))
        for j in jobs[:limit]:
            path = j.url.replace(public, "")
            d = f.get_json("https://%s/wday/cxs/%s/%s%s" % (host, tenant, site, path),
                           cache_ttl=86400)
            info = (d or {}).get("jobPostingInfo") or {}
            if info:
                j.description = H.strip_tags(info.get("jobDescription", ""))
                j.location = j.location or info.get("location", "")
                j.posted = j.posted or info.get("startDate", "")
                j.external_id = info.get("jobReqId") or j.external_id
                j.normalise()
    return jobs


def _sf_slug_location(href, title):
    """Recover the location from a SuccessFactors job URL.

    SuccessFactors builds them as /job/<Location>-<Title>/<id>/. The newer
    "job tile" layout (Subsea 7) has no location column at all, so the slug is
    the only source. Taking the first hyphen-separated token turns "Kuala
    Lumpur" into "Kuala" and "Port Harcourt" into "Port", so instead strip the
    slugified title off the end and keep whatever precedes it.
    """
    if "/job/" not in (href or ""):
        return ""
    seg = urllib.parse.unquote(href.split("/job/")[-1]).split("/")[0]
    slug = re.sub(r"[^A-Za-z0-9]+", "-", seg).strip("-")
    tslug = re.sub(r"[^A-Za-z0-9]+", "-", title or "").strip("-")
    if tslug and slug.lower().endswith(tslug.lower()):
        loc = slug[: len(slug) - len(tslug)].strip("-")
        if loc:
            return loc.replace("-", " ").strip()
    return seg.split("-")[0]


# --------------------------------------------------------------------------
# SAP SuccessFactors career site (ExxonMobil and many others)
# --------------------------------------------------------------------------
@adapter("successfactors")
def successfactors(f, cfg):
    base = cfg["base"].rstrip("/")
    page_size = int(cfg.get("page_size", 25))
    max_pages = int(cfg.get("max_pages", 8))
    queries = _listify(cfg, "queries") or [""]
    jobs, seen = [], set()

    for q in queries:
        for page in range(max_pages):
            url = ("%s/search/?q=%s&sortColumn=referencedate&sortDirection=desc&startrow=%d"
                   % (base, urllib.parse.quote(q), page * page_size))
            r = f.get(url)
            if not r.ok or not r.text:
                break
            rows = re.split(r"<tr[^>]*class=\"[^\"]*data-row", r.text)[1:]
            if not rows:
                rows = re.split(r"<li[^>]*class=\"[^\"]*job", r.text)[1:]
            found = 0
            for row in rows:
                m = re.search(r"<a[^>]+class=\"[^\"]*jobTitle-link[^\"]*\"[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>",
                              row, re.S | re.I)
                if not m:
                    m = re.search(r"<a[^>]+href=\"(/job/[^\"]+)\"[^>]*>(.*?)</a>", row, re.S | re.I)
                if not m:
                    continue
                href, title = m.group(1), H.strip_tags(m.group(2), keep_breaks=False)
                url_abs = urllib.parse.urljoin(base + "/", href)
                if url_abs in seen or not title:
                    continue
                seen.add(url_abs)
                loc = re.search(r"class=\"[^\"]*jobLocation[^\"]*\"[^>]*>(.*?)</", row, re.S | re.I)
                date = re.search(r"class=\"[^\"]*jobDate[^\"]*\"[^>]*>(.*?)</", row, re.S | re.I)
                dept = re.search(r"class=\"[^\"]*jobDepartment[^\"]*\"[^>]*>(.*?)</", row, re.S | re.I)
                # SF encodes the location in the slug too: /job/Luanda-Engineer-.../123/
                slug_loc = _sf_slug_location(href, title)
                jobs.append(_mk(cfg, title=title, url=url_abs,
                                location=H.strip_tags(loc.group(1), False) if loc else slug_loc,
                                posted=H.strip_tags(date.group(1), False) if date else "",
                                department=H.strip_tags(dept.group(1), False) if dept else ""))
                found += 1
            if found < page_size:
                break
    _enrich_details(f, cfg, jobs)
    return jobs


# --------------------------------------------------------------------------
# Free public JSON boards
# --------------------------------------------------------------------------
@adapter("greenhouse")
def greenhouse(f, cfg):
    token = cfg["token"]
    d = f.get_json("https://boards-api.greenhouse.io/v1/boards/%s/jobs?content=true" % token)
    out = []
    for j in (d or {}).get("jobs", []):
        out.append(_mk(cfg, title=j.get("title", ""),
                       location=(j.get("location") or {}).get("name", ""),
                       url=j.get("absolute_url", ""), posted=j.get("updated_at", ""),
                       external_id=str(j.get("id", "")),
                       description=H.strip_tags(j.get("content", ""))))
    return out


@adapter("lever")
def lever(f, cfg):
    d = f.get_json("https://api.lever.co/v0/postings/%s?mode=json" % cfg["token"])
    out = []
    for j in (d or []):
        cat = j.get("categories") or {}
        out.append(_mk(cfg, title=j.get("text", ""), location=cat.get("location", ""),
                       department=cat.get("team", ""), contract_type=cat.get("commitment", ""),
                       url=j.get("hostedUrl", ""), posted=j.get("createdAt", ""),
                       external_id=j.get("id", ""),
                       description=j.get("descriptionPlain", "")))
    return out


@adapter("smartrecruiters")
def smartrecruiters(f, cfg):
    company = cfg["company_id"]
    out, offset = [], 0
    for _ in range(int(cfg.get("max_pages", 10))):
        d = f.get_json("https://api.smartrecruiters.com/v1/companies/%s/postings?limit=100&offset=%d"
                       % (company, offset))
        items = (d or {}).get("content") or []
        if not items:
            break
        for j in items:
            loc = j.get("location") or {}
            parts = [loc.get("city"), loc.get("region"), loc.get("country")]
            out.append(_mk(cfg, title=j.get("name", ""),
                           location=", ".join([p for p in parts if p]),
                           url="https://jobs.smartrecruiters.com/%s/%s" % (company, j.get("id", "")),
                           posted=j.get("releasedDate", ""), external_id=str(j.get("id", "")),
                           department=(j.get("department") or {}).get("label", "")))
        offset += 100
        if offset >= int((d or {}).get("totalFound") or 0):
            break
    return out


@adapter("recruitee")
def recruitee(f, cfg):
    d = f.get_json("https://%s.recruitee.com/api/offers/" % cfg["company_id"])
    out = []
    for j in (d or {}).get("offers", []):
        parts = [j.get("city"), j.get("country")]
        out.append(_mk(cfg, title=j.get("title", ""),
                       location=", ".join([p for p in parts if p]),
                       url=j.get("careers_url") or j.get("careers_apply_url", ""),
                       posted=j.get("published_at", ""), department=j.get("department", ""),
                       contract_type=j.get("employment_type", ""),
                       external_id=str(j.get("id", "")),
                       description=H.strip_tags(j.get("description", ""))))
    return out


@adapter("workable")
def workable(f, cfg):
    acct = cfg["company_id"]
    d = f.get_json("https://apply.workable.com/api/v1/widget/accounts/%s?details=true" % acct)
    out = []
    for j in (d or {}).get("jobs", []):
        out.append(_mk(cfg, title=j.get("title", ""), location=j.get("location", ""),
                       url=j.get("url") or j.get("application_url", ""),
                       posted=j.get("published_on", ""), department=j.get("department", ""),
                       external_id=j.get("shortcode", ""),
                       description=H.strip_tags(j.get("description", ""))))
    return out


@adapter("ashby")
def ashby(f, cfg):
    d = f.get_json("https://api.ashbyhq.com/posting-api/job-board/%s" % cfg["company_id"])
    out = []
    for j in (d or {}).get("jobs", []):
        out.append(_mk(cfg, title=j.get("title", ""), location=j.get("location", ""),
                       url=j.get("jobUrl", ""), posted=j.get("publishedAt", ""),
                       department=j.get("department", ""), contract_type=j.get("employmentType", ""),
                       external_id=j.get("id", ""),
                       description=H.strip_tags(j.get("descriptionHtml", ""))))
    return out


def _lang(value, default=""):
    """BeeHire stores translatable fields as {"0": "English", "1": "French"}."""
    if isinstance(value, dict):
        for key in ("0", "en", "en_US"):
            if value.get(key):
                return value[key]
        for v in value.values():
            if isinstance(v, str) and v.strip():
                return v
        return default
    return value if isinstance(value, str) else default


@adapter("beehire")
def beehire(f, cfg):
    """BeeHire career pages (used by Aldelia among others).

    The visible page is a JavaScript app, but it feeds from one public,
    unauthenticated JSON endpoint that returns every open campaign at once.
    """
    company = cfg["company_id"]
    d = f.get_json("https://app.beehire.com/users/getPublicCampaigns/%s" % company)
    if not d:
        return []
    items = d if isinstance(d, list) else None
    if items is None:
        items = d.get("campaigns")
    if items is None:
        items = next((v for v in d.values() if isinstance(v, list) and v), [])

    out = []
    for j in items:
        if not isinstance(j, dict):
            continue
        loc = j.get("location") or {}
        if isinstance(loc, dict):
            bits = [loc.get("name"), loc.get("city"), loc.get("country")]
            seen, flat = set(), []
            for b in bits:
                if b and b not in seen:
                    seen.add(b)
                    flat.append(str(b))
            loc_str = ", ".join(flat)
        else:
            loc_str = str(loc)
        contract = ((j.get("details") or {}).get("contract") or {}).get("type", "")
        out.append(_mk(cfg, title=_lang(j.get("title")),
                       location=loc_str,
                       url=j.get("inviteLink") or
                           "https://app.beehire.com/career/%s" % company,
                       external_id=str(j.get("_id", "")),
                       contract_type=str(contract).replace("contractType_", ""),
                       description=H.strip_tags(_lang(j.get("description")))))
    return out


def _orc_requisitions(container):
    """Pull the job list out of an Oracle response.

    Tenants differ: some return requisitionList as a plain array, others wrap
    it in a paging object {"items": [...], "count": n}.
    """
    rl = container.get("requisitionList")
    if isinstance(rl, dict):
        rl = rl.get("items")
    if not isinstance(rl, list):
        return []
    return [r for r in rl if isinstance(r, dict)]


@adapter("oracle_orc")
def oracle_orc(f, cfg):
    """Oracle Recruiting Cloud - Eni, Wood, and many Gulf national oil companies."""
    host = cfg["host"].replace("https://", "").strip("/")
    site = cfg["site"]
    page_size = int(cfg.get("page_size", 100))
    out, offset = [], 0
    for _ in range(int(cfg.get("max_pages", 8))):
        url = ("https://%s/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
               "?onlyData=true&expand=requisitionList"
               "&finder=findReqs;siteNumber=%s,limit=%d,offset=%d,sortBy=POSTING_DATES_DESC"
               % (host, site, page_size, offset))
        d = f.get_json(url, headers={"REST-Framework-Version": "4"})
        items = (d or {}).get("items") or []
        # Some tenants answer with an error payload whose "items" are strings,
        # so never assume the first element is the requisition container.
        first = items[0] if items and isinstance(items[0], dict) else {}
        reqs = _orc_requisitions(first)
        if not reqs:
            break
        for j in reqs:
            out.append(_mk(cfg, title=j.get("Title", ""),
                           location=j.get("PrimaryLocation") or j.get("Location", ""),
                           url="https://%s/hcmUI/CandidateExperience/en/sites/%s/job/%s"
                               % (host, site, j.get("Id", "")),
                           posted=j.get("PostedDate", ""), external_id=str(j.get("Id", "")),
                           contract_type=j.get("JobFunction", "")))
        offset += page_size
        if len(reqs) < page_size or offset >= int(first.get("TotalJobsCount") or 0):
            break
    return out


def _phenom_ddo(html_doc):
    """Pull the phApp.ddo JSON blob out of a Phenom People career page."""
    i = (html_doc or "").find("phApp.ddo")
    if i < 0:
        return None
    start = html_doc.find("{", i)
    if start < 0:
        return None
    depth = 0
    for k in range(start, len(html_doc)):
        ch = html_doc[k]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html_doc[start:k + 1])
                except ValueError:
                    # Only a malformed blob is expected here. Anything else is
                    # a real bug and should not be silently swallowed.
                    return None
    return None


@adapter("phenom")
def phenom(f, cfg):
    """Phenom People career sites (ADNOC, KBR and many large employers).

    The search page ships its first result set inside a phApp.ddo JSON blob,
    and ?from=N pages through the rest server side - no private API needed.
    """
    base = cfg["base"].rstrip("/")
    path = cfg.get("search_path", "/us/en/search-results")
    page_size = int(cfg.get("page_size", 10))
    max_pages = int(cfg.get("max_pages", 20))
    queries = _listify(cfg, "queries") or [""]

    out, seen = [], set()
    for q in queries:
        total = None
        for page in range(max_pages):
            offset = page * page_size
            url = "%s%s?from=%d&s=1" % (base, path, offset)
            if q:
                url += "&keywords=" + urllib.parse.quote(q)
            r = f.get(url)
            if not r.ok:
                break
            ddo = _phenom_ddo(r.text)
            block = (ddo or {}).get("eagerLoadRefineSearch") or {}
            jobs = (block.get("data") or {}).get("jobs") or []
            if not jobs:
                break
            if total is None:
                total = int(block.get("totalHits") or 0)
            for j in jobs:
                jid = str(j.get("jobSeqNo") or j.get("jobId") or "")
                if jid in seen:
                    continue
                seen.add(jid)
                loc = (j.get("cityStateCountry") or j.get("location")
                       or ", ".join([x for x in (j.get("city"), j.get("state"),
                                                 j.get("country")) if x]))
                url_job = j.get("applyUrl") or j.get("jobUrl") or ""
                if not url_job:
                    slug = re.sub(r"[^a-z0-9]+", "-", (j.get("title") or "").lower()).strip("-")
                    url_job = "%s/us/en/job/%s/%s" % (base, jid, slug)
                out.append(_mk(cfg, title=j.get("title", ""), location=loc,
                               url=urllib.parse.urljoin(base, url_job),
                               posted=j.get("postedDate") or j.get("dateCreated", ""),
                               external_id=str(j.get("reqId") or jid),
                               department=j.get("category") or "",
                               contract_type=j.get("type") or "",
                               description=j.get("descriptionTeaser") or ""))
            offset += page_size
            if len(jobs) < page_size or (total and offset >= total):
                break
    return out


@adapter("ncore")
def ncore(f, cfg):
    """nCore-hosted boards (Saipem).

    The page is a JavaScript shell - it even carries a stale "positions under
    maintenance" notice - but it loads one static JSON file holding every
    vacancy, which is far better than scraping the rendered cards.
    """
    url = cfg.get("feed") or (cfg["base"].rstrip("/") + "/positions_saipem.json")
    d = f.get_json(url)
    groups = ((d or {}).get("data") or {}).get("Positions") or {}
    out = []
    for company, jobs in groups.items():
        if not isinstance(jobs, list):
            continue
        for j in jobs:
            if not isinstance(j, dict) or not j.get("title"):
                continue
            out.append(_mk(cfg, title=j.get("title", ""),
                           location=j.get("countryText") or j.get("country", ""),
                           url=j.get("url", ""),
                           posted=j.get("orderDate", ""),
                           department=j.get("sectorText", ""),
                           external_id=str(j.get("url", "")).rstrip("/").split("/")[-1],
                           description=H.strip_tags(j.get("description", ""))))
            # The hiring entity varies per job; keep it when the config has
            # not pinned a display name.
            if not cfg.get("company"):
                out[-1].company = j.get("root-node") or company
    return out


@adapter("zoho_recruit")
def zoho_recruit(f, cfg):
    """Zoho Recruit career sites (Q-Sourcing and many African agencies).

    The visible list is drawn by JavaScript, but the same data is already in
    the served HTML as an HTML-escaped JSON array, so one request gets
    everything without touching a private API.
    """
    base = cfg.get("base") or "https://%s.zohorecruit.com" % cfg["company_id"]
    base = base.rstrip("/")
    path = cfg.get("path", "/jobs/Careers/")
    r = f.get(base + path)
    if not r.ok:
        return []

    raw = html_unescape_all(r.text)
    out, seen = [], set()
    for m in re.finditer(r"\{[^{}]*\"Job_Opening_Name\"[^{}]*\}", raw):
        try:
            j = json.loads(m.group(0))
        except ValueError:
            continue
        jid = str(j.get("id") or "")
        title = j.get("Posting_Title") or j.get("Job_Opening_Name") or ""
        if not jid or not title or jid in seen:
            continue
        if j.get("Publish") is False:
            continue
        seen.add(jid)
        loc = ", ".join([x for x in (j.get("City"), j.get("State"), j.get("Country")) if x])
        slug = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-")
        out.append(_mk(cfg, title=title, location=loc,
                       url="%s%s%s/%s" % (base, path, jid, slug),
                       external_id=jid,
                       contract_type=j.get("Job_Type") or "",
                       department=j.get("Industry") or j.get("Department_Name") or "",
                       posted=j.get("Date_Opened") or ""))
    _enrich_details(f, cfg, out)
    return out


def html_unescape_all(text):
    """Undo the numeric entity escaping Zoho applies to its embedded JSON."""
    import html as _h
    prev = text
    for _ in range(2):
        cur = _h.unescape(prev)
        if cur == prev:
            break
        prev = cur
    return prev


@adapter("vennture")
def vennture(f, cfg):
    """Vennture-built recruiter sites (NES Fircroft, Kintec Global, others).

    The job-search listing is drawn by JavaScript, but every job detail page is
    pre-rendered server side and the site publishes a sitemap at
    /api/sitemap.xml. So: take the URLs from the sitemap, read each page.

    Note the sitemap keeps expired jobs; those return a near-empty shell and
    are skipped rather than stored as blank rows.
    """
    sitemap_url = cfg.get("sitemap") or (_origin(cfg.get("careers_url", "")) + "/api/sitemap.xml")
    r = f.get(sitemap_url, accept="application/xml, text/xml, */*")
    if not r.ok:
        return []
    keep = re.compile(cfg.get("url_pattern", r"/job/"), re.I)
    skip = re.compile(cfg["exclude_pattern"], re.I) if cfg.get("exclude_pattern") else None

    # Read <lastmod> alongside each URL so that when max_details caps the run we
    # spend it on the newest postings rather than an arbitrary slice.
    entries, seen = [], set()
    for block in re.findall(r"<url>(.*?)</url>", r.text, re.S | re.I):
        loc = re.search(r"<loc>\s*(.*?)\s*</loc>", block, re.S)
        if not loc:
            continue
        u = loc.group(1)
        if not keep.search(u) or (skip and skip.search(u)) or u in seen:
            continue
        seen.add(u)
        mod = re.search(r"<lastmod>\s*(.*?)\s*</lastmod>", block, re.S)
        entries.append((mod.group(1) if mod else "", u))
    entries.sort(key=lambda e: e[0], reverse=True)
    picked = [u for _, u in entries]

    out = []
    for u in picked[:int(cfg.get("max_details", 120))]:
        d = f.get(u, cache_ttl=cfg.get("detail_ttl", 86400))
        if not d.ok or len(d.text) < 2000:      # expired posting
            continue
        title = H.meta(d.text, "og:title") or ""
        if not title:
            m = re.search(r"<h1[^>]*>(.*?)</h1>", d.text, re.S | re.I)
            title = H.strip_tags(m.group(1), keep_breaks=False) if m else ""
        if not title:
            continue
        loc = re.search(r"icon location\"[^>]*></i>\s*<span[^>]*>(.*?)</span>", d.text, re.S | re.I)
        ref = re.search(r"class=\"job-ref\"[^>]*>(.*?)</span>", d.text, re.S | re.I)
        posted = re.search(r"Posted:\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})", d.text)
        jtype = re.search(r"class=\"job_type\"[^>]*>(.*?)</span>", d.text, re.S | re.I)
        sector = re.search(r"class=\"media job_sector\"[^>]*>(.*?)</div>", d.text, re.S | re.I)
        posted_iso = ""
        if posted:                               # site writes DD/MM/YYYY
            dd, mm, yy = posted.group(1).split("/")
            posted_iso = "%s-%02d-%02d" % (yy, int(mm), int(dd))
        out.append(_mk(cfg, title=title,
                       url=u,
                       location=H.strip_tags(loc.group(1), False) if loc else "",
                       external_id=H.strip_tags(ref.group(1), False) if ref else "",
                       posted=posted_iso,
                       contract_type=H.strip_tags(jtype.group(1), False) if jtype else "",
                       department=H.strip_tags(sector.group(1), False) if sector else "",
                       description=H.meta(d.text, "og:description")))
    return out


@adapter("nicoka")
def nicoka(f, cfg):
    """Nicoka-hosted career sites (SEAOWL Group and others).

    The whole vacancy list is server-rendered into one page, but the job links
    are bare id-hash paths with no 'job' segment, so the generic link harvester
    walks straight past them. Parsing the cards directly also gives us the
    location for free, without fetching every detail page.
    """
    out, seen = [], set()
    for url in _listify(cfg, "urls", "url", "careers_url"):
        r = f.get(url)
        if not r.ok:
            continue
        blocks = re.findall(r"<div class=\"job[ \"][^>]*>.*?(?=<div class=\"job[ \"]|</section>)",
                            r.text, re.S | re.I)
        for b in blocks:
            m = re.search(r"class=\"job-title\"[^>]*>\s*<a[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>",
                          b, re.S | re.I)
            if not m:
                continue
            job_url = urllib.parse.urljoin(r.url, m.group(1).strip().rstrip('"'))
            title = H.strip_tags(m.group(2), keep_breaks=False)
            if not title or job_url in seen:
                continue
            seen.add(job_url)
            loc = re.search(r"job-info-location[^>]*>(.*?)</li>", b, re.S | re.I)
            country = re.search(r"job-info-country[^>]*>(.*?)</li>", b, re.S | re.I)
            parts = [H.strip_tags(x.group(1), keep_breaks=False).strip(" ,")
                     for x in (loc, country) if x]
            # The location line often reads ", , Uganda" and the country is then
            # repeated on its own line, giving "Port-Gentil, Gabon, Gabon".
            parts = [re.sub(r"\s*,\s*(,\s*)*", ", ", p).strip(" ,") for p in parts if p]
            uniq = []
            for p in parts:
                if not p:
                    continue
                low = p.lower()
                if any(low == u.lower() or low in u.lower() for u in uniq):
                    continue
                uniq = [u for u in uniq if u.lower() not in low]
                uniq.append(p)
            out.append(_mk(cfg, title=title, url=job_url, location=", ".join(uniq)))
    _enrich_details(f, cfg, out)
    return out


# --------------------------------------------------------------------------
# Generic adapters - work on almost any career site
# --------------------------------------------------------------------------
@adapter("jsonld")
def jsonld(f, cfg):
    """Read schema.org JobPosting data. Google requires it for job search
    visibility, so the vast majority of career sites publish it."""
    out, seen = [], set()
    urls = _listify(cfg, "urls", "url")
    for page_url in urls:
        for page in range(int(cfg.get("max_pages", 1))):
            u = _paged_url(page_url, cfg, page)
            r = f.get(u)
            if not r.ok:
                break
            nodes = H.json_blobs(r.text, "JobPosting")
            for n in nodes:
                job = _from_jsonld(cfg, n, r.url)
                if job and job.url not in seen:
                    seen.add(job.url)
                    out.append(job)
            if not _is_paged(page_url) or not nodes:
                break
    if not out and cfg.get("link_pattern"):
        return links(f, cfg)
    return out


def _from_jsonld(cfg, n, base):
    title = n.get("title") or n.get("name") or ""
    if not title:
        return None
    url = n.get("url") or n.get("sameAs") or base
    if isinstance(url, list):
        url = url[0] if url else base
    j = _mk(cfg, title=H.strip_tags(str(title), False),
            location=H.jsonld_location(n),
            url=H.absolutize(base, str(url)),
            posted=n.get("datePosted", ""),
            contract_type=(n.get("employmentType") if isinstance(n.get("employmentType"), str)
                           else ", ".join(n.get("employmentType") or [])),
            external_id=str(n.get("identifier", {}).get("value", ""))
            if isinstance(n.get("identifier"), dict) else str(n.get("identifier") or ""),
            description=H.strip_tags(str(n.get("description", ""))))
    if not cfg.get("company"):
        j.company = H.jsonld_org(n) or cfg.get("id", "")
    return j


@adapter("links")
def links(f, cfg):
    """Harvest job links off listing pages, then read each detail page.

    The fallback that works when a site has no JSON API and no structured data.
    Configure ``link_pattern`` with a regex matching the job-detail URLs.
    """
    pattern = cfg.get("link_pattern") or r"/(job|jobs|vacancy|vacancies|career|opportunit|position)s?/"
    out, seen = [], set()
    candidates = []
    for page_url in _listify(cfg, "urls", "url"):
        for page in range(int(cfg.get("max_pages", 1))):
            u = _paged_url(page_url, cfg, page)
            r = f.get(u)
            if not r.ok:
                break
            found = H.find_links(r.text, r.url, pattern)
            new = [(lu, lt) for lu, lt in found if lu not in seen]
            for lu, lt in new:
                seen.add(lu)
                candidates.append((lu, lt))
            if not _is_paged(page_url) or not new:
                break

    exclude = cfg.get("exclude_pattern")
    if exclude:
        rx = re.compile(exclude, re.I)
        candidates = [c for c in candidates if not rx.search(c[0])]

    max_details = int(cfg.get("max_details", 60))
    for url, label in candidates[:max_details]:
        j = _parse_detail(f, cfg, url, label)
        if j:
            out.append(j)
    return out


def _parse_detail(f, cfg, url, label=""):
    """Read one job page: structured data if present, readable text if not."""
    r = f.get(url, cache_ttl=cfg.get("detail_ttl", 86400))
    if not r.ok:
        return None
    nodes = H.json_blobs(r.text, "JobPosting")
    if nodes:
        j = _from_jsonld(cfg, nodes[0], r.url)
        if j and j.title:
            if not j.location:
                j.location = _guess_location(H.text_of(r.text), cfg)
                j.normalise()
            return j
    title = (H.meta(r.text, "og:title") or H.page_title(r.text) or label).strip()
    # Page titles are usually "Role | Company" - keep the role.
    title = re.split(r"\s+[|–—]\s+|\s+-\s+(?=[A-Z][a-z]+\s*$)", title)[0].strip() or label
    if not title or _looks_like_listing(title):
        return None
    body = H.text_of(r.text)
    return _mk(cfg, title=title, url=r.url,
               location=_guess_location(body, cfg),
               posted=_guess_date(body),
               description=body[:6000])


_LOC_LABELS = r"(?:work\s*location|workplace\s*location|job\s*location|duty\s*station|" \
              r"location|country|city|based\s*in|region)"
# "Location: Luanda" / "Location - Luanda"
_LOC_INLINE = re.compile(_LOC_LABELS + r"\s*[:\-–]\s*([A-Za-z][A-Za-z .,'/()-]{2,60})", re.I)
# Label on its own line, value on the next line - very common once tags are stripped.
_LOC_BLOCK = re.compile(r"^\s*" + _LOC_LABELS + r"\s*:?\s*$\n+\s*([A-Za-z][^\n]{1,60})",
                        re.I | re.M)
_COUNTRY_BLOCK = re.compile(r"^\s*country\s*:?\s*$\n+\s*([A-Za-z][^\n]{1,45})", re.I | re.M)
_CITY_BLOCK = re.compile(r"^\s*city\s*:?\s*$\n+\s*([A-Za-z][^\n]{1,45})", re.I | re.M)
_DATE_RX = re.compile(r"(?:posted|published|date posted|start date)\s*(?:on)?\s*[:\-–]?\s*"
                      r"([0-9]{1,2}[ /-][A-Za-z0-9]{2,9}[ /-][0-9]{2,4}|[0-9]{4}-[0-9]{2}-[0-9]{2})", re.I)


_LISTING_TITLE = re.compile(
    r"^\s*(?:(?:all|browse|latest|search|view|current|open)\s+){0,2}"
    r"(job\s+(search|alerts?|listings?|board|results)|jobs?|vacanc(y|ies)|"
    r"careers?|opportunit(y|ies)|positions?|roles?)"
    r"\b(\s+(in|at|for|with|by|across|near)\b.*|\s*$)", re.I)


def _looks_like_listing(title):
    """Category and search pages sneak past link harvesting; drop them.

    'Jobs in Engineering & IT' is a browse page, not a vacancy.
    """
    return bool(_LISTING_TITLE.match(title or ""))


def _plausible_location(value):
    """Reject prose that happened to follow a 'location' label."""
    v = (value or "").strip(" .,:-–")
    if not v or len(v) > 60 or len(v.split()) > 7:
        return ""
    if re.search(r"\b(the|and|for|with|will|must|your|our|please|requirement|apply|"
                 r"web|website|see|below|above|various|other)\b", v, re.I):
        return ""
    return v


def _guess_location(body, cfg):
    if cfg.get("location_pattern"):
        m = re.search(cfg["location_pattern"], body, re.I)
        if m and _plausible_location(m.group(1)):
            return _plausible_location(m.group(1))

    # Prefer an explicit City + Country pair when the page offers both.
    city = _CITY_BLOCK.search(body)
    country = _COUNTRY_BLOCK.search(body)
    city_v = _plausible_location(city.group(1)) if city else ""
    country_v = _plausible_location(country.group(1)) if country else ""
    if city_v and country_v:
        return "%s, %s" % (city_v, country_v)
    if country_v:
        return country_v

    for rx in (_LOC_BLOCK, _LOC_INLINE):
        for m in rx.finditer(body):
            v = _plausible_location(m.group(1))
            if v:
                return v
    return city_v


def _guess_date(body):
    m = _DATE_RX.search(body)
    return m.group(1).strip() if m else ""


@adapter("rss")
def rss(f, cfg):
    out = []
    for url in _listify(cfg, "urls", "url"):
        r = f.get(url, accept="application/rss+xml, application/xml, text/xml, */*")
        if not r.ok:
            continue
        items = re.findall(r"<item\b.*?</item>", r.text, re.S | re.I) or \
                re.findall(r"<entry\b.*?</entry>", r.text, re.S | re.I)
        for it in items:
            title = _xml_tag(it, "title")
            link = _xml_tag(it, "link") or _xml_attr(it, "link", "href")
            if not title:
                continue
            desc = H.strip_tags(_xml_tag(it, "description") or _xml_tag(it, "summary")
                                or _xml_tag(it, "content"))
            out.append(_mk(cfg, title=title, url=link,
                           posted=_xml_tag(it, "pubDate") or _xml_tag(it, "updated")
                           or _xml_tag(it, "published"),
                           location=_guess_location(desc, cfg), description=desc))
    return out


def _xml_tag(blob, tag):
    m = re.search(r"<%s\b[^>]*>(.*?)</%s>" % (tag, tag), blob, re.S | re.I)
    if not m:
        return ""
    val = m.group(1).strip()
    cd = re.match(r"^<!\[CDATA\[(.*?)\]\]>$", val, re.S)
    return H.strip_tags(cd.group(1) if cd else val, keep_breaks=False)


def _xml_attr(blob, tag, attr):
    m = re.search(r"<%s\b[^>]*%s\s*=\s*[\"']([^\"']+)[\"']" % (tag, attr), blob, re.I)
    return m.group(1) if m else ""


@adapter("sitemap")
def sitemap(f, cfg):
    """Read a sitemap (or sitemap index), keep job URLs, then detail-parse."""
    root = cfg.get("url") or (_origin(cfg.get("careers_url", "")) + "/sitemap.xml")
    url_pattern = cfg.get("url_pattern", r"/job")
    rx = re.compile(url_pattern, re.I)
    to_visit, job_urls, depth = [root], [], 0
    while to_visit and depth < 3:
        nxt = []
        for sm in to_visit[:10]:
            r = f.get(sm, accept="application/xml, text/xml, */*")
            if not r.ok:
                continue
            locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", r.text, re.S | re.I)
            if re.search(r"<sitemapindex", r.text, re.I):
                nxt.extend([l for l in locs if rx.search(l) or "job" in l.lower()][:10])
            else:
                job_urls.extend([l for l in locs if rx.search(l)])
        to_visit, depth = nxt, depth + 1
    cfg = dict(cfg)
    seen, uniq = set(), []
    for u in job_urls:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    # Some sitemaps append new jobs at the end. Set "newest_last": true for
    # those so the max_details budget is spent on the freshest adverts.
    if cfg.get("newest_last"):
        uniq.reverse()
    out = []
    for u in uniq[:int(cfg.get("max_details", 80))]:
        j = _parse_detail(f, cfg, u)
        if j:
            out.append(j)
    return out


def _enrich_details(f, cfg, jobs):
    """Optionally pull descriptions for jobs that only have a title + link."""
    if not cfg.get("detail"):
        return
    for j in jobs[:int(cfg.get("max_details", 40))]:
        if j.description:
            continue
        r = f.get(j.url, cache_ttl=86400)
        if not r.ok:
            continue
        nodes = H.json_blobs(r.text, "JobPosting")
        if nodes:
            j.description = H.strip_tags(str(nodes[0].get("description", "")))
            j.location = j.location or H.jsonld_location(nodes[0])
        else:
            j.description = H.text_of(r.text)[:6000]
        j.normalise()


# --------------------------------------------------------------------------
# ATS auto-detection
# --------------------------------------------------------------------------
FINGERPRINTS = [
    ("workday", re.compile(r"https?://([a-z0-9\-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-zA-Z\-]+/)?([A-Za-z0-9_\-]+)", re.I)),
    ("greenhouse", re.compile(r"https?://(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_board\?for=)?([A-Za-z0-9_\-]+)", re.I)),
    ("lever", re.compile(r"https?://jobs\.(?:eu\.)?lever\.co/([A-Za-z0-9_\-]+)", re.I)),
    ("smartrecruiters", re.compile(r"(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9_\-]+)", re.I)),
    ("recruitee", re.compile(r"https?://([a-z0-9\-]+)\.recruitee\.com", re.I)),
    ("workable", re.compile(r"https?://apply\.workable\.com/([A-Za-z0-9_\-]+)", re.I)),
    ("ashby", re.compile(r"https?://jobs\.ashbyhq\.com/([A-Za-z0-9_\-]+)", re.I)),
    ("oracle_orc", re.compile(r"https?://([a-z0-9\-.]+oraclecloud\.com|[a-z0-9\-.]+)/hcmUI/CandidateExperience/[a-z\-]+/sites/([A-Za-z0-9_\-]+)", re.I)),
    ("successfactors", re.compile(r"jobTitle-link|successfactors|/services/x/careersite|sfcareer", re.I)),
    ("taleo", re.compile(r"https?://([a-z0-9\-.]+\.taleo\.net)/careersection/([A-Za-z0-9_\-]+)", re.I)),
    ("icims", re.compile(r"https?://([a-z0-9\-]+)\.icims\.com", re.I)),
    ("avature", re.compile(r"avature\.net|avature", re.I)),
    ("phenom", re.compile(r"phenompeople|phenom\.com|ph-widget|/widgets\?", re.I)),
    ("beehire", re.compile(r"app\.beehire\.com/career/([A-Za-z0-9_\-]+)", re.I)),
    ("teamtailor", re.compile(r"teamtailor\.com", re.I)),
    ("bullhorn", re.compile(r"bullhorn(?:staffing)?\.com|bhrs\b", re.I)),
]


def sniff(url, html_doc):
    """Return (ats_name, match) for the strongest fingerprint in URL + HTML."""
    haystack = (url or "") + "\n" + (html_doc or "")
    for name, rx in FINGERPRINTS:
        m = rx.search(url or "")
        if m:
            return name, m
        m = rx.search(haystack)
        if m:
            return name, m
    return ("unknown", None)


def derive_config(url, html_doc, base_cfg=None):
    """Turn a careers URL + its HTML into a runnable source config."""
    cfg = dict(base_cfg or {})
    ats, m = sniff(url, html_doc)
    cfg["detected_ats"] = ats
    origin = _origin(url)

    if ats == "workday" and m:
        tenant, wd, site = m.group(1), m.group(2), m.group(3)
        if site.lower() in ("en-us", "en", "fr-fr", "job", "login"):
            m2 = re.search(r"myworkdayjobs\.com/(?:[a-zA-Z\-]+/)?([A-Za-z0-9_\-]+)", url, re.I)
            site = m2.group(1) if m2 else site
        cfg.update({"adapter": "workday", "host": "%s.%s.myworkdayjobs.com" % (tenant, wd),
                    "tenant": tenant, "site": site})
    elif ats == "greenhouse" and m:
        cfg.update({"adapter": "greenhouse", "token": m.group(1)})
    elif ats == "lever" and m:
        cfg.update({"adapter": "lever", "token": m.group(1)})
    elif ats == "smartrecruiters" and m:
        cfg.update({"adapter": "smartrecruiters", "company_id": m.group(1)})
    elif ats == "recruitee" and m:
        cfg.update({"adapter": "recruitee", "company_id": m.group(1)})
    elif ats == "workable" and m:
        cfg.update({"adapter": "workable", "company_id": m.group(1)})
    elif ats == "ashby" and m:
        cfg.update({"adapter": "ashby", "company_id": m.group(1)})
    elif ats == "oracle_orc" and m:
        # The careers URL is usually a vanity domain that does NOT serve the
        # REST API; the real Fusion host is named inside the page.
        host, site = m.group(1), m.group(2)
        fusion = re.search(r"[a-z0-9\-]+\.fa\.[a-z0-9]+\.oraclecloud\.com", html_doc or "", re.I)
        if fusion:
            host = fusion.group(0)
        site_hint = re.search(r"siteNumber[=\"':\s]+([A-Za-z0-9_\-]+)", html_doc or "")
        if site_hint:
            site = site_hint.group(1)
        cfg.update({"adapter": "oracle_orc", "host": host, "site": site})
    elif ats == "beehire" and m:
        cfg.update({"adapter": "beehire", "company_id": m.group(1)})
    elif ats == "successfactors":
        cfg.update({"adapter": "successfactors", "base": origin})
    else:
        # Structured data first, raw link harvesting as the safety net.
        if H.json_blobs(html_doc, "JobPosting"):
            cfg.update({"adapter": "jsonld", "urls": [url]})
        else:
            cfg.update({"adapter": "links", "urls": [url]})
    return cfg


@adapter("autodetect")
def autodetect(f, cfg):
    """Fetch the careers page, work out the ATS, then run the real adapter."""
    url = cfg.get("careers_url") or cfg.get("url")
    if not url:
        return []
    r = f.get(url, cache_ttl=cfg.get("detect_ttl", 21600))
    if not r.ok and not r.text:
        print("      [autodetect] could not reach %s (status %s)" % (url, r.status))
        return []

    # Career pages often just bounce to the real ATS - follow that hint too.
    hint = r.url
    if hint == url:
        for _, rx in FINGERPRINTS[:8]:
            m = rx.search(r.text)
            if m:
                hint = m.group(0)
                break

    derived = derive_config(hint if hint != url else r.url, r.text, cfg)
    name = derived.get("adapter", "links")
    if name == "autodetect":
        name = "links"
    print("      [autodetect] %s -> %s" % (cfg.get("id"), derived.get("detected_ats", name)))
    fn = REGISTRY.get(name)
    if not fn:
        return []
    return fn(f, derived)


def run_source(f, cfg):
    name = cfg.get("adapter", "autodetect")
    fn = REGISTRY.get(name)
    if not fn:
        raise ValueError("unknown adapter: %s" % name)
    return fn(f, cfg)
