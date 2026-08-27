"""Output: a self-contained HTML dashboard, CSV, and an RSS feed."""
import csv
import html
import json
import os
import re
from datetime import datetime, timezone

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--fg:#14181d;--muted:#5c6672;--line:#e2e6eb;
--accent:#0b6b53;--accent-soft:#e6f2ee;--new:#b4531a;--new-soft:#fdf0e6;--shadow:0 1px 2px rgba(16,24,40,.06)}
@media (prefers-color-scheme:dark){:root{--bg:#0f1216;--card:#171b21;--fg:#e8ecf1;--muted:#98a2b0;
--line:#262c35;--accent:#4fd1a5;--accent-soft:#12261f;--new:#f0a06a;--new-soft:#2a1c11;--shadow:none}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:28px 20px 60px}
h1{font-size:24px;margin:0 0 4px}
.sub{color:var(--muted);font-size:13px;margin-bottom:20px}
.stats{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:18px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px;box-shadow:var(--shadow)}
.stat b{display:block;font-size:20px}
.stat span{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.05em}
.controls{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px}
input,select{background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:8px;
padding:9px 11px;font-size:14px;font-family:inherit}
input[type=search]{flex:1;min-width:220px}
.job{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;
margin-bottom:10px;box-shadow:var(--shadow)}
.job h2{font-size:16px;margin:0 0 6px;line-height:1.35}
.job h2 a{color:var(--fg);text-decoration:none}
.job h2 a:hover{color:var(--accent);text-decoration:underline}
.meta{color:var(--muted);font-size:13px;display:flex;flex-wrap:wrap;gap:6px 14px;margin-bottom:8px}
.when{white-space:nowrap}
.when.fresh{color:var(--accent);font-weight:600}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{background:var(--accent-soft);color:var(--accent);border-radius:999px;padding:2px 9px;font-size:11.5px;font-weight:600}
.chip.new{background:var(--new-soft);color:var(--new)}
.chip.plain{background:transparent;border:1px solid var(--line);color:var(--muted);font-weight:500}
.score{float:right;font-weight:700;color:var(--accent);font-size:13px}
.snippet{color:var(--muted);font-size:13px;margin-top:8px;display:none;white-space:pre-wrap;
max-height:220px;overflow:auto;border-top:1px solid var(--line);padding-top:8px}
.job.open .snippet{display:block}
.toggle{background:none;border:0;color:var(--muted);font-size:12px;cursor:pointer;padding:4px 0;font-family:inherit}
.empty{text-align:center;color:var(--muted);padding:50px 0}
.scanbar{display:flex;flex-wrap:wrap;align-items:center;gap:12px;background:var(--card);
border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin-bottom:16px;box-shadow:var(--shadow)}
.btn{background:var(--accent);color:#fff;border:0;border-radius:8px;padding:10px 18px;
font-size:14px;font-weight:600;cursor:pointer;font-family:inherit}
.btn:hover{filter:brightness(1.08)}
.btn:disabled{opacity:.55;cursor:not-allowed;filter:none}
@media (prefers-color-scheme:dark){.btn{color:#07120e}}
:root[data-theme="dark"] .btn{color:#07120e}
.opt{display:flex;align-items:center;gap:6px;font-size:13px;color:var(--muted)}
.opt input{width:auto}
.scanmsg{font-size:13px;color:var(--muted);flex:1;min-width:180px}
.bar{height:5px;background:var(--line);border-radius:99px;overflow:hidden;margin-top:10px;display:none}
.bar>i{display:block;height:100%;width:0;background:var(--accent);transition:width .4s ease}
.scanlog{display:none;margin-top:10px;background:var(--bg);border:1px solid var(--line);
border-radius:8px;padding:10px 12px;font:12px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace;
color:var(--muted);max-height:230px;overflow:auto;white-space:pre-wrap}
.scanning .bar,.scanning .scanlog{display:block}
footer{color:var(--muted);font-size:12px;margin-top:30px;border-top:1px solid var(--line);padding-top:14px}

/* Phones: full-width controls and finger-sized tap targets. */
@media (max-width:600px){
  .wrap{padding:16px 12px 44px}
  h1{font-size:20px}
  .stat{flex:1 1 calc(50% - 6px);padding:9px 12px}
  .stat b{font-size:18px}
  .controls{gap:8px}
  .controls input,.controls select{width:100%;min-width:0;padding:12px 11px}
  .btn{width:100%;padding:14px 18px;font-size:15px}
  .opt,.scanmsg{width:100%}
  .scanbar{gap:10px}
  .job{padding:13px 14px}
  .job h2{font-size:15px;padding-right:44px}
  .score{font-size:14px}
  .toggle{padding:10px 0;font-size:13px}
  .scanlog{max-height:180px;font-size:11.5px}
}
"""

JS = """
const rows=[...document.querySelectorAll('.job')];
const q=document.getElementById('q'),src=document.getElementById('src'),
      cty=document.getElementById('cty'),onlynew=document.getElementById('onlynew'),
      age=document.getElementById('age'),
      sortBy=document.getElementById('sortby'),count=document.getElementById('count');
function apply(){
  const t=q.value.toLowerCase().trim(), s=src.value, c=cty.value, n=onlynew.checked;
  const maxAge=age.value?+age.value:null;
  let shown=0;
  rows.forEach(r=>{
    const hay=r.dataset.hay;
    // A job with no readable date is excluded once a date filter is active:
    // we cannot claim it is recent.
    const a=r.dataset.age===''?null:+r.dataset.age;
    const ok=(!t||hay.includes(t))&&(!s||r.dataset.company===s)&&
             (!c||(r.dataset.countries||'').includes(c))&&(!n||r.dataset.new==='1')&&
             (maxAge===null||(a!==null&&a<=maxAge));
    r.style.display=ok?'':'none'; if(ok)shown++;
  });
  count.textContent=shown;
}
function sort(){
  const key=sortBy.value, box=document.getElementById('list');
  rows.sort((a,b)=>key==='score'
    ? (+b.dataset.score)-(+a.dataset.score)
    : (b.dataset.date||'').localeCompare(a.dataset.date||''));
  rows.forEach(r=>box.appendChild(r));
}
[q,src,cty,onlynew,age].forEach(el=>el.addEventListener('input',apply));
sortBy.addEventListener('change',sort);
document.querySelectorAll('.toggle').forEach(b=>b.addEventListener('click',
  ()=>b.closest('.job').classList.toggle('open')));
apply();
"""

# Only injected by the live server - the static file has nothing to talk to.
SCAN_JS = """
(function(){
  const bar=document.getElementById('scanbar'), btn=document.getElementById('scanbtn'),
        msg=document.getElementById('scanmsg'), log=document.getElementById('scanlog'),
        fill=document.getElementById('scanfill'), fresh=document.getElementById('scanfresh');
  let polling=null, t0=null;

  function paint(s){
    const pct=s.total?Math.round(s.index/s.total*100):0;
    fill.style.width=pct+'%';
    log.textContent=(s.log||[]).join('\\n');
    log.scrollTop=log.scrollHeight;
    if(s.running){
      const secs=t0?Math.round((Date.now()-t0)/1000):0;
      msg.textContent='Scanning '+(s.current||'')+'  ('+s.index+'/'+s.total+')  '
        +s.matched+' matched so far  ·  '+secs+'s';
    }
  }
  function stop(s){
    clearInterval(polling); polling=null;
    bar.classList.remove('scanning');
    btn.disabled=false; btn.textContent='Scan now';
    const errs=(s.errors||[]).length;
    msg.textContent='Done: '+s.found+' scraped, '+s.matched+' matched, '+s.new+' new'
      +(errs?('  ·  '+errs+' source(s) failed'):'')+'  ·  reloading...';
    setTimeout(()=>location.reload(),1400);
  }
  function poll(){
    fetch('/api/status').then(r=>r.json()).then(s=>{
      paint(s);
      if(!s.running) stop(s);
    }).catch(()=>{});
  }
  btn.addEventListener('click',()=>{
    btn.disabled=true; btn.textContent='Scanning...';
    bar.classList.add('scanning');
    log.textContent='Starting...'; t0=Date.now();
    msg.textContent='Starting scan - this takes a few minutes across all sources.';
    fetch('/api/scan',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({fresh:fresh.checked})})
      .then(r=>r.json().then(d=>({ok:r.ok,d})))
      .then(({ok,d})=>{
        if(!ok){ msg.textContent=d.reason||'could not start'; }
        polling=setInterval(poll,1500); poll();
      })
      .catch(e=>{ msg.textContent='could not reach the server: '+e;
                  btn.disabled=false; btn.textContent='Scan now';
                  bar.classList.remove('scanning'); });
  });
  // If a scan is already running (page opened mid-scan), attach to it.
  fetch('/api/status').then(r=>r.json()).then(s=>{
    if(s.running){ btn.disabled=true; btn.textContent='Scanning...';
      bar.classList.add('scanning'); t0=Date.now();
      polling=setInterval(poll,1500); poll(); }
  }).catch(()=>{});
})();
"""

# Shown on a static host (GitHub Pages). The page cannot scrape, so the button
# sends you to the Actions page where one tap starts the scan on GitHub.
HOSTED_HTML = """
<div class="scanbar">
  <a class="btn" href="%(url)s" target="_blank" rel="noopener"
     style="text-decoration:none;display:inline-block;text-align:center">Refresh jobs</a>
  <span class="scanmsg">Opens GitHub &rarr; press <b>Run workflow</b>. New jobs appear
    here in about 5 minutes (pull down to reload). Updates automatically once a day.</span>
  <span style="font-size:13px"><a href="jobs.csv" style="color:var(--accent)">CSV</a>
    &nbsp;<a href="jobs.xml" style="color:var(--accent)">RSS</a></span>
</div>
"""

SCAN_HTML = """
<div class="scanbar" id="scanbar">
  <button class="btn" id="scanbtn">Scan now</button>
  <label class="opt"><input type="checkbox" id="scanfresh" checked> ignore cache (fully fresh)</label>
  <span class="scanmsg" id="scanmsg">Scans every enabled source and rebuilds this page.</span>
  <span style="font-size:13px"><a href="/jobs.csv" style="color:var(--accent)">CSV</a>
    &nbsp;<a href="/jobs.xml" style="color:var(--accent)">RSS</a></span>
  <div class="bar" style="flex-basis:100%"><i id="scanfill"></i></div>
  <div class="scanlog" id="scanlog" style="flex-basis:100%"></div>
</div>
"""


def _e(s):
    return html.escape(str(s or ""))


def date_label(job):
    """Human date for a job card.

    Returns (text, iso_for_sorting, age_in_days). Falls back to the day we
    first saw the advert when the site publishes no date, and says so, so the
    two are never confused. age_in_days is None when no date can be read.
    """
    from datetime import datetime, timezone

    def pretty(iso):
        try:
            d = datetime.strptime(iso[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except Exception:
            return None, None
        days = (datetime.now(timezone.utc) - d).days
        if days <= 0:
            ago = "today"
        elif days == 1:
            ago = "yesterday"
        elif days < 7:
            ago = "%d days ago" % days
        elif days < 14:
            ago = "1 week ago"
        elif days < 61:
            ago = "%d weeks ago" % (days // 7)
        else:
            ago = "%d months ago" % (days // 30)
        return "%s (%s)" % (d.strftime("%d %b %Y"), ago), days

    posted = (job.get("posted") or "").strip()
    if posted:
        text, days = pretty(posted)
        if text:
            return "Posted " + text, posted[:10], days

    seen = (job.get("first_seen") or "")[:10]
    if seen:
        text, days = pretty(seen)
        if text:
            # No published date on the advert, so be explicit about what this is.
            return "Found " + text, seen, days
    return "", "", None


def build_html(jobs, meta=None, live=False):
    """Render the dashboard.

    ``live=True`` adds the Scan now control, which only works when the page is
    served by server.py. The static export leaves it out rather than showing a
    button that cannot do anything.
    """
    meta = meta or {}
    sources = sorted({j.get("source", "") for j in jobs if j.get("source")})
    # The picker shows company names ("Saipem"), not internal ids ("saipem"),
    # with a count so it is obvious which employers are represented.
    company_counts = {}
    for j in jobs:
        name = (j.get("company") or j.get("source") or "").strip()
        if name:
            company_counts[name] = company_counts.get(name, 0) + 1
    companies = sorted(company_counts, key=lambda n: (-company_counts[n], n.lower()))
    countries = sorted({c.strip() for j in jobs for c in (j.get("countries") or "").split(",")
                        if c.strip()})
    new_count = sum(1 for j in jobs if j.get("is_new") or j.get("_new"))

    parts = ["<title>Oil &amp; Gas Job Radar</title>", "<style>%s</style>" % CSS,
             '<div class="wrap">',
             "<h1>Oil &amp; Gas Job Radar</h1>",
             '<div class="sub">GCC &amp; Africa &middot; generated %s UTC &middot; %d sources scanned</div>'
             % (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"), meta.get("sources_run", len(sources))),
             '<div class="stats">',
             '<div class="stat"><b>%d</b><span>matches</span></div>' % len(jobs),
             '<div class="stat"><b>%d</b><span>new this run</span></div>' % new_count,
             '<div class="stat"><b>%d</b><span>countries</span></div>' % len(countries),
             '<div class="stat"><b>%d</b><span>companies</span></div>' % len(sources),
             "</div>",
             (SCAN_HTML if live
              else (HOSTED_HTML % {"url": _e(meta.get("hosted_url"))}
                    if meta.get("hosted_url") else "")),
             '<div class="controls">',
             '<input type="search" id="q" placeholder="Search title, company, location, keyword...">',
             '<select id="src"><option value="">All companies (%d)</option>%s</select>'
             % (len(companies),
                "".join('<option value="%s">%s (%d)</option>'
                        % (_e(c), _e(c), company_counts[c]) for c in companies)),
             '<select id="cty"><option value="">All countries</option>%s</select>'
             % "".join('<option>%s</option>' % _e(c) for c in countries),
             '<select id="age" title="Uses the advert\'s posted date. Where a site '
             'publishes no date, the day this tool first saw the job is used instead '
             '(those cards say &quot;Found&quot; rather than &quot;Posted&quot;).">'
             '<option value="">Any date</option>'
             '<option value="1">Last 24 hours</option>'
             '<option value="3">Last 3 days</option>'
             '<option value="7">Last week</option>'
             '<option value="14">Last 2 weeks</option>'
             '<option value="30">Last month</option>'
             '<option value="90">Last 3 months</option>'
             '</select>',
             '<select id="sortby"><option value="score">Sort: best match</option>'
             '<option value="date">Sort: newest</option></select>',
             '<label style="display:flex;align-items:center;gap:6px;font-size:13px;color:var(--muted)">'
             '<input type="checkbox" id="onlynew" style="width:auto"> new only</label>',
             "</div>",
             '<div class="sub"><b id="count">0</b> shown</div>',
             '<div id="list">']

    if not jobs:
        parts.append('<div class="empty">No matches yet. Run <code>python -m ogjobs run</code>, '
                     'or loosen <code>config/filters.json</code>.</div>')

    for j in jobs:
        hay = " ".join([str(j.get(k, "")) for k in
                        ("title", "company", "location", "countries", "matched",
                         "department", "source", "description")]).lower()
        date_text, date_iso, date_age = date_label(j)
        date_fresh = date_age is not None and date_age <= 7
        is_new = bool(j.get("is_new") or j.get("_new"))
        chips = []
        if is_new:
            chips.append('<span class="chip new">NEW</span>')
        for c in (j.get("countries") or "").split(","):
            if c.strip():
                chips.append('<span class="chip">%s</span>' % _e(c.strip()))
        for m in (j.get("matched") or "").split(",")[:6]:
            m = m.strip()
            if m and m not in (j.get("countries") or ""):
                chips.append('<span class="chip plain">%s</span>' % _e(m))
        snippet = re.sub(r"\n{2,}", "\n", (j.get("description") or ""))[:1400]
        parts.append(
            '<div class="job" data-source="%s" data-company="%s" data-countries="%s" '
            'data-score="%s" data-date="%s" data-age="%s" data-new="%d" data-hay="%s">'
            '<span class="score">%s</span>'
            '<h2><a href="%s" target="_blank" rel="noopener">%s</a></h2>'
            '<div class="meta"><span><b>%s</b></span><span>%s</span>'
            '<span class="when%s">%s</span>%s</div>'
            '<div class="chips">%s</div>%s</div>'
            % (_e(j.get("source")), _e(j.get("company") or j.get("source")),
               _e(j.get("countries")), _e(j.get("score")),
               _e(date_iso), "" if date_age is None else date_age,
               1 if is_new else 0, _e(hay),
               _e(j.get("score")), _e(j.get("url")), _e(j.get("title")),
               _e(j.get("company")), _e(j.get("location") or "location not stated"),
               " fresh" if date_fresh else "", _e(date_text),
               ('<span>%s</span>' % _e(j.get("department"))) if j.get("department") else "",
               "".join(chips),
               ('<button class="toggle">description</button><div class="snippet">%s</div>' % _e(snippet))
               if snippet else ""))

    parts.append("</div>")
    parts.append('<footer>Built by Muhammad Imran Khan '
                 '(<a href="tel:+923346844642" style="color:var(--accent)">+92 334 6844642</a>). '
                 'Data read directly from each employer&rsquo;s own public careers site. '
                 'Always apply through the official link above &mdash; never pay a fee '
                 'to a recruiter for a job placement.</footer>')
    parts.append("</div><script>%s</script>" % JS)
    if live:
        parts.append("<script>%s</script>" % SCAN_JS)
    return "\n".join(parts)


def write_html(jobs, path, meta=None):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    doc = "<!doctype html><html><head><meta charset='utf-8'>" \
          "<meta name='viewport' content='width=device-width,initial-scale=1'>" \
          + build_html(jobs, meta) + "</body></html>"
    doc = doc.replace("<style>", "</head><body><style>", 1)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    return path


def write_csv(jobs, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    cols = ["score", "title", "company", "location", "countries", "posted", "url",
            "source", "department", "contract_type", "matched", "first_seen", "flags"]
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for j in jobs:
            w.writerow({c: j.get(c, "") for c in cols})
    return path


def write_rss(jobs, path, title="Oil & Gas Job Radar"):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    items = []
    for j in jobs[:100]:
        items.append(
            "<item><title>%s</title><link>%s</link><guid isPermaLink='false'>%s</guid>"
            "<pubDate>%s</pubDate><description>%s</description></item>"
            % (_e("[%s] %s - %s" % (j.get("score"), j.get("title"), j.get("company"))),
               _e(j.get("url")), _e(j.get("fingerprint") or j.get("url")), now,
               _e("%s | %s | score %s" % (j.get("location"), j.get("countries"), j.get("score")))))
    xml = ("<?xml version='1.0' encoding='UTF-8'?><rss version='2.0'><channel>"
           "<title>%s</title><link>about:blank</link>"
           "<description>Matched oil and gas vacancies in the GCC and Africa</description>"
           "<lastBuildDate>%s</lastBuildDate>%s</channel></rss>"
           % (_e(title), now, "".join(items)))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(xml)
    return path


def write_json(jobs, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(jobs, fh, indent=2, ensure_ascii=False)
    return path
