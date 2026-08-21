"""Command line interface: python -m ogjobs <command>"""
import argparse
import json
import os
import sys
import webbrowser

from . import adapters, geo
from .filters import Filters
from .http import Fetcher
from .pipeline import Runner, load_json


def cmd_run(args):
    r = Runner(verbose=not args.quiet)
    only = set(args.source or [])
    r.run(only=only or None, dry_run=args.dry_run, no_store=args.no_store)
    if not args.no_report:
        rows, paths = r.report(min_score=args.min_score)
        print("\nReport written:")
        for p in paths:
            print("   %s" % p)
        if args.open and rows:
            webbrowser.open("file://" + os.path.abspath(paths[0]))
    r.close()


def cmd_report(args):
    r = Runner(verbose=False)
    rows, paths = r.report(new_only=args.new, min_score=args.min_score,
                           source=args.source[0] if args.source else None,
                           country=args.country, limit=args.limit,
                           out_dir=args.out_dir, hosted_url=args.hosted_url,
                           index_name=args.index_name)
    print("%d job(s) in report" % len(rows))
    for p in paths:
        print("   %s" % p)
    for j in rows[:args.top]:
        print("\n  %3d  %s" % (j["score"], j["title"]))
        print("       %s | %s | %s" % (j["company"], j.get("location") or "?", j.get("posted") or ""))
        print("       %s" % j["url"])
    if args.open and rows:
        webbrowser.open("file://" + os.path.abspath(paths[0]))
    r.close()


def cmd_serve(args):
    from .server import serve
    serve(port=args.port, open_browser=not args.no_open,
          host=args.host, token=args.key)


def cmd_probe(args):
    """Work out which ATS a careers page uses and print a working config block."""
    f = Fetcher(cache_dir="data/cache", delay=1.0, respect_robots=not args.ignore_robots,
                verify_ssl=not args.insecure, cache_ttl=0)
    blocks = []
    for url in args.url:
        if not url.startswith("http"):
            url = "https://" + url
        print("\n>>> %s" % url)
        r = f.get(url)
        if not r.ok and not r.text:
            print("    unreachable (status %s) - check the URL in a browser" % r.status)
            continue
        print("    final URL : %s" % r.url)
        print("    status    : %s   size: %d chars" % (r.status, len(r.text)))

        hint = r.url
        for _, rx in adapters.FINGERPRINTS[:8]:
            m = rx.search(r.text)
            if m:
                hint = m.group(0)
                break
        cfg = adapters.derive_config(hint, r.text, {"id": args.id or _slug(url),
                                                    "company": args.company or _slug(url)})
        ats = cfg.pop("detected_ats", "unknown")
        print("    ATS       : %s -> adapter '%s'" % (ats, cfg.get("adapter")))
        cfg.setdefault("enabled", True)
        blocks.append(cfg)
        print("    config block:")
        print("\n".join("      " + l for l in json.dumps(cfg, indent=2).splitlines()))

        if args.test:
            print("    testing...")
            try:
                jobs = adapters.run_source(f, cfg)
            except Exception as e:
                print("    test failed: %s: %s" % (type(e).__name__, e))
                continue
            print("    -> %d job(s) returned" % len(jobs))
            for j in jobs[:5]:
                print("       - %s  |  %s" % (j.title[:60], (j.location or "?")[:35]))

    if blocks and args.append:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "config", "sources.json")
        data = load_json(path)
        have = {s.get("id") for s in data["sources"]}
        added = [b for b in blocks if b.get("id") not in have]
        data["sources"].extend(added)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        print("\nAppended %d source(s) to %s" % (len(added), path))


def _slug(url):
    host = url.split("//")[-1].split("/")[0]
    host = host.replace("www.", "").replace("careers.", "").replace("jobs.", "")
    return host.split(".")[0].lower()


def cmd_sources(args):
    r = Runner(verbose=False)
    print("%-3s %-16s %-28s %-16s %s" % ("", "ID", "COMPANY", "ADAPTER", "TARGET"))
    for s in r.sources:
        mark = "ON " if s.get("enabled", True) else "off"
        target = (s.get("careers_url") or s.get("base") or s.get("host")
                  or s.get("token") or s.get("company_id") or (s.get("urls") or [""])[0])
        print("%-3s %-16s %-28s %-16s %s" % (mark, s.get("id", "")[:16],
                                             (s.get("company") or "")[:28],
                                             s.get("adapter", "autodetect")[:16], str(target)[:52]))
    print("\n%d source(s); %d enabled" % (len(r.sources), len(r.pick())))
    r.close()


def cmd_enable(args):
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "config", "sources.json")
    data = load_json(path)
    want = set(args.id)
    n = 0
    for s in data["sources"]:
        if "all" in want or s.get("id") in want:
            s["enabled"] = not args.off
            n += 1
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    print("%s %d source(s)" % ("Disabled" if args.off else "Enabled", n))


def cmd_stats(args):
    r = Runner(verbose=False)
    s = r.store.stats()
    print("Tracked jobs : %d" % s["total"])
    print("Marked applied: %d" % s["applied"])
    print("Sources seen : %d" % s["sources"])
    rows = r.store.db.execute(
        "SELECT started, found, kept, new FROM runs ORDER BY id DESC LIMIT 8").fetchall()
    if rows:
        print("\nRecent runs:")
        print("  %-21s %8s %8s %6s" % ("STARTED", "SCRAPED", "MATCHED", "NEW"))
        for x in rows:
            print("  %-21s %8d %8d %6d" % (x["started"], x["found"] or 0, x["kept"] or 0, x["new"] or 0))
    top = r.store.db.execute(
        "SELECT countries, COUNT(*) n FROM jobs WHERE countries<>'' "
        "GROUP BY countries ORDER BY n DESC LIMIT 10").fetchall()
    if top:
        print("\nTop locations:")
        for t in top:
            print("  %-34s %d" % (t["countries"][:34], t["n"]))
    r.close()


