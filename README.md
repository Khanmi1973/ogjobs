# ogjobs — Oil & Gas Job Radar (GCC + Africa)

An agent that scans blue-chip oil & gas operators and specialist recruiters for
vacancies in the Gulf and Africa, filters them to your target countries, ranks
them, and builds a report you can open in a browser.

**No API keys. No paid services. No `pip install`.** It uses only the Python
standard library and reads the same public endpoints each employer's own careers
website uses.

---

## Quick start — the dashboard

Double-click **`dashboard.bat`**, or run:

```bash
cd C:\cdx\ogjobs && python -m ogjobs serve
```

Your browser opens at `http://127.0.0.1:8765/` with a **Scan now** button.
Press it and it scrapes every enabled source live, showing which company it is
on, a progress bar, and a running match count. When it finishes the page
reloads itself with the new jobs. Leave the console window open while you use
it; Ctrl+C there shuts it down.

The **"ignore cache (fully fresh)"** tick box is on by default, so Scan now
always pulls straight from the source rather than reusing anything stored
earlier. Untick it for a much faster re-run that reuses recent pages.

A full fresh scan of all enabled sources takes a few minutes — the delay
between requests is deliberate and is what keeps you from being blocked.

Only one scan runs at a time, and the dashboard is bound to `127.0.0.1`, so
nothing is reachable from outside your machine.

## Using it on your phone

There are three ways. Pick one:

| | PC can be off | Refresh button | Stays private |
|---|---|---|---|
| **A. GitHub Pages** — see [GITHUB-SETUP.md](GITHUB-SETUP.md) | yes | yes, via GitHub | no, public |
| **B. `mobile.bat`** over your Wi-Fi | no | yes, instant | yes |
| **C. Copy `jobs.html`** to the phone | yes, offline too | no | yes |

**A is what most people want.** GitHub runs the scraper on its own computers,
once a day plus whenever you press Refresh, and publishes the dashboard at a
web address you can open anywhere. Free, but the page is public — it only ever
contains job adverts, never your details. Follow
[GITHUB-SETUP.md](GITHUB-SETUP.md).

### Option B — over your Wi-Fi (full dashboard, Scan now works)

Your PC must be switched on and both devices on the same Wi-Fi. Double-click
**`mobile.bat`**, or run:

```bash
cd C:\cdx\ogjobs && python -m ogjobs serve --host lan
```

The console prints a link with an access key:

```
http://192.168.1.20:8765/?k=AbC123xyz
```

Type that into your phone's browser once — the key is stored for 24 hours, so
afterwards `http://192.168.1.20:8765/` is enough. Add it to your home screen and
it behaves like an app. The layout adapts to a phone screen: full-width
controls, finger-sized buttons, no sideways scrolling.

**If the phone cannot connect**, Windows Firewall is blocking the port. Run this
once in an **Administrator** PowerShell:

```bash
netsh advfirewall firewall add rule name="ogjobs" dir=in action=allow protocol=TCP localport=8765
```

A few things worth knowing about this mode:

- A new random key is generated each start, so old links stop working. Pass
  `--key mysecret` if you want a permanent one you can bookmark.
- Requests without the key get refused, including scan requests — someone on
  your Wi-Fi cannot trigger scans or read your list without the link.
- It is plain HTTP on your local network, not encrypted, and there is no
  hardening beyond the key. Use it on your own or a trusted Wi-Fi, not on hotel
  or café networks, and close the window when you are done.
- This is your PC serving the page, so it only works while that console window
  is open and the machine is awake.

### Option C — take the file with you (works anywhere, no PC needed)

Copy `data\reports\jobs.html` to your phone — email it to yourself, or drop it in
Google Drive / OneDrive / WhatsApp to yourself — and open it there. It is a
single self-contained file, so search and filtering work offline on a plane or
with no signal.

The trade-off: it is a snapshot. There is no Scan now button, and you must copy
a new file after each scan. Good for reviewing on the move; use Option A when
you want fresh jobs.

### Or without the dashboard

```bash
python -m ogjobs run --open
```

That scrapes every enabled source, stores results in `data/jobs.db`, and writes
`data/reports/jobs.html`, `jobs.csv` and `jobs.xml`. This is the form to use for
scheduled runs. Later runs are much faster — listing pages cache for 15 minutes
and job pages for 24 hours, and only genuinely new adverts are flagged.

