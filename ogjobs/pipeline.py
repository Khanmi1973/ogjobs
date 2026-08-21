"""Orchestration: read config, run every source, filter, store, report."""
import json
import os
import time
import traceback

from . import adapters, report
from .filters import Filters
from .http import Fetcher
from .models import now_iso
from .store import Store

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_json(path, default=None):
    if not os.path.exists(path):
        if default is not None:
            return default
        raise SystemExit("missing config file: %s" % path)
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


class Runner:
    def __init__(self, config_dir=None, data_dir=None, verbose=True, fresh=False):
        self.config_dir = config_dir or os.path.join(HERE, "config")
        self.data_dir = data_dir or os.path.join(HERE, "data")
        self.verbose = verbose

        self.settings = load_json(os.path.join(self.config_dir, "settings.json"), {})
        self.sources = load_json(os.path.join(self.config_dir, "sources.json"))["sources"]
        self.filters = Filters(load_json(os.path.join(self.config_dir, "filters.json")))

        net = self.settings.get("network", {})
        self.fetcher = Fetcher(
            cache_dir=os.path.join(self.data_dir, "cache"),
            delay=float(net.get("delay_seconds", 1.5)),
            timeout=int(net.get("timeout_seconds", 30)),
            respect_robots=bool(net.get("respect_robots", True)),
            verify_ssl=bool(net.get("verify_ssl", True)),
            cache_ttl=int(net.get("cache_ttl_seconds", 900)),
            max_retries=int(net.get("max_retries", 2)),
            verbose=verbose,
        )
        # "Scan fresh" from the dashboard bypasses the HTTP cache entirely.
        self.fetcher.force_fresh = bool(fresh)
        # A source may declare "insecure_hosts" when its portal serves a broken
        # certificate chain; the exception stays scoped to those hosts.
        for s in self.sources:
            for h in (s.get("insecure_hosts") or []):
                self.fetcher.insecure_hosts.add(str(h).lower())
        self.store = Store(os.path.join(self.data_dir, "jobs.db"))

    # ------------------------------------------------------------------

    def pick(self, only=None, skip_disabled=True):
        out = []
        for s in self.sources:
            if skip_disabled and not s.get("enabled", True):
                continue
            if only and s.get("id") not in only and s.get("company", "") not in only:
                continue
            out.append(s)
        return out

    def run(self, only=None, dry_run=False, no_store=False, progress=None):
        """Scrape the selected sources.

        ``progress`` is an optional callable receiving dict events, so a UI
        (see server.py) can show what is happening while a scan runs.
        """
        def emit(**event):
            if progress:
                try:
                    progress(event)
                except Exception:
                    pass

        started = now_iso()
        chosen = self.pick(only)
        if not chosen:
            print("No sources selected. Check config/sources.json (enabled flags) or --source id.")
            emit(type="done", found=0, kept=0, new=0, errors=["no sources selected"])
            return []
        emit(type="start", total=len(chosen), started=started)

        print("=" * 74)
        print("ogjobs run  %s   %d source(s)" % (started, len(chosen)))
        print("=" * 74)

        all_kept, total_found, total_new, errors = [], 0, 0, []
        for i, cfg in enumerate(chosen, 1):
            label = cfg.get("company") or cfg.get("id")
            print("\n[%d/%d] %s  (%s)" % (i, len(chosen), label, cfg.get("adapter", "autodetect")))
            emit(type="source", index=i, total=len(chosen), id=cfg.get("id"),
                 company=label, adapter=cfg.get("adapter", "autodetect"))
            t0 = time.time()
            try:
                raw = adapters.run_source(self.fetcher, cfg) or []
            except Exception as e:
                msg = "%s: %s" % (type(e).__name__, e)
                errors.append("%s -> %s" % (cfg.get("id"), msg))
                print("      ERROR %s" % msg)
                emit(type="source_error", index=i, total=len(chosen),
                     id=cfg.get("id"), company=label, message=msg)
                if self.verbose and os.environ.get("OGJOBS_DEBUG"):
                    traceback.print_exc()
                continue

            kept, dropped, scanned = [], {}, []
            for job in raw:
                if not job.title or not job.url:
                    continue
                ok, reason = self.filters.evaluate(job)
                job.is_match = ok
                job.drop_reason = "" if ok else reason
                scanned.append(job)
                if ok:
                    kept.append(job)
                else:
                    dropped[reason.split(":")[0]] = dropped.get(reason.split(":")[0], 0) + 1

            new_here = 0
            if not (dry_run or no_store):
                # Store everything, matching or not: that is what lets
                # "ogjobs refilter" re-apply a changed filters.json instantly
                # instead of re-scraping every site.
                for job in scanned:
                    was_new = self.store.upsert(job)
                    if was_new and job.is_match:
                        new_here += 1
                self.store.db.commit()

            total_found += len(raw)
            total_new += new_here
            all_kept.extend(kept)
            top_drop = sorted(dropped.items(), key=lambda kv: -kv[1])[:2]
            print("      %d scraped -> %d match -> %d new   (%.1fs)%s"
                  % (len(raw), len(kept), new_here, time.time() - t0,
                     "   [" + "; ".join("%s x%d" % (k, v) for k, v in top_drop) + "]"
                     if top_drop else ""))
            for j in sorted(kept, key=lambda x: -x.score)[:3]:
                print("        %3d  %s  -  %s" % (j.score, j.title[:58], (j.location or "?")[:32]))
            emit(type="source_done", index=i, total=len(chosen), id=cfg.get("id"),
                 company=label, scraped=len(raw), matched=len(kept), new=new_here,
                 seconds=round(time.time() - t0, 1))

        if not (dry_run or no_store):
            self.store.record_run(started, total_found, len(all_kept), total_new,
                                  "; ".join(errors)[:900])

        print("\n" + "-" * 74)
        print("TOTAL: %d scraped, %d matched, %d new" % (total_found, len(all_kept), total_new))
        if errors:
            print("%d source(s) failed:" % len(errors))
            for e in errors:
                print("   - %s" % e)
        emit(type="done", found=total_found, kept=len(all_kept), new=total_new, errors=errors)
        return all_kept

    # ------------------------------------------------------------------

    def refilter(self, progress=None):
        """Re-apply config/filters.json to every stored job. No network.

        Scraping discards nothing, so widening the filters (adding a country,
        say) can be applied to jobs already collected instead of re-scraping
        every site.
        """
        from .models import Job

        rows = self.store.db.execute("SELECT * FROM jobs").fetchall()
        promoted, demoted, unchanged = 0, 0, 0
        for r in rows:
            job = Job(source=r["source"] or "", company=r["company"] or "",
                      title=r["title"] or "", location=r["location"] or "",
                      url=r["url"] or "", posted=r["posted"] or "",
                      description=r["description"] or "",
                      department=r["department"] or "",
                      contract_type=r["contract_type"] or "",
                      external_id=r["external_id"] or "")
            ok, reason = self.filters.evaluate(job)
            was = 1 if (r["is_match"] if r["is_match"] is not None else 1) else 0
            if ok and not was:
                promoted += 1
            elif was and not ok:
                demoted += 1
            else:
                unchanged += 1
            self.store.db.execute(
                "UPDATE jobs SET is_match=?, drop_reason=?, score=?, matched=?, "
                "countries=?, regions=?, flags=? WHERE fingerprint=?",
                (1 if ok else 0, "" if ok else reason, job.score,
                 ", ".join(job.matched), ", ".join(job.countries),
                 ", ".join(job.regions), ", ".join(job.flags), r["fingerprint"]))
        self.store.db.commit()
        return {"total": len(rows), "now_matching": promoted,
                "no_longer_matching": demoted, "unchanged": unchanged}

    def report(self, new_only=False, min_score=None, source=None, country=None,
               limit=1000, out_dir=None, hosted_url=None, index_name="jobs.html"):
        """Write the HTML/CSV/RSS report.

        ``out_dir`` overrides the default data/reports (GitHub Pages publishes
        from docs/). ``hosted_url`` turns the scan control into a link to the
        GitHub Actions page, since a static host cannot run the scraper itself.
        """
        out_dir = out_dir or os.path.join(self.data_dir, "reports")
        os.makedirs(out_dir, exist_ok=True)
        rows = self.store.query(min_score=min_score, source=source, country=country,
                                limit=limit, new_only=new_only)
        last = self.store.last_run_started()
        for r in rows:
            r["_new"] = bool(last and r.get("first_seen", "") >= last)
        meta = {"sources_run": len(self.pick()), "hosted_url": hosted_url}
        paths = [
            report.write_html(rows, os.path.join(out_dir, index_name), meta),
            report.write_csv(rows, os.path.join(out_dir, "jobs.csv")),
            report.write_rss(rows, os.path.join(out_dir, "jobs.xml")),
        ]
        return rows, paths

    def close(self):
        self.store.close()
