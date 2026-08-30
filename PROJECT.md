# ogjobs — master reference

Paste this file into a future chat to bring an assistant fully up to speed.

**What it is:** a job-hunting agent that scrapes oil & gas operators and
specialist recruiters for vacancies in the GCC, wider Middle East and Africa,
filters them by country, ranks them, and publishes a dashboard.

**Owner:** Muhammad Imran Khan
**Repo:** https://github.com/Khanmi1973/ogjobs (public)
**Live dashboard:** https://Khanmi1973.github.io/ogjobs/
**Local path:** `C:\cdx\ogjobs`
**Cost:** £0. No API keys, no paid services, no `pip install` — Python standard
library only.

Current state: **41 sources configured, 25 enabled, 6,038 jobs stored,
1,494 matching across 39 countries.**

---

## 1. How it works

```
config/sources.json   what to scrape
        |
        v
   adapters.py        one reader per applicant-tracking system
        |             autodetect sniffs the ATS when it is unknown
        v
    http.py           rate-limited, cached, gzip-aware, robots-aware
        |
        v
   filters.py         geography gate (geo.py), then keyword scoring
        |
        v
    store.py          SQLite. Stores EVERYTHING, matching or not
        |
        v
   report.py          HTML dashboard + CSV + RSS
        |
        v
   server.py          local dashboard with a live "Scan now" button
```

**Key design decision:** rejected jobs are stored too. That is what lets
`ogjobs refilter` re-apply a changed `filters.json` to everything already
collected, in about a second, with no re-scraping. Before this existed,
widening the filters meant a full re-scrape and anything previously rejected
was lost forever.

---

## 2. Commands

```bash
cd C:\cdx\ogjobs
```

| Command | What it does |
|---|---|
| `python -m ogjobs run` | Scrape all enabled sources, rebuild the report |
| `python -m ogjobs run --fresh` | Same, ignoring the local page cache |
| `python -m ogjobs run --deep 5` | Multiply per-source caps for a full back-catalogue sweep (slow) |
| `python -m ogjobs run -s wood -s kbr` | Only these sources |
| `python -m ogjobs refilter` | Re-apply filters.json to stored jobs, no network |
| `python -m ogjobs serve` | Local dashboard with a working Scan now button |
| `python -m ogjobs serve --host lan` | Same, reachable from your phone on the same Wi-Fi |
| `python -m ogjobs probe <url> --test` | Detect a site's ATS and try scraping it |
| `python -m ogjobs sources` | List every source and its state |
| `python -m ogjobs enable <id>` / `--off` | Turn sources on and off |
| `python -m ogjobs stats` | Database and run history |
| `python -m ogjobs report --country Iraq --open` | Filtered report |

Launchers: `run.bat` (scan), `dashboard.bat` (local dashboard),
`mobile.bat` (dashboard reachable from a phone).

---

## 3. Configuration — the three files you edit

**`config/filters.json`** — geography decides what is *kept*, keywords decide
the *ranking*.
- `countries.include` — 44 countries: GCC, Iraq/Yemen/Jordan, and Africa.
- `roles.must_any` — empty on purpose. Empty keeps every in-geography job.
  Put your own trade words here to narrow it.
- `roles.boost` — ranking weights only, never filters. Negative numbers push
  things down (interns, apprentices).
- `max_age_days: 90`, `min_score: 0`.

**`config/sources.json`** — one entry per employer. `adapter` picks the reader.

**`config/settings.json`** — `delay_seconds: 1.5` between requests to the same
host. Do not lower it; that politeness is why we are not blocked.

---

## 4. Adapters written

| Adapter | Platform | Notes |
|---|---|---|
| `workday` | Workday | `total` is only reported on page 1 |
| `successfactors` | SAP SuccessFactors | Two layouts: old table, new job tiles |
| `phenom` | Phenom People | Data sits in the page's `phApp.ddo` JSON blob |
| `oracle_orc` | Oracle Recruiting Cloud | Careers domain is a shop window; API is on the Fusion host |
| `vennture` | Vennture recruiter sites | Sitemap + pre-rendered detail pages |
| `beehire` | BeeHire | One public JSON endpoint |
| `zoho_recruit` | Zoho Recruit | Jobs embedded as HTML-escaped JSON |
| `ncore` | nCore | One static JSON file with every vacancy |
| `nicoka` | Nicoka | Cards parsed directly; job URLs have no "job" in them |
| `links` | anything | Harvest job links, read each page |
| `jsonld` / `sitemap` / `rss` | anything | Structured data, sitemaps, feeds |
| `autodetect` | — | Sniffs the ATS at run time and delegates |

**To add a company:** `python -m ogjobs probe <careers-url> --test`. It prints a
ready config block and shows real job titles. That is how bp, Eni, Wood, ADNOC
and KBR were all solved.

---

## 5. Sources — current status

### Working (25 enabled)

| Source | Adapter | Matching |
|---|---|---:|
| KBR | phenom | 222 |
| Wood | oracle_orc | 220 |
| Aldelia | beehire | 204 |
| Q-Sourcing Servtec | zoho_recruit | 185 |
| Kintec Global | vennture | 136 |
| ADNOC | phenom | 119 |
| NES Fircroft | vennture | 87 |
| TrueNorth Africa | links | 61 |
| Saipem | ncore | 47 |
| QatarEnergy LNG | successfactors | 36 |
| WTS Energy | sitemap | 36 |
| TotalEnergies | links | 33 |
| Airswift | sitemap | 26 |
| Petrofac | links | 18 |
| SEAOWL Group | nicoka | 16 |
| Eni | oracle_orc | 14 |
| bp | workday | 9 |
| SBM Offshore | successfactors | 8 |
| Shell | workday | 6 |
| SPIE | rss | 5 |
| MODEC | links | 2 |
| ExxonMobil | successfactors | 2 |
| Brunel | autodetect | 2 |
| Subsea 7 | successfactors | 0 |
| Petroplan | autodetect | 0 |

