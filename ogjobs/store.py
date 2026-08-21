"""SQLite persistence.

Keeps history so every run can tell you what is genuinely new rather than
re-showing the same hundred adverts.
"""
import os
import sqlite3

from .models import now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    fingerprint   TEXT PRIMARY KEY,
    source        TEXT,
    company       TEXT,
    title         TEXT,
    location      TEXT,
    url           TEXT,
    posted        TEXT,
    description   TEXT,
    department    TEXT,
    contract_type TEXT,
    external_id   TEXT,
    countries     TEXT,
    regions       TEXT,
    flags         TEXT,
    score         INTEGER,
    matched       TEXT,
    first_seen    TEXT,
    last_seen     TEXT,
    applied       INTEGER DEFAULT 0,
    hidden        INTEGER DEFAULT 0,
    notes         TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_jobs_score  ON jobs(score DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_seen   ON jobs(first_seen DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);

CREATE TABLE IF NOT EXISTS runs (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    started   TEXT,
    finished  TEXT,
    found     INTEGER,
    kept      INTEGER,
    new       INTEGER,
    detail    TEXT
);
"""

FIELDS = ["fingerprint", "source", "company", "title", "location", "url", "posted",
          "description", "department", "contract_type", "external_id", "countries",
          "regions", "flags", "score", "matched", "first_seen", "last_seen"]


class Store:
    def __init__(self, path="data/jobs.db"):
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self.path = path
        # timeout: a scan running in another thread may hold a write lock.
        self.db = sqlite3.connect(path, timeout=20)
        self.db.row_factory = sqlite3.Row
        # WAL lets the dashboard read while a scan is still writing.
        try:
            self.db.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error:
            pass
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self):
        self.db.commit()
        self.db.close()

    # ---- writes --------------------------------------------------------

    def upsert(self, job):
        """Insert or refresh a job. Returns True when it is new to us."""
        fp = job.fingerprint
        stamp = now_iso()
        row = self.db.execute("SELECT first_seen FROM jobs WHERE fingerprint=?", (fp,)).fetchone()
        is_new = row is None
        job.first_seen = row["first_seen"] if row else stamp
        job.last_seen = stamp
        job.is_new = is_new

        data = job.to_row()
        data["fingerprint"] = fp
        values = [data.get(k, "") for k in FIELDS]
        placeholders = ",".join(["?"] * len(FIELDS))
        if is_new:
            self.db.execute("INSERT INTO jobs (%s) VALUES (%s)" % (",".join(FIELDS), placeholders),
                            values)
        else:
            sets = ",".join(["%s=?" % k for k in FIELDS if k != "fingerprint"])
            self.db.execute("UPDATE jobs SET %s WHERE fingerprint=?" % sets,
                            [data.get(k, "") for k in FIELDS if k != "fingerprint"] + [fp])
        return is_new

    def record_run(self, started, found, kept, new, detail=""):
        self.db.execute(
            "INSERT INTO runs (started, finished, found, kept, new, detail) VALUES (?,?,?,?,?,?)",
            (started, now_iso(), found, kept, new, detail))
        self.db.commit()

    def mark(self, fingerprint, applied=None, hidden=None, notes=None):
        if applied is not None:
            self.db.execute("UPDATE jobs SET applied=? WHERE fingerprint LIKE ?",
                            (1 if applied else 0, fingerprint + "%"))
        if hidden is not None:
            self.db.execute("UPDATE jobs SET hidden=? WHERE fingerprint LIKE ?",
                            (1 if hidden else 0, fingerprint + "%"))
        if notes is not None:
            self.db.execute("UPDATE jobs SET notes=? WHERE fingerprint LIKE ?",
                            (notes, fingerprint + "%"))
        self.db.commit()

    # ---- reads ---------------------------------------------------------

    def query(self, since=None, min_score=None, source=None, country=None,
              include_hidden=False, limit=1000, new_only=False):
        sql = "SELECT * FROM jobs WHERE 1=1"
        args = []
        if not include_hidden:
            sql += " AND hidden=0"
        if since:
            sql += " AND last_seen >= ?"
            args.append(since)
        if new_only:
            sql += " AND first_seen >= (SELECT COALESCE(MAX(started),'') FROM runs)"
        if min_score is not None:
            sql += " AND score >= ?"
            args.append(min_score)
        if source:
            sql += " AND source = ?"
            args.append(source)
        if country:
            sql += " AND countries LIKE ?"
            args.append("%" + country + "%")
        sql += " ORDER BY score DESC, COALESCE(NULLIF(posted,''),first_seen) DESC LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def last_run_started(self):
        row = self.db.execute("SELECT started FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        return row["started"] if row else None

    def stats(self):
        row = self.db.execute(
            "SELECT COUNT(*) n, SUM(applied) applied, COUNT(DISTINCT source) srcs FROM jobs"
        ).fetchone()
        return {"total": row["n"] or 0, "applied": row["applied"] or 0, "sources": row["srcs"] or 0}