def cmd_mark(args):
    r = Runner(verbose=False)
    r.store.mark(args.fingerprint, applied=args.applied, hidden=args.hide, notes=args.note)
    print("updated %s" % args.fingerprint)
    r.close()


def cmd_countries(args):
    for region, table in geo.COUNTRIES.items():
        print("\n%s" % region)
        for c in sorted(table):
            print("   %s" % c)


def cmd_test_filters(args):
    """Sanity-check the filter config against a made-up job."""
    from .models import Job
    fl = Filters(load_json(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "filters.json")))
    j = Job(source="test", company="Test", title=args.title, location=args.location,
            description=args.description or "").normalise()
    ok, reason = fl.evaluate(j)
    print("title    : %s" % j.title)
    print("location : %s" % j.location)
    print("countries: %s" % ", ".join(j.countries) or "-")
    print("regions  : %s" % ", ".join(j.regions) or "-")
    print("flags    : %s" % ", ".join(j.flags) or "-")
    print("score    : %d" % j.score)
    print("matched  : %s" % ", ".join(j.matched))
    print("VERDICT  : %s (%s)" % ("KEEP" if ok else "DROP", reason))


def build_parser():
    p = argparse.ArgumentParser(
        prog="ogjobs",
        description="Oil & gas job radar for the GCC and Africa. "
                    "Reads employers' own public career sites. No API keys, no cost.")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="scrape every enabled source and build the report")
    r.add_argument("--source", "-s", action="append", help="only this source id (repeatable)")
    r.add_argument("--min-score", type=int, default=None)
    r.add_argument("--dry-run", action="store_true", help="scrape but do not write to the database")
    r.add_argument("--no-store", action="store_true")
    r.add_argument("--no-report", action="store_true")
    r.add_argument("--open", action="store_true", help="open the HTML report when finished")
    r.add_argument("--quiet", "-q", action="store_true")
    r.set_defaults(func=cmd_run)

    rp = sub.add_parser("report", help="rebuild the report from stored jobs")
    rp.add_argument("--new", action="store_true", help="only jobs first seen in the latest run")
    rp.add_argument("--min-score", type=int, default=None)
    rp.add_argument("--source", "-s", action="append")
    rp.add_argument("--country", "-c")
    rp.add_argument("--limit", type=int, default=1000)
    rp.add_argument("--top", type=int, default=10, help="how many to print to the console")
    rp.add_argument("--open", action="store_true")
    rp.add_argument("--out-dir", help="write the report here instead of data/reports")
    rp.add_argument("--index-name", default="jobs.html",
                    help="file name for the HTML (use index.html for GitHub Pages)")
    rp.add_argument("--hosted-url",
                    help="GitHub Actions URL; adds a 'Refresh jobs' button for hosted pages")
    rp.set_defaults(func=cmd_report)

    sv = sub.add_parser("serve", help="open the live dashboard with a Scan now button")
    sv.add_argument("--port", type=int, default=8765)
    sv.add_argument("--no-open", action="store_true", help="do not launch the browser")
    sv.add_argument("--host", default="local",
                    help="'local' (this PC only, default) or 'lan' to let your "
                         "phone on the same Wi-Fi reach it")
    sv.add_argument("--key", help="fixed access key for --host lan "
                                  "(default: a new random one each start)")
    sv.set_defaults(func=cmd_serve)

    pr = sub.add_parser("probe", help="detect the ATS behind any careers URL and emit config")
    pr.add_argument("url", nargs="+")
    pr.add_argument("--id")
    pr.add_argument("--company")
    pr.add_argument("--test", action="store_true", help="immediately try scraping it")
    pr.add_argument("--append", action="store_true", help="append the result to config/sources.json")
    pr.add_argument("--ignore-robots", action="store_true")
    pr.add_argument("--insecure", action="store_true", help="skip TLS verification")
    pr.set_defaults(func=cmd_probe)

    sub.add_parser("sources", help="list configured sources").set_defaults(func=cmd_sources)

    en = sub.add_parser("enable", help="enable or disable sources by id ('all' works)")
    en.add_argument("id", nargs="+")
    en.add_argument("--off", action="store_true")
    en.set_defaults(func=cmd_enable)

    sub.add_parser("stats", help="database and run history").set_defaults(func=cmd_stats)
    sub.add_parser("countries", help="list recognised countries").set_defaults(func=cmd_countries)

    mk = sub.add_parser("mark", help="mark a job applied/hidden by fingerprint prefix")
    mk.add_argument("fingerprint")
    mk.add_argument("--applied", action="store_true")
    mk.add_argument("--hide", action="store_true")
    mk.add_argument("--note")
    mk.set_defaults(func=cmd_mark)

    tf = sub.add_parser("test-filters", help="check how a sample job scores")
    tf.add_argument("title")
    tf.add_argument("location")
    tf.add_argument("description", nargs="?")
    tf.set_defaults(func=cmd_test_filters)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