**Note the shape of that table: the recruiters carry the regional volume, not
the supermajors.** Shell, bp and ExxonMobil contribute 17 matches between them.

### Disabled, with reasons

| Source | Why |
|---|---|
| **TechnipFMC** | Renders its job list entirely in the browser. Homepage, `/search/`, `/viewalljobs/` and the filtered URL all return zero job markup; no RSS, no sitemap, no API, consent cookie made no difference. Subsea 7 runs the same platform and *does* render server-side, so this is TechnipFMC's own configuration. |
| **UltiPro board (Hill)** | `robots.txt` says `Disallow: */JobBoardView`, the only endpoint holding the data. Deliberately not scraped. |
| **Kentz** | Company no longer exists; absorbed into SNC-Lavalin, now AtkinsRéalis (`careers.atkinsrealis.com`). |
| QatarEnergy, ALS, Aramco, PDO | Unreachable or blocked from the test environment. Probe from your own network. |
| Baker Hughes, SLB, Halliburton, Weatherford, Chevron, Equinor, McDermott, Orion Group, Sonangol | Never probed. Configured and ready to switch on. |

---

## 6. Deployment

**GitHub Actions** runs the scraper on GitHub's machines and commits the
result; **GitHub Pages** serves `docs/` as the public dashboard.

- Schedule: `cron: "10 */4 * * *"` — six runs a day at 00:10, 04:10, 08:10,
  12:10, 16:10, 20:10 UTC (05:10, 09:10, 13:10, 17:10, 21:10, 01:10 PKT).
- Manual: Actions tab → Run workflow, or the **Refresh jobs** button on the
  dashboard.
- A healthy run takes **20–30 minutes**. A run finishing in under a minute
  means something is wrong — see the cache trap below.
- A guard step fails the run if fewer than 1,000 adverts were read, so a
  silently empty scan shows red instead of false green.
- Public repo = unlimited Actions minutes, so the frequency costs nothing.
- GitHub disables scheduled workflows after 60 days of repo inactivity; the
  scan's own commits keep it alive.

**Mobile:** the Pages URL works on any phone (PC can be off). Alternatives are
`mobile.bat` over Wi-Fi with an access key, or copying `docs/index.html` to the
phone for offline use.

---

## 7. Traps and lessons — read before debugging

**Never commit `data/cache/`.** This cost a week of silent failure. Git
checkout stamps files with the *current* time, and the cache freshness test
compares that timestamp against its TTL — so a committed cache looks freshly
downloaded to every CI run, and the scraper answers the whole sweep from disk
without making a single request. Symptom: runs finish in 30 seconds and add
zero jobs. The workflow now passes `--fresh` so this cannot recur silently.

**A filter change only affects future scrapes** unless you run `refilter`.
Jobs rejected before the change were historically thrown away; that is why
Iraq stayed empty after Iraq was added. Now everything is stored, so
`refilter` is enough.

**An empty-state message is not evidence a site is dead.** Saipem's HTML shell
carries a stale "positions under maintenance" notice while the board is fully
live behind JavaScript. Check what the page *fetches*, not what it *says*.

**Per-source caps read newest-first**, so the back catalogue is never collected
by daily runs. `--deep 5` sweeps it. NES Fircroft throttles hard — its 585
pages took ~16 hours, against 5 minutes for Kintec's 286.

**Bugs found the hard way, all fixed:**
- Header keys lost case-insensitivity when converted to a plain dict, so gzip
  responses were never decompressed and pages came back as garbage.
- `adapters.py` never imported `json`; a broad `except Exception` turned the
  resulting error into a silent empty result. Handlers are now narrow.
- Iraq was missing from the country table entirely — every Iraqi job discarded.
- Bare "Congo" matched nothing; only city aliases were listed.
- `Bonnyville, Canada` matched `Bonny, Nigeria` via substring matching.
- Dutch and French `om,` matched Oman's ISO code. Two-letter codes now only
  count between commas, and never inside descriptions.
- SuccessFactors slug parsing took the first token, turning `Kuala Lumpur` into
  `Kuala` and `Port Harcourt` into `Port` — which would have hidden Nigerian
  jobs.
- The report was capped at 1,000 jobs while 1,205 matched; the rest vanished
  silently.
- The company picker listed internal ids (`saipem`) rather than names.

---

## 8. Open items

1. **Brunel** — 394 jobs sit in the page's embedded Next.js JSON, 12 per page,
   but pagination is unsolved (`?page=`, `?p=`, `?skip=`, `?offset=` and the
   `_next/data` route all return the same first 12). Currently yields ~12.
2. **Petroplan** — has never returned anything. Needs probing.
3. **QatarEnergy, ADNOC parent, ALS** — probe from your own network.
4. **Guyana** is not in `filters.json`, so MODEC's Guyana FPSO roles are
   filtered out. Add `"Guyana"` to `countries.include` if you want them.
5. **Monetisation idea** (discussed, not built): AdSense on a public job board
   is normally rejected as scraped content, and GitHub Pages forbids commercial
   sites. Would need original writing (country guides, rotation explainers,
   salary reality, scam warnings) plus a host such as Cloudflare Pages, and
   listings trimmed to snippet-plus-link for copyright.

---

## 9. Safety note carried on the dashboard

Every match links to the employer's own posting. In this market fake
"recruiters" charge fees for GCC and African placements. Legitimate employers
and licensed recruiters never ask a candidate for money for a job, a visa or
"medical processing".
