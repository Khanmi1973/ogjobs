"""The single record type that flows through the whole pipeline."""
import hashlib
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

_NOISE = re.compile(r"[^a-z0-9 ]+")
_ROLE_NOISE = re.compile(
    r"\b(senior|snr|sr|junior|jr|lead|principal|chief|head of|i{1,3}|iv|v|"
    r"level\s*\d|grade\s*\d|\d{3,}|m/f/d|m/f|h/f|f/m|all genders)\b")


def _clean(s):
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


@dataclass
class Job:
    source: str = ""            # config id of the source, e.g. "shell"
    company: str = ""           # display name of the hiring company
    title: str = ""
    location: str = ""
    url: str = ""
    posted: str = ""            # ISO date if the site gives one
    description: str = ""
    department: str = ""
    contract_type: str = ""
    external_id: str = ""
    countries: list = field(default_factory=list)
    regions: list = field(default_factory=list)
    flags: list = field(default_factory=list)
    score: int = 0
    matched: list = field(default_factory=list)
    first_seen: str = ""
    last_seen: str = ""
    is_new: bool = False

    def normalise(self):
        self.title = _clean(self.title)
        self.company = _clean(self.company)
        self.location = _clean(self.location)
        self.department = _clean(self.department)
        self.url = (self.url or "").strip()
        self.description = _clean(self.description)[:8000]
        self.posted = normalise_date(self.posted)
        return self

    @property
    def fingerprint(self):
        """Stable identity so the same role from two sources collapses to one row."""
        t = _ROLE_NOISE.sub(" ", _NOISE.sub(" ", (self.title or "").lower()))
        t = re.sub(r"\s+", " ", t).strip()
        loc = _NOISE.sub(" ", (self.countries[0] if self.countries else self.location or "").lower())
        loc = re.sub(r"\s+", " ", loc).strip()
        co = _NOISE.sub(" ", (self.company or self.source or "").lower()).strip()
        basis = "|".join([co, t, loc]) if t else (self.url or "")
        return hashlib.sha1(basis.encode("utf-8")).hexdigest()

    def to_row(self):
        d = asdict(self)
        for k in ("countries", "regions", "flags", "matched"):
            d[k] = ", ".join(d[k] or [])
        d["is_new"] = 1 if d["is_new"] else 0
        return d


_DATE_PATTERNS = [
    ("%Y-%m-%dT%H:%M:%S", 19), ("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d", 10),
    ("%d/%m/%Y", 10), ("%m/%d/%Y", 10), ("%d-%m-%Y", 10), ("%d %b %Y", 11),
    ("%d %B %Y", 20), ("%b %d, %Y", 12), ("%B %d, %Y", 20),
]


def normalise_date(value):
    """Best-effort date normalisation to YYYY-MM-DD. Returns '' when unknown."""
    if not value:
        return ""
    if isinstance(value, (int, float)):
        try:
            ts = float(value)
            if ts > 1e11:          # milliseconds
                ts /= 1000.0
            return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")
        except Exception:
            return ""
    s = str(value).strip()
    if not s:
        return ""

    # Relative phrasing used by Workday and friends: "Posted 3 Days Ago".
    m = re.search(r"(\d+)\+?\s*(day|week|month|hour)s?\s*ago", s, re.I)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        days = {"hour": 0, "day": 1, "week": 7, "month": 30}[unit] * n
        from datetime import timedelta
        return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    if re.search(r"today|just posted", s, re.I):
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if re.search(r"yesterday", s, re.I):
        from datetime import timedelta
        return (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    s2 = s.replace("Z", "").split("+")[0].strip()
    for fmt, ln in _DATE_PATTERNS:
        try:
            return datetime.strptime(s2[:ln], fmt).strftime("%Y-%m-%d")
        except Exception:
            continue
    m = re.search(r"(20\d{2})-(\d{2})-(\d{2})", s)
    return "%s-%s-%s" % m.groups() if m else ""


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