---

## What is already verified working

Tested live end-to-end — **1,073 jobs scraped, 233 matches in your target
regions** in a single run:

| Source | Company | Platform | Scraped | In GCC/Africa |
|---|---|---|---:|---:|
| `aldelia` | Aldelia | BeeHire JSON | 248 | **195** |
| `totalenergies` | TotalEnergies | Avature | 120 | **22** |
| `bp` | bp | Workday | 333 | 6 |
| `sbmoffshore` | SBM Offshore | SuccessFactors | 63 | 4 |
| `shell` | Shell | Workday | 135 | 3 |
| `exxonmobil` | ExxonMobil | SuccessFactors | 201 | 1 |

Note the shape of that table: **the recruiters carry the regional volume, the
majors don't.** Aldelia alone produced more GCC/Africa matches than all four
supermajors combined — 195 roles across Mozambique, Uganda, Angola and Namibia.
Keep the recruiters enabled.

Two sources needed detective work worth knowing about:

- **Aldelia** publishes nothing on its own website — its board is hosted on
  BeeHire, whose page is a JavaScript app. Opening it in a browser and watching
  the network traffic revealed one public JSON endpoint
  (`app.beehire.com/users/getPublicCampaigns/aldelia`) that returns all 248
  jobs at once. There is now a `beehire` adapter, so any other recruiter on
  BeeHire is auto-detected too.
- **Airswift** paginates with JavaScript, but its `sitemap.xml` lists every job
  URL and its robots.txt permits `/jobs/`, so it uses the `sitemap` adapter.

Still configured but **not verified from here** — my sandbox could not resolve
their DNS, so run `probe` on your own machine: Eni, SAEOWL, Q-Sourcing Servtec,
TruNorth Africa, NES Fircroft, Petroplan. Brunel is enabled but its generic
fallback returned little; probe it too.

Sitting disabled in `config/sources.json`, ready to switch on: ADNOC,
QatarEnergy, Aramco, PDO, Petrofac, Saipem, TechnipFMC, McDermott, Wood, Baker
Hughes, SLB, Halliburton, Weatherford, Chevron, Equinor, Sonangol, Orion Group.

```bash
python -m ogjobs sources
```

```bash
python -m ogjobs enable adnoc qatarenergy petrofac
```

---

## The three files you actually edit

### 1. `config/filters.json` — what counts as a match

Geography decides what is **kept**; keywords decide the **ranking**.

- `countries.include` — the country list. Delete any you don't want.
- `roles.must_any` — **starts empty on purpose.** Empty means "keep every job
  in my target countries at these companies". Once you see the volume, put your
  own discipline in and only those survive:

  ```json
  "must_any": ["piping", "welding", "qa/qc", "inspector", "ndt"]
  ```

- `roles.exclude` — throw away anything containing these words. Add
  `"intern"`, `"graduate"`, `"apprentice"` if you only want experienced roles.
- `roles.boost` — ranking weights. Put your trade words at a high number so
  your roles float to the top. Negative numbers push things down.
- `min_score` — raise to 45–60 later to cut the tail.

Check any change without a full scrape:

```bash
python -m ogjobs test-filters "Senior Piping Inspector - FPSO" "Luanda, Angola"
```

### 2. `config/sources.json` — where to look

Each entry is one employer. The key field is `adapter`:

| adapter | use |
|---|---|
| `autodetect` | **default** — works out the platform at run time |
| `workday` | Workday boards (`*.myworkdayjobs.com`) |
| `successfactors` | SAP SuccessFactors career sites |
| `greenhouse` / `lever` / `smartrecruiters` / `recruitee` / `workable` / `ashby` / `beehire` | public JSON boards |
| `oracle_orc` | Oracle Recruiting Cloud (common for Gulf national oil companies) |
| `jsonld` | any site publishing schema.org JobPosting data |
| `links` | generic fallback: harvest job links, then read each page |
| `rss` / `sitemap` | feeds and sitemaps |

### 3. `config/settings.json` — politeness

`delay_seconds` (default 1.5) is the pause between requests to the same host.
**Don't lower it.** Staying slow is why this doesn't get blocked. `respect_robots`
is on by default.

---

## Adding a company yourself

This is the part that makes the system future-proof. Point `probe` at any
careers URL and it works out which platform is behind it and prints a working
config block:

```bash
python -m ogjobs probe https://careers.someoperator.com --test
```

`--test` immediately tries scraping so you can see real job titles before
committing. To write it straight into your config:

```bash
python -m ogjobs probe https://careers.someoperator.com --id someop --company "Some Operator" --append
```

This is exactly how the bp entry was built: probing bp's public careers page
resolved it to the Workday tenant `bpinternational` / site `bpCareers`, which
returned 300 jobs on the first try.

**If a source returns 0 jobs**, probe its careers URL — the company has almost
certainly moved its job board.

---

## Everyday commands

```bash
python -m ogjobs run --open
```

```bash
python -m ogjobs run --source shell --source bp
```

```bash
python -m ogjobs report --new --top 20
```

```bash
python -m ogjobs report --country Angola --min-score 50 --open
```

```bash
python -m ogjobs stats
```

```bash
python -m ogjobs serve --port 8790
```

`--dry-run` scrapes without touching the database. `OGJOBS_DEBUG=1` prints full
tracebacks when a source misbehaves.

---

## Running it automatically (free)

`run.bat` runs a scan and refreshes the report. To have Windows do it every
morning at 07:00, run this once in PowerShell:

```bash
schtasks /create /tn "OG Job Radar" /tr "C:\cdx\ogjobs\run.bat" /sc daily /st 07:00
```

Then just open `data/reports/jobs.html` with your coffee. New adverts since the
last run carry a **NEW** badge, and `data/reports/jobs.xml` is an RSS feed you
can subscribe to in any free reader.

---

## How it works

```
config/sources.json
        |
        v
   adapters.py  ---- autodetect: sniff the ATS, pick the right reader
        |             (Workday / SuccessFactors / Avature / JSON boards / generic)
        v
    http.py     ---- rate-limited, cached, gzip-aware, robots-aware
        |
        v
   filters.py   ---- geography gate (geo.py) then keyword scoring
        |
        v
    store.py    ---- SQLite (WAL): dedup by fingerprint, track first_seen
        |
        v
   report.py    ---- HTML dashboard + CSV + RSS
        |
        v
   server.py    ---- serves the dashboard, runs Scan now in a worker thread
```

The Scan now button posts to `/api/scan`, which starts the same pipeline in a
background thread; the page polls `/api/status` every 1.5s for progress. The
database runs in WAL mode so the dashboard stays readable while a scan writes.

**Deduplication** is by company + normalised title + country, so the same role
seen twice — or advertised by two recruiters — collapses into one row.

**Geography matching** understands country names, ISO codes and oil-town names:
`Luanda`, `Cabinda`, `Ras Laffan`, `Al Khobar`, `Port Harcourt`, `Pointe-Noire`
all resolve correctly, and it knows `28/28` means rotational. It also guards
against lookalikes — `Bonnyville, Canada` does not match `Bonny, Nigeria`.

---

## Honest limitations

- **Some sites need JavaScript.** Where a board renders purely client-side and
  exposes no JSON endpoint, the `links` adapter may return little. Probe it,
  then open the page in Chrome, press F12 → Network → reload, and look for a
  request returning JSON. That is exactly how the Aldelia board was cracked, and
  it usually takes two minutes. Two other tricks before giving up: check
  `/sitemap.xml` for job URLs (this is how Airswift works), and check whether the
  company's *real* board lives on a different domain than its marketing site.
- **Volume at the majors is genuinely low.** In testing, Shell had 135 open
  roles worldwide and only 3 in the target regions. That is the real market, not
  a bug — much Gulf hiring runs through local portals and the recruiters
  (Airswift, Brunel, NES Fircroft, Aldelia) carry far more regional volume.
  Enable plenty of recruiters.
- **LinkedIn and Indeed are not included.** Both actively block scraping and
  their terms forbid it. Set up their free native job alerts by hand instead —
  that costs nothing and complements this tool.
- **Anti-bot protection** stops some sites (Cloudflare interstitials). Those
  return 0; nothing is faked or invented.

---

## One safety note

Every match links to the employer's own official posting — apply there. In this
market fake "agents" charge fees for GCC and African oil & gas placements.
**Legitimate employers and licensed recruiters never ask a candidate for money**
for a job, a visa, or a "medical processing" fee. If someone does, walk away.
